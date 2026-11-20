"""Unit tests for P5 goal recovery (no network, no gold)."""
from __future__ import annotations

import unittest

from .goal_recovery import (
    apply_action_overlays,
    provisional_action_from_nearby_events,
    recover_goal_candidates,
)


def _ev(eid, typ, t, score, replay=False):
    return {
        "event_id": eid,
        "event_type": typ,
        "media_time": {"event_time_sec": t, "start_time_sec": t - 1, "end_time_sec": t + 1},
        "video_context": {"is_replay": replay, "broadcast_phase": "REPLAY" if replay else "LIVE"},
        "attributes": {"Score_Recognition": [score]} if score else {},
    }


class TestGoalRecovery(unittest.TestCase):
    def test_single_increments_not_hardcoded_count(self):
        rows = [
            _ev("a", "Pass", 10, "0:0"),
            _ev("b", "Shot", 50, "0:0"),
            _ev("c", "Pass", 100, "0:1"),
            _ev("d", "Pass", 200, "1:1"),
            _ev("e", "Pass", 300, "2:1"),
        ]
        cands = recover_goal_candidates(rows)
        self.assertEqual(len(cands), 3)
        self.assertTrue(all(c["single_goal_increment"] for c in cands))
        self.assertTrue(all(c["goal_action_sec"] is None for c in cands))

    def test_overlay_sets_action_not_confirm(self):
        rows = [
            _ev("a", "Pass", 10, "0:0"),
            _ev("b", "Pass", 100, "0:1"),
        ]
        cands = recover_goal_candidates(rows)
        overlays = [{
            "score_before": [0, 0],
            "score_after": [0, 1],
            "score_confirmation_sec": 100.0,
            "goal_action_sec": 88.0,
            "goal_action_interval": {"media_in": 85.0, "media_out": 95.0},
            "is_replay": False,
            "source": "test",
            "verification_status": "possible_first_live",
        }]
        out = apply_action_overlays(cands, overlays)
        self.assertEqual(out[0]["goal_action_sec"], 88.0)
        self.assertNotEqual(out[0]["goal_action_sec"], out[0]["score_confirmation_sec"])

    def test_refuse_overlay_equal_confirm(self):
        rows = [_ev("a", "Pass", 10, "0:0"), _ev("b", "Pass", 100, "1:0")]
        cands = recover_goal_candidates(rows)
        out = apply_action_overlays(cands, [{
            "score_before": [0, 0], "score_after": [1, 0],
            "score_confirmation_sec": 100.0, "goal_action_sec": 100.0,
            "source": "bad",
        }])
        self.assertIsNone(out[0]["goal_action_sec"])

    def test_provisional_shot_not_confirm(self):
        rows = [
            _ev("a", "Pass", 10, "0:0"),
            _ev("s", "Shot", 80, None),
            _ev("b", "Pass", 100, "0:1"),
        ]
        # attach nearby manually via recover then provisional
        cands = recover_goal_candidates([
            _ev("a", "Pass", 10, "0:0"),
            _ev("s", "Shot", 80, "0:0"),
            _ev("b", "Pass", 100, "0:1"),
        ])
        out = provisional_action_from_nearby_events(cands)
        self.assertEqual(out[0]["goal_action_sec"], 80.0)
        self.assertEqual(out[0]["verification_status"], "provisional_from_nearby_event")


if __name__ == "__main__":
    unittest.main()
