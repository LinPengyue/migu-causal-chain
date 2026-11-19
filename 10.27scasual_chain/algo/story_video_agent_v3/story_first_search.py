"""Run Story-First for the initial edit and expose unverified proposals to Planner."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace

from .story_first_evidence_adapter import _read_artifact, read_story_first_observation_branch
from .story_first_hypotheses import (
    adjacent_story_anchor_pairs, build_observation_plan, model_messages,
    parse_hypotheses, prepare_story_input,
)
from .story_first_poc_cli import configured_flash_model_id, parse_model_json, write_json
from .story_paid_eval import _call_audit_from_raw, provider_usage


def story_first_calls_left(api):
    if api is None or api.max_calls is None or api.max_cost_usd is None:
        return 0
    usage = provider_usage(api)
    if getattr(api, "_output_budget_exceeded", False) or (
        float(usage.get("est_cost_usd_real") or 0) >= api.max_cost_usd
    ):
        return 0
    return max(0, api.max_calls - int(usage.get("http_attempts") or 0))


def _query(api, cfg, messages, directory, stage):
    write_json(directory / f"{stage}_request.json", messages)
    raw = api.chat(
        role="planner", config_override=cfg, stats_role=f"story_first_{stage}",
        messages=messages, temperature=0.0, allow_degraded_fallback=False,
    )
    content = str(raw.get("content") or "")
    (directory / f"{stage}_response.txt").write_text(content, encoding="utf-8")
    write_json(directory / f"{stage}_usage.json", _call_audit_from_raw(raw))
    if raw.get("provider_mode") not in ("real", "openai_compatible") or (
        str(raw.get("finish_reason") or "").lower() in ("length", "content_filter")
    ):
        raise ValueError(f"invalid_or_truncated_story_first_{stage}_response")
    return parse_model_json(content)


def _proposals(prepared, hypotheses, interval_id):
    """Preserve generator order and pass only generator data to Planner."""
    inventory = {row["event_id"]: row for row in prepared["event_inventory"]}
    annotations = prepared.get("event_annotations") or {}
    for h in hypotheses:
        hid = h["hypothesis_id"]
        refs = dict.fromkeys(h["supporting_event_ids"])
        for relation in h["proposed_long_range_relations"]:
            refs[relation["source_event_id"]] = None
            refs[relation["target_event_id"]] = None
        yield {
            "proposal_id": f"{interval_id}:{hid}",
            "scope": prepared["scope"],
            "evidence_status": "UNVERIFIED",
            "summary": h["narrative_summary"],
            "expected_story_contribution": h.get("expected_story_contribution"),
            "events": [
                {k: inventory[eid].get(k) for k in (
                    "event_id", "source_pts_sec", "event_type", "known_replay_or_slowmo",
                )} | {"annotation": annotations.get(eid) or None}
                for eid in sorted(refs, key=lambda eid: inventory[eid]["source_pts_sec"])
            ],
            "relations": [
                {"relation_id": f"r{i}", **rel}
                for i, rel in enumerate(h["proposed_long_range_relations"], 1)
            ],
            "falsification_conditions": h["falsification_conditions"],
            "observation_queries": h["observation_queries"],
        }


def discover_story_first(*, edl, story_plan, events, source_sha, out_dir,
                         api=None, artifacts_dir=None, reserve_calls=3,
                         data_tier="RAW_EVENT_DERIVED", revision_context=None):
    """Generate proposals from adjacent anchors; keep scoring in offline research.

    The former runtime scorer call is commented below for reference.
    """
    pairs = adjacent_story_anchor_pairs(edl)
    interval_width = max(2, len(str(len(pairs))))
    intervals = []
    proposals = []
    cfg = None
    model_config_error = None
    if api is not None:
        try:
            planner = api.configs["planner"]
            token_param = (os.environ.get("STORY_FIRST_TOKEN_PARAM") or planner.token_param).strip()
            if token_param not in ("max_tokens", "max_completion_tokens"):
                raise ValueError("invalid_or_uncapped_story_first_token_parameter")
            cfg = replace(
                planner, model=configured_flash_model_id(), token_param=token_param,
                max_retries=0, request_profile="default", stream=False,
                thinking_object_disabled=True, send_thinking_params=False,
                enable_thinking=None, thinking_budget=None,
            )
        except ValueError as exc:
            model_config_error = str(exc)
    for i, (left, right) in enumerate(pairs, 1):
        interval_id = f"interval_{i:0{interval_width}d}"
        entry = {"interval_id": interval_id, "from_segment_id": left,
                 "to_segment_id": right, "score_status": "OFFLINE_RESEARCH_ONLY"}
        intervals.append(entry)
        directory = out_dir / interval_id
        directory.mkdir(parents=True, exist_ok=True)
        try:
            prepared = prepare_story_input(
                edl, events, story_plan=story_plan, from_segment_id=left, to_segment_id=right,
            )
            prepared["data_tier"] = data_tier
            if revision_context is not None:
                prepared["revision_context"] = revision_context
        except ValueError as exc:
            entry.update(status="INVALID_INTERVAL", reason=str(exc))
            continue
        entry["scope"] = prepared["scope"]
        prepared_path = directory / "prepared_story_input.json"
        write_json(prepared_path, prepared)
        cached = artifacts_dir / interval_id if artifacts_dir is not None else None
        if cached is not None and not cached.is_dir():
            cached = artifacts_dir
        if cached is not None and (cached / "01_generate_max5").is_dir():
            cached = cached / "01_generate_max5"
        if cached is not None and (cached / "prepared_story_input.json").is_file():
            try:
                saved = _read_artifact(cached, "prepared_story_input.json")
                if saved.get("scope") == prepared["scope"]:
                    imported = read_story_first_observation_branch(
                        artifacts_dir=cached, current_edl=edl, current_story_plan=story_plan,
                        permitted_events=events, current_source_sha256=source_sha,
                        rebuild_missing_observation_plan=True, include_ranking=False,
                    )
                    entry["artifact_status"] = imported["status"]
                    if imported["status"] != "REJECTED_NO_PROMOTION":
                        items = imported["hypotheses"]
                        provenance = {
                            name: hashlib.sha256((cached / name).read_bytes()).hexdigest()
                            for name in ("prepared_story_input.json", "story_hypotheses.json")
                        }
                        entry.update(status="REUSED", reused_from=str(cached),
                                     candidate_count=len(items), artifact_sha256=provenance)
                        proposals.extend(_proposals(prepared, items, interval_id))
                        write_json(directory / "imported_evidence.json", imported)
                        write_json(directory / "story_hypotheses.json",
                                   _read_artifact(cached, "story_hypotheses.json"))
                        continue
                    entry["artifact_error"] = imported["reason"]
            except (OSError, ValueError) as exc:
                entry["artifact_error"] = str(exc)
        if len(prepared["event_inventory"]) < 2:
            entry.update(status="INSUFFICIENT_EVENTS", candidate_count=0)
            continue
        generation = model_messages(prepared)
        if cfg is None or story_first_calls_left(api) <= reserve_calls:
            write_json(directory / "generator_request.json", generation)
            status = ("MODEL_CONFIG_MISSING" if model_config_error else
                      "PREPARED_ONLY" if api is None else "DEFERRED_FOR_BUDGET")
            entry.update(status=status, reason=model_config_error)
            continue
        try:
            raw = _query(api, cfg, generation, directory, "generator")
            valid = parse_hypotheses(raw, prepared)
        except Exception as exc:
            entry.update(status="GENERATION_FAILED", reason=f"{type(exc).__name__}:{exc}")
            continue
        write_json(directory / "story_hypotheses.json", valid)
        write_json(directory / "observation_plan.json", build_observation_plan(prepared, valid))
        items = valid["hypotheses"]
        entry.update(status="GENERATED" if items else "NO_VALID_HYPOTHESES",
                     candidate_count=len(items))
        proposals.extend(_proposals(prepared, items, interval_id))
    result = {
        "source_sha256": source_sha,
        "initial_edl_sha256": hashlib.sha256(
            json.dumps(edl, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
        "intervals": intervals, "proposals": proposals,
    }
    if artifacts_dir is not None and source_sha:
        from .story_first_revision import replace_replay_proposals, story_first_proposals_sha256

        try:
            prior = _read_artifact(artifacts_dir, "story_first_pool.json")
            if all(prior.get(k) == result[k] for k in ("source_sha256", "initial_edl_sha256")):
                history = []
                if prior.get("replay_base_proposals_sha256") == story_first_proposals_sha256(proposals):
                    history = prior.get("replay_revision_history") or []
                elif not prior.get("replay_revision_history") and prior.get("proposals") == proposals:
                    # Reuse the recorded P2 rejection when starting from a pre-repair run.
                    record = _read_artifact(artifacts_dir.parent / "02_round_01", "story_first_trial.json")
                    history = [record]
                for record in history:
                    replace_replay_proposals(result, record["trial"], record["review"], events)
        except (OSError, ValueError, KeyError, TypeError):
            # A generation-only archive has no P2 result to restore.
            pass
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "story_first_pool.json", result)
    return result


# Previous in-loop scoring block, retained for future offline experiments.
# from .story_first_a_ranker import SCHEMA as RANKING_SCHEMA
# from .story_first_a_ranker import build_score_messages, rank_model_evaluations
# def _record_causal_scores(entry, directory, prepared, valid, api, cfg, reserve_calls):
#     score_dir = directory / "scheme_a_ranking"
#     score_dir.mkdir(exist_ok=True)
#     score_request = build_score_messages(prepared, valid)
#     write_json(score_dir / "score_model_input.json", {
#         "messages": score_request,
#         "source_prepared_sha256": hashlib.sha256(
#             (directory / "prepared_story_input.json").read_bytes()
#         ).hexdigest(),
#         "source_hypotheses_sha256": hashlib.sha256(
#             (directory / "story_hypotheses.json").read_bytes()
#         ).hexdigest(),
#     })
#     scored = {
#         "schema": RANKING_SCHEMA,
#         "status": "AWAITING_SCORING_MODEL", "ranked_hypotheses": [],
#         "selected_for_video_observation": [],
#     }
#     entry["score_status"] = "PREPARED_ONLY_ZERO_HTTP"
#     if story_first_calls_left(api) > reserve_calls:
#         try:
#             scored = rank_model_evaluations(
#                 _query(api, cfg, score_request, score_dir, "scorer"), valid,
#             )
#             entry["score_status"] = "REAL_MODEL_PRIOR_NOT_VIDEO_VERIFIED"
#         except Exception as exc:
#             entry["score_error"] = f"{type(exc).__name__}:{exc}"
#     write_json(score_dir / "scheme_a_story_ranking.json", scored)
#     write_json(score_dir / "scheme_a_audit.json", {
#         "schema": RANKING_SCHEMA, "status": entry["score_status"],
#     })
