"""P11 regression: no human causal atoms and honest bounded fullcut critic coverage."""
from __future__ import annotations

import json
from pathlib import Path

from story_video_agent_v3.atomic_event_enrich import enrich_files
from story_video_agent_v3.story_editorial_redundancy import validate_editorial_irrelevance_claims
from story_video_agent_v3.story_full_e2e_cli import build_parser, validate_inputs
from story_video_agent_v3.story_paid_eval import select_critic_frame_bundle
from story_video_agent_v3.story_timeline import build_story_timeline


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
    assert all(f["segment_id"] in {"setup", "event", "turn", "ending"} for f in frames)
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
    assert not ledger["no_new_pts_created"] is False


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
