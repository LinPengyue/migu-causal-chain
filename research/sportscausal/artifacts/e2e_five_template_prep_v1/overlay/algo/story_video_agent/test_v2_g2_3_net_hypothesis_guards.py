"""G2.3 negative tests: hypothesized net must not upgrade to verified_first_live."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from story_video_agent.v2_g2_first_live_retrieval import annotate_shot_only_evidence
from story_video_agent.v2_video_evidence_gate import (
    NOT_VERIFIED,
    evaluate_video_verification_claim,
)


def _identity():
    return {
        "match_id": "match_A",
        "video_sha256": "v" * 64,
        "events_sha256": "e" * 64,
        "strip_provenance": "algo_predicted|run=x",
    }


def _artifacts(td: Path):
    clip = td / "c.mp4"
    clip.write_bytes(b"0" * 2000)
    f1 = td / "a.jpg"
    f2 = td / "b.jpg"
    f1.write_bytes(b"jpeg1" * 100)
    f2.write_bytes(b"jpeg2" * 100)
    return clip, f1, f2


class TestG23NetHypothesisGuards(unittest.TestCase):
    def test_annotate_never_puts_hyp_into_net_sec(self):
        a = annotate_shot_only_evidence(
            media_in=6767.67,
            media_out=6778.15,
            shot_sec=6774.49,
            hypothesized_result_sec=6778.49,  # past media_out (G2.2 bug pattern)
            observed_net_sec=None,
            event_broadcast_phase="LIVE",
        )
        self.assertEqual(a["evidence_status"], "SHOT_ONLY_NET_UNRESOLVED")
        self.assertIsNone(a["net_sec"])
        self.assertEqual(a["hypothesized_result_sec"], 6778.49)
        self.assertTrue(a["hyp_net_outside_clip"])
        self.assertFalse(a["claims_continuous_live"])
        self.assertEqual(a["semantic_verification_class"], NOT_VERIFIED)

    def test_hyp_net_past_clip_end_cannot_verify(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            clip, f1, f2 = _artifacts(td)
            goal = {
                "verification_status": "verified_first_live",
                "media_in": 6767.67,
                "shot_sec": 6774.49,
                "net_sec": 6778.49,  # mis-copied hyp into net
                "media_out": 6778.15,
                "hypothesized_result_sec": 6778.49,
                "observed_net": False,
                "live_or_replay": "live",
                "clip_path": str(clip),
                "frame_paths": [str(f1), str(f2)],
                "identity": _identity(),
                "semantic_verification_class": "automated_video_verified",
                "automated_semantic_log_path": str(td / "log.json"),
            }
            (td / "log.json").write_text("{}", encoding="utf-8")
            d = evaluate_video_verification_claim(goal=goal, expected_identity=_identity(), video_duration_sec=9000)
            self.assertFalse(d["ok"])
            self.assertIn(
                d.get("reason"),
                {
                    "hypothesized_result_misrepresented_as_net_sec",
                    "net_sec_after_media_out",
                    "pts_order_violation",
                },
            )

    def test_shot_only_live_event_cannot_verify(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            clip, f1, f2 = _artifacts(td)
            goal = {
                "verification_status": "verified_first_live",
                "evidence_status": "SHOT_ONLY_NET_UNRESOLVED",
                "media_in": 10.0,
                "shot_sec": 12.0,
                "net_sec": None,
                "media_out": 20.0,
                "event_broadcast_phase": "LIVE",
                "live_or_replay": "live",
                "claims_continuous_live": True,
                "clip_path": str(clip),
                "frame_paths": [str(f1), str(f2)],
                "identity": _identity(),
            }
            d = evaluate_video_verification_claim(goal=goal, expected_identity=_identity())
            self.assertFalse(d["ok"])
            self.assertEqual(d.get("reason"), "shot_only_net_unresolved_cannot_verify_first_live")

    def test_net_only_after_replay_transition_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            clip, f1, f2 = _artifacts(td)
            goal = {
                "verification_status": "verified_first_live",
                "media_in": 10.0,
                "shot_sec": 12.0,
                "net_sec": 18.0,
                "media_out": 25.0,
                "net_after_replay_transition": True,
                "live_or_replay": "live",
                "clip_path": str(clip),
                "frame_paths": [str(f1), str(f2)],
                "identity": _identity(),
                "semantic_verification_class": "automated_video_verified",
                "automated_semantic_log_path": str(td / "log.json"),
            }
            (td / "log.json").write_text("{}", encoding="utf-8")
            d = evaluate_video_verification_claim(goal=goal, expected_identity=_identity())
            self.assertFalse(d["ok"])
            self.assertEqual(d.get("reason"), "net_only_after_replay_transition")

    def test_net_on_other_camera_angle_still_needs_semantics(self):
        """Ball-in-net on alternate angle without continuous first-live — stitch/other angle fails closed."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            clip, f1, f2 = _artifacts(td)
            goal = {
                "verification_status": "verified_first_live",
                "media_in": 10.0,
                "shot_sec": 12.0,
                "net_sec": 14.0,
                "media_out": 20.0,
                "spliced_from_multiple_windows": True,  # other camera stitch
                "live_or_replay": "live",
                "clip_path": str(clip),
                "frame_paths": [str(f1), str(f2)],
                "identity": _identity(),
            }
            d = evaluate_video_verification_claim(goal=goal, expected_identity=_identity())
            self.assertFalse(d["ok"])
            self.assertEqual(d.get("level"), "rejected_stitch")

    def test_wrong_team_ordinary_shot_cannot_verify(self):
        d = evaluate_video_verification_claim(
            goal={
                "verification_status": "verified_first_live",
                "wrong_team_shot": True,
                "ordinary_shot_score_changes_later_only": True,
                "identity": _identity(),
                "live_or_replay": "live",
            },
            expected_identity=_identity(),
        )
        self.assertFalse(d["ok"])
        self.assertEqual(d.get("reason"), "wrong_team_or_ordinary_shot_not_goal")

    def test_b_post_score_replay_negative_control(self):
        """G2.1 B late_third pattern: board already new then action — must not verify."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            clip, f1, f2 = _artifacts(td)
            goal = {
                "verification_status": "verified_first_live",
                "media_in": 5675.01,
                "shot_sec": 5680.0,
                "net_sec": 5685.0,
                "media_out": 5715.01,
                "live_or_replay": "replay",  # post-score replay package
                "clip_path": str(clip),
                "frame_paths": [str(f1), str(f2)],
                "identity": _identity(),
                "semantic_verification_class": "automated_video_verified",
                "automated_semantic_log_path": str(td / "log.json"),
            }
            (td / "log.json").write_text("{}", encoding="utf-8")
            d = evaluate_video_verification_claim(goal=goal, expected_identity=_identity())
            self.assertFalse(d["ok"])
            self.assertEqual(d.get("level"), "rejected_replay_or_ambiguous")


if __name__ == "__main__":
    unittest.main()
