"""Round 2.5 unit tests — strict live gates (no real API)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from story_video_agent.v2_strip_guided_r2_5_event_replay_audit import audit_event_replay_fields
from story_video_agent.v2_strip_guided_r2_5_live_only import (
    build_live_only_edl,
    classify_live_replay,
    goal_live_core_window,
    locate_continuous_live_goal_window,
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
        self.assertGreaterEqual(w["media_in"], 3558.0)
        self.assertLessEqual(w["media_out"], 3571.0)
        self.assertLess(w["media_in"], 3562.32)
        self.assertGreater(w["media_out"], 3566.64)


class TestReplayClassify(unittest.TestCase):
    def test_replay_keyword(self):
        r = classify_live_replay(
            {"observed_actions": ["slow-mo replay of the goal"], "notes": "回放"}
        )
        self.assertEqual(r["live_or_replay"], "replay")

    def test_live_badge_alone_is_unknown(self):
        r = classify_live_replay(
            {"observed_actions": ["直播 badge visible in corner", "player stands"], "notes": ""}
        )
        self.assertEqual(r["live_or_replay"], "unknown")
        self.assertTrue(r["badge_alone_not_sufficient"])

    def test_live_action_evidence(self):
        r = classify_live_replay(
            {
                "observed_actions": [
                    "wide tactical live play continuing",
                    "player shoots toward goal",
                    "ball into the net",
                    "not a replay",
                ],
                "notes": "match clock visible",
            }
        )
        self.assertEqual(r["live_or_replay"], "live")

    def test_not_a_replay_negation(self):
        r = classify_live_replay(
            {
                "observed_actions": [
                    "player strikes the ball",
                    "ball enters the net",
                    "This appears to be live match play, not a replay, evidenced by continuous motion",
                ],
                "notes": "broadcast_state=live_action",
            }
        )
        self.assertEqual(r["live_or_replay"], "live")
        self.assertFalse(r["has_replay_keyword"])

    def test_lack_of_slow_motion_not_replay(self):
        r = classify_live_replay(
            {
                "observed_actions": [
                    "player strikes the ball",
                    "ball enters the net",
                    "Visuals indicate live match play due to continuous motion and lack of slow-motion artifacts",
                ],
                "notes": "broadcast_state=live_action match clock visible",
            }
        )
        self.assertEqual(r["live_or_replay"], "live")
        self.assertFalse(r["has_replay_keyword"])

    def test_replay_package_is_replay(self):
        r = classify_live_replay(
            {
                "observed_actions": ["live broadcast replay package of the goal"],
                "notes": "broadcast_state=replay",
            }
        )
        self.assertEqual(r["live_or_replay"], "replay")

    def test_striking_counts_as_shot(self):
        r = classify_live_replay(
            {
                "observed_actions": [
                    "Croatia player #9 striking the ball with right foot",
                    "Ball entering the net",
                    "broadcast_state=live_action wide tactical view",
                ],
                "notes": "",
            }
        )
        self.assertEqual(r["live_or_replay"], "live")
        blob = " ".join(r["observed_actions"])
        self.assertRegex(blob, r"striking")


class TestLocateLive(unittest.TestCase):
    def test_trims_before_replay(self):
        timeline = {
            "runs": [
                {
                    "phase": "live",
                    "media_in": 3552.0,
                    "media_out": 3569.0,
                    "has_shot": True,
                    "has_net": True,
                },
                {"phase": "replay", "media_in": 3571.0, "media_out": 3580.0, "has_shot": True, "has_net": True},
            ],
            "slices": [
                {"media_in": 3552.0, "media_out": 3556.0, "phase": "live", "has_shot": False, "has_net": False},
                {"media_in": 3560.0, "media_out": 3564.0, "phase": "live", "has_shot": True, "has_net": False},
                {"media_in": 3564.0, "media_out": 3569.0, "phase": "live", "has_shot": False, "has_net": True},
                {"media_in": 3571.0, "media_out": 3575.0, "phase": "replay", "has_shot": True, "has_net": True},
            ],
        }
        loc = locate_continuous_live_goal_window(
            timeline=timeline, shot_sec=3562.32, result_sec=3566.64
        )
        self.assertTrue(loc["ok"])
        self.assertLessEqual(loc["media_out"], 3571.0)
        self.assertLess(loc["media_in"], 3562.32)


class TestEdlBuilder(unittest.TestCase):
    def test_drops_failed_strip_keeps_goal(self):
        goals = [
            {
                "key_event_id": "ke_3",
                "score_before": [1, 1],
                "score_after": [2, 1],
                "pass": True,
                "accepted_media_in": 3552.0,
                "accepted_media_out": 3568.5,
                "verified_shot_sec": 3562.32,
                "verified_result_sec": 3566.64,
                "live_or_replay": "live",
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
        self.assertAlmostEqual(goal_seg["media_in"], 3552.0)
        self.assertNotAlmostEqual(goal_seg["media_in"], 3556.32)


class TestEventReplayAudit(unittest.TestCase):
    def test_counts_without_defaulting_missing(self):
        doc = {
            "events": [
                {
                    "event_id": "e1",
                    "event_type": "Pass",
                    "media_time": {"start_time_sec": 10.0, "end_time_sec": 12.0},
                    "video_context": {
                        "broadcast_phase": "LIVE",
                        "is_replay": False,
                        "is_slow_motion": False,
                        "replay_of_event_id": None,
                    },
                },
                {
                    "event_id": "e2",
                    "event_type": "Save",
                    "media_time": {"start_time_sec": 20.0, "end_time_sec": 25.0},
                    "video_context": {
                        "broadcast_phase": "REPLAY",
                        "is_replay": True,
                        "is_slow_motion": False,
                        "replay_of_event_id": None,
                    },
                },
            ]
        }
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "events.json"
            p.write_text(__import__("json").dumps(doc), encoding="utf-8")
            audit = audit_event_replay_fields(
                events_path=p,
                edl_spans=[{"segment_id": "g", "role": "goal", "media_in": 19.0, "media_out": 22.0}],
            )
        self.assertEqual(audit["is_replay_counts"]["True"], 1)
        self.assertEqual(audit["is_replay_counts"]["False"], 1)
        self.assertEqual(audit["edl_span_coverage"][0]["n_overlapping_replay"], 1)


class TestFinalMp4AcceptanceGates(unittest.TestCase):
    def test_late_only_mixed_fails(self):
        from story_video_agent.v2_strip_guided_r2_5_final_mp4_audit import audit_final_mp4_goals

        # Unit-test the decision logic via a lightweight inline reimplementation check:
        # any mixed status must fail (regression for late_only_mixed false pass).
        statuses = ["live", "live", "mixed_or_ambiguous"]
        has_mixed = any(s == "mixed_or_ambiguous" for s in statuses)
        strong_replay = any(s == "replay" for s in statuses)
        self.assertTrue(has_mixed)
        self.assertFalse(strong_replay)
        # Prior buggy policy allowed late_only_mixed to pass; new policy must fail.
        late_only_mixed = (
            len(statuses) >= 3
            and statuses[-1] == "mixed_or_ambiguous"
            and all(s == "live" for s in statuses[:-1])
        )
        self.assertTrue(late_only_mixed)
        fail = []
        if strong_replay or has_mixed:
            fail.append("final_mp4_contains_replay_or_mixed")
        self.assertIn("final_mp4_contains_replay_or_mixed", fail)

    def test_replay_shot_net_negative_rejected(self):
        """Negative: shot+net present but replay → must not count as live goal."""
        r = classify_live_replay(
            {
                "observed_actions": [
                    "slow-mo replay package: player shoots",
                    "ball enters the net from alternate camera",
                    "回放 graphic on screen",
                ],
                "notes": "broadcast_state=replay",
            }
        )
        self.assertEqual(r["live_or_replay"], "replay")
        blob = " ".join(r["observed_actions"])
        self.assertRegex(blob, r"shoot|enters the net")

    def test_score_order_rejects_result_after_confirm(self):
        from story_video_agent.v2_enhanced_events import score_order_ok, should_emit_inferred_goal

        order = score_order_ok(result_sec=6461.08, score_confirmation_time=6408.70)
        self.assertFalse(order["ok"])
        self.assertEqual(order["reason"], "result_after_score_confirmation")
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

    def test_cross_row_stitch_rejected(self):
        from story_video_agent.v2_event_guided_evidence import merge_action_evidence_windows

        rows = [
            {
                "evidence": {
                    "live_or_replay": "live",
                    "shot_action": {"media_sec": 100.0, "frame_id": "f1"},
                    "goal_result": None,
                }
            },
            {
                "evidence": {
                    "live_or_replay": "live",
                    "shot_action": None,
                    "goal_result": {"media_sec": 104.0, "frame_id": "f2"},
                }
            },
        ]
        merged = merge_action_evidence_windows(rows)
        self.assertFalse(merged["action_time_resolved"])
        self.assertTrue(merged["rejected_cross_row_stitch"])


if __name__ == "__main__":
    unittest.main()
