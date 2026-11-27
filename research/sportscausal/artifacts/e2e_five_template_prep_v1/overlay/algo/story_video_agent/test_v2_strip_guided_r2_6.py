"""R2.6 regression: score-order + first-live confirm preference (no API)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent.v2_enhanced_events import score_order_ok, should_emit_inferred_goal
from story_video_agent.v2_event_adapter import load_events_json, score_transition_anchors
from story_video_agent.v2_missing_goal_detector import detect_missing_goals


class TestR26ScoreOrder(unittest.TestCase):
    def test_reject_result_after_live_confirm(self):
        self.assertFalse(
            score_order_ok(result_sec=6461.08, score_confirmation_time=6408.70)["ok"]
        )
        self.assertTrue(
            score_order_ok(result_sec=6320.0, score_confirmation_time=6408.70)["ok"]
        )

    def test_emit_blocked_for_post_confirm_net(self):
        evidence = {
            "grade": "action_localized",
            "verification_status": "verified_action",
            "live_or_replay": "live",
            "shooting_action_evidence": True,
            "goal_result_evidence": True,
            "action_time_resolved": True,
            "shot_action": {"media_sec": 6457.0},
            "goal_result": {"media_sec": 6461.08},
            "related_score_transition": {"score_confirmation_time": 6408.70},
        }
        self.assertFalse(should_emit_inferred_goal(evidence))


class TestR26TrajectoryOnFoulScoreOnly(unittest.TestCase):
    def test_live_3_1_from_scores_field(self):
        payload = {
            "match_id": "t",
            "events": [
                {
                    "event_id": "e21",
                    "event_type": "Shot",
                    "media_time": {
                        "event_time_sec": 3697.35,
                        "start_time_sec": 3690.0,
                        "end_time_sec": 3700.0,
                    },
                    "video_context": {"broadcast_phase": "LIVE", "is_replay": False},
                    "attributes": {"Score_Recognition": ["2:1"]},
                },
                {
                    "event_id": "e118",
                    "event_type": "Foul_Being_fouled",
                    "media_time": {
                        "event_time_sec": 6408.70,
                        "start_time_sec": 6400.0,
                        "end_time_sec": 6412.0,
                    },
                    "video_context": {"broadcast_phase": "LIVE", "is_replay": False},
                    "attributes": {},
                    "scores": {"score_recognition": "3:1"},
                },
                {
                    "event_id": "e119",
                    "event_type": "Substitution",
                    "media_time": {
                        "event_time_sec": 6479.08,
                        "start_time_sec": 6467.0,
                        "end_time_sec": 6480.0,
                    },
                    "video_context": {"broadcast_phase": "REPLAY", "is_replay": True},
                    "attributes": {"Score_Recognition": ["3:1"]},
                },
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "events.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            bundle = load_events_json(path)
            changes = [
                a for a in score_transition_anchors(bundle["events"]) if a["kind"] == "score_change"
            ]
            self.assertEqual(changes[-1]["event_id"], "e118")
            self.assertAlmostEqual(float(changes[-1]["event_time_sec"]), 6408.70)
            det = detect_missing_goals(events=bundle["events"], predicted_strips=[])
            mg3 = [c for c in det["missing_goal_candidates"] if c.get("score_after") == [3, 1]][0]
            self.assertEqual(mg3["confirmation_event_id"], "e118")
            self.assertFalse(bool(mg3.get("confirmation_is_replay")))


if __name__ == "__main__":
    unittest.main()
