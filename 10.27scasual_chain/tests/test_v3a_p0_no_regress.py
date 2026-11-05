"""Offline P0 no-regression tests for V3-A incremental edit guards (no paid API)."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent_v3.quality_audit import compare_edl_non_regression, evaluate
from story_video_agent_v3.self_revise_agent import (
    apply_candidate_revision,
    build_bound_segment_from_observations,
    decide_accept,
    find_duplicate_goal_cuts,
    important_segments_regressed,
    resolve_phase5_baseline,
    run_self_revise,
)

A_ROOT = Path("/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_A_uae_oman")
A_RAW = A_ROOT / "04_phase5"
A_POLISH = A_ROOT / "04_phase5_p1_polish"
A_BEST1 = A_ROOT / "v3a_cross_match_3round_20261104" / "best_candidate_edl.json"


def _obs(media_in: float, media_out: float, *, live_or_replay: str = "live") -> dict:
    mid = 0.5 * (media_in + media_out)
    return {
        "ok": True,
        "request_id": "tool_test",
        "window": {"start": media_in, "end": media_out},
        "allowed_windows": [{"start": media_in - 5, "end": media_out + 5}],
        "frames": [
            {"frame_id": "f0", "actual_media_sec": mid - 0.5},
            {"frame_id": "f1", "actual_media_sec": mid + 0.5},
        ],
        "vlm": {
            "observation_only": True,
            "observed_shot": True,
            "observed_net": True,
            "supports_bound_segment": True,
            "live_or_replay": live_or_replay,
            "candidate_goal_action_span": {"start": media_in, "end": media_out},
        },
    }


class BaselineResolutionTests(unittest.TestCase):
    def test_prefer_sibling_p1_polish(self):
        if not (A_POLISH / "candidate_edl.json").is_file():
            self.skipTest("A p1_polish missing")
        meta = resolve_phase5_baseline(A_RAW, prefer_p1_polish=True)
        self.assertTrue(meta["switched_to_p1_polish"])
        self.assertEqual(Path(meta["path"]).name, "04_phase5_p1_polish")
        self.assertNotEqual(meta["requested_edl_sha256"], meta["resolved_edl_sha256"])

    def test_disable_prefer_keeps_raw(self):
        meta = resolve_phase5_baseline(A_RAW, prefer_p1_polish=False)
        self.assertFalse(meta["switched_to_p1_polish"])
        self.assertEqual(Path(meta["path"]).resolve(), A_RAW.resolve())


class EditGuardTests(unittest.TestCase):
    def setUp(self):
        self.baseline = [
            {"segment_id": "seg_title_open", "role": "story_title", "include_in_cut": True},
            {
                "segment_id": "seg_opponent_opening_goal_action",
                "role": "opponent_opening_goal_action",
                "media_in": 1325.123,
                "media_out": 1347.123,
                "include_in_cut": True,
            },
            {
                "segment_id": "seg_equalizer_goal_action",
                "role": "equalizer_goal_action",
                "media_in": 6437.644,
                "media_out": 6459.644,
                "include_in_cut": True,
            },
        ]

    def test_B_search_add_rejects_duplicate_opening(self):
        intents = [{
            "intent_id": "i0",
            "action": "search_add",
            "role": "opponent_opening_goal_action_live",
            "anchor_id": "score_node:behind_start",
        }]
        edl, meta = apply_candidate_revision(
            self.baseline, intents, [_obs(1320.0, 1350.0)],
            trusted_windows_by_anchor={
                "score_node:behind_start": [{"start": 1300.0, "end": 1360.0}],
            },
        )
        active = [r for r in edl if r.get("include_in_cut", True) and "opening" in str(r.get("role"))]
        self.assertEqual(len(active), 1)
        self.assertTrue(any(
            x.get("reason") == "duplicate_role_or_window_already_present"
            for x in meta["rejected"]
        ))

    def test_C_unverified_replace_cannot_expand_good_goal(self):
        intents = [{
            "intent_id": "i0",
            "action": "replace",
            "role": "equalizer_goal_action",
            "target_segment_id": "seg_equalizer_goal_action",
            "anchor_id": "edl:seg_equalizer_goal_action",
        }]
        # Expanded window without verification
        edl, meta = apply_candidate_revision(
            self.baseline, intents, [_obs(6430.0, 6470.0)],
            trusted_windows_by_anchor={
                "edl:seg_equalizer_goal_action": [{"start": 6400.0, "end": 6500.0}],
            },
        )
        eq = next(r for r in edl if r["segment_id"] == "seg_equalizer_goal_action")
        self.assertTrue(eq.get("include_in_cut", True))
        self.assertAlmostEqual(eq["media_in"], 6437.644, places=2)
        self.assertTrue(any(
            x.get("reason") == "unverified_replace_of_existing_goal_window"
            for x in meta["rejected"]
        ))

    def test_D_replace_excludes_old_from_cut(self):
        # Defective baseline (marked replay) may be replaced when evidence-bound
        base = copy.deepcopy(self.baseline)
        base[1]["is_replay"] = True
        intents = [{
            "intent_id": "i0",
            "action": "replace",
            "role": "opponent_opening_goal_action",
            "target_segment_id": "seg_opponent_opening_goal_action",
            "anchor_id": "edl:seg_opponent_opening_goal_action",
        }]
        edl, meta = apply_candidate_revision(
            base, intents, [_obs(1325.0, 1347.0)],
            trusted_windows_by_anchor={
                "edl:seg_opponent_opening_goal_action": [{"start": 1300.0, "end": 1360.0}],
            },
        )
        self.assertTrue(meta["evidence_bound_count"] >= 1)
        old = next(r for r in edl if r["segment_id"] == "seg_opponent_opening_goal_action")
        # Either retired or upserted in place; if synonym sid used, old must be out
        if old.get("agent_replaced_by"):
            self.assertFalse(old.get("include_in_cut", True))
        active_opening = [
            r for r in edl
            if r.get("include_in_cut", True)
            and "opponent_opening_goal_action" in str(r.get("role") or "")
        ]
        self.assertEqual(len(active_opening), 1)

    def test_bound_segment_does_not_claim_non_replay(self):
        bound = build_bound_segment_from_observations(
            intent={"role": "go_ahead_goal_action", "anchor_id": "a"},
            observations=[_obs(100.0, 120.0)],
            trusted_windows=[{"start": 90.0, "end": 130.0}],
            score_anchor_sec=140.0,
        )
        self.assertTrue(bound.get("ok"))
        self.assertIsNone(bound["segment"].get("is_replay"))
        self.assertEqual(bound["segment"]["first_live_status"], "NOT_VERIFIED")

    def test_agent_bound_does_not_exempt_media_shift(self):
        base = copy.deepcopy(self.baseline)
        cand = copy.deepcopy(self.baseline)
        cand[1]["media_in"] = 1382.0
        cand[1]["media_out"] = 1412.0
        cand[1]["agent_bound"] = True
        cand[1]["first_live_status"] = "NOT_VERIFIED"
        regs = important_segments_regressed(base, cand)
        self.assertTrue(any("media_shifted" in r for r in regs))

    def test_decide_accept_rejects_duplicate_and_suspected_replay(self):
        base_edl = copy.deepcopy(self.baseline)
        cand = copy.deepcopy(self.baseline)
        cand.append({
            "segment_id": "seg_opponent_opening_goal_action_live",
            "role": "opponent_opening_goal_action_live",
            "media_in": 1325.123,
            "media_out": 1347.123,
            "include_in_cut": True,
            "agent_bound": True,
            "first_live_status": "NOT_VERIFIED",
        })
        self.assertTrue(find_duplicate_goal_cuts(cand))
        audit = {"hard_gate_findings": [], "dimensions": {
            "story_element_coverage": {"score": 100.0},
            "story_coherence": {"score": 100.0},
        }}
        decision = decide_accept(
            baseline_audit=audit,
            candidate_audit=audit,
            verifier={
                "ok": True,
                "ok_for_semantic_accept": True,
                "validated": {
                    "dimensions": {
                        "story_element_coverage": {
                            "status": "improved", "score": 100, "summary": "x",
                            "evidence_refs": ["t"],
                        },
                    },
                    "evidence_of_improvement": [{"claim": "added", "evidence_refs": ["t"]}],
                    "live_segment_assessments": [{
                        "segment_id": "seg_go_ahead_goal_action",
                        "live_status": "SUSPECTED_REPLAY",
                        "score": 30,
                    }],
                    "hard_vetoes": [],
                },
            },
            revision_meta={
                "applied": [{
                    "intent": "i0", "action": "search_add",
                    "status": "applied_evidence_bound",
                    "segment_id": "seg_opponent_opening_goal_action_live",
                }],
                "rejected": [],
            },
            baseline_edl=base_edl,
            candidate_edl=cand,
            semantic_verification_status="PASSED",
        )
        self.assertFalse(decision["accept"])


class OfflineLoopTests(unittest.TestCase):
    def test_A_no_revision_preserves_polish_baseline(self):
        if not (A_POLISH / "candidate_edl.json").is_file():
            self.skipTest("A p1_polish missing")
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out"
            summary = run_self_revise(
                phase5_dir=A_RAW,
                out_dir=out,
                enable_real_api=False,
                i_approve_budget=False,
                allow_degraded_offline=True,
                prefer_p1_polish=True,
                max_rounds=1,
                skip_vlm=True,
                stop_on_quality_threshold=False,
            )
            self.assertTrue(summary["workflow_completed"])
            br = summary.get("baseline_resolution") or {}
            self.assertTrue(br.get("switched_to_p1_polish"))
            best = json.loads((out / "best_candidate_edl.json").read_text())
            polish = json.loads((A_POLISH / "candidate_edl.json").read_text())
            self.assertEqual(len(best), len(polish))
            for a, b in zip(best, polish):
                self.assertEqual(a.get("segment_id"), b.get("segment_id"))
                self.assertEqual(a.get("media_in"), b.get("media_in"))
                self.assertEqual(a.get("media_out"), b.get("media_out"))

    def test_E_timeout_style_degraded_keeps_baseline(self):
        """Degraded offline with no planner intents → best EDL equals resolved baseline."""
        if not (A_POLISH / "candidate_edl.json").is_file():
            self.skipTest("A p1_polish missing")
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out"
            summary = run_self_revise(
                phase5_dir=A_RAW,
                out_dir=out,
                enable_real_api=False,
                i_approve_budget=False,
                allow_degraded_offline=True,
                prefer_p1_polish=True,
                max_rounds=2,
                skip_vlm=True,
                stop_on_quality_threshold=False,
            )
            self.assertFalse(summary.get("accepted_revision") or summary.get("accepted_any_revision"))
            self.assertEqual(summary.get("best_round"), 0)
            polish_sha = __import__("hashlib").sha256(
                (A_POLISH / "candidate_edl.json").read_bytes()
            ).hexdigest()
            best_sha = __import__("hashlib").sha256(
                (out / "best_candidate_edl.json").read_bytes()
            ).hexdigest()
            self.assertEqual(polish_sha, best_sha)

    def test_F_missing_opening_search_add_still_allowed(self):
        """When opening is absent, search_add may still bind (Agent not locked)."""
        base = [
            {"segment_id": "seg_title_open", "role": "story_title", "include_in_cut": True},
            {
                "segment_id": "seg_setup_deficit",
                "role": "deficit_scoreboard_anchor",
                "media_in": 1409.0,
                "media_out": 1413.0,
                "include_in_cut": True,
            },
        ]
        intents = [{
            "intent_id": "i0",
            "action": "search_add",
            "role": "opponent_opening_goal_action",
            "anchor_id": "score_node:behind_start",
        }]
        edl, meta = apply_candidate_revision(
            base, intents, [_obs(1325.0, 1347.0)],
            trusted_windows_by_anchor={
                "score_node:behind_start": [{"start": 1300.0, "end": 1360.0}],
            },
            score_anchor_by_anchor_id={"score_node:behind_start": 1410.0},
        )
        self.assertGreaterEqual(meta["evidence_bound_count"], 1)
        self.assertTrue(any(
            r.get("role") == "opponent_opening_goal_action" and r.get("include_in_cut", True)
            for r in edl
        ))

    def test_quality_audit_flags_best1_style_duplicate(self):
        if not A_BEST1.is_file() or not (A_POLISH / "candidate_edl.json").is_file():
            self.skipTest("artifacts missing")
        story = json.loads((A_POLISH / "t01_story.json").read_text())
        plan = json.loads((A_POLISH / "story_plan.json").read_text())
        bad = json.loads(A_BEST1.read_text())
        polish = json.loads((A_POLISH / "candidate_edl.json").read_text())
        audit = evaluate(story, plan, bad, baseline_edl=polish)
        kinds = {i["kind"] for i in audit["hard_gate_findings"]}
        self.assertTrue(
            "duplicate_canonical_goal_role" in kinds
            or "overlapping_goal_windows" in kinds
            or "baseline_goal_media_regressed" in kinds
        )
        # Polish vs itself: no regression issues
        clean = evaluate(story, plan, polish, baseline_edl=polish)
        reg_kinds = {
            i["kind"] for i in clean["diagnostic_issues"]
            if i["kind"] in (
                "duplicate_canonical_goal_role",
                "overlapping_goal_windows",
                "baseline_goal_media_regressed",
            )
        }
        self.assertFalse(reg_kinds)


if __name__ == "__main__":
    unittest.main()
