"""P13 regression: semantic goal completeness and no-gold P3 localizer reuse."""
import json
from pathlib import Path

import pytest

from story_video_agent_v3 import first_live_localize as loc
from story_video_agent_v3.story_full_e2e_cli import evaluate_stages


def _write(root: Path, relative: str, obj):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return path


def test_first_live_event_loader_agrees_with_raw_goal_recovery(tmp_path):
    raw = _write(tmp_path, "events.json", {"events": [
        {"event_id": "a", "event_type": "Pass",
         "media_time": {"event_time_sec": 12, "start_time_sec": 0},
         "scores": {"score_recognition": "0:1"}},
        {"event_id": "b", "event_type": "Pass",
         "media_time": {"event_time_sec": 20},
         "attributes": {"Score_Recognition": ["1:1"]},
         "video_context": {"broadcast_phase": "REPLAY"}},
    ]})
    result = loc.load_events_rows(raw)
    assert [r["score_pair"] for r in result] == [[0, 1], [1, 1]]
    assert result[0]["media_start_sec"] == 0.0
    assert result[1]["is_replay"] is True


def test_existing_localizer_reused_for_raw_only_missing_goal(monkeypatch, tmp_path):
    raw = _write(tmp_path, "events.json", {"events": []})
    recovery = _write(tmp_path, "recovery.json", {
        "schema": "v3_goal_recovery_v1", "candidates": [
            {"candidate_id": "goalcand_03_01_to_11", "single_goal_increment": True,
             "goal_action_sec": None, "score_before": [0, 1], "score_after": [1, 1],
             "score_confirmation_sec": 150,
             "possible_action_interval": {"media_in": 100, "media_out": 150}},
            {"candidate_id": "goalcand_04_11_to_21", "single_goal_increment": True,
             "goal_action_sec": 170, "score_before": [1, 1], "score_after": [2, 1],
             "score_confirmation_sec": 200},
        ],
    })
    video = tmp_path / "raw.mp4"
    video.write_bytes(b"fixture_video")
    calls = []

    def fake_localizer(**kwargs):
        calls.append(kwargs)
        return {
            "bounds": {"unknown_interval": {"media_in": 110, "media_out": 149}},
            "summary": {"n_candidate_extracted_ok": 2,
                        "verdict_bucket": "possible_clip_semantic_insufficient_for_auto_verify"},
        }

    monkeypatch.setattr(loc, "run_first_live_localization", fake_localizer)
    out = tmp_path / "p13"
    out.mkdir()  # pre-existing *empty* output folder is allowed
    report = loc.localize_unresolved_recovered_goals(
        video=video, events_path=raw, recovery_path=recovery,
        out_dir=out, max_candidates=2, max_video_read_sec=30.0,
    )
    assert len(calls) == 1
    assert calls[0]["historical_clues"] == []
    assert calls[0]["human_score_observations"] == []
    assert calls[0]["human_review_by_candidate"] == {}
    assert calls[0]["events_path"] == raw
    assert calls[0]["video"] == video
    assert calls[0]["task_row"]["score_before"] == [0, 1]
    assert report["n_unresolved_requested"] == 1
    assert report["results"][0]["ocr_score_bounds"]["media_in"] == 110
    assert report["results"][0]["action_timestamp_autofilled"] is False
    assert report["results"][0]["edl_inserted"] is False
    assert report["no_automatic_goal_timestamp_or_edl"] is True
    assert (out / "raw_only_video_localization_summary.json").is_file()
    with pytest.raises(ValueError, match="refuse_reuse_nonempty_evidence_dir"):
        loc.localize_unresolved_recovered_goals(
            video=video, events_path=raw, recovery_path=recovery, out_dir=out,
        )


def test_localizer_rejects_non_unresolved_candidate(tmp_path):
    raw = _write(tmp_path, "raw.json", {"events": []})
    recovery = _write(tmp_path, "recovery.json", {
        "schema": "v3_goal_recovery_v1", "candidates": [
            {"candidate_id": "already_known", "single_goal_increment": True,
             "goal_action_sec": 100},
        ],
    })
    vid = tmp_path / "source.mp4"
    vid.write_bytes(b"x")
    with pytest.raises(ValueError, match="candidate_id_not_unresolved"):
        loc.localize_unresolved_recovered_goals(
            video=vid, events_path=raw, recovery_path=recovery,
            out_dir=tmp_path / "results", candidate_ids=["already_known"],
        )


def test_all_pipeline_stages_valid_but_missing_goal_blocks_all_required(tmp_path):
    fresh = tmp_path / "fresh"
    _write(fresh, "01_enrich/events_enriched.json", {"events": [{"event_id": "one"}]})
    _write(fresh, "01_enrich/enrich_report.json", {"n_injected": 0})
    _write(fresh, "02_strip831/strip_A_original.json", {"n_chains": 1, "chains": [{}]})
    _write(fresh, "03_v1_adapt/goal_recovery.json", {
        "n_candidates": 1, "n_single_goal": 1,
        "n_with_goal_action_sec": 0,
        "candidates": [{"candidate_id": "score_01_to_11",
                        "single_goal_increment": True, "goal_action_sec": None}],
    })
    _write(fresh, "03_v1_adapt/goal_recovery_impact.json", {"entered_predicted_causal": True})
    _write(fresh, "03_v1_adapt/predicted_causal.json", {
        "causal_chains": [{"events": []}],
        "v3_adapter": {"goal_recovery_used": True, "n_v3_outcome_chains": 1},
    })
    _write(fresh, "03_v1_adapt/predicted_causal_live_goals_only.json", {})
    _write(fresh, "04_phase5/candidate_edl.json", [
        {"segment_id": "scoreboard", "media_in": 100, "media_out": 103},
    ])
    mp4 = fresh / "04_phase5/story_clean.mp4"
    mp4.write_bytes(b"0" * 50000)
    _write(fresh, "05_live_audit/goal_live_audit.json", {"n_goal_terminals": 1})
    _write(fresh, "05_live_audit/first_live_visual_audit.json", {
        "n_goal_anchors": 1,
        "goals": [{"candidate_extracted_ok": True, "first_live_status": "UNRESOLVED"}],
        "any_first_live_verified": False, "success_claimed": False,
        "status_counts": {"UNRESOLVED": 1},
    })
    _write(tmp_path, "99_final/delivery_status.json", {
        "delivery_status": "BLOCKED", "release_authorized": False,
    })
    _write(tmp_path, "99_final/final_goal_evidence_manifest.json", {
        "label": "final_delivery", "n_goal_anchors": 1, "success_claimed": False,
    })
    _write(tmp_path, "99_final/goal_lineage_report.json", {
        "n_final_goal_segments": 1, "n_strict_complete": 1,
        "n_inferred": 0, "n_unresolved": 0,
    })
    result = evaluate_stages(
        out_dir=tmp_path, fresh_root=fresh,
        delivery={"delivery_status": "BLOCKED"},
    )
    assert result["pipeline_stages_valid"] is True
    assert all(r["valid"] for r in result["stages"].values())
    assert result["story_goal_actions_present"] is False
    assert "03_score_confirmed_goal_action_missing" in result["blocking_errors"]
    assert result["all_required_valid"] is False
    assert result["release_ready"] is False
