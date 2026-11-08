"""Phase 7: VLM → structured semantic evidence → CONFIRMED_STORY_DEFECT gate."""
from __future__ import annotations

import inspect
import unittest

from story_video_agent_v3.dual_video_vision_verifier import (
    build_verifier_focus_from_revision_cases,
)
from story_video_agent_v3.semantic_story_diagnosis import apply_semantic_diagnosis_layer
from story_video_agent_v3.story_e2e_agent import run_story_e2e
from story_video_agent_v3.story_paid_eval import run_vlm_story_critic
from story_video_agent_v3.vlm_semantic_evidence import (
    normalize_semantic_evidence_item,
    vlm_critic_to_observation_updates,
)


class TestSemanticEvidenceTiers(unittest.TestCase):
    def test_two_frame_ids_alone_are_frame_cited_not_defect_confirmed(self):
        item = normalize_semantic_evidence_item(
            {
                "issue_id": "large_source_jump_a_b",
                "observed_fact": "abrupt cut between adjacent beats",
                "defect_hypothesis": "bridge broken",
                "claims_story_defect": True,
                "confidence": 0.99,
                "evidence_refs": [{"frame_id": "f0"}, {"frame_id": "f2"}],
            },
            sent_frame_ids=["f0", "f1", "f2"],
        )
        self.assertEqual(item["citation_status"], "FRAME_CITED")
        # Bare ids without substantive notes / grounded mentions → not confirmed.
        self.assertEqual(item["claim_status"], "SEMANTIC_HYPOTHESIS")
        self.assertFalse(item["supports_original_issue"])

    def test_frame_cited_without_defect_claim(self):
        item = normalize_semantic_evidence_item(
            {
                "issue_id": "ending_tail_x",
                "observed_fact": "f0 and f1 both show midfield",
                "evidence_refs": [
                    {"frame_id": "f0", "note": "midfield left"},
                    {"frame_id": "f1", "note": "midfield right"},
                ],
            },
            sent_frame_ids=["f0", "f1", "f2"],
        )
        self.assertEqual(item["citation_status"], "FRAME_CITED")
        self.assertIn(item["claim_status"], ("FRAME_CITED", "SEMANTIC_HYPOTHESIS"))
        self.assertFalse(item["supports_original_issue"])

    def test_defect_confirmed_needs_substantive_cites(self):
        item = normalize_semantic_evidence_item(
            {
                "issue_id": "large_source_jump_a_b",
                "observed_fact": (
                    "Clock jumps from 12:45 setup to 46:53 buildup across adjacent "
                    "story frames with no linking live action."
                ),
                "defect_hypothesis": "causal bridge missing",
                "claims_story_defect": True,
                "confidence": 0.4,
                "evidence_refs": [
                    {"frame_id": "f0", "note": "Clock 12:45 setup board"},
                    {"frame_id": "f2", "note": "Clock 46:53 buildup phase"},
                ],
            },
            sent_frame_ids=["f0", "f1", "f2"],
        )
        self.assertEqual(item["claim_status"], "DEFECT_CONFIRMED")
        self.assertTrue(item["supports_original_issue"])
        self.assertEqual(item["legacy_claim_alias"], "EVIDENCE_SUPPORTED")

    def test_invented_frame_ids_block_support(self):
        item = normalize_semantic_evidence_item(
            {
                "issue_id": "large_source_jump_a_b",
                "observed_fact": "x " * 20,
                "defect_hypothesis": "y",
                "claims_story_defect": True,
                "evidence_refs": [
                    {"frame_id": "ghost1", "note": "a"},
                    {"frame_id": "ghost2", "note": "b"},
                ],
            },
            sent_frame_ids=["f0", "f1"],
        )
        self.assertNotEqual(item["claim_status"], "DEFECT_CONFIRMED")
        self.assertFalse(item["supports_original_issue"])

    def test_or_true_removed_hyp_filter_respected(self):
        updates = vlm_critic_to_observation_updates(
            {
                "parsed": {
                    "semantic_evidence": [
                        {
                            "issue_id": "other_match_ending_gap",
                            "observed_fact": (
                                "Tail ends on crowd shot without scoreboard resolve "
                                "after climax celebration."
                            ),
                            "defect_hypothesis": "ending incomplete",
                            "claims_story_defect": True,
                            "evidence_refs": [
                                {"frame_id": "e0", "note": "crowd only"},
                                {"frame_id": "e1", "note": "no scoreboard"},
                            ],
                        }
                    ]
                },
                "observation_method": "ordered_multi_frame_vlm",
                "claims_full_video_watch": False,
            },
            sent_frame_ids=["e0", "e1"],
            hypothesis_issues=[{"issue_id": "large_source_jump_a_b"}],
        )
        # Defect may be DEFECT_CONFIRMED internally but must NOT enter confirmed_issue_ids
        # when it does not address the supplied hypothesis set.
        self.assertNotIn("other_match_ending_gap", updates["confirmed_issue_ids"])
        self.assertEqual(updates["stats"]["n_defect_confirmed"], 1)

    def test_vlm_updates_confirm_matching_hypothesis(self):
        updates = vlm_critic_to_observation_updates(
            {
                "parsed": {
                    "semantic_evidence": [
                        {
                            "issue_id": "large_source_jump_a_b",
                            "observed_fact": (
                                "scoreboard then unrelated wing play with no bridge action"
                            ),
                            "defect_hypothesis": "no live bridge action",
                            "claims_story_defect": True,
                            "confidence": 0.7,
                            "evidence_refs": [
                                {"frame_id": "story_j_t1p00", "note": "scoreboard 0-1"},
                                {"frame_id": "story_j_t3p00", "note": "wing play only"},
                            ],
                        }
                    ]
                },
                "observation_method": "dense_ordered_multi_frame_vlm",
                "claims_full_video_watch": False,
            },
            sent_frame_ids=["story_j_t1p00", "story_j_t2p00", "story_j_t3p00"],
            hypothesis_issues=[{"issue_id": "large_source_jump_a_b"}],
        )
        self.assertEqual(updates["stats"]["n_defect_confirmed"], 1)
        self.assertIn("large_source_jump_a_b", updates["confirmed_issue_ids"])
        self.assertEqual(
            updates["derived_issues"][0]["claim_status"], "DEFECT_CONFIRMED"
        )

    def test_diagnosis_requires_defect_confirmed_not_frame_cited(self):
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
        out_cited = apply_semantic_diagnosis_layer(
            base,
            observations={
                "semantic_provider_used": True,
                "fixture_or_offline": False,
                "semantic_evidence": [
                    {
                        "issue_id": "large_source_jump_a_b",
                        "claim_status": "FRAME_CITED",
                        "evidence_tier": "FRAME_CITED",
                        "supports_original_issue": False,
                        "observed_fact": "two frames cited",
                        "defect_hypothesis": "maybe jump",
                        "frame_refs": ["a", "b"],
                        "citation_status": "FRAME_CITED",
                    }
                ],
                "derived_issues": [],
            },
        )
        self.assertEqual(
            out_cited["issues"][0]["diagnosis_status"], "HYPOTHESIS_NEEDS_VIDEO"
        )

        out = apply_semantic_diagnosis_layer(
            base,
            observations={
                "semantic_provider_used": True,
                "fixture_or_offline": False,
                "semantic_evidence": [
                    {
                        "issue_id": "large_source_jump_a_b",
                        "claim_status": "DEFECT_CONFIRMED",
                        "evidence_tier": "DEFECT_CONFIRMED",
                        "supports_original_issue": True,
                        "observed_fact": "cut with no linking action",
                        "defect_hypothesis": "bridge missing",
                        "frame_refs": ["a", "b"],
                    }
                ],
                "derived_issues": [],
                "confirmed_issue_ids": ["large_source_jump_a_b"],
            },
        )
        self.assertEqual(out["issues"][0]["diagnosis_status"], "CONFIRMED_STORY_DEFECT")


class TestVerifierFocusMatchAgnostic(unittest.TestCase):
    def test_focus_built_from_revision_case_not_a_hardcode(self):
        focus = build_verifier_focus_from_revision_cases(
            [
                {
                    "issue_id": "ending_incomplete_b_match",
                    "revision_intent_id": "trim_0",
                    "target_action": "trim",
                    "original_story_problem": {
                        "observation": "celebration then black",
                        "missing_information": "scoreboard resolve",
                    },
                    "expected_improvement": "scoreboard visible before end card",
                    "falsification_evidence": "still ends on black",
                    "candidate_footage": {
                        "source_pts": {"start": 10.0, "end": 12.0},
                        "apply": {
                            "segment_id": "seg_end_trim",
                            "insert_after_segment_id": None,
                        },
                    },
                }
            ]
        )
        blob = "\n".join(focus["focus_lines"])
        self.assertIn("ending_incomplete_b_match", blob)
        self.assertIn("scoreboard visible before end card", blob)
        self.assertIn("celebration then black", blob)
        # Must not inject A-match critical-bridge boilerplate.
        self.assertNotIn("critical buildup bridge between deficit setup", blob)
        self.assertNotIn("阿联酋", blob)
        self.assertNotIn("阿曼", blob)

    def test_empty_cases_generic_no_match_assumption(self):
        focus = build_verifier_focus_from_revision_cases([])
        blob = "\n".join(focus["focus_lines"]).lower()
        self.assertIn("no revision_case", blob)
        self.assertNotIn("buildup bridge", blob)

    def test_dual_verifier_source_has_no_a_bridge_hardcode(self):
        import story_video_agent_v3.dual_video_vision_verifier as mod

        src = inspect.getsource(mod.run_dual_video_vision_verifier)
        self.assertNotIn("critical buildup bridge between deficit setup", src)
        self.assertIn("build_verifier_focus_from_revision_cases", src)
        self.assertIn("REVISION_CASES", src)


class TestMainChainWiresPhase7(unittest.TestCase):
    def test_run_story_e2e_source_references_evidence_bridge(self):
        src = inspect.getsource(run_story_e2e)
        self.assertIn("extract_dense_frames_for_issue", src)
        self.assertIn("run_vlm_story_critic", src)
        self.assertIn("semantic_evidence", src)
        self.assertIn("confirmed_issue_ids", src)
        self.assertIn("provisional_revision_cases", src)
        self.assertNotIn('setdefault("evidence_sufficiency", "observed")', src)

    def test_vlm_critic_accepts_extra_frames(self):
        sig = inspect.signature(run_vlm_story_critic)
        self.assertIn("extra_frames", sig.parameters)


if __name__ == "__main__":
    unittest.main()
