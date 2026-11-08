"""Phase 8 Commit-1: pure feedback + loop policy (zero HTTP)."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from story_video_agent_v3.story_loop_policy import (
    apply_transition,
    evaluate_round_transition,
    init_loop_state,
)
from story_video_agent_v3.story_revision_feedback import (
    classify_failure_class,
    load_phase7_round_into_feedback,
    normalize_feedback,
    should_penalize_candidate,
    summarize_feedback,
)

PHASE7_ROUND = Path(
    "/data2/lpy1/_story_va_outputs/v3/plan2/story_quality_phase7_20261108/"
    "A_bridge_e2e/02_round_01"
)


class TestFailureClass(unittest.TestCase):
    def test_opaque_reject_not_confirmed_negative(self):
        fc = classify_failure_class(
            quality="UNCERTAIN",
            evidence_status="INSUFFICIENT",
            technical_error=True,
            semantic_status="NOT_EVALUATED",
        )
        self.assertEqual(fc, "TECHNICAL_FAILURE")

    def test_worse_requires_sufficient_evidence(self):
        self.assertEqual(
            classify_failure_class(
                quality="WORSE", evidence_status="INSUFFICIENT"
            ),
            "UNCERTAIN_OR_UNVERIFIED",
        )
        self.assertEqual(
            classify_failure_class(
                quality="WORSE", evidence_status="SUFFICIENT"
            ),
            "CONFIRMED_NEGATIVE",
        )


class TestNormalizePhase7Artifact(unittest.TestCase):
    @unittest.skipUnless(PHASE7_ROUND.is_dir(), "Phase7 artifact missing")
    def test_phase7_reject_is_not_confirmed_negative(self):
        store = load_phase7_round_into_feedback(PHASE7_ROUND)
        self.assertGreaterEqual(len(store.records), 1)
        row = store.records[0]
        self.assertNotEqual(row["failure_class"], "CONFIRMED_NEGATIVE")
        self.assertIn(
            row["failure_class"],
            ("UNCERTAIN_OR_UNVERIFIED", "TECHNICAL_FAILURE"),
        )
        self.assertFalse(row.get("pts_permanently_banned"))
        self.assertEqual(row.get("source_pts"), [3504.14, 3515.83])
        summary = store.summary()
        self.assertTrue(summary["opaque_reject_is_not_confirmed_negative"])


class TestPenalizeOverlap(unittest.TestCase):
    def test_confirmed_negative_suppresses_overlap_not_all_pts(self):
        memory = [
            {
                "action": "search_add",
                "source_pts": [3504.14, 3515.83],
                "failure_class": "CONFIRMED_NEGATIVE",
                "issue_signature": {
                    "category": "transition",
                    "anchor_segment_ids": ["seg_setup"],
                },
            }
        ]
        hit = should_penalize_candidate(
            memory,
            issue_signature={"category": "transition", "anchor_segment_ids": ["seg_setup"]},
            action="search_add",
            source_pts=[3505.0, 3514.0],
        )
        self.assertTrue(hit["suppress"])
        self.assertFalse(hit["pts_permanently_banned"])
        miss = should_penalize_candidate(
            memory,
            issue_signature={"category": "transition", "anchor_segment_ids": ["seg_setup"]},
            action="search_add",
            source_pts=[5000.0, 5010.0],
        )
        self.assertFalse(miss["suppress"])


class TestLoopPolicy(unittest.TestCase):
    def test_promising_continues_working_not_promote(self):
        state = init_loop_state(edl_path="e0.json", mp4_path="m0.mp4")
        tr = evaluate_round_transition(
            state,
            {
                "version_id": "v1",
                "parent_version_id": "v0",
                "edl_changed": True,
                "rendered": True,
                "mp4_exists": True,
            },
            {
                "safety": "PASS",
                "quality": "PROMISING",
                "evidence": "PARTIAL",
                "source_kind": "FIXTURE",
            },
            {"rounds_done": 1, "max_rounds": 3, "has_executable_revision": True},
        )
        self.assertEqual(tr["next_action"], "CONTINUE_WORKING")
        self.assertEqual(tr["working_ref"], "v1")
        self.assertEqual(tr["best_ref"], "v0")
        self.assertFalse(tr["promote"])
        state2 = apply_transition(
            state,
            tr,
            candidate_version={
                "parent_version_id": "v0",
                "edl_path": "e1.json",
                "mp4_path": "m1.mp4",
                "safety": "PASS",
                "quality": "PROMISING",
                "source": "FIXTURE",
            },
        )
        self.assertEqual(state2["working_version_id"], "v1")
        self.assertEqual(state2["best_verified_version_id"], "v0")

    def test_uncertain_not_auto_negative_reobserve_once(self):
        state = init_loop_state()
        tr = evaluate_round_transition(
            state,
            {"version_id": "v1", "edl_changed": True, "rendered": True},
            {"safety": "PASS", "quality": "UNCERTAIN", "evidence": "INSUFFICIENT"},
            {
                "rounds_done": 1,
                "max_rounds": 3,
                "has_new_visual_target": True,
                "specific_reobserve_target": {
                    "issue_id": "jump_1",
                    "question": "Does insert supply narrative pressure?",
                    "source_pts": [10.0, 20.0],
                },
                "has_executable_revision": True,
            },
        )
        self.assertEqual(tr["next_action"], "REOBSERVE")
        self.assertFalse(tr["record_confirmed_negative"])

    def test_budget_after_current_better_retained(self):
        state = init_loop_state()
        tr = evaluate_round_transition(
            state,
            {
                "version_id": "v1",
                "edl_changed": True,
                "rendered": True,
                "mp4_exists": True,
            },
            {
                "safety": "PASS",
                "quality": "BETTER",
                "evidence": "SUFFICIENT",
                "issue_effect": "RESOLVED",
                "global_regression": "NO",
                "source_kind": "REAL_VLM",
                "compared_against_best": True,
            },
            {"rounds_done": 1, "max_rounds": 1},
        )
        self.assertEqual(tr["next_action"], "PROMOTE_BEST")
        self.assertTrue(tr["promote"])
        self.assertEqual(tr.get("stop_reason"), "STOP_BUDGET")
        state2 = apply_transition(state, tr)
        self.assertEqual(state2["best_verified_version_id"], "v1")

    def test_promising_real_continues_without_accept(self):
        state = init_loop_state()
        tr = evaluate_round_transition(
            state,
            {
                "version_id": "v1",
                "edl_changed": True,
                "rendered": True,
                "mp4_exists": True,
            },
            {
                "safety": "PASS",
                "quality": "PROMISING",
                "evidence": "PARTIAL",
                "source_kind": "REAL_VLM",
                "accept_candidate": False,
            },
            {"rounds_done": 1, "max_rounds": 3, "has_executable_revision": True},
        )
        self.assertEqual(tr["next_action"], "CONTINUE_WORKING")
        self.assertTrue(tr["accept_candidate_ignored"])

    def test_missing_render_never_working(self):
        state = init_loop_state()
        tr = evaluate_round_transition(
            state,
            {"version_id": "v1", "edl_changed": True, "rendered": False, "mp4_exists": False},
            {
                "safety": "PASS",
                "quality": "PROMISING",
                "evidence": "PARTIAL",
                "source_kind": "FIXTURE",
            },
            {"rounds_done": 1, "max_rounds": 3},
        )
        self.assertNotEqual(tr["working_ref"], "v1")
        self.assertIn("promising_missing_render", ",".join(tr["reason_codes"]))

    def test_worse_sufficient_replans_with_negative(self):
        state = init_loop_state()
        tr = evaluate_round_transition(
            state,
            {"version_id": "v1", "edl_changed": True, "rendered": True},
            {"safety": "PASS", "quality": "WORSE", "evidence": "SUFFICIENT"},
            {"rounds_done": 1, "max_rounds": 3, "has_distinct_alternative": True},
        )
        self.assertEqual(tr["next_action"], "REPLAN_FROM_BEST")
        self.assertTrue(tr["record_confirmed_negative"])
        self.assertEqual(tr["working_ref"], "v0")

    def test_safety_fail_stops(self):
        state = init_loop_state()
        tr = evaluate_round_transition(
            state,
            {"version_id": "v1", "edl_changed": True},
            {"safety": "FAIL", "quality": "PROMISING", "evidence": "PARTIAL", "hard_vetoes": ["replay"]},
            {"rounds_done": 1, "max_rounds": 3},
        )
        self.assertEqual(tr["next_action"], "STOP_SAFETY")

    def test_fixture_better_does_not_promote_best(self):
        state = init_loop_state()
        tr = evaluate_round_transition(
            state,
            {
                "version_id": "v1",
                "edl_changed": True,
                "rendered": True,
                "mp4_exists": True,
            },
            {
                "safety": "PASS",
                "quality": "BETTER",
                "evidence": "SUFFICIENT",
                "issue_effect": "RESOLVED",
                "global_regression": "NO",
                "source_kind": "FIXTURE",
            },
            {"rounds_done": 1, "max_rounds": 3},
        )
        self.assertEqual(tr["next_action"], "CONTINUE_WORKING")
        self.assertFalse(tr["promote"])

    def test_real_better_promotes(self):
        state = init_loop_state()
        tr = evaluate_round_transition(
            state,
            {
                "version_id": "v1",
                "edl_changed": True,
                "rendered": True,
                "mp4_exists": True,
            },
            {
                "safety": "PASS",
                "quality": "BETTER",
                "evidence": "SUFFICIENT",
                "issue_effect": "RESOLVED",
                "global_regression": "NO",
                "source_kind": "REAL_VLM",
                "compared_against_best": True,
            },
            {"rounds_done": 1, "max_rounds": 3},
        )
        self.assertEqual(tr["next_action"], "PROMOTE_BEST")
        self.assertTrue(tr["promote"])

    def test_accept_boolean_ignored(self):
        state = init_loop_state()
        tr = evaluate_round_transition(
            state,
            {
                "version_id": "v1",
                "edl_changed": True,
                "rendered": True,
                "mp4_exists": True,
            },
            {
                "safety": "PASS",
                "quality": "PROMISING",
                "evidence": "PARTIAL",
                "accept_candidate": False,
            },
            {"rounds_done": 1, "max_rounds": 3, "has_executable_revision": True},
        )
        self.assertEqual(tr["next_action"], "CONTINUE_WORKING")
        self.assertTrue(tr["accept_candidate_ignored"])


class TestNormalizeFeedbackBundle(unittest.TestCase):
    def test_synthetic_bundle_uncertain(self):
        bundle = {
            "cases": [
                {
                    "issue_id": "jump_a_b",
                    "revision_intent_id": "search_add_0",
                    "target_action": "search_add",
                    "original_story_problem": {
                        "story_role": "transition",
                        "missing_information": "causal bridge",
                    },
                    "candidate_footage": {
                        "source_pts": {"start": 10.0, "end": 20.0},
                        "apply": {
                            "action": "search_add",
                            "insert_after_segment_id": "seg_a",
                            "status": "applied_evidence_bound",
                        },
                    },
                    "final_decision": "REJECT",
                    "failure_reasons": ["verifier_or_pipeline_rejected"],
                    "verifier_judgment": {"quality_judgment": None},
                }
            ]
        }
        vfix = {
            "candidate_accepted": False,
            "hard_vetoes": [],
            "warnings": ["refuse_accept_without_semantic_verification"],
            "vision_backed": True,
            "sent_frame_ids": ["baseline_opening_0", "candidate_opening_0"],
            "dual_verifier": {"semantic_verification_status": "NOT_EVALUATED"},
            "dual_verifier_full": {"error": "vision_citations_insufficient_or_text_only"},
        }
        entries = normalize_feedback(bundle, vfix, round_idx=1, source_kind="FIXTURE")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["quality"], "UNCERTAIN")
        self.assertNotEqual(entries[0]["failure_class"], "CONFIRMED_NEGATIVE")
        summary = summarize_feedback(entries)
        self.assertEqual(summary["n_records"], 1)


if __name__ == "__main__":
    unittest.main()
