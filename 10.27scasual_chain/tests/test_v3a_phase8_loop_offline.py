"""Phase 8 offline loop control-flow tests (zero HTTP).

structural_loop_pass may be true here; video_semantic_quality_verified /
unseen_match_generalization_verified / release_authorized remain false for fixtures.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent_v3.story_loop_policy import (
    apply_transition,
    evaluate_round_transition,
    init_loop_state,
    write_loop_state,
)
from story_video_agent_v3.story_revision_feedback import (
    RevisionFeedbackStore,
    load_phase7_round_into_feedback,
    normalize_feedback,
    should_penalize_candidate,
    summarize_feedback,
)
from story_video_agent_v3.story_evidence_search import _apply_feedback_to_candidates
from story_video_agent_v3.story_revision_planner import plan_from_diagnosis
from story_video_agent_v3.story_video_verifier import build_phase8_verdict

PHASE7_ROUND = Path(
    "/data2/lpy1/_story_va_outputs/v3/plan2/story_quality_phase7_20261108/"
    "A_bridge_e2e/02_round_01"
)
OUT_ROOT = Path("/data2/lpy1/_story_va_outputs/v3/plan2")


class TestPhase8ThreeRoundOfflineLoop(unittest.TestCase):
    def test_promising_then_alternate_then_stop(self):
        """r1 PROMISING -> working v1; r2 different PTS after feedback; r3 stop."""
        state = init_loop_state(edl_path="e0.json", mp4_path="m0.mp4")
        store = RevisionFeedbackStore()
        decisions = []

        # Round 1: safety PASS + PROMISING
        tr1 = evaluate_round_transition(
            state,
            {"version_id": "v1", "parent_version_id": "v0", "edl_changed": True, "rendered": True},
            {
                "safety": "PASS",
                "quality": "PROMISING",
                "evidence": "PARTIAL",
                "source_kind": "FIXTURE",
                "issue_effect": "PARTIAL",
                "global_regression": "NO",
            },
            {"rounds_done": 1, "max_rounds": 3, "has_executable_revision": True},
        )
        self.assertEqual(tr1["next_action"], "CONTINUE_WORKING")
        state = apply_transition(
            state,
            tr1,
            candidate_version={
                "parent_version_id": "v0",
                "edl_path": "e1.json",
                "mp4_path": "m1.mp4",
                "safety": "PASS",
                "quality": "PROMISING",
                "source": "FIXTURE",
            },
        )
        store.extend(
            [
                {
                    "schema": "v3a_phase8_feedback_v1",
                    "round": 1,
                    "action": "search_add",
                    "source_pts": [3504.14, 3515.83],
                    "quality": "PROMISING",
                    "evidence_status": "PARTIAL",
                    "failure_class": "POSITIVE",
                    "issue_signature": {
                        "category": "transition",
                        "anchor_segment_ids": ["seg_setup", "seg_turn"],
                        "missing_narrative_info": "causal bridge",
                    },
                    "next_search_requirement": "alternate narrative function",
                    "new_evidence_required_for_retry": True,
                    "source_kind": "FIXTURE",
                }
            ]
        )
        decisions.append(
            {
                "round": 1,
                "parent": "v0",
                "candidate": "v1",
                "transition": tr1["next_action"],
                "action": "search_add",
                "source_pts": [3504.14, 3515.83],
                "working": state["working_version_id"],
                "best": state["best_verified_version_id"],
            }
        )
        self.assertEqual(state["working_version_id"], "v1")
        self.assertEqual(state["best_verified_version_id"], "v0")

        # Round 2: same PTS suppressed; alternate PTS chosen
        cands = [
            {
                "candidate_id": "cand_old",
                "category": "transition",
                "source_pts_start": 3504.14,
                "source_pts_end": 3515.83,
                "insert_after_segment_id": "seg_setup",
                "score": 0.95,
            },
            {
                "candidate_id": "cand_new",
                "category": "transition",
                "source_pts_start": 4200.0,
                "source_pts_end": 4210.0,
                "insert_after_segment_id": "seg_setup",
                "score": 0.70,
            },
        ]
        filtered = _apply_feedback_to_candidates(cands, store.to_dict())
        kept_ids = [c["candidate_id"] for c in filtered["verified_candidates"]]
        self.assertNotIn("cand_old", kept_ids)
        self.assertIn("cand_new", kept_ids)

        tr2 = evaluate_round_transition(
            state,
            {"version_id": "v2", "parent_version_id": "v1", "edl_changed": True, "rendered": True},
            {
                "safety": "PASS",
                "quality": "UNCERTAIN",
                "evidence": "INSUFFICIENT",
                "source_kind": "FIXTURE",
            },
            {
                "rounds_done": 2,
                "max_rounds": 3,
                "has_executable_revision": True,
                "has_distinct_alternative": False,
                "has_new_visual_target": False,
            },
        )
        self.assertEqual(tr2["next_action"], "STOP_NO_ACTION")
        state = apply_transition(state, tr2)
        decisions.append(
            {
                "round": 2,
                "parent": "v1",
                "candidate": "v2",
                "transition": tr2["next_action"],
                "action": "search_add",
                "source_pts": [4200.0, 4210.0],
                "working": state["working_version_id"],
                "best": state["best_verified_version_id"],
                "filtered_out": "cand_old",
                "kept": "cand_new",
            }
        )

        # Round 3: budget stop preserves best=v0
        tr3 = evaluate_round_transition(
            state,
            {"version_id": "v3", "edl_changed": False, "rendered": False},
            {"safety": "PASS", "quality": "SAME", "evidence": "PARTIAL", "source_kind": "FIXTURE"},
            {"rounds_done": 3, "max_rounds": 3},
        )
        self.assertEqual(tr3["next_action"], "STOP_BUDGET")
        state = apply_transition(state, tr3)
        decisions.append(
            {
                "round": 3,
                "transition": tr3["next_action"],
                "working": state["working_version_id"],
                "best": state["best_verified_version_id"],
                "stop_reason": state.get("stop_reason"),
            }
        )
        self.assertEqual(state["best_verified_version_id"], "v0")
        self.assertEqual(state.get("delivery_version_id") or state["best_verified_version_id"], "v0")

        out = OUT_ROOT / "story_quality_phase8_20261108_offline_loop"
        out.mkdir(parents=True, exist_ok=True)
        write_loop_state(state, out / "phase8_loop_state.json")
        store.write_json(out / "phase8_feedback_memory.json")
        audit = {
            "schema": "v3a_phase8_offline_loop_audit_v1",
            "structural_loop_pass": True,
            "video_semantic_quality_verified": False,
            "unseen_match_generalization_verified": False,
            "release_authorized": False,
            "zero_http": True,
            "rounds": decisions,
            "proof": {
                "r1_promising_sets_working_not_best": True,
                "r2_feedback_changes_candidate_pts": True,
                "r3_budget_stop_preserves_best": True,
                "two_distinct_source_candidates": ["cand_old@3504-3515", "cand_new@4200-4210"],
            },
            "note": (
                "Fixture control-flow proof only. Not a claim of better real story video."
            ),
        }
        (out / "phase8_offline_loop_audit.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        self.assertTrue((out / "phase8_offline_loop_audit.json").is_file())


class TestPhase7RejectFeedsMemoryNotNegative(unittest.TestCase):
    @unittest.skipUnless(PHASE7_ROUND.is_dir(), "Phase7 artifact missing")
    def test_phase7_into_planner_changes_strategy(self):
        store = load_phase7_round_into_feedback(PHASE7_ROUND)
        self.assertTrue(store.records)
        self.assertNotEqual(store.records[0]["failure_class"], "CONFIRMED_NEGATIVE")
        fb = store.to_dict()
        # Same PTS should be suppressed for retry without new evidence
        hit = should_penalize_candidate(
            store.records,
            issue_signature=store.records[0]["issue_signature"],
            action=store.records[0].get("action") or "search_add",
            source_pts=store.records[0]["source_pts"],
        )
        self.assertTrue(hit["suppress"])
        plan = plan_from_diagnosis(
            {
                "issues": [
                    {
                        "issue_id": "hyp_transition",
                        "category": "transition",
                        "severity": "major",
                        "diagnosis_status": "HYPOTHESIS_NEEDS_VIDEO",
                        "evidence_sufficiency": "needs_video_verify",
                    }
                ],
                "protected_goal_segment_ids": [],
            },
            search_results={
                "search_success": False,
                "verified_candidates": [],
                "feedback_filtered_candidates": [{"candidate_id": "x"}],
                "feedback_filter_applied": True,
            },
            feedback_context=fb,
            offline=True,
        )
        self.assertEqual(plan["decision"], "UNRESOLVED")
        self.assertTrue(plan["phase8_rules"]["use_prior_round_feedback"])


class TestPhase8VerdictDoesNotSynthesizeAccept(unittest.TestCase):
    def test_promising_verdict_with_accept_false(self):
        v = build_phase8_verdict(
            hard_vetoes=[],
            goal_intact=True,
            render_rows_ok=True,
            semantic_status="NOT_EVALUATED",
            vision_backed=True,
            sent_frame_ids=["baseline_a", "candidate_a"],
            validated={},
            fixture={
                "phase8_quality": "PROMISING",
                "phase8_safety": "PASS",
                "phase8_evidence": "PARTIAL",
                "source_kind": "FIXTURE",
            },
            accept_candidate=False,
        )
        self.assertEqual(v["quality"], "PROMISING")
        self.assertFalse(v["accept_candidate_raw"])
        self.assertTrue(v["accept_not_synthesized_from_promising"])


class TestWorseRollback(unittest.TestCase):
    def test_worse_does_not_become_working_baseline(self):
        state = init_loop_state()
        tr = evaluate_round_transition(
            state,
            {"version_id": "v1", "edl_changed": True, "rendered": True},
            {
                "safety": "PASS",
                "quality": "WORSE",
                "evidence": "SUFFICIENT",
                "source_kind": "FIXTURE",
            },
            {"rounds_done": 1, "max_rounds": 3, "has_distinct_alternative": True},
        )
        self.assertEqual(tr["next_action"], "REPLAN_FROM_BEST")
        self.assertEqual(tr["working_ref"], "v0")
        self.assertTrue(tr["record_confirmed_negative"])
        state2 = apply_transition(state, tr)
        self.assertEqual(state2["working_version_id"], "v0")
        self.assertEqual(state2["best_verified_version_id"], "v0")


if __name__ == "__main__":
    unittest.main()
