"""Small synthetic regressions for V3-A stage-1 read-only QC.

Run: PYTHONPATH=10.27scasual_chain/algo python -m unittest
     discover -s 10.27scasual_chain/tests -p 'test_v3a_quality_audit.py' -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "algo"))
from story_video_agent_v3.quality_audit import evaluate  # noqa: E402


def make_inputs():
    story = {"match_id": "synthetic", "story_tier": "complete"}
    plan = {
        "match_id": "synthetic",
        "story_tier": "complete",
        "story_scope": {
            "selected_arc": {
                "behind_start": {"score": "0:1", "t_sec": 100.0},
                "equalizer": {"score": "1:1", "t_sec": 200.0},
                "go_ahead": {"score": "2:1", "t_sec": 300.0},
            }
        },
    }
    def row(name, beat, start, event_id):
        return {
            "segment_id": name, "role": name, "beat": beat,
            "shot_kind": "live", "is_replay": False,
            "media_in": start, "media_out": start + 15,
            "event_ids": [event_id], "include_in_cut": True,
            "goal_action_complete": True,
        }
    edl = [
        {"segment_id": "title_open", "role": "story_title", "shot_kind": "title_card",
         "media_in": None, "media_out": None, "include_in_cut": True},
        row("opponent_opening_goal_action", "铺垫", 90, "e1"),
        row("equalizer_goal_action", "转折", 190, "e2"),
        row("go_ahead_goal_action", "高潮", 290, "e3"),
    ]
    return story, plan, edl


class V3AQualityAuditTests(unittest.TestCase):
    def test_full_structural_proxy_never_grants_render_ready(self):
        story, plan, edl = make_inputs()
        result = evaluate(story, plan, edl)
        self.assertEqual(100.0, result["dimensions"]["story_element_coverage"]["score"])
        self.assertEqual(100.0, result["dimensions"]["story_coherence"]["score"])
        self.assertTrue(result["structural_proxy_pass"])
        self.assertFalse(result["render_ready"])
        self.assertEqual("NOT_AUTHORIZED", result["release_decision"])
        self.assertEqual("NOT_MEASURED", result["dimensions"]["image_quality"]["status"])

    def test_missing_opponent_goal_is_not_replaced_by_title_or_scoreboard(self):
        story, plan, edl = make_inputs()
        edl[1] = {
            "segment_id": "scoreboard", "role": "deficit_scoreboard_anchor",
            "shot_kind": "scoreboard_anchor", "media_in": 100, "media_out": 103,
        }
        report = evaluate(story, plan, edl)
        self.assertFalse(report["structural_proxy_pass"])
        self.assertEqual(66.7, report["dimensions"]["story_element_coverage"]["score"])
        self.assertIn("missing_story_element", {x["kind"] for x in report["diagnostic_issues"]})

    def test_incomplete_goal_does_not_count_as_coverage(self):
        story, plan, edl = make_inputs()
        edl[2]["goal_action_complete"] = False
        report = evaluate(story, plan, edl)
        kinds = {x["kind"] for x in report["hard_gate_findings"]}
        self.assertIn("goal_window_incomplete", kinds)
        self.assertIn("missing_story_element", kinds)

    def test_replay_must_not_count_as_live_goal(self):
        story, plan, edl = make_inputs()
        edl[2]["is_replay"] = True
        report = evaluate(story, plan, edl)
        self.assertIn("replay_as_primary", {x["kind"] for x in report["hard_gate_findings"]})
        self.assertEqual(66.7, report["dimensions"]["story_element_coverage"]["score"])

    def test_bad_media_window_is_hard_error(self):
        story, plan, edl = make_inputs()
        edl[3]["media_out"] = 280
        report = evaluate(story, plan, edl)
        self.assertIn("bad_media_window", {x["kind"] for x in report["hard_gate_findings"]})

    def test_shared_event_between_distinct_goal_roles_is_hard_error(self):
        story, plan, edl = make_inputs()
        edl[3]["event_ids"] = ["e2"]
        report = evaluate(story, plan, edl)
        self.assertIn("duplicated_goal_event", {x["kind"] for x in report["hard_gate_findings"]})

    def test_known_source_corruption_is_hard_error(self):
        story, plan, edl = make_inputs()
        edl[2]["integrity_failure"] = "source_corruption"
        report = evaluate(story, plan, edl)
        self.assertIn("known_integrity_failure", {x["kind"] for x in report["hard_gate_findings"]})

    def test_missing_story_scope_remains_unknown_not_false_success(self):
        story, plan, edl = make_inputs()
        plan.pop("story_scope")
        report = evaluate(story, plan, edl)
        self.assertIsNone(report["dimensions"]["story_element_coverage"]["score"])
        self.assertFalse(report["structural_proxy_pass"])

    def test_order_inversion_creates_diagnostic(self):
        story, plan, edl = make_inputs()
        edl[1], edl[2] = edl[2], edl[1]
        report = evaluate(story, plan, edl)
        self.assertIn("beat_order_inversion", {x["kind"] for x in report["diagnostic_issues"]})
        self.assertFalse(report["structural_proxy_pass"])


if __name__ == "__main__":
    unittest.main()
