"""Round 2.2 unit tests — live/replay audit, merge dedupe, EDL gates (no real API)."""

from __future__ import annotations

import unittest

from story_video_agent.v2_goal_live_replay_audit import (
    apply_audit_correction,
    audit_inferred_goal,
    propose_live_shot_result_pair,
)
from story_video_agent.v2_strip_guided_r2_2_edl import build_candidate_edl
from story_video_agent.v2_strip_guided_r2_2_merge import dedupe_inferred_goals
from story_video_agent.v2_strip_guided_r2_2_story import build_t01_story_graph


def _vv_deficit_like():
    return [
        {
            "evidence_id": "rcv_live",
            "frames": [
                {"frame_id": "f_0059_982050", "actual_media_sec": 982.05},
                {"frame_id": "f_0062_1026990", "actual_media_sec": 1027.0},
            ],
            "observed_actions": [
                "Goal scored by Canada: Ball enters net past diving goalkeeper, players celebrate immediately (f_0059_982050).",
                "Replay angle showing the ball crossing the goal line into the net (f_0062_1026990).",
            ],
        }
    ]


class TestLiveReplayAudit(unittest.TestCase):
    def test_corrects_replay_splice_to_live_net(self):
        inferred = {
            "inferred_event_id": "inferred_goal_mg_initial_deficit_0",
            "verification_status": "verified_action",
            "shot_action": {"frame_id": "f_x", "media_sec": 1026.12},
            "goal_result": {"frame_id": "f_0062_1026990", "media_sec": 1027.0},
            "media_time": {"event_time_sec": 1027.0, "start_time_sec": 1024.0, "end_time_sec": 1030.0},
            "related_score_transition": {"score_before": None, "score_after": [0, 1], "score_confirmation_time": 1079.0},
            "video_context": {"is_replay": False},
            "source": "video_agent_inferred",
        }
        audit = audit_inferred_goal(inferred_event=inferred, verifications=_vv_deficit_like())
        self.assertEqual(audit["status"], "corrected_live_rebind")
        corr = apply_audit_correction(inferred, audit)
        self.assertEqual(corr["verification_status"], "verified_action")
        self.assertAlmostEqual(corr["goal_result"]["media_sec"], 982.05, places=2)
        self.assertEqual(corr["video_context"]["broadcast_phase"], "LIVE")

    def test_propose_same_frame_live_goal_clause(self):
        prop = propose_live_shot_result_pair(
            verifications=_vv_deficit_like(), score_confirmation_time=1079.0
        )
        self.assertIsNotNone(prop)
        self.assertEqual(prop["verification_status"], "verified_action")
        self.assertAlmostEqual(prop["goal_result"]["media_sec"], 982.05, places=2)


class TestMergeDedupe(unittest.TestCase):
    def test_dedupe_per_score_transition(self):
        goals = [
            {
                "source": "video_agent_inferred",
                "inferred_event_id": "a",
                "verification_status": "verified_action",
                "related_score_transition": {"score_before": [1, 1], "score_after": [2, 1]},
                "media_time": {"event_time_sec": 3600.0},
                "goal_result": {"media_sec": 3600.0},
            },
            {
                "source": "video_agent_inferred",
                "inferred_event_id": "b",
                "verification_status": "verified_action",
                "related_score_transition": {"score_before": [1, 1], "score_after": [2, 1]},
                "media_time": {"event_time_sec": 3566.0},
                "goal_result": {"media_sec": 3566.0},
                "video_context": {"broadcast_phase": "LIVE"},
            },
        ]
        out = dedupe_inferred_goals(goals)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["inferred_event_id"], "b")


class TestStoryAndEdl(unittest.TestCase):
    def test_story_graph_and_edl(self):
        goals = [
            {
                "inferred_event_id": "inferred_goal_mg_initial_deficit_0",
                "verification_status": "verified_action",
                "related_score_transition": {"score_before": None, "score_after": [0, 1]},
                "shot_action": {"media_sec": 982.0},
                "goal_result": {"media_sec": 982.0},
                "edit_window": {"media_in": 980.0, "media_out": 985.0},
                "media_time": {"event_time_sec": 982.0},
                "video_context": {"broadcast_phase": "LIVE"},
            },
            {
                "inferred_event_id": "inferred_goal_mg_trans_1",
                "verification_status": "verified_action",
                "related_score_transition": {"score_before": [0, 1], "score_after": [1, 1]},
                "shot_action": {"media_sec": 3105.0},
                "goal_result": {"media_sec": 3107.0},
                "edit_window": {"media_in": 3103.0, "media_out": 3110.0},
                "media_time": {"event_time_sec": 3107.0},
                "video_context": {"broadcast_phase": "LIVE"},
            },
            {
                "inferred_event_id": "inferred_goal_mg_trans_2",
                "verification_status": "verified_action",
                "related_score_transition": {"score_before": [1, 1], "score_after": [2, 1]},
                "shot_action": {"media_sec": 3562.0},
                "goal_result": {"media_sec": 3566.0},
                "edit_window": {"media_in": 3560.0, "media_out": 3569.0},
                "media_time": {"event_time_sec": 3566.0},
                "video_context": {"broadcast_phase": "LIVE"},
            },
        ]
        sg = build_t01_story_graph(
            verified_goals=goals,
            strip_b_bundle={"chains": []},
            event_digest={
                "score_anchors": [
                    {"kind": "score_change", "score_after": [0, 1]},
                    {"kind": "score_change", "score_after": [1, 1]},
                    {"kind": "score_change", "score_after": [2, 1]},
                ]
            },
            evidence_ids=["e1"],
        )
        self.assertEqual(sg["n_verified_goal_nodes"], 3)
        self.assertEqual(sg["discovery_status"], "story_candidate")
        edl = build_candidate_edl(story_graph=sg)
        self.assertEqual(edl["n_segments"], 3)
        self.assertFalse(edl["render_ready"])
        self.assertTrue(edl["narrative_completeness"]["ok"])


if __name__ == "__main__":
    unittest.main()
