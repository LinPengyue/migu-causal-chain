"""V3 remote VLM verify unit tests (mock / no billed HTTP)."""
from __future__ import annotations

import unittest

from story_video_agent.api_provider import ApiConfigError

from .remote_vlm_verify import (
    cross_check_visible_evidence,
    make_api,
    scrub_config_audit,
)


class BudgetGateTests(unittest.TestCase):
    def test_real_requires_budget_approval(self):
        with self.assertRaises(ApiConfigError):
            make_api(enable_real_api=True, i_approve_budget=False)

    def test_mock_default(self):
        api = make_api(enable_real_api=False, i_approve_budget=False, max_calls=3)
        self.assertTrue(api.force_mock)
        st = api.status()
        self.assertEqual(st["mode"], "mock")


class CrossCheckTests(unittest.TestCase):
    def test_high_confidence_alone_does_not_verify(self):
        cross = cross_check_visible_evidence(
            vlm_inference={
                "observed_shot": True,
                "observed_net": True,
                "live_or_replay": "live",
                "attacking_team_match": True,
                "claims_continuous_live": True,
                "confidence": 0.99,
                "shot_frame_ids": ["f1"],
                "net_frame_ids": ["f2"],
                "uncertain": ["something_unclear"],
            },
            frames=[
                {"frame_id": "f1", "requested_media_sec": 1.0, "actual_media_sec": 1.0, "path": "/tmp/nope1.jpg"},
                {"frame_id": "f2", "requested_media_sec": 1.5, "actual_media_sec": 1.5, "path": "/tmp/nope2.jpg"},
            ],
            score_bounds={
                "last_before_obs": {"media_sec": 0.5},
                "first_after_obs": {"media_sec": 5.0},
            },
            media_in=0.0,
            media_out=3.0,
            continuous_clip_ok=True,
        )
        self.assertTrue(cross["auto_upgrade_from_confidence_blocked"])
        self.assertFalse(cross["structurally_ready_for_automated_verify"])
        self.assertIn("vlm_listed_uncertainties", cross["evidence_gaps"])

    def test_net_without_frame_ids_rejected(self):
        cross = cross_check_visible_evidence(
            vlm_inference={
                "observed_shot": True,
                "observed_net": True,
                "live_or_replay": "live",
                "attacking_team_match": True,
                "claims_continuous_live": True,
                "confidence": 0.9,
                "shot_frame_ids": ["f1"],
                "net_frame_ids": [],
                "uncertain": [],
            },
            frames=[{"frame_id": "f1", "requested_media_sec": 1.0, "path": "/tmp/x.jpg"}],
            score_bounds=None,
            media_in=0.0,
            media_out=2.0,
            continuous_clip_ok=True,
        )
        self.assertIn("net_claimed_without_net_frame_ids", cross["evidence_gaps"])
        self.assertFalse(cross["structurally_ready_for_automated_verify"])

    def test_shot_after_net_pts_rejected(self):
        cross = cross_check_visible_evidence(
            vlm_inference={
                "observed_shot": True,
                "observed_net": True,
                "live_or_replay": "live",
                "attacking_team_match": True,
                "claims_continuous_live": True,
                "shot_frame_ids": ["f_shot"],
                "net_frame_ids": ["f_net"],
                "uncertain": [],
                "confidence": 0.8,
            },
            frames=[
                {"frame_id": "f_shot", "actual_media_sec": 2.5, "path": __file__},
                {"frame_id": "f_net", "actual_media_sec": 1.0, "path": __file__},
            ],
            score_bounds=None,
            media_in=0.0,
            media_out=3.0,
            continuous_clip_ok=True,
        )
        self.assertIn("shot_pts_after_net_pts", cross["evidence_gaps"])
        self.assertFalse(cross["structurally_ready_for_automated_verify"])

    def test_replay_excluded(self):
        cross = cross_check_visible_evidence(
            vlm_inference={
                "observed_shot": True,
                "observed_net": True,
                "live_or_replay": "replay",
                "attacking_team_match": True,
                "claims_continuous_live": True,
                "shot_frame_ids": ["f1"],
                "net_frame_ids": ["f2"],
                "uncertain": [],
            },
            frames=[
                {"frame_id": "f1", "actual_media_sec": 1.0, "path": __file__},
                {"frame_id": "f2", "actual_media_sec": 1.2, "path": __file__},
            ],
            score_bounds=None,
            media_in=0.0,
            media_out=3.0,
            continuous_clip_ok=True,
        )
        self.assertIn("replay_not_first_live", cross["evidence_gaps"])
        self.assertFalse(cross["visible_crosscheck"]["replay_excluded"])


class ConfigAuditTests(unittest.TestCase):
    def test_scrub_audit_zero_http_shape(self):
        audit = scrub_config_audit(max_calls=3, tcp_probe=False)
        self.assertEqual(audit["http_requests_sent"], 0)
        self.assertIn("models", audit)
        self.assertNotIn("api_key", json_keys_flat(audit))


def json_keys_flat(obj, prefix="") -> set:
    keys = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.add(k)
            keys |= json_keys_flat(v, k)
    elif isinstance(obj, list):
        for i in obj[:3]:
            keys |= json_keys_flat(i, prefix)
    return keys


if __name__ == "__main__":
    unittest.main()
