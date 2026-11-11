"""Synthetic no-HTTP tests: contextual two-cut gain cannot auto-promote.

The MP4 and frame bytes are test placeholders; no vision provider is called.
"""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from story_video_agent_v3.story_fullcut_sampling import fullcut_edit_context_sample_plan
from story_video_agent_v3.story_fullcut_semantic import screen_fullcut_semantic_gain
from story_video_agent_v3.story_timeline import build_story_timeline


def _edl():
    baseline = [
        {"segment_id": "opening", "role": "opponent_opening", "media_in": 0, "media_out": 10},
        {"segment_id": "setup", "role": "deficit_setup", "media_in": 15, "media_out": 25},
        {"segment_id": "buildup", "role": "buildup", "media_in": 50, "media_out": 60},
        {"segment_id": "goal", "role": "equalizer_goal_action", "media_in": 90, "media_out": 102},
        {"segment_id": "ending", "role": "ending_wrap", "media_in": 110, "media_out": 120},
    ]
    candidate = [
        baseline[0], baseline[1],
        {"segment_id": "new", "role": "buildup_bridge_action", "media_in": 32, "media_out": 40},
        *baseline[2:],
    ]
    return baseline, candidate


def _bound_pack(root: Path):
    frames = []
    for slot in ("pre_edit", "edit_impact", "post_edit", "global_ending"):
        for tag in ("baseline", "candidate"):
            fid = f"{tag}_{slot}_0"
            f = root / (fid + ".jpg")
            f.write_bytes(fid.encode())
            frames.append({
                "frame_id": fid, "video_tag": tag,
                "narrative_slot": slot, "path": str(f),
                "story_sec": 2.0,
            })
    b = root / "baseline.mp4"
    c = root / "candidate.mp4"
    b.write_bytes(b"baseline-test-cut")
    c.write_bytes(b"candidate-test-cut")
    return b, c, {"ok": True, "frames": frames}


def _review():
    base = {
        "information_gain": "YES",
        "beat_continuity": "IMPROVED",
        "pacing_tradeoff": "JUSTIFIED",
        "redundancy": "NO",
        "global_regression": "NO",
    }
    refs = {
        "information_gain": ["baseline_edit_impact_0", "candidate_edit_impact_0"],
        "beat_continuity": ["baseline_pre_edit_0", "candidate_pre_edit_0",
                           "baseline_post_edit_0", "candidate_post_edit_0"],
        "pacing_tradeoff": ["baseline_edit_impact_0", "candidate_edit_impact_0"],
        "redundancy": ["baseline_edit_impact_0", "candidate_edit_impact_0"],
        "global_regression": ["baseline_global_ending_0", "candidate_global_ending_0"],
    }
    return {
        **{k: {
            "verdict": verdict,
            "observed_difference": "The baseline and candidate show an explicit changed story state around the edit",
            "frame_ids": refs[k],
        } for k, verdict in base.items()},
        "recommendation": "CANDIDATE_PREFERABLE",
        "marginal_gain_vs_duration": (
            "The newly visible story-state transition may justify this extra duration, "
            "though video motion and audio require further review."
        ),
    }


class TestFullcutSemantic(unittest.TestCase):
    def test_sampler_spends_frames_on_edit_and_context(self):
        base, cand = _edl()
        plan = fullcut_edit_context_sample_plan(
            build_story_timeline(base), build_story_timeline(cand),
            changed_segment_ids=["new"], max_slots=4,
        )
        self.assertEqual(
            [p["narrative_slot"] for p in plan],
            ["pre_edit", "edit_impact", "post_edit", "global_ending"],
        )
        self.assertEqual(plan[1]["candidate_segment_id"], "new")
        self.assertEqual(plan[1]["baseline_segment_id"], "setup")
        self.assertEqual(
            plan[1]["reason"], "counterfactual_cut_boundary_not_same_event",
        )

    def test_low_budget_cannot_drop_edit_target(self):
        base, cand = _edl()
        plan = fullcut_edit_context_sample_plan(
            build_story_timeline(base), build_story_timeline(cand),
            changed_segment_ids=["new"], max_slots=2,
        )
        self.assertIn("edit_impact", [p["narrative_slot"] for p in plan])

    def test_screened_better_is_only_promising_not_formal_improvement(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            b, c, pack = _bound_pack(root)
            out = screen_fullcut_semantic_gain(
                _review(), frame_pack=pack, baseline_mp4=b, candidate_mp4=c,
            )
            self.assertEqual(out["status"], "SCREENED_BETTER")
            self.assertEqual(out["quality_advisory"], "PROMISING")
            self.assertFalse(out["authorizes_promote_best"])
            self.assertFalse(out["improvement_verified"])
            self.assertEqual(len(out["sampled_frame_sha256"]), 8)

    def test_observed_no_gain_retains_baseline(self):
        with tempfile.TemporaryDirectory() as td:
            b, c, pack = _bound_pack(Path(td))
            review = _review()
            review["information_gain"]["verdict"] = "NO"
            review["pacing_tradeoff"]["verdict"] = "NOT_JUSTIFIED"
            out = screen_fullcut_semantic_gain(
                review, frame_pack=pack, baseline_mp4=b, candidate_mp4=c,
            )
            self.assertEqual(out["status"], "SCREENED_NO_GAIN")
            self.assertEqual(out["quality_advisory"], "SAME")
            self.assertFalse(out["authorizes_promote_best"])

    def test_wrong_frame_citation_is_unverified(self):
        with tempfile.TemporaryDirectory() as td:
            b, c, pack = _bound_pack(Path(td))
            review = _review()
            review["information_gain"]["frame_ids"].append("not_sent")
            out = screen_fullcut_semantic_gain(
                review, frame_pack=pack, baseline_mp4=b, candidate_mp4=c,
            )
            self.assertEqual(out["status"], "UNVERIFIED")
            self.assertIn("unknown_frame_ids:information_gain", out["reasons"])

    def test_one_video_only_citations_do_not_prove_gain(self):
        with tempfile.TemporaryDirectory() as td:
            b, c, pack = _bound_pack(Path(td))
            review = _review()
            review["information_gain"]["frame_ids"] = ["candidate_edit_impact_0"]
            out = screen_fullcut_semantic_gain(
                review, frame_pack=pack, baseline_mp4=b, candidate_mp4=c,
            )
            self.assertEqual(out["status"], "UNVERIFIED")
            self.assertIn("missing_two_cut_comparison:information_gain", out["reasons"])

    def test_missing_ending_context_blocks_positive(self):
        with tempfile.TemporaryDirectory() as td:
            b, c, pack = _bound_pack(Path(td))
            pack["frames"] = [
                f for f in pack["frames"]
                if f["narrative_slot"] != "global_ending"
            ]
            out = screen_fullcut_semantic_gain(
                _review(), frame_pack=pack, baseline_mp4=b, candidate_mp4=c,
            )
            self.assertEqual(out["status"], "UNVERIFIED")
            self.assertIn("global_ending", out["missing_required_context_slots"])

    def test_frame_byte_tampering_is_not_quality_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            b, c, pack = _bound_pack(Path(td))
            target = Path(pack["frames"][0]["path"])
            target.unlink()
            out = screen_fullcut_semantic_gain(
                _review(), frame_pack=pack, baseline_mp4=b, candidate_mp4=c,
            )
            self.assertEqual(out["status"], "UNVERIFIED")
            self.assertIn("extracted_frame_file_missing", out["reasons"])

    def test_mp4_digest_mismatch_is_unverified(self):
        with tempfile.TemporaryDirectory() as td:
            b, c, pack = _bound_pack(Path(td))
            out = screen_fullcut_semantic_gain(
                _review(), frame_pack=pack, baseline_mp4=b, candidate_mp4=c,
                baseline_mp4_sha256="f" * 64,
            )
            self.assertEqual(out["status"], "UNVERIFIED")
            self.assertIn("baseline_mp4_sha_mismatch", out["reasons"])

    def test_length_truncated_response_never_supports_gain(self):
        with tempfile.TemporaryDirectory() as td:
            b, c, pack = _bound_pack(Path(td))
            out = screen_fullcut_semantic_gain(
                _review(), frame_pack=pack, baseline_mp4=b, candidate_mp4=c,
                finish_reason="length",
            )
            self.assertEqual(out["status"], "UNVERIFIED")

    def test_missing_semantic_response_is_unverified(self):
        with tempfile.TemporaryDirectory() as td:
            b, c, pack = _bound_pack(Path(td))
            out = screen_fullcut_semantic_gain(
                None, frame_pack=pack, baseline_mp4=b, candidate_mp4=c,
            )
            self.assertEqual(out["status"], "UNVERIFIED")
            self.assertFalse(out["authorizes_release"])


if __name__ == "__main__":
    unittest.main()
