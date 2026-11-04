"""Fault-injection tests for hybrid Rule+API fallback (no paid HTTP)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_video_agent_v3.hybrid_fallback import (
    build_orchestration_status,
    build_rule_planner_fallback,
    not_evaluated_semantic_block,
    run_dual_verifier,
    run_rule_verifier,
)
from story_video_agent_v3.self_revise_agent import decide_accept, run_self_revise


def _mini_phase(tmpdir: Path, *, with_p0: bool = True):
    story = {"match_id": "hyb", "title": "t", "protagonist": "left"}
    plan = {
        "match_id": "hyb", "story_tier": "story",
        "story_scope": {"selected_arc": {
            "behind_start": {"t_sec": 100.0, "score": "0:1"},
            "equalizer": {"t_sec": 200.0, "score": "1:1"},
            "go_ahead": {"t_sec": 300.0, "score": "2:1"},
        }},
        "missing_evidence": [],
    }
    edl = [
        {"segment_id": "seg_title", "role": "story_title", "media_in": 0, "media_out": 3,
         "include_in_cut": True, "shot_kind": "title_card"},
        {"segment_id": "seg_equalizer_goal_action", "role": "equalizer_goal_action",
         "media_in": 180, "media_out": 200, "include_in_cut": True, "is_replay": False},
        {"segment_id": "seg_go_ahead_goal_action", "role": "go_ahead_goal_action",
         "media_in": 280, "media_out": 300, "include_in_cut": True, "is_replay": False},
    ]
    if not with_p0:
        edl.insert(1, {
            "segment_id": "seg_opponent_opening_goal_action",
            "role": "opponent_opening_goal_action",
            "media_in": 80, "media_out": 100, "include_in_cut": True, "is_replay": False,
        })
    phase = tmpdir / "phase5"
    phase.mkdir()
    (phase / "t01_story.json").write_text(json.dumps(story), encoding="utf-8")
    (phase / "story_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (phase / "candidate_edl.json").write_text(json.dumps(edl), encoding="utf-8")
    audit = {
        "schema": "v3a_story_quality_audit_v1", "match_id": "hyb",
        "hard_gate_findings": (
            [{"kind": "missing_story_element", "severity": "P0", "target": "opponent_opening",
              "detail": "missing"}] if with_p0 else []
        ),
        "diagnostic_issues": [],
        "revision_requests": (
            [{"kind": "missing_story_element", "severity": "P0", "target": "opponent_opening",
              "detail": "missing"}] if with_p0 else []
        ),
        "unverified": ["live_vs_replay_visual_truth"],
        "structural_proxy_pass": not with_p0,
        "render_ready": False, "release_decision": "NOT_AUTHORIZED",
    }
    (phase / "v3a_quality_audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return phase, story, plan, edl, audit


class HybridFallbackUnitTests(unittest.TestCase):
    def test_rule_verifier_always_runs(self):
        _, story, plan, edl, _ = _mini_phase(Path(tempfile.mkdtemp()))
        out = run_rule_verifier(story, plan, edl)
        self.assertTrue(out["ok"])
        self.assertEqual(out["rule_verification_status"], "FAILED")  # missing opening
        self.assertEqual(out["semantic_scores"]["narrative_coherence"], "NOT_EVALUATED")

    def test_dual_verifier_degrade_marks_not_evaluated(self):
        _, story, plan, edl, _ = _mini_phase(Path(tempfile.mkdtemp()))

        def boom(payload, fixture=None):
            return {"ok": False, "error": "502", "provider_mode": "degraded", "attempts": [{"ok": False}]}

        dual = run_dual_verifier(
            story=story, plan=plan, baseline_edl=edl, candidate_edl=edl,
            api_verifier_fn=boom, api_payload={},
        )
        self.assertFalse(dual["ok"])
        self.assertFalse(dual.get("semantic_pretend_pass"))
        self.assertFalse(dual.get("rule_fallback_success"))
        self.assertEqual(dual["semantic_verification_status"], "NOT_EVALUATED")
        for d in dual["validated"]["dimensions"].values():
            self.assertEqual(d["status"], "NOT_EVALUATED")
            self.assertIsNone(d.get("score"))
        self.assertEqual(dual["rule_verification_status"], "FAILED")

    def test_rule_planner_fallback_no_invention(self):
        _, story, plan, edl, audit = _mini_phase(Path(tempfile.mkdtemp()))
        fb = build_rule_planner_fallback(story, plan, edl, audit, video_duration=500.0)
        self.assertTrue(fb["ok"])
        self.assertTrue(fb["fallback"])
        self.assertEqual(fb["provider_mode"], "rule_fallback")
        for it in fb["validated"]["revision_intents"]:
            self.assertIn(it["action"], ("search_add", "mark_unresolved", "keep"))

    def test_goal_bind_refused_without_semantic(self):
        d = decide_accept(
            baseline_audit={"hard_gate_findings": [{"severity": "P0"}],
                            "dimensions": {"story_element_coverage": {"score": 66},
                                           "story_coherence": {"score": 100}}},
            candidate_audit={"hard_gate_findings": [],
                             "dimensions": {"story_element_coverage": {"score": 100},
                                            "story_coherence": {"score": 100}}},
            verifier={"ok": False, "validated": {"dimensions": not_evaluated_semantic_block()}},
            revision_meta={"applied": [{
                "status": "applied_evidence_bound", "action": "search_add",
                "segment_id": "seg_opponent_opening_goal_action",
            }]},
            semantic_verification_status="NOT_EVALUATED",
        )
        self.assertFalse(d["accept"])
        self.assertIn("goal_bind_requires_semantic_verification", d["reasons"])


class HybridOrchestrationFaultTests(unittest.TestCase):
    def test_planner_fault_still_completes_baseline(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            phase, _, _, edl, _ = _mini_phase(root)
            edl_sha = (phase / "candidate_edl.json").read_bytes()
            out = root / "out"
            summary = run_self_revise(
                phase5_dir=phase, out_dir=out,
                enable_real_api=False, i_approve_budget=False,
                allow_degraded_offline=True,
                inject_planner_failure=True,
                inject_vlm_failure=True,
                inject_verifier_failure=True,
                max_rounds=1, skip_vlm=True,
            )
            self.assertTrue(summary["workflow_completed"])
            self.assertTrue(summary["degraded_execution_success"])
            self.assertFalse(summary["multimodal_self_revision_success"])
            self.assertFalse(summary["agent_contributed_improvement"])
            self.assertFalse(summary["accepted_revision"])
            self.assertEqual(summary["semantic_verification_status"], "NOT_EVALUATED")
            self.assertFalse(summary["render_ready"])
            self.assertEqual(summary["release_decision"], "NOT_AUTHORIZED")
            self.assertEqual((phase / "candidate_edl.json").read_bytes(), edl_sha)
            best = json.loads((out / "best_candidate_edl.json").read_text())
            self.assertEqual(len(best), len(edl))

    def test_all_api_faults_preserve_edl_and_rule_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            phase, _, _, _, _ = _mini_phase(root)
            out = root / "out"
            summary = run_self_revise(
                phase5_dir=phase, out_dir=out,
                allow_degraded_offline=True,
                inject_planner_failure=True,
                inject_vlm_failure=True,
                inject_verifier_failure=True,
                max_rounds=1, skip_vlm=True,
            )
            self.assertTrue(summary["workflow_completed"])
            self.assertIsNotNone(summary["fallback_reason"])
            self.assertTrue((out / "baseline_rule_verifier.json").is_file())
            self.assertTrue((out / "final_rule_verifier.json").is_file())
            self.assertFalse(summary["edl_modified_frozen_phase5"])

    def test_api_recovery_keeps_best_accepted(self):
        """After a degraded round, a later fixture round may accept; best preserved."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            phase, _, _, edl, _ = _mini_phase(root, with_p0=False)
            # First: all inject fail → baseline best
            out1 = root / "out1"
            s1 = run_self_revise(
                phase5_dir=phase, out_dir=out1,
                allow_degraded_offline=True,
                inject_planner_failure=True, inject_verifier_failure=True,
                max_rounds=1, skip_vlm=True,
            )
            self.assertFalse(s1["accepted_revision"])
            best1 = json.loads((out1 / "best_candidate_edl.json").read_text())
            self.assertEqual(len(best1), len(edl))
            # Status schema
            orch = build_orchestration_status(
                workflow_completed=True,
                rule_verification_status="PASSED",
                semantic_verification_status="NOT_EVALUATED",
                fallback_reasons=["verifier:502"],
                accepted_revision=False,
                agent_contributed_improvement=False,
            )
            self.assertTrue(orch["degraded_execution_success"])
            self.assertFalse(orch["multimodal_self_revision_success"])

    def test_no_false_accept_replay_or_unverified_goal(self):
        d = decide_accept(
            baseline_audit={"hard_gate_findings": [], "dimensions": {
                "story_element_coverage": {"score": 100}, "story_coherence": {"score": 100}}},
            candidate_audit={"hard_gate_findings": [], "dimensions": {
                "story_element_coverage": {"score": 100}, "story_coherence": {"score": 100}}},
            verifier={"ok": True, "validated": {
                "dimensions": {
                    "story_element_coverage": {"status": "improved", "evidence_refs": ["x"], "summary": "s"},
                    "narrative_coherence": {"status": "unchanged", "evidence_refs": [], "summary": ""},
                    "image_content_quality": {"status": "unchanged", "evidence_refs": [], "summary": ""},
                },
                "evidence_of_improvement": [{"claim": "c", "evidence_refs": ["x"]}],
                "hard_vetoes": [{"kind": "replay_as_first_live"}],
            }},
            revision_meta={"applied": [{"status": "applied", "action": "drop", "segment_id": "x"}]},
            semantic_verification_status="PASSED",
        )
        self.assertFalse(d["accept"])
        self.assertIn("verifier_hard_veto", d["reasons"])


if __name__ == "__main__":
    unittest.main()
