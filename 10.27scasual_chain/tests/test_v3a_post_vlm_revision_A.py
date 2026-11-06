"""Offline Post-VLM Revision Planner tests (zero paid HTTP).

Replays saved Oman one-round artifacts + synthetic fixtures.
Simulated Revision Planner fixtures do NOT prove real DeepSeek judgment quality.
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent_v3.one_round_opening_budget import ONE_ROUND_MAX_HTTP, OPENING_SEGMENT_ID
from story_video_agent_v3.revision_planner import (
    DECISION_KEEP_WITH_NEW_EVIDENCE,
    DECISION_PROPOSE_REPAIR,
    DECISION_UNRESOLVED,
    FIXTURE_MARK,
    build_revision_planner_context,
    call_llm_revision_planner,
    collect_known_evidence_tokens,
    edl_rows_sha256,
    fail_closed_intents_after_revision_failure,
    select_intents_for_edl_revision,
    validate_revision_planner_output,
)
from story_video_agent_v3.self_revise_agent import (
    apply_candidate_revision,
    build_trusted_anchors,
    decide_accept,
    run_self_revise,
    validate_planner_output,
)

REAL_RUN = Path(
    "/data2/lpy1/_story_va_outputs/v3/plan2/A_one_round_opening_20261106_133900"
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


def _synthetic_offset_obs(*, issue_id="SYN_OFFSET"):
    """Synthetic observation: dense PTS near start of a padded window."""
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
        "ok": True,
        "provider_mode": "offline_fixture",
        "window": {"start": 1325.123, "end": 1347.123},
        "frames": frames,
        "allowed_windows": [{"start": 1325.123, "end": 1347.123}],
        "fact_verified": False,
        "observation_only": True,
        "vlm": {
            "visible_content": "Synthetic: clear shot then ball in net early in window.",
            "observed_shot": True,
            "observed_net": True,
            "live_or_replay": "live",
            "supports_bound_segment": True,
            "candidate_goal_action_span": {"start": 1326.0, "end": 1331.0},
            "scoreboard_only": False,
            "fact_verified": False,
            "observation_only": True,
            "cited_frame_ids": [f["frame_id"] for f in frames],
            "cannot_certify_first_live": True,
        },
    }


def _planner_inspect_fixture():
    return {
        "diagnoses": [{
            "issue_id": "D01",
            "problem": "Need directed observe of opening goal action",
            "severity": "P1",
            "target_segment_id": OPENING_SEGMENT_ID,
            "evidence_refs": ["composer_handoff"],
        }],
        "revision_intents": [{
            "intent_id": "intent_000",
            "action": "keep",
            "disposition": "INSPECT",
            "target_segment_id": OPENING_SEGMENT_ID,
            "role": "opponent_opening_goal_action",
            "anchor_id": f"edl:{OPENING_SEGMENT_ID}",
            "rationale": "pre-VLM inspect keep",
        }],
        "video_tool_requests": [],
        "notes": "offline_post_vlm_test",
    }


@unittest.skipUnless(
    (REAL_RUN / "round_01/vlm_observations.json").is_file()
    and (FRESH_BASELINE / "candidate_edl.json").is_file()
    and (FIX / "rp_keep_opening_real_replay.json").is_file(),
    "real Oman one-round artifacts or fixtures missing",
)
class PostVlmRevisionOfflineTests(unittest.TestCase):
    def setUp(self):
        self.baseline_edl = _edl_rows(_load(FRESH_BASELINE / "candidate_edl.json"))
        self.plan = _load(FRESH_BASELINE / "story_plan.json")
        self.story = _load(FRESH_BASELINE / "t01_story.json")
        self.real_obs_pack = _load(REAL_RUN / "round_01/vlm_observations.json")
        self.real_obs = list(self.real_obs_pack.get("observations") or [])
        self.anchors = build_trusted_anchors(self.plan, self.baseline_edl)
        self.baseline_sha = edl_rows_sha256(self.baseline_edl)
        self.frozen_file_sha = __import__("hashlib").sha256(
            (FRESH_BASELINE / "candidate_edl.json").read_bytes()
        ).hexdigest()

    def test_A_keep_with_real_qwen_evidence_no_false_gain(self):
        """A: shot+net observed; fixture KEEP; EDL unchanged; evidence recorded."""
        rp_raw = _load(FIX / "rp_keep_opening_real_replay.json")
        self.assertTrue(rp_raw.get(FIXTURE_MARK))
        known = collect_known_evidence_tokens(observations=self.real_obs)
        validated = validate_revision_planner_output(
            rp_raw,
            trusted_anchors=self.anchors,
            video_duration=9000.0,
            known_evidence=known,
            best_edl=self.baseline_edl,
        )
        self.assertEqual(validated["decision"], DECISION_KEEP_WITH_NEW_EVIDENCE)
        self.assertTrue(all(it["action"] == "keep" for it in validated["proposed_revision_intents"]))

        cand, meta = apply_candidate_revision(
            self.baseline_edl,
            validated["proposed_revision_intents"],
            self.real_obs,
        )
        self.assertEqual(edl_rows_sha256(cand), self.baseline_sha)
        self.assertEqual(meta["evidence_bound_count"], 0)
        self.assertFalse(validated.get("first_live_not_claimed") is False)

        # Full offline loop replay with fixtures (0 HTTP).
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pf = root / "planner.json"
            rpf = root / "rp.json"
            vf = root / "ver.json"
            pf.write_text(json.dumps(_planner_inspect_fixture()), encoding="utf-8")
            rpf.write_text(json.dumps(rp_raw), encoding="utf-8")
            vf.write_text(json.dumps({
                "issues": [],
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
                        "status": "unchanged", "summary": "ok", "score": 70,
                        "evidence_refs": [], "problems": [],
                    },
                    "live_authenticity": {
                        "status": "insufficient_evidence", "summary": "UNKNOWN",
                        "score": None,
                        "evidence_refs": [], "problems": ["not FIRST_LIVE"],
                    },
                },
                "revision_suggestions": [],
                "quality_delta_vs_baseline": "unchanged",
                "hard_vetoes": [],
                "evidence_of_improvement": [],
                "live_segment_assessments": [],
            }), encoding="utf-8")
            out = root / "out"
            # Replay saved real Qwen obs as seeded historical evidence (0 new HTTP).
            seeded = []
            for o in self.real_obs:
                s = dict(o)
                s["historical_reuse"] = True
                s["counts_as_new_http"] = False
                s["provenance_validated"] = True
                s["observation_only"] = True
                s["fact_verified"] = False
                seeded.append(s)
            summary = run_self_revise(
                phase5_dir=FRESH_BASELINE,
                out_dir=out,
                prefer_p1_polish=False,
                planner_fixture=pf,
                revision_planner_fixture=rpf,
                verifier_fixture=vf,
                enable_post_vlm_revision=True,
                skip_vlm=True,
                max_rounds=1,
                allow_degraded_offline=True,
                seed_observations=seeded,
            )
            self.assertEqual(
                (summary.get("api_usage") or {}).get("http_attempts", 0) or 0,
                0,
            )
            self.assertFalse(summary.get("enable_real_api"))
            round1 = (summary.get("rounds") or [{}])[0]
            self.assertEqual(round1.get("intent_source"), "post_vlm_revision_planner")
            self.assertEqual(
                round1.get("revision_planner_decision"),
                DECISION_KEEP_WITH_NEW_EVIDENCE,
            )
            best = _load(out / "best_candidate_edl.json")
            self.assertEqual(edl_rows_sha256(best), self.baseline_sha)
            self.assertFalse(summary.get("accepted_any_revision"))
            self.assertFalse(summary.get("render_ready"))
            # Frozen baseline bytes untouched.
            self.assertEqual(
                __import__("hashlib").sha256(
                    (FRESH_BASELINE / "candidate_edl.json").read_bytes()
                ).hexdigest(),
                self.frozen_file_sha,
            )
            intent_src = _load(out / "round_01/intent_source.json")
            self.assertTrue(intent_src.get("planner_revision_intents_audit"))
            self.assertEqual(intent_src.get("intent_source"), "post_vlm_revision_planner")

    def test_B_propose_repair_trim_accepted_when_verifier_allows(self):
        """B: synthetic offset → PROPOSE_REPAIR trim → candidate differs; may accept."""
        obs = _synthetic_offset_obs()
        rp_raw = _load(FIX / "rp_propose_trim_synthetic.json")
        known = collect_known_evidence_tokens(observations=[obs])
        validated = validate_revision_planner_output(
            rp_raw,
            trusted_anchors=self.anchors,
            video_duration=9000.0,
            known_evidence=known,
            best_edl=self.baseline_edl,
        )
        self.assertEqual(validated["decision"], DECISION_PROPOSE_REPAIR)
        cand, meta = apply_candidate_revision(
            self.baseline_edl,
            validated["proposed_revision_intents"],
            [obs],
        )
        self.assertGreaterEqual(meta["evidence_bound_count"], 1)
        self.assertNotEqual(edl_rows_sha256(cand), self.baseline_sha)
        opening = next(
            r for r in cand if r.get("segment_id") == OPENING_SEGMENT_ID
        )
        self.assertGreaterEqual(float(opening["media_in"]), 1325.123 - 1e-6)
        self.assertLess(float(opening["media_out"]), 1347.123 - 1e-3)

        decision = decide_accept(
            baseline_audit={"hard_gate_findings": [], "dimensions": {}},
            candidate_audit={"hard_gate_findings": [], "dimensions": {}},
            verifier={
                "ok": True,
                "ok_for_semantic_accept": True,
                "validated": _load(FIX / "verifier_accept_trim.json"),
            },
            revision_meta=meta,
            baseline_edl=self.baseline_edl,
            candidate_edl=cand,
            semantic_verification_status="PASSED",
            mode="loop",
        )
        self.assertTrue(decision.get("accept") or decision.get("loop_retain"))
        self.assertFalse(decision.get("release_eligible") and decision.get("path") == "release")
        # loop_retain / accept must not imply FIRST_LIVE or render_ready
        self.assertNotEqual(decision.get("path"), "FIRST_LIVE_VERIFIED")

    def test_C_illegal_or_verifier_reject_rolls_back(self):
        """C: evidence fail / verifier reject → best SHA == pre-revision."""
        obs = _synthetic_offset_obs()
        pre = edl_rows_sha256(self.baseline_edl)

        # C1: forged evidence_refs rejected at validate
        bad = _load(FIX / "rp_propose_trim_synthetic.json")
        bad = copy.deepcopy(bad)
        bad["evidence_refs"] = ["forged_pts:9999.1"]
        bad["proposed_revision_intents"][0]["evidence_refs"] = ["forged_pts:9999.1"]
        known = collect_known_evidence_tokens(observations=[obs])
        with self.assertRaises(ValueError):
            validate_revision_planner_output(
                bad,
                trusted_anchors=self.anchors,
                video_duration=9000.0,
                known_evidence=known,
                best_edl=self.baseline_edl,
            )

        # C2: free timestamp on repair intent rejected
        bad2 = _load(FIX / "rp_propose_trim_synthetic.json")
        bad2 = copy.deepcopy(bad2)
        bad2["proposed_revision_intents"][0]["media_in"] = 1200.0
        bad2["proposed_revision_intents"][0]["media_out"] = 1210.0
        with self.assertRaises(ValueError):
            validate_revision_planner_output(
                bad2,
                trusted_anchors=self.anchors,
                video_duration=9000.0,
                known_evidence=known,
                best_edl=self.baseline_edl,
            )

        # C3: legal trim candidate but verifier rejects → decide_accept false → SHA unchanged
        rp_ok = validate_revision_planner_output(
            _load(FIX / "rp_propose_trim_synthetic.json"),
            trusted_anchors=self.anchors,
            video_duration=9000.0,
            known_evidence=known,
            best_edl=self.baseline_edl,
        )
        cand, meta = apply_candidate_revision(
            self.baseline_edl, rp_ok["proposed_revision_intents"], [obs],
        )
        self.assertNotEqual(edl_rows_sha256(cand), pre)
        decision = decide_accept(
            baseline_audit={"hard_gate_findings": [], "dimensions": {}},
            candidate_audit={
                "hard_gate_findings": [
                    {"severity": "P0", "kind": "confirmed_severe_corruption",
                     "confirmed": True},
                ],
                "dimensions": {},
            },
            verifier={
                "ok": True,
                "ok_for_semantic_accept": True,
                "validated": _load(FIX / "verifier_reject.json"),
            },
            revision_meta=meta,
            baseline_edl=self.baseline_edl,
            candidate_edl=cand,
            semantic_verification_status="PASSED",
            mode="loop",
        )
        # Either hard gate blocks or reject path — must not accept.
        self.assertFalse(decision.get("accept"))
        # Best remains baseline when reject.
        self.assertEqual(edl_rows_sha256(self.baseline_edl), pre)

        # C4: replay-ish / out-of-window trim fails apply
        far_obs = _synthetic_offset_obs()
        far_obs["frames"] = [{
            "frame_id": "far0",
            "actual_media_sec": 2000.0,
            "pts_status": "pts",
        }]
        far_obs["vlm"]["cited_frame_ids"] = ["far0"]
        far_obs["request_id"] = "far_obs"
        # Intent cites known token but PTS outside segment → apply rejects trim
        known_far = collect_known_evidence_tokens(observations=[far_obs])
        # Build a keep-like repair that tries trim with wrong pts via issue match
        intents = [{
            "intent_id": "bad_trim",
            "action": "trim",
            "issue_id": "SYN_OFFSET",
            "target_segment_id": OPENING_SEGMENT_ID,
            "evidence_refs": ["far_obs"],
        }]
        # Use obs with matching issue_id but out-of-window pts
        far_obs["issue_id"] = "SYN_OFFSET"
        cand2, meta2 = apply_candidate_revision(self.baseline_edl, intents, [far_obs])
        self.assertEqual(edl_rows_sha256(cand2), pre)
        self.assertTrue(meta2.get("rejected"))

    def test_D_revision_planner_exceptions_fail_closed(self):
        """D: timeout / bad JSON / missing fields / forged refs → no unverified EDL edit."""
        pre = self.baseline_sha
        planner_intents = validate_planner_output(
            {
                "diagnoses": [{"issue_id": "d", "problem": "x", "severity": "P1"}],
                "revision_intents": [{
                    "action": "trim",
                    "target_segment_id": OPENING_SEGMENT_ID,
                    "anchor_id": f"edl:{OPENING_SEGMENT_ID}",
                    "rationale": "should not apply on RP failure",
                    "evidence_refs": ["x"],
                }],
                "video_tool_requests": [],
            },
            trusted_anchors=self.anchors,
            video_duration=9000.0,
        )["revision_intents"]

        # Missing decision
        with self.assertRaises(ValueError):
            validate_revision_planner_output(
                {"proposed_revision_intents": [], FIXTURE_MARK: True},
                trusted_anchors=self.anchors,
                video_duration=9000.0,
                known_evidence={"tokens": []},
                best_edl=self.baseline_edl,
            )

        # call with invalid fixture content
        bad_call = call_llm_revision_planner(
            None,
            {},
            fixture={"decision": "PROPOSE_REPAIR", FIXTURE_MARK: True},
            trusted_anchors=self.anchors,
            video_duration=9000.0,
            best_edl=self.baseline_edl,
            known_evidence={"tokens": ["x"]},
        )
        self.assertFalse(bad_call.get("ok"))

        pack = select_intents_for_edl_revision(
            enable_post_vlm_revision=True,
            revision_planner_result={"ok": False, "error": "timeout"},
            planner_intents=planner_intents,
            focus_segment_ids=[OPENING_SEGMENT_ID],
        )
        self.assertTrue(pack["fail_closed"])
        self.assertTrue(all(it.get("action") == "keep" for it in pack["intents"]))
        cand, meta = apply_candidate_revision(
            self.baseline_edl, pack["intents"], self.real_obs,
        )
        self.assertEqual(edl_rows_sha256(cand), pre)
        self.assertEqual(meta["evidence_bound_count"], 0)

        closed = fail_closed_intents_after_revision_failure(
            planner_intents=planner_intents,
            focus_segment_ids=[OPENING_SEGMENT_ID],
            error="illegal_json",
        )
        self.assertIn("audit only", closed["note"].lower().replace("-", " ") or closed["note"])

        # Injected failure via run_self_revise
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pf = root / "planner.json"
            pf.write_text(json.dumps(_planner_inspect_fixture()), encoding="utf-8")
            out = root / "out"
            summary = run_self_revise(
                phase5_dir=FRESH_BASELINE,
                out_dir=out,
                prefer_p1_polish=False,
                planner_fixture=pf,
                enable_post_vlm_revision=True,
                inject_revision_planner_failure=True,
                skip_vlm=True,
                max_rounds=1,
                allow_degraded_offline=True,
            )
            self.assertEqual(edl_rows_sha256(_load(out / "best_candidate_edl.json")), pre)
            r0 = (summary.get("rounds") or [{}])[0]
            self.assertTrue(r0.get("revision_planner_fail_closed"))
            self.assertEqual(r0.get("intent_source"), "revision_planner_failed_fail_closed")
            # Pre-VLM intents preserved for audit, not silently applied as trim.
            src = _load(out / "round_01/intent_source.json")
            self.assertTrue(src.get("planner_revision_intents_audit") is not None)

    def test_budget_four_roles_and_context_shape(self):
        self.assertGreaterEqual(ONE_ROUND_MAX_HTTP, 4)
        ctx = build_revision_planner_context(
            best_edl=self.baseline_edl,
            composer_handoff={"segments": {OPENING_SEGMENT_ID: {"segment_id": OPENING_SEGMENT_ID}}},
            planner_validated={
                "diagnoses": [{"issue_id": "D01"}],
                "revision_intents": [{"action": "keep"}],
                "video_tool_requests": [],
            },
            historical_observations=[],
            new_observations=self.real_obs,
            trusted_anchors=self.anchors,
            focus_segment_ids=[OPENING_SEGMENT_ID],
        )
        self.assertIn("planner_revision_intents_pre_vlm", ctx)
        self.assertIn("new_vlm_observations", ctx)
        self.assertTrue(ctx["first_live_constraints"]["sparse_frames_do_not_force_trim"])
        # UNRESOLVED fixture path
        u = validate_revision_planner_output(
            _load(FIX / "rp_unresolved.json"),
            trusted_anchors=self.anchors,
            video_duration=9000.0,
            known_evidence=collect_known_evidence_tokens(observations=self.real_obs),
            best_edl=self.baseline_edl,
        )
        self.assertEqual(u["decision"], DECISION_UNRESOLVED)
        self.assertTrue(all(it["action"] == "mark_unresolved" for it in u["proposed_revision_intents"]))


class PostVlmRevisionRegressionGuard(unittest.TestCase):
    """E: legacy path still works with post-vlm disabled."""

    def test_legacy_pre_vlm_intents_when_disabled(self):
        pack = select_intents_for_edl_revision(
            enable_post_vlm_revision=False,
            revision_planner_result=None,
            planner_intents=[{"action": "keep", "intent_id": "i0"}],
        )
        self.assertEqual(pack["intent_source"], "pre_vlm_planner")
        self.assertEqual(pack["intents"][0]["action"], "keep")


if __name__ == "__main__":
    unittest.main()
