"""Zero-HTTP checks for V3-A scoreboard-vs-story-goal coverage.

These test DETECTION and source-search planning, not recovered goal video.
The model receives no target PTS, benchmark gold, injected revision intents,
or first-live sign-off; a score board is never an action timestamp.
"""
from __future__ import annotations

import json

from story_video_agent_v3.global_story_critic import (
    detect_goal_coverage_hypotheses, structural_diagnosis,
)
from story_video_agent_v3.story_evidence_search import (
    run_story_evidence_search, search_window_for_issue,
)
from story_video_agent_v3.global_story_critic import merge_observation_into_diagnosis
from story_video_agent_v3.story_revision_planner import plan_from_diagnosis


def _event(eid, t, score=None, kind="Shot", replay=False):
    out = {
        "event_id": eid, "event_type": kind,
        "media_time": {"event_time_sec": t, "start_time_sec": t - 1,
                       "end_time_sec": t + 3},
        "video_context": {
            "broadcast_phase": "REPLAY" if replay else "LIVE",
            "is_replay": replay,
        },
    }
    if score is not None:
        out["scores"] = {"score_recognition": score}
    return out


def _events():
    # 0:0 -> 0:1 -> 1:1 -> 2:1. No event type=Goal is required.
    return [
        _event("board_0", 3, "0:0", kind="Foul_Being_fouled"),
        _event("opp_shot", 51, "0:0"),
        _event("board_01", 64, "0:1", kind="Foul_Being_fouled"),
        _event("still_01", 102, "0:1", kind="Foul_Being_fouled"),
        _event("equalizer_shot", 151, "0:1"),
        _event("board_11", 164, "1:1", kind="Foul_Being_fouled"),
        _event("still_11", 192, "1:1", kind="Foul_Being_fouled"),
        _event("winner_shot", 231, "1:1"),
        _event("board_21", 244, "2:1", kind="Foul_Being_fouled"),
    ]


def _edl():
    return [
        {"segment_id": "opener", "role": "opponent_opening_goal_action",
         "goal_anchor_t_sec": 51.0, "media_in": 45.0, "media_out": 56.0},
        {"segment_id": "deficit", "role": "deficit_scoreboard_anchor",
         "media_in": 63.0, "media_out": 67.0},
        {"segment_id": "bridge", "role": "buildup_action",
         "media_in": 110.0, "media_out": 120.0},
        {"segment_id": "equalizer", "role": "equalizer_goal_action",
         "goal_anchor_t_sec": 151.0, "media_in": 143.0, "media_out": 156.0},
        {"segment_id": "equalizer_board", "role": "equalizer_scoreboard_anchor",
         "media_in": 163.0, "media_out": 167.0},
        {"segment_id": "winner", "role": "go_ahead_goal_action",
         "goal_anchor_t_sec": 231.0, "media_in": 224.0, "media_out": 238.0},
        {"segment_id": "winner_board", "role": "go_ahead_scoreboard_anchor",
         "media_in": 243.0, "media_out": 247.0},
    ]


def _broken():
    return [x for x in _edl() if x["segment_id"] != "equalizer"]


def test_complete_cut_does_not_invent_score_to_goal_coverage_defect():
    assert detect_goal_coverage_hypotheses(
        edl=_edl(), raw_events=_events()
    ) == []


def test_missing_equalizer_detected_without_time_or_gold_leakage():
    issues = detect_goal_coverage_hypotheses(
        edl=_broken(), raw_events=_events()
    )
    assert len(issues) == 1
    issue = issues[0]
    assert issue["category"] == "goal_coverage"
    assert issue["score_before"] == [0, 1]
    assert issue["score_after"] == [1, 1]
    assert issue["score_confirmation_sec"] == 164
    assert issue["story_defect_confirmed"] is False
    assert issue["diagnosis_status"] == "HYPOTHESIS_NEEDS_VIDEO"
    assert issue["action_timestamp_known"] is False
    assert issue["first_live_verified"] is False
    assert issue["auto_insert_authorized"] is False
    assert issue["board_confirmation_is_not_action"] is True
    assert issue["possible_action_interval"]["media_out"] < 164
    assert "equalizer" not in issue["segment_ids"]
    assert "equalizer_board" in issue["segment_ids"]
    assert "151.0" not in issue["observation"]


def test_structural_critic_keeps_goal_gap_unconfirmed_without_video(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"not-a-video")
    diagnosis = structural_diagnosis(
        edl=_broken(), story_plan={},
        initial_story_mp4=None, source_video=source,
        raw_events=_events(),
    )
    merged = merge_observation_into_diagnosis(
        diagnosis, {"semantic_provider_used": False, "fixture_or_offline": True}
    )
    found = [x for x in merged["issues"] if x["category"] == "goal_coverage"]
    assert len(found) == 1
    assert found[0]["diagnosis_status"] == "HYPOTHESIS_NEEDS_VIDEO"
    assert not found[0]["story_defect_confirmed"]
    revision = plan_from_diagnosis(merged, offline=True)
    assert revision["decision"] != "REVISE"
    assert not any(
        i.get("action") == "search_add"
        for i in revision.get("revision_intents") or []
    )


def test_score_gap_routes_into_source_search_as_goal_probe_only(tmp_path):
    events = tmp_path / "events.json"
    events.write_text(json.dumps({"events": _events()}), encoding="utf-8")
    issue = detect_goal_coverage_hypotheses(
        edl=_broken(), raw_events=_events(),
    )[0]
    window = search_window_for_issue(issue, _broken())
    assert window is not None
    assert window["kind"] == "missing_goal_action_evidence_search"
    assert window["role"] == "goal_action_probe"
    assert window["auto_insert_authorized"] is False
    assert window["before_segment_id"] == "equalizer_board"
    result = run_story_evidence_search(
        diagnosis={"issues": [issue]}, edl=_broken(),
        events_json=events, max_issues=1,
    )
    assert result["targets"]
    assert result["targets"][0]["category"] == "goal_coverage"
    assert result["targets"][0]["search_window"]["kind"] == (
        "missing_goal_action_evidence_search"
    )
    assert all(c["goal_probe_only"] for c in result["candidates"])
    assert all(not c["goal_video_semantic_verified"] for c in result["candidates"])
    assert not result["executable_first_live_candidates"]
    assert all(
        c["evidence_tier"] == "EVENT_PTS_CANDIDATE"
        for c in result["verified_candidates"]
    )


def test_no_gold_synthetic_goal_label_without_score_change_is_not_detection():
    only_goals = [
        _event("goal", 151, None, kind="Goal"),
        _event("shot", 152, None, kind="Shot"),
    ]
    assert not detect_goal_coverage_hypotheses(
        edl=_broken(), raw_events=only_goals,
    )


def test_replay_or_slow_goal_cannot_count_as_live_coverage():
    wrong = _edl()
    wrong[3]["is_replay"] = True
    gaps = detect_goal_coverage_hypotheses(
        edl=wrong, raw_events=_events()
    )
    assert len(gaps) == 1
    assert gaps[0]["score_after"] == [1, 1]


def test_repeated_score_cues_do_not_trigger_duplicate_gap():
    events = _events() + [
        _event("repeat_11", 260, "1:1", replay=True),
        _event("repeat_21", 261, "2:1"),
    ]
    gaps = detect_goal_coverage_hypotheses(
        edl=_broken(), raw_events=events,
    )
    assert len([x for x in gaps if x["score_after"] == [1, 1]]) == 1


def test_multi_goal_board_jump_not_silent_goal_action_oracle():
    events = [
        _event("s0", 1, "0:0"),
        _event("s2", 120, "2:0"),
    ]
    assert not detect_goal_coverage_hypotheses(
        edl=[], raw_events=events,
    )


def test_score_only_reference_window_cannot_be_used_as_action_time():
    issue = detect_goal_coverage_hypotheses(
        edl=_broken(), raw_events=_events()
    )[0]
    lo = issue["possible_action_interval"]["media_in"]
    hi = issue["possible_action_interval"]["media_out"]
    assert lo <= 151 <= hi
    assert 164 > hi
    assert "goal_action_sec" not in issue
