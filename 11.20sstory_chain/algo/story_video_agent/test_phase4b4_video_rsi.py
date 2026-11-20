"""Phase 4B.4：Video-RSI 兼容请求体 / 帧绑定 / 互斥 / 熔断（Mock，无计费）。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_video_agent.api_provider import (
    ApiCallError,
    ApiConfigError,
    ApiProvider,
    EndpointConfig,
    frame_time_binding_text,
    load_endpoint_configs,
    redact_request_body_for_diff,
)
from story_video_agent.internal_verification import sanitize_plan_trust
from story_video_agent.story_output_schema import build_render_ready_edl


def _base_cfgs(**vision_kw):
    vision = EndpointConfig(
        role="vision",
        base_url="https://example.test/v1",
        api_key="sk-test",
        model="Qwen3.6-Plus",
        max_retries=0,
        token_param="max_tokens",
        max_completion_tokens=256,
        default_temperature=0.0,
        stream=False,
        **vision_kw,
    )
    planner = EndpointConfig(
        role="planner",
        base_url="https://example.test/v1",
        api_key="sk-test",
        model="DeepSeek-V4-Pro-0813",
        max_retries=0,
        token_param="max_tokens",
        max_completion_tokens=128,
        request_profile="default",
        thinking_object_disabled=False,
        stream=False,
    )
    return {"vision": vision, "planner": planner}


class VideoRsiBodyTests(unittest.TestCase):
    def test_video_rsi_body_matches_official_shape_not_8192(self) -> None:
        api = ApiProvider(
            force_mock=False,
            require_real=True,
            configs=_base_cfgs(
                request_profile="video_rsi",
                thinking_object_disabled=True,
            ),
            max_calls=3,
            max_completion_tokens=256,
            required_roles=["vision"],
        )
        body, audit = api.build_chat_request_body(
            api.configs["vision"],
            messages=[{"role": "user", "content": "x"}],
            temperature=0.0,
        )
        self.assertEqual(body["temperature"], 0.0)
        self.assertEqual(body["stream"], False)
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertEqual(body["max_tokens"], 256)  # 项目 cap，非官方 8192
        self.assertNotEqual(body["max_tokens"], 8192)
        self.assertNotIn("enable_thinking", body)
        self.assertNotIn("thinking_budget", body)
        self.assertTrue(audit["thinking_object_disabled_sent"])
        self.assertFalse(audit["paratera_thinking_object_documented"])

    def test_thinking_formats_mutually_exclusive(self) -> None:
        api = ApiProvider(
            force_mock=False,
            require_real=True,
            configs=_base_cfgs(
                thinking_object_disabled=True,
                send_thinking_params=True,
                enable_thinking=False,
            ),
            required_roles=["vision"],
        )
        with self.assertRaises(ApiConfigError):
            api.build_chat_request_body(
                api.configs["vision"],
                messages=[{"role": "user", "content": "x"}],
                temperature=0.0,
            )

    def test_planner_default_unaffected_when_vlm_video_rsi(self) -> None:
        cfgs = _base_cfgs(request_profile="video_rsi", thinking_object_disabled=True)
        api = ApiProvider(
            force_mock=False,
            require_real=True,
            configs=cfgs,
            max_completion_tokens=256,
            required_roles=["vision", "planner"],
        )
        pb, pa = api.build_chat_request_body(
            cfgs["planner"],
            messages=[{"role": "user", "content": "plan"}],
            temperature=0.1,
        )
        self.assertEqual(pa["request_profile"], "default")
        self.assertNotIn("thinking", pb)
        self.assertEqual(pb["stream"], False)
        self.assertEqual(pb["temperature"], 0.1)


class FrameBindingTests(unittest.TestCase):
    def test_binding_text_actual_and_requested_only(self) -> None:
        t1 = frame_time_binding_text(
            {
                "frame_id": "f_0001_3065903",
                "actual_media_sec": 3065.9,
                "requested_media_sec": 3065.903,
                "pts_status": "pts",
            },
            "f_0001_3065903",
        )
        self.assertIn("frame_id=f_0001_3065903", t1)
        self.assertIn("actual_media_sec=3065.900", t1)
        self.assertIn("media_time_status=actual_pts", t1)
        self.assertNotIn("invent", t1.lower() + "x")

        t2 = frame_time_binding_text(
            {
                "frame_id": "f_x",
                "requested_media_sec": 10.5,
                "pts_status": "requested_only",
            },
            "f_x",
        )
        self.assertIn("media_time_status=requested_only", t2)
        self.assertIn("requested_media_sec=10.500", t2)
        self.assertIn("do not invent media time", t2)

    def test_vision_json_orders_text_then_image(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            img = Path(td) / "a.jpg"
            img.write_bytes(b"\xff\xd8\xff\xd9")  # minimal jpeg-ish
            cfgs = _base_cfgs(request_profile="video_rsi", thinking_object_disabled=True)
            api = ApiProvider(
                force_mock=False,
                require_real=True,
                configs=cfgs,
                max_completion_tokens=256,
                required_roles=["vision"],
            )
            captured = {}

            def fake_post(_cfg, *, body):
                captured["body"] = body
                return {
                    "choices": [
                        {
                            "message": {"content": '{"observed_actions":["shot"]}'},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 2,
                        "total_tokens": 3,
                    },
                }

            with mock.patch.object(api, "_post_chat", side_effect=fake_post):
                api.vision_json(
                    prompt="describe",
                    frame_paths=[img],
                    frame_ids=["f_0001_3065903"],
                    mock_obj={"ok": True},
                    frame_bindings=[
                        {
                            "frame_id": "f_0001_3065903",
                            "actual_media_sec": 3065.9,
                            "requested_media_sec": 3065.903,
                            "pts_status": "pts",
                        }
                    ],
                )
            parts = captured["body"]["messages"][1]["content"]
            # text binding immediately before image
            types = [p["type"] for p in parts]
            self.assertIn("image_url", types)
            img_i = types.index("image_url")
            self.assertEqual(parts[img_i - 1]["type"], "text")
            self.assertIn("actual_media_sec=3065.900", parts[img_i - 1]["text"])
            self.assertEqual(captured["body"]["thinking"], {"type": "disabled"})
            self.assertEqual(captured["body"]["temperature"], 0.0)
            red = redact_request_body_for_diff(captured["body"])
            self.assertIn("[REDACTED_FRAME]", json.dumps(red))
            self.assertNotIn("sk-test", json.dumps(red))


class OverBudgetAndGateTests(unittest.TestCase):
    def test_over_budget_still_blocks_after_rsi_profile(self) -> None:
        api = ApiProvider(
            force_mock=False,
            require_real=True,
            configs=_base_cfgs(
                request_profile="video_rsi", thinking_object_disabled=True
            ),
            max_calls=3,
            max_completion_tokens=256,
            required_roles=["vision"],
        )

        def fake_post(_cfg, *, body):
            self.assertEqual(body.get("max_tokens"), 256)
            return {
                "choices": [{"message": {"content": "ok"}, "finish_reason": "length"}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 3195,
                    "total_tokens": 3205,
                },
            }

        with mock.patch.object(api, "_post_chat", side_effect=fake_post):
            r = api.chat(
                role="vision",
                messages=[{"role": "user", "content": "a"}],
                cache_key="v1",
            )
        self.assertTrue(r["response_audit"]["output_budget_exceeded"])
        with self.assertRaises(ApiCallError) as ctx:
            api.chat(
                role="vision",
                messages=[{"role": "user", "content": "b"}],
                cache_key="v2",
            )
        self.assertEqual(ctx.exception.failure_status, "output_budget_exceeded")

    def test_observation_does_not_set_render_ready(self) -> None:
        plan = {
            "render_ready": False,
            "segments": [
                {
                    "segment_id": "seg_equalizer_goal_action",
                    "role": "equalizer_goal_action",
                    "media_in": 3059.903,
                    "media_out": 3071.903,
                    "render_eligibility": "candidate_only",
                    "time_status": "pending_review",
                    "blocking_reasons": ["phase4a_observation_unverified"],
                    "pipeline_verified": False,
                }
            ],
        }
        cleaned = sanitize_plan_trust(plan)
        self.assertFalse(cleaned.get("render_ready"))
        self.assertEqual(build_render_ready_edl(cleaned.get("segments") or []), [])


class EnvProfileTests(unittest.TestCase):
    def test_load_video_rsi_vision_keeps_planner_default(self) -> None:
        env = {
            "STORY_LLM_BASE_URL": "https://example.test/v1",
            "STORY_LLM_API_KEY": "sk-x",
            "STORY_LLM_MODEL": "DeepSeek-V4-Pro-0813",
            "STORY_VLM_MODEL": "Qwen3.6-Plus",
            "STORY_VLM_REQUEST_PROFILE": "video_rsi",
            "STORY_PLANNER_REQUEST_PROFILE": "default",
            "STORY_VLM_SEND_THINKING": "",
            "STORY_PLANNER_SEND_THINKING": "",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            cfgs = load_endpoint_configs()
        self.assertEqual(cfgs["vision"].request_profile, "video_rsi")
        self.assertTrue(cfgs["vision"].thinking_object_disabled)
        self.assertEqual(cfgs["vision"].default_temperature, 0.0)
        self.assertEqual(cfgs["planner"].request_profile, "default")
        self.assertFalse(cfgs["planner"].thinking_object_disabled)


if __name__ == "__main__":
    unittest.main()
