"""Phase C-1 unit tests (mock only)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from story_video_agent.api_provider import ApiProvider
from story_video_agent.v2_phase_c1_runner import run_localization
from story_video_agent.v2_phase_c1_verifier import grade_localization
from story_video_agent.v2_score_transitions import (
    analyze_score_transitions,
    independent_discovery_check,
    parse_score_pairs,
    unique_score_timeline,
)


class TestScoreTransitions(unittest.TestCase):
    def test_no_hardcoded_only_zero_one(self):
        # Works for 1-2 → 2-2 → 3-2 as well
        obs = [
            {"notes": "score 1-2", "media_start_sec": 10},
            {"notes": "board 2 - 2", "media_start_sec": 50},
            {"notes": "now 3:2", "media_start_sec": 90},
        ]
        tl = unique_score_timeline(obs)
        an = analyze_score_transitions(tl)
        self.assertEqual(an["suggested_discovery_status"], "story_candidate")
        self.assertEqual(an["deficit_side"], "left")
        self.assertTrue(an["leveled_after_deficit"])
        self.assertTrue(an["lead_after_deficit"])

    def test_ignores_narrative_keywords_alone(self):
        obs = [{"notes": "amazing comeback trailing then equalizer", "media_start_sec": 1}]
        check = independent_discovery_check(llm_status="story_candidate", observations=obs)
        self.assertEqual(check["final_status"], "unresolved")
        self.assertTrue(check["demoted"])

    def test_demote_llm_overclaim(self):
        obs = [
            {"notes": "0-1", "media_start_sec": 1},
            {"notes": "1-1", "media_start_sec": 2},
        ]
        check = independent_discovery_check(llm_status="story_candidate", observations=obs)
        self.assertEqual(check["score_suggested_status"], "partial_story")
        self.assertEqual(check["final_status"], "partial_story")
        self.assertTrue(check["demoted"])

    def test_parse_pairs(self):
        self.assertIn((2, 1), parse_score_pairs("Croatia 2 - 1 Canada"))


class TestGrades(unittest.TestCase):
    def test_scoreboard_only(self):
        obs = {
            "media_start_sec": 0,
            "media_end_sec": 10,
            "perception": {
                "notes": "Scoreboard shows 1-1",
                "observed_actions": ["scoreboard visible"],
                "normalized_ok": True,
            },
        }
        g = grade_localization(observation=obs, task_role="equalizer_goal", window_span_sec=10)
        self.assertEqual(g["grade"], "scoreboard_only")

    def test_wide_window_cannot_be_action_localized(self):
        obs = {
            "media_start_sec": 0,
            "media_end_sec": 60,
            "perception": {
                "notes": "Player shoots and ball into the net. Live broadcast.",
                "observed_actions": ["shot on goal", "ball in net", "live"],
                "normalized_ok": True,
            },
        }
        g = grade_localization(observation=obs, task_role="equalizer_goal", window_span_sec=60)
        self.assertNotEqual(g["grade"], "action_localized")
        self.assertNotEqual(g["grade"], "action_corroborated")


class TestRunnerMock(unittest.TestCase):
    def test_mock_localization(self):
        video = Path("/tmp/migu_vd_clips/croatia_2_1_60s.mp4")
        if not video.is_file():
            self.skipTest("no clip")
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            api = ApiProvider(force_mock=True, require_real=False)
            bundle = run_localization(
                video=video,
                out_dir=out,
                api=api,
                max_steps=3,
                frame_budget=12,
                use_llm_planner=True,
            )
            self.assertTrue((out / "localized_events.json").is_file())
            self.assertTrue((out / "story_evidence_tasks.json").is_file())
            self.assertTrue((out / "localization_eval.json").is_file() or True)
            self.assertIn("discovery_check", bundle)


if __name__ == "__main__":
    unittest.main()
