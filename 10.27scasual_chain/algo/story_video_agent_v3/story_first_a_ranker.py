"""Story-First Scheme A: independent LLM whole-story scoring, Stage 2 only.

Consumes valid Stage-1 candidates and the same immutable story/event context.
A high model score is ONLY a video-observation priority, never causal proof,
FIRST_LIVE evidence, Planner authorization, or measured narrative improvement.
Default: zero HTTP. Compatible with Python 3.9.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .story_first_hypotheses import parse_hypotheses
from .story_first_poc_cli import (
    build_shared_story_first_provider,
    parse_model_json,
    write_json,
)

SCHEMA = "v2_story_first_scheme_a_whole_story_prior_v1"
_AXES = ("anchor_fit", "internal_coherence", "joint_composition",
         "marginal_narrative_gain", "event_grounding")
_WORDS = ("new_story_information", "comparison_to_existing_story",
          "major_uncertainty")


def _read(path: Path) -> Dict[str, Any]:
    if not path.is_file() or path.stat().st_size > 10_000_000:
        raise ValueError("missing_or_oversized_input:" + path.name)
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("input_is_not_json_object:" + path.name)
    return doc


def build_score_messages(prepared: Mapping[str, Any],
                         validated: Mapping[str, Any]) -> List[Dict[str, str]]:
    """One independent evaluation pass over candidate event COMBINATIONS."""
    candidates = validated.get("hypotheses") or []
    inventory = {str(x["event_id"]): x
                 for x in prepared.get("event_inventory") or []}
    rich = {str(x["event_id"]): x for x in prepared.get("events") or []}
    target_ids = {str(eid) for h in candidates
                  for eid in h.get("supporting_event_ids") or []}
    for h in candidates:
        for rel in h.get("proposed_long_range_relations") or []:
            target_ids.add(str(rel["source_event_id"]))
            target_ids.add(str(rel["target_event_id"]))
    event_context = []
    for eid in sorted(target_ids):
        if eid not in inventory:
            raise ValueError("candidate_event_id_not_in_inventory:" + eid)
        item = inventory[eid]
        detail = rich.get(eid) or {}
        event_context.append({
            "event_id": eid,
            "source_pts_sec": item["source_pts_sec"],
            "type": item.get("event_type"),
            "label": item.get("comment_label"),
            "description": detail.get("description"),
            "known_replay_or_slowmo": item.get("known_replay_or_slowmo"),
        })
    compact = []
    for h in candidates:
        compact.append({
            "hypothesis_id": h["hypothesis_id"],
            "narrative_summary": h["narrative_summary"],
            "supporting_event_ids": h["supporting_event_ids"],
            "relations_are_hypotheses": h["proposed_long_range_relations"],
            "falsification_conditions": h["falsification_conditions"],
            "expected_story_contribution": h.get("expected_story_contribution"),
        })
    system = (
        "You are an INDEPENDENT football story assessor, not the candidate generator. "
        "Given a frozen V3-R story, two existing story anchors, and real event IDs, "
        "score each proposed MULTI-EVENT story AS A WHOLE, not by summing per-event relevance. "
        "Use only supplied event facts; event order, substitutions and commentary DO NOT prove "
        "causality, player intentions or tactical changes. Replay-labelled events cannot be "
        "promoted to source footage. No video has been watched. Score cautiously on 0..4 "
        "ordinal scales (0=no support; 4=strong event-level justification, NOT verified). "
        "Assess anchor_fit, internal_coherence, joint_composition "
        "(whole more useful than isolated events), marginal_narrative_gain "
        "(nonredundant information compared with existing story), event_grounding. "
        "In scoring marginal gain, prefer 0 if the current story already covers the point. "
        "Never invent event IDs, source times, frames, or observations. "
        "Return ONE JSON object exactly {evaluations:[{hypothesis_id,anchor_fit,"
        "internal_coherence,joint_composition,marginal_narrative_gain,event_grounding,"
        "cited_event_ids,new_story_information,comparison_to_existing_story,"
        "major_uncertainty}]}. All five scores are INTEGERS 0..4. "
        "cited_event_ids must be a nonempty subset of that hypothesis's event IDs. "
        "Return one evaluation per candidate, including bad ones. "
        "No EDL edits, causal certification, video evidence or final decision."
    )
    user = {
        "story_scope": prepared["scope"],
        "frozen_story_plan": prepared.get("story_plan_reference"),
        "event_context": event_context,
        "candidate_stories": compact,
        "evaluation_is_unverified_prior": True,
    }
    return [{"role": "system", "content": system},
            {"role": "user", "content": json.dumps(
                user, ensure_ascii=False, separators=(",", ":"))}]


def rank_model_evaluations(score_json: Mapping[str, Any],
                           validated: Mapping[str, Any],
                           *, top_k: int = 2) -> Dict[str, Any]:
    """Strict structural gate. Does not claim factual/causal correctness."""
    if not 1 <= top_k <= 5:
        raise ValueError("top_k_out_of_range")
    candidates = {str(h["hypothesis_id"]): h
                  for h in validated.get("hypotheses") or []}
    evaluations = score_json.get("evaluations")
    if not isinstance(evaluations, list):
        raise ValueError("evaluations_must_be_array")
    if len(evaluations) != len(candidates):
        raise ValueError("evaluation_count_mismatch")
    ranked = []
    seen = set()
    for item in evaluations:
        if not isinstance(item, Mapping):
            raise ValueError("evaluation_must_be_object")
        hid = str(item.get("hypothesis_id") or "")
        if hid not in candidates or hid in seen:
            raise ValueError("duplicate_or_unknown_hypothesis_id:" + hid)
        seen.add(hid)
        for axis in _AXES:
            score = item.get(axis)
            if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 4:
                raise ValueError("invalid_ordinal_score:" + axis)
        for key in _WORDS:
            value = item.get(key)
            if not isinstance(value, str) or not value.strip() or len(value) > 600:
                raise ValueError("missing_or_oversized_reason:" + key)
        cited = item.get("cited_event_ids")
        support = set(str(e) for e in candidates[hid]["supporting_event_ids"])
        if (not isinstance(cited, list) or not cited
                or len(set(map(str, cited))) != len(cited)
                or any(str(e) not in support for e in cited)):
            raise ValueError("cited_events_unbound_to_candidate:" + hid)
        # The ranking is a non-calibrated, bounded QUEUE PRIOR only.
        structural = (item["anchor_fit"] + item["internal_coherence"]
                      + item["joint_composition"]) / 12.0
        gain = item["marginal_narrative_gain"] / 4.0
        grounding = item["event_grounding"] / 4.0
        multi_event = len(support) >= 2
        priority = round(0.45 * structural + 0.40 * gain + 0.15 * grounding, 4)
        ranked.append({
            "multi_event_combination": multi_event,
            "hypothesis_id": hid,
            "story_summary": candidates[hid]["narrative_summary"],
            "supporting_event_ids": candidates[hid]["supporting_event_ids"],
            "scores": {axis: item[axis] for axis in _AXES},
            "cited_event_ids": [str(e) for e in cited],
            "model_priority_0_to_1": priority,
            "structural_prior": round(structural, 4),
            "marginal_gain_prior": round(gain, 4),
            "event_grounding_prior": round(grounding, 4),
            "new_story_information": item["new_story_information"],
            "comparison_to_existing_story": item["comparison_to_existing_story"],
            "major_uncertainty": item["major_uncertainty"],
            "requires_video_evidence": True,
            "causal_link_verified": False,
            "narrative_gain_verified": False,
            "first_live_certified": False,
            "planner_eligible": False,
        })
    ranked.sort(key=lambda x: (-x["model_priority_0_to_1"], x["hypothesis_id"]))
    # Scheme A ranks EVENT COMBINATIONS. Legacy single-event hypotheses stay
    # auditable but are not a whole-story observation candidate.
    selected = [x["hypothesis_id"] for x in ranked
                if x["multi_event_combination"]][:top_k]
    return {
        "schema": SCHEMA,
        "status": "RANKED_FOR_OBSERVATION_ONLY" if ranked else "NO_CANDIDATES",
        "ranked_hypotheses": ranked,
        "selected_for_video_observation": selected,
        "top_k": top_k,
        "ranking_is_model_prior_not_calibrated": True,
        "video_observed": False,
        "causal_claims_verified": 0,
        "narrative_gain_verified": False,
        "first_live_certified": False,
        "planner_candidates": [],
        "edl_modified": False,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Story-First v2 Scheme A whole-story ranker")
    p.add_argument("--prepared-story-input", required=True, type=Path)
    p.add_argument("--story-hypotheses", required=True, type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--fixture-score-json", type=Path)
    p.add_argument("--top-k", type=int, default=2)
    p.add_argument("--enable-real-api", action="store_true")
    p.add_argument("--i-approve-budget", action="store_true")
    p.add_argument("--max-cost-usd", type=float, default=0.05)
    p.add_argument("--max-completion-tokens", type=int, default=2200)
    p.add_argument("--measured-input-tokens", type=int)
    p.add_argument("--verified-context-window-tokens", type=int)
    args = p.parse_args(argv)
    if args.enable_real_api and not (
        args.i_approve_budget and os.environ.get("STORY_API_ENABLE") == "1"
    ):
        p.error("paid mode requires BOTH approval flags and STORY_API_ENABLE=1")
    if args.enable_real_api and args.fixture_score_json:
        p.error("real API and fixture cannot be combined")
    if not 1 <= args.top_k <= 5 or not 0 < args.max_cost_usd <= 0.10:
        p.error("invalid rank or cost cap")
    if not 128 <= args.max_completion_tokens <= 3200:
        p.error("invalid output token cap")
    if args.enable_real_api and not (
        args.measured_input_tokens and args.verified_context_window_tokens
        and args.measured_input_tokens + args.max_completion_tokens
            <= args.verified_context_window_tokens
    ):
        p.error("paid mode needs provider-confirmed token capacity and measured input")
    if args.out_dir.exists() and (
        not args.out_dir.is_dir() or any(args.out_dir.iterdir())
    ):
        p.error("out-dir must be new/empty; do not overwrite historical runs")
    audit: Dict[str, Any] = {
        "schema": SCHEMA, "status": "FAILED_NO_PROMOTION",
        "http_attempts": 0, "edl_modified": False,
        "first_live_certified": False, "planner_candidates": 0,
    }
    try:
        prepared = _read(args.prepared_story_input)
        stored = _read(args.story_hypotheses)
        # Revalidate old candidates; the ranker never reinterprets failed output.
        validated = parse_hypotheses(
            {"hypotheses": stored.get("hypotheses") or []},
            prepared, max_hypotheses=5,
        )
        if validated.get("rejected"):
            raise ValueError("stage1_hypotheses_failed_revalidation")
        messages = build_score_messages(prepared, validated)
        args.out_dir.mkdir(parents=True, exist_ok=True)
        write_json(args.out_dir / "score_model_input.json", {
            "messages": messages, "source_prepared_sha256": hashlib.sha256(
                args.prepared_story_input.read_bytes()).hexdigest(),
            "source_hypotheses_sha256": hashlib.sha256(
                args.story_hypotheses.read_bytes()).hexdigest(),
            "no_video_observed": True,
        })
        if not validated["hypotheses"]:
            ranked = rank_model_evaluations(
                {"evaluations": []}, validated, top_k=args.top_k)
            audit["status"] = "NO_STAGE1_CANDIDATES"
        elif args.fixture_score_json:
            ranked = rank_model_evaluations(
                _read(args.fixture_score_json), validated, top_k=args.top_k)
            audit["status"] = "OFFLINE_FIXTURE_NOT_REAL_LLM"
        elif args.enable_real_api:
            from .story_paid_eval import provider_usage
            api, preflight = build_shared_story_first_provider(
                max_cost_usd=args.max_cost_usd,
                max_completion_tokens=args.max_completion_tokens,
            )
            audit["api_preflight"] = preflight
            try:
                raw = api.chat(
                    role="planner", messages=messages, temperature=0.0,
                    allow_degraded_fallback=False,
                )
            finally:
                usage = provider_usage(api)
                audit["http_attempts"] = int(usage.get("http_attempts") or 0)
                audit["usage"] = {
                    k: usage.get(k) for k in (
                        "http_attempts", "prompt_tokens", "completion_tokens",
                        "est_cost_usd_real")
                }
            content = str(raw.get("content") or "")
            (args.out_dir / "llm_raw_response.txt").write_text(
                content, encoding="utf-8")
            audit["finish_reason"] = raw.get("finish_reason")
            if (str(raw.get("provider_mode")) != "real"
                    or str(raw.get("finish_reason") or "").lower()
                        in ("length", "content_filter")):
                raise ValueError("real_model_response_invalid_or_truncated")
            ranked = rank_model_evaluations(
                parse_model_json(content), validated, top_k=args.top_k)
            audit["status"] = "REAL_MODEL_PRIOR_NOT_VIDEO_VERIFIED"
        else:
            ranked = {
                "schema": SCHEMA, "status": "AWAITING_SCORING_MODEL",
                "ranked_hypotheses": [],
                "selected_for_video_observation": [],
                "planner_candidates": [],
                "edl_modified": False, "video_observed": False,
            }
            audit["status"] = "PREPARED_ONLY_ZERO_HTTP"
        write_json(args.out_dir / "scheme_a_story_ranking.json", ranked)
        audit["candidate_count"] = len(validated["hypotheses"])
        audit["selected_for_video_observation"] = (
            ranked["selected_for_video_observation"])
        write_json(args.out_dir / "scheme_a_audit.json", audit)
        print(json.dumps({
            "status": audit["status"],
            "selected": audit["selected_for_video_observation"],
            "http_attempts": audit["http_attempts"],
        }, ensure_ascii=False))
        return 0
    except Exception as exc:
        audit["error"] = "%s:%s" % (type(exc).__name__, str(exc)[:300])
        if args.out_dir.is_dir():
            write_json(args.out_dir / "scheme_a_audit.json", audit)
        print("SCHEME_A_FAILED_NO_PROMOTION: " + audit["error"], file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
