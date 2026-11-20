"""DEV-only human-attested goal preview inside the existing V3-A E2E loop.

This opt-in path creates an EDL candidate for human video review; it is not a
FIRST_LIVE verifier, autonomous repair, or a release authorization. A human
confirmation of the GOAL does not certify proposed clip in/out boundaries.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from .story_goal_video_repair import (
    apply_video_verified_goal_repair,
    goal_coverage_issues,
)

ATTESTATION_SCHEMA = "v3a_expb_human_first_live_attestation_v1"


def propose_human_assisted_goal_preview(
    *,
    edl: Sequence[Mapping[str, Any]],
    diagnosis: Mapping[str, Any],
    source_sha: str,
    attestation_path: Path,
    proposed_media_in: float,
    proposed_media_out: float,
) -> Dict[str, Any]:
    """Return one strictly isolated, non-release EDL candidate or a no-op."""
    fail = lambda reason: {
        "changed": False, "status": "UNRESOLVED", "reason": reason,
        "human_assisted_preview_only": True, "release_authorized": False,
        "edl": [dict(r) for r in edl],
    }
    try:
        att = json.loads(Path(attestation_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return fail("human_attestation_missing_or_invalid_json")
    if not isinstance(att, Mapping) or att.get("schema") != ATTESTATION_SCHEMA:
        return fail("wrong_human_attestation_schema")
    if att.get("human_confirmed_first_live") is not True:
        return fail("missing_explicit_human_first_live_confirmation")
    if att.get("first_live_verified_by_system") is not False or att.get("edl_authorization") is not False:
        return fail("attestation_must_not_claim_automatic_authorization")
    if len(source_sha) != 64 or att.get("source_sha256") != source_sha:
        return fail("human_attestation_source_sha_mismatch")
    issues = [
        i for i in goal_coverage_issues(diagnosis)
        if i.get("issue_id") == att.get("issue_id")
    ]
    if len(issues) != 1:
        return fail("no_unique_matching_goal_coverage_issue")
    issue = issues[0]
    try:
        a, b = float(proposed_media_in), float(proposed_media_out)
        shot = float(att["shot_sec_reference_not_a_cut"])
        net = float(att["net_sec_reference_not_a_cut"])
        confirm = float(issue["score_confirmation_sec"])
        bounds = issue["possible_action_interval"]
        lo, hi = float(bounds["media_in"]), float(bounds["media_out"])
    except (KeyError, TypeError, ValueError):
        return fail("missing_video_time_or_score_bracket")
    if not all(math.isfinite(x) for x in (a, b, shot, net, confirm, lo, hi)):
        return fail("nonfinite_source_pts")
    if not (0 <= a < shot < net < b and b-a <= 45.0):
        return fail("candidate_must_contain_shot_and_net_within_45s")
    if not (a < confirm - 0.5 and net < confirm - 0.5 and
            b >= lo - 15.0 and a <= hi + 5.0):
        return fail("candidate_outside_observed_score_transition_bracket")
    # This is NOT a video semantic or first-broadcast validation object. It is
    # a limited user-attested proposal for the shared safe EDL insertion logic.
    proposal = apply_video_verified_goal_repair(
        edl=edl, issue=issue,
        validated={
            "ok": True, "media_in": a, "media_out": b, "action_sec": net,
            "shot_sec": shot, "reviewer_type": "HUMAN_ATTESTATION_DEV_ONLY",
        },
        human_assisted_preview=True,
    )
    return {
        "status": "HUMAN_ASSISTED_CANDIDATE_PREVIEW" if proposal.get("applied") else "UNRESOLVED",
        "changed": bool(proposal.get("applied")),
        "reason": proposal.get("reason"),
        "edl": proposal.get("edl", [dict(r) for r in edl]),
        "issue_id": issue.get("issue_id"),
        "source_sha256": source_sha,
        "proposed_media_window": [a, b],
        "shot_net_references": [shot, net],
        "new_segment_id": proposal.get("new_segment_id"),
        "attestation_path": str(Path(attestation_path)),
        "human_confirmed_goal_first_live": True,
        "cut_boundaries_human_verified": False,
        "human_assisted_preview_only": True,
        "first_live_verified_by_system": False,
        "agent_auto_verified": False,
        "release_authorized": False,
        "candidate_quality_improved": "UNVERIFIED",
        "requires_human_review_of_entire_candidate_window": True,
    }
