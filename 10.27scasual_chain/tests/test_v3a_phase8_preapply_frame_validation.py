"""Pre-apply Search must not accept a claimed FIRST_LIVE without real binding.

Zero HTTP. The positive review is a unit-test-only synthetic fixture; it is
NOT a certification of any football footage.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent_v3.first_live_window_evidence import (
    SCHEMA,
    TIMELINE_REVIEW_SCHEMA,
    validate_first_live_evidence_record,
    window_key,
)
from story_video_agent_v3.story_evidence_search import (
    EVIDENCE_TIER_EVENT_PTS,
    EVIDENCE_TIER_FIRST_LIVE,
    _annotate_first_live_tier,
)

SOURCE_SHA = "cd" * 32
START, END = 100.0, 112.0


def valid_pack(root: Path):
    frames = []
    for i, pts in enumerate((START + 1.0, END - 1.0)):
        f = root / f"frame{i}.jpg"
        data = f"synthetic_test_frame_{i}".encode()
        f.write_bytes(data)
        frames.append({
            "frame_id": f"frame{i}",
            "source_pts_sec": pts,
            "path": str(f),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    manifest = {
        "source_sha256": SOURCE_SHA,
        "source_pts_start": START,
        "source_pts_end": END,
        "frame_sha256": [r["sha256"] for r in frames],
    }
    return {
        "schema": SCHEMA,
        "key": window_key(SOURCE_SHA, START, END),
        "source_sha256": SOURCE_SHA,
        "source_pts_start": START,
        "source_pts_end": END,
        "frames": frames,
        "manifest": manifest,
        "manifest_digest": hashlib.sha256(
            json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
        "broadcast_timeline_review": {
            "schema": TIMELINE_REVIEW_SCHEMA,
            "source_sha256": SOURCE_SHA,
            "source_pts_start": START,
            "source_pts_end": END,
            "outcome": "FIRST_LIVE_VERIFIED",
            "method": "synthetic_unit_test_review",
            "replay_hits": [],
        },
    }


def annotate(pack):
    key = window_key(SOURCE_SHA, START, END)
    return _annotate_first_live_tier(
        {
            "candidate_id": "not_match_specific",
            "source_pts_start": START,
            "source_pts_end": END,
            "evidence_tier": EVIDENCE_TIER_EVENT_PTS,
        },
        evidence_store={"by_key": {key: pack}},
        source_sha=SOURCE_SHA,
    )


class TestPreApplyFrameAndTimelineGate(unittest.TestCase):
    def test_bare_status_string_does_not_certify(self):
        c = annotate({"first_live_status": "FIRST_LIVE_VERIFIED"})
        self.assertFalse(c["executable_safe_revision"])
        self.assertEqual(c["first_live_status"], "NOT_VERIFIED")
        self.assertFalse(c["first_live_validation"]["binding_valid"])

    def test_complete_synthetic_evidence_is_executable(self):
        with tempfile.TemporaryDirectory() as td:
            pack = valid_pack(Path(td))
            self.assertTrue(validate_first_live_evidence_record(
                pack, source_sha=SOURCE_SHA, pts_start=START, pts_end=END
            )["ok"])
            c = annotate(pack)
            self.assertTrue(c["executable_safe_revision"])
            self.assertEqual(c["evidence_tier"], EVIDENCE_TIER_FIRST_LIVE)

    def test_modified_frame_file_fails(self):
        with tempfile.TemporaryDirectory() as td:
            pack = valid_pack(Path(td))
            Path(pack["frames"][0]["path"]).write_bytes(b"tampered_frame_bytes")
            c = annotate(pack)
            self.assertFalse(c["executable_safe_revision"])
            self.assertEqual(c["first_live_status"], "NOT_VERIFIED")
            self.assertEqual(c["first_live_validation"]["reason"], "frame_bytes_hash_mismatch")

    def test_conflicting_replay_hits_fail(self):
        with tempfile.TemporaryDirectory() as td:
            pack = valid_pack(Path(td))
            pack["broadcast_timeline_review"]["replay_hits"] = [{"event_id": "replay"}]
            c = annotate(pack)
            self.assertFalse(c["executable_safe_revision"])
            self.assertEqual(c["first_live_status"], "REPLAY_CONFIRMED")

    def test_wrong_source_or_pts_does_not_certify(self):
        with tempfile.TemporaryDirectory() as td:
            pack = valid_pack(Path(td))
            pack["broadcast_timeline_review"]["source_pts_start"] = START + 7.0
            self.assertFalse(annotate(pack)["executable_safe_revision"])
            pack = valid_pack(Path(td))
            pack["source_sha256"] = "ef" * 32
            self.assertFalse(annotate(pack)["executable_safe_revision"])

    def test_one_valid_one_missing_is_not_all_safe(self):
        with tempfile.TemporaryDirectory() as td:
            good = valid_pack(Path(td))
            self.assertTrue(annotate(good)["executable_safe_revision"])
            self.assertFalse(annotate({"first_live_status": "FIRST_LIVE_VERIFIED"})["executable_safe_revision"])


if __name__ == "__main__":
    unittest.main()
