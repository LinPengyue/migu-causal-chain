from __future__ import annotations

from story_video_agent_v3.story_narrative_function import assess_narrative_function_loss


def _row(sid, role, included=True):
    return {"segment_id": sid, "role": role, "include_in_cut": included,
            "media_in": 10.0, "media_out": 15.0}


def test_motivation_bridge_loss_is_flagged_without_semantic_claim():
    base = [_row("s1", "setup_deficit"), _row("s2", "buildup_action"),
            _row("s3", "equalizer_goal_action"), _row("s4", "ending")]
    candidate = [dict(r) for r in base]
    candidate[1]["include_in_cut"] = False
    result = assess_narrative_function_loss(
        base, candidate, target_segment_id="s2", action="drop")
    assert result["risk_level"] == "HIGH_UNVERIFIED"
    assert "setup_to_turn_bridge_may_be_lost" in result["signals"]
    assert result["semantic_video_verified"] is False
    assert result["human_quality_inferred"] is False


def test_not_every_buildup_is_a_bridge():
    base = [_row("s1", "generic"), _row("s2", "buildup_action"),
            _row("s3", "generic"), _row("s4", "ending")]
    candidate = [dict(r) for r in base]
    candidate[1]["include_in_cut"] = False
    result = assess_narrative_function_loss(
        base, candidate, target_segment_id="s2", action="drop")
    assert result["risk_level"] == "ELEVATED_UNVERIFIED"
    assert "setup_to_turn_bridge_may_be_lost" not in result["signals"]


def test_neutral_edit_is_not_called_safe():
    base = [_row("s1", "setup"), _row("s2", "ambient"),
            _row("s3", "turn"), _row("s4", "ending")]
    candidate = [dict(r) for r in base]
    candidate[1]["include_in_cut"] = False
    result = assess_narrative_function_loss(
        base, candidate, target_segment_id="s2", action="drop")
    assert result["risk_level"] == "UNKNOWN"
    assert result["requires_contextual_video_review"]


def test_unknown_target_fails_without_invention():
    result = assess_narrative_function_loss(
        [_row("s1", "buildup")], [], target_segment_id="absent", action="drop")
    assert result["status"] == "TARGET_NOT_ACTIVE"
    assert result["risk_level"] == "UNKNOWN"


def test_generic_role_hints_not_hardcoded_to_match_or_id():
    base = [_row("opening", "trailing_setup"), _row("middle", "pressure"),
            _row("final", "go_ahead_goal_action")]
    candidate = [dict(r) for r in base]
    candidate[1]["include_in_cut"] = False
    result = assess_narrative_function_loss(
        base, candidate, target_segment_id="middle", action="drop")
    assert result["risk_level"] == "HIGH_UNVERIFIED"
