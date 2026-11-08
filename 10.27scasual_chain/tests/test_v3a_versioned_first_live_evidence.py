"""Unit tests for versioned first-live evidence ingest (no paid API)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent_v3.versioned_first_live_evidence import (
    apply_versioned_equalizer_binding,
    validate_paid_binding,
)


class VersionedBindingTests(unittest.TestCase):
    def test_reject_sha_mismatch(self):
        paid = {
            "source_video_sha256": "aaa",
            "segment_id": "seg_equalizer_goal_action",
            "source_pts": {"media_in": 1.0, "media_out": 2.0},
            "event_id_from_b_manifest": "eid",
            "final_first_live_status": "FIRST_LIVE_VERIFIED",
            "agreement": "consistent",
        }
        r = validate_paid_binding(
            paid_verify=paid,
            expected_sha256="bbb",
            expected_segment_id="seg_equalizer_goal_action",
            expected_event_id="eid",
            expected_media_in=1.0,
            expected_media_out=2.0,
        )
        self.assertFalse(r["ok"])
        self.assertIn("source_video_sha256_mismatch", r["errors"])

    def test_versioned_write_does_not_mutate_prior_and_keeps_other_unresolved(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            prior = {
                "schema": "v3a_final_goal_evidence_manifest_v1",
                "source_video": "/tmp/x.mp4",
                "source_video_sha256": "abc",
                "goals": [
                    {
                        "segment_id": "seg_opponent_opening_goal_action",
                        "role": "opponent_opening_goal_action",
                        "event_ids": ["e0"],
                        "media_in": 10.0,
                        "media_out": 20.0,
                        "first_live_status": "UNRESOLVED",
                    },
                    {
                        "segment_id": "seg_equalizer_goal_action",
                        "role": "equalizer_goal_action",
                        "event_ids": ["atom_fill_0116_Goal_5657621"],
                        "media_in": 5645.621,
                        "media_out": 5667.621,
                        "first_live_status": "UNRESOLVED",
                    },
                    {
                        "segment_id": "seg_go_ahead_goal_action",
                        "role": "go_ahead_goal_action",
                        "event_ids": ["e2"],
                        "media_in": 100.0,
                        "media_out": 120.0,
                        "first_live_status": "UNRESOLVED",
                    },
                ],
            }
            prior_path = td_path / "prior.json"
            prior_path.write_text(json.dumps(prior), encoding="utf-8")
            paid = {
                "source_video_sha256": "abc",
                "segment_id": "seg_equalizer_goal_action",
                "source_pts": {"media_in": 5645.621, "media_out": 5667.621},
                "event_id_from_b_manifest": "atom_fill_0116_Goal_5657621",
                "final_first_live_status": "FIRST_LIVE_VERIFIED",
                "agreement": "consistent",
                "judgments": ["FIRST_LIVE_VERIFIED", "FIRST_LIVE_VERIFIED"],
                "score_confirmation_sec": 5712.01,
            }
            paid_path = td_path / "paid.json"
            paid_path.write_text(json.dumps(paid), encoding="utf-8")
            out = td_path / "out"
            res = apply_versioned_equalizer_binding(
                prior_manifest_path=prior_path,
                paid_verify_path=paid_path,
                out_dir=out,
                code_sha="deadbeef",
                force_human_review=True,
            )
            # Prior file unchanged
            prior_after = json.loads(prior_path.read_text(encoding="utf-8"))
            self.assertEqual(prior_after["goals"][1]["first_live_status"], "UNRESOLVED")
            m = res["manifest"]
            self.assertFalse(m["release_authorized"])
            self.assertEqual(m["delivery_label"], "HUMAN_REVIEW_REQUIRED")
            by_id = {g["segment_id"]: g for g in m["goals"]}
            self.assertEqual(by_id["seg_opponent_opening_goal_action"]["first_live_status"], "UNRESOLVED")
            self.assertEqual(by_id["seg_go_ahead_goal_action"]["first_live_status"], "UNRESOLVED")
            # Residual risk → POSSIBLE_FIRST_LIVE under force_human_review
            self.assertEqual(by_id["seg_equalizer_goal_action"]["first_live_status"], "POSSIBLE_FIRST_LIVE")
            self.assertTrue((out / "versions").is_dir())
            self.assertTrue((out / "latest_version_pointer.json").is_file())


if __name__ == "__main__":
    unittest.main()
