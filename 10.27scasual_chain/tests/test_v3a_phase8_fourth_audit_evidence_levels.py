"""Phase 8 fourth audit — frame binding ≠ first-broadcast LIVE.

Zero HTTP. No Planner/Verifier redesign. No auto paid.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent_v3.first_live_window_evidence import (
    BINDING_FRAME_BOUND_VALID,
    FIRST_LIVE_VERIFIED,
    REPLAY_CONFIRMED,
    TIMELINE_REVIEW_SCHEMA,
    build_broadcast_timeline_review,
    build_local_first_live_evidence_pack,
    validate_first_live_evidence_record,
    validate_frame_binding,
)
from story_video_agent_v3.story_video_verifier import (
    build_first_live_window_ledger,
    compute_independent_hard_safety,
)


def _tiny_mp4(path: Path, *, pattern: str = "color=c=black:s=64x64:d=3") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    import subprocess

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        pattern,
        "-f",
        "lavfi",
        "-i",
        "sine=f=440:d=3",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not path.is_file():
        raise unittest.SkipTest(f"ffmpeg tiny mp4 failed: {(r.stderr or '')[-200:]}")
    return path


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _synthetic_pack(sha: str, start: float, end: float) -> dict:
    manifest = {"k": 1, "evidence_tier": "frame_binding_only"}
    return {
        "schema": "v3a_first_live_window_evidence_v1",
        "status": BINDING_FRAME_BOUND_VALID,
        "binding_status": BINDING_FRAME_BOUND_VALID,
        "first_live_status": "NOT_VERIFIED",
        "source_sha256": sha,
        "source_pts_start": start,
        "source_pts_end": end,
        "manifest": manifest,
        "manifest_digest": hashlib.sha256(
            json.dumps(manifest, sort_keys=True).encode()
        ).hexdigest(),
        "frames": [
            {"sha256": "b" * 64, "path": "/no/file", "source_pts_sec": start + 0.2},
            {"sha256": "c" * 64, "path": "/no/file", "source_pts_sec": end - 0.2},
        ],
    }


class TestEvidenceLevelsFourthAudit(unittest.TestCase):
    def test_binding_pack_without_timeline_is_unknown(self):
        root = Path(tempfile.mkdtemp(prefix="p8_l4_bind_"))
        mp4 = _tiny_mp4(root / "source.mp4")
        sha = _sha256_file(mp4)
        pack = build_local_first_live_evidence_pack(
            source_mp4=mp4,
            source_sha=sha,
            pts_start=0.4,
            pts_end=2.2,
            out_dir=root / "pack",
        )
        self.assertEqual(pack["binding_status"], BINDING_FRAME_BOUND_VALID)
        self.assertEqual(pack["first_live_status"], "NOT_VERIFIED")
        self.assertNotEqual(pack["status"], FIRST_LIVE_VERIFIED)
        val = validate_first_live_evidence_record(
            pack, source_sha=sha, pts_start=0.4, pts_end=2.2
        )
        self.assertTrue(val["binding_valid"])
        self.assertFalse(val["first_live_verified"])
        self.assertFalse(val["ok"])
        led = build_first_live_window_ledger(
            source_sha=sha,
            new_windows=[
                {
                    "source_pts_start": 0.4,
                    "source_pts_end": 2.2,
                    "validated_evidence": pack,
                    "require_evidence_files": True,
                }
            ],
        )
        self.assertEqual(led["aggregate_status"], "NOT_VERIFIED")
        self.assertEqual(led["windows"][0]["candidate_class"], "pending_timeline_review")
        cand = _tiny_mp4(root / "cand.mp4")
        hs = compute_independent_hard_safety(
            hard_vetoes=[],
            goal_intact=True,
            render_rows_ok=True,
            candidate_mp4=cand,
            extra={
                "has_new_footage": True,
                "first_live_ledger": led,
                "pts_ok": True,
                "source_provenance_ok": True,
                "require_candidate_mp4": True,
            },
        )
        self.assertEqual(hs["safety"], "UNKNOWN")
        self.assertEqual(hs.get("candidate_class"), "pending_timeline_review")

    def test_identical_jpg_hashes_not_first_live(self):
        root = Path(tempfile.mkdtemp(prefix="p8_l4_ident_"))
        # Static black → identical frame hashes (same false-positive class as audit).
        mp4 = _tiny_mp4(root / "source.mp4")
        sha = _sha256_file(mp4)
        pack = build_local_first_live_evidence_pack(
            source_mp4=mp4,
            source_sha=sha,
            pts_start=0.4,
            pts_end=2.2,
            out_dir=root / "pack",
        )
        hashes = [f["sha256"] for f in pack["frames"]]
        self.assertEqual(len(set(hashes)), 1, hashes)
        self.assertTrue(pack["manifest"]["identical_frame_hashes"])
        self.assertFalse(pack["manifest"]["claims_full_broadcast_timeline"])
        val = validate_frame_binding(
            pack, source_sha=sha, pts_start=0.4, pts_end=2.2
        )
        self.assertTrue(val["binding_valid"])
        self.assertTrue(val["identical_frame_hashes"])
        self.assertFalse(val["first_live_verified"])

    def test_replay_timeline_review_fails_hard_safety(self):
        sha = "sha_replay"
        pack = _synthetic_pack(sha, 10.0, 18.0)
        events = [
            {
                "event_id": "ev_replay",
                "media_time": {"start_time_sec": 10.0, "end_time_sec": 18.0},
                "video_context": {
                    "is_replay": True,
                    "broadcast_phase": "REPLAY",
                },
            }
        ]
        review = build_broadcast_timeline_review(
            source_sha=sha,
            pts_start=10.0,
            pts_end=18.0,
            events=events,
            binding_record=pack,
        )
        self.assertEqual(review["outcome"], REPLAY_CONFIRMED)
        val = validate_first_live_evidence_record(
            pack,
            source_sha=sha,
            pts_start=10.0,
            pts_end=18.0,
            require_files_exist=False,
            timeline_review=review,
        )
        self.assertTrue(val["binding_valid"])
        self.assertTrue(val["replay_confirmed"])
        self.assertFalse(val["first_live_verified"])
        led = build_first_live_window_ledger(
            source_sha=sha,
            new_windows=[
                {
                    "source_pts_start": 10.0,
                    "source_pts_end": 18.0,
                    "validated_evidence": pack,
                    "broadcast_timeline_review": review,
                    "require_evidence_files": False,
                }
            ],
        )
        self.assertEqual(led["aggregate_status"], "REPLAY_CONFIRMED")
        self.assertEqual(led["windows"][0]["candidate_class"], "unsafe_replay")
        hs = compute_independent_hard_safety(
            hard_vetoes=[],
            goal_intact=True,
            render_rows_ok=True,
            extra={
                "has_new_footage": True,
                "first_live_ledger": led,
                "pts_ok": True,
                "source_provenance_ok": True,
                "require_candidate_mp4": False,
            },
        )
        self.assertEqual(hs["safety"], "FAIL")

    def test_explicit_timeline_review_can_verify_first_live(self):
        sha = "sha_live"
        pack = _synthetic_pack(sha, 900.0, 908.0)
        review = build_broadcast_timeline_review(
            source_sha=sha,
            pts_start=900.0,
            pts_end=908.0,
            binding_record=pack,
            explicit_review={
                "source_sha256": sha,
                "source_pts_start": 900.0,
                "source_pts_end": 908.0,
                "outcome": FIRST_LIVE_VERIFIED,
                "method": "human_continuous_context_review",
                "rationale": "scoreboard advancing; no prior occurrence in pad window",
                "evidence_refs": [
                    {"kind": "context_clip", "sha256": "d" * 64, "media_in": 892.0, "media_out": 916.0}
                ],
                "reviewer": "unit_test_reviewer",
                "provenance": "UNIT_TEST_AUTHENTICATED",
            },
        )
        self.assertEqual(review["outcome"], FIRST_LIVE_VERIFIED)
        self.assertEqual(review["schema"], TIMELINE_REVIEW_SCHEMA)
        led = build_first_live_window_ledger(
            source_sha=sha,
            new_windows=[
                {
                    "source_pts_start": 900.0,
                    "source_pts_end": 908.0,
                    "validated_evidence": pack,
                    "broadcast_timeline_review": review,
                    "require_evidence_files": False,
                }
            ],
        )
        self.assertEqual(led["aggregate_status"], "FIRST_LIVE_VERIFIED")
        self.assertEqual(led["windows"][0]["candidate_class"], "approved_first_live")
        hs = compute_independent_hard_safety(
            hard_vetoes=[],
            goal_intact=True,
            render_rows_ok=True,
            extra={
                "has_new_footage": True,
                "first_live_ledger": led,
                "pts_ok": True,
                "source_provenance_ok": True,
                "require_candidate_mp4": False,
            },
        )
        self.assertEqual(hs["safety"], "PASS")

    def test_frame_pack_self_certify_explicit_review_rejected(self):
        sha = "sha_self"
        pack = _synthetic_pack(sha, 1.0, 2.0)
        review = build_broadcast_timeline_review(
            source_sha=sha,
            pts_start=1.0,
            pts_end=2.0,
            binding_record=pack,
            explicit_review={
                "source_sha256": sha,
                "source_pts_start": 1.0,
                "source_pts_end": 2.0,
                "outcome": FIRST_LIVE_VERIFIED,
                "cites_frame_pack_only": True,
                "rationale": "frames extracted ok",
                "evidence_refs": [{"kind": "frame_pack"}],
            },
        )
        self.assertEqual(review["outcome"], "UNKNOWN")
        val = validate_first_live_evidence_record(
            pack,
            source_sha=sha,
            pts_start=1.0,
            pts_end=2.0,
            require_files_exist=False,
            timeline_review=review,
        )
        self.assertFalse(val["first_live_verified"])

    def test_mismatched_source_sha_fails_binding(self):
        pack = _synthetic_pack("sha_ok", 1.0, 2.0)
        val = validate_frame_binding(
            pack, source_sha="sha_other", pts_start=1.0, pts_end=2.0, require_files_exist=False
        )
        self.assertFalse(val["binding_valid"])
        self.assertEqual(val["reason"], "source_sha_mismatch")

    def test_two_windows_one_unreviewed_unknown(self):
        sha = "sha_two"
        pack = _synthetic_pack(sha, 900.0, 908.0)
        review = build_broadcast_timeline_review(
            source_sha=sha,
            pts_start=900.0,
            pts_end=908.0,
            explicit_review={
                "source_sha256": sha,
                "source_pts_start": 900.0,
                "source_pts_end": 908.0,
                "outcome": FIRST_LIVE_VERIFIED,
                "rationale": "ok",
                "evidence_refs": [{"kind": "ctx"}],
                "reviewer": "t",
            },
        )
        pack2 = _synthetic_pack(sha, 1500.0, 1510.0)
        led = build_first_live_window_ledger(
            source_sha=sha,
            new_windows=[
                {
                    "source_pts_start": 900.0,
                    "source_pts_end": 908.0,
                    "validated_evidence": pack,
                    "broadcast_timeline_review": review,
                    "require_evidence_files": False,
                },
                {
                    "source_pts_start": 1500.0,
                    "source_pts_end": 1510.0,
                    "validated_evidence": pack2,
                    "require_evidence_files": False,
                },
            ],
        )
        self.assertTrue(led["any_window_unverified"])
        self.assertTrue(led["any_frame_bound_pending_timeline"])
        hs = compute_independent_hard_safety(
            hard_vetoes=[],
            goal_intact=True,
            render_rows_ok=True,
            extra={
                "has_new_footage": True,
                "first_live_ledger": led,
                "pts_ok": True,
                "source_provenance_ok": True,
                "require_candidate_mp4": False,
            },
        )
        self.assertEqual(hs["safety"], "UNKNOWN")

    def test_prior_ledger_label_without_timeline_does_not_certify(self):
        sha = "sha_prior"
        prior = {
            "windows": [
                {
                    "key": f"{sha}|900.000:908.000",
                    "source_sha": sha,
                    "status": FIRST_LIVE_VERIFIED,
                    # No broadcast_timeline_review → cannot carry forward.
                }
            ]
        }
        led = build_first_live_window_ledger(
            source_sha=sha,
            new_windows=[
                {
                    "source_pts_start": 900.0,
                    "source_pts_end": 908.0,
                    "first_live_status": FIRST_LIVE_VERIFIED,
                }
            ],
            prior_ledger=prior,
        )
        self.assertEqual(led["aggregate_status"], "NOT_VERIFIED")


if __name__ == "__main__":
    unittest.main()
