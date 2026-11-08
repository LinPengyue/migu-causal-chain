"""Phase 8 Commit-2: feedback-aware search + planner (zero HTTP)."""
from __future__ import annotations

import inspect
import unittest

from story_video_agent_v3.story_evidence_search import _apply_feedback_to_candidates, run_story_evidence_search
from story_video_agent_v3.story_paid_eval import run_llm_revision_planner
from story_video_agent_v3.story_revision_planner import plan_from_diagnosis


class TestSignaturesBackwardCompatible(unittest.TestCase):
    def test_search_feedback_optional(self):
        sig = inspect.signature(run_story_evidence_search)
        self.assertIn("feedback_context", sig.parameters)
        self.assertIsNone(sig.parameters["feedback_context"].default)

    def test_planner_feedback_optional(self):
        sig = inspect.signature(plan_from_diagnosis)
        self.assertIn("feedback_context", sig.parameters)
        self.assertIsNone(sig.parameters["feedback_context"].default)

    def test_paid_planner_feedback_optional(self):
        sig = inspect.signature(run_llm_revision_planner)
        self.assertIn("feedback_context", sig.parameters)
        self.assertIsNone(sig.parameters["feedback_context"].default)


class TestFeedbackChangesSecondAttempt(unittest.TestCase):
    def test_second_search_suppresses_same_pts_not_global_ban(self):
        verified = [
            {
                "candidate_id": "cand_a",
                "issue_id": "jump_1",
                "category": "transition",
                "action": "search_add",
                "source_pts_start": 3504.14,
                "source_pts_end": 3515.83,
                "insert_after_segment_id": "seg_setup",
                "before_segment_id": "seg_turn",
                "score": 0.9,
            },
            {
                "candidate_id": "cand_b",
                "issue_id": "jump_1",
                "category": "transition",
                "source_pts_start": 4000.0,
                "source_pts_end": 4012.0,
                "insert_after_segment_id": "seg_setup",
                "before_segment_id": "seg_turn",
                "score": 0.7,
            },
        ]
        fb = {
            "records": [
                {
                    "action": "search_add",
                    "source_pts": [3504.14, 3515.83],
                    "failure_class": "UNCERTAIN_OR_UNVERIFIED",
                    "issue_signature": {
                        "category": "transition",
                        "anchor_segment_ids": ["seg_setup"],
                    },
                }
            ]
        }
        out = _apply_feedback_to_candidates(verified, fb)
        ids = [c["candidate_id"] for c in out["verified_candidates"]]
        self.assertNotIn("cand_a", ids)
        self.assertIn("cand_b", ids)
        self.assertTrue(out["feedback_filter_applied"])
        # Unverified suppress is temporary — not a permanent ban flag
        self.assertFalse(
            any((x.get("feedback_skip") or {}).get("pts_permanently_banned") for x in out["feedback_filtered_candidates"])
        )

    def test_planner_reads_feedback_and_does_not_force_repeat(self):
        diagnosis = {
            "issues": [
                {
                    "issue_id": "jump_1",
                    "category": "transition",
                    "severity": "major",
                    "diagnosis_status": "HYPOTHESIS_NEEDS_VIDEO",
                    "evidence_sufficiency": "needs_video_verify",
                    "segment_ids": ["seg_a", "seg_b"],
                }
            ],
            "protected_goal_segment_ids": ["seg_goal"],
        }
        search = {
            "search_success": False,
            "verified_candidates": [],
            "feedback_filtered_candidates": [
                {"candidate_id": "cand_a", "source_pts_start": 1.0, "source_pts_end": 2.0}
            ],
            "feedback_filter_applied": True,
        }
        fb = {
            "summary": {
                "n_records": 1,
                "tried_revisions": [
                    {
                        "action": "search_add",
                        "source_pts": [1.0, 2.0],
                        "failure_class": "UNCERTAIN_OR_UNVERIFIED",
                        "next_search_requirement": "alternate narrative function",
                    }
                ]
            }
        }
        plan = plan_from_diagnosis(
            diagnosis, search_results=search, feedback_context=fb, offline=True
        )
        self.assertEqual(plan["decision"], "UNRESOLVED")
        self.assertTrue(plan["phase8_rules"]["use_prior_round_feedback"])
        self.assertEqual(plan["search_feedback_filter"]["filtered_count"], 1)
        self.assertEqual(plan["search_feedback_filter"]["kept_count"], 0)
        self.assertIn("no_remaining_live_candidates_after_feedback_filter", plan["rationale"])


if __name__ == "__main__":
    unittest.main()
