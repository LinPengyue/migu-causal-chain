"""Zero-HTTP tests for feedback-driven one-edit fullcut story revision.

These are mechanism tests; synthetic MP4 digest strings do not imply the model
has established better story quality on any real football match.
"""
from __future__ import annotations

import unittest

from story_video_agent_v3.story_fullcut_learning import (
    extract_fullcut_learning,
    prioritize_confirmed_edits,
)
from story_video_agent_v3.story_revision_planner import plan_from_diagnosis
from story_video_agent_v3.story_loop_policy import init_loop_state, evaluate_round_transition


def _fullcut_screen(status="SCREENED_NO_GAIN"):
    return {
        "schema": "v3a_fullcut_semantic_screen_v1",
        "status": status,
        "baseline_mp4_sha256": "a" * 64,
        "candidate_mp4_sha256": "b" * 64,
        "sampled_frame_sha256": {
            "baseline_pre_edit_0": "c" * 64,
            "candidate_edit_impact_0": "d" * 64,
        },
        "aspect_verdicts": {
            "information_gain": "NO",
            "pacing_tradeoff": "NOT_JUSTIFIED",
        },
        "authorizes_promote_best": False,
        "improvement_verified": False,
    }


def _diagnosis():
    return {
        "issues": [
            {
                "issue_id": "missing_change",
                "category": "transition",
                "severity": "major",
                "story_defect_confirmed": True,
                "diagnosis_status": "CONFIRMED_STORY_DEFECT",
                "missing_information": "Need an understandable pressure change",
                "segment_ids": ["setup", "turn"],
            },
            {
                "issue_id": "duplicate_non_goal",
                "category": "redundancy",
                "severity": "minor",
                "story_defect_confirmed": True,
                "diagnosis_status": "CONFIRMED_STORY_DEFECT",
                "evidence_tier": "DEFECT_CONFIRMED",
                "evidence_frame_refs": ["baseline_frame_a", "baseline_frame_b"],
                "preferred_drop_segment_id": "repeat",
                "segment_ids": ["repeat"],
                "observed_evidence": "The repeated buildup shot adds no new story state",
            },
        ],
        "protected_goal_segment_ids": ["goal"],
    }


def _search():
    row = {
        "candidate_id": "candidate_x",
        "event_id": "event_x",
        "issue_id": "missing_change",
        "role": "buildup_bridge_action",
        "source_pts_start": 35.0,
        "source_pts_end": 40.0,
        "insert_after_segment_id": "setup",
        "before_segment_id": "turn",
        "executable_safe_revision": True,
        "first_live_status": "FIRST_LIVE_VERIFIED",
        "evidence_tier": "FIRST_LIVE_VERIFIED",
        "narrative_fit_supports_insert": True,
        "narrative_fit": {
            "binding_valid": True,
            "status": "REVIEW_SUPPORTED",
        },
        "search_window": {"lo": 20, "hi": 90, "kind": "bridge_between_cuts"},
    }
    return {
        "search_success": True,
        "feedback_filter_applied": True,
        "executable_search_success": True,
        "verified_candidates": [row],
        "executable_first_live_candidates": [row],
        "narrative_fit_supported_candidates": [row],
    }


class TestFullcutLearning(unittest.TestCase):
    def test_no_gain_real_screen_creates_context_bound_conditional_feedback(self):
        diag = _diagnosis()
        plan = {
            "revision_intents": [{
                "intent_id": "insert",
                "issue_id": "missing_change",
                "action": "search_add",
                "insert_after_segment_id": "setup",
                "before_segment_id": "turn",
                "bound_source_window": {"start": 35, "end": 40},
            }]
        }
        out = extract_fullcut_learning(
            screen=_fullcut_screen(),
            revision_plan=plan, diagnosis=diag,
            parent_version_id="v0", candidate_version_id="v1",
            source_sha256="e" * 64, round_idx=1,
        )
        self.assertTrue(out["admissible"])
        self.assertEqual(out["strategy"], "PREFER_CONFIRMED_NON_ADDITIVE")
        self.assertEqual(len(out["entries"]), 1)
        item = out["entries"][0]
        self.assertEqual(item["source_pts"], [35.0, 40.0])
        self.assertEqual(item["issue_signature"]["category"], "transition")
        self.assertEqual(item["issue_signature"]["anchor_segment_ids"], ["setup", "turn"])
        self.assertEqual(item["failure_class"], "UNCERTAIN_OR_UNVERIFIED")
        self.assertFalse(item["pts_permanently_banned"])

    def test_fixture_or_bare_quality_label_cannot_create_learning(self):
        diag = _diagnosis()
        plan = {"revision_intents": [{"action": "search_add", "issue_id": "missing_change"}]}
        for mode, screen in (
            ("FIXTURE", _fullcut_screen()),
            ("REAL_VLM", {"status": "SCREENED_NO_GAIN", "quality": "SAME"}),
            ("OFFLINE_RULE", _fullcut_screen()),
        ):
            with self.subTest(mode=mode):
                out = extract_fullcut_learning(
                    screen=screen, revision_plan=plan, diagnosis=diag,
                    parent_version_id="v0", candidate_version_id="v1",
                    source_sha256="e"*64, round_idx=1, provider_mode=mode,
                )
                self.assertFalse(out["admissible"])
                self.assertEqual(out["entries"], [])

    def test_contextual_failure_does_not_fabricate_drop_from_unknown_issue(self):
        fake = {
            "records": [{
                "issue_id": "other_issue",
                "screen_status": "SCREENED_NO_GAIN",
                "source_kind": "REAL_VLM",
                "alternative_edit_priority": "CONFIRMED_NON_ADDITIVE",
                "issue_signature": {"anchor_segment_ids": ["unrelated"]},
            }]
        }
        out = prioritize_confirmed_edits(
            structure_intents=[],
            insert_intents=[{
                "action": "search_add", "issue_id": "missing_change",
                "insert_after_segment_id": "setup",
            }],
            feedback_context=fake,
        )
        self.assertEqual(out["selected"][0]["action"], "search_add")
        self.assertFalse(out["recent_no_gain"])

    def test_real_failures_prefer_confirmed_nonadditive_before_new_footage(self):
        diag = _diagnosis()
        learn = extract_fullcut_learning(
            screen=_fullcut_screen(),
            revision_plan={"revision_intents": [{
                "intent_id": "old_add",
                "issue_id": "missing_change",
                "action": "search_add",
                "insert_after_segment_id": "setup",
                "before_segment_id": "turn",
                "bound_source_window": {"start": 35, "end": 40},
            }]},
            diagnosis=diag, parent_version_id="v0",
            candidate_version_id="v1", source_sha256="e"*64,
            round_idx=1,
        )
        plan = plan_from_diagnosis(
            diag, search_results=_search(),
            feedback_context={"records": learn["entries"],
                              "feedback_filter_applied": True},
            use_fullcut_learning=True,
            require_narrative_fit=True,
        )
        self.assertEqual(plan["decision"], "REVISE")
        self.assertEqual(len([i for i in plan["revision_intents"] if
                              i["action"] in ("drop", "search_add")]), 1)
        self.assertEqual(plan["revision_intents"][0]["action"], "drop")
        self.assertEqual(plan["revision_intents"][0]["target_segment_id"], "repeat")
        self.assertTrue(plan["fullcut_edit_selection"]["recent_no_gain"])
        self.assertEqual(
            plan["fullcut_edit_selection"]["deferred"][0]["action"], "search_add",
        )

    def test_failed_structural_edit_not_repeated_when_another_target_exists(self):
        history = [{
            "source_kind": "REAL_VLM",
            "screen_status": "SCREENED_NO_GAIN",
            "alternative_edit_priority": "CONFIRMED_NON_ADDITIVE",
            "action": "drop",
            "issue_id": "duplicate_non_goal",
            "target_segment_id": "repeat",
            "issue_signature": {"anchor_segment_ids": ["repeat"]},
        }]
        ranked = prioritize_confirmed_edits(
            structure_intents=[
                {"action": "drop", "issue_id": "duplicate_non_goal",
                 "target_segment_id": "repeat"},
                {"action": "drop", "issue_id": "duplicate_non_goal",
                 "target_segment_id": "different_redundant_cut"},
            ],
            insert_intents=[],
            feedback_context={"records": history},
        )
        self.assertEqual(len(ranked["selected"]), 1)
        self.assertEqual(
            ranked["selected"][0]["target_segment_id"], "different_redundant_cut"
        )
        self.assertEqual(len(ranked["skipped_repeated_structural"]), 1)

    def test_screened_same_can_replan_when_distinct_confirmed_edit_waits(self):
        transition = evaluate_round_transition(
            init_loop_state(version_id="v0"),
            {
                "version_id": "v1", "parent_version_id": "v0",
                "edl_changed": True, "rendered": True,
            },
            {
                "safety": "PASS", "quality": "SAME", "evidence": "PARTIAL",
                "source_kind": "REAL_VLM", "hard_vetoes": [],
            },
            budget={
                "rounds_done": 1, "max_rounds": 3,
                "has_distinct_alternative": True,
            },
        )
        self.assertEqual(transition["next_action"], "REPLAN_FROM_BEST")
        self.assertFalse(transition["promote"])
        self.assertEqual(transition["best_ref"], "v0")

    def test_no_confirmed_structure_never_invents_drop(self):
        diag = _diagnosis()
        diag["issues"] = diag["issues"][:1]
        plan = plan_from_diagnosis(
            diag, search_results=_search(),
            use_fullcut_learning=True, require_narrative_fit=True,
        )
        self.assertEqual(plan["decision"], "REVISE")
        self.assertEqual(plan["revision_intents"][0]["action"], "search_add")

    def test_minor_redundancy_without_frame_evidence_is_not_auto_dropped(self):
        diag = _diagnosis()
        diag["issues"] = [dict(diag["issues"][1])]
        diag["issues"][0].pop("evidence_frame_refs")
        result = plan_from_diagnosis(
            diag, use_fullcut_learning=True, require_narrative_fit=True,
        )
        self.assertEqual(result["decision"], "KEEP")
        self.assertFalse(any(
            it.get("action") == "drop" for it in result["revision_intents"]
        ))

    def test_goal_protection_blocks_even_confirmed_redundancy(self):
        diag = _diagnosis()
        diag["issues"] = [dict(diag["issues"][1])]
        diag["issues"][0]["preferred_drop_segment_id"] = "goal"
        result = plan_from_diagnosis(
            diag, use_fullcut_learning=True, require_narrative_fit=True,
        )
        self.assertNotEqual(result["decision"], "REVISE")
        self.assertFalse(any(
            it.get("action") == "drop" for it in result["revision_intents"]
        ))


if __name__ == "__main__":
    unittest.main()
