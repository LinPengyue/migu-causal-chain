"""Zero-network regression tests for the A-match Planner diagnostic."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from diagnose_v3a_A_planner import (  # noqa: E402
    configure_and_preflight, one_planner_call, provenance,
)


class PlannerDiagnosticTests(unittest.TestCase):
    def test_preflight_disables_planner_thinking_without_http(self):
        env = {
            "STORY_LLM_BASE_URL": "https://example.invalid/v1",
            "STORY_LLM_API_KEY": "test-not-real",
            "STORY_LLM_MODEL": "test-model",
            "STORY_VLM_MODEL": "test-vision",
            "STORY_LLM_MAX_RETRIES": "3",
            "STORY_PLANNER_SEND_THINKING": "1",
            "STORY_PLANNER_ENABLE_THINKING": "1",
            "STORY_PLANNER_THINKING_BUDGET": "4096",
        }
        with patch.dict(os.environ, env, clear=True):
            provider, preflight = configure_and_preflight()
            self.assertTrue(preflight["thinking_object_disabled"])
            self.assertTrue(preflight["request_thinking_sent"])
            self.assertEqual(preflight["max_retries"], 0)
            self.assertEqual(preflight["max_http_attempts"], 1)
            self.assertEqual(preflight["token_limit_sent"], 2048)
            self.assertEqual(provider.status()["http_attempts"], 0)
            self.assertNotIn("api_key", preflight)

    def test_provenance_detects_old_raw_vs_p1(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history, run = root / "history", root / "run"
            old_raw = history / "04_phase5"
            old_p1 = history / "04_phase5_p1_polish"
            fresh = run / "01_to_04_fresh_v3r/04_phase5"
            agent = run / "05_v3a"
            for p in (old_raw, old_p1, fresh, agent):
                p.mkdir(parents=True, exist_ok=True)
            raw = [{"segment_id": "g", "media_in": 1.0, "media_out": 3.0}]
            polished = [{"segment_id": "g", "media_in": 1.5, "media_out": 3.0}]
            for p, rows in (
                (old_raw / "candidate_edl.json", raw),
                (old_p1 / "candidate_edl.json", polished),
                (fresh / "candidate_edl.json", polished),
                (agent / "best_candidate_edl.json", polished),
            ):
                p.write_text(json.dumps(rows), encoding="utf-8")
            result = provenance(run, history)
            self.assertTrue(result["edl_comparisons"]["fresh_v3r_vs_historical_p1"]["exactly_equal"])
            self.assertFalse(result["edl_comparisons"]["fresh_v3r_vs_historical_raw"]["exactly_equal"])
            self.assertFalse(result["history_used_as_pipeline_input"])

    def test_one_call_success_requires_actual_tool_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ctx.json"
            path.write_text(json.dumps({"trusted_anchors": [{"anchor_id": "goal1"}]}))
            reply = {
                "ok": True, "provider_mode": "real", "model": "fake",
                "validated": {"video_tool_requests": [{"tool": "vlm_observe", "anchor_id": "goal1"}]},
                "usage": {"total_tokens": 100}, "est_cost_usd": 0.0001,
            }
            with patch("story_video_agent_v3.self_revise_agent.call_llm_planner", return_value=reply):
                result = one_planner_call(object(), path)
            self.assertEqual(result["gate"], "PLANNER_READY_FOR_VLM")
            reply["validated"] = {"video_tool_requests": []}
            with patch("story_video_agent_v3.self_revise_agent.call_llm_planner", return_value=reply):
                result = one_planner_call(object(), path)
            self.assertEqual(result["gate"], "PLANNER_NOT_READY")


if __name__ == "__main__":
    unittest.main()
