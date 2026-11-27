"""Phase A unit tests (mock only — no billed API)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent.api_provider import ApiProvider
from story_video_agent.v2_phase_a_agent import V2PhaseAAgent
from story_video_agent.v2_phase_a_runner import compare_paths, run_fixed_frame, run_multi_round
from story_video_agent.v2_rsi_toolbox import V2RSIToolbox
from story_video_agent.v2_story_memory import V2StoryMemory


class TestToolboxNormalize(unittest.TestCase):
    def test_scan_bounds(self):
        # lightweight stub store/vision unused for normalize
        class _S:
            budget = type("B", (), {"remaining": 10})()

        class _V:
            pass

        tb = V2RSIToolbox(duration=60.0, store=_S(), vision=_V())  # type: ignore[arg-type]
        with self.assertRaises(Exception):
            tb.normalize_arguments("scan_interval", {"start": 0, "end": 5})
        ok = tb.normalize_arguments("scan_interval", {"start": 10, "end": 30})
        self.assertEqual(ok["start"], 10.0)


class TestMemory(unittest.TestCase):
    def test_evidence_schema(self):
        mem = V2StoryMemory()
        mem.set_hypothesis({"story_type": "T01_comeback", "status": "candidate"})
        mem.add_tool_result(
            {"tool": "overview", "arguments": {}},
            {
                "media_start_sec": 0,
                "media_end_sec": 10,
                "perception": {
                    "normalized_ok": True,
                    "observed_actions": ["scoreboard 2-1 visible"],
                    "frame_ids": ["f1"],
                    "confidence": 0.5,
                    "provider_mode": "mock",
                },
            },
        )
        ev = mem.to_story_evidence(video="x.mp4", stop_reason="test", budget={})
        self.assertEqual(ev["schema"], "v2_story_evidence_phase_a_v1")
        self.assertFalse(ev["render_ready"])
        self.assertTrue(ev["candidate_events"])


class TestRunnerMock(unittest.TestCase):
    def test_compare_on_synth_or_clip(self):
        video = Path("/tmp/migu_vd_clips/croatia_2_1_60s.mp4")
        if not video.is_file():
            video = Path("/tmp/migu_vd_synth/synth_pil2.mp4")
        if not video.is_file():
            self.skipTest("no local clip")
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)

            def factory():
                return ApiProvider(force_mock=True, require_real=False)

            cmp = compare_paths(
                video=video,
                out_dir=out,
                api_factory=factory,
                max_steps=3,
                frame_budget_multi=10,
                frame_count_fixed=4,
                use_llm_planner=True,  # mock planner still works
            )
            self.assertIn("path_a_fixed", cmp)
            self.assertIn("path_b_multi", cmp)
            self.assertTrue((out / "path_a_fixed" / "story_evidence.json").is_file())
            self.assertTrue((out / "path_b_multi" / "agent_trace.json").is_file())
            a = json.loads((out / "path_a_fixed" / "agent_trace.json").read_text())
            b = json.loads((out / "path_b_multi" / "agent_trace.json").read_text())
            self.assertEqual(a["path"], "fixed_frame")
            self.assertEqual(b["path"], "multi_round_planner")
            # multi should have >=1 planner mode entries
            self.assertTrue(b.get("planner_mode_log"))


if __name__ == "__main__":
    unittest.main()
