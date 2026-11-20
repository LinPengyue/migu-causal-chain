"""P10-E: source-bound narrative-function loss audit for exploratory edits.

A structural risk hypothesis, NOT a video-grounded semantic verdict. No
benchmark labels, human review, match-specific IDs, model calls or API use.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from .story_timeline import active_cut_rows

SCHEMA = "v3a_narrative_function_loss_v1"
MOTIVATION = ("buildup", "build_up", "bridge", "pressure", "attempt", "attack",
              "development", "struggle", "effort", "chase", "momentum")
TURN = ("equaliz", "comeback", "turn", "go_ahead", "winner", "climax",
        "goal_action", "scoreboard")
SETUP = ("deficit", "setup", "concede", "opponent", "trailing", "opening")


def _role(row: Mapping[str, Any]) -> str:
    return str(row.get("role") or "").lower()


def _matches(role: str, words: tuple[str, ...]) -> bool:
    return any(word in role for word in words)


def assess_narrative_function_loss(
    baseline_edl: Sequence[Mapping[str, Any]],
    candidate_edl: Sequence[Mapping[str, Any]],
    *,
    target_segment_id: str,
    action: str,
) -> dict[str, Any]:
    """Report editorial bridge risk; never claim the footage shows intent."""
    before = active_cut_rows(baseline_edl)
    after = active_cut_rows(candidate_edl)
    ids = [str(r.get("segment_id") or "") for r in before]
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "UNASSESSED",
        "target_segment_id": target_segment_id,
        "action": action,
        "risk_level": "UNKNOWN",
        "semantic_video_verified": False,
        "human_quality_inferred": False,
        "requires_contextual_video_review": True,
        "signals": [],
        "limitations": [
            "Role labels and editorial adjacency are hypotheses, not visual semantics.",
            "No segment ID or match-specific human preference is hardcoded.",
        ],
    }
    if target_segment_id not in ids:
        result["status"] = "TARGET_NOT_ACTIVE"
        return result
    i = ids.index(target_segment_id)
    target = before[i]
    role = _role(target)
    prior = [_role(x) for x in before[max(0, i-2):i]]
    following = [_role(x) for x in before[i+1:i+3]]
    after_ids = [str(r.get("segment_id") or "") for r in after]
    removed = target_segment_id not in after_ids
    result["status"] = "STRUCTURAL_SCREENED"
    result["target_role_hint"] = role
    result["preceding_role_hints"] = prior
    result["following_role_hints"] = following
    result["removed"] = removed
    if action == "drop" and removed and _matches(role, MOTIVATION):
        result["signals"].append("potential_motivation_or_effort_visual_removed")
        if any(_matches(x, SETUP) for x in prior) and any(
            _matches(x, TURN) for x in following
        ):
            result["signals"].append("setup_to_turn_bridge_may_be_lost")
            result["risk_level"] = "HIGH_UNVERIFIED"
        else:
            result["risk_level"] = "ELEVATED_UNVERIFIED"
    elif action in {"trim", "reorder"} and _matches(role, MOTIVATION):
        result["signals"].append("potential_motivation_visual_modified")
        result["risk_level"] = "ELEVATED_UNVERIFIED"
    else:
        result["risk_level"] = "UNKNOWN"
    result["recommendation"] = (
        "Inspect full before-target-after video and judge whether effort, "
        "motivation or anticipation becomes implicit; compare blind fullcuts."
        if result["signals"] else
        "No role-based bridge signal; still requires whole-story blind review."
    )
    return result
