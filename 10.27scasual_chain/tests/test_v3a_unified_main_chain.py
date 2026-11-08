"""Phase 4.2: unified story E2E main-chain contracts (zero paid HTTP).

Proves Critic→Planner→EDL apply→PTS safety→Verifier retain/accept wiring.
Does NOT claim fixture ACCEPT as authentic story-quality IMPROVED.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_video_agent_v3.self_revise_agent import apply_candidate_revision
from story_video_agent_v3.story_edl_safety import (
    check_source_pts_monotonic,
    classify_revision_status,
)
from story_video_agent_v3.story_e2e_agent import (
    UNIFIED_CHAIN_ID,
    StoryE2EInputs,
    run_story_e2e,
)
from story_video_agent_v3.story_e2e_cli import build_parser, main as e2e_cli_main
from story_video_agent_v3.story_revision_planner import plan_from_diagnosis
from story_video_agent_v3.global_story_critic import structural_diagnosis


def _tiny_mp4(path: Path) -> Path:
    """Write a minimal but ffprobe-readable H264+AAC MP4 via ffmpeg if available."""
    path.parent.mkdir(parents=True, exist_ok=True)
    import subprocess

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1",
        "-f", "lavfi", "-i", "sine=f=440:d=1",
        "-c:v", "libx264", "-c:a", "aac", "-shortest",
        str(path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not path.is_file():
        raise unittest.SkipTest(f"ffmpeg tiny mp4 failed: {r.stderr[-200:]}")
    return path


def _bridge_edl():
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
        {
            "segment_id": "seg_sb",
            "role": "go_ahead_scoreboard_anchor",
            "include_in_cut": True,
            "media_in": 3100.0,
            "media_out": 3104.0,
            "is_replay": False,
        },
    ]


class TestEdlPtsSafety(unittest.TestCase):
    def test_monotonic_detects_order_break(self):
        edl = _bridge_edl()
        edl.insert(
            -1,
            {
                "segment_id": "seg_ending_bad",
                "role": "ending_closure_action",
                "include_in_cut": True,
                "media_in": 3120.0,
                "media_out": 3130.0,
                "is_replay": False,
            },
        )
        # ending after climax but after scoreboard PTS → break vs scoreboard if placed before it
        # Rebuild: climax, ending(3120), scoreboard(3100)
        edl = [
            _bridge_edl()[0],
            _bridge_edl()[3],
            {
                "segment_id": "seg_ending_bad",
                "role": "ending_closure_action",
                "include_in_cut": True,
                "media_in": 3120.0,
                "media_out": 3130.0,
            },
            _bridge_edl()[4],
        ]
        gate = check_source_pts_monotonic(edl)
        self.assertFalse(gate["ok"])
        self.assertTrue(gate["breaks"])

    def test_apply_rejects_illegal_pts_before_render(self):
        edl = _bridge_edl()
        intents = [
            {
                "intent_id": "bad_ending",
                "action": "search_add",
                "role": "ending_closure_action",
                "insert_after_segment_id": "seg_climax",
                "before_segment_id": "seg_sb",
                "bound_source_window": {"start": 3110.0, "end": 3120.0},
                "new_segment_id": "seg_ending_bad",
                "event_ids": ["ev_x"],
            }
        ]
        out, report = apply_candidate_revision(edl, intents, observations=[])
        rejected = report.get("rejected") or []
        self.assertTrue(
            any(r.get("reason") == "search_add_breaks_source_pts_order_vs_next" for r in rejected),
            rejected,
        )
        self.assertTrue(check_source_pts_monotonic(out)["ok"])

    def test_status_buckets_distinguish_applied_verified_improved(self):
        s = classify_revision_status(
            edl_changed=True,
            applied_bound=True,
            candidate_rendered=True,
            candidate_accepted=False,
            vision_backed=False,
            semantic_passed=False,
            quality_delta=None,
            safety_ok=True,
        )
        self.assertTrue(s["APPLIED"])
        self.assertFalse(s["VERIFIED"])
        self.assertFalse(s["IMPROVED"])
        s2 = classify_revision_status(
            edl_changed=True,
            applied_bound=True,
            candidate_rendered=True,
            candidate_accepted=True,
            vision_backed=True,
            semantic_passed=True,
            quality_delta="improved",
            safety_ok=True,
        )
        self.assertTrue(s2["VERIFIED"])
        self.assertTrue(s2["IMPROVED"])


class TestCriticPlannerHandoff(unittest.TestCase):
    def test_critic_issues_reach_planner_intents(self):
        edl = _bridge_edl()
        # Controlled diagnosis (avoid input_integrity blockers from missing paths).
        diag = {
            "schema": "v3a_story_diagnosis_v1",
            "story_diagnosis_valid": True,
            "issues": [
                {
                    "issue_id": "large_source_jump_seg_setup_to_seg_turn",
                    "category": "transition",
                    "severity": "minor",
                    "evidence_sufficiency": "needs_video_verify",
                    "segment_ids": ["seg_setup", "seg_turn"],
                    "story_time_range": [0.0, 1.0],
                    "observation": "gap",
                    "narrative_problem": "jump",
                    "suggested_fix": "verify_transition_or_insert_bridge",
                }
            ],
            "protected_goal_segment_ids": [
                "seg_open_goal",
                "seg_turn",
                "seg_climax",
            ],
        }
        search = {
            "search_success": True,
            "verified_candidates": [
                {
                    "candidate_id": "cand_bridge",
                    "issue_id": (diag["issues"][0].get("issue_id")),
                    "role": "buildup_bridge_action",
                    "source_pts_start": 900.0,
                    "source_pts_end": 908.0,
                    "insert_after_segment_id": "seg_setup",
                    "before_segment_id": "seg_turn",
                    "event_id": "ev_bridge",
                    "live": {"broadcast_phase": "LIVE"},
                    "confidence": 0.8,
                    "risks": [],
                    "narrative_function": "supplement_buildup_or_transition_bridge",
                    "search_window": {"lo": 206.0, "hi": 1999.0, "kind": "bridge_between_cuts"},
                }
            ],
        }
        plan = plan_from_diagnosis(diag, offline=True, search_results=search)
        self.assertEqual(plan["decision"], "REVISE")
        issue_ids = {i.get("issue_id") for i in plan["revision_intents"]}
        self.assertIn(diag["issues"][0]["issue_id"], issue_ids)
        out, report = apply_candidate_revision(
            edl, plan["revision_intents"], observations=[]
        )
        applied = [
            a for a in (report.get("applied") or [])
            if a.get("status") == "applied_evidence_bound"
        ]
        self.assertTrue(applied)
        self.assertNotEqual(out, edl)
        self.assertTrue(check_source_pts_monotonic(out)["ok"])


class TestUnifiedE2EIntegration(unittest.TestCase):
    def _phase5_or_skip(self) -> dict:
        phase5 = Path(
            os.environ.get(
                "V3A_MATCH_A_PHASE5",
                "/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_A_uae_oman/"
                "fresh_e2e_A_real_20261105_183136/01_to_04_fresh_v3r/04_phase5",
            )
        )
        mp4 = Path(
            os.environ.get(
                "V3A_MATCH_A_MP4",
                "/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4",
            )
        )
        mj = Path(
            os.environ.get(
                "V3A_MATCH_A_JSON",
                "/data2/lpy1/causal-chain2/causal_chain/examples/交付_out/"
                "10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语.json",
            )
        )
        if not phase5.is_dir() or not mp4.is_file() or not mj.is_file():
            self.skipTest("A phase5/source assets unavailable")
        return {"phase5": phase5, "mp4": mp4, "json": mj}

    def test_cli_enters_unified_main_chain(self):
        assets = self._phase5_or_skip()
        out_root = Path("/data2/lpy1/_story_va_outputs/v3/plan2")
        out = Path(tempfile.mkdtemp(prefix="unified_cli_", dir=str(out_root)))
        # Patch run to avoid smoke/candidate render cost: still exercises chain.
        argv = [
            "--match-json", str(assets["json"]),
            "--source-mp4", str(assets["mp4"]),
            "--phase5-dir", str(assets["phase5"]),
            "--out-dir", str(out),
            "--offline",
            "--no-smoke-render",
            "--max-rounds", "1",
        ]
        # Force skip candidate render by monkeypatching _render_edl if REVISE would render.
        import story_video_agent_v3.story_e2e_agent as e2e_mod

        real_render = e2e_mod._render_edl

        def _no_render(**kwargs):
            # Still create a placeholder so gates can be inspected without full ffmpeg.
            od = Path(kwargs["out_dir"])
            od.mkdir(parents=True, exist_ok=True)
            # Reuse baseline mp4 via symlink to avoid re-encode.
            src = assets["phase5"] / "story_clean.mp4"
            dst = od / "story_clean.mp4"
            if src.is_file() and not dst.exists():
                try:
                    dst.symlink_to(src.resolve())
                except OSError:
                    pass
            return {"ok": True, "story_clean": str(dst), "note": "test_reuse_no_reencode"}

        with mock.patch.object(e2e_mod, "_render_edl", side_effect=_no_render):
            rc = e2e_cli_main(argv)
        self.assertEqual(rc, 0)
        audit = json.loads((out / "story_e2e_audit.json").read_text(encoding="utf-8"))
        umc = audit.get("unified_main_chain") or {}
        self.assertEqual(umc.get("id"), UNIFIED_CHAIN_ID)
        self.assertEqual(umc.get("entry"), "run_story_e2e")
        self.assertTrue(umc.get("does_not_call_run_self_revise"))
        self.assertIn("revision_status_totals", audit)
        # Critic artifacts present
        self.assertTrue((out / "02_round_01" / "story_diagnosis.json").is_file())
        self.assertTrue((out / "02_round_01" / "revision_plan.json").is_file())
        self.assertTrue((out / "02_round_01" / "edl_pts_safety.json").is_file())
        # Formal final exists; if verifier refused, final should match baseline delivery path
        final = out / "99_final" / "story_final.mp4"
        self.assertTrue(final.exists())
        gates = audit["status_gates"]
        self.assertTrue(gates["workflow_completed"])
        self.assertFalse(gates["release_authorized"])

    def test_verifier_reject_keeps_baseline_final(self):
        assets = self._phase5_or_skip()
        out_root = Path("/data2/lpy1/_story_va_outputs/v3/plan2")
        out = Path(tempfile.mkdtemp(prefix="unified_retain_", dir=str(out_root)))
        import story_video_agent_v3.story_e2e_agent as e2e_mod

        def _no_render(**kwargs):
            od = Path(kwargs["out_dir"])
            od.mkdir(parents=True, exist_ok=True)
            src = assets["phase5"] / "story_clean.mp4"
            dst = od / "story_clean.mp4"
            if src.is_file() and not dst.exists():
                try:
                    dst.symlink_to(src.resolve())
                except OSError:
                    pass
            return {"ok": True, "story_clean": str(dst)}

        with mock.patch.object(e2e_mod, "_render_edl", side_effect=_no_render):
            audit = run_story_e2e(
                StoryE2EInputs(
                    match_json=assets["json"],
                    source_mp4=assets["mp4"],
                    out_dir=out,
                    phase5_dir=assets["phase5"],
                    skip_vlm=True,
                    enable_real_api=False,
                    smoke_render=False,
                    max_rounds=1,
                )
            )
        self.assertTrue(audit.get("ok") or audit.get("status_gates", {}).get("workflow_completed"))
        rounds = audit.get("rounds") or []
        self.assertTrue(rounds)
        # Offline verifier cannot accept → retain baseline
        last = rounds[-1]
        self.assertFalse(last.get("accepted", True))
        self.assertTrue(last.get("retain_baseline") or not last.get("accepted"))
        final_edl = json.loads((out / "99_final" / "final_edl.json").read_text(encoding="utf-8"))
        base_edl = json.loads((out / "01_initial_story" / "candidate_edl.json").read_text(encoding="utf-8"))
        # When not accepted, final EDL equals baseline initial (or last accepted=baseline)
        if not (audit.get("last_verifier") or {}).get("candidate_accepted"):
            self.assertEqual(
                [r.get("segment_id") for r in final_edl if isinstance(r, dict)],
                [r.get("segment_id") for r in base_edl if isinstance(r, dict)],
            )

    def test_fixture_accept_gate_wiring_not_real_improved(self):
        """ACCEPT path can be exercised with fixture vision; IMPROVED stays false."""
        assets = self._phase5_or_skip()
        out_root = Path("/data2/lpy1/_story_va_outputs/v3/plan2")
        out = Path(tempfile.mkdtemp(prefix="unified_fixture_accept_", dir=str(out_root)))
        import story_video_agent_v3.story_e2e_agent as e2e_mod

        def _no_render(**kwargs):
            od = Path(kwargs["out_dir"])
            od.mkdir(parents=True, exist_ok=True)
            src = assets["phase5"] / "story_clean.mp4"
            dst = od / "story_clean.mp4"
            if src.is_file() and not dst.exists():
                try:
                    dst.symlink_to(src.resolve())
                except OSError:
                    pass
            return {"ok": True, "story_clean": str(dst)}

        fixture_v = {
            "sent_frame_ids": ["baseline_f0", "candidate_f0"],
            "quality_delta_vs_baseline": "improved",
            "accept_candidate": True,
            "dimensions": {
                "story_coherence": {
                    "status": "improved",
                    "evidence_refs": [{"frame_id": "baseline_f0"}, {"frame_id": "candidate_f0"}],
                }
            },
            "hard_vetoes": [],
        }
        # Also need revision that changes EDL — use fixture revision with empty intents
        # and rely on search; if no change, accept won't update best. Force a safe intent.
        fixture_rev = {
            "decision": "REVISE",
            "revision_intents": [
                {
                    "intent_id": "fixture_bridge",
                    "action": "search_add",
                    "role": "buildup_bridge_action",
                    "issue_id": "fixture_issue",
                    "insert_after_segment_id": "seg_setup_deficit",
                    "before_segment_id": "seg_buildup_event_000472",
                    "bound_source_window": {"start": 3504.14, "end": 3515.83},
                    "new_segment_id": "seg_buildup_bridge_action_fixture",
                    "event_ids": ["event_000417"],
                    "narrative_purpose": "supplement_buildup_or_transition_bridge",
                }
            ],
        }
        with mock.patch.object(e2e_mod, "_render_edl", side_effect=_no_render):
            audit = run_story_e2e(
                StoryE2EInputs(
                    match_json=assets["json"],
                    source_mp4=assets["mp4"],
                    out_dir=out,
                    phase5_dir=assets["phase5"],
                    skip_vlm=True,
                    enable_real_api=False,
                    smoke_render=False,
                    max_rounds=1,
                    fixture_revision=fixture_rev,
                    fixture_verifier=fixture_v,
                )
            )
        totals = audit.get("revision_status_totals") or {}
        # Must not advertise authentic IMPROVED from fixture.
        self.assertEqual(int(totals.get("IMPROVED") or 0), 0)
        rs_path = out / "02_round_01" / "revision_status.json"
        if rs_path.is_file():
            rs = json.loads(rs_path.read_text(encoding="utf-8"))
            self.assertFalse(rs.get("IMPROVED"))
            if rs.get("candidate_accepted"):
                self.assertIn("synthetic_gate_wiring_not_real_quality", str(rs.get("fixture_quality_disclaimer") or ""))


class TestCliParserUnified(unittest.TestCase):
    def test_parser_exposes_story_e2e_entry(self):
        p = build_parser()
        ns = p.parse_args(
            [
                "--match-json", "/tmp/x.json",
                "--source-mp4", "/tmp/x.mp4",
                "--out-dir", "/tmp/out",
                "--offline",
            ]
        )
        self.assertTrue(ns.offline)


if __name__ == "__main__":
    unittest.main()
