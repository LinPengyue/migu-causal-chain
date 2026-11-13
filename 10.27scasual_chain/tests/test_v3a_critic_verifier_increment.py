"""Incremental V3-A wiring: B2 video evidence belongs to Critic; business checks to Verifier.

These are zero-HTTP unit checks. They do not certify any real match's
FIRST_LIVE or final story quality.
"""
from copy import deepcopy

from algo.story_video_agent_v3.global_story_critic import (
    merge_goal_video_observation_into_diagnosis,
)
from algo.story_video_agent_v3.story_video_verifier import (
    assess_first_live_business_context,
    build_first_live_window_ledger,
)


SHA = "a" * 64
ISSUE = {
    "issue_id": "goal_coverage_01_to_11",
    "category": "goal_coverage",
    "diagnosis_status": "HYPOTHESIS_NEEDS_VIDEO",
    "story_defect_confirmed": False,
    "first_live_verified": False,
    "auto_insert_authorized": False,
    "score_before": [0, 1],
    "score_after": [1, 1],
    "score_confirmation_sec": 595.0,
}
EDL = [{
    "segment_id": "goal_repair_1",
    "role": "score_change_goal_action",
    "media_in": 554.0, "media_out": 567.0,
    "include_in_cut": True,
    "is_replay": False,
}]
NEW = [{
    "segment_id": "goal_repair_1",
    "source_pts_start": 554.0, "source_pts_end": 567.0,
}]


def observation():
    return {
        "status": "GOAL_SEMANTIC_CANDIDATE_OBSERVED_FIRST_LIVE_UNVERIFIED",
        "source_issue_id": ISSUE["issue_id"],
        "candidate_id": "source_candidate_1",
        "source_window": [550.0, 570.0],
        "provider_mode": "real",
        "frame_ids_sent": ["f1", "f2"],
        "model_response_audit": {
            "provider_mode": "real",
            "raw_response_excerpt": '{"observed_shot":true,"observed_net":true}',
            "cited_frame_ids": ["f1", "f2"],
        },
        "source_video_crosscheck": {
            "structurally_ready_for_automated_verify": True,
            "derived_times": {"shot_sec": 560.0, "net_sec": 562.0},
        },
        "first_live_verified": False,
    }


def diagnosed(obs=None, issue=None):
    return merge_goal_video_observation_into_diagnosis(
        {"issues": [deepcopy(ISSUE if issue is None else issue)]},
        observation() if obs is None else obs,
        source_sha256=SHA,
    )


def business(*, diag=None, edl=None, events=None):
    return assess_first_live_business_context(
        candidate_edl=EDL if edl is None else edl,
        new_source_windows=NEW,
        critic_diagnosis=diagnosed() if diag is None else diag,
        source_events=events or [],
    )


def test_real_video_claim_goes_into_matching_critic_issue_but_not_gate():
    d = diagnosed()
    i = d["issues"][0]
    assert d["goal_video_critic_handoff"]["status"] == (
        "BOUND_OBSERVATION_NOT_FIRST_LIVE_CERTIFICATION"
    )
    assert i["critic_video_evidence"]["shot_sec"] == 560.0
    assert i["critic_video_evidence"]["cited_frame_ids"] == ["f1", "f2"]
    assert i["diagnosis_status"] == "HYPOTHESIS_NEEDS_VIDEO"
    assert i["story_defect_confirmed"] is False
    assert i["auto_insert_authorized"] is False
    assert i["critic_video_evidence"]["first_live_verified"] is False


def test_offline_vlm_label_does_not_become_critic_video_evidence():
    obs = observation()
    obs["provider_mode"] = "offline_fixture"
    d = diagnosed(obs)
    assert "critic_video_evidence" not in d["issues"][0]
    assert d["goal_video_critic_handoff"]["status"].startswith("UNRESOLVED")


def test_nonexistent_issue_id_does_not_bind_video_to_unrelated_issue():
    obs = observation()
    obs["source_issue_id"] = "different_match_or_transition"
    d = diagnosed(obs)
    assert "critic_video_evidence" not in d["issues"][0]
    assert d["goal_video_critic_handoff"]["status"] == "UNRESOLVED_GOAL_ISSUE_BINDING"


def test_business_consistency_is_only_a_diagnostic_not_first_live():
    r = business()
    assert r["status"] == "UNRESOLVED"
    assert not r["hard_vetoes"]
    assert r["windows"][0]["status"] == "GOAL_VIDEO_BUSINESS_CUES_CONSISTENT_UNVERIFIED"
    assert r["first_live_verified"] is False
    assert r["edit_authorized"] is False


def test_explicit_replay_row_is_vetoed():
    r = business(edl=[{**EDL[0], "is_replay": True}])
    assert r["status"] == "REJECT_REPLAY_BUSINESS_CONFLICT"
    assert r["hard_vetoes"][0]["kind"] == "first_live_business_replay_conflict"


def test_explicit_complete_replay_event_is_vetoed():
    r = business(events=[{
        "event_id": "replay_event",
        "media_time": {
            "event_time_sec": 560.0,
            "start_time_sec": 550.0, "end_time_sec": 570.0,
        },
        "video_context": {"broadcast_phase": "REPLAY"},
    }])
    assert r["hard_vetoes"]
    assert r["windows"][0]["replay_event_ids"] == ["replay_event"]


def test_partial_replay_event_is_not_automatically_a_full_window_veto():
    r = business(events=[{
        "event_id": "partial_replay_event",
        "media_time": {
            "event_time_sec": 566.0,
            "start_time_sec": 565.0, "end_time_sec": 575.0,
        },
        "video_context": {"broadcast_phase": "REPLAY"},
    }])
    assert not r["hard_vetoes"]
    assert r["first_live_verified"] is False


def test_inconsistent_score_increment_does_not_support_first_live():
    issue = {**ISSUE, "score_after": [2, 2]}
    r = business(diag=diagnosed(issue=issue))
    assert r["windows"][0]["status"] == "UNRESOLVED"
    assert not r["hard_vetoes"]


def test_unproven_new_window_remains_unverified_in_original_hard_gate():
    ledger = build_first_live_window_ledger(
        source_sha=SHA,
        new_windows=[{
            **NEW[0],
            "first_live_status": "GOAL_VIDEO_BUSINESS_CUES_CONSISTENT_UNVERIFIED",
            "require_evidence_files": False,
        }],
    )
    assert ledger["aggregate_status"] == "NOT_VERIFIED"
    assert not ledger["all_windows_verified"]


def test_no_new_windows_keeps_business_verifier_dormant():
    r = assess_first_live_business_context(
        candidate_edl=EDL, new_source_windows=[],
        critic_diagnosis=diagnosed(),
    )
    assert r["status"] == "NO_NEW_SOURCE_WINDOWS"
    assert not r["hard_vetoes"]
