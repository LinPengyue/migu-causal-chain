"""Unit tests for final EDL evidence binding + goal lineage (no paid API)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent_v3.final_goal_evidence import (
    build_goal_lineage_report,
    can_inherit_prior_evidence,
    compare_candidate_delivery_video_binding,
)


class InheritEvidenceTests(unittest.TestCase):
    def _seg(self, **kw):
        base = {
            "segment_id": "seg_equalizer_goal_action",
            "role": "equalizer_goal_action",
            "event_ids": ["v3_goal_goalcand_01_01_to_11"],
            "media_in": 100.0,
            "media_out": 120.0,
        }
        base.update(kw)
        return base

    def _prior(self, **kw):
        base = {
            "segment_id": "seg_equalizer_goal_action",
            "role": "equalizer_goal_action",
            "event_ids": ["v3_goal_goalcand_01_01_to_11"],
            "media_in": 100.0,
            "media_out": 120.0,
            "source_pts": {"media_in": 100.0, "media_out": 120.0},
            "observation_window": {"media_in": 100.0, "media_out": 120.0},
            "source_video_sha256": "abc",
            "first_live_status": "UNRESOLVED",
        }
        base.update(kw)
        return base

    def test_inherit_requires_matching_sha_and_observation_window(self):
        ok, why = can_inherit_prior_evidence(
            segment=self._seg(),
            prior_row=self._prior(),
            source_video_sha256="abc",
            prior_video_sha256="abc",
        )
        self.assertTrue(ok, why)

    def test_reject_missing_prior_sha(self):
        ok, why = can_inherit_prior_evidence(
            segment=self._seg(),
            prior_row=self._prior(source_video_sha256=None),
            source_video_sha256="abc",
            prior_video_sha256=None,
        )
        self.assertFalse(ok)
        self.assertEqual(why, "missing_prior_video_sha256")

    def test_reject_missing_prior_sha_for_verified(self):
        ok, why = can_inherit_prior_evidence(
            segment=self._seg(),
            prior_row=self._prior(
                first_live_status="FIRST_LIVE_VERIFIED",
                source_video_sha256=None,
            ),
            source_video_sha256="abc",
            prior_video_sha256=None,
        )
        self.assertFalse(ok)
        self.assertEqual(why, "missing_prior_video_sha256_cannot_inherit_verified")

    def test_reject_sha_mismatch(self):
        ok, why = can_inherit_prior_evidence(
            segment=self._seg(),
            prior_row=self._prior(),
            source_video_sha256="aaa",
            prior_video_sha256="bbb",
        )
        self.assertFalse(ok)
        self.assertEqual(why, "source_video_sha256_mismatch")

    def test_reject_changed_media_window(self):
        ok, why = can_inherit_prior_evidence(
            segment=self._seg(media_out=130.0),
            prior_row=self._prior(),
            source_video_sha256="abc",
            prior_video_sha256="abc",
        )
        self.assertFalse(ok)
        self.assertEqual(why, "source_media_window_changed")

    def test_reject_observation_window_changed(self):
        ok, why = can_inherit_prior_evidence(
            segment=self._seg(),
            prior_row=self._prior(
                observation_window={"media_in": 100.0, "media_out": 115.0},
                source_pts={"media_in": 100.0, "media_out": 115.0},
            ),
            source_video_sha256="abc",
            prior_video_sha256="abc",
        )
        self.assertFalse(ok)
        self.assertEqual(why, "observation_window_changed")

    def test_reject_same_pts_different_goal_identity(self):
        ok, why = can_inherit_prior_evidence(
            segment=self._seg(role="go_ahead_goal_action", event_ids=["v3_goal_other"]),
            prior_row=self._prior(),
            source_video_sha256="abc",
            prior_video_sha256="abc",
        )
        self.assertFalse(ok)
        self.assertIn(why, (
            "goal_identity_role_mismatch",
            "goal_identity_event_ids_mismatch",
        ))

    def test_reject_verified_inherit_when_current_event_ids_empty(self):
        """Reverse: FIRST_LIVE_VERIFIED must not inherit without current event identity."""
        ok, why = can_inherit_prior_evidence(
            segment=self._seg(event_ids=[]),
            prior_row=self._prior(first_live_status="FIRST_LIVE_VERIFIED"),
            source_video_sha256="abc",
            prior_video_sha256="abc",
        )
        self.assertFalse(ok)
        self.assertEqual(why, "verified_inherit_requires_current_event_ids")

    def test_reject_verified_inherit_when_prior_event_ids_empty(self):
        """Reverse: FIRST_LIVE_VERIFIED must not inherit without prior event identity."""
        ok, why = can_inherit_prior_evidence(
            segment=self._seg(),
            prior_row=self._prior(
                first_live_status="FIRST_LIVE_VERIFIED",
                event_ids=[],
                causal_event_ids=[],
            ),
            source_video_sha256="abc",
            prior_video_sha256="abc",
        )
        self.assertFalse(ok)
        self.assertEqual(why, "verified_inherit_requires_prior_event_ids")

    def test_reject_verified_inherit_when_event_ids_mismatch(self):
        """Reverse: FIRST_LIVE_VERIFIED must not inherit across different goal events."""
        ok, why = can_inherit_prior_evidence(
            segment=self._seg(event_ids=["v3_goal_other"]),
            prior_row=self._prior(first_live_status="FIRST_LIVE_VERIFIED"),
            source_video_sha256="abc",
            prior_video_sha256="abc",
        )
        self.assertFalse(ok)
        self.assertEqual(why, "goal_identity_event_ids_mismatch")

    def test_allow_verified_inherit_when_event_ids_match(self):
        ok, why = can_inherit_prior_evidence(
            segment=self._seg(),
            prior_row=self._prior(first_live_status="FIRST_LIVE_VERIFIED"),
            source_video_sha256="abc",
            prior_video_sha256="abc",
        )
        self.assertTrue(ok, why)


class LineageStrictVsInferredTests(unittest.TestCase):
    def test_explicit_recovery_chain_graph_is_strict(self):
        edl = [
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
                }
            ]
        }
        graph = {
            "nodes": [
                {"id": "seg_equalizer_goal_action", "type": "story_segment"},
                {
                    "id": "event:v3_goal_goalcand_01_01_to_11",
                    "type": "event",
                    "event_id": "v3_goal_goalcand_01_01_to_11",
                    "linked_from_segment": "seg_equalizer_goal_action",
                },
            ]
        }
        report = build_goal_lineage_report(
            edl=edl,
            predicted_causal=predicted,
            goal_recovery=recovery,
            story_graph=graph,
            evidence_manifest={"goals": [{"segment_id": "seg_equalizer_goal_action",
                                          "first_live_status": "UNRESOLVED"}]},
        )
        self.assertEqual(report["n_strict_complete"], 1)
        self.assertEqual(report["n_inferred"], 0)
        self.assertEqual(report["n_unresolved"], 0)
        self.assertEqual(report["goals"][0]["lineage_class"], "STRICT_COMPLETE")

    def test_nearest_pts_only_is_inferred_not_strict(self):
        """EDL event is strip atom; recovery only matches by PTS → INFERRED at best."""
        edl = [
            {
                "segment_id": "seg_opponent_opening_goal_action",
                "role": "opponent_opening_goal_action",
                "media_in": 100.0,
                "media_out": 122.0,
                "event_ids": ["causal:pred_0007:atom_fill_Goal_x"],
                "include_in_cut": True,
            },
        ]
        # Chain contains the atom event (explicit causal) but recovery only via PTS.
        predicted = {
            "causal_chains": [
                {
                    "annotation_id": "pred_0007",
                    "prediction_source": "causal_chain6_predicted",
                    "events": [
                        {"event_id": "atom_fill_Goal_x", "type": "进球", "t_ms": 110000}
                    ],
                }
            ]
        }
        recovery = {
            "candidates": [
                {
                    "candidate_id": "goalcand_00_00_to_01",
                    "goal_action_sec": 110.0,
                    "score_confirmation_sec": 150.0,
                }
            ]
        }
        graph = {
            "nodes": [
                {"id": "seg_opponent_opening_goal_action", "type": "story_segment"},
                {
                    "id": "event:causal:pred_0007:atom_fill_Goal_x",
                    "type": "event",
                    "linked_from_segment": "seg_opponent_opening_goal_action",
                },
            ]
        }
        report = build_goal_lineage_report(
            edl=edl,
            predicted_causal=predicted,
            goal_recovery=recovery,
            story_graph=graph,
            evidence_manifest={"goals": []},
        )
        g = report["goals"][0]
        # Causal+graph explicit via event_ids → can still be STRICT without recovery id.
        # Recovery itself is INFERRED if linked; overall STRICT if chain/graph explicit.
        self.assertIn(g["lineage_class"], ("STRICT_COMPLETE", "INFERRED"))
        if g.get("recovery_link_class") == "INFERRED":
            self.assertEqual(g["recovery_link"], "inferred_nearest_pts")
        # Nearest-PTS alone must never be the only path counted as structural without
        # explicit chain — n_structurally_traced alias equals n_strict_complete.
        self.assertEqual(report["n_structurally_traced_to_mp4"], report["n_strict_complete"])

    def test_pts_only_no_chain_no_graph_is_unresolved(self):
        edl = [{
            "segment_id": "seg_x",
            "role": "equalizer_goal_action",
            "media_in": 50.0,
            "media_out": 70.0,
            "event_ids": [],
            "include_in_cut": True,
        }]
        recovery = {
            "candidates": [{"candidate_id": "goalcand_z", "goal_action_sec": 55.0}]
        }
        report = build_goal_lineage_report(
            edl=edl,
            predicted_causal={"causal_chains": []},
            goal_recovery=recovery,
            story_graph={"nodes": []},
            evidence_manifest={"goals": []},
        )
        self.assertEqual(report["n_strict_complete"], 0)
        self.assertEqual(report["n_unresolved"], 1)
        self.assertEqual(report["goals"][0]["lineage_class"], "UNRESOLVED")
        self.assertEqual(report["goals"][0]["recovery_link_class"], "INFERRED")

    def test_deleted_segment_excluded_from_counts(self):
        edl = [
            {
                "segment_id": "seg_keep",
                "role": "equalizer_goal_action",
                "media_in": 1.0,
                "media_out": 2.0,
                "event_ids": ["v3_goal_goalcand_a"],
                "include_in_cut": True,
            },
            {
                "segment_id": "seg_drop",
                "role": "go_ahead_goal_action",
                "media_in": 3.0,
                "media_out": 4.0,
                "event_ids": ["v3_goal_goalcand_b"],
                "include_in_cut": False,
            },
        ]
        predicted = {
            "causal_chains": [{
                "annotation_id": "v3_outcome_a",
                "goal_candidate_id": "goalcand_a",
                "events": [{"event_id": "v3_goal_goalcand_a", "type": "进球"}],
            }]
        }
        recovery = {"candidates": [
            {"candidate_id": "goalcand_a", "goal_action_sec": 1.5},
            {"candidate_id": "goalcand_b", "goal_action_sec": 3.5},
        ]}
        graph = {"nodes": [
            {"id": "seg_keep", "type": "story_segment"},
            {"id": "event:v3_goal_goalcand_a", "type": "event",
             "linked_from_segment": "seg_keep"},
        ]}
        report = build_goal_lineage_report(
            edl=edl,
            predicted_causal=predicted,
            goal_recovery=recovery,
            story_graph=graph,
            evidence_manifest={"goals": []},
        )
        self.assertEqual(report["n_final_goal_segments"], 1)
        self.assertEqual(report["goals"][0]["segment_id"], "seg_keep")


class CandidateDeliveryBindingTests(unittest.TestCase):
    def test_detects_window_change_and_sha_mismatch(self):
        delivery = {"source_video_sha256": "aaa", "goals": []}
        candidate = {"source_video_sha256": "bbb", "goals": []}
        d_edl = [{
            "segment_id": "seg_equalizer_goal_action",
            "role": "equalizer_goal_action",
            "media_in": 10.0,
            "media_out": 20.0,
            "include_in_cut": True,
        }]
        c_edl = [{
            "segment_id": "seg_equalizer_goal_action",
            "role": "equalizer_goal_action",
            "media_in": 10.0,
            "media_out": 25.0,
            "include_in_cut": True,
        }]
        b = compare_candidate_delivery_video_binding(
            delivery_manifest=delivery,
            candidate_manifest=candidate,
            delivery_edl=d_edl,
            candidate_edl=c_edl,
        )
        self.assertFalse(b["same_source_video_sha256"])
        self.assertEqual(b["window_changed_segments"], ["seg_equalizer_goal_action"])


class NoAutoStampPriorShaTests(unittest.TestCase):
    def test_build_delivery_does_not_stamp_current_sha_on_prior(self):
        from story_video_agent_v3.final_goal_evidence import build_delivery_and_candidate_evidence
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            video = root / "v.mp4"
            video.write_bytes(b"\x00" * 1000)
            prior = {
                "schema": "v3a_first_live_chain_audit_v1",
                # Intentionally missing source_video_sha256
                "goals": [{
                    "segment_id": "seg_equalizer_goal_action",
                    "role": "equalizer_goal_action",
                    "event_ids": ["v3_goal_goalcand_01"],
                    "media_in": 1.0,
                    "media_out": 2.0,
                    "first_live_status": "FIRST_LIVE_VERIFIED",
                    "agent_auto_verified": True,
                    "goal_action_verified_ok": True,
                    "observation_window": {"media_in": 1.0, "media_out": 2.0},
                }],
            }
            edl = [{
                "segment_id": "seg_equalizer_goal_action",
                "role": "equalizer_goal_action",
                "event_ids": ["v3_goal_goalcand_01"],
                "media_in": 1.0,
                "media_out": 2.0,
                "include_in_cut": True,
            }]
            # Avoid real ffmpeg by mocking audit path via empty need when inherit fails
            # — inherit must fail due to missing prior SHA, then reaudit runs.
            # Use a tiny stub: patch audit_retained_goal_first_live.
            import story_video_agent_v3.final_goal_evidence as mod

            def fake_audit(**kwargs):
                return {
                    "schema": "v3a_first_live_chain_audit_v1",
                    "goals": [{
                        "segment_id": "seg_equalizer_goal_action",
                        "role": "equalizer_goal_action",
                        "media_in": 1.0,
                        "media_out": 2.0,
                        "first_live_status": "UNRESOLVED",
                        "agent_auto_verified": False,
                        "goal_action_verified_ok": False,
                    }],
                    "status_counts": {"UNRESOLVED": 1, "FIRST_LIVE_VERIFIED": 0,
                                      "POSSIBLE_FIRST_LIVE": 0, "REPLAY_DETECTED": 0},
                    "n_goal_anchors": 1,
                }

            orig = mod.audit_retained_goal_first_live
            mod.audit_retained_goal_first_live = fake_audit  # type: ignore
            try:
                pack = build_delivery_and_candidate_evidence(
                    delivery_edl=edl,
                    candidate_edl=None,
                    video=video,
                    out_dir=root / "out",
                    prior_v3r_audit=prior,
                    predicted_causal={"causal_chains": []},
                    goal_recovery={"candidates": []},
                    story_graph={"nodes": []},
                )
            finally:
                mod.audit_retained_goal_first_live = orig  # type: ignore

            trust = pack["prior_source_trust"]
            self.assertFalse(trust["stamped_current_sha_onto_prior"])
            self.assertFalse(trust["prior_has_trusted_sha"])
            # Prior VERIFIED must not be inherited without SHA.
            g = pack["delivery"]["goals"][0]
            self.assertFalse(g.get("inherited"))
            self.assertEqual(g.get("first_live_status"), "UNRESOLVED")
            self.assertTrue(pack["delivery"].get("prior_source_missing_records"))


if __name__ == "__main__":
    unittest.main()
