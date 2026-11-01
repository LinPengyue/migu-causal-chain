"""G2 evidence upgrade gate — fail-closed integration anti-cases."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent.v2_generic_edl_composer import compose_generic_t01_edl
from story_video_agent.v2_video_evidence_gate import (
    evaluate_video_verification_claim,
    verification_level_for_edl,
)


def _identity():
    return {
        "match_id": "match_A",
        "video_sha256": "v" * 64,
        "events_sha256": "e" * 64,
        "strip_provenance": "algo_predicted|run=x",
    }


class TestEvidenceGate(unittest.TestCase):
    def test_status_string_alone_fails(self):
        goal = {
            "verification_status": "verified_first_live",
            "shot_sec": 10.0,
            "net_sec": 12.0,
            "live_or_replay": "live",
            "media_in": 5.0,
            "media_out": 20.0,
            "identity": _identity(),
            # no clip/frames
        }
        d = evaluate_video_verification_claim(goal=goal, expected_identity=_identity(), video_duration_sec=100.0)
        self.assertFalse(d["ok"])

    def test_wrong_match_identity_fails(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            clip = td / "c.mp4"
            clip.write_bytes(b"0" * 2000)
            f1 = td / "a.jpg"
            f2 = td / "b.jpg"
            f1.write_bytes(b"jpeg1" * 100)
            f2.write_bytes(b"jpeg2" * 100)
            goal = {
                "verification_status": "verified_first_live",
                "shot_sec": 10.0,
                "net_sec": 12.0,
                "live_or_replay": "live",
                "media_in": 5.0,
                "media_out": 20.0,
                "clip_path": str(clip),
                "frame_paths": [str(f1), str(f2)],
                "identity": {**_identity(), "match_id": "other_match"},
                "semantic_verification_class": "automated_video_verified",
                "automated_semantic_log_path": str(td / "log.json"),
            }
            (td / "log.json").write_text("{}", encoding="utf-8")
            d = evaluate_video_verification_claim(goal=goal, expected_identity=_identity())
            self.assertFalse(d["ok"])
            self.assertEqual(d.get("level"), "rejected_identity")

    def test_replay_fails(self):
        d = evaluate_video_verification_claim(
            goal={"live_or_replay": "replay", "verification_status": "verified_first_live", "identity": _identity()},
            expected_identity=_identity(),
        )
        self.assertFalse(d["ok"])
        self.assertIn("replay", d.get("level", ""))

    def test_inverted_pts_fails(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            clip = td / "c.mp4"
            clip.write_bytes(b"0" * 2000)
            f1 = td / "a.jpg"
            f2 = td / "b.jpg"
            f1.write_bytes(b"1" * 200)
            f2.write_bytes(b"2" * 200)
            goal = {
                "media_in": 20.0,
                "shot_sec": 12.0,
                "net_sec": 10.0,
                "media_out": 5.0,
                "live_or_replay": "live",
                "clip_path": str(clip),
                "frame_paths": [str(f1), str(f2)],
                "identity": _identity(),
            }
            d = evaluate_video_verification_claim(goal=goal, expected_identity=_identity(), video_duration_sec=100)
            self.assertFalse(d["ok"])
            self.assertEqual(d.get("level"), "rejected_pts")

    def test_out_of_range_pts_fails(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            clip = td / "c.mp4"
            clip.write_bytes(b"0" * 2000)
            f1 = td / "a.jpg"
            f2 = td / "b.jpg"
            f1.write_bytes(b"1" * 200)
            f2.write_bytes(b"2" * 200)
            goal = {
                "media_in": 5.0,
                "shot_sec": 10.0,
                "net_sec": 12.0,
                "media_out": 9999.0,
                "live_or_replay": "live",
                "clip_path": str(clip),
                "frame_paths": [str(f1), str(f2)],
                "identity": _identity(),
            }
            d = evaluate_video_verification_claim(goal=goal, expected_identity=_identity(), video_duration_sec=100)
            self.assertFalse(d["ok"])

    def test_scoreboard_only_fails(self):
        d = evaluate_video_verification_claim(
            goal={"scoreboard_only": True, "identity": _identity(), "verification_status": "verified_first_live"},
            expected_identity=_identity(),
        )
        self.assertFalse(d["ok"])

    def test_stitch_fails(self):
        d = evaluate_video_verification_claim(
            goal={"cross_window_stitch": True, "identity": _identity()},
            expected_identity=_identity(),
        )
        self.assertFalse(d["ok"])

    def test_edl_composer_does_not_upgrade_fake_verified(self):
        arc = {
            "protagonist_side": "left",
            "protagonist_team_name": "X",
            "deficit_score": [0, 1],
            "equalizer_score": [1, 1],
            "go_ahead_score": [2, 1],
            "score_confirmation_sec": {"deficit": 1, "equalizer": 2, "go_ahead": 3},
            "goal_action_sec": {},
        }
        fake_goal = {
            "role": "opening_deficit",
            "verification_status": "verified_first_live",
            "shot_sec": 10,
            "net_sec": 12,
            "live_or_replay": "live",
            "media_in": 5,
            "media_out": 20,
        }
        edl = compose_generic_t01_edl(
            match_id="match_A",
            selected_arc=arc,
            arc_status="story_candidate",
            goals=[fake_goal],
            level="video_verified",
            expected_identity=_identity(),
            video_duration_sec=100.0,
        )
        # fake goal must remain unresolved / not verified_first_live segment
        goal_segs = [s for s in edl["segments"] if s.get("role") == "opening_deficit"]
        self.assertTrue(goal_segs)
        self.assertNotEqual(goal_segs[0].get("verification_status"), "verified_first_live")
        self.assertFalse(edl.get("verified_first_live"))
        self.assertFalse(edl["render_ready"])

    def test_level_helper_without_identity_never_video_verified(self):
        lvl = verification_level_for_edl(
            {
                "verification_status": "verified_first_live",
                "shot_sec": 1,
                "net_sec": 2,
                "live_or_replay": "live",
            }
        )
        self.assertNotEqual(lvl, "video_verified")


if __name__ == "__main__":
    unittest.main()
