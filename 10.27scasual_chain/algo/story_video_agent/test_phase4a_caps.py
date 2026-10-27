"""Phase 4A：HTTP 限额合并与计数（成功/失败/429）；无计费。"""

from __future__ import annotations

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
from story_video_agent.phase4a_config import Phase4AConfig
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


if __name__ == "__main__":
    unittest.main()
