"""Human-assisted B1: preview is a real EDL mutation, not FIRST_LIVE certification."""
import json

from algo.story_video_agent_v3.story_human_goal_preview import (
    propose_human_assisted_goal_preview,
)
from algo.story_video_agent_v3.story_goal_video_repair import apply_video_verified_goal_repair

SHA = "a" * 64
ISSUE = {
    "issue_id": "goal_coverage_01_to_11",
    "category": "goal_coverage",
    "diagnosis_status": "HYPOTHESIS_NEEDS_VIDEO",
    "score_before": [0, 1],
    "score_after": [1, 1],
    "score_confirmation_sec": 595.0,
    "possible_action_interval": {"media_in": 550.0, "media_out": 590.0},
}
EDL = [
    {"segment_id": "s0", "role": "intro", "include_in_cut": True},
    {"segment_id": "s1", "role": "deficit_setup", "media_in": 510.0,
     "media_out": 520.0, "include_in_cut": True},
    {"segment_id": "s2", "role": "equalizer_scoreboard_anchor", "media_in": 600.0,
     "media_out": 605.0, "include_in_cut": True},
]


def make_attestation(tmp_path, **changes):
    att = {
        "schema": "v3a_expb_human_first_live_attestation_v1",
        "human_confirmed_first_live": True,
        "source_sha256": SHA,
        "issue_id": ISSUE["issue_id"],
        "first_live_verified_by_system": False,
        "edl_authorization": False,
        "shot_sec_reference_not_a_cut": 560.0,
        "net_sec_reference_not_a_cut": 562.0,
        "precise_cut_boundaries_confirmed": False,
    }
    att.update(changes)
    p = tmp_path / "human.json"
    p.write_text(json.dumps(att), encoding="utf-8")
    return p


def call(tmp_path, *, edl=EDL, diagnosis=None, **changes):
    return propose_human_assisted_goal_preview(
        edl=edl,
        diagnosis={"issues": [ISSUE]} if diagnosis is None else diagnosis,
        source_sha=SHA,
        attestation_path=make_attestation(tmp_path, **changes),
        proposed_media_in=554.0,
        proposed_media_out=567.0,
    )


def test_human_preview_produces_candidate_without_automatic_first_live(tmp_path):
    r = call(tmp_path)
    assert r["changed"], r["reason"]
    assert len(r["edl"]) == len(EDL) + 1
    row = next(x for x in r["edl"] if x.get("human_assisted_preview_only"))
    assert row["first_live_status"] == "HUMAN_ATTESTED_PREVIEW_ONLY"
    assert row["agent_auto_verified"] is False
    assert row["validated_evidence"] is None
    assert row["cut_boundaries_human_verified"] is False
    assert r["release_authorized"] is False
    assert r["first_live_verified_by_system"] is False
    assert r["candidate_quality_improved"] == "UNVERIFIED"


def test_attestation_wrong_source_is_fail_closed(tmp_path):
    r = call(tmp_path, source_sha256="b" * 64)
    assert not r["changed"]
    assert r["reason"] == "human_attestation_source_sha_mismatch"


def test_complete_story_negative_control_remains_unchanged(tmp_path):
    r = call(tmp_path, diagnosis={"issues": []})
    assert not r["changed"]
    assert r["edl"] == EDL
    assert r["reason"] == "no_unique_matching_goal_coverage_issue"


def test_candidate_overlap_with_existing_source_footage_blocked(tmp_path):
    overlapping_edl = [
        {**EDL[0]},
        {"segment_id": "s1", "role": "already_present_goal",
         "media_in": 556.0, "media_out": 564.0, "include_in_cut": True},
        {**EDL[2]},
    ]
    r = call(tmp_path, edl=overlapping_edl)
    assert not r["changed"]
    assert r["reason"] == "new_window_overlaps_existing_footage"


def test_automatic_goal_repair_still_rejects_human_preview_level_evidence():
    validated = {
        "ok": True, "media_in": 554.0, "media_out": 567.0,
        "action_sec": 562.0, "reviewer_type": "HUMAN_ATTESTATION_DEV_ONLY",
    }
    auto = apply_video_verified_goal_repair(
        edl=EDL, issue=ISSUE, validated=validated,
    )
    assert not auto["applied"]
    assert auto["edl"] == EDL


def test_human_preview_main_chain_rejects_multiround_before_baseline(tmp_path):
    from pathlib import Path
    from algo.story_video_agent_v3.story_e2e_agent import StoryE2EInputs, run_story_e2e

    att = make_attestation(tmp_path)
    result = run_story_e2e(StoryE2EInputs(
        match_json=tmp_path / "match.json",
        source_mp4=tmp_path / "source.mp4",
        out_dir=tmp_path / "refused_out",
        human_assisted_first_live_attestation=att,
        human_preview_media_in=554.0,
        human_preview_media_out=567.0,
        max_rounds=2,
        enable_real_api=False,
        skip_vlm=True,
    ))
    assert result["error"] == (
        "human_preview_requires_single_round_offline_historical_baseline_without_fixtures"
    )
