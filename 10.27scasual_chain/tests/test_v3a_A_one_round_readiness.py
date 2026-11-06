"""Zero-cost readiness tests for Oman one-round opening-goal V3-A experiment."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent_v3.one_round_opening_budget import (
    ONE_ROUND_MAX_HTTP,
    OPENING_SEGMENT_ID,
    build_one_round_preflight,
    enforce_provider_one_round_budget,
    evidence_gap_for_opening,
    filter_tools_to_focus,
    load_and_validate_historical_observation,
)
from story_video_agent_v3.self_revise_agent import decide_accept
from story_video_agent.api_provider import ApiProvider

FRESH = Path(
    "/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_A_uae_oman/"
    "fresh_e2e_A_real_20261105_183136"
)
OBS = Path("/data2/lpy1/_story_va_outputs/v3/plan2/A_vlm_smoke_20261105_210200/observation.json")
SUMMARY = Path(
    "/data2/lpy1/_story_va_outputs/v3/plan2/A_vlm_smoke_20261105_210200/vlm_smoke_summary.json"
)


@unittest.skipUnless(
    (FRESH / "05_v3a/_baseline_phase5/candidate_edl.json").is_file() and OBS.is_file(),
    "fresh Oman artifacts or historical VLM obs missing",
)
class OneRoundReadinessTests(unittest.TestCase):
    def test_preflight_ready_no_http(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "pre"
            report = build_one_round_preflight(
                fresh_run=FRESH,
                historical_obs=OBS,
                historical_summary=SUMMARY,
                out_dir=out,
            )
            self.assertEqual(report["status"], "READY_FOR_AUTHORIZED_ONE_ROUND")
            self.assertFalse(report["real_http_executed"])
            self.assertTrue(report["checks"]["planner_sees_full_composer_handoff"])
            self.assertTrue(report["checks"]["disposition_protocol_keep_ok"])
            self.assertTrue(report["checks"]["disposition_protocol_inspect_ok"])
            self.assertTrue(report["checks"]["vlm_only_on_inspect_with_gap"])
            self.assertTrue(report["checks"]["keep_preserves_edl"])
            self.assertTrue(report["checks"]["http_budget_retries_zero"])
            self.assertEqual(report["budget"]["max_http_attempts"], ONE_ROUND_MAX_HTTP)
            self.assertTrue((out / "one_round_preflight.json").is_file())
            self.assertTrue((out / "planner_context_preview.json").is_file())
            ctx = json.loads((out / "planner_context_preview.json").read_text(encoding="utf-8"))
            self.assertIn("composer_evidence_handoff", ctx)
            self.assertIn(
                OPENING_SEGMENT_ID,
                ctx["composer_evidence_handoff"]["segments"],
            )

    def test_historical_obs_provenance_not_new_call(self):
        manifest = json.loads((FRESH / "00_input_manifest.json").read_text(encoding="utf-8"))
        sha = ((manifest.get("sources") or {}).get("video") or {}).get("sha256")
        packed = load_and_validate_historical_observation(
            OBS, summary_path=SUMMARY, expected_video_sha256=sha,
        )
        self.assertFalse(packed["provenance"]["counts_as_new_http"])
        self.assertFalse(packed["provenance"]["counts_as_first_live_certification"])
        self.assertTrue(packed["provenance"]["pts_ok"])
        self.assertTrue(packed["observation"]["historical_reuse"])

    def test_tool_filter_and_budget(self):
        filtered = filter_tools_to_focus([
            {"tool": "vlm_observe", "anchor_id": f"edl:{OPENING_SEGMENT_ID}"},
            {"tool": "vlm_observe", "anchor_id": "edl:seg_equalizer_goal_action"},
            {"tool": "vlm_observe", "anchor_id": f"edl:{OPENING_SEGMENT_ID}"},
        ])
        self.assertEqual(len(filtered["tools"]), 1)
        self.assertTrue(any(d["reason"] == "outside_focus_segment" for d in filtered["dropped"]))
        api = ApiProvider(force_mock=True, max_calls=8, max_cost_usd=1.0)
        budget = enforce_provider_one_round_budget(api, max_calls=3)
        self.assertEqual(budget["max_calls"], 3)
        self.assertTrue(all(v == 0 for v in budget["max_retries_by_role"].values()))

    def test_evidence_gap_requires_inspect_when_no_shot(self):
        gap = evidence_gap_for_opening(
            {
                "media_in": 1325.123,
                "media_out": 1347.123,
                "suggested_planner_disposition": {"disposition": "INSPECT"},
            },
            {"observed_shot": False},
        )
        self.assertTrue(gap["needs_new_vlm"])
        self.assertEqual(gap["disposition"], "INSPECT")
        self.assertIsNotNone(gap["gap"])

    def test_verifier_gate_compares_baseline_not_candidate_alone(self):
        # decide_accept requires baseline vs candidate audit + revision evidence.
        base = {"hard_gate_findings": [], "dimensions": {}}
        cand = {"hard_gate_findings": [], "dimensions": {}}
        d = decide_accept(
            baseline_audit=base,
            candidate_audit=cand,
            verifier={
                "ok": True,
                "ok_for_semantic_accept": True,
                "semantic_verification_status": "PASSED",
                "validated": {"quality_delta_vs_baseline": "unchanged"},
            },
            revision_meta={"applied": [], "rejected": [], "evidence_bound_count": 0},
        )
        self.assertFalse(d["accept"])
        self.assertIn("no_evidence_bound_or_safe_edit", d.get("reasons") or [])


if __name__ == "__main__":
    unittest.main()
