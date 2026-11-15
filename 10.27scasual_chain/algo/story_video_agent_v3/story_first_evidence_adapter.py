"""V2 Story-First branch adapter inside V3-A Evidence Search.

Import an isolated Story-First POC as an AUDITABLE observation queue, never as
verified evidence or an EDL-edit instruction. The original issue-driven search,
Planner, Renderer, Verifier and FIRST_LIVE gates remain authoritative.

This adapter makes ZERO API calls and does not read benchmark gold.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from .story_first_a_ranker import rank_model_evaluations
from .story_first_hypotheses import (
    build_observation_plan,
    parse_hypotheses,
    prepare_story_input,
)

SCHEMA = "v2_story_first_evidence_branch_v1"
_REQUIRED = (
    "prepared_story_input.json",
    "story_hypotheses.json",
    "observation_plan.json",
)
_SCORED_MODES = ("REAL_MODEL_PRIOR_NOT_VIDEO_VERIFIED", "OFFLINE_FIXTURE_NOT_REAL_LLM")
_UNSCORED_MODES = {
    "PREPARED_ONLY_ZERO_HTTP": "AWAITING_SCORING_MODEL",
    "NO_STAGE1_CANDIDATES": "NO_CANDIDATES",
}


def _read_artifact(directory: Path, name: str) -> Mapping[str, Any]:
    path = directory / name
    if not path.is_file() or path.stat().st_size > 8_000_000:
        raise ValueError("missing_or_oversized_artifact:" + name)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("artifact_must_be_object:" + name)
    return data


def _event_fingerprint(prepared: Mapping[str, Any]) -> list:
    """Cross-check source event IDs AND their actual media PTS, not labels."""
    return [
        (str(e["event_id"]), float(e["source_pts_sec"]))
        for e in prepared.get("event_inventory") or []
    ]


def read_story_first_observation_branch(
    *,
    artifacts_dir: Path,
    current_edl: Sequence[Mapping[str, Any]],
    current_story_plan: Any,
    permitted_events: Sequence[Mapping[str, Any]],
    current_source_sha256: Optional[str],
) -> Dict[str, Any]:
    """Rebind POC references to the current V3-A story before exposing a queue.

    FAIL CLOSED on stale anchors, plan or events. Even a successful rebind
    does NOT validate source-video bytes: the existing POC has no source MP4
    SHA binding. Consequently 0 candidates may enter the Planner.
    """
    result: Dict[str, Any] = {
        "schema": SCHEMA,
        "branch": "story_driven",
        "source": "isolated_story_first_poc",
        "status": "REJECTED_NO_PROMOTION",
        "reason": None,
        "current_source_sha256_for_audit_only": current_source_sha256,
        "poc_source_sha256_bound": False,
        "http_calls_by_adapter": 0,
        "hypothesis_count": 0,
        "observation_target_count": 0,
        "hypotheses": [],
        "observation_targets": [],
        "scheme_a_ranking_status": "NOT_PROVIDED",
        "scheme_a_selected_for_observation": [],
        "verified_long_range_causal_links": 0,
        "planner_candidates": [],
        "planner_candidate_count": 0,
        "first_live_certified": False,
        "narrative_gain_verified": False,
        "edl_modified": False,
        "observation_only": True,
        "note": (
            "Story-First model hypotheses are not video evidence. No insertion, "
            "replacement, promotion or first-LIVE certification is authorized."
        ),
    }
    try:
        artifact_dir = Path(artifacts_dir)
        saved = {name: _read_artifact(artifact_dir, name) for name in _REQUIRED}
        old = saved["prepared_story_input.json"]
        scope = old.get("scope")
        if not isinstance(scope, Mapping):
            raise ValueError("missing_poc_scope")
        sid_from = str(scope.get("from_segment_id") or "")
        sid_to = str(scope.get("to_segment_id") or "")
        if not sid_from or not sid_to:
            raise ValueError("unbound_poc_anchors")
        detail_cap = max(1, min(2000, len(old.get("events") or [])))
        fresh = prepare_story_input(
            current_edl,
            permitted_events,
            story_plan=current_story_plan,
            from_segment_id=sid_from,
            to_segment_id=sid_to,
            max_events=detail_cap,
        )
        new_scope = fresh["scope"]
        if (list(new_scope["source_interval_sec"]) != list(scope.get("source_interval_sec") or [])
                or new_scope["from_segment_id"] != sid_from
                or new_scope["to_segment_id"] != sid_to):
            raise ValueError("story_anchors_or_source_pts_changed")
        plan_key = ("frozen_story_plan" if "frozen_story_plan" in old
                    else "story_plan_reference")
        if fresh[plan_key] != old.get(plan_key):
            raise ValueError("story_plan_changed_since_poc")
        if _event_fingerprint(fresh) != _event_fingerprint(old):
            raise ValueError("event_ids_or_pts_changed_since_poc")
        if saved["story_hypotheses.json"].get("edl_modified") is True:
            raise ValueError("poc_claims_edl_modified")
        validated = parse_hypotheses(
            saved["story_hypotheses.json"], fresh, max_hypotheses=5,
        )
        # Never trust a stored observation target's source times. Reconstruct
        # exact probe windows from current event PTS through the source code.
        observation = build_observation_plan(fresh, validated)
        supplied_targets = saved["observation_plan.json"].get("targets")
        if (not isinstance(supplied_targets, list)
                or any(not isinstance(x, Mapping) for x in supplied_targets)):
            raise ValueError("invalid_saved_observation_plan")
        def _target_key(x: Mapping[str, Any]) -> tuple:
            return (
                str(x.get("hypothesis_id") or ""),
                str(x.get("probe_id") or ""),
                tuple(x.get("source_interval_sec") or []),
            )
        if (len(supplied_targets) != len(observation["targets"])
                or [_target_key(x) for x in supplied_targets]
                != [_target_key(x) for x in observation["targets"]]):
            raise ValueError("stored_observation_plan_not_reproducible")
        targets = observation["targets"]
        # Optional Scheme-A evaluation pass, produced in an isolated child
        # directory by story_first_a_ranker.py. Scores are ONLY a queue prior.
        # Verify both source artifact byte hashes AND ranker output equations.
        score_dir = artifact_dir / "scheme_a_ranking"
        audit_status = "NOT_PROVIDED"
        if score_dir.exists():
            provenance = _read_artifact(score_dir, "score_model_input.json")
            ranking = _read_artifact(score_dir, "scheme_a_story_ranking.json")
            rank_audit = _read_artifact(score_dir, "scheme_a_audit.json")
            if (provenance.get("source_prepared_sha256")
                != hashlib.sha256(
                    (artifact_dir / "prepared_story_input.json").read_bytes()
                ).hexdigest() or provenance.get("source_hypotheses_sha256")
                != hashlib.sha256(
                    (artifact_dir / "story_hypotheses.json").read_bytes()
                ).hexdigest()):
                raise ValueError("scheme_a_source_artifacts_changed")
            audit_status = str(rank_audit.get("status") or "")
            if audit_status not in _SCORED_MODES:
                if (audit_status not in _UNSCORED_MODES
                        or ranking.get("status") != _UNSCORED_MODES[audit_status]
                        or ranking.get("ranked_hypotheses") != []
                        or ranking.get("selected_for_video_observation") != []
                        or (audit_status == "NO_STAGE1_CANDIDATES"
                            and validated["hypotheses"])):
                    raise ValueError("scheme_a_not_scored_or_untrusted_mode")
        if audit_status in _SCORED_MODES:
            if "current_edl" in old and old["current_edl"] != fresh["current_edl"]:
                raise ValueError("current_edl_changed_since_scheme_a_input")
            rows = ranking.get("ranked_hypotheses")
            if not isinstance(rows, list):
                raise ValueError("scheme_a_missing_rank_rows")
            evaluations = []
            for item in rows:
                if not isinstance(item, Mapping):
                    raise ValueError("scheme_a_nonobject_row")
                entry = {
                    "hypothesis_id": item.get("hypothesis_id"),
                    "cited_event_ids": item.get("cited_event_ids"),
                    "new_story_information": item.get("new_story_information"),
                    "comparison_to_existing_story": item.get(
                        "comparison_to_existing_story"),
                    "major_uncertainty": item.get("major_uncertainty"),
                }
                scores = item.get("scores")
                if not isinstance(scores, Mapping):
                    raise ValueError("scheme_a_missing_scores")
                entry.update(scores)
                evaluations.append(entry)
            recomputed = rank_model_evaluations(
                {"evaluations": evaluations}, validated,
                top_k=int(ranking.get("top_k") or 2),
            )
            if (recomputed["ranked_hypotheses"] != rows
                    or recomputed["selected_for_video_observation"]
                    != ranking.get("selected_for_video_observation")
                    or ranking.get("status") != recomputed["status"]):
                raise ValueError("scheme_a_ranking_not_reproducible")
            preferred = recomputed["selected_for_video_observation"]
            # Reprioritize the *observation* queue, NEVER the legacy Planner.
            order = {hid: i for i, hid in enumerate(preferred)}
            targets = sorted(
                targets,
                key=lambda t: (
                    order.get(str(t["hypothesis_id"]), len(preferred)),
                    str(t["hypothesis_id"]), str(t["probe_id"])),
            )
            result["scheme_a_selected_for_observation"] = preferred
            result["scheme_a_ranking"] = recomputed["ranked_hypotheses"]
            result["scheme_a_model_prior_not_factual_proof"] = True
        result["scheme_a_ranking_status"] = audit_status
        result["status"] = (
            "OBSERVATION_QUEUE_ONLY"
            if validated["hypotheses"] else "NO_VALID_HYPOTHESES"
        )
        result["reason"] = "poc_has_no_independent_source_video_binding_or_verified_causality"
        result["hypotheses"] = validated["hypotheses"]
        result["hypothesis_count"] = len(validated["hypotheses"])
        result["observation_targets"] = targets
        result["observation_target_count"] = len(targets)
        result["rejected_hypotheses"] = validated.get("rejected") or []
        result["scope"] = new_scope
        result["data_tier"] = old.get("data_tier")
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        result["reason"] = "%s:%s" % (type(exc).__name__, str(exc)[:200])
    return result


def planner_safe_story_first_summary(branch: Mapping[str, Any]) -> Dict[str, Any]:
    """Metadata only; NEVER pass unverified hypotheses to legacy Planner."""
    return {
        "status": str(branch.get("status") or "REJECTED_NO_PROMOTION"),
        "hypothesis_count": int(branch.get("hypothesis_count") or 0),
        "observation_target_count": int(branch.get("observation_target_count") or 0),
        "planner_candidate_count": 0,
        "observation_only": True,
        "edl_modified": False,
        "first_live_certified": False,
    }
