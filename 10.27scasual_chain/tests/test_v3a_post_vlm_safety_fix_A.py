"""Zero-cost safety fixes for post-VLM Revision Planner (HTTP=0).

Each reject scenario runs the real self_revise main loop (or equivalent state
update) and asserts best_candidate_edl.json SHA equals the pre-revision SHA.
"""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

from story_video_agent_v3.one_round_opening_budget import OPENING_SEGMENT_ID
from story_video_agent_v3.revision_planner import (
    FIXTURE_MARK,
    collect_known_evidence_tokens,
    edl_rows_sha256,
    validate_revision_planner_output,
)
from story_video_agent_v3.self_revise_agent import (
    apply_candidate_revision,
    build_trusted_anchors,
    decide_accept,
    evaluate_trim_bounds,
    run_self_revise,
)

FRESH_BASELINE = Path(
    "/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_A_uae_oman/"
    "fresh_e2e_A_real_20261105_183136/05_v3a/_baseline_phase5"
)
FIX = Path(__file__).resolve().parent / "fixtures" / "v3a_post_vlm_revision_A"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _edl_rows(obj):
    if isinstance(obj, list):
        return obj
    return obj.get("segments") or obj.get("edl") or obj.get("rows") or []


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _planner_keep_fixture():
    return {
        "diagnoses": [{
            "issue_id": "SYN_OFFSET",
            "problem": "opening window may be padded",
            "severity": "P1",
            "target_segment_id": OPENING_SEGMENT_ID,
        }],
        "revision_intents": [{
            "intent_id": "pre_vlm_inspect",
            "action": "keep",
            "disposition": "INSPECT",
            "target_segment_id": OPENING_SEGMENT_ID,
            "role": "opponent_opening_goal_action",
            "anchor_id": f"edl:{OPENING_SEGMENT_ID}",
            "rationale": "pre-vlm",
        }],
        "video_tool_requests": [],
        "notes": "safety_fix_offline",
    }


def _syn_obs(*, replay: bool = False, issue_id: str = "SYN_OFFSET"):
    frames = []
    pts = [1326.0, 1327.5, 1329.0, 1330.5]
    for i, t in enumerate(pts):
        frames.append({
            "frame_id": f"syn_f{i}",
            "requested_media_sec": t,
            "actual_media_sec": t,
            "pts_status": "pts",
            "path": f"/tmp/syn_{i}.jpg",
        })
    return {
        "request_id": "syn_obs_offset_w0",
        "issue_id": issue_id,
        "anchor_id": f"edl:{OPENING_SEGMENT_ID}",
        "segment_id": OPENING_SEGMENT_ID,
        "ok": True,
        "provider_mode": "offline_fixture",
        "window": {"start": 1325.123, "end": 1347.123},
        "frames": frames,
        "allowed_windows": [{"start": 1325.123, "end": 1347.123}],
        "fact_verified": False,
        "observation_only": True,
        "historical_reuse": True,
        "counts_as_new_http": False,
        "provenance_validated": True,
        "vlm": {
            "visible_content": "Synthetic shot then net" + (" REPLAY angle" if replay else ""),
            "observed_shot": True,
            "observed_net": True,
            "live_or_replay": "replay" if replay else "live",
            "supports_bound_segment": True,
            "candidate_goal_action_span": {"start": 1326.0, "end": 1331.0},
            "scoreboard_only": False,
            "fact_verified": False,
            "observation_only": True,
            "cited_frame_ids": [f["frame_id"] for f in frames],
            "cannot_certify_first_live": True,
        },
    }


def _verifier_ok_improved():
    return _load(FIX / "verifier_accept_trim.json")


def _verifier_regressed():
    return {
        "issues": [{
            "issue_id": "v_reg",
            "severity": "P1",
            "dimension": "image_content_quality",
            "problem": "quality declined vs baseline",
            "evidence_refs": ["syn_obs_offset_w0"],
            "suggested_fix": "keep baseline",
        }],
        "dimensions": {
            "story_element_coverage": {
                "status": "unchanged", "summary": "ok", "score": 70,
                "evidence_refs": [], "problems": [],
            },
            "narrative_coherence": {
                "status": "unchanged", "summary": "ok", "score": 70,
                "evidence_refs": [], "problems": [],
            },
            "image_content_quality": {
                "status": "regressed", "summary": "worse", "score": 40,
                "evidence_refs": ["syn_obs_offset_w0"], "problems": ["context loss"],
            },
            "live_authenticity": {
                "status": "insufficient_evidence", "summary": "unknown",
                "score": None, "evidence_refs": [], "problems": [],
            },
        },
        "revision_suggestions": [],
        "quality_delta_vs_baseline": "regressed",
        "hard_vetoes": [],
        "evidence_of_improvement": [],
        "live_segment_assessments": [],
    }


@unittest.skipUnless(
    (FRESH_BASELINE / "candidate_edl.json").is_file()
    and (FIX / "rp_propose_trim_synthetic.json").is_file(),
    "baseline or fixtures missing",
)
class PostVlmSafetyFixMainLoopTests(unittest.TestCase):
    def setUp(self):
        self.baseline_edl = _edl_rows(_load(FRESH_BASELINE / "candidate_edl.json"))
        self.plan = _load(FRESH_BASELINE / "story_plan.json")
        self.anchors = build_trusted_anchors(self.plan, self.baseline_edl)
        self.baseline_row_sha = edl_rows_sha256(self.baseline_edl)
        self.frozen_file_sha = _file_sha(FRESH_BASELINE / "candidate_edl.json")

    def _run_loop(
        self,
        *,
        td: Path,
        rp_raw: Dict[str, Any],
        verifier_raw: Optional[Dict[str, Any]],
        seed_obs: List[Dict[str, Any]],
        inject_verifier_failure: bool = False,
    ):
        pf = td / "planner.json"
        rpf = td / "rp.json"
        vf = td / "ver.json"
        pf.write_text(json.dumps(_planner_keep_fixture()), encoding="utf-8")
        rpf.write_text(json.dumps(rp_raw), encoding="utf-8")
        if verifier_raw is not None:
            vf.write_text(json.dumps(verifier_raw), encoding="utf-8")
        out = td / "out"
        pre_best_sha = self.baseline_row_sha
        summary = run_self_revise(
            phase5_dir=FRESH_BASELINE,
            out_dir=out,
            prefer_p1_polish=False,
            planner_fixture=pf,
            revision_planner_fixture=rpf,
            verifier_fixture=None if inject_verifier_failure else vf,
            enable_post_vlm_revision=True,
            inject_verifier_failure=inject_verifier_failure,
            skip_vlm=True,
            max_rounds=1,
            allow_degraded_offline=True,
            seed_observations=seed_obs,
        )
        best_path = out / "best_candidate_edl.json"
        best_sha = edl_rows_sha256(_load(best_path))
        return summary, out, pre_best_sha, best_sha

    def test_1_verifier_api_fail_does_not_update_best(self):
        """Verifier API failure + evidence-bound candidate → best SHA unchanged."""
        obs = _syn_obs()
        rp = _load(FIX / "rp_propose_trim_synthetic.json")
        with tempfile.TemporaryDirectory() as td:
            summary, out, pre, best = self._run_loop(
                td=Path(td),
                rp_raw=rp,
                verifier_raw=_verifier_ok_improved(),
                seed_obs=[obs],
                inject_verifier_failure=True,
            )
            self.assertEqual(best, pre)
            self.assertFalse(summary.get("accepted_any_revision"))
            r0 = (summary.get("rounds") or [{}])[0]
            decision = r0.get("accept_decision") or {}
            self.assertFalse(decision.get("accept"))
            self.assertFalse(decision.get("loop_retain"))
            # Research pending proposal may exist, but must not be best.
            pending = out / "round_01/pending_proposal.json"
            if pending.is_file():
                blob = _load(pending)
                self.assertTrue(blob.get("not_accepted_edl"))
                self.assertFalse(blob.get("render_ready"))
                self.assertNotEqual(blob.get("candidate_edl_sha256"), best)
            self.assertEqual(_file_sha(FRESH_BASELINE / "candidate_edl.json"), self.frozen_file_sha)
            self.assertEqual(
                (summary.get("api_usage") or {}).get("http_attempts", 0) or 0, 0,
            )

    def test_2_verifier_quality_regressed_rolls_back_best(self):
        """Verifier says regressed (no extra P0) → best SHA == pre-revision."""
        obs = _syn_obs()
        rp = _load(FIX / "rp_propose_trim_synthetic.json")
        with tempfile.TemporaryDirectory() as td:
            summary, out, pre, best = self._run_loop(
                td=Path(td),
                rp_raw=rp,
                verifier_raw=_verifier_regressed(),
                seed_obs=[obs],
            )
            self.assertEqual(best, pre)
            self.assertFalse(summary.get("accepted_any_revision"))
            decision = (summary.get("rounds") or [{}])[0].get("accept_decision") or {}
            self.assertFalse(decision.get("accept"))
            reasons = " ".join(decision.get("reasons") or [])
            self.assertTrue(
                ("regressed" in reasons)
                or ("dimension_regressed" in reasons)
                or ("no_verifiable" in reasons)
                or ("refuse" in reasons)
                or (not decision.get("loop_retain")),
                decision.get("reasons"),
            )

    def test_3_replay_obs_trim_rejected_best_unchanged(self):
        """Replay VLM observation proposing trim must not change best EDL."""
        obs = _syn_obs(replay=True)
        rp = _load(FIX / "rp_propose_trim_synthetic.json")
        # Unit: trim evaluator rejects replay
        row = next(r for r in self.baseline_edl if r.get("segment_id") == OPENING_SEGMENT_ID)
        te = evaluate_trim_bounds(
            intent={"intent_id": "t", "action": "trim", "issue_id": "SYN_OFFSET",
                    "target_segment_id": OPENING_SEGMENT_ID},
            row=row,
            observations=[obs],
        )
        self.assertFalse(te.get("ok"))
        self.assertIn("replay", str(te.get("reason") or ""))

        with tempfile.TemporaryDirectory() as td:
            summary, out, pre, best = self._run_loop(
                td=Path(td),
                rp_raw=rp,
                verifier_raw=_verifier_ok_improved(),
                seed_obs=[obs],
            )
            self.assertEqual(best, pre)
            self.assertFalse(summary.get("accepted_any_revision"))
            meta = _load(out / "round_01/revision_meta.json")
            self.assertEqual(meta.get("evidence_bound_count"), 0)

    def test_4_empty_forged_unrelated_refs_rejected(self):
        """Empty / forged / fuzzy / unrelated evidence_refs cannot authorize REPAIR."""
        obs = _syn_obs()
        known = collect_known_evidence_tokens(observations=[obs])
        base = _load(FIX / "rp_propose_trim_synthetic.json")

        empty = copy.deepcopy(base)
        empty["evidence_refs"] = []
        empty["proposed_revision_intents"][0]["evidence_refs"] = []
        with self.assertRaises(ValueError):
            validate_revision_planner_output(
                empty, trusted_anchors=self.anchors, video_duration=9000.0,
                known_evidence=known, best_edl=self.baseline_edl,
            )

        forged = copy.deepcopy(base)
        forged["evidence_refs"] = ["forged_pts:9999.1"]
        forged["proposed_revision_intents"][0]["evidence_refs"] = ["forged_pts:9999.1"]
        with self.assertRaises(ValueError):
            validate_revision_planner_output(
                forged, trusted_anchors=self.anchors, video_duration=9000.0,
                known_evidence=known, best_edl=self.baseline_edl,
            )

        # Fuzzy affix must NOT pass (exact match only).
        fuzzy = copy.deepcopy(base)
        fuzzy["evidence_refs"] = ["XXXsyn_f0YYY"]
        fuzzy["proposed_revision_intents"][0]["evidence_refs"] = ["XXXsyn_f0YYY"]
        with self.assertRaises(ValueError):
            validate_revision_planner_output(
                fuzzy, trusted_anchors=self.anchors, video_duration=9000.0,
                known_evidence=known, best_edl=self.baseline_edl,
            )

        # Label-only refs insufficient for REPAIR.
        labels_only = copy.deepcopy(base)
        labels_only["evidence_refs"] = ["new_vlm_observation"]
        labels_only["proposed_revision_intents"][0]["evidence_refs"] = ["new_vlm_observation"]
        with self.assertRaises(ValueError):
            validate_revision_planner_output(
                labels_only, trusted_anchors=self.anchors, video_duration=9000.0,
                known_evidence=known, best_edl=self.baseline_edl,
            )

        # Unrelated concrete token from another segment must fail segment link.
        other = copy.deepcopy(obs)
        other["request_id"] = "other_seg_obs"
        other["anchor_id"] = "edl:seg_equalizer_goal_action"
        other["segment_id"] = "seg_equalizer_goal_action"
        other["frames"] = [{
            "frame_id": "eq_f0", "actual_media_sec": 2400.0, "pts_status": "pts",
        }]
        other["vlm"] = dict(other["vlm"])
        other["vlm"]["cited_frame_ids"] = ["eq_f0"]
        known2 = collect_known_evidence_tokens(observations=[other])
        unrelated = copy.deepcopy(base)
        unrelated["evidence_refs"] = ["other_seg_obs", "eq_f0"]
        unrelated["proposed_revision_intents"][0]["evidence_refs"] = ["other_seg_obs", "eq_f0"]
        with self.assertRaises(ValueError):
            validate_revision_planner_output(
                unrelated, trusted_anchors=self.anchors, video_duration=9000.0,
                known_evidence=known2, best_edl=self.baseline_edl,
            )

        # Main loop: bad RP fixture → fail-closed → best unchanged.
        bad_rp = copy.deepcopy(base)
        bad_rp["evidence_refs"] = ["forged_only"]
        bad_rp["proposed_revision_intents"][0]["evidence_refs"] = ["forged_only"]
        with tempfile.TemporaryDirectory() as td:
            summary, out, pre, best = self._run_loop(
                td=Path(td),
                rp_raw=bad_rp,
                verifier_raw=_verifier_ok_improved(),
                seed_obs=[obs],
            )
            self.assertEqual(best, pre)
            r0 = (summary.get("rounds") or [{}])[0]
            self.assertTrue(r0.get("revision_planner_fail_closed"))

    def test_5_legal_candidate_still_accepted(self):
        """Legal trim + Verifier accept still updates best when all gates pass."""
        obs = _syn_obs()
        rp = _load(FIX / "rp_propose_trim_synthetic.json")
        # Direct apply still produces a different candidate.
        known = collect_known_evidence_tokens(observations=[obs])
        validated = validate_revision_planner_output(
            rp, trusted_anchors=self.anchors, video_duration=9000.0,
            known_evidence=known, best_edl=self.baseline_edl,
        )
        cand, meta = apply_candidate_revision(
            self.baseline_edl, validated["proposed_revision_intents"], [obs],
        )
        self.assertGreaterEqual(meta["evidence_bound_count"], 1)
        self.assertNotEqual(edl_rows_sha256(cand), self.baseline_row_sha)

        d = decide_accept(
            baseline_audit={"hard_gate_findings": [], "dimensions": {}},
            candidate_audit={"hard_gate_findings": [], "dimensions": {}},
            verifier={
                "ok": True,
                "ok_for_semantic_accept": True,
                "validated": _verifier_ok_improved(),
            },
            revision_meta=meta,
            baseline_edl=self.baseline_edl,
            candidate_edl=cand,
            semantic_verification_status="PASSED",
            mode="loop",
        )
        self.assertTrue(d.get("accept") or d.get("loop_retain"), d.get("reasons"))
        self.assertFalse(d.get("pending_proposal_only"))

        with tempfile.TemporaryDirectory() as td:
            summary, out, pre, best = self._run_loop(
                td=Path(td),
                rp_raw=rp,
                verifier_raw=_verifier_ok_improved(),
                seed_obs=[obs],
            )
            # Accepted path may update best; SHA should differ from pre when accepted.
            if summary.get("accepted_any_revision"):
                self.assertNotEqual(best, pre)
                opening = next(
                    r for r in _load(out / "best_candidate_edl.json")
                    if r.get("segment_id") == OPENING_SEGMENT_ID
                )
                self.assertLess(float(opening["media_out"]), 1347.123 - 1e-3)
                self.assertEqual(opening.get("first_live_status"), "NOT_VERIFIED")
            else:
                # If structural audit blocks, still must not claim FIRST_LIVE/render_ready.
                self.assertFalse(summary.get("render_ready"))
            self.assertEqual(
                (summary.get("api_usage") or {}).get("http_attempts", 0) or 0, 0,
            )
            self.assertEqual(_file_sha(FRESH_BASELINE / "candidate_edl.json"), self.frozen_file_sha)

    def test_sparse_minmax_pts_alone_cannot_trim(self):
        """Four frames without a tighter action span → pending, not forced trim."""
        obs = _syn_obs()
        obs = copy.deepcopy(obs)
        # Remove span → only sparse PTS remain
        obs["vlm"]["candidate_goal_action_span"] = None
        row = next(r for r in self.baseline_edl if r.get("segment_id") == OPENING_SEGMENT_ID)
        te = evaluate_trim_bounds(
            intent={"intent_id": "t", "action": "trim", "issue_id": "SYN_OFFSET",
                    "target_segment_id": OPENING_SEGMENT_ID},
            row=row,
            observations=[obs],
        )
        self.assertFalse(te.get("ok"))
        self.assertEqual(te.get("status"), "pending_evidence_slot")
        cand, meta = apply_candidate_revision(
            self.baseline_edl,
            [{"intent_id": "t", "action": "trim", "issue_id": "SYN_OFFSET",
              "target_segment_id": OPENING_SEGMENT_ID}],
            [obs],
        )
        self.assertEqual(edl_rows_sha256(cand), self.baseline_row_sha)
        self.assertEqual(meta["evidence_bound_count"], 0)
        self.assertTrue(any(
            a.get("status") == "pending_evidence_slot" for a in (meta.get("applied") or [])
        ))


class DecideAcceptVerifierUnevaluatedUnit(unittest.TestCase):
    def test_unevaluated_sets_pending_proposal_only(self):
        d = decide_accept(
            baseline_audit={"hard_gate_findings": [{"severity": "P0", "kind": "missing_story_element"}],
                            "dimensions": {"story_element_coverage": {"score": 50}}},
            candidate_audit={"hard_gate_findings": [],
                             "dimensions": {"story_element_coverage": {"score": 90}}},
            verifier={"ok": False, "validated": {"hard_vetoes": [], "dimensions": {},
                                                 "evidence_of_improvement": []}},
            revision_meta={"applied": [{
                "status": "applied_evidence_bound", "action": "search_add",
                "segment_id": OPENING_SEGMENT_ID, "role": "opponent_opening_goal_action",
            }]},
            semantic_verification_status="NOT_EVALUATED",
        )
        self.assertFalse(d["accept"])
        self.assertTrue(d["pending_proposal_only"])
        self.assertNotEqual(d.get("path"), "loop_pending_verification")


if __name__ == "__main__":
    unittest.main()
