"""P10-G: playback/source cut relevance cannot be inferred from role names."""
from __future__ import annotations

import copy
import json

import pytest

from story_video_agent_v3.story_cut_relevance_audit import (
    audit_playback_observations, build_cut_relevance_inventory, main,
)
from story_video_agent_v3.story_timeline import build_story_timeline, story_time_to_media


def _edl():
    return [
        {"segment_id": "title", "role": "story_title", "shot_kind": "title_card",
         "media_in": None, "media_out": None, "placeholder_sec": 2.5},
        {"segment_id": "pre", "role": "buildup_action", "shot_kind": "live",
         "media_in": 10.0, "media_out": 14.0},
        {"segment_id": "score", "role": "equalizer_scoreboard_anchor", "shot_kind": "scoreboard_anchor",
         "media_in": 20.0, "media_out": 23.5},
        {"segment_id": "goal", "role": "equalizer_goal_action", "shot_kind": "live",
         "media_in": 30.0, "media_out": 52.0, "goal_action_complete": True},
    ]


def test_adjacent_boundary_maps_to_later_segment_exactly():
    tl = build_story_timeline(_edl())
    assert story_time_to_media(tl, 6.5)["segment_id"] == "score"
    assert story_time_to_media(tl, 10.0)["segment_id"] == "goal"
    assert story_time_to_media(tl, 32.0)["segment_id"] == "goal"
    assert story_time_to_media(tl, 32.001) is None


def test_timeline_inventory_does_not_conflate_protection_with_necessity():
    rows = build_cut_relevance_inventory(_edl())["segments"]
    by_id = {r["segment_id"]: r for r in rows}
    assert by_id["score"]["exploratory_edit_protected"]
    assert by_id["goal"]["exploratory_edit_protected"]
    assert not by_id["pre"]["exploratory_edit_protected"]
    assert all(r["narrative_necessity"] == "UNVERIFIED" for r in rows)


def test_boundary_conservatively_includes_both_source_bound_windows():
    report = audit_playback_observations(_edl(), [10.0], observation_radius_sec=0.2)
    obs = report["observations"][0]
    assert obs["nominal_segment_id"] == "goal"
    assert obs["status"] == "NEEDS_BOUNDARY_VIDEO_REVIEW"
    assert [s["segment_id"] for s in obs["candidate_segments"]] == ["score", "goal"]
    assert not obs["edit_authorized"]


def test_render_duration_discrepancy_expands_uncertainty_without_fake_offset():
    edl = _edl()
    report = audit_playback_observations(
        edl, [7.6], rendered_duration_sec=34.0, observation_radius_sec=0.5,
    )
    obs = report["observations"][0]
    assert report["effective_uncertainty_radius_sec"] == 2.5
    assert {s["segment_id"] for s in obs["candidate_segments"]} == {"pre", "score", "goal"}
    assert report["no_automatic_deletion"]


def test_no_label_or_segment_id_hardcoding_and_no_input_mutation():
    edl = _edl()
    before = copy.deepcopy(edl)
    report = audit_playback_observations(edl, [3.5], source_sha256="source-hash")
    assert edl == before
    assert report["not_agent_runtime_input"]
    assert report["source_sha256"] == "source-hash"
    assert report["source_sha_verified_here"] is False


def test_invalid_times_or_nonfinite_radius_fail_closed():
    report = audit_playback_observations(_edl(), [-1, 400])
    assert [o["status"] for o in report["observations"]] == [
        "INVALID_PLAYBACK_TIME", "OUTSIDE_EDL_DURATION",
    ]
    with pytest.raises(ValueError):
        audit_playback_observations(_edl(), [4], observation_radius_sec=float("nan"))
    with pytest.raises(ValueError):
        audit_playback_observations(_edl(), [4], rendered_duration_sec=-4)
    with pytest.raises(ValueError):
        audit_playback_observations(_edl(), [4], rendered_duration_sec=float("inf"))


def test_cli_outputs_read_only_json_for_runtime_edl(tmp_path):
    edl_path = tmp_path / "edl.json"
    output_path = tmp_path / "report.json"
    edl_path.write_text(json.dumps({"segments": _edl()}), encoding="utf-8")
    assert main([
        "--edl", str(edl_path), "--time", "6.5",
        "--rendered-duration-sec", "32", "--out", str(output_path),
    ]) == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["observations"][0]["status"] == "NEEDS_BOUNDARY_VIDEO_REVIEW"
    assert report["no_automatic_deletion"] is True
    assert json.loads(edl_path.read_text(encoding="utf-8")) == {"segments": _edl()}
