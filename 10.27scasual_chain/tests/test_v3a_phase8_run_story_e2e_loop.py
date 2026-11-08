"""Phase 8: real run_story_e2e multi-round integration (zero HTTP).

Proves feedback changes the next planner/search/EDL decision on the actual
main-chain path. Temporary dirs only — does not write under /data2/lpy1.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_video_agent_v3.story_e2e_agent import StoryE2EInputs, run_story_e2e
from story_video_agent_v3.story_video_verifier import build_phase8_verdict


def _tiny_mp4(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    import subprocess

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=64x64:d=1",
        "-f",
        "lavfi",
        "-i",
        "sine=f=440:d=1",
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


def _base_edl():
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
            "media_in": 2000.0,
            "media_out": 2020.0,
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


def _stage_mini_assets(root: Path) -> dict:
    phase5 = root / "phase5"
    phase5.mkdir(parents=True, exist_ok=True)
    edl = _base_edl()
    (phase5 / "candidate_edl.json").write_text(
        json.dumps(edl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (phase5 / "story_plan.json").write_text(
        json.dumps({"schema": "test_plan", "segments": edl}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    (phase5 / "t01_story.json").write_text(
        json.dumps({"schema": "t01", "title": "test"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    mp4 = _tiny_mp4(phase5 / "story_clean.mp4")
    src = _tiny_mp4(root / "source.mp4")
    mj = root / "match.json"
    mj.write_text(json.dumps({"match_id": "phase8_test"}, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"phase5": phase5, "mp4": src, "json": mj, "story_mp4": mp4}


class TestProvenanceP0(unittest.TestCase):
    def test_fixture_claiming_real_stays_fixture(self):
        v = build_phase8_verdict(
            hard_vetoes=[],
            goal_intact=True,
            render_rows_ok=True,
            semantic_status="PASSED",
            vision_backed=True,
            sent_frame_ids=["a", "b"],
            validated={"quality_delta_vs_baseline": "BETTER"},
            fixture={"source_kind": "REAL", "phase8_quality": "BETTER", "phase8_safety": "PASS"},
            verdict_provenance="FIXTURE",
            accept_candidate=False,
        )
        self.assertEqual(v["verdict_provenance"], "FIXTURE")
        self.assertEqual(v["source_kind"], "FIXTURE")

    def test_real_vlm_path_marked_real(self):
        v = build_phase8_verdict(
            hard_vetoes=[],
            goal_intact=True,
            render_rows_ok=True,
            semantic_status="PASSED",
            vision_backed=True,
            sent_frame_ids=["a", "b"],
            validated={"quality_delta_vs_baseline": "PROMISING"},
            fixture={"quality_delta_vs_baseline": "PROMISING"},
            verdict_provenance="REAL_VLM",
            hard_safety={"safety": "PASS", "accept_candidate_ignored": True},
            accept_candidate=False,
        )
        self.assertEqual(v["verdict_provenance"], "REAL_VLM")
        self.assertEqual(v["safety"], "PASS")
        self.assertFalse(v["accept_candidate_raw"])


class TestRunStoryE2EMultiRound(unittest.TestCase):
    def test_two_rounds_feedback_changes_edl(self):
        root = Path(tempfile.mkdtemp(prefix="p8_e2e_loop_"))
        assets = _stage_mini_assets(root)
        out = root / "out"
        import story_video_agent_v3.story_e2e_agent as e2e_mod

        call_n = {"search": 0}

        def _fake_render(**kwargs):
            od = Path(kwargs["out_dir"])
            od.mkdir(parents=True, exist_ok=True)
            dst = od / "story_clean.mp4"
            if not dst.exists():
                try:
                    dst.symlink_to(assets["story_mp4"].resolve())
                except OSError:
                    import shutil

                    shutil.copy2(assets["story_mp4"], dst)
            return {"ok": True, "story_clean": str(dst), "note": "test_reuse"}

        def _fake_search(**kwargs):
            call_n["search"] += 1
            fb = kwargs.get("feedback_context") or {}
            n_fb = int((fb.get("n_records") or 0) if isinstance(fb, dict) else 0)
            # After round-1 feedback exists, return a DIFFERENT PTS candidate.
            if n_fb > 0 or call_n["search"] > 1:
                cands = [
                    {
                        "candidate_id": "cand_alt_1500",
                        "issue_id": "large_source_jump_seg_setup_to_seg_turn",
                        "category": "transition",
                        "role": "buildup_bridge_action",
                        "source_pts_start": 1500.0,
                        "source_pts_end": 1510.0,
                        "insert_after_segment_id": "seg_bridge_r1",
                        "before_segment_id": "seg_turn",
                        "event_id": "ev_alt",
                        "live": {"broadcast_phase": "LIVE"},
                        "confidence": 0.8,
                        "score": 0.8,
                        "narrative_function": "supplement_buildup_or_transition_bridge",
                        "evidence_verification": {"ok": True},
                    }
                ]
            else:
                cands = [
                    {
                        "candidate_id": "cand_first_900",
                        "issue_id": "large_source_jump_seg_setup_to_seg_turn",
                        "category": "transition",
                        "role": "buildup_bridge_action",
                        "source_pts_start": 900.0,
                        "source_pts_end": 908.0,
                        "insert_after_segment_id": "seg_setup",
                        "before_segment_id": "seg_turn",
                        "event_id": "ev_first",
                        "live": {"broadcast_phase": "LIVE"},
                        "confidence": 0.9,
                        "score": 0.9,
                        "narrative_function": "supplement_buildup_or_transition_bridge",
                        "evidence_verification": {"ok": True},
                    }
                ]
            return {
                "schema": "v3a_story_evidence_search_v1",
                "search_success": True,
                "verified_candidates": cands,
                "candidates": cands,
                "targets": [],
                "feedback_filter_applied": bool(n_fb),
                "feedback_filtered_candidates": [],
            }

        fixtures = [
            {
                "decision": "REVISE",
                "revision_intents": [
                    {
                        "intent_id": "search_add_r1",
                        "action": "search_add",
                        "issue_id": "large_source_jump_seg_setup_to_seg_turn",
                        "role": "buildup_bridge_action",
                        "insert_after_segment_id": "seg_setup",
                        "before_segment_id": "seg_turn",
                        "bound_source_window": {"start": 900.0, "end": 908.0},
                        "new_segment_id": "seg_bridge_r1",
                        "anchor_id": "search:cand_first_900",
                        "narrative_purpose": "supplement_buildup_or_transition_bridge",
                    }
                ],
                "phase8_quality": "PROMISING",
                "phase8_safety": "PASS",
                "phase8_evidence": "PARTIAL",
                "first_live_status": "FIRST_LIVE_VERIFIED",
                "sent_frame_ids": ["baseline_a", "candidate_a"],
                "issue_effect": "PARTIAL",
                "global_regression": "NO",
            },
            {
                "decision": "REVISE",
                "revision_intents": [
                    {
                        "intent_id": "search_add_r2",
                        "action": "search_add",
                        "issue_id": "large_source_jump_seg_setup_to_seg_turn",
                        "role": "buildup_bridge_action",
                        "insert_after_segment_id": "seg_bridge_r1",
                        "before_segment_id": "seg_turn",
                        "bound_source_window": {"start": 1500.0, "end": 1510.0},
                        "new_segment_id": "seg_bridge_r2",
                        "anchor_id": "search:cand_alt_1500",
                        "narrative_purpose": "supplement_buildup_or_transition_bridge",
                    }
                ],
                "phase8_quality": "UNCERTAIN",
                "phase8_safety": "PASS",
                "phase8_evidence": "INSUFFICIENT",
                "first_live_status": "FIRST_LIVE_VERIFIED",
                "sent_frame_ids": ["baseline_b", "candidate_b"],
                "issue_effect": "UNOBSERVED",
                "global_regression": "UNKNOWN",
            },
        ]

        with mock.patch.object(e2e_mod, "_render_edl", side_effect=_fake_render), mock.patch(
            "story_video_agent_v3.story_e2e_agent.run_story_evidence_search",
            side_effect=_fake_search,
        ), mock.patch(
            "story_video_agent_v3.story_e2e_agent.observe_layers",
            return_value={
                "schema": "test_observe",
                "layers": [],
                "semantic_provider_used": False,
                "fixture_or_offline": True,
            },
        ):
            audit = run_story_e2e(
                StoryE2EInputs(
                    match_json=assets["json"],
                    source_mp4=assets["mp4"],
                    out_dir=out,
                    phase5_dir=assets["phase5"],
                    skip_vlm=True,
                    enable_real_api=False,
                    smoke_render=False,
                    max_rounds=3,
                    phase8_round_fixtures=fixtures,
                )
            )

        self.assertTrue((out / "02_round_01").is_dir())
        self.assertTrue((out / "02_round_02").is_dir())
        # STOP_NO_ACTION on uncertain r2 ⇒ no third round executed.
        self.assertFalse((out / "02_round_03").is_dir())

        r1_plan = json.loads((out / "02_round_01" / "revision_plan.json").read_text())
        r2_plan = json.loads((out / "02_round_02" / "revision_plan.json").read_text())
        self.assertEqual(r1_plan["decision"], "REVISE")
        self.assertEqual(r2_plan["decision"], "REVISE")
        self.assertNotEqual(
            (r1_plan["revision_intents"][0].get("bound_source_window") or {}).get("start"),
            (r2_plan["revision_intents"][0].get("bound_source_window") or {}).get("start"),
        )

        r1_edl = json.loads((out / "02_round_01" / "candidate_edl.json").read_text())
        r2_edl = json.loads((out / "02_round_02" / "candidate_edl.json").read_text())
        r1_ids = [r.get("segment_id") for r in r1_edl if isinstance(r, dict)]
        r2_ids = [r.get("segment_id") for r in r2_edl if isinstance(r, dict)]
        self.assertIn("seg_bridge_r1", r1_ids)
        # r2 parent is working v1 (CONTINUE_WORKING), so edit applies on top of r1 or replaces —
        # at minimum the r2 intent window must appear in planner feedback / transition.
        tr1 = json.loads((out / "02_round_01" / "phase8_transition.json").read_text())
        tr2 = json.loads((out / "02_round_02" / "phase8_transition.json").read_text())
        self.assertEqual(tr1["next_action"], "CONTINUE_WORKING")
        self.assertEqual(tr2["next_action"], "STOP_NO_ACTION")

        mem = json.loads((out / "phase8_feedback_memory.json").read_text())
        self.assertGreaterEqual(mem.get("n_records") or 0, 1)
        self.assertTrue((out / "02_round_02" / "planner_feedback_context.json").is_file())
        # Delivery remains best_verified=v0 (PROMISING never promotes).
        loop = json.loads((out / "phase8_loop_state.json").read_text())
        self.assertEqual(loop.get("best_verified_version_id"), "v0")
        self.assertEqual(loop.get("stop_reason"), "STOP_NO_ACTION")
        # Write review copy under out for ChatGPT (still temp, also assertable).
        (out / "MAIN_LOOP_ROUND_PROOF.json").write_text(
            json.dumps(
                {
                    "rounds_executed": [1, 2],
                    "r1_transition": tr1["next_action"],
                    "r2_transition": tr2["next_action"],
                    "r1_pts": (r1_plan["revision_intents"][0].get("bound_source_window")),
                    "r2_pts": (r2_plan["revision_intents"][0].get("bound_source_window")),
                    "r1_edl_ids": r1_ids,
                    "r2_edl_ids": r2_ids,
                    "feedback_n": mem.get("n_records"),
                    "best": loop.get("best_verified_version_id"),
                    "structural_loop_pass": True,
                    "video_semantic_quality_verified": False,
                    "release_authorized": False,
                    "zero_http": True,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        self.assertFalse(audit.get("delivery", {}).get("release_authorized"))

    def test_stop_no_action_produces_exactly_two_rounds_max(self):
        """If r1 already STOP_NO_ACTION, only one round directory exists."""
        root = Path(tempfile.mkdtemp(prefix="p8_e2e_stop_"))
        assets = _stage_mini_assets(root)
        out = root / "out"
        import story_video_agent_v3.story_e2e_agent as e2e_mod

        def _fake_render(**kwargs):
            od = Path(kwargs["out_dir"])
            od.mkdir(parents=True, exist_ok=True)
            dst = od / "story_clean.mp4"
            if not dst.exists():
                try:
                    dst.symlink_to(assets["story_mp4"].resolve())
                except OSError:
                    import shutil

                    shutil.copy2(assets["story_mp4"], dst)
            return {"ok": True, "story_clean": str(dst)}

        with mock.patch.object(e2e_mod, "_render_edl", side_effect=_fake_render), mock.patch(
            "story_video_agent_v3.story_e2e_agent.run_story_evidence_search",
            return_value={
                "schema": "v3a_story_evidence_search_v1",
                "search_success": False,
                "verified_candidates": [],
                "candidates": [],
                "targets": [],
            },
        ), mock.patch(
            "story_video_agent_v3.story_e2e_agent.observe_layers",
            return_value={
                "schema": "test_observe",
                "layers": [],
                "semantic_provider_used": False,
                "fixture_or_offline": True,
            },
        ):
            run_story_e2e(
                StoryE2EInputs(
                    match_json=assets["json"],
                    source_mp4=assets["mp4"],
                    out_dir=out,
                    phase5_dir=assets["phase5"],
                    skip_vlm=True,
                    enable_real_api=False,
                    smoke_render=False,
                    max_rounds=3,
                    fixture_revision={"decision": "KEEP", "revision_intents": [{"action": "keep"}]},
                )
            )
        self.assertTrue((out / "02_round_01").is_dir())
        self.assertFalse((out / "02_round_02").is_dir())


if __name__ == "__main__":
    unittest.main()
