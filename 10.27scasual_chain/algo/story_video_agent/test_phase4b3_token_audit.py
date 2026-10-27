"""Phase 4B.3：Token/Thinking 参数兼容、超限阻断、角色隔离（Mock，无计费）。"""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from story_video_agent.api_provider import (
    ApiCallError,
    ApiProvider,
    EndpointConfig,
    extract_usage_audit,
    load_endpoint_configs,
)
from story_video_agent.phase4a_config import Phase4AConfig
from story_video_agent.media import MediaInfo


def _cfg(
    *,
    role: str = "vision",
    token_param: str = "max_tokens",
    max_completion_tokens=256,
    send_thinking: bool = False,
    enable_thinking=None,
    thinking_budget=None,
) -> EndpointConfig:
    return EndpointConfig(
        role=role,
        base_url="https://example.test/v1",
        api_key="sk-test-not-real",
        model="Qwen3.6-Plus" if role == "vision" else "DeepSeek-V4-Pro-0813",
        max_retries=0,
        token_param=token_param,
        max_completion_tokens=max_completion_tokens,
        send_thinking_params=send_thinking,
        enable_thinking=enable_thinking,
        thinking_budget=thinking_budget,
    )


class RequestBodyCompatTests(unittest.TestCase):
    def test_phase4b2_style_sends_max_tokens_256(self) -> None:
        api = ApiProvider(
            force_mock=False,
            require_real=True,
            configs={"vision": _cfg(), "planner": _cfg(role="planner")},
            max_calls=3,
            max_completion_tokens=256,
            required_roles=["vision"],
        )
        body, audit = api.build_chat_request_body(
            api.configs["vision"],
            messages=[{"role": "user", "content": "x"}],
            temperature=0.1,
        )
        self.assertEqual(body.get("max_tokens"), 256)
        self.assertNotIn("max_completion_tokens", body)
        self.assertNotIn("enable_thinking", body)
        self.assertEqual(audit["token_param_sent"], "max_tokens")
        self.assertEqual(audit["token_limit_sent"], 256)
        self.assertFalse(audit["thinking_params_sent"])

    def test_vlm_can_use_max_completion_tokens_without_affecting_planner_default(self) -> None:
        vision = _cfg(token_param="max_completion_tokens", max_completion_tokens=256)
        planner = _cfg(role="planner", token_param="max_tokens", max_completion_tokens=128)
        api = ApiProvider(
            force_mock=False,
            require_real=True,
            configs={"vision": vision, "planner": planner},
            max_calls=3,
            max_completion_tokens=512,
            required_roles=["vision", "planner"],
        )
        vb, va = api.build_chat_request_body(
            vision, messages=[{"role": "user", "content": "v"}], temperature=0.1
        )
        pb, pa = api.build_chat_request_body(
            planner, messages=[{"role": "user", "content": "p"}], temperature=0.1
        )
        self.assertEqual(vb.get("max_completion_tokens"), 256)  # min(256,512)
        self.assertNotIn("max_tokens", vb)
        self.assertEqual(pb.get("max_tokens"), 128)
        self.assertNotIn("max_completion_tokens", pb)
        self.assertEqual(va["token_param_sent"], "max_completion_tokens")
        self.assertEqual(pa["token_param_sent"], "max_tokens")

    def test_thinking_not_sent_unless_opt_in(self) -> None:
        cfg = _cfg(send_thinking=False, enable_thinking=False, thinking_budget=64)
        api = ApiProvider(
            force_mock=False,
            require_real=True,
            configs={"vision": cfg, "planner": _cfg(role="planner")},
            required_roles=["vision"],
        )
        body, audit = api.build_chat_request_body(
            cfg, messages=[{"role": "user", "content": "x"}], temperature=0.0
        )
        self.assertNotIn("enable_thinking", body)
        self.assertNotIn("thinking_budget", body)
        self.assertFalse(audit["thinking_params_sent"])

    def test_thinking_sent_only_when_opt_in(self) -> None:
        cfg = _cfg(send_thinking=True, enable_thinking=False, thinking_budget=64)
        api = ApiProvider(
            force_mock=False,
            require_real=True,
            configs={"vision": cfg, "planner": _cfg(role="planner")},
            required_roles=["vision"],
        )
        body, audit = api.build_chat_request_body(
            cfg, messages=[{"role": "user", "content": "x"}], temperature=0.0
        )
        self.assertIs(body.get("enable_thinking"), False)
        self.assertEqual(body.get("thinking_budget"), 64)
        self.assertTrue(audit["thinking_params_sent"])


class UsageAuditAndBlockTests(unittest.TestCase):
    def test_extract_usage_audit_missing_fields_not_invented(self) -> None:
        payload = {
            "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        }
        audit = extract_usage_audit(payload, content="hello")
        self.assertEqual(audit["finish_reason"], "stop")
        self.assertIsNone(audit["reasoning_tokens"])
        self.assertFalse(audit["has_completion_tokens_details"])
        self.assertFalse(audit["reasoning_content_present"])
        self.assertEqual(audit["visible_output_chars"], 5)

    def test_extract_reasoning_tokens_when_present(self) -> None:
        payload = {
            "choices": [
                {
                    "message": {"content": "ans", "reasoning_content": "SECRET_THOUGHT"},
                    "finish_reason": "length",
                }
            ],
            "usage": {
                "completion_tokens": 100,
                "completion_tokens_details": {"reasoning_tokens": 80},
            },
        }
        audit = extract_usage_audit(payload, content="ans")
        self.assertEqual(audit["reasoning_tokens"], 80)
        self.assertTrue(audit["reasoning_content_present"])
        # 审计不得带回思考原文
        blob = json.dumps(audit)
        self.assertNotIn("SECRET_THOUGHT", blob)

    def test_over_budget_blocks_subsequent_request(self) -> None:
        configs = {
            "vision": _cfg(max_completion_tokens=256),
            "planner": _cfg(role="planner"),
        }
        with mock.patch.dict(os.environ, {"STORY_API_MAX_CALLS": "3"}, clear=False):
            api = ApiProvider(
                force_mock=False,
                require_real=True,
                configs=configs,
                max_calls=3,
                max_completion_tokens=256,
                required_roles=["vision"],
            )

            def fake_post(_cfg, *, body):
                self.assertEqual(body.get("max_tokens"), 256)
                return {
                    "choices": [
                        {"message": {"content": "x" * 10}, "finish_reason": "stop"}
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 3195,  # 超过 256
                        "total_tokens": 3205,
                    },
                }

            with mock.patch.object(api, "_post_chat", side_effect=fake_post):
                r1 = api.chat(
                    role="vision",
                    messages=[{"role": "user", "content": "a"}],
                    cache_key="k1",
                    allow_degraded_fallback=False,
                )
            self.assertTrue(r1["response_audit"]["output_budget_exceeded"])
            self.assertEqual(r1["usage"]["completion_tokens"], 3195)  # 不篡改
            self.assertTrue(api.stats.calls[-1].output_budget_exceeded)
            self.assertEqual(api.stats.calls[-1].finish_reason, "stop")

            with self.assertRaises(ApiCallError) as ctx:
                api.chat(
                    role="vision",
                    messages=[{"role": "user", "content": "b"}],
                    cache_key="k2",
                    allow_degraded_fallback=False,
                )
            self.assertEqual(ctx.exception.failure_status, "output_budget_exceeded")
            # 阻断发生在 HTTP 之前：http_attempts 仍为 1
            self.assertEqual(api._http_attempts, 1)


class RoleEnvIsolationTests(unittest.TestCase):
    def test_load_endpoint_configs_per_role_env(self) -> None:
        env = {
            "STORY_LLM_BASE_URL": "https://example.test/v1",
            "STORY_LLM_API_KEY": "sk-x",
            "STORY_LLM_MODEL": "DeepSeek-V4-Pro-0813",
            "STORY_VLM_MODEL": "Qwen3.6-Plus",
            "STORY_API_TOKEN_PARAM": "max_tokens",
            "STORY_VLM_TOKEN_PARAM": "max_completion_tokens",
            "STORY_VLM_MAX_COMPLETION_TOKENS": "256",
            "STORY_PLANNER_MAX_COMPLETION_TOKENS": "128",
            "STORY_VLM_SEND_THINKING": "",
            "STORY_PLANNER_SEND_THINKING": "",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            cfgs = load_endpoint_configs()
        self.assertEqual(cfgs["vision"].token_param, "max_completion_tokens")
        self.assertEqual(cfgs["planner"].token_param, "max_tokens")
        self.assertEqual(cfgs["vision"].max_completion_tokens, 256)
        self.assertEqual(cfgs["planner"].max_completion_tokens, 128)
        self.assertFalse(cfgs["vision"].send_thinking_params)


class WindowProvenanceTests(unittest.TestCase):
    def test_shrink_next_window_not_written_when_max_rounds_1(self) -> None:
        """规则 shrink 的 next_window 不等于已观察并写入的候选窗。"""
        from story_video_agent.phase4a_optimize import rule_decide_next_window

        media = MediaInfo(
            path="/v.mp4",
            duration_sec=4000.0,
            width=1280,
            height=720,
            fps=25.0,
            video_codec="h264",
            audio_codec="aac",
            start_time_sec=0.0,
            format_name="mp4",
            size_bytes=1,
        )
        window = {"start": 3059.903, "end": 3071.903}
        labels = {
            "labels": ["goal", "shot", "celebration"],
            "primary": "goal",
            "confidence": 0.95,
        }
        dec = rule_decide_next_window(
            target={"kind": "action_verify", "score_anchor_sec": 3145.98},
            window=window,
            labels=labels,
            media=media,
            cfg=Phase4AConfig(max_rounds=1),
            round_idx=0,
        )
        self.assertEqual(dec["action"], "shrink")
        self.assertEqual(dec["next_window"]["start"], 3062.903)
        self.assertEqual(dec["next_window"]["end"], 3068.903)
        # 与 Phase4B.2 一致：观察窗仍是 seed 全窗，不是 shrink 结果
        self.assertNotEqual(dec["next_window"], window)


if __name__ == "__main__":
    unittest.main()
