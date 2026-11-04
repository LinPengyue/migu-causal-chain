"""Match-agnostic Agent checks + four-dim Verifier (no paid API)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent_v3.hybrid_fallback import SEMANTIC_DIMS
from story_video_agent_v3.self_revise_agent import (
    VERIFIER_SYSTEM,
    compact_context,
    composite_quality_score,
    run_self_revise,
    validate_verifier_output,
)

ABC_PHASE5 = [
    Path("/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_A_uae_oman/04_phase5"),
    Path("/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_B_osasuna_celta/04_phase5"),
    Path("/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_C_croatia_canada/04_phase5"),
]


class FourDimVerifierTests(unittest.TestCase):
    def test_semantic_dims_include_live_authenticity(self):
        self.assertIn("live_authenticity", SEMANTIC_DIMS)
        self.assertEqual(len(SEMANTIC_DIMS), 4)
        self.assertIn("live_authenticity", VERIFIER_SYSTEM)

    def test_score_preserved_and_unknown_null(self):
        v = validate_verifier_output({
            "issues": [],
            "dimensions": {
                "story_element_coverage": {
                    "status": "improved", "score": 82, "summary": "cov", "evidence_refs": ["a"],
                },
                "narrative_coherence": {
                    "status": "unchanged", "score": 90, "summary": "coh", "evidence_refs": [],
                },
                "image_content_quality": {
                    "status": "unknown", "score": None, "summary": "", "evidence_refs": [],
                },
                "live_authenticity": {
                    "status": "regressed", "score": 40, "summary": "suspect replay",
                    "evidence_refs": ["obs"],
                },
            },
            "live_segment_assessments": [{
                "segment_id": "seg_eq", "live_status": "SUSPECTED_REPLAY",
                "score": 35, "evidence_refs": ["is_replay_meta"], "reason": "slow-mo cues",
            }],
            "hard_vetoes": [],
            "evidence_of_improvement": [],
        })
        self.assertEqual(v["dimensions"]["story_element_coverage"]["score"], 82.0)
        self.assertIsNone(v["dimensions"]["image_content_quality"]["score"])
        self.assertEqual(v["dimensions"]["live_authenticity"]["score"], 40.0)
        self.assertEqual(v["live_segment_assessments"][0]["live_status"], "SUSPECTED_REPLAY")

    def test_composite_excludes_unknown_equal_weight(self):
        scores = composite_quality_score(
            {"dimensions": {
                "story_element_coverage": {"score": 80},
                "story_coherence": {"score": 100},
            }},
            verifier_validated={"dimensions": {
                "live_authenticity": {"status": "improved", "score": 60},
                "image_content_quality": {"status": "NOT_EVALUATED", "score": None},
            }},
        )
        # 80, 100, 60 evaluated; image UNKNOWN excluded → mean 80
        self.assertEqual(scores["evaluated_count"], 3)
        self.assertAlmostEqual(scores["composite"], 80.0)
        self.assertIn("image_content_quality", scores["unknown_dimensions"])

    def test_prior_feedback_in_context(self):
        story = {"match_id": "x"}
        plan = {"match_id": "x", "story_tier": "story", "story_scope": {"selected_arc": {
            "behind_start": {"t_sec": 10, "score": "0:1"},
            "equalizer": {"t_sec": 20, "score": "1:1"},
            "go_ahead": {"t_sec": 30, "score": "2:1"},
        }}}
        edl = [{"segment_id": "s1", "role": "equalizer_goal_action",
                "media_in": 18, "media_out": 22, "include_in_cut": True}]
        audit = {"hard_gate_findings": [], "diagnostic_issues": [], "revision_requests": []}
        fb = {"from_round": 1, "verifier_issues": [{"problem": "suspect replay"}], "accepted": False}
        ctx = compact_context(
            story=story, plan=plan, edl=edl, audit=audit,
            prior_round_feedback=fb, video_duration=100.0,
        )
        self.assertEqual(ctx["prior_round_feedback"]["from_round"], 1)
        self.assertTrue(ctx["constraints"]["match_agnostic_general_agent"])


class CrossMatchOfflineRegression(unittest.TestCase):
    """A/B/C phase5 must run degraded offline without France-only assumptions."""

    def test_abc_degraded_loop_completes(self):
        available = [p for p in ABC_PHASE5 if (p / "candidate_edl.json").is_file()]
        self.assertGreaterEqual(len(available), 1)
        for phase in available:
            with self.subTest(match=phase.parent.name):
                with tempfile.TemporaryDirectory() as td:
                    out = Path(td) / "out"
                    summary = run_self_revise(
                        phase5_dir=phase,
                        out_dir=out,
                        enable_real_api=False,
                        i_approve_budget=False,
                        allow_degraded_offline=True,
                        max_rounds=1,
                        skip_vlm=True,
                        stop_on_quality_threshold=False,
                    )
                    self.assertTrue(summary["workflow_completed"])
                    self.assertFalse(summary["edl_modified_frozen_phase5"])
                    self.assertFalse(summary["render_ready"])
                    # Context must not inject France literals
                    ctx = json.loads((out / "round_01/planner_context.json").read_text())
                    blob = json.dumps(ctx, ensure_ascii=False).lower()
                    self.assertNotIn("法国", blob)
                    self.assertNotIn("australia", blob)
                    self.assertTrue(ctx["constraints"].get("match_agnostic_general_agent"))


if __name__ == "__main__":
    unittest.main()
