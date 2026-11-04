"""Offline adapter fixes using France real round-1 planner_result.json (no paid API)."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from story_video_agent.api_provider import ApiProvider
from story_video_agent_v3.self_revise_agent import (
    VERIFIER_SYSTEM,
    call_llm_verifier,
    validate_planner_output,
    validate_verifier_output,
)

REAL_ROUND = Path(
    "/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_FR_france_australia_zeroshot"
    "/v3a_self_revise_fr_real_20261104_r1/round_01"
)


@unittest.skipUnless(
    (REAL_ROUND / "planner_result.json").is_file(),
    "France real round-1 artifacts not present",
)
class RealPlannerReplayTests(unittest.TestCase):
    def setUp(self):
        pr = json.loads((REAL_ROUND / "planner_result.json").read_text(encoding="utf-8"))
        ctx = json.loads((REAL_ROUND / "planner_context.json").read_text(encoding="utf-8"))
        self.raw = pr["raw"]
        self.anchors = ctx["trusted_anchors"]
        self.duration = ctx.get("video_duration_sec")

    def test_real_tools_not_stripped(self):
        raw_n = len(self.raw.get("video_tool_requests") or [])
        self.assertGreaterEqual(raw_n, 3)
        out = validate_planner_output(
            self.raw, trusted_anchors=self.anchors, video_duration=self.duration,
        )
        tools = out["video_tool_requests"]
        self.assertGreaterEqual(len(tools), 3, out.get("dropped_tools"))
        for tr in tools:
            self.assertIn(tr["tool"], ("vlm_observe", "extract_frames", "widen_search"))
            self.assertTrue(tr["anchor_id"])
            self.assertTrue(tr["search_windows"])
            for w in tr["search_windows"]:
                self.assertLess(w["start"], w["end"])
                self.assertGreaterEqual(w["start"], 0.0)
                if self.duration is not None:
                    self.assertLessEqual(w["end"], float(self.duration) + 1e-6)
        # Opening scan should land near 1351 relative to 1535.65
        opening = next(t for t in tools if "behind_start" in t["anchor_id"])
        starts = [w["start"] for w in opening["search_windows"]]
        self.assertTrue(any(abs(s - 1345.65) < 1.0 for s in starts), starts)

    def test_real_intents_normalize_role_anchor(self):
        out = validate_planner_output(
            self.raw, trusted_anchors=self.anchors, video_duration=self.duration,
        )
        intents = out["revision_intents"]
        search = [i for i in intents if i["action"] == "search_add"]
        self.assertTrue(search, out.get("dropped_intents"))
        self.assertEqual(search[0]["role"], "opponent_opening_goal_action")
        self.assertEqual(search[0]["anchor_id"], "score_node:behind_start")

    def test_drops_are_audited(self):
        out = validate_planner_output(
            self.raw, trusted_anchors=self.anchors, video_duration=self.duration,
        )
        for d in out.get("dropped_tools") or []:
            self.assertIn("reason", d)
            self.assertIn("suggested_fix", d)
        for d in out.get("dropped_intents") or []:
            self.assertIn("reason", d)
            self.assertIn("suggested_fix", d)

    def test_free_pts_still_rejected(self):
        bad = {
            "diagnoses": [{"issue_id": "d", "problem": "x", "severity": "P1",
                           "evidence_refs": []}],
            "revision_intents": [],
            "video_tool_requests": [{
                "tool_name": "vlm_observe",
                "anchor_id": "score_node:behind_start",
                "search_windows": [{"start": 10.0, "end": 40.0}],  # far from 1535
            }],
            "notes": "",
        }
        out = validate_planner_output(
            bad, trusted_anchors=self.anchors, video_duration=self.duration,
        )
        # Window rejected → fallback expansion still yields tools (recoverable)
        self.assertTrue(out["video_tool_requests"])
        self.assertTrue(any(
            d.get("reason") == "absolute_window_outside_anchor_bound"
            for d in out["dropped_tools"]
        ))


class VerifierEmptyBodyTests(unittest.TestCase):
    def test_empty_content_marked_empty_model_content(self):
        api = ApiProvider(force_mock=True, max_calls=0)

        def boom(**kwargs):
            return {
                "provider_mode": "real",
                "content": "",
                "usage": {"prompt_tokens": 10, "completion_tokens": 2048,
                          "completion_tokens_details": {"reasoning_tokens": 2048}},
                "est_cost_usd": 0.001,
                "model": "x",
            }

        with mock.patch.object(api, "verify_decision", side_effect=boom):
            out = call_llm_verifier(api, {"x": 1}, max_retries=0)
        self.assertFalse(out["ok"])
        self.assertEqual(out.get("failure_code") or out.get("error"), "EMPTY_MODEL_CONTENT"
                         if out.get("failure_code") == "EMPTY_MODEL_CONTENT"
                         else out.get("error"))
        self.assertTrue(out.get("http_ok"))
        self.assertIn("EMPTY_MODEL_CONTENT", str(out.get("error")))
        self.assertNotIn("empty VLM response", str(out.get("error")))

    def test_valid_json_ok(self):
        api = ApiProvider(force_mock=True, max_calls=0)
        fixture = {
            "issues": [],
            "dimensions": {
                "story_element_coverage": {"status": "unchanged", "summary": "s", "evidence_refs": []},
                "narrative_coherence": {"status": "unchanged", "summary": "s", "evidence_refs": []},
                "image_content_quality": {"status": "unknown", "summary": "", "evidence_refs": []},
            },
            "hard_vetoes": [],
            "evidence_of_improvement": [],
            "quality_delta_vs_baseline": "none",
        }
        out = call_llm_verifier(api, {}, fixture=fixture)
        self.assertTrue(out["ok"])
        self.assertTrue(out["structured_ok"])

    def test_http_502_degraded(self):
        api = ApiProvider(force_mock=True, max_calls=0)

        def boom(**kwargs):
            from story_video_agent.api_provider import ApiCallError
            raise ApiCallError("Tunnel 502 Bad Gateway", retryable=True, http_status=502)

        with mock.patch.object(api, "verify_decision", side_effect=boom):
            out = call_llm_verifier(api, {"x": 1}, max_retries=1)
        self.assertFalse(out["ok"])
        self.assertFalse(out.get("http_ok", True))
        self.assertIn("502", str(out.get("error")))

    def test_missing_node_demoted_from_hard_veto(self):
        v = validate_verifier_output({
            "issues": [],
            "dimensions": {
                "story_element_coverage": {"status": "regressed", "summary": "missing opening",
                                           "evidence_refs": []},
                "narrative_coherence": {"status": "unchanged", "summary": "", "evidence_refs": []},
                "image_content_quality": {"status": "unknown", "summary": "", "evidence_refs": []},
            },
            "hard_vetoes": [{"kind": "missing_required_node", "problem": "missing opening node"}],
            "evidence_of_improvement": [],
        })
        self.assertEqual(v["hard_vetoes"], [])
        self.assertTrue(v["demoted_coverage_vetoes"])
        self.assertTrue(any(i.get("demoted_from_hard_veto") for i in v["issues"]))
        # Prompt must say NOT to hard-veto missing coverage
        self.assertIn("Do NOT put missing story coverage", VERIFIER_SYSTEM)

    def test_replay_hard_veto_kept(self):
        v = validate_verifier_output({
            "issues": [],
            "dimensions": {
                "story_element_coverage": {"status": "unchanged", "summary": "", "evidence_refs": []},
                "narrative_coherence": {"status": "unchanged", "summary": "", "evidence_refs": []},
                "image_content_quality": {"status": "unknown", "summary": "", "evidence_refs": []},
            },
            "hard_vetoes": [{"kind": "replay_as_first_live", "problem": "replay used as live"}],
            "evidence_of_improvement": [],
        })
        self.assertEqual(len(v["hard_vetoes"]), 1)

    def test_stats_role_verifier_separate(self):
        api = ApiProvider(force_mock=True, max_calls=0)
        api.verify_decision(
            system_prompt="s", user_prompt="u",
            mock_decision={"ok": True},
        )
        by = api.stats.summary()["by_role"]
        self.assertIn("verifier", by)
        self.assertGreaterEqual(by["verifier"]["http_attempts"] + by["verifier"].get("tokens", 0), 0)


if __name__ == "__main__":
    unittest.main()
