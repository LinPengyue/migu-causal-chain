"""Phase 2C.1：HTTP 计数、failure_status、smoke 预检（无计费）。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_video_agent.api_provider import (
    COST_DISCLAIMER,
    ApiCallError,
    ApiProvider,
    EndpointConfig,
    smoke_enabled,
)
from story_video_agent.smoke_api import (
    SmokePreflightError,
    _assert_real_not_mock,
    _interpret_planner,
    main as smoke_main,
    preflight,
)
from story_video_agent.vision_provider import (
    EvidenceNormalizationError,
    VisionProvider,
    classify_normalization_failure,
    normalize_evidence,
)


def _cfg(ok: bool = True) -> dict:
    if ok:
        return {
            "planner": EndpointConfig(
                "planner", "https://example.invalid/v1", "k", "m-plan"
            ),
            "vision": EndpointConfig(
                "vision", "https://example.invalid/v1", "k", "m-vis"
            ),
        }
    return {
        "planner": EndpointConfig("planner", "", "", ""),
        "vision": EndpointConfig("vision", "", "", ""),
    }


class Phase2C1Tests(unittest.TestCase):
    def test_cost_disclaimer_present(self) -> None:
        self.assertIn("NOT a billing guarantee", COST_DISCLAIMER)
        api = ApiProvider(force_mock=True)
        self.assertIn("NOT a billing guarantee", api.stats.summary()["cost_disclaimer"])

    def test_http_attempts_count_failures_and_retries(self) -> None:
        api = ApiProvider(
            force_mock=False,
            require_real=True,
            configs=_cfg(True),
            max_calls=10,
            required_roles=["planner"],
        )
        cfg = api.configs["planner"]
        cfg.max_retries = 2
        calls = {"n": 0}

        def boom(*_a, **_k):
            calls["n"] += 1
            raise ApiCallError("HTTP 429", retryable=True, http_status=429)

        with mock.patch.object(api, "_post_chat", side_effect=boom), mock.patch(
            "story_video_agent.api_provider.time.sleep"
        ):
            with self.assertRaises(ApiCallError) as ctx:
                api.chat(
                    role="planner",
                    messages=[{"role": "user", "content": "x"}],
                    allow_degraded_fallback=False,
                )
        self.assertEqual(ctx.exception.failure_status, "http_429")
        self.assertEqual(api._http_attempts, 3)  # initial + 2 retries
        summary = api.stats.summary()
        self.assertEqual(summary["http_attempts"], 3)
        self.assertEqual(summary["real_failures"], 3)
        self.assertEqual(summary["cached_hits"], 0)

    def test_cache_hit_excluded_from_http_cap(self) -> None:
        api = ApiProvider(
            force_mock=False,
            require_real=True,
            configs=_cfg(True),
            max_calls=1,
            required_roles=["planner"],
        )

        def ok_payload(*_a, **_k):
            return {
                "choices": [{"message": {"content": '{"type":"answer"}'}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }

        with mock.patch.object(api, "_post_chat", side_effect=ok_payload):
            r1 = api.chat(
                role="planner",
                messages=[{"role": "user", "content": "x"}],
                cache_key="k1",
            )
            r2 = api.chat(
                role="planner",
                messages=[{"role": "user", "content": "x"}],
                cache_key="k1",
            )
        self.assertEqual(r1["provider_mode"], "real")
        self.assertEqual(r2["provider_mode"], "cache")
        self.assertEqual(api._http_attempts, 1)
        self.assertEqual(api.stats.summary()["cached_hits"], 1)
        # second real would exceed cap
        with mock.patch.object(api, "_post_chat", side_effect=ok_payload):
            with self.assertRaises(ApiCallError) as ctx:
                api.chat(
                    role="planner",
                    messages=[{"role": "user", "content": "y"}],
                    cache_key="k2",
                )
        self.assertEqual(ctx.exception.failure_status, "budget_exhausted")

    def test_max_completion_tokens_in_request_body(self) -> None:
        cfg = _cfg(True)
        cfg["planner"].token_param = "max_tokens"
        api = ApiProvider(
            force_mock=False,
            require_real=True,
            configs=cfg,
            max_completion_tokens=128,
            required_roles=["planner"],
        )
        captured = {}

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(
                    {
                        "choices": [{"message": {"content": "{}"}}],
                        "usage": {
                            "prompt_tokens": 1,
                            "completion_tokens": 1,
                            "total_tokens": 2,
                        },
                    }
                ).encode()

        def fake_urlopen(req, timeout=0):
            captured["body"] = json.loads(req.data.decode())
            return _Resp()

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            api.chat(role="planner", messages=[{"role": "user", "content": "hi"}])
        self.assertEqual(captured["body"]["max_tokens"], 128)
        self.assertNotIn("max_completion_tokens", captured["body"])

        cfg2 = _cfg(True)
        cfg2["planner"].token_param = "max_completion_tokens"
        api2 = ApiProvider(
            force_mock=False,
            require_real=True,
            configs=cfg2,
            max_completion_tokens=64,
            required_roles=["planner"],
        )
        captured2 = {}

        def fake_urlopen2(req, timeout=0):
            captured2["body"] = json.loads(req.data.decode())
            return _Resp()

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen2):
            api2.chat(role="planner", messages=[{"role": "user", "content": "hi"}])
        self.assertEqual(captured2["body"]["max_completion_tokens"], 64)
        self.assertNotIn("max_tokens", captured2["body"])

    def test_failure_status_timeout_and_empty_json(self) -> None:
        err = ApiCallError("timed out", retryable=True, http_status=0)
        self.assertEqual(err.failure_status, "timeout")
        with self.assertRaises(EvidenceNormalizationError) as ctx:
            normalize_evidence(
                {},
                gap_id="g",
                frame_ids=["f1"],
                frame_bindings=[],
                provider_mode="real",
            )
        self.assertEqual(ctx.exception.failure_status, "empty_json")
        with self.assertRaises(EvidenceNormalizationError) as ctx2:
            normalize_evidence(
                {
                    "frame_ids": ["nope"],
                    "observed_actions": ["x"],
                    "story_relation": "y",
                },
                gap_id="g",
                frame_ids=["f1"],
                frame_bindings=[],
                provider_mode="real",
            )
        self.assertEqual(ctx2.exception.failure_status, "invalid_frame_id")
        self.assertEqual(
            classify_normalization_failure("invalid frame_ids cited"),
            "invalid_frame_id",
        )

    def test_unrelated_visual_failure_status(self) -> None:
        api = ApiProvider(force_mock=True)
        vision = VisionProvider(api, force_mock=True)
        with mock.patch.object(
            api,
            "vision_json",
            return_value={
                "content": json.dumps(
                    {
                        "observed_actions": ["crowd"],
                        "story_relation": "unrelated scene",
                        "confidence": 0.2,
                        "frame_ids": ["f1"],
                    }
                ),
                "provider_mode": "real",
                "provider": "openai_compatible",
                "model": "m",
                "usage": {},
            },
        ):
            out = vision.describe_frames(
                gap_id="missing_setup_visual",
                gap_note="",
                frame_paths=[],
                frame_ids=["f1"],
                frame_bindings=[{"frame_id": "f1"}],
            )
        self.assertFalse(out.get("normalized_ok"))
        self.assertEqual(out.get("failure_status"), "unrelated_visual")

    def test_smoke_default_refuse(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("STORY_API")}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertFalse(smoke_enabled())
            code = smoke_main(
                [
                    "--mode",
                    "vlm-only",
                    "--story-json",
                    "/tmp/no.json",
                    "--video-path",
                    "/tmp/no.mp4",
                ]
            )
        self.assertEqual(code, 2)

    def test_preflight_checks_video_and_caps(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            story = Path(td) / "s.json"
            video = Path(td) / "v.mp4"
            story.write_text("{}", encoding="utf-8")
            # video missing
            with mock.patch.dict(
                os.environ,
                {
                    "STORY_API_SMOKE": "1",
                    "STORY_API_ENABLE": "1",
                    "STORY_LLM_BASE_URL": "https://x",
                    "STORY_LLM_API_KEY": "k",
                    "STORY_LLM_MODEL": "m",
                    "STORY_VLM_MODEL": "m",
                    "STORY_API_MAX_CALLS": "2",
                    "STORY_API_MAX_COST_USD": "0.01",
                },
                clear=False,
            ):
                with self.assertRaises(SmokePreflightError) as ctx:
                    preflight(
                        mode="vlm-only", story_json=story, video_path=video
                    )
                self.assertIn("video missing", str(ctx.exception))
                video.write_bytes(b"x")
                # missing cost cap
                env2 = {
                    k: v
                    for k, v in os.environ.items()
                    if k != "STORY_API_MAX_COST_USD"
                }
                env2.update(
                    {
                        "STORY_API_SMOKE": "1",
                        "STORY_API_ENABLE": "1",
                        "STORY_LLM_BASE_URL": "https://x",
                        "STORY_LLM_API_KEY": "k",
                        "STORY_LLM_MODEL": "m",
                        "STORY_VLM_MODEL": "m",
                        "STORY_API_MAX_CALLS": "2",
                    }
                )
                with mock.patch.dict(os.environ, env2, clear=True):
                    with self.assertRaises(SmokePreflightError) as ctx2:
                        preflight(
                            mode="vlm-only", story_json=story, video_path=video
                        )
                    self.assertIn("STORY_API_MAX_COST_USD", str(ctx2.exception))

    def test_assert_real_rejects_mock(self) -> None:
        with self.assertRaises(RuntimeError):
            _assert_real_not_mock("mock", context="test")

    def test_interpret_planner(self) -> None:
        self.assertEqual(
            _interpret_planner({"type": "answer", "answer": "finish_evidence_plan"}),
            "stop",
        )
        self.assertEqual(
            _interpret_planner(
                {
                    "type": "tool",
                    "tool": "refine_search_window",
                    "arguments": {"mode": "shrink"},
                }
            ),
            "refine:shrink",
        )
        self.assertEqual(
            _interpret_planner(
                {"type": "tool", "tool": "sample_next_evidence", "arguments": {}}
            ),
            "continue_search",
        )

    def test_required_roles_vision_only(self) -> None:
        cfg = {
            "planner": EndpointConfig("planner", "", "", ""),
            "vision": EndpointConfig(
                "vision", "https://example.invalid/v1", "k", "m-vis"
            ),
        }
        # vision-only ok
        ApiProvider(
            force_mock=False, require_real=True, configs=cfg, required_roles=["vision"]
        )
        with self.assertRaises(Exception):
            ApiProvider(
                force_mock=False,
                require_real=True,
                configs=cfg,
                required_roles=["vision", "planner"],
            )


if __name__ == "__main__":
    unittest.main()
