"""V2 Story-First branch adapter inside V3-A Evidence Search.

Import an isolated Story-First POC as an AUDITABLE observation queue, never as
verified evidence or an EDL-edit instruction. The original issue-driven search,
Planner, Renderer, Verifier and FIRST_LIVE gates remain authoritative.

This adapter makes ZERO API calls and does not read benchmark gold.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

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
        if fresh["story_plan_reference"] != old.get("story_plan_reference"):
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
        if not isinstance(supplied_targets, list):
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
        result["status"] = (
            "OBSERVATION_QUEUE_ONLY"
            if validated["hypotheses"] else "NO_VALID_HYPOTHESES"
        )
        result["reason"] = "poc_has_no_independent_source_video_binding_or_verified_causality"
        result["hypotheses"] = validated["hypotheses"]
        result["hypothesis_count"] = len(validated["hypotheses"])
        result["observation_targets"] = observation["targets"]
        result["observation_target_count"] = len(observation["targets"])
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
