"""P11 regression: no human causal atoms and honest bounded fullcut critic coverage."""
from __future__ import annotations

import json
from pathlib import Path

from story_video_agent_v3.atomic_event_enrich import enrich_files
from story_video_agent_v3.goal_recovery import score_observations, recover_goal_candidates
from story_video_agent_v3.v1_causal_adapter import score_transitions_from_events
from story_video_agent_v3.story_editorial_redundancy import validate_editorial_irrelevance_claims
from story_video_agent_v3.story_full_e2e_cli import build_parser, validate_inputs, evaluate_stages
from story_video_agent_v3.story_paid_eval import (
    select_critic_frame_bundle, _story_frame_segment_id,
)
from story_video_agent_v3.story_timeline import build_story_timeline, story_time_to_media


def _edl():
    return [
        {"segment_id": "setup", "role": "deficit_scoreboard_anchor", "shot_kind": "scoreboard_anchor",
         "media_in": 10.0, "media_out": 13.0},
        {"segment_id": "event", "role": "buildup_action", "shot_kind": "live",
         "media_in": 15.0, "media_out": 19.0},
        {"segment_id": "turn", "role": "equalizer_goal_action", "shot_kind": "live",
         "goal_action_complete": True, "media_in": 25.0, "media_out": 30.0},
        {"segment_id": "ending", "role": "story_wrap_scoreboard", "shot_kind": "scoreboard_anchor",
         "media_in": 32.0, "media_out": 34.0},
    ]


def test_raw_only_enrichment_preserves_original_events_without_gold(tmp_path):
    original = {
        "schema_version": "1.0", "teams": {},
        "events": [
            {"event_id": "s1", "event_type": "Shot", "media_time": {"event_time_sec": 5}},
            {"event_id": "s2", "event_type": "Shot", "media_time": {"event_time_sec": 10}},
        ],
    }
    inp = tmp_path / "raw.json"
    out = tmp_path / "events_enriched.json"
    inp.write_text(json.dumps(original), encoding="utf-8")
    report = enrich_files(events_path=inp, out_events_path=out,
                          out_report_path=tmp_path / "report.json")
    assert json.loads(out.read_text(encoding="utf-8")) == original
    assert report["input_mode"] == "RAW_EVENTS_ONLY"
    assert report["n_injected"] == 0
    assert report["n_goal_injected"] == 0
    assert report["eligible_for_raw_only_evaluation"]
    assert not report["human_annotation_atoms_used"]


def test_optional_legacy_atoms_are_explicitly_dev_only(tmp_path):
    original = {"events": []}
    inp = tmp_path / "raw.json"
    causal = tmp_path / "match_causal.json"
    inp.write_text(json.dumps(original), encoding="utf-8")
    causal.write_text(json.dumps({"causal_chains": [{
        "is_replay": False,
        "events": [{"event_id": "gold1", "type_en": "Goal", "t_ms": 12000}],
    }]}), encoding="utf-8")
    report = enrich_files(events_path=inp, causal_path=causal,
                          out_events_path=tmp_path / "enriched.json")
    assert report["input_mode"] == "HUMAN_ATOM_ENRICHED_DEV"
    assert report["human_annotation_atoms_used"] is True
    assert report["eligible_for_raw_only_evaluation"] is False
    assert report["n_goal_injected"] == 1


def test_full_e2e_requires_only_raw_mp4_and_events_and_strict_rejects_human(tmp_path):
    raw, vid, causal = [tmp_path / n for n in ("raw.json", "game.mp4", "human_causal.json")]
    raw.write_text(json.dumps({"events": []}), encoding="utf-8")
    vid.write_bytes(b"fake test video")
    causal.write_text(json.dumps({"causal_chains": []}), encoding="utf-8")
    common = ["--source-mp4", str(vid), "--events-json", str(raw),
              "--out-dir", str(tmp_path / "out"), "--strict-raw-only"]
    args = build_parser().parse_args(common)
    assert args.causal_json is None
    assert validate_inputs(args) == []
    args2 = build_parser().parse_args(common + ["--causal-json", str(causal)])
    assert "strict_raw_only_rejects_human_causal_json" in validate_inputs(args2)


def _observations():
    # Global sample positions deliberately cover both the start and ending,
    # unlike the old first-N extraction which could starve the story tail.
    samples = [0.3, 1.1, 1.6, 3.1, 3.9, 5.6, 6.6, 7.6, 9.1, 11.1, 13.1]
    return {"layers": {"global": {"frames": [
        {"frame_id": f"global_{j}", "story_sec": t, "path": f"/tmp/f_{j}.jpg"}
        for j, t in enumerate(samples)
    ]}, "paragraph": []}}


def test_critic_frame_selection_reserves_global_story_coverage():
    diag = {"timeline": build_story_timeline(_edl())}
    dense = [
        {"frame_id": f"dense_{i}", "story_sec": 3.2 + 0.1*i, "path": f"/tmp/d_{i}.jpg"}
        for i in range(6)
    ]
    got = select_critic_frame_bundle(
        _observations(), diag, extra_frames=dense, max_frames=7,
    )
    frames = got["frames"]
    assert len(frames) <= 7
    assert any(str(f["frame_id"]).startswith("dense_") for f in frames)
    assert got["coverage"]["media_segment_count"] == 4
    assert "setup" in got["coverage"]["covered_segment_ids"]
    assert "ending" in got["coverage"]["covered_segment_ids"]
    assert all(f["segment_id"] in {None, "setup", "event", "turn", "ending"} for f in frames)
    assert got["coverage"]["claims_full_video_watch"] is False


def test_critic_coverage_reports_unobserved_as_unknown():
    diag = {"timeline": build_story_timeline(_edl())}
    got = select_critic_frame_bundle(
        {"layers": {"global": {"frames": [
            {"frame_id": "only", "story_sec": 0.5, "path": "/tmp/only.jpg"}
        ]}}}, diag, max_frames=3,
    )
    assert got["coverage"]["unobserved_media_segment_ids"] == ["event", "turn", "ending"]
    assert not got["coverage"]["all_media_segments_covered"]


def _bound_frames(tmp_path):
    ids = ["before", "candidate", "after"]
    mappings = ["setup", "event", "turn"]
    result = []
    for fid, segment_id in zip(ids, mappings):
        path = tmp_path / f"{fid}.jpg"
        path.write_bytes((fid + segment_id).encode())
        result.append({"frame_id": fid, "segment_id": segment_id, "path": str(path)})
    return result


def _claim(refs=None, target="event"):
    return {
        "target_segment_id": target,
        "observed_content": "An unrelated short live action interrupts the wider narrative arc.",
        "why_not_support_story": "The observed play does not change state or develop the central setup and turn.",
        "why_removal_may_preserve_continuity": "The previous deficit can lead directly into the verified turning point.",
        "evidence_refs": [{"frame_id": fid} for fid in (refs or ["before", "candidate", "after"])],
    }


def test_non_duplicate_irrelevance_is_only_a_hypothesis(tmp_path):
    ledger = validate_editorial_irrelevance_claims(
        [_claim()], frame_bindings=_bound_frames(tmp_path),
        timeline=build_story_timeline(_edl()), protected_goal_ids=["turn"],
    )
    assert len(ledger["issues"]) == 1
    issue = ledger["issues"][0]
    assert issue["category"] == "narrative_relevance"
    assert issue["story_defect_confirmed"] is False
    assert issue["no_automatic_edit_authorized"] is True
    assert len(issue["evidence_refs"]) == 3
    assert ledger["no_new_pts_created"] is True


def test_irrelevance_fails_closed_for_fabricated_frames_and_protected_goal(tmp_path):
    tl = build_story_timeline(_edl())
    frames = _bound_frames(tmp_path)
    bad = validate_editorial_irrelevance_claims(
        [_claim(refs=["before", "candidate", "nonexistent"])],
        frame_bindings=frames, timeline=tl, protected_goal_ids=[],
    )
    assert bad["issues"] == []
    assert bad["rejected"][0]["reason"] == "missing_or_fabricated_cited_frames"
    goal = validate_editorial_irrelevance_claims(
        [_claim(target="turn")], frame_bindings=frames, timeline=tl,
        protected_goal_ids=["turn"],
    )
    assert goal["issues"] == []


def test_irrelevance_requires_exact_before_target_after_not_three_arbitrary_frames(tmp_path):
    tl = build_story_timeline(_edl())
    frames = _bound_frames(tmp_path)
    frames[0]["segment_id"] = "event"  # all refs valid but BEFORE segment not cited
    bad = validate_editorial_irrelevance_claims(
        [_claim()], frame_bindings=frames, timeline=tl, protected_goal_ids=["turn"],
    )
    assert not bad["issues"]
    assert bad["rejected"][0]["reason"] == "not_cited_exact_before_target_after_context"


def test_exact_cut_boundary_belongs_to_following_segment():
    timeline = build_story_timeline(_edl())
    assert story_time_to_media(timeline, 3.0)["segment_id"] == "event"
    assert story_time_to_media(timeline, 7.0)["segment_id"] == "turn"
    assert story_time_to_media(timeline, 14.0)["segment_id"] == "ending"


def test_seam_adjacent_frame_has_no_trusted_segment_binding():
    timeline = build_story_timeline(_edl())
    assert _story_frame_segment_id(timeline, 7.0) is None
    assert _story_frame_segment_id(timeline, 7.2) is None
    assert _story_frame_segment_id(timeline, 8.0) == "turn"


def test_official_full_e2e_stage_validation_blocks_nonmonotonic_input_edl(tmp_path):
    fresh_root = tmp_path / "fresh"
    phase5 = fresh_root / "04_phase5"
    phase5.mkdir(parents=True)
    edl = [
        {"segment_id": "a", "role": "buildup_action", "media_in": 100, "media_out": 110},
        {"segment_id": "b", "role": "equalizer_goal_action", "media_in": 105, "media_out": 116},
    ]
    (phase5 / "candidate_edl.json").write_text(json.dumps(edl), encoding="utf-8")
    report = evaluate_stages(out_dir=tmp_path, fresh_root=fresh_root, delivery={})
    assert report["stages"]["04_phase5_edl"]["source_pts_monotonic"] is False
    assert report["stages"]["04_phase5_edl"]["valid"] is False
    assert "04_phase5_source_pts_nonmonotonic" in report["blocking_errors"]
    assert not report["all_required_valid"]


def test_raw_only_rejects_malformed_event_file(tmp_path):
    import pytest
    raw = tmp_path / "bad.json"
    raw.write_text(json.dumps({"causal_chains": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="events input must"):
        enrich_files(events_path=raw, out_events_path=tmp_path / "out.json")


def test_raw_only_score_recovery_reads_both_historical_score_locations():
    events = [
        {"event_id": "a", "event_type": "Shot",
         "media_time": {"event_time_sec": 10.0},
         "attributes": {"Score_Recognition": ["0:0"]}},
        {"event_id": "b", "event_type": "Foul_Being_fouled",
         "media_time": {"event_time_sec": 20.0},
         "scores": {"score_recognition": "1-0"}},
        {"event_id": "c", "event_type": "Shot",
         "media_time": {"event_time_sec": 30.0},
         "attributes": {"Score_Recognition": "1:1"}},
    ]
    seen = score_observations(events)
    assert [x["score"] for x in seen] == [[0, 0], [1, 0], [1, 1]]
    transitions = score_transitions_from_events(events)
    assert len(transitions) == 2
    assert all(x["single_goal_increment"] for x in transitions)
    assert all(x["goal_action_sec"] is None for x in transitions)
    candidates = recover_goal_candidates(events)
    assert len(candidates) == 2
    assert all(c["single_goal_increment"] for c in candidates)


def test_score_schema_fallback_used_if_primary_field_is_unparseable():
    events = [
        {"event_id": "a", "event_type": "Shot",
         "media_time": {"event_time_sec": 10.0},
         "attributes": {"Score_Recognition": "INVALID"},
         "scores": {"score_recognition": ["2:1"]}},
    ]
    assert score_observations(events)[0]["score"] == [2, 1]
