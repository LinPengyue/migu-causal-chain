"""P17 true native source MP4 observation, mocked API only; zero real HTTP."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from story_video_agent_v3.native_broadcast_observer import (
    observe_native_broadcast_phase,
)


class NoCallApi:
    def chat(self, **kwargs):
        raise AssertionError("must not call HTTP or a mocked provider")


class FakeUsage:
    def __init__(self):
        self.calls = 0

    def summary(self):
        return {"http_attempts": self.calls, "est_cost_usd_real": 0.0}


class FakeRealVideoApi:
    def __init__(self, observations=None, mode="real"):
        self.stats = FakeUsage()
        self.mode = mode
        self.messages = []
        self.observations = observations

    def chat(self, **kwargs):
        self.stats.calls += 1
        self.messages = kwargs["messages"]
        user_parts = self.messages[1]["content"]
        assert sum(1 for x in user_parts if x.get("type") == "video_url") == 1
        assert sum(1 for x in user_parts if x.get("type") == "image_url") >= 3
        assert user_parts[1]["video_url"]["url"].startswith(
            "data:video/mp4;base64,"
        )
        rows = self.observations
        if rows is None:
            rows = [
                {
                    "phase": "CONTINUOUS_LIVE_PLAY", "frame_id": "pre",
                    "source_pts_sec": 91.0,
                    "visible_cue": "visible normal-speed active play before shot",
                },
                {
                    "phase": "GOAL_SHOT_NET", "frame_id": "shot",
                    "source_pts_sec": 100.0,
                    "visible_cue": "ball travels into target from active play",
                },
                {
                    "phase": "IMMEDIATE_LIVE_REACTION", "frame_id": "reaction",
                    "source_pts_sec": 104.0,
                    "visible_cue": "players turn to celebrate without any cut",
                },
            ]
        return {
            "provider_mode": self.mode, "model": "fictional_fake_test_model",
            "content": json.dumps({
                "phase_observations": rows,
                "later_replay_status": "NO_REPLAY_OBSERVED_IN_REVIEWED_CONTEXT",
                "post_action_reviewed_through_sec": 110.0,
                "same_action_identity_evidence": None,
                "timeline_uncertainties": ["prior same-action airing NOT CHECKED"],
            }),
        }


def _prepare(tmp_path, monkeypatch):
    import story_video_agent.media as media_mod
    import story_video_agent_v3.native_broadcast_observer as phase_mod

    video = tmp_path / "source.mp4"
    video.write_bytes(b"source-identity-unique-video-bytes")
    sha = hashlib.sha256(video.read_bytes()).hexdigest()
    monkeypatch.setattr(
        media_mod, "probe_video",
        lambda v: SimpleNamespace(duration_sec=240.0),
    )

    def fake_clip(*, source_mp4, begin, end, output):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"synthetic compressed source context bytes")
        return {
            "ok": True, "path": str(output),
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "bytes": output.stat().st_size,
            "source_pts_start": begin, "source_pts_end": end,
        }

    def fake_extract(**kwargs):
        out = Path(kwargs["out_dir"])
        out.mkdir(parents=True, exist_ok=True)
        frames = []
        for fid, sec in (("pre", 91.0), ("shot", 100.0), ("reaction", 104.0)):
            p = out / (fid + ".jpg")
            p.write_bytes(("fake jpg " + fid).encode())
            frames.append({
                "frame_id": fid, "path": str(p),
                "actual_media_sec": sec, "requested_media_sec": sec,
                "pts_status": "pts",
            })
        return None, frames

    monkeypatch.setattr(phase_mod, "_source_context_video", fake_clip)
    monkeypatch.setattr(phase_mod, "extract_dense_frames", fake_extract)
    return video, sha


def test_default_no_authorization_is_exactly_zero_calls(tmp_path):
    result = observe_native_broadcast_phase(
        source_mp4=tmp_path / "missing.mp4",
        source_sha="a" * 64,
        shot_sec=100., net_sec=103.,
        api=NoCallApi(), out_dir=tmp_path / "no_call",
        approved=False, max_calls=5, max_cost_usd=0.1,
    )
    assert result["status"] == "SKIPPED_NOT_EXPLICITLY_AUTHORIZED"
    assert result["n_real_http_calls"] == 0
    assert result["first_live_verified"] is False
    assert result["edl_modified"] is False


def test_one_real_native_video_and_exact_source_pts_frames_observation_only(
    tmp_path, monkeypatch,
):
    video, sha = _prepare(tmp_path, monkeypatch)
    api = FakeRealVideoApi()
    result = observe_native_broadcast_phase(
        source_mp4=video, source_sha=sha, shot_sec=100., net_sec=102.,
        api=api, out_dir=tmp_path / "real_fake_http",
        approved=True, max_calls=5, max_cost_usd=0.1,
    )
    assert api.stats.calls == 1
    assert result["n_real_http_calls"] == 1
    assert result["status"] == "REAL_NATIVE_VIDEO_PHASE_OBSERVATION_ONLY", result
    assert result["native_video_model_input"] is True
    assert result["first_live_verified"] is False
    assert result["edl_modified"] is False
    assert result["independent_prior_occurrence_check"] == "NOT_PERFORMED"
    assert Path(result["model_response_path"]).is_file()
    assert result["model_response_sha256"] == hashlib.sha256(
        Path(result["model_response_path"]).read_bytes()
    ).hexdigest()


def test_source_mismatch_blocks_native_video_and_model_call(tmp_path, monkeypatch):
    video, _ = _prepare(tmp_path, monkeypatch)
    api = FakeRealVideoApi()
    result = observe_native_broadcast_phase(
        source_mp4=video, source_sha="f" * 64,
        shot_sec=100., net_sec=102.,
        api=api, out_dir=tmp_path / "wrong_source",
        approved=True, max_calls=5, max_cost_usd=0.1,
    )
    assert result["status"] == "SOURCE_SHA_MISMATCH_OR_VIDEO_MISSING"
    assert api.stats.calls == 0


def test_untrusted_video_model_frame_id_never_becomes_semantic_evidence(
    tmp_path, monkeypatch,
):
    video, sha = _prepare(tmp_path, monkeypatch)
    api = FakeRealVideoApi(observations=[{
        "phase": "GOAL_SHOT_NET", "frame_id": "invented_image_id",
        "source_pts_sec": 100.,
        "visible_cue": "claims to see a goal from a non-sent image",
    }])
    result = observe_native_broadcast_phase(
        source_mp4=video, source_sha=sha, shot_sec=100., net_sec=102.,
        api=api, out_dir=tmp_path / "forged_id",
        approved=True, max_calls=5, max_cost_usd=0.1,
    )
    assert result["status"] == "NATIVE_VIDEO_PHASE_CITATION_OR_TIMELINE_UNRESOLVED"
    assert result["temporal_observation_validation"]["reason"] == (
        "uncited_or_reused_model_input_frame"
    )
    assert result["phase_observations"] is None
    assert result["first_live_verified"] is False


def test_incomplete_video_phase_observation_is_not_a_positive_result(
    tmp_path, monkeypatch,
):
    video, sha = _prepare(tmp_path, monkeypatch)
    api = FakeRealVideoApi(observations=[{
        "phase": "GOAL_SHOT_NET", "frame_id": "shot",
        "source_pts_sec": 100.0,
        "visible_cue": "one goal image but no live temporal sequence",
    }])
    result = observe_native_broadcast_phase(
        source_mp4=video, source_sha=sha, shot_sec=100., net_sec=102.,
        api=api, out_dir=tmp_path / "incomplete_phase",
        approved=True, max_calls=5, max_cost_usd=0.1,
    )
    assert result["status"] == "NATIVE_VIDEO_PHASE_CITATION_OR_TIMELINE_UNRESOLVED"
    assert result["temporal_observation_validation"]["reason"] == (
        "incomplete_live_goal_reaction"
    )
    assert result["first_live_verified"] is False


def test_mock_video_provider_never_substitutes_real_video_review(
    tmp_path, monkeypatch,
):
    video, sha = _prepare(tmp_path, monkeypatch)
    api = FakeRealVideoApi(mode="mock")
    result = observe_native_broadcast_phase(
        source_mp4=video, source_sha=sha, shot_sec=100., net_sec=102.,
        api=api, out_dir=tmp_path / "fake_provider",
        approved=True, max_calls=5, max_cost_usd=0.1,
    )
    assert result["status"] == "NON_REAL_OR_EMPTY_VIDEO_MODEL_RESPONSE"
    assert result["first_live_verified"] is False


def test_budget_exhausted_prevents_video_upload(tmp_path):
    api = FakeRealVideoApi()
    api.stats.calls = 5
    result = observe_native_broadcast_phase(
        source_mp4=tmp_path / "missing_video.mp4", source_sha="a" * 64,
        shot_sec=100., net_sec=102.,
        api=api, out_dir=tmp_path / "budget",
        approved=True, max_calls=5, max_cost_usd=0.1,
    )
    assert result["status"] == "SKIPPED_SHARED_PROVIDER_BUDGET_EXHAUSTED"
    assert api.stats.calls == 5


def test_native_video_opt_in_is_separate_from_real_api_consent():
    from story_video_agent_v3.story_e2e_cli import build_parser
    from story_video_agent_v3.story_full_e2e_cli import (
        build_parser as build_full_parser, validate_inputs,
    )

    args = build_parser().parse_args([
        "--match-json", "missing.json", "--source-mp4", "missing.mp4",
        "--out-dir", "missing_out",
        "--enable-native-broadcast-observation",
    ])
    assert args.enable_native_broadcast_observation is True
    assert args.enable_real_api is False
    assert args.i_approve_budget is False

    full = build_full_parser().parse_args([
        "--source-mp4", "missing.mp4", "--events-json", "missing.json",
        "--out-dir", "missing_out", "--enable-native-broadcast-observation",
    ])
    assert "native_broadcast_observation_requires_real_api_and_budget_approval" in (
        validate_inputs(full)
    )
