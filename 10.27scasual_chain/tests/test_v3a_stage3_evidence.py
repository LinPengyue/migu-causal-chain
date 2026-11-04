"""V3-A Stage-3 zero-billed safety tests; synthetic source, no real API."""
from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "algo"))
from story_video_agent.media import MediaInfo  # noqa: E402
from story_video_agent_v3.planner_stage2 import _intervals, compile_proposal  # noqa: E402
from story_video_agent_v3.stage3_evidence import (  # noqa: E402
    _select_vlm_window_indices, _validate_bounds,
    validate_stage3_inputs, run,
)


def fixture():
    story = {"match_id": "fr_test", "story_tier": "complete"}
    plan = {
        "match_id": "fr_test", "story_tier": "complete",
        "story_scope": {"selected_arc": {
            "behind_start": {"score": "0:1", "t_sec": 1535.65},
            "equalizer": {"score": "1:1", "t_sec": 2600.0},
            "go_ahead": {"score": "2:1", "t_sec": 3200.0},
        }},
    }
    edl = [
        {"segment_id": "eq", "role": "equalizer_goal_action",
         "media_in": 2600, "media_out": 2620, "event_ids": ["eq"]},
    ]
    issue = {"kind": "missing_story_element", "severity": "P0",
             "target": "opponent_opening", "detail": "missing original live goal"}
    audit = {
        "schema": "v3a_story_quality_audit_v1",
        "match_id": "fr_test", "render_ready": False,
        "release_decision": "NOT_AUTHORIZED",
        "revision_requests": [issue],
    }
    proposal = compile_proposal(story, plan, edl, audit)
    hashes = {"story": "a", "plan": "b", "edl": "c", "audit": "d"}
    proposal["source_sha256"] = hashes
    return proposal, story, plan, edl, audit, hashes


def validate(proposal, story, plan, edl, audit, hashes, **kwargs):
    return validate_stage3_inputs(proposal, story, plan, edl, audit, hashes, **kwargs)


class Stage3EvidenceTests(unittest.TestCase):
    def test_fr_canonical_p0_is_accepted_as_search_only(self):
        p, s, pl, e, a, h = fixture()
        task = validate(p, s, pl, e, a, h)
        self.assertEqual("opponent_opening", task["issue_target"])
        self.assertEqual(_intervals(1535.65), task["search_windows"])
        self.assertEqual(7, len(task["search_windows"]))
        self.assertFalse(task["may_edit_edl"])
        self.assertEqual("UNVERIFIED", task["evidence_status"])

    def test_cannot_forge_new_goal_time_or_window(self):
        p, s, pl, e, a, h = fixture()
        p["selected_tasks"][0]["search_windows"][0]["start"] = 1351.0
        with self.assertRaisesRegex(ValueError, "canonical derivation|search window"):
            validate(p, s, pl, e, a, h)

    def test_cannot_reassign_cross_match(self):
        p, s, pl, e, a, h = fixture()
        p["match_id"] = "another_match"
        with self.assertRaisesRegex(ValueError, "cross-match"):
            validate(p, s, pl, e, a, h)

    def test_cannot_use_changed_phase5_files(self):
        p, s, pl, e, a, h = fixture()
        h["edl"] = "changed"
        with self.assertRaisesRegex(ValueError, "sha256"):
            validate(p, s, pl, e, a, h)

    def test_v2_false_live_cannot_be_marked_verified(self):
        p, s, pl, e, a, h = fixture()
        p["selected_tasks"][0]["evidence_status"] = "VERIFIED"
        with self.assertRaises(ValueError):
            validate(p, s, pl, e, a, h)

    def test_bad_source_video_or_manifest_refused(self):
        p, s, pl, e, a, h = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "fr.mp4"
            manifest = {
                "match_id": "fr_test", "render_ready": False,
                "inputs": {"video": str(Path(tmp) / "wrong.mp4")},
            }
            with self.assertRaisesRegex(ValueError, "does not match"):
                validate(p, s, pl, e, a, h, video_path=video, manifest=manifest)

    def test_bounded_frames_refuse_duration_overrun(self):
        p, s, pl, e, a, h = fixture()
        task = validate(p, s, pl, e, a, h)
        media = MediaInfo(
            path="/tmp/synthetic.mp4", duration_sec=120,
            width=160, height=90, fps=5, video_codec="mpeg4",
            audio_codec="", start_time_sec=0, format_name="mp4", size_bytes=1000,
        )
        with self.assertRaisesRegex(ValueError, "out of source"):
            _validate_bounds(task, media, per_window=3, max_frames=24)

    def test_frame_budget_cannot_be_exceeded(self):
        p, s, pl, e, a, h = fixture()
        media = MediaInfo(
            path="/tmp/synthetic.mp4", duration_sec=7305.555,
            width=160, height=90, fps=5, video_codec="mpeg4",
            audio_codec="", start_time_sec=0, format_name="mp4", size_bytes=1000,
        )
        task = validate(p, s, pl, e, a, h)
        with self.assertRaisesRegex(ValueError, "budget"):
            _validate_bounds(task, media, per_window=4, max_frames=24)

    def test_vlm_selection_covers_early_middle_late(self):
        self.assertEqual([0, 3, 6], _select_vlm_window_indices(7))
        self.assertEqual([0], _select_vlm_window_indices(1))

    def test_auto_edl_authorization_is_rejected(self):
        p, s, pl, e, a, h = fixture()
        p["edl_modified"] = True
        with self.assertRaises(ValueError):
            validate(p, s, pl, e, a, h)

    def test_unrelated_p2_in_place_of_p0_rejected(self):
        p, s, pl, e, a, h = fixture()
        p["selected_tasks"][0]["issue_kind"] = "possible_image_anomaly"
        with self.assertRaises(ValueError):
            validate(p, s, pl, e, a, h)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                         "FFmpeg / FFprobe unavailable")
    def test_source_bound_sample_run_no_remote_edl_or_release(self):
        # Compact 20s fixture: T01 10s, search window is [0,25] so use >=25s source.
        p, s, pl, e, a, h = fixture()
        pl["story_scope"]["selected_arc"]["behind_start"]["t_sec"] = 10.0
        p = compile_proposal(s, pl, e, a)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            video = base / "fr.mp4"
            import subprocess
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                 "-i", "color=c=blue:s=160x90:r=5:d=30",
                 "-c:v", "mpeg4", "-y", str(video)],
                check=True, timeout=25,
            )
            phase = base / "04_phase5"
            phase.mkdir()
            docs = {"story": (s, "t01_story.json"), "plan": (pl, "story_plan.json"),
                    "edl": (e, "candidate_edl.json"), "audit": (a, "v3a_quality_audit.json")}
            from story_video_agent_v3.planner_stage2 import _sha
            for _, (doc, name) in docs.items():
                (phase / name).write_text(json.dumps(doc), encoding="utf-8")
            p["source_sha256"] = {
                k: _sha(phase / name) for k, (_, name) in docs.items()
            }
            proposal_path = base / "proposal.json"
            proposal_path.write_text(json.dumps(p), encoding="utf-8")
            (phase / "phase5_manifest.json").write_text(json.dumps({
                "match_id": "fr_test", "render_ready": False,
                "inputs": {"video": str(video)},
            }), encoding="utf-8")
            out = base / "stage3"
            result = run(phase5=phase, proposal_path=proposal_path, video=video,
                         out_dir=out, samples_per_window=1, frame_budget=3)
            self.assertEqual("FRAMES_ONLY", result["mode"])
            self.assertEqual(1, result["frame_budget_used"])
            self.assertFalse(result["edl_modified"])
            self.assertFalse(result["render_ready"])
            self.assertFalse(result["first_live_goal_verified"])
            self.assertEqual("UNKNOWN", result["semantic_coverage"])
            self.assertEqual(0, result["vlm_execution"]["real_requests"])
            self.assertTrue((out / "stage3_evidence.json").is_file())
            self.assertTrue((out / "frame_manifest.json").is_file())
            self.assertEqual([w["frame_id"] for item in result["search_windows"]
                              for w in item["frames"] if w["frame_id"]],
                             [w["frame_id"] for item in result["search_windows"]
                              for w in item["frames"]])
            with self.assertRaisesRegex(ValueError, "already exists"):
                run(phase5=phase, proposal_path=proposal_path,
                    video=video, out_dir=out, samples_per_window=1, frame_budget=3)


if __name__ == "__main__":
    unittest.main()
