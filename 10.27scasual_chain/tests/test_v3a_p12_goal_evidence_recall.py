"""P12: no hallucinated goal timestamp from scoreboard-only transitions."""
import json
from pathlib import Path

from story_video_agent_v3.goal_recovery import (
    propose_unresolved_goal_video_windows, recover_goal_candidates,
    recover_match_goals,
)
from story_video_agent_v3.story_full_e2e_cli import evaluate_stages


def _event(eid, t, score, kind="Pass"):
    return {
        "event_id": eid, "event_type": kind,
        "media_time": {"event_time_sec": t},
        "attributes": {"Score_Recognition": [score]},
    }


def test_score_only_equalizer_produces_video_requests_not_fake_action():
    events = [
        _event("pre", 100, "0:1"),
        _event("post", 220, "1:1", "Win_an_aerial_duel"),
    ]
    candidates = recover_goal_candidates(events)
    assert len(candidates) == 1
    assert candidates[0]["nearby_events"] == []
    assert candidates[0]["goal_action_sec"] is None
    requests = propose_unresolved_goal_video_windows(candidates)
    assert len(requests) == 1
    req = requests[0]
    assert req["score_before"] == [0, 1]
    assert req["score_after"] == [1, 1]
    assert req["no_action_time_inferred"]
    assert req["no_automatic_edl_insertion"]
    assert len(req["observation_windows"]) == 5
    assert all(100 <= w["media_in"] < w["media_out"] <= 220 for w in req["observation_windows"])
    assert all(not w["first_live_verified"] for w in req["observation_windows"])


def test_search_windows_respect_tiny_bracket_and_reject_invalid():
    c = {
        "candidate_id": "x", "single_goal_increment": True,
        "goal_action_sec": None, "score_before": [0, 0],
        "score_after": [1, 0], "score_confirmation_sec": 12,
        "possible_action_interval": {"media_in": 10, "media_out": 12},
        "linked_strip_chain_ids": [{"clip_id": "clip1", "t0_sec": 10, "t1_sec": 12}],
    }
    req = propose_unresolved_goal_video_windows([c], max_windows_per_goal=3)[0]
    assert all(w["media_in"] == 10 and w["media_out"] == 12 for w in req["observation_windows"])
    assert all(w["supporting_strip_clip_ids"] == ["clip1"] for w in req["observation_windows"])
    assert propose_unresolved_goal_video_windows([{**c, "goal_action_sec": 11}]) == []
    assert propose_unresolved_goal_video_windows([{**c, "single_goal_increment": False}]) == []


def test_recover_match_goals_emits_missing_goal_search_without_gold(tmp_path):
    inp = tmp_path / "raw.json"
    inp.write_text(json.dumps({"events": [
        _event("pre", 100, "0:1"),
        _event("post", 220, "1:1"),
    ]}), encoding="utf-8")
    result = recover_match_goals(events_path=inp)
    assert result["n_single_goal"] == 1
    assert result["n_with_goal_action_sec"] == 0
    assert result["n_unresolved_single_goals"] == 1
    assert not result["all_single_goal_actions_located"]
    assert result["pending_goal_video_search"][0]["candidate_id"] == "goalcand_00_01_to_11"


def test_official_stage_report_marks_missing_action_as_release_blocker(tmp_path):
    root = tmp_path / "fresh"
    p = root / "03_v1_adapt"
    p.mkdir(parents=True)
    (p / "goal_recovery.json").write_text(json.dumps({
        "n_candidates": 1, "n_single_goal": 1,
        "n_with_goal_action_sec": 0, "n_unresolved_single_goals": 1,
        "all_single_goal_actions_located": False,
        "candidates": [{
            "candidate_id": "goalcand_00_01_to_11",
            "single_goal_increment": True, "goal_action_sec": None,
        }],
    }), encoding="utf-8")
    (p / "predicted_causal.json").write_text(json.dumps({
        "causal_chains": [{"events": []}],
        "v3_adapter": {"goal_recovery_used": True, "n_v3_outcome_chains": 1},
    }), encoding="utf-8")
    (p / "predicted_causal_live_goals_only.json").write_text("{}", encoding="utf-8")
    (p / "goal_recovery_impact.json").write_text(
        '{"entered_predicted_causal": true}', encoding="utf-8")
    report = evaluate_stages(out_dir=tmp_path, fresh_root=root, delivery={})
    assert report["stages"]["03_v1_adapt"]["valid"]
    assert report["stages"]["03_v1_adapt"]["unresolved_goal_candidate_ids"] == [
        "goalcand_00_01_to_11"
    ]
    assert "03_score_confirmed_goal_action_missing" in report["blocking_errors"]
    assert not report["all_required_valid"]
