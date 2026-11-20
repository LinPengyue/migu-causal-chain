"""Round 2.4 unit tests — observation feedback, EDL dual order (no real API)."""

from __future__ import annotations

import unittest

from story_video_agent.v2_strip_guided_r2_4_edl import build_r24_candidate_edl
from story_video_agent.v2_strip_guided_r2_4_memory import V2R24StoryMemory
from story_video_agent.v2_strip_guided_r2_4_planner import apply_r24_decision, apply_review_observations
from story_video_agent.v2_strip_guided_r2_4_review import grade_strip_observation


class TestObservationFeedback(unittest.TestCase):
    def test_planner_view_includes_observations(self):
        mem = V2R24StoryMemory()
        mem.selected_node_ids = ["strip_clip24"]
        mem.selection_reasons["strip_clip24"] = "pre-equalizer"
        apply_review_observations(
            mem,
            {
                "reviews": [
                    {
                        "node_id": "strip_clip24",
                        "recommendation": "drop",
                        "supports_prior_why": False,
                        "summary": "replay_only",
                        "observed_actions": ["replay of shot"],
                        "evidence_id": "e1",
                        "live_or_replay": "replay",
                        "verification_status": "observed_not_verified_causal",
                    }
                ]
            },
        )
        view = mem.planner_view()
        self.assertTrue(view["strip_observations"])
        self.assertEqual(view["strip_observations"][0]["recommendation"], "drop")

    def test_unselect_changes_selection(self):
        mem = V2R24StoryMemory()
        apply_r24_decision(
            mem,
            {
                "type": "tool",
                "tool": "select_node",
                "arguments": {"node_id": "strip_a", "beat": "buildup", "why": "x"},
            },
        )
        self.assertIn("strip_a", mem.selected_node_ids)
        apply_r24_decision(
            mem,
            {
                "type": "tool",
                "tool": "unselect_node",
                "arguments": {"node_id": "strip_a", "why": "obs_drop"},
            },
        )
        self.assertNotIn("strip_a", mem.selected_node_ids)
        self.assertIn("strip_a", mem.excluded_node_ids)
        self.assertTrue(any(x.get("action") == "unselect" for x in mem.selection_change_log))


class TestGradeStrip(unittest.TestCase):
    def test_replay_recommends_drop(self):
        obs = grade_strip_observation(
            node_id="strip_x",
            strip_meta={"first_event": "shot", "last_event": "save", "category": "danger", "t0_sec": 1, "t1_sec": 10},
            prior_why="danger before goal",
            raw={"observed_actions": ["slow-mo replay of previous shot"], "notes": "replay"},
            evidence_id="e",
        )
        self.assertEqual(obs["recommendation"], "drop")
        self.assertEqual(obs["live_or_replay"], "replay")
        self.assertEqual(obs["verification_status"], "observed_not_verified_causal")


class TestEdlDualOrder(unittest.TestCase):
    def test_source_media_and_narrative_fields(self):
        graph = {
            "beats": {
                "setup": {
                    "members": [
                        {
                            "node_id": "ke_1",
                            "media_in": 100.0,
                            "media_out": 110.0,
                            "time_status": "verified_action",
                        }
                    ]
                },
                "buildup": {
                    "members": [
                        {
                            "node_id": "strip_a",
                            "media_in": 50.0,
                            "media_out": 70.0,
                            "time_status": "predicted_strip_span",
                        }
                    ]
                },
            }
        }
        edl = build_r24_candidate_edl(story_graph=graph, playout_policy="prefer_match_timeline")
        timed = [s for s in edl["segments"] if s.get("media_in") is not None]
        self.assertEqual(timed[0]["media_in"], 50.0)
        self.assertIn("source_media_order", timed[0])
        self.assertIn("narrative_order", timed[0])
        # narrative follows media under prefer_match_timeline
        self.assertEqual(timed[0]["narrative_order"], timed[0]["source_media_order"] + 1)  # +1 for title


if __name__ == "__main__":
    unittest.main()
