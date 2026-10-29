"""Round 2.1 unit tests — timing localization + emit gates (no real API)."""

from __future__ import annotations

import unittest

from story_video_agent.api_provider import ApiProvider
from story_video_agent.v2_api_preflight import is_fatal_api_failure
from story_video_agent.v2_enhanced_events import make_inferred_goal_event, should_emit_inferred_goal
from story_video_agent.v2_event_guided_evidence import (
    grade_with_frame_evidence,
    localize_goal_action_times,
    merge_action_evidence_windows,
)
from story_video_agent.v2_goal_recovery_agent import V2GoalRecoveryAgent


class TestFatalApi(unittest.TestCase):
    def test_invalid_model_400_fatal(self):
        self.assertTrue(
            is_fatal_api_failure(
                {"http_status": 400, "detail_scrubbed": "Invalid model name passed in model=X"}
            )
        )
        self.assertTrue(is_fatal_api_failure({"http_status": 401, "detail_scrubbed": "auth"}))
        self.assertFalse(is_fatal_api_failure({"http_status": 429, "detail_scrubbed": "rate"}))


class TestActionTiming(unittest.TestCase):
    def _obs(self):
        return {
            "media_start_sec": 100.0,
            "media_end_sec": 112.0,
            "frames": [
                {"frame_id": "f_001", "requested_media_sec": 101.0, "actual_media_sec": 101.0},
                {"frame_id": "f_002", "requested_media_sec": 104.0, "actual_media_sec": 104.0},
                {"frame_id": "f_003", "requested_media_sec": 108.0, "actual_media_sec": 108.0},
            ],
            "perception": {
                "notes": "On f_002 a clear shot toward goal; on f_003 the ball enters the net.",
                "observed_actions": ["shot on f_002", "ball into the net on f_003"],
                "frame_ids": ["f_002", "f_003"],
                "normalized_ok": True,
            },
        }

    def test_localizes_shot_and_result_not_midpoint(self):
        obs = self._obs()
        timing = localize_goal_action_times(
            observation=obs,
            evidence_hint={
                "supporting_frame_ids": ["f_002", "f_003"],
                "shooting_action_evidence": True,
                "goal_result_evidence": True,
            },
        )
        self.assertTrue(timing["action_time_resolved"])
        self.assertEqual(timing["shot_action"]["media_sec"], 104.0)
        self.assertEqual(timing["goal_result"]["media_sec"], 108.0)
        mid = timing["forbidden_midpoint_of_observation_window"]
        self.assertAlmostEqual(mid, 106.0)
        self.assertNotAlmostEqual(timing["goal_result"]["media_sec"], mid)

    def test_grade_requires_bound_times_for_action_localized(self):
        # Keywords + cites but no per-clause frame binding → not action_localized
        obs = {
            "media_start_sec": 10.0,
            "media_end_sec": 20.0,
            "frames": [
                {"frame_id": "f_010", "actual_media_sec": 12.0, "requested_media_sec": 12.0},
                {"frame_id": "f_011", "actual_media_sec": 18.0, "requested_media_sec": 18.0},
            ],
            "perception": {
                "notes": "There is a shot and the ball into the net somewhere.",
                "observed_actions": ["shot", "into the net"],
                "frame_ids": ["f_010", "f_011"],
                "normalized_ok": True,
            },
        }
        ev = grade_with_frame_evidence(observation=obs, window_span_sec=10.0)
        self.assertNotEqual(ev["grade"], "action_localized")
        self.assertFalse(should_emit_inferred_goal(ev))

    def test_emit_uses_result_time(self):
        evidence = {
            "grade": "action_localized",
            "verification_status": "verified_action",
            "live_or_replay": "live",
            "shooting_action_evidence": True,
            "goal_result_evidence": True,
            "action_time_resolved": True,
            "shot_action": {"frame_id": "f_002", "media_sec": 104.0},
            "goal_result": {"frame_id": "f_003", "media_sec": 108.0},
            "edit_window": {"media_in": 102.0, "media_out": 111.0},
            "uncertainty": 0.2,
        }
        self.assertTrue(should_emit_inferred_goal(evidence))
        ge = make_inferred_goal_event(
            inferred_event_id="inferred_goal_x",
            media_time_sec=float(evidence["goal_result"]["media_sec"]),
            media_start_sec=102.0,
            media_end_sec=111.0,
            related_score_transition={"score_before": [1, 1], "score_after": [2, 1]},
            supporting_frame_ids=["f_002", "f_003"],
            supporting_video_windows=[{"start": 100, "end": 112}],
            verification_status="verified_action",
            confidence=0.8,
            uncertainty=0.2,
            live_or_replay="live",
            shot_action=evidence["shot_action"],
            goal_result=evidence["goal_result"],
            edit_window=evidence["edit_window"],
        )
        self.assertEqual(ge["media_time"]["event_time_sec"], 108.0)
        self.assertNotAlmostEqual(ge["media_time"]["event_time_sec"], 106.0)
        self.assertTrue(ge["as_story_node_candidate"])

    def test_aggregate_across_windows(self):
        rows = [
            {
                "evidence": {
                    "live_or_replay": "live",
                    "shot_action": {"frame_id": "f_a", "media_sec": 50.0},
                    "goal_result": None,
                }
            },
            {
                "evidence": {
                    "live_or_replay": "live",
                    "shot_action": None,
                    "goal_result": {"frame_id": "f_b", "media_sec": 52.5},
                }
            },
        ]
        agg = merge_action_evidence_windows(rows)
        self.assertTrue(agg["action_time_resolved"])
        self.assertEqual(agg["shot_action"]["media_sec"], 50.0)
        self.assertEqual(agg["goal_result"]["media_sec"], 52.5)

    def test_aggregate_rejects_wide_shot_result_gap(self):
        rows = [
            {
                "evidence": {
                    "live_or_replay": "live",
                    "shot_action": {"frame_id": "f_a", "media_sec": 6359.0},
                    "goal_result": None,
                }
            },
            {
                "evidence": {
                    "live_or_replay": "live",
                    "shot_action": None,
                    "goal_result": {"frame_id": "f_b", "media_sec": 6461.0},
                }
            },
        ]
        agg = merge_action_evidence_windows(rows)
        self.assertFalse(agg["action_time_resolved"])
        self.assertTrue(agg.get("rejected_wide_gap"))


class TestEarlierThanScoreboardRule(unittest.TestCase):
    def _agent(self) -> V2GoalRecoveryAgent:
        api = ApiProvider(
            force_mock=True,
            require_real=False,
            max_calls=8,
            max_cost_usd=1.0,
            max_completion_tokens=256,
        )
        return V2GoalRecoveryAgent(api=api, use_llm_planner=False)

    def test_walks_earlier_after_scoreboard_after(self):
        phases = [
            {"phase": "early_third", "start_sec": 3145.98, "end_sec": 3329.77},
            {"phase": "mid_third", "start_sec": 3329.77, "end_sec": 3513.56},
            {"phase": "late_third_near_confirm", "start_sec": 3513.56, "end_sec": 3697.35},
            {"phase": "refine_tail", "start_sec": 3652.35, "end_sec": 3697.35},
        ]
        state = {
            "open_candidates": [
                {
                    "candidate_id": "mg_trans_2",
                    "kind": "score_change_missing_goal",
                    "score_before": [1, 1],
                    "score_after": [2, 1],
                    "score_confirmation_time": 3697.35,
                    "previous_score_observation_time": 3145.98,
                    "search_region": {"phases": phases},
                    "n_observations": 1,
                    "last_grade": "scoreboard_only",
                    "last_window": {"start": 3652.35, "end": 3697.35},
                    "last_score_pairs": [[2, 1]],
                    "board_after_seen": True,
                    "board_after_window": {"start": 3652.35, "end": 3697.35},
                }
            ],
            "frames_remaining": 40,
        }
        d = self._agent().decide(state, 1, 10)
        self.assertEqual(d["tool"], "refine")
        self.assertEqual(d["reason"], "rule_search_earlier_than_scoreboard_after")
        self.assertLessEqual(float(d["arguments"]["end"]), 3652.35 + 1e-6)
        self.assertLess(float(d["arguments"]["start"]), float(d["arguments"]["end"]))

    def test_keeps_walking_when_earlier_window_still_after(self):
        state = {
            "open_candidates": [
                {
                    "candidate_id": "mg_trans_2",
                    "kind": "score_change_missing_goal",
                    "score_before": [1, 1],
                    "score_after": [2, 1],
                    "score_confirmation_time": 3697.35,
                    "previous_score_observation_time": 3145.98,
                    "search_region": {
                        "phases": [
                            {"phase": "late", "start_sec": 3145.98, "end_sec": 3697.35},
                        ]
                    },
                    "n_observations": 2,
                    "last_grade": "goal_candidate",
                    "last_window": {"start": 3577.35, "end": 3652.35},
                    "last_score_pairs": [[2, 1]],
                    "board_after_seen": True,
                    "board_after_window": {"start": 3577.35, "end": 3652.35},
                    "same_window_streak": 1,
                }
            ],
            "frames_remaining": 40,
        }
        d = self._agent().decide(state, 2, 10)
        self.assertEqual(d["reason"], "rule_search_earlier_than_scoreboard_after")
        self.assertLessEqual(float(d["arguments"]["end"]), 3577.35 + 1e-6)

    def test_short_frame_cite_binds_shot_time(self):
        obs = {
            "media_start_sec": 3577.35,
            "media_end_sec": 3652.35,
            "frames": [
                {"frame_id": "f_0010_3637320", "actual_media_sec": 3637.32, "requested_media_sec": 3637.32},
                {"frame_id": "f_0011_3652300", "actual_media_sec": 3652.3, "requested_media_sec": 3652.3},
            ],
            "perception": {
                "notes": "Player shooting the ball towards the goal (f_0010). Keeper dive; ball not clearly into the net.",
                "observed_actions": [
                    "Player in black jersey shooting the ball towards the goal (f_0010)",
                    "Goalkeeper diving to save the shot (f_0010)",
                ],
                "frame_ids": ["f_0010_3637320", "f_0011_3652300"],
                "normalized_ok": True,
            },
        }
        timing = localize_goal_action_times(
            observation=obs,
            evidence_hint={
                "supporting_frame_ids": ["f_0010_3637320", "f_0011_3652300"],
                "shooting_action_evidence": True,
                "goal_result_evidence": False,
            },
        )
        self.assertIsNotNone(timing["shot_action"])
        self.assertAlmostEqual(timing["shot_action"]["media_sec"], 3637.32)
        self.assertIsNone(timing["goal_result"])


if __name__ == "__main__":
    unittest.main()
