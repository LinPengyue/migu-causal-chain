"""Zero-HTTP contract tests for B1 launcher."""
import argparse
import json

import pytest

from algo.story_video_agent_v3.b1_human_assisted_e2e import preflight


def _args(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fake source for preflight only")
    match = tmp_path / "match.json"
    match.write_text("{}", encoding="utf-8")
    edl = tmp_path / "edl.json"
    edl.write_text(json.dumps([{"segment_id":"s1","media_in":1,"media_out":2,"include_in_cut":True}]), encoding="utf-8")
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    return argparse.Namespace(match_json=match, source_mp4=source, baseline_edl=edl,
        goal_repair_evidence_dir=reviews, first_live_evidence_dir=None,
        narrative_fit_evidence_dir=None, max_rounds=1)


def test_no_review_never_runs(tmp_path):
    args = _args(tmp_path)
    with pytest.raises(ValueError, match="human statement alone"):
        preflight(args)


def test_review_is_not_claimed_verified(tmp_path):
    args = _args(tmp_path)
    (args.goal_repair_evidence_dir / "issue.json").write_text("{}", encoding="utf-8")
    result = preflight(args)
    assert result["mode"] == "HUMAN_ASSISTED_DEV_NOT_AUTONOMOUS_NOT_BENCHMARK"
    assert result["paid_http_authorized"] is False
    assert result["release_authorized"] is False
    assert result["baseline_segment_count"] == 1


def test_missing_baseline_fails(tmp_path):
    args = _args(tmp_path)
    args.baseline_edl.unlink()
    with pytest.raises(ValueError, match="Missing inputs"):
        preflight(args)
