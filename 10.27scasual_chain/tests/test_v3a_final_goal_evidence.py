"""Unit tests for final EDL evidence binding + goal lineage (no paid API)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_video_agent_v3.final_goal_evidence import (
    build_goal_lineage_report,
    can_inherit_prior_evidence,
)


class InheritEvidenceTests(unittest.TestCase):
    def test_inherit_requires_matching_sha_and_window(self):
        seg = {"segment_id": "seg_equalizer_goal_action", "role": "equalizer_goal_action",
               "media_in": 100.0, "media_out": 120.0}
        prior = {
            "segment_id": "seg_equalizer_goal_action",
            "role": "equalizer_goal_action",
            "media_in": 100.0,
            "media_out": 120.0,
            "source_pts": {"media_in": 100.0, "media_out": 120.0},
            "first_live_status": "UNRESOLVED",
        }
        ok, why = can_inherit_prior_evidence(
            segment=seg, prior_row=prior,
            source_video_sha256="abc", prior_video_sha256="abc",
        )
        self.assertTrue(ok, why)

    def test_reject_changed_media_window(self):
        seg = {"segment_id": "seg_x", "role": "equalizer_goal_action",
               "media_in": 100.0, "media_out": 130.0}
        prior = {
            "segment_id": "seg_x",
            "media_in": 100.0,
            "media_out": 120.0,
            "source_pts": {"media_in": 100.0, "media_out": 120.0},
            "first_live_status": "UNRESOLVED",
        }
        ok, why = can_inherit_prior_evidence(
            segment=seg, prior_row=prior,
            source_video_sha256="abc", prior_video_sha256="abc",
        )
        self.assertFalse(ok)
        self.assertEqual(why, "source_media_window_changed")

    def test_reject_sha_mismatch(self):
        seg = {"segment_id": "seg_x", "media_in": 1.0, "media_out": 2.0}
        prior = {
            "segment_id": "seg_x",
            "media_in": 1.0,
            "media_out": 2.0,
            "source_pts": {"media_in": 1.0, "media_out": 2.0},
            "first_live_status": "POSSIBLE_FIRST_LIVE",
        }
        ok, why = can_inherit_prior_evidence(
            segment=seg, prior_row=prior,
            source_video_sha256="aaa", prior_video_sha256="bbb",
        )
        self.assertFalse(ok)
        self.assertEqual(why, "source_video_sha256_mismatch")


class LineageTests(unittest.TestCase):
    def test_recovery_to_edl_to_timeline(self):
        edl = [
            {
                "segment_id": "seg_title_open",
                "role": "story_title",
                "media_in": None,
                "media_out": None,
                "include_in_cut": True,
            },
            {
                "segment_id": "seg_equalizer_goal_action",
                "role": "equalizer_goal_action",
                "media_in": 100.0,
                "media_out": 122.0,
                "event_ids": ["v3_goal_goalcand_01_01_to_11"],
                "include_in_cut": True,
            },
        ]
        predicted = {
            "causal_chains": [
                {
                    "annotation_id": "v3_outcome_0001",
                    "goal_candidate_id": "goalcand_01_01_to_11",
                    "prediction_source": "v3_goal_recovery+optional_8.31_antecedent",
                    "events": [
                        {"event_id": "v3_goal_goalcand_01_01_to_11", "type": "进球", "t_ms": 110000}
                    ],
                }
            ]
        }
        recovery = {
            "candidates": [
                {
                    "candidate_id": "goalcand_01_01_to_11",
                    "goal_action_sec": 110.0,
                    "score_confirmation_sec": 150.0,
                    "score_before": [1, 1],
                    "score_after": [2, 1],
                    "single_goal_increment": True,
                }
            ]
        }
        graph = {
            "nodes": [
                {"id": "seg_equalizer_goal_action", "type": "story_segment", "role": "equalizer_goal_action"},
                {"id": "event:v3_goal_goalcand_01_01_to_11", "type": "event",
                 "event_id": "v3_goal_goalcand_01_01_to_11", "linked_from_segment": "seg_equalizer_goal_action"},
            ]
        }
        evid = {
            "goals": [
                {
                    "segment_id": "seg_equalizer_goal_action",
                    "first_live_status": "UNRESOLVED",
                    "evidence_binding": "reverified_after_window_or_subject_change",
                }
            ]
        }
        report = build_goal_lineage_report(
            edl=edl,
            predicted_causal=predicted,
            goal_recovery=recovery,
            story_graph=graph,
            evidence_manifest=evid,
            final_mp4=Path("/tmp/story.mp4"),
        )
        self.assertEqual(report["n_final_goal_segments"], 1)
        self.assertEqual(report["n_structurally_traced_to_mp4"], 1)
        g = report["goals"][0]
        self.assertEqual(g["recovery_candidate_id"], "goalcand_01_01_to_11")
        self.assertEqual(g["predicted_causal_chain_id"], "v3_outcome_0001")
        self.assertEqual(g["story_graph_segment_node"], "seg_equalizer_goal_action")
        self.assertTrue(g["in_final_mp4"])
        self.assertEqual(g["first_live_status"], "UNRESOLVED")
        self.assertIn("first_live_unresolved", g["gaps"])

    def test_entered_causal_alone_not_enough_without_edl(self):
        """Recovery in predicted_causal but absent from final EDL → 0 final goals."""
        report = build_goal_lineage_report(
            edl=[{"segment_id": "seg_title_open", "role": "story_title"}],
            predicted_causal={
                "causal_chains": [{
                    "annotation_id": "v3_outcome_0001",
                    "goal_candidate_id": "goalcand_x",
                    "prediction_source": "v3_goal_recovery+optional_8.31_antecedent",
                    "events": [{"event_id": "v3_goal_goalcand_x", "type": "进球"}],
                }]
            },
            goal_recovery={"candidates": [{"candidate_id": "goalcand_x", "goal_action_sec": 1.0}]},
            story_graph={"nodes": []},
            evidence_manifest={"goals": []},
        )
        self.assertEqual(report["n_final_goal_segments"], 0)
        self.assertTrue(report["entered_predicted_causal_alone_insufficient"])


if __name__ == "__main__":
    unittest.main()
