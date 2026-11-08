"""Phase 7: VLM → structured semantic evidence → CONFIRMED_STORY_DEFECT gate."""
from __future__ import annotations

import inspect
import unittest
from pathlib import Path

from story_video_agent_v3.semantic_story_diagnosis import apply_semantic_diagnosis_layer
from story_video_agent_v3.story_e2e_agent import run_story_e2e
from story_video_agent_v3.story_paid_eval import run_vlm_story_critic
from story_video_agent_v3.vlm_semantic_evidence import (
    normalize_semantic_evidence_item,
    vlm_critic_to_observation_updates,
)


class TestSemanticEvidenceBridge(unittest.TestCase):
    def test_model_claimed_without_frame_refs_not_supported(self):
        item = normalize_semantic_evidence_item(
            {
                "issue_id": "large_source_jump_a_b",
                "observed_fact": "abrupt cut",
                "defect_hypothesis": "bridge broken",
                "claims_story_defect": True,
                "confidence": 0.99,
            },
            sent_frame_ids=["f0", "f1", "f2"],
        )
        self.assertEqual(item["claim_status"], "MODEL_CLAIMED")
        self.assertFalse(item["supports_original_issue"])

    def test_evidence_supported_requires_ge2_sent_frame_ids(self):
        item = normalize_semantic_evidence_item(
            {
                "issue_id": "large_source_jump_a_b",
                "observed_fact": "crowd then midfield with no buildup",
                "defect_hypothesis": "causal bridge missing",
                "claims_story_defect": True,
                "confidence": 0.4,
                "evidence_refs": [{"frame_id": "f0"}, {"frame_id": "f2"}],
            },
            sent_frame_ids=["f0", "f1", "f2"],
        )
        self.assertEqual(item["claim_status"], "EVIDENCE_SUPPORTED")
        self.assertTrue(item["supports_original_issue"])

    def test_invented_frame_ids_block_support(self):
        item = normalize_semantic_evidence_item(
            {
                "issue_id": "large_source_jump_a_b",
                "observed_fact": "x",
                "defect_hypothesis": "y",
                "claims_story_defect": True,
                "evidence_refs": [{"frame_id": "ghost1"}, {"frame_id": "ghost2"}],
            },
            sent_frame_ids=["f0", "f1"],
        )
        self.assertEqual(item["claim_status"], "MODEL_CLAIMED")
        self.assertFalse(item["supports_original_issue"])

    def test_vlm_updates_populate_derived_issues(self):
        updates = vlm_critic_to_observation_updates(
            {
                "parsed": {
                    "semantic_evidence": [
                        {
                            "issue_id": "large_source_jump_a_b",
                            "observed_fact": "scoreboard then unrelated wing play",
                            "defect_hypothesis": "no live bridge action",
                            "claims_story_defect": True,
                            "confidence": 0.7,
                            "evidence_refs": [
                                {"frame_id": "story_j_t1p00"},
                                {"frame_id": "story_j_t3p00"},
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
        self.assertEqual(updates["stats"]["n_evidence_supported"], 1)
        self.assertIn("large_source_jump_a_b", updates["confirmed_issue_ids"])
        self.assertEqual(len(updates["derived_issues"]), 1)
        self.assertEqual(
            updates["derived_issues"][0]["claim_status"], "EVIDENCE_SUPPORTED"
        )

    def test_diagnosis_confirms_only_evidence_supported(self):
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
        out = apply_semantic_diagnosis_layer(
            base,
            observations={
                "semantic_provider_used": True,
                "fixture_or_offline": False,
                "semantic_evidence": [
                    {
                        "issue_id": "large_source_jump_a_b",
                        "claim_status": "EVIDENCE_SUPPORTED",
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

        out2 = apply_semantic_diagnosis_layer(
            base,
            observations={
                "semantic_provider_used": True,
                "fixture_or_offline": False,
                "semantic_evidence": [
                    {
                        "issue_id": "large_source_jump_a_b",
                        "claim_status": "MODEL_CLAIMED",
                        "supports_original_issue": False,
                        "observed_fact": "maybe abrupt",
                        "defect_hypothesis": "unclear",
                        "frame_refs": [],
                    }
                ],
                "derived_issues": [],
                "confirmed_issue_ids": ["large_source_jump_a_b"],
            },
        )
        self.assertEqual(out2["issues"][0]["diagnosis_status"], "HYPOTHESIS_NEEDS_VIDEO")


class TestMainChainWiresPhase7(unittest.TestCase):
    def test_run_story_e2e_source_references_evidence_bridge(self):
        src = inspect.getsource(run_story_e2e)
        self.assertIn("extract_dense_frames_for_issue", src)
        self.assertIn("run_vlm_story_critic", src)
        self.assertIn("semantic_evidence", src)
        self.assertIn("confirmed_issue_ids", src)
        # Must not force observed sufficiency (defeats frame-check gate).
        self.assertNotIn('setdefault("evidence_sufficiency", "observed")', src)

    def test_vlm_critic_accepts_extra_frames(self):
        sig = inspect.signature(run_vlm_story_critic)
        self.assertIn("extra_frames", sig.parameters)


if __name__ == "__main__":
    unittest.main()
