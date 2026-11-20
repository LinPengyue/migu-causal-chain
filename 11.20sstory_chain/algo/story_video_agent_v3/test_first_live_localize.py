"""Unit tests for V3-P3 first-live localization (no match-specific PTS hardcoded)."""
from __future__ import annotations

import unittest

from .first_live_localize import (
    classify_semantic_label,
    covered_intervals,
    merge_score_bounds,
    propose_localization_candidates,
    uncovered_subintervals,
)


class ScoreBoundsTests(unittest.TestCase):
    def test_merge_last_before_first_after_from_obs(self):
        bounds = merge_score_bounds(
            score_before=[1, 1],
            score_after=[2, 1],
            ocr_rows=[],
            human_obs=[
                {"media_sec": 100.0, "score_tuple": [1, 1]},
                {"media_sec": 110.0, "score_tuple": [1, 1]},
                {"media_sec": 118.0, "score_tuple": [2, 1]},
                {"media_sec": 200.0, "score_tuple": [2, 1]},
            ],
            event_rows=[{"event_time_sec": 205.0, "score_pair": [2, 1], "event_id": "e1"}],
            confirm_sec=205.0,
        )
        self.assertEqual(bounds["last_before_obs"]["media_sec"], 110.0)
        self.assertEqual(bounds["first_after_obs"]["media_sec"], 118.0)
        self.assertEqual(bounds["unknown_interval"]["media_in"], 110.0)
        self.assertEqual(bounds["unknown_interval"]["media_out"], 118.0)

    def test_uncovered_prefers_gaps_not_historical(self):
        covered = covered_intervals([
            {"media_in": 50.0, "media_out": 80.0},
        ])
        gaps = uncovered_subintervals(40.0, 120.0, covered)
        self.assertTrue(any(abs(a - 80.0) < 0.1 for a, _ in gaps))
        self.assertFalse(any(a <= 50.0 and b >= 80.0 for a, b in gaps))


class ProposalTests(unittest.TestCase):
    def test_prefers_uncovered_over_identical_historical_recut(self):
        plan = propose_localization_candidates(
            role="opening_deficit",
            confirm_sec=200.0,
            score_before=[1, 1],
            score_after=[2, 1],
            historical_clues=[
                {"media_in": 100.0, "media_out": 125.0, "candidate_id": "hist_a"},
            ],
            events=[],
            score_bounds={
                "unknown_interval": {"media_in": 125.0, "media_out": 150.0},
                "last_before_obs": {"media_sec": 125.0, "score_tuple": [1, 1]},
                "first_after_obs": {"media_sec": 150.0, "score_tuple": [2, 1]},
            },
            max_candidates=3,
            max_video_read_sec=90.0,
            lookback_sec=120.0,
        )
        origins = [c["origin"] for c in plan["candidates"]]
        self.assertTrue(any("uncovered" in o or o == "score_unknown_core" for o in origins))
        # First selected should not be pure historical when uncovered exists
        self.assertNotEqual(plan["candidates"][0]["origin"], "historical_clue_recheck")

    def test_no_hardcoded_b_pts_in_proposal(self):
        """Generic proposal must work for arbitrary confirm times (not B-only constants)."""
        plan = propose_localization_candidates(
            role="opening_deficit",
            confirm_sec=5000.0,
            score_before=[0, 0],
            score_after=[1, 0],
            historical_clues=[],
            events=[],
            score_bounds={"unknown_interval": None},
            max_candidates=2,
            lookback_sec=90.0,
        )
        for c in plan["candidates"]:
            self.assertGreaterEqual(c["media_in"], 5000.0 - 120.0)
            self.assertLessEqual(c["media_out"], 5000.0 + 0.1)


class ClassifierTests(unittest.TestCase):
    def test_never_auto_verify_without_semantic_log(self):
        clf = classify_semantic_label(
            media_in=100.0,
            media_out=120.0,
            score_bounds={
                "last_before_obs": {"media_sec": 105.0},
                "first_after_obs": {"media_sec": 115.0},
            },
            events=[],
            frame_notes={"box_scramble": True, "celebration_like": True, "attacking_team_match": True},
        )
        self.assertEqual(clf["semantic_label"], "possible_first_live")
        self.assertFalse(clf["agent_auto_verified"])
        self.assertEqual(clf["verification_status"], "unresolved")

    def test_post_score_celebration_label(self):
        clf = classify_semantic_label(
            media_in=120.0,
            media_out=140.0,
            score_bounds={"first_after_obs": {"media_sec": 115.0}, "last_before_obs": {"media_sec": 100.0}},
            events=[],
            frame_notes={"celebration_like": True},
        )
        self.assertEqual(clf["semantic_label"], "post_goal_celebration")

    def test_human_review_is_separate_evidence_type(self):
        clf = classify_semantic_label(
            media_in=100.0,
            media_out=120.0,
            score_bounds={},
            events=[],
            human_review={
                "conclusion_label": "possible_first_live",
                "observed_shot": True,
                "observed_net": False,
                "first_live_visual_ok": False,
                "attacking_team_match": True,
                "claims_continuous_live": True,
                "live_or_replay": "live",
                "evidence_gaps": ["observed_net_unconfirmed"],
                "reviewer": "agent_visual_audit",
            },
        )
        self.assertTrue(clf["human_video_supported"])
        self.assertFalse(clf["agent_auto_verified"])
        self.assertEqual(clf["semantic_label"], "possible_first_live")


if __name__ == "__main__":
    unittest.main()
