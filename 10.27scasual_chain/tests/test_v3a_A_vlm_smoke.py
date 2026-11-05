"""No-network tests for the one-shot A-match VLM observer."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from smoke_v3a_A_vlm import (  # noqa: E402
    configure_vision, evaluate_observation, select_goal_request, run_one_window,
)


class OneShotVlmTests(unittest.TestCase):
    def setUp(self):
        self.context = {
            "trusted_anchors": [
                {"anchor_id": "edl:seg_goal", "kind": "existing_edl_segment",
                 "role": "equalizer_goal_action", "media_in": 100, "media_out": 116},
                {"anchor_id": "edl:seg_buildup", "kind": "existing_edl_segment",
                 "role": "buildup", "media_in": 200, "media_out": 215},
            ],
            "video_duration_sec": 300,
        }
        self.smoke = {
            "gate": "PLANNER_READY_FOR_VLM", "planner_ok": True, "provider_mode": "real",
            "tool_requests": [
                {"tool": "vlm_observe", "request_id": "buildup", "anchor_id": "edl:seg_buildup",
                 "question": "buildup", "search_windows": [{"start": 200, "end": 215}]},
                {"tool": "vlm_observe", "request_id": "goal", "anchor_id": "edl:seg_goal",
                 "question": "equalizer goal action", "search_windows": [
                     {"start": 100, "end": 116}, {"start": 116, "end": 132}
                 ]},
            ],
        }

    def test_goal_selection_skips_buildup_and_uses_trusted_anchor(self):
        selected = select_goal_request(self.smoke, self.context)
        self.assertEqual(selected["request"]["request_id"], "goal")
        self.assertEqual(selected["planner_tool_index"], 1)
        self.assertEqual(selected["selected_window"], {"start": 100.0, "end": 116.0})

    def test_goal_selection_rejects_unknown_anchor_or_untrusted_window(self):
        self.smoke["tool_requests"][1]["anchor_id"] = "edl:invented"
        with self.assertRaises(ValueError):
            select_goal_request(self.smoke, self.context)
        self.smoke["tool_requests"][1]["anchor_id"] = "edl:seg_goal"
        self.smoke["tool_requests"][1]["search_windows"] = [{"start": 999, "end": 1010}]
        with self.assertRaises(ValueError):
            select_goal_request(self.smoke, self.context)

    def test_vision_preflight_forces_one_call_and_2048_not_shell_256(self):
        env = {
            "STORY_VLM_BASE_URL": "https://example.invalid/v1",
            "STORY_VLM_API_KEY": "fake-key-not-real",
            "STORY_VLM_MODEL": "fake-qwen",
            "STORY_LLM_BASE_URL": "https://example.invalid/v1",
            "STORY_LLM_API_KEY": "fake-key-not-real",
            "STORY_LLM_MODEL": "fake-planner",
            "STORY_API_MAX_COMPLETION_TOKENS": "256",
            "STORY_API_MAX_CALLS": "24",
            "STORY_LLM_MAX_RETRIES": "3",
            "STORY_VLM_SEND_THINKING": "1",
            "STORY_VLM_ENABLE_THINKING": "1",
        }
        with patch.dict(os.environ, env, clear=True):
            api, report = configure_vision()
            self.assertTrue(report["thinking_object_disabled_sent"])
            self.assertEqual(report["max_http_attempts"], 1)
            self.assertEqual(report["max_retries"], 0)
            self.assertEqual(report["max_completion_tokens"], 2048)
            self.assertEqual(api.status()["http_attempts"], 0)
            self.assertEqual(report["token_param_sent"], "max_tokens")

    def test_evidence_requires_real_cited_pts_and_semantics(self):
        obs = {
            "ok": True, "provider_mode": "real",
            "frames": [{"frame_id": "f1", "actual_media_sec": 110.25, "pts_status": "pts"}],
            "vlm": {"cited_frame_ids": ["f1"], "visible_content": "players near goal",
                    "live_or_replay": "unknown", "observed_shot": True},
        }
        assessment = evaluate_observation(obs)
        self.assertEqual(assessment["gate"], "VLM_OBSERVATION_WITH_PTS")
        self.assertFalse(assessment["first_live_verified"])
        obs["vlm"]["cited_frame_ids"] = ["invented"]
        self.assertEqual(evaluate_observation(obs)["gate"], "VLM_REAL_BUT_EVIDENCE_INCOMPLETE")
        obs["vlm"]["cited_frame_ids"] = ["f1"]
        obs["frames"][0]["pts_status"] = "requested_only"
        self.assertEqual(evaluate_observation(obs)["gate"], "VLM_REAL_BUT_EVIDENCE_INCOMPLETE")

    def test_run_one_window_does_not_schedule_followups(self):
        selected = select_goal_request(self.smoke, self.context)
        fake_obs = {"ok": True, "provider_mode": "real", "frames": [], "vlm": {}}
        with tempfile.TemporaryDirectory() as tmp, \
             patch("story_video_agent.media.probe_video", return_value=object()), \
             patch("story_video_agent.frames.FrameStore") as store, \
             patch("story_video_agent_v3.self_revise_agent._observe_one_window",
                   return_value=fake_obs) as observe:
            got = run_one_window(object(), Path(tmp) / "video.mp4", selected, Path(tmp))
        self.assertEqual(got, fake_obs)
        observe.assert_called_once()
        self.assertEqual(observe.call_args.kwargs["win"], {"start": 100.0, "end": 116.0})
        self.assertEqual(store.call_args.kwargs["budget"].max_frames, 4)


if __name__ == "__main__":
    unittest.main()
