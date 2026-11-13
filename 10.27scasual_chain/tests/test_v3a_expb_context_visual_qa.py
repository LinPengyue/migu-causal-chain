"""Experiment B source-context image QA: zero-HTTP regression and fake provider."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import story_video_agent_v3.expb_context_visual_qa_cli as qa


class FakeStats:
    def summary(self):
        return {"est_cost_usd_real": 0.002, "by_role": {}}


class FakeApi:
    def __init__(self, reply=None, mode="real"):
        self.max_calls = 1
        self.max_cost_usd = 0.10
        self.configs = {"vision": SimpleNamespace(max_retries=0)}
        self._http_attempts = 0
        self.stats = FakeStats()
        self.mode = mode
        self.messages = None
        self.reply = reply

    def chat(self, **kw):
        self._http_attempts += 1
        self.messages = kw["messages"]
        assert kw["cache_key"] is None
        assert kw["allow_degraded_fallback"] is False
        content = self.messages[1]["content"]
        assert not any(x.get("type") == "video_url" for x in content)
        assert sum(x.get("type") == "image_url" for x in content) == 3
        return {
            "provider_mode": self.mode, "model": "FAKE_NO_HTTP",
            "content": json.dumps(self.reply or {
                "observations": [
                    {"phase": "ACTIVE_PLAY_BEFORE", "frame_id": "before",
                     "source_pts_sec": 90.0, "visible_cue": "players visibly attacking"},
                    {"phase": "GOAL_SHOT_NET", "frame_id": "goal",
                     "source_pts_sec": 101.0, "visible_cue": "net and ball visible nearby"},
                    {"phase": "IMMEDIATE_CELEBRATION", "frame_id": "after",
                     "source_pts_sec": 105.0, "visible_cue": "players raising arms by goal"},
                ],
                "uncertainties": ["no continuous video or prior occurrence review"],
                "visual_limitations": ["three isolated stills"],
            }),
        }


def setup_inputs(tmp_path, monkeypatch):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"fake source identity bytes")
    sha = hashlib.sha256(video.read_bytes()).hexdigest()
    manifest = tmp_path / "original_frame_manifest.json"
    log = tmp_path / "automated_semantic_log.json"
    diag = tmp_path / "story_diagnosis.json"
    manifest.write_text("{}", encoding="utf-8")
    log.write_text("{}", encoding="utf-8")
    diag.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        qa, "resolve_reverified_archived_goal_anchors",
        lambda **kw: {"ok": True, "status": "ARCHIVED_REAL_GOAL_SOURCE_ANCHORS_REVALIDATED",
                      "shot_sec": 100.0, "net_sec": 103.0},
    )
    monkeypatch.setattr(
        qa, "match_archived_anchors_to_current_goal_issue",
        lambda **kw: {"ok": True, "issue_id": "goal_coverage_fixture"},
    )

    def fake_extract(**kw):
        path = Path(kw["out_dir"])
        path.mkdir(parents=True, exist_ok=True)
        frames = []
        for fid, sec in [("before", 90.0), ("goal", 101.0), ("after", 105.0)]:
            frame = path / (fid + ".jpg")
            frame.write_bytes(("JPEG " + fid).encode())
            frames.append({
                "frame_id": fid, "path": str(frame),
                "actual_media_sec": sec, "requested_media_sec": sec,
                "pts_status": "pts", "sha256": qa.sha256_file(frame),
                "bytes": frame.stat().st_size,
            })
        return frames

    monkeypatch.setattr(qa, "extract_context_frames", fake_extract)
    return {
        "source_mp4": video, "source_sha256": sha,
        "frame_manifest": manifest, "semantic_log": log,
        "story_diagnosis": diag,
    }


def test_zero_http_by_default(tmp_path, monkeypatch):
    kw = setup_inputs(tmp_path, monkeypatch)
    result = qa.run_context_qa(**kw, out_dir=tmp_path / "preflight")
    assert result["status"] == "READY_ZERO_HTTP_PREFLIGHT", result
    assert result["n_real_http_calls"] == 0
    assert result["first_live_verified"] is False
    assert result["edl_modified"] is False
    assert result["issue_id"] == "goal_coverage_fixture"
    assert len(result["image_frames"]) == 3
    assert (tmp_path / "preflight" / "expb_context_visual_qa_report.json").is_file()


def test_opt_in_only_one_image_http_and_observation_not_first_live(tmp_path, monkeypatch):
    kw = setup_inputs(tmp_path, monkeypatch)
    api = FakeApi()
    result = qa.run_context_qa(
        **kw, out_dir=tmp_path / "paid_fake",
        execute_real=True, approve_budget=True, api=api,
    )
    assert api._http_attempts == 1
    assert result["n_real_http_calls"] == 1
    assert result["status"] == "LIVE_SEQUENCE_SUPPORTED", result
    assert result["validation"]["model_reported_only"] is True
    assert result["first_live_verified"] is False
    assert result["edl_modified"] is False
    assert result["best_modified"] is False
    assert (tmp_path / "paid_fake" / "original_model_response.txt").is_file()


@pytest.mark.parametrize("execute_real,approve_budget", [(True, False), (False, True)])
def test_partial_approval_blocks_every_http(tmp_path, monkeypatch, execute_real, approve_budget):
    kw = setup_inputs(tmp_path, monkeypatch)
    api = FakeApi()
    with pytest.raises(ValueError, match="both_explicit_flags"):
        qa.run_context_qa(
            **kw, out_dir=tmp_path / "invalid",
            execute_real=execute_real, approve_budget=approve_budget, api=api,
        )
    assert api._http_attempts == 0


def test_bad_frame_citation_never_supports_live(tmp_path, monkeypatch):
    kw = setup_inputs(tmp_path, monkeypatch)
    api = FakeApi(reply={"observations": [
        {"phase": "ACTIVE_PLAY_BEFORE", "frame_id": "invented",
         "source_pts_sec": 90., "visible_cue": "players visibly attacking"},
    ]})
    result = qa.run_context_qa(
        **kw, out_dir=tmp_path / "forged",
        execute_real=True, approve_budget=True, api=api,
    )
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["validation"]["ok"] is False
    assert result["first_live_verified"] is False


def test_goal_preceded_by_celebration_is_replay_suspected_not_certified():
    frames = [
        {"frame_id": "before", "actual_media_sec": 90.0},
        {"frame_id": "goal", "actual_media_sec": 101.0},
    ]
    result = qa.validate_observations(
        {"observations": [
            {"phase": "PRE_GOAL_CELEBRATION", "frame_id": "before",
             "source_pts_sec": 90., "visible_cue": "players embracing and celebrating"},
            {"phase": "GOAL_SHOT_NET", "frame_id": "goal",
             "source_pts_sec": 101., "visible_cue": "ball inside the goal frame"},
        ]}, frames=frames, shot=100., net=103.,
    )
    assert result["status"] == "REPLAY_SUSPECTED"
    assert result["first_live_verified"] is False


def test_nonreal_provider_is_rejected_and_reported(tmp_path, monkeypatch):
    kw = setup_inputs(tmp_path, monkeypatch)
    api = FakeApi(mode="mock")
    result = qa.run_context_qa(
        **kw, out_dir=tmp_path / "mock",
        execute_real=True, approve_budget=True, api=api,
    )
    assert result["n_real_http_calls"] == 1  # fake counter only, no network
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert "model_response_not_real" in result["blocked_or_failed_reason"]


def test_provider_with_retries_is_blocked_before_call(tmp_path, monkeypatch):
    kw = setup_inputs(tmp_path, monkeypatch)
    api = FakeApi()
    api.configs["vision"].max_retries = 1
    result = qa.run_context_qa(
        **kw, out_dir=tmp_path / "retry_block",
        execute_real=True, approve_budget=True, api=api,
    )
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert api._http_attempts == 0
    assert "provider_not_limited" in result["blocked_or_failed_reason"]


def test_source_identity_mismatch_blocks_preflight(tmp_path, monkeypatch):
    kw = setup_inputs(tmp_path, monkeypatch)
    kw["source_sha256"] = "0" * 64
    result = qa.run_context_qa(**kw, out_dir=tmp_path / "bad_source")
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["n_real_http_calls"] == 0
    assert result["blocked_or_failed_reason"].endswith("source_mp4_sha256_mismatch")
