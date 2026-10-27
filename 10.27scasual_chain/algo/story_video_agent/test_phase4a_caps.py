"""Phase 4A：HTTP 限额合并与计数（成功/失败/429）；--targets / real dry-check；无计费。"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_video_agent.api_provider import (
    ApiCallError,
    ApiProvider,
    EndpointConfig,
    resolve_effective_caps,
)
from story_video_agent.phase4a_config import (
    CROATIA_SEED_EQUALIZER_LIVE_SEC,
    FIRST_REAL_VLM_ONLY,
    OFFICIAL_VIDEO_RSI_MODELS,
    Phase4AConfig,
    first_real_vlm_only_config,
    parse_targets,
    select_seed_targets,
)
from story_video_agent.phase4a_optimize import main as phase4a_main
from story_video_agent.phase4a_optimize import preflight_phase4a


def _cfg(ok: bool = True) -> dict:
    key = "sk-test" if ok else ""
    return {
        "planner": EndpointConfig(
            role="planner",
            base_url="https://example.test/v1",
            api_key=key,
            model="planner-model",
            max_retries=2,
            token_param="max_tokens",
        ),
        "vision": EndpointConfig(
            role="vision",
            base_url="https://example.test/v1",
            api_key=key,
            model="vision-model",
            max_retries=2,
            token_param="max_tokens",
        ),
    }


class CapMergeTests(unittest.TestCase):
    def test_stricter_of_env_and_explicit(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "STORY_API_MAX_CALLS": "3",
                "STORY_API_MAX_COST_USD": "0.05",
                "STORY_API_MAX_COMPLETION_TOKENS": "256",
            },
            clear=False,
        ):
            caps = resolve_effective_caps(max_calls=12, max_cost_usd=1.0, max_completion_tokens=512)
            self.assertEqual(caps["max_calls"], 3)
            self.assertEqual(caps["max_cost_usd"], 0.05)
            self.assertEqual(caps["max_completion_tokens"], 256)

            api = ApiProvider(
                force_mock=False,
                require_real=True,
                configs=_cfg(True),
                max_calls=12,
                required_roles=["vision"],
            )
            self.assertEqual(api.max_calls, 3)
            self.assertEqual(api.cap_sources["max_calls"]["explicit_value"], 12)
            self.assertEqual(api.cap_sources["max_calls"]["env_value"], "3")
            self.assertEqual(api.cap_sources["max_calls"]["effective"], 3)

    def test_phase4a_default_12_cannot_override_env_3(self) -> None:
        cfg = Phase4AConfig(max_api_calls=12)
        with mock.patch.dict(os.environ, {"STORY_API_MAX_CALLS": "3"}, clear=False):
            api = ApiProvider(
                force_mock=True,
                max_calls=cfg.max_api_calls,
                required_roles=["vision"],
            )
            self.assertEqual(api.max_calls, 3)


class HttpAttemptCapTests(unittest.TestCase):
    def test_success_fail_429_all_count_toward_max_3(self) -> None:
        """STORY_API_MAX_CALLS=3：成功 / 400 失败 / 429 各计 1 次 HTTP，第 4 次拒绝。"""
        with mock.patch.dict(os.environ, {"STORY_API_MAX_CALLS": "3"}, clear=False):
            api = ApiProvider(
                force_mock=False,
                require_real=True,
                configs=_cfg(True),
                max_calls=12,  # 应被 env=3 压低
                required_roles=["planner"],
                max_completion_tokens=64,
            )
            api.configs["planner"].max_retries = 0  # 禁止重试，便于精确计数
            self.assertEqual(api.max_calls, 3)

            call_n = {"i": 0}

            def side_effect(*_a, **_k):
                i = call_n["i"]
                call_n["i"] += 1
                if i == 0:
                    return {
                        "choices": [{"message": {"content": '{"ok":1}'}}],
                        "usage": {
                            "prompt_tokens": 1,
                            "completion_tokens": 1,
                            "total_tokens": 2,
                        },
                    }
                if i == 1:
                    raise ApiCallError(
                        "HTTP 400",
                        retryable=False,
                        http_status=400,
                        failure_status="http_400",
                    )
                if i == 2:
                    raise ApiCallError(
                        "HTTP 429",
                        retryable=False,  # max_retries=0 下直接记一次
                        http_status=429,
                        failure_status="http_429",
                    )
                raise AssertionError("4th HTTP should be blocked by cap before post")

            with mock.patch.object(api, "_post_chat", side_effect=side_effect):
                r = api.chat(
                    role="planner",
                    messages=[{"role": "user", "content": "a"}],
                    cache_key="c1",
                    allow_degraded_fallback=False,
                )
                self.assertEqual(r["provider_mode"], "real")
                self.assertEqual(api._http_attempts, 1)

                with self.assertRaises(ApiCallError) as ctx400:
                    api.chat(
                        role="planner",
                        messages=[{"role": "user", "content": "b"}],
                        cache_key="c2",
                        allow_degraded_fallback=False,
                    )
                self.assertEqual(ctx400.exception.failure_status, "http_400")
                self.assertEqual(api._http_attempts, 2)

                with self.assertRaises(ApiCallError) as ctx429:
                    api.chat(
                        role="planner",
                        messages=[{"role": "user", "content": "c"}],
                        cache_key="c3",
                        allow_degraded_fallback=False,
                    )
                self.assertEqual(ctx429.exception.failure_status, "http_429")
                self.assertEqual(api._http_attempts, 3)

                with self.assertRaises(ApiCallError) as ctx4:
                    api.chat(
                        role="planner",
                        messages=[{"role": "user", "content": "d"}],
                        cache_key="c4",
                        allow_degraded_fallback=False,
                    )
                self.assertEqual(ctx4.exception.failure_status, "budget_exhausted")
                self.assertEqual(api._http_attempts, 3)

    def test_exact_three_http_attempts_then_block(self) -> None:
        with mock.patch.dict(os.environ, {"STORY_API_MAX_CALLS": "3"}, clear=False):
            api = ApiProvider(
                force_mock=False,
                require_real=True,
                configs=_cfg(True),
                max_calls=99,
                required_roles=["planner"],
            )
            # force max_retries=0 so each chat = exactly one HTTP
            api.configs["planner"].max_retries = 0

            def ok(*_a, **_k):
                return {
                    "choices": [{"message": {"content": "{}"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }

            with mock.patch.object(api, "_post_chat", side_effect=ok):
                for i in range(3):
                    api.chat(
                        role="planner",
                        messages=[{"role": "user", "content": f"m{i}"}],
                        cache_key=f"k{i}",
                    )
                self.assertEqual(api._http_attempts, 3)
                with self.assertRaises(ApiCallError) as ctx:
                    api.chat(
                        role="planner",
                        messages=[{"role": "user", "content": "m3"}],
                        cache_key="k3",
                    )
                self.assertEqual(ctx.exception.failure_status, "budget_exhausted")


class DryCheckReportTests(unittest.TestCase):
    def test_dry_check_fields_no_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            story = Path(td) / "s.json"
            story.write_text("{}", encoding="utf-8")
            vid = Path(td) / "v.mp4"
            vid.write_bytes(b"\x00\x00")
            with mock.patch.dict(
                os.environ,
                {
                    "STORY_API_MAX_CALLS": "3",
                    "STORY_API_MAX_COST_USD": "0.08",
                    "STORY_API_MAX_COMPLETION_TOKENS": "128",
                    "STORY_API_TOKEN_PARAM": "max_tokens",
                },
                clear=False,
            ):
                pf = preflight_phase4a(
                    mode="vlm-only",
                    story_json=story,
                    video_path=vid,
                    force_mock=True,
                    max_api_calls=12,
                )
            self.assertTrue(pf.get("secrets_redacted"))
            text = json.dumps(pf)
            self.assertNotIn("sk-", text)
            self.assertNotIn("api_key\":", text.replace("api_key_set", ""))
            self.assertEqual(pf["effective_caps"]["max_calls"], 3)
            self.assertEqual(pf["effective_caps"]["max_cost_usd"], 0.08)
            self.assertEqual(pf["effective_caps"]["max_completion_tokens"], 128)
            self.assertIn("models", pf)
            self.assertIn("vendor_compat", pf)
            self.assertEqual(pf["vendor_compat"]["token_param"], "max_tokens")
            self.assertFalse(pf["http_requests_sent"])
            self.assertEqual(
                pf["official_video_rsi_models"]["planner"],
                OFFICIAL_VIDEO_RSI_MODELS["planner"],
            )
            self.assertEqual(
                pf["official_video_rsi_models"]["vision"],
                OFFICIAL_VIDEO_RSI_MODELS["vision"],
            )


class TargetsCliTests(unittest.TestCase):
    def test_parse_targets_default_both(self) -> None:
        self.assertEqual(
            parse_targets(None),
            ("equalizer_goal", "go_ahead_goal"),
        )

    def test_parse_targets_equalizer_only(self) -> None:
        self.assertEqual(parse_targets("equalizer_goal"), ("equalizer_goal",))
        self.assertEqual(parse_targets(["equalizer_goal"]), ("equalizer_goal",))

    def test_parse_targets_both_space_or_comma(self) -> None:
        self.assertEqual(
            parse_targets(["equalizer_goal", "go_ahead_goal"]),
            ("equalizer_goal", "go_ahead_goal"),
        )
        self.assertEqual(
            parse_targets("equalizer_goal,go_ahead_goal"),
            ("equalizer_goal", "go_ahead_goal"),
        )

    def test_parse_targets_rejects_unknown(self) -> None:
        with self.assertRaises(ValueError):
            parse_targets("winner_goal")

    def test_select_seed_equalizer_only_near_3065(self) -> None:
        seeds = select_seed_targets(["equalizer_goal"])
        self.assertEqual(len(seeds), 1)
        self.assertEqual(seeds[0]["target_id"], "equalizer_goal")
        self.assertAlmostEqual(
            float(seeds[0]["seed_center_sec"]),
            CROATIA_SEED_EQUALIZER_LIVE_SEC,
            places=3,
        )

    def test_first_real_vlm_only_profile(self) -> None:
        cfg = first_real_vlm_only_config(force_mock=True)
        self.assertEqual(cfg.targets, ("equalizer_goal",))
        self.assertEqual(cfg.max_rounds, 1)
        self.assertEqual(cfg.frames_per_round, 2)
        self.assertEqual(cfg.frame_budget, 4)
        self.assertEqual(cfg.max_api_calls, 3)
        self.assertEqual(FIRST_REAL_VLM_ONLY["max_completion_tokens"], 256)

    def test_cli_targets_equalizer_filters_seed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            story = Path(td) / "s.json"
            story.write_text("{}", encoding="utf-8")
            vid = Path(td) / "v.mp4"
            vid.write_bytes(b"\x00\x00")
            out = Path(td) / "out"
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                rc = phase4a_main(
                    [
                        "--story-json",
                        str(story),
                        "--video-path",
                        str(vid),
                        "--out-dir",
                        str(out),
                        "--mode",
                        "vlm-only",
                        "--targets",
                        "equalizer_goal",
                        "--dry-check",
                    ]
                )
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["targets"], ["equalizer_goal"])
            self.assertEqual(len(payload["seed_windows"]), 1)
            self.assertAlmostEqual(
                float(payload["seed_windows"][0]["seed_center_sec"]),
                CROATIA_SEED_EQUALIZER_LIVE_SEC,
                places=3,
            )
            self.assertFalse(payload["http_requests_sent"])


class RealModeDryCheckTests(unittest.TestCase):
    def test_real_dry_check_reports_config_without_http(self) -> None:
        """--real --dry-check：确认模型/端点/密钥/预算/兼容参数，绝不发 HTTP。"""
        with tempfile.TemporaryDirectory() as td:
            story = Path(td) / "s.json"
            story.write_text("{}", encoding="utf-8")
            vid = Path(td) / "v.mp4"
            vid.write_bytes(b"\x00\x00")
            out = Path(td) / "out"
            env = {
                "STORY_API_ENABLE": "1",
                "STORY_PHASE4A_REAL": "1",
                "STORY_API_SMOKE": "1",
                "STORY_LLM_BASE_URL": "https://example.test/v1",
                "STORY_LLM_API_KEY": "sk-test-not-for-http",
                "STORY_LLM_MODEL": "deepseek-v4-pro",
                "STORY_VLM_MODEL": "qwen3.6-plus",
                "STORY_API_MAX_CALLS": "3",
                "STORY_API_MAX_COST_USD": "0.10",
                "STORY_API_MAX_COMPLETION_TOKENS": "256",
                "STORY_API_TOKEN_PARAM": "max_tokens",
            }
            post_calls = {"n": 0}

            def _forbid_http(*_a, **_k):
                post_calls["n"] += 1
                raise AssertionError("dry-check must not send HTTP")

            buf = io.StringIO()
            with mock.patch.dict(os.environ, env, clear=False):
                with mock.patch(
                    "story_video_agent.api_provider.ApiProvider._post_chat",
                    side_effect=_forbid_http,
                ):
                    with mock.patch(
                        "urllib.request.urlopen",
                        side_effect=_forbid_http,
                    ):
                        with mock.patch("sys.stdout", buf):
                            rc = phase4a_main(
                                [
                                    "--story-json",
                                    str(story),
                                    "--video-path",
                                    str(vid),
                                    "--out-dir",
                                    str(out),
                                    "--mode",
                                    "vlm-only",
                                    "--targets",
                                    "equalizer_goal",
                                    "--max-rounds",
                                    "1",
                                    "--frames-per-round",
                                    "2",
                                    "--frame-budget",
                                    "4",
                                    "--max-api-calls",
                                    "3",
                                    "--max-completion-tokens",
                                    "256",
                                    "--real",
                                    "--dry-check",
                                ]
                            )
            self.assertEqual(rc, 0)
            self.assertEqual(post_calls["n"], 0)
            payload = json.loads(buf.getvalue())
            self.assertTrue(payload["dry_check"])
            self.assertTrue(payload["want_real"])
            self.assertFalse(payload["force_mock"])
            self.assertFalse(payload["http_requests_sent"])
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["targets"], ["equalizer_goal"])
            self.assertEqual(payload["effective_caps"]["max_calls"], 3)
            self.assertEqual(payload["effective_caps"]["max_cost_usd"], 0.10)
            self.assertEqual(payload["effective_caps"]["max_completion_tokens"], 256)
            self.assertTrue(payload["effective_caps"]["cost_is_estimate_not_invoice_cap"])
            self.assertEqual(payload["request_models"]["planner"], "deepseek-v4-pro")
            self.assertEqual(payload["request_models"]["vision"], "qwen3.6-plus")
            self.assertEqual(
                payload["official_video_rsi_models"]["planner"],
                "deepseek-v4-pro",
            )
            self.assertEqual(
                payload["official_video_rsi_models"]["vision"],
                "qwen3.6-plus",
            )
            self.assertTrue(payload["vendor_compat"]["vision_base_url_set"])
            self.assertTrue(payload["vendor_compat"]["vision_api_key_set"])
            self.assertTrue(payload["endpoint_ready"]["vision_configured"])
            self.assertEqual(payload["run_profile"]["max_rounds"], 1)
            self.assertEqual(payload["run_profile"]["frames_per_round"], 2)
            self.assertEqual(payload["run_profile"]["frame_budget"], 4)
            text = json.dumps(payload)
            self.assertNotIn("sk-test-not-for-http", text)
            self.assertIn("api_key_set", text)

    def test_real_dry_check_incomplete_still_no_http(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            story = Path(td) / "s.json"
            story.write_text("{}", encoding="utf-8")
            vid = Path(td) / "v.mp4"
            vid.write_bytes(b"\x00\x00")
            out = Path(td) / "out"
            # 清掉计费相关 env，仍应输出报告且不发 HTTP
            scrub = {
                k: ""
                for k in (
                    "STORY_API_ENABLE",
                    "STORY_PHASE4A_REAL",
                    "STORY_API_SMOKE",
                    "STORY_LLM_BASE_URL",
                    "STORY_LLM_API_KEY",
                    "STORY_LLM_MODEL",
                    "STORY_VLM_MODEL",
                    "OPENAI_BASE_URL",
                    "OPENAI_API_KEY",
                    "OPENAI_MODEL",
                )
            }
            buf = io.StringIO()
            with mock.patch.dict(os.environ, scrub, clear=False):
                with mock.patch(
                    "urllib.request.urlopen",
                    side_effect=AssertionError("no http"),
                ):
                    with mock.patch("sys.stdout", buf):
                        rc = phase4a_main(
                            [
                                "--story-json",
                                str(story),
                                "--video-path",
                                str(vid),
                                "--out-dir",
                                str(out),
                                "--mode",
                                "vlm-only",
                                "--targets",
                                "equalizer_goal",
                                "--real",
                                "--dry-check",
                            ]
                        )
            self.assertEqual(rc, 4)
            payload = json.loads(buf.getvalue())
            self.assertFalse(payload["ok"])
            self.assertFalse(payload["http_requests_sent"])
            self.assertTrue(len(payload["problems"]) >= 1)


if __name__ == "__main__":
    unittest.main()
