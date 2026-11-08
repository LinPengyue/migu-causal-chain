"""Phase 8 third-audit real-loop gates (zero HTTP).

1) First-LIVE positive/negative via source SHA + PTS evidence packs
2) Paired with/without feedback ablation on the SAME baseline EDL
3) Evidence tokens require content hashes, not round/version/frame_ids
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent_v3.first_live_window_evidence import (
    build_local_first_live_evidence_pack,
    diff_new_source_windows,
    looks_like_content_hash,
    validate_first_live_evidence_record,
    window_key,
)
from story_video_agent_v3.story_evidence_search import run_story_evidence_search
from story_video_agent_v3.story_revision_feedback import (
    is_observation_grade_evidence_token,
    make_observation_evidence_token,
    should_penalize_candidate,
)
from story_video_agent_v3.story_revision_planner import plan_from_diagnosis
from story_video_agent_v3.story_video_verifier import (
    build_first_live_window_ledger,
    compute_independent_hard_safety,
)


def _tiny_mp4(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    import subprocess

    cmd = [
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=3",
        "-f", "lavfi", "-i", "sine=f=440:d=3",
        "-c:v", "libx264", "-c:a", "aac", "-shortest", str(path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not path.is_file():
        raise unittest.SkipTest(f"ffmpeg tiny mp4 failed: {(r.stderr or '')[-200:]}")
    return path


def _sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _edl_baseline():
    return [
        {
            "segment_id": "seg_open_goal",
            "role": "opponent_opening_goal_action",
            "include_in_cut": True,
            "media_in": 100.0,
            "media_out": 120.0,
            "is_replay": False,
        },
        {
            "segment_id": "seg_setup",
            "role": "deficit_scoreboard_anchor",
            "include_in_cut": True,
            "media_in": 200.0,
            "media_out": 205.0,
            "is_replay": False,
        },
        {
            "segment_id": "seg_turn",
            "role": "equalizer_goal_action",
            "include_in_cut": True,
            "media_in": 2800.0,
            "media_out": 2820.0,
            "is_replay": False,
        },
        {
            "segment_id": "seg_climax",
            "role": "go_ahead_goal_action",
            "include_in_cut": True,
            "media_in": 3000.0,
            "media_out": 3020.0,
            "is_replay": False,
        },
    ]


def _events_ab(path: Path) -> Path:
    events = {
        "events": [
            {
                "event_id": "ev_cand_A",
                "event_type": "Shot",
                "media_time": {
                    "event_time_sec": 900.0,
                    "start_time_sec": 896.0,
                    "end_time_sec": 908.0,
                },
                "video_context": {
                    "broadcast_phase": "LIVE",
                    "is_replay": False,
                    "is_slow_motion": False,
                },
                "scores": {
                    "overall_score": 9.0,
                    "emotional_heat_score": 9.0,
                    "criticality_score": 5.0,
                },
            },
            {
                "event_id": "ev_cand_B",
                "event_type": "Shot",
                "media_time": {
                    "event_time_sec": 1500.0,
                    "start_time_sec": 1496.0,
                    "end_time_sec": 1510.0,
                },
                "video_context": {
                    "broadcast_phase": "LIVE",
                    "is_replay": False,
                    "is_slow_motion": False,
                },
                "scores": {
                    "overall_score": 3.0,
                    "emotional_heat_score": 2.0,
                    "criticality_score": 1.0,
                },
            },
        ]
    }
    path.write_text(json.dumps(events), encoding="utf-8")
    return path


def _diag():
    return {
        "issues": [
            {
                "issue_id": "large_source_jump_seg_setup_to_seg_turn",
                "category": "transition",
                "severity": "minor",
                "evidence_sufficiency": "observed",
                "diagnosis_status": "CONFIRMED_STORY_DEFECT",
                "story_defect_confirmed": True,
                "segment_ids": ["seg_setup", "seg_turn"],
                "narrative_problem": "abrupt jump",
                "suggested_fix": "insert_bridge",
            }
        ],
        "protected_goal_segment_ids": [
            "seg_open_goal",
            "seg_turn",
            "seg_climax",
        ],
    }


class TestFirstLiveEvidenceGate(unittest.TestCase):
    def test_boolean_targeted_visual_rejected(self):
        led = build_first_live_window_ledger(
            source_sha="shaA",
            new_windows=[
                {
                    "source_pts_start": 0.5,
                    "source_pts_end": 1.5,
                    "targeted_visual_verified": True,
                    "first_live_status": "FIRST_LIVE_VERIFIED",
                }
            ],
        )
        self.assertEqual(led["aggregate_status"], "NOT_VERIFIED")
        self.assertEqual(led["windows"][0]["method"], "boolean_targeted_visual_rejected")

    def test_event_chain_still_negative(self):
        led = build_first_live_window_ledger(
            source_sha="shaA",
            new_windows=[
                {
                    "source_pts_start": 900.0,
                    "source_pts_end": 908.0,
                    "evidence_status": "SEARCH_EVENT_CHAIN_LIVE_VERIFIED",
                    "first_live_status": "NOT_VERIFIED",
                }
            ],
        )
        hs = compute_independent_hard_safety(
            hard_vetoes=[],
            goal_intact=True,
            render_rows_ok=True,
            candidate_mp4=Path("/tmp/missing_candidate.mp4"),
            extra={
                "has_new_footage": True,
                "first_live_ledger": led,
                "pts_ok": True,
                "source_provenance_ok": True,
                "require_candidate_mp4": True,
            },
        )
        self.assertEqual(hs["safety"], "UNKNOWN")

    def test_positive_local_source_pack(self):
        root = Path(tempfile.mkdtemp(prefix="p8_fl_pos_"))
        mp4 = _tiny_mp4(root / "source.mp4")
        sha = _sha256_file(mp4)
        # Use in-range PTS for 3s clip
        pack = build_local_first_live_evidence_pack(
            source_mp4=mp4,
            source_sha=sha,
            pts_start=0.4,
            pts_end=2.2,
            out_dir=root / "pack",
            segment_id="seg_bridge",
        )
        self.assertTrue(pack.get("ok"), pack)
        self.assertEqual(pack.get("status"), "FIRST_LIVE_VERIFIED")
        self.assertTrue(looks_like_content_hash(pack["frames"][0]["sha256"]))
        val = validate_first_live_evidence_record(
            pack, source_sha=sha, pts_start=0.4, pts_end=2.2
        )
        self.assertTrue(val.get("ok"), val)
        led = build_first_live_window_ledger(
            source_sha=sha,
            new_windows=[
                {
                    "source_pts_start": 0.4,
                    "source_pts_end": 2.2,
                    "segment_id": "seg_bridge",
                    "validated_evidence": pack,
                    "require_evidence_files": True,
                }
            ],
        )
        self.assertEqual(led["aggregate_status"], "FIRST_LIVE_VERIFIED")
        # Real revision requires existing candidate mp4
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
        self.assertEqual(hs["safety"], "PASS", hs)
        # Persist for ChatGPT audit
        (root / "POSITIVE_PROOF.json").write_text(
            json.dumps(
                {
                    "source_sha": sha,
                    "window": [0.4, 2.2],
                    "ledger": led,
                    "hard_safety": hs["safety"],
                    "manifest_digest": pack.get("manifest_digest"),
                    "frame_sha256": [f["sha256"] for f in pack["frames"]],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def test_edl_diff_detects_new_window(self):
        parent = _edl_baseline()
        cand = _edl_baseline() + [
            {
                "segment_id": "seg_bridge",
                "role": "buildup_bridge_action",
                "include_in_cut": True,
                "media_in": 896.0,
                "media_out": 908.0,
                "is_replay": False,
            }
        ]
        # insert between setup and turn for realism
        cand = [
            parent[0],
            parent[1],
            {
                "segment_id": "seg_bridge",
                "role": "buildup_bridge_action",
                "include_in_cut": True,
                "media_in": 896.0,
                "media_out": 908.0,
                "is_replay": False,
            },
            parent[2],
            parent[3],
        ]
        news = diff_new_source_windows(parent, cand, source_sha="shaX")
        self.assertEqual(len(news), 1)
        self.assertAlmostEqual(news[0]["source_pts_start"], 896.0)
        self.assertEqual(news[0]["origin"], "edl_diff")


class TestEvidenceTokenContentHashes(unittest.TestCase):
    def test_frame_id_not_observation_grade(self):
        tok = make_observation_evidence_token(
            source_sha="src",
            pts_start=1.0,
            pts_end=2.0,
            observation_id="v1:r1",
            frame_hashes=["baseline_a", "candidate_a"],
        )
        self.assertFalse(is_observation_grade_evidence_token(tok))
        self.assertTrue(str(tok).startswith("sha:"))

    def test_content_hash_is_observation_grade(self):
        tok = make_observation_evidence_token(
            source_sha="src",
            pts_start=1.0,
            pts_end=2.0,
            frame_hashes=["ab" * 32],
            manifest_digest="cd" * 32,
        )
        self.assertTrue(is_observation_grade_evidence_token(tok))
        # Unequal content hashes unlock; candidate_id does not
        prior = tok
        hit = should_penalize_candidate(
            [
                {
                    "action": "search_add",
                    "source_pts": [1.0, 2.0],
                    "failure_class": "UNCERTAIN_OR_UNVERIFIED",
                    "issue_signature": {"category": "transition", "anchor_segment_ids": ["s"]},
                    "evidence_token": prior,
                }
            ],
            issue_signature={"category": "transition", "anchor_segment_ids": ["s"]},
            action="search_add",
            source_pts=[1.0, 2.0],
            new_evidence_token="cand_x",
        )
        self.assertTrue(hit["suppress"])


class TestPairedFeedbackAblationSameBaseline(unittest.TestCase):
    def test_same_edl_with_vs_without_feedback(self):
        """Causal ablation: identical baseline EDL + events + diagnosis.

        After a failed/uncertain attempt, roll back to the SAME best EDL so A
        remains available. With feedback memory A is suppressed and B chosen;
        without feedback A remains top. Occupancy cannot explain the difference.
        """
        edl = _edl_baseline()  # identical for both arms — A still available
        diag = _diag()
        with tempfile.TemporaryDirectory() as td:
            ev = _events_ab(Path(td) / "events.json")
            no_fb = run_story_evidence_search(diagnosis=diag, edl=edl, match_json=ev)
            self.assertEqual(no_fb["verified_candidates"][0]["event_id"], "ev_cand_A")
            plan_no = plan_from_diagnosis(diag, offline=True, search_results=no_fb)
            win_no = plan_no["revision_intents"][0]["bound_source_window"]

            # Simulate round-1 uncertain attempt rolled back to best=v0 (same EDL).
            fb = {
                "records": [
                    {
                        "action": "search_add",
                        "source_pts": [896.0, 908.0],
                        "failure_class": "UNCERTAIN_OR_UNVERIFIED",
                        "issue_signature": {
                            "category": "transition",
                            "anchor_segment_ids": ["seg_setup", "seg_turn"],
                        },
                        "evidence_token": make_observation_evidence_token(
                            source_sha="src",
                            pts_start=896.0,
                            pts_end=908.0,
                            frame_hashes=["9" * 64],
                            manifest_digest="8" * 64,
                        ),
                    }
                ],
                "n_records": 1,
                "note": "rolled_back_to_best_edl_after_uncertain_round1",
            }
            with_fb = run_story_evidence_search(
                diagnosis=diag, edl=edl, match_json=ev, feedback_context=fb
            )
            filtered = [c["event_id"] for c in with_fb["feedback_filtered_candidates"]]
            kept = [c["event_id"] for c in with_fb["verified_candidates"]]
            self.assertIn("ev_cand_A", filtered)
            self.assertEqual(kept[0], "ev_cand_B")
            plan_fb = plan_from_diagnosis(
                diag, offline=True, search_results=with_fb, feedback_context=fb
            )
            win_fb = plan_fb["revision_intents"][0]["bound_source_window"]
            self.assertNotAlmostEqual(float(win_no["start"]), float(win_fb["start"]), delta=1.0)
            # A still present in pre-feedback pool under same EDL
            before = [c["event_id"] for c in with_fb.get("verified_candidates_before_feedback") or []]
            self.assertIn("ev_cand_A", before)
            proof = {
                "same_baseline_edl": True,
                "occupancy_confound_excluded": True,
                "no_feedback_top": no_fb["verified_candidates"][0]["event_id"],
                "no_feedback_window": win_no,
                "with_feedback_filtered": filtered,
                "with_feedback_top": kept[0],
                "with_feedback_window": win_fb,
                "rollback_note": "uncertain_round1_rolled_back_to_identical_best_edl",
            }
            Path(td, "PAIRED_ABLATION_PROOF.json").write_text(
                json.dumps(proof, indent=2) + "\n", encoding="utf-8"
            )
            self.assertEqual(proof["no_feedback_top"], "ev_cand_A")
            self.assertEqual(proof["with_feedback_top"], "ev_cand_B")


if __name__ == "__main__":
    unittest.main()
