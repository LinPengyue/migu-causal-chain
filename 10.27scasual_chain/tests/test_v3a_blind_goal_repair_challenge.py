"""No-HTTP, no-video regressions for blind V3-A goal-omission experiment.

Mock render verifies staging/evaluator separation only; these tests NEVER
demonstrate actual video understanding, recovery or FIRST_LIVE compliance.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from story_video_agent_v3.story_repair_challenge import (
    prepare_controlled, prepare_historical, prepare_clean_control, score_case,
    _run_dir,
)


def _write(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def _rows():
    return [
        {"segment_id": "opener", "role": "opponent_opening_goal_action",
         "media_in": 10.0, "media_out": 20.0},
        {"segment_id": "setup", "role": "deficit_scoreboard_anchor",
         "media_in": 22.0, "media_out": 24.0},
        {"segment_id": "equalizer", "role": "equalizer_goal_action",
         "media_in": 50.0, "media_out": 62.0},
        {"segment_id": "eq_board", "role": "equalizer_scoreboard_anchor",
         "media_in": 70.0, "media_out": 72.0},
        {"segment_id": "winner", "role": "go_ahead_goal_action",
         "media_in": 80.0, "media_out": 90.0},
    ]


def _base(tmp_path):
    complete = _write(tmp_path / "original_edl.json", _rows())
    plan = _write(tmp_path / "story_plan.json", {"title": "test"})
    raw = _write(tmp_path / "raw.json", {"events": []})
    video = tmp_path / "source.mp4"
    video.write_bytes(b"source_placeholder")
    return complete, plan, raw, video


def _fake_renderer(*, plan, video, edl, out_dir):
    assert not any(x["segment_id"] == "equalizer" for x in edl)
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / "story_clean.mp4"
    output.write_bytes(b"synthetic_broken_story")
    return {"ok": True, "story_clean": str(output)}


def _prepare(tmp_path):
    full, plan, raw, video = _base(tmp_path)
    case = tmp_path / "case"
    prepare_controlled(
        complete_edl=full, story_plan=plan, events_json=raw,
        source_mp4=video, case_dir=case, omitted_role="equalizer_goal_action",
        renderer=_fake_renderer,
    )
    return case, full


def test_blind_omission_inputs_do_not_contain_correct_edl(tmp_path):
    case, full = _prepare(tmp_path)
    broken = json.loads(
        (case / "agent_input/04_phase5/candidate_edl.json").read_text()
    )
    assert len(broken) == len(_rows()) - 1
    assert not any(row["segment_id"] == "equalizer" for row in broken)
    assert any(row["segment_id"] == "eq_board" for row in broken)
    assert any(row["segment_id"] == "winner" for row in broken)
    assert (case / "agent_input/04_phase5/story_clean.mp4").read_bytes() == (
        b"synthetic_broken_story"
    )
    assert not (case / "agent_input" / "private_eval").exists()
    assert "reference_action" not in (
        case / "run_manifest.json"
    ).read_text()
    private = json.loads((case / "private_eval/truth.json").read_text())
    assert private["reference_action"]["segment_id"] == "equalizer"
    assert json.loads(full.read_text()) == _rows()


def test_score_not_run_does_not_fabricate_repair(tmp_path):
    case, _ = _prepare(tmp_path)
    result = score_case(case)
    assert result["status"] == "NOT_RUN"
    assert result["missing_goal_count"] == 1
    assert result["no_quality_or_first_live_claim"] is True


def test_scorer_repair_needs_matching_source_window_not_only_goal_label(tmp_path):
    case, _ = _prepare(tmp_path)
    dest = case / "agent_run/99_final/final_edl.json"
    dest.parent.mkdir(parents=True)
    broken = json.loads((case / "agent_input/04_phase5/candidate_edl.json").read_text())
    _write(dest, broken + [{
        "segment_id": "made_up", "role": "equalizer_goal_action",
        "media_in": 120.0, "media_out": 125.0
    }])
    wrong = score_case(case)
    assert wrong["status"] == "NOT_REPAIRED"
    assert wrong["recovery"]["equalizer_goal_action"]["role_restored"]
    assert not wrong["recovery"]["equalizer_goal_action"]["source_window_overlap"]
    # Even matching oracle PTS can only establish the edited window, not the
    # visual correctness/first-LIVE or full-story quality.
    restored = broken[:2] + [{
        "segment_id": "agent_discovered_candidate", "role": "equalizer_goal_action",
        "media_in": 49.0, "media_out": 62.0, "is_replay": False
    }] + broken[2:]
    _write(dest, restored)
    assert score_case(case)["status"] == "EDL_WINDOW_RESTORED_NO_MP4"
    (dest.parent / "story_final.mp4").write_bytes(b"synthetic_video_only_not_verified")
    recovered = score_case(case)
    assert recovered["status"] == "EDL_WINDOW_RESTORED_UNVERIFIED"
    assert recovered["stage_observations"]["source_pts_monotonic_ok"]
    assert recovered["first_live_video_verified"] is False
    assert recovered["story_quality_improved"] == "UNVERIFIED"
    assert recovered["formal_benchmark"] is False


def test_historical_uses_only_failure_artifacts_and_raw_events(tmp_path):
    original, plan, raw, video = _base(tmp_path)
    phase5 = tmp_path / "failed_phase5"
    phase5.mkdir()
    broken = [x for x in _rows() if x["segment_id"] != "equalizer"]
    _write(phase5 / "candidate_edl.json", broken)
    _write(phase5 / "story_plan.json", {"title": "historical_failed"})
    (phase5 / "story_clean.mp4").write_bytes(b"historical_broken_cut")
    case = tmp_path / "historical_case"
    manifest = prepare_historical(
        failed_phase5=phase5, source_mp4=video,
        raw_events_json=raw, case_dir=case,
    )
    assert manifest["input_mode"] == "RAW_EVENTS_ONLY"
    assert not (case / "private_eval/truth.json").exists()
    assert (case / "agent_input/04_phase5/story_clean.mp4").read_bytes() == (
        b"historical_broken_cut"
    )
    with pytest.raises(FileNotFoundError, match="external_reference_edl"):
        score_case(case)
    assert score_case(case, external_reference_edl=original)["status"] == "NOT_RUN"


def test_oracle_inside_agent_input_cannot_be_submitted_as_reference(tmp_path):
    case, _ = _prepare(tmp_path)
    with pytest.raises(ValueError, match="reference_edl_not_private"):
        score_case(
            case, external_reference_edl=case / "agent_input/04_phase5/candidate_edl.json"
        )


def test_prepare_refuses_duplicate_goal_target_and_existing_output(tmp_path):
    full, plan, raw, video = _base(tmp_path)
    doubled = _rows() + [{
        "segment_id": "equalizer_2", "role": "equalizer_goal_action",
        "media_in": 63, "media_out": 67,
    }]
    _write(full, doubled)
    with pytest.raises(ValueError, match="exactly_one"):
        prepare_controlled(
            complete_edl=full, story_plan=plan, source_mp4=video,
            events_json=raw, case_dir=tmp_path / "c",
            omitted_role="equalizer_goal_action", renderer=_fake_renderer,
        )
    _write(full, _rows())
    case = tmp_path / "case_existing"
    case.mkdir()
    (case / "do_not_overwrite").write_bytes(b"safe")
    with pytest.raises(FileExistsError, match="must_be_new"):
        prepare_controlled(
            complete_edl=full, story_plan=plan, source_mp4=video,
            events_json=raw, case_dir=case,
            omitted_role="equalizer_goal_action", renderer=_fake_renderer,
        )


def test_clean_control_does_not_require_gold_and_detects_unnecessary_edit(tmp_path):
    original, plan, raw, video = _base(tmp_path)
    baseline_mp4 = tmp_path / "good.mp4"
    baseline_mp4.write_bytes(b"whole_original_story")
    case = tmp_path / "clean_case"
    manifest = prepare_clean_control(
        complete_edl=original, story_plan=plan, baseline_mp4=baseline_mp4,
        source_mp4=video, events_json=raw, case_dir=case,
    )
    assert manifest["variant"] == "CLEAN_NO_DEFECT_CONTROL"
    assert not (case / "private_eval/truth.json").exists()
    assert score_case(case)["status"] == "NOT_RUN"
    final = case / "agent_run/99_final/final_edl.json"
    final.parent.mkdir(parents=True)
    _write(final, _rows())
    assert score_case(case)["status"] == "NO_UNNECESSARY_EDL_EDIT"
    changed = _rows()
    changed[1]["media_out"] = 23.0
    _write(final, changed)
    flagged = score_case(case)
    assert flagged["status"] == "UNNECESSARY_EDL_EDIT"
    assert flagged["story_quality_improved"] == "UNVERIFIED"


def test_tagged_rerun_uses_existing_case_inputs_without_overwriting_baseline(tmp_path):
    case, _ = _prepare(tmp_path)
    first = case / "agent_run/99_final/final_edl.json"
    first.parent.mkdir(parents=True)
    _write(first, json.loads((case / "agent_input/04_phase5/candidate_edl.json").read_text()))
    second = _run_dir(case, "goal_coverage_v1")
    assert second == case / "agent_run_goal_coverage_v1"
    assert second != first.parent.parent
    assert score_case(case, run_id="goal_coverage_v1")["status"] == "NOT_RUN"
    new_edl = second / "99_final/final_edl.json"
    new_edl.parent.mkdir(parents=True)
    _write(new_edl, _rows())
    assert score_case(case, run_id="goal_coverage_v1")["status"] == (
        "EDL_WINDOW_RESTORED_NO_MP4"
    )
    assert first.is_file()
    with pytest.raises(ValueError, match="invalid_run_id"):
        _run_dir(case, "../private_eval")
