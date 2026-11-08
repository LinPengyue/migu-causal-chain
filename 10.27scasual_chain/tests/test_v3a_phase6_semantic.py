"""Phase 6: semantic critic/planner + truncated verifier recovery (zero paid HTTP)."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from story_video_agent_v3.global_story_critic import (
    merge_observation_into_diagnosis,
    structural_diagnosis,
)
from story_video_agent_v3.revision_case import build_revision_case, build_revision_cases_for_round
from story_video_agent_v3.semantic_story_diagnosis import apply_semantic_diagnosis_layer
from story_video_agent_v3.story_edl_safety import (
    check_source_pts_monotonic,
    classify_revision_status,
)
from story_video_agent_v3.story_e2e_agent import UNIFIED_CHAIN_ID, run_story_e2e, StoryE2EInputs
from story_video_agent_v3.story_revision_planner import plan_from_diagnosis
from story_video_agent_v3.truncated_response_recovery import recover_per_revision_judgments


PHASE5_AUDIT = Path(
    "/data2/lpy1/_story_va_outputs/v3/plan2/story_semantic_eval_phase5_20261108/api_audit"
)


class TestTruncatedRecoveryPhase5Fixtures(unittest.TestCase):
    def _load(self, name: str) -> dict:
        p = PHASE5_AUDIT / name
        if not p.is_file():
            self.skipTest(f"missing Phase5 fixture {p}")
        return json.loads(p.read_text(encoding="utf-8"))

    def test_recover_b_complete_judgments_with_checkable_tokens(self):
        raw = self._load("B_raw_response_full.json")
        rec = recover_per_revision_judgments(
            raw["raw_text"],
            sent_frame_ids=raw["sent_frame_ids"],
            finish_reason=raw.get("finish_reason"),
            parse_error=raw.get("full_json_parse_error"),
        )
        self.assertIn("OUTPUT_TRUNCATED", rec["status_tags"])
        self.assertIn("PARSE_FAILED", rec["status_tags"])
        self.assertGreaterEqual(rec["n_valid_recovered"], 1)
        for item in rec["recovered"]:
            self.assertEqual(item["recovery_status"], "RECOVERED_PARTIAL_RESPONSE")
            self.assertIn(item["quality_judgment"], ("BETTER", "SAME", "WORSE", "UNRESOLVED"))
            self.assertTrue(item["evidence_check"]["ok"])
            self.assertTrue(item["source"]["no_fields_invented"])
            # Integrity statuses ≠ model UNRESOLVED unless label says so
            if item["quality_judgment"] != "UNRESOLVED":
                self.assertFalse(item["status_distinction"]["model_UNRESOLVED"])

    def test_a_first_call_evidence_uncheckable_not_model_unresolved(self):
        raw = self._load("A_raw_response_full.json")
        rec = recover_per_revision_judgments(
            raw["raw_text"],
            sent_frame_ids=raw["sent_frame_ids"],
            finish_reason=raw.get("finish_reason"),
        )
        self.assertIn("OUTPUT_TRUNCATED", rec["status_tags"])
        # First A call objects exist but typically fail evidence checkability
        if rec["n_rejected"]:
            for r in rec["rejected"]:
                self.assertFalse(r["status_distinction"]["model_UNRESOLVED"])
                if "EVIDENCE_UNCHECKABLE" in (r.get("issues") or []):
                    self.assertTrue(r["status_distinction"]["EVIDENCE_UNCHECKABLE"])

    def test_a_short_retry_recovers_one_with_structured_refs(self):
        raw = self._load("A_short_retry_raw.json")
        rec = recover_per_revision_judgments(
            raw["raw_text"],
            sent_frame_ids=raw["sent_frame_ids"],
            finish_reason=raw.get("finish_reason"),
            parse_error=raw.get("full_json_parse_error"),
        )
        self.assertGreaterEqual(rec["n_valid_recovered"], 1)
        j = rec["recovered"][0]
        self.assertEqual(j["intent_id"], "search_add_0_cand_event_000417_3504")
        self.assertTrue(j["evidence_check"]["has_baseline_citation"])
        self.assertTrue(j["evidence_check"]["has_candidate_citation"])


class TestSemanticCriticLayer(unittest.TestCase):
    def test_structure_gap_is_hypothesis_without_video(self):
        edl = [
            {
                "segment_id": "a",
                "role": "deficit_scoreboard_anchor",
                "include_in_cut": True,
                "media_in": 100.0,
                "media_out": 105.0,
            },
            {
                "segment_id": "b",
                "role": "equalizer_goal_action",
                "include_in_cut": True,
                "media_in": 2000.0,
                "media_out": 2020.0,
            },
        ]
        diag = structural_diagnosis(edl=edl, story_plan={"roles": []}, initial_story_mp4=None)
        # Force missing-mp4 aside: enrich via merge with offline observe
        obs = {"fixture_or_offline": True, "semantic_provider_used": False, "derived_issues": []}
        # Drop input integrity for focused check by applying layer on filtered issues
        jump_issues = [
            i
            for i in (diag.get("issues") or [])
            if str(i.get("issue_id") or "").startswith("large_source_jump")
        ]
        self.assertTrue(jump_issues)
        layered = apply_semantic_diagnosis_layer(
            {**diag, "issues": jump_issues}, observations=obs
        )
        for iss in layered["issues"]:
            self.assertEqual(iss["diagnosis_status"], "HYPOTHESIS_NEEDS_VIDEO")
            self.assertFalse(iss["story_defect_confirmed"])
            for k in (
                "issue_id",
                "story_role",
                "observed_evidence",
                "missing_information",
                "causal_explanation",
                "confidence",
                "evidence_sufficiency",
            ):
                self.assertIn(k, iss)

    def test_video_derived_issue_can_confirm(self):
        base = {
            "issues": [
                {
                    "issue_id": "large_source_jump_a_b",
                    "category": "transition",
                    "evidence_sufficiency": "needs_video_verify",
                    "observation": "gap",
                    "narrative_problem": "jump",
                }
            ]
        }
        obs = {
            "semantic_provider_used": True,
            "fixture_or_offline": False,
            "derived_issues": [
                {
                    "issue_id": "large_source_jump_a_b",
                    "evidence_sufficiency": "observed",
                    "observation": "crowd then unrelated midfield",
                    "narrative_problem": "causal break",
                    "confidence": 0.9,
                }
            ],
        }
        out = apply_semantic_diagnosis_layer(base, observations=obs)
        self.assertTrue(out["issues"][0]["story_defect_confirmed"])
        self.assertEqual(out["issues"][0]["diagnosis_status"], "CONFIRMED_STORY_DEFECT")


class TestProblemDrivenPlanner(unittest.TestCase):
    def test_planner_does_not_auto_add_on_gap_hypothesis(self):
        diag = {
            "issues": [
                {
                    "issue_id": "large_source_jump_x",
                    "category": "transition",
                    "severity": "minor",
                    "evidence_sufficiency": "needs_video_verify",
                    "diagnosis_status": "HYPOTHESIS_NEEDS_VIDEO",
                    "story_defect_confirmed": False,
                    "observation": "PTS gap",
                    "narrative_problem": "maybe abrupt",
                }
            ],
            "protected_goal_segment_ids": ["g"],
        }
        search = {
            "search_success": True,
            "verified_candidates": [
                {
                    "candidate_id": "c1",
                    "issue_id": "large_source_jump_x",
                    "role": "buildup_bridge_action",
                    "source_pts_start": 1.0,
                    "source_pts_end": 2.0,
                    "insert_after_segment_id": "a",
                    "event_id": "e",
                    "live": {"broadcast_phase": "LIVE"},
                    "confidence": 0.5,
                    "risks": [],
                }
            ],
        }
        plan = plan_from_diagnosis(diag, offline=True, search_results=search)
        self.assertEqual(plan["decision"], "UNRESOLVED")
        self.assertNotIn("search_add", {i["action"] for i in plan["revision_intents"]})
        self.assertTrue(plan["phase6_rules"]["no_auto_add_on_large_source_gap_alone"])

    def test_planner_keep_trim_replace_search_add_when_confirmed(self):
        # keep path
        keep = plan_from_diagnosis({"issues": [], "protected_goal_segment_ids": []}, offline=True)
        self.assertEqual(keep["decision"], "KEEP")
        # replace via fixture
        fix = plan_from_diagnosis(
            {
                "issues": [
                    {
                        "issue_id": "bad_seg",
                        "story_defect_confirmed": True,
                        "diagnosis_status": "CONFIRMED_STORY_DEFECT",
                        "evidence_sufficiency": "observed",
                        "observation": "wrong shot",
                        "narrative_problem": "misleads",
                    }
                ],
                "protected_goal_segment_ids": [],
            },
            offline=True,
            fixture_intents=[
                {
                    "intent_id": "r1",
                    "action": "replace",
                    "issue_id": "bad_seg",
                    "target_segment_id": "seg_x",
                    "bound_source_window": {"start": 10.0, "end": 12.0},
                    "rationale": "better live window",
                    "expected_improvement": "fix meaning",
                    "falsification_evidence": "still wrong content",
                }
            ],
        )
        self.assertEqual(fix["decision"], "REVISE")
        self.assertEqual(fix["revision_intents"][0]["action"], "replace")
        self.assertIn("answers", fix["revision_intents"][0])
        # trim fixture
        trim = plan_from_diagnosis(
            {"issues": [], "protected_goal_segment_ids": []},
            offline=True,
            fixture_intents=[
                {
                    "intent_id": "t1",
                    "action": "trim",
                    "issue_id": "redundant",
                    "target_segment_id": "seg_y",
                    "rationale": "no new info",
                }
            ],
        )
        self.assertEqual(trim["decision"], "REVISE")
        # unresolved alias
        unr = plan_from_diagnosis(
            {"issues": [], "protected_goal_segment_ids": []},
            offline=True,
            fixture_intents=[{"intent_id": "u1", "action": "unresolved", "issue_id": "x"}],
        )
        self.assertEqual(unr["decision"], "UNRESOLVED")

    def test_intent_bound_to_issue(self):
        plan = plan_from_diagnosis(
            {
                "issues": [
                    {
                        "issue_id": "iss1",
                        "story_defect_confirmed": True,
                        "diagnosis_status": "CONFIRMED_STORY_DEFECT",
                        "evidence_sufficiency": "observed",
                        "observed_evidence": "missing setup",
                        "causal_explanation": "cannot understand goal",
                        "missing_information": "pressure build",
                    }
                ],
                "protected_goal_segment_ids": [],
            },
            offline=True,
            search_results={
                "search_success": True,
                "verified_candidates": [
                    {
                        "candidate_id": "c",
                        "issue_id": "iss1",
                        "role": "buildup_bridge_action",
                        "source_pts_start": 1.0,
                        "source_pts_end": 2.0,
                        "insert_after_segment_id": "s",
                        "event_id": "e",
                        "live": {"broadcast_phase": "LIVE"},
                        "confidence": 0.7,
                        "risks": [],
                    }
                ],
            },
        )
        it = plan["revision_intents"][0]
        self.assertEqual(it["issue_id"], "iss1")
        self.assertEqual(it["action"], "search_add")
        self.assertTrue(it.get("duration_pad_not_quality_proxy"))


class TestRevisionCaseAndGates(unittest.TestCase):
    def test_better_not_auto_accept_or_improved(self):
        case = build_revision_case(
            issue={"issue_id": "i", "story_defect_confirmed": True},
            intent={"intent_id": "r", "action": "search_add", "issue_id": "i"},
            verifier_judgment={
                "quality_judgment": "BETTER",
                "original_issue_resolved": True,
                "introduced_new_defect": False,
            },
            pts_safety={"ok": False, "breaks": [{"x": 1}]},
            candidate_accepted=False,
        )
        self.assertEqual(case["final_decision"], "REJECT")
        self.assertIn("pts_or_safety_gate", case["failure_reasons"])
        self.assertIn("BETTER_not_auto_ACCEPT", case["failure_reasons"])

        st = classify_revision_status(
            edl_changed=True,
            applied_bound=True,
            candidate_rendered=True,
            candidate_accepted=False,
            vision_backed=True,
            semantic_passed=False,
            quality_delta="better",
            safety_ok=False,
        )
        self.assertFalse(st["IMPROVED"])
        self.assertTrue(st["BETTER_not_auto_IMPROVED"])

    def test_illegal_pts_rejected(self):
        edl = [
            {"segment_id": "a", "include_in_cut": True, "media_in": 100.0, "media_out": 110.0},
            {"segment_id": "b", "include_in_cut": True, "media_in": 90.0, "media_out": 95.0},
        ]
        self.assertFalse(check_source_pts_monotonic(edl)["ok"])

    def test_case_bundle_binds_issue_to_intent(self):
        bundle = build_revision_cases_for_round(
            diagnosis={
                "issues": [
                    {
                        "issue_id": "iss",
                        "observed_evidence": "gap",
                        "causal_explanation": "break",
                        "diagnosis_status": "CONFIRMED_STORY_DEFECT",
                        "story_defect_confirmed": True,
                    }
                ]
            },
            revision_plan={
                "revision_intents": [
                    {
                        "intent_id": "add1",
                        "action": "search_add",
                        "issue_id": "iss",
                        "expected_improvement": "clearer transition",
                    }
                ]
            },
            pts_safety={"ok": True},
            candidate_accepted=False,
        )
        self.assertEqual(bundle["n_cases"], 1)
        self.assertEqual(bundle["cases"][0]["bindings"]["issue_id"], "iss")
        self.assertEqual(bundle["cases"][0]["final_decision"], "REJECT")


class TestMainChainPhase6Wiring(unittest.TestCase):
    def test_unified_chain_metadata_lists_phase6_modules(self):
        # Import-time constant check + lightweight audit shape via dry path if assets exist
        self.assertEqual(UNIFIED_CHAIN_ID, "v3a_unified_story_self_revise_main_v1")
        # Ensure merge path applies semantic layer (no paid)
        diag = {
            "inputs": {"initial_story_mp4": "/tmp/x.mp4"},
            "timeline": {"segments": []},
            "issues": [
                {
                    "issue_id": "large_source_jump_a_b",
                    "category": "transition",
                    "evidence_sufficiency": "needs_video_verify",
                    "observation": "gap",
                    "narrative_problem": "maybe",
                }
            ],
        }
        merged = merge_observation_into_diagnosis(
            diag, {"fixture_or_offline": True, "semantic_provider_used": False}
        )
        self.assertIn("semantic_diagnosis_layer", merged)
        self.assertEqual(merged["issues"][0]["diagnosis_status"], "HYPOTHESIS_NEEDS_VIDEO")


if __name__ == "__main__":
    unittest.main()
