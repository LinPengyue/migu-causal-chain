"""Zero-HTTP regression: FIRST_LIVE evidence/feedback precede top-k cutoff.

The first-broadcast attestation is a synthetic structural test fixture, never a
claim about the original game footage. No match-specific PTS are used.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent_v3.first_live_window_evidence import (
    SCHEMA, TIMELINE_REVIEW_SCHEMA, window_key,
)
from story_video_agent_v3.story_evidence_search import (
    _rank_events_in_window, run_story_evidence_search,
)

SHA = "e9" * 32


def event(event_id: str, t: float, heat: float):
    return {
        "event_id": event_id,
        "event_type": "Shot",
        "media_time": {
            "event_time_sec": t,
            "start_time_sec": t - 2.0,
            "end_time_sec": t + 4.0,
        },
        "video_context": {
            "broadcast_phase": "LIVE", "is_replay": False,
            "is_slow_motion": False,
        },
        "scores": {
            "overall_score": heat,
            "emotional_heat_score": heat,
            "criticality_score": heat,
        },
    }


def evidence(root: Path, start: float, end: float):
    frames = []
    for idx, t in enumerate((start + .5, end - .5)):
        f = root / f"test-frame-{idx}.jpg"
        data = f"zero-http-synthetic-frame-{idx}".encode()
        f.write_bytes(data)
        frames.append({
            "frame_id": f"f{idx}",
            "source_pts_sec": t,
            "path": str(f),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    manifest = {
        "source_sha256": SHA,
        "source_pts_start": start,
        "source_pts_end": end,
        "frame_sha256": [fr["sha256"] for fr in frames],
    }
    return {
        "schema": SCHEMA,
        "key": window_key(SHA, start, end),
        "source_sha256": SHA,
        "source_pts_start": start,
        "source_pts_end": end,
        "frames": frames,
        "manifest": manifest,
        "manifest_digest": hashlib.sha256(json.dumps(
            manifest, sort_keys=True, ensure_ascii=False,
        ).encode()).hexdigest(),
        "broadcast_timeline_review": {
            "schema": TIMELINE_REVIEW_SCHEMA,
            "source_sha256": SHA,
            "source_pts_start": start,
            "source_pts_end": end,
            "outcome": "FIRST_LIVE_VERIFIED",
            "method": "synthetic_unit_test_review_not_real_game",
            "replay_hits": [],
        },
    }


class TestEvidenceFirstTopK(unittest.TestCase):
    def test_safe_sixth_candidate_survives_unauthenticated_top_five(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows = [event(f"heat{i}", float(i * 100), 15.0) for i in range(1, 6)]
            # A higher-scoring candidate overlapping the attested window must
            # not erase its safety-qualified alternative during raw dedup.
            rows.append(event("overlap_heat", 602.0, 25.0))
            rows.append(event("safe_below_heat_rank", 600.0, 2.0))
            path = root / "events.json"
            path.write_text(json.dumps({"events": rows}), encoding="utf-8")
            raw_top5 = _rank_events_in_window(
                rows, lo=11.0, hi=999.0, hints=("shot",),
                goals=[], occupied=[],
            )
            self.assertEqual(len(raw_top5), 5)
            self.assertFalse(any(r["event_id"] == "safe_below_heat_rank" for r in raw_top5))
            pack = evidence(root, 598.0, 604.0)
            store = {"by_key": {pack["key"]: pack}}
            diag = {"issues": [{
                "issue_id": "gap_a_to_b", "category": "transition",
                "severity": "major", "diagnosis_status": "CONFIRMED_STORY_DEFECT",
                "evidence_sufficiency": "observed",
                "story_defect_confirmed": True, "segment_ids": ["a", "b"],
            }]}
            edl = [
                {"segment_id": "a", "role": "setup", "media_in": 0.0,
                 "media_out": 10.0, "include_in_cut": True},
                {"segment_id": "b", "role": "buildup", "media_in": 1000.0,
                 "media_out": 1010.0, "include_in_cut": True},
            ]
            out = run_story_evidence_search(
                diagnosis=diag, edl=edl, events_json=path,
                source_sha256=SHA, first_live_evidence_store=store,
            )
            selected = out["verified_candidates"]
            self.assertEqual(len(selected), 5)
            self.assertEqual(selected[0]["event_id"], "safe_below_heat_rank")
            self.assertTrue(selected[0]["executable_safe_revision"])
            self.assertEqual(out["targets"][0]["n_candidates_considered"], 7)
            self.assertEqual(out["targets"][0]["n_first_live_executable"], 1)
            self.assertFalse(any(c["event_id"] == "overlap_heat" for c in selected))
            self.assertTrue(out["executable_search_success"])

    def test_no_evidence_keeps_original_event_rank_order(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows = [event(f"e{i}", float(i * 100), 20.0 - i) for i in range(1, 7)]
            p = root / "events.json"
            p.write_text(json.dumps({"events": rows}), encoding="utf-8")
            diag = {"issues": [{
                "issue_id": "gap", "category": "transition",
                "severity": "major", "evidence_sufficiency": "observed",
                "segment_ids": ["a", "b"],
            }]}
            edl = [
                {"segment_id": "a", "role": "setup", "media_in": 0.0,
                 "media_out": 10.0, "include_in_cut": True},
                {"segment_id": "b", "role": "buildup", "media_in": 1000.0,
                 "media_out": 1010.0, "include_in_cut": True},
            ]
            out = run_story_evidence_search(
                diagnosis=diag, edl=edl, events_json=p,
            )
            self.assertEqual(len(out["verified_candidates"]), 5)
            self.assertFalse(out["executable_search_success"])
            self.assertTrue(all(not c["executable_safe_revision"] for c in out["verified_candidates"]))
            self.assertEqual(out["targets"][0]["n_candidates_considered"], 6)


if __name__ == "__main__":
    unittest.main()
