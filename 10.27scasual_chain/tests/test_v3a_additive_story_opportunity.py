"""Focused zero-HTTP regression tests for V3-A additive video opportunity search."""
import hashlib
import json
from pathlib import Path

import pytest

from story_video_agent_v3.story_additive_opportunity import (
    build_opportunity_video_pack,
    discover_additive_opportunities,
)


SHA = "a" * 64


def _edl(*, goal_in=4920.0, prev_role="buildup_action", prev_out=2612.0):
    return [
        {"segment_id": "title", "role": "story_title", "media_in": None, "media_out": None},
        {"segment_id": "g1", "role": "opponent_opening_goal_action", "media_in": 100., "media_out": 122.},
        {"segment_id": "board0", "role": "deficit_scoreboard_anchor", "media_in": 150., "media_out": 153.},
        {"segment_id": "setup", "role": prev_role, "media_in": prev_out - 12, "media_out": prev_out},
        {"segment_id": "g2", "role": "equalizer_goal_action", "media_in": goal_in, "media_out": goal_in + 22},
        {"segment_id": "board1", "role": "equalizer_scoreboard_anchor", "media_in": goal_in + 80, "media_out": goal_in + 83},
        {"segment_id": "g3", "role": "go_ahead_goal_action", "media_in": goal_in + 350, "media_out": goal_in + 372},
        {"segment_id": "board2", "role": "go_ahead_scoreboard_anchor", "media_in": goal_in + 400, "media_out": goal_in + 403},
        {"segment_id": "close", "role": "story_wrap_title", "media_in": None, "media_out": None},
    ]


def test_recall_near_action_instead_of_remote_event_heat():
    data = discover_additive_opportunities(_edl(), source_sha256=SHA)
    assert data["source_window_count"] == 4
    assert len(data["opportunities"]) == 1
    item = data["opportunities"][0]
    assert item["before_segment_id"] == "setup"
    assert item["after_segment_id"] == "g2"
    assert item["hypothesis_status"] == "OPPORTUNITY_UNVERIFIED"
    assert item["story_defect_confirmed"] is False
    assert data["event_metadata_used_for_video_ranking"] is False
    assert all(4920-150 <= c["media_in"] < c["media_out"] <= 4920-4
               for c in item["source_video_windows"])
    assert all(c["edl_insert_authorized"] is False and
               c["first_live_verified"] is False for c in item["source_video_windows"])
    assert data["paid_http_calls"] == 0


def test_no_generic_gap_only_misdiagnosis():
    data = discover_additive_opportunities(
        _edl(prev_role="deficit_scoreboard_anchor"), source_sha256=SHA
    )
    assert data["opportunities"] == []


def test_no_probe_if_same_local_action():
    data = discover_additive_opportunities(
        _edl(goal_in=2712.0), source_sha256=SHA
    )
    assert data["opportunities"] == []


def test_respects_occupied_source_and_unavailable_duration():
    edl = _edl()
    # Covers the most recent probes. Those slots must not leak into the queue.
    edl.insert(3, {"segment_id": "already_used",
                   "role": "pressure_action",
                   "media_in": 4800, "media_out": 4920})
    # Put it before the buildup, preserving the key adjacent pair.
    data = discover_additive_opportunities(edl, source_sha256=SHA)
    assert data["opportunities"] == []
    # Empty candidate budget must not fabricate evidence.
    assert data["source_window_count"] == 0


def test_invalid_inputs_fail_closed():
    with pytest.raises(ValueError):
        discover_additive_opportunities(_edl(), source_sha256="unknown")
    with pytest.raises(ValueError):
        discover_additive_opportunities(_edl(), source_sha256=SHA, max_candidates=100)
    with pytest.raises(ValueError):
        discover_additive_opportunities(_edl(), source_sha256=SHA, window_sec=0)


def test_review_export_has_no_edit_or_live_claim(tmp_path, monkeypatch):
    from story_video_agent_v3 import story_additive_opportunity as mod

    source = tmp_path / "source.mp4"
    story = tmp_path / "story.mp4"
    source.write_bytes(b"faked_original_video_bytes")
    story.write_bytes(b"faked_story_video_bytes")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    data = discover_additive_opportunities(_edl(), source_sha256=source_sha)
    calls = []

    def fake_export(video, a, b, target):
        calls.append((video, a, b, target))
        return {"ok": True, "path": str(target), "semantic_status": "NOT_REVIEWED"}

    monkeypatch.setattr(mod, "_export_clip", fake_export)
    output = tmp_path / "review"
    report = build_opportunity_video_pack(
        opportunities=data, source_mp4=source, story_mp4=story,
        edl=_edl(), out_dir=output,
    )
    assert len(calls) == 5  # One finished-story seam + four original-video clips.
    assert sum(x[2] - x[1] for x in calls if x[0] == source) <= 48.001
    assert report["edl_modified"] is False
    assert report["release_authorized"] is False
    assert report["paid_http_calls"] == 0
    assert report["review_items"][0]["first_live_verified"] is False
    assert json.loads((output/"opportunity_video_manifest.json").read_text()) == report
    with pytest.raises(FileExistsError):
        build_opportunity_video_pack(
            opportunities=data, source_mp4=source, story_mp4=story,
            edl=_edl(), out_dir=output,
        )


def test_sha_mismatch_never_exports_source(tmp_path, monkeypatch):
    source, story = tmp_path/"src.mp4", tmp_path/"story.mp4"
    source.write_bytes(b"video")
    story.write_bytes(b"story")
    data = discover_additive_opportunities(_edl(), source_sha256=SHA)
    with pytest.raises(ValueError, match="source_sha256_mismatch"):
        build_opportunity_video_pack(
            opportunities=data, source_mp4=source, story_mp4=story,
            edl=_edl(), out_dir=tmp_path/"review",
        )
