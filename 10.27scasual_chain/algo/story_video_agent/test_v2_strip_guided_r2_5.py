"""Round 2.5 unit tests — tight live goal windows (no real API)."""

from __future__ import annotations

import unittest

from story_video_agent.v2_strip_guided_r2_5_live_only import (
    build_live_only_edl,
    classify_live_replay,
    goal_live_core_window,
)


class TestGoalWindow(unittest.TestCase):
    def test_tight_core_not_shot_minus_six(self):
        ke = {
            "shot_action": {"media_sec": 3562.32},
            "goal_result": {"media_sec": 3566.64},
            "edit_window": {"media_in": 3560.32, "media_out": 3569.64},
        }
        w = goal_live_core_window(ke)
        self.assertTrue(w["ok"])
        self.assertGreaterEqual(w["media_in"], 3558.0)  # not 3556.32 (shot-6)
        self.assertLessEqual(w["media_out"], 3571.0)
        self.assertLess(w["media_in"], 3562.32)
        self.assertGreater(w["media_out"], 3566.64)


class TestReplayClassify(unittest.TestCase):
    def test_replay_keyword(self):
        r = classify_live_replay({"observed_actions": ["slow-mo replay of the goal"], "notes": "回放"})
        self.assertEqual(r["live_or_replay"], "replay")

    def test_live_badge(self):
        r = classify_live_replay({"observed_actions": ["直播 badge visible", "player shoots"], "notes": ""})
        self.assertEqual(r["live_or_replay"], "live")


class TestEdlBuilder(unittest.TestCase):
    def test_drops_failed_strip_keeps_goal(self):
        goals = [
            {
                "key_event_id": "ke_3",
                "score_before": [1, 1],
                "score_after": [2, 1],
                "pass": True,
                "accepted_media_in": 3560.8,
                "accepted_media_out": 3569.1,
                "verified_shot_sec": 3562.32,
                "verified_result_sec": 3566.64,
                "observation": {"live_or_replay": "live"},
            }
        ]
        strips = [
            {
                "node_id": "strip_x",
                "pass_live_only": False,
                "fail_reasons": ["replay"],
                "accepted_media_in": None,
                "accepted_media_out": None,
            }
        ]
        r24 = [
            {"role": "title_card", "segment_id": "title_open"},
            {
                "role": "goal",
                "beat": "climax",
                "source_node_ids": ["ke_3"],
                "media_in": 3556.32,
                "media_out": 3571.64,
            },
            {
                "role": "strip_context",
                "beat": "buildup",
                "source_node_ids": ["strip_x"],
                "media_in": 100.0,
                "media_out": 120.0,
            },
        ]
        edl = build_live_only_edl(goal_audits=goals, strip_audits=strips, r24_segments=r24)
        self.assertEqual(edl["n_goal_segments"], 1)
        self.assertEqual(edl["n_non_goal_strip_segments"], 0)
        goal_seg = next(s for s in edl["segments"] if s.get("role") == "goal")
        self.assertAlmostEqual(goal_seg["media_in"], 3560.8)
        self.assertNotAlmostEqual(goal_seg["media_in"], 3556.32)


if __name__ == "__main__":
    unittest.main()
