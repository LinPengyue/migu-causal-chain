"""Phase 8 second-audit fixes: first-LIVE ledger, evidence token, autonomous A→B.

Zero HTTP. Does not mock run_story_evidence_search / plan_from_diagnosis for P0-C.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_video_agent_v3.dual_video_vision_verifier import validate_visual_verifier_payload
from story_video_agent_v3.story_e2e_agent import StoryE2EInputs, run_story_e2e
from story_video_agent_v3.story_evidence_search import run_story_evidence_search
from story_video_agent_v3.story_revision_feedback import (
    make_observation_evidence_token,
    should_penalize_candidate,
)
from story_video_agent_v3.story_revision_planner import plan_from_diagnosis
from story_video_agent_v3.story_video_verifier import (
    build_first_live_window_ledger,
    build_phase8_verdict,
    compute_independent_hard_safety,
)


def _edl():
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


def _diag_confirmed():
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


class TestFirstLiveLedgerP0A(unittest.TestCase):
    def test_event_chain_not_verified_is_unknown(self):
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
            extra={
                "has_new_footage": True,
                "first_live_ledger": led,
                "pts_ok": True,
                "source_provenance_ok": True,
            },
        )
        self.assertEqual(hs["safety"], "UNKNOWN")

    def test_two_windows_one_unverified_unknown(self):
        # Synthetic validated pack for window A only (no files required in this unit).
        pack_a = {
            "schema": "v3a_first_live_window_evidence_v1",
            "status": "FIRST_LIVE_VERIFIED",
            "source_sha256": "shaA",
            "source_pts_start": 900.0,
            "source_pts_end": 908.0,
            "manifest_digest": "a" * 64,
            "manifest": {"k": 1},
            "frames": [
                {"sha256": "b" * 64, "path": "/no/file", "source_pts_sec": 901.0},
                {"sha256": "c" * 64, "path": "/no/file", "source_pts_sec": 907.0},
            ],
        }
        # Recompute digest to match manifest
        import hashlib, json as _json

        pack_a["manifest_digest"] = hashlib.sha256(
            _json.dumps(pack_a["manifest"], sort_keys=True).encode()
        ).hexdigest()
        led = build_first_live_window_ledger(
            source_sha="shaA",
            new_windows=[
                {
                    "source_pts_start": 900.0,
                    "source_pts_end": 908.0,
                    "validated_evidence": pack_a,
                    "require_evidence_files": False,
                },
                {
                    "source_pts_start": 1500.0,
                    "source_pts_end": 1510.0,
                    "first_live_status": "NOT_VERIFIED",
                },
            ],
        )
        self.assertTrue(led["any_window_unverified"])
        hs = compute_independent_hard_safety(
            hard_vetoes=[],
            goal_intact=True,
            render_rows_ok=True,
            extra={
                "has_new_footage": True,
                "first_live_ledger": led,
                "pts_ok": True,
                "source_provenance_ok": True,
                "require_candidate_mp4": False,
            },
        )
        self.assertEqual(hs["safety"], "UNKNOWN")

    def test_any_hard_veto_fails(self):
        hs = compute_independent_hard_safety(
            hard_vetoes=[{"kind": "ocr_corruption"}],
            goal_intact=True,
            render_rows_ok=True,
            extra={"has_new_footage": False, "require_candidate_mp4": False},
        )
        self.assertEqual(hs["safety"], "FAIL")

    def test_all_windows_verified_pass(self):
        import hashlib, json as _json

        manifest = {"k": 1}
        pack = {
            "schema": "v3a_first_live_window_evidence_v1",
            "status": "FRAME_BOUND_VALID",
            "binding_status": "FRAME_BOUND_VALID",
            "source_sha256": "shaA",
            "source_pts_start": 900.0,
            "source_pts_end": 908.0,
            "manifest": manifest,
            "manifest_digest": hashlib.sha256(
                _json.dumps(manifest, sort_keys=True).encode()
            ).hexdigest(),
            "frames": [
                {"sha256": "b" * 64, "path": "/no/file", "source_pts_sec": 901.0},
                {"sha256": "c" * 64, "path": "/no/file", "source_pts_sec": 907.0},
            ],
        }
        timeline = {
            "schema": "v3a_broadcast_timeline_review_v1",
            "source_sha256": "shaA",
            "source_pts_start": 900.0,
            "source_pts_end": 908.0,
            "outcome": "FIRST_LIVE_VERIFIED",
            "method": "explicit_authenticated_timeline_review",
            "rationale": ["unit_test_authenticated_first_broadcast"],
            "evidence_refs": [{"kind": "continuous_context", "note": "fixture"}],
            "reviewer": "unit_test",
            "provenance": "UNIT_TEST_TIMELINE_REVIEW",
        }
        led = build_first_live_window_ledger(
            source_sha="shaA",
            new_windows=[
                {
                    "source_pts_start": 900.0,
                    "source_pts_end": 908.0,
                    "validated_evidence": pack,
                    "broadcast_timeline_review": timeline,
                    "require_evidence_files": False,
                }
            ],
        )
        self.assertEqual(led["aggregate_status"], "FIRST_LIVE_VERIFIED")
        hs = compute_independent_hard_safety(
            hard_vetoes=[],
            goal_intact=True,
            render_rows_ok=True,
            candidate_mp4=None,
            extra={
                "has_new_footage": True,
                "first_live_ledger": led,
                "pts_ok": True,
                "source_provenance_ok": True,
                "require_candidate_mp4": False,
            },
        )
        self.assertEqual(hs["safety"], "PASS")

    def test_vlm_first_live_claim_ignored_without_ledger(self):
        # Content-claimed FIRST_LIVE_VERIFIED without ledger/new-window proof → UNKNOWN
        # when treated as legacy token that is actually event-chain-ish; empty ledger path
        # with has_new_footage and no ledger uses first_live_status carefully.
        hs = compute_independent_hard_safety(
            hard_vetoes=[],
            goal_intact=True,
            render_rows_ok=True,
            extra={
                "has_new_footage": True,
                "first_live_status": "SEARCH_EVENT_CHAIN_LIVE_VERIFIED",
                "pts_ok": True,
                "source_provenance_ok": True,
            },
        )
        self.assertEqual(hs["safety"], "UNKNOWN")


class TestEvidenceTokenP0D(unittest.TestCase):
    def test_candidate_id_does_not_unlock_same_pts(self):
        tok = make_observation_evidence_token(
            source_sha="src",
            pts_start=900.0,
            pts_end=908.0,
            frame_hashes=["a" * 64],
            manifest_digest="b" * 64,
        )
        memory = [
            {
                "action": "search_add",
                "source_pts": [900.0, 908.0],
                "failure_class": "UNCERTAIN_OR_UNVERIFIED",
                "issue_signature": {
                    "category": "transition",
                    "anchor_segment_ids": ["seg_setup"],
                },
                "evidence_token": tok,
            }
        ]
        hit = should_penalize_candidate(
            memory,
            issue_signature={
                "category": "transition",
                "anchor_segment_ids": ["seg_setup"],
            },
            action="search_add",
            source_pts=[900.0, 908.0],
            new_evidence_token="cand_first_900",
        )
        self.assertTrue(hit["suppress"])

    def test_new_observation_token_unlocks(self):
        prior = make_observation_evidence_token(
            source_sha="src",
            pts_start=900.0,
            pts_end=908.0,
            frame_hashes=["a" * 64],
            manifest_digest="b" * 64,
        )
        nxt = make_observation_evidence_token(
            source_sha="src",
            pts_start=900.0,
            pts_end=908.0,
            frame_hashes=["c" * 64, "d" * 64],
            manifest_digest="e" * 64,
        )
        memory = [
            {
                "action": "search_add",
                "source_pts": [900.0, 908.0],
                "failure_class": "UNCERTAIN_OR_UNVERIFIED",
                "issue_signature": {
                    "category": "transition",
                    "anchor_segment_ids": ["seg_setup"],
                },
                "evidence_token": prior,
            }
        ]
        hit = should_penalize_candidate(
            memory,
            issue_signature={
                "category": "transition",
                "anchor_segment_ids": ["seg_setup"],
            },
            action="search_add",
            source_pts=[900.0, 908.0],
            new_evidence_token=nxt,
        )
        self.assertFalse(hit["suppress"])


class TestAutonomousFeedbackSearchP0C(unittest.TestCase):
    def test_real_search_and_planner_choose_b_after_feedback(self):
        edl = _edl()
        diag = _diag_confirmed()
        with tempfile.TemporaryDirectory() as td:
            ev = _events_ab(Path(td) / "events.json")
            control = run_story_evidence_search(
                diagnosis=diag, edl=edl, match_json=ev
            )
            self.assertTrue(control["search_success"])
            self.assertEqual(control["verified_candidates"][0]["event_id"], "ev_cand_A")
            plan_a = plan_from_diagnosis(
                diag, offline=True, search_results=control
            )
            self.assertEqual(plan_a["decision"], "REVISE")
            win_a = plan_a["revision_intents"][0]["bound_source_window"]
            self.assertAlmostEqual(float(win_a["start"]), 896.0, delta=1.0)

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
                            frame_hashes=["1" * 64],
                            manifest_digest="2" * 64,
                        ),
                    }
                ],
                "n_records": 1,
            }
            with_fb = run_story_evidence_search(
                diagnosis=diag, edl=edl, match_json=ev, feedback_context=fb
            )
            filtered_ids = [
                c["event_id"] for c in with_fb["feedback_filtered_candidates"]
            ]
            kept_ids = [c["event_id"] for c in with_fb["verified_candidates"]]
            self.assertIn("ev_cand_A", filtered_ids)
            self.assertEqual(kept_ids[0], "ev_cand_B")
            plan_b = plan_from_diagnosis(
                diag, offline=True, search_results=with_fb, feedback_context=fb
            )
            self.assertEqual(plan_b["decision"], "REVISE")
            win_b = plan_b["revision_intents"][0]["bound_source_window"]
            self.assertAlmostEqual(float(win_b["start"]), 1496.0, delta=1.0)
            self.assertNotAlmostEqual(
                float(win_a["start"]), float(win_b["start"]), delta=1.0
            )


class TestSoftQualityRealVlmShapeP0B(unittest.TestCase):
    def test_soft_promising_preserved_without_accept(self):
        validated = validate_visual_verifier_payload(
            {
                "hard_vetoes": [],
                "quality_delta_vs_baseline": "NOT_EVALUATED",
                "accept_candidate": False,
                "soft_quality": "PROMISING",
                "issue_effect": "PARTIAL",
                "global_regression": "NO",
                "suggested_next_evidence": {
                    "question": "Does bridge show pressure?",
                    "source_pts": [900.0, 908.0],
                    "issue_id": "jump",
                },
                "observed_changes": ["clearer midfield advance"],
                "evidence_of_improvement": [],
            },
            sent_frame_ids=["baseline_a", "candidate_a"],
        )
        out = validated["validated"]
        self.assertEqual(out.get("soft_quality"), "PROMISING")
        self.assertFalse(out.get("accept_candidate"))
        v = build_phase8_verdict(
            hard_vetoes=[],
            goal_intact=True,
            render_rows_ok=True,
            semantic_status="NOT_EVALUATED",
            vision_backed=True,
            sent_frame_ids=["baseline_a", "candidate_a"],
            validated=out,
            quality_overlay=out,
            verdict_provenance="REAL_VLM",
            hard_safety={"safety": "PASS", "accept_candidate_ignored": True},
            accept_candidate=False,
        )
        self.assertEqual(v["quality"], "PROMISING")
        self.assertEqual(v["safety"], "PASS")
        self.assertFalse(v["accept_candidate_raw"])
        self.assertIsInstance(v["suggested_next_evidence"], dict)


class TestRunStoryE2EAutonomousFeedback(unittest.TestCase):
    def test_e2e_real_search_planner_no_scripted_round2_intents(self):
        """Mock only render/observe; real search+planner pick B after feedback."""
        root = Path(tempfile.mkdtemp(prefix="p8_auto_"))
        phase5 = root / "phase5"
        phase5.mkdir(parents=True)
        edl = _edl()
        (phase5 / "candidate_edl.json").write_text(
            json.dumps(edl, indent=2) + "\n", encoding="utf-8"
        )
        (phase5 / "story_plan.json").write_text(
            json.dumps({"schema": "test_plan", "segments": edl}, indent=2) + "\n",
            encoding="utf-8",
        )
        (phase5 / "t01_story.json").write_text(
            json.dumps({"schema": "t01"}, indent=2) + "\n", encoding="utf-8"
        )
        # Tiny stub mp4s (avoid ffmpeg dependency if possible)
        for name in ("story_clean.mp4",):
            (phase5 / name).write_bytes(b"\x00\x00\x00\x18ftypmp42fake")
        src = root / "source.mp4"
        src.write_bytes(b"\x00\x00\x00\x18ftypmp42fake")
        ev = _events_ab(root / "events.json")
        mj = root / "match.json"
        mj.write_text(json.dumps({"match_id": "p8_auto"}), encoding="utf-8")
        out = root / "out"

        import story_video_agent_v3.story_e2e_agent as e2e_mod

        def _fake_render(**kwargs):
            od = Path(kwargs["out_dir"])
            od.mkdir(parents=True, exist_ok=True)
            dst = od / "story_clean.mp4"
            if not dst.exists():
                dst.write_bytes(b"\x00\x00\x00\x18ftypmp42fake")
            return {"ok": True, "story_clean": str(dst)}

        # Soft quality only — NO revision_intents. confirm_issue_ids for planner mutate.
        fixtures = [
            {
                "confirm_issue_ids": [
                    "large_source_jump_seg_setup_to_seg_turn"
                ],
                "phase8_quality": "PROMISING",
                "phase8_safety": "PASS",
                "phase8_evidence": "PARTIAL",
            },
            {
                # After r1 insert, jump issue id may rename; confirm any remaining via prefix handled in loop
                "confirm_issue_ids": [
                    "large_source_jump_seg_setup_to_seg_turn"
                ],
                "phase8_quality": "UNCERTAIN",
                "phase8_safety": "PASS",
                "phase8_evidence": "INSUFFICIENT",
            },
        ]

        with mock.patch.object(e2e_mod, "_render_edl", side_effect=_fake_render), mock.patch(
            "story_video_agent_v3.story_e2e_agent.observe_layers",
            return_value={
                "schema": "test_observe",
                "layers": [],
                "semantic_provider_used": False,
                "fixture_or_offline": True,
            },
        ):
            # Also confirm dynamic jump ids that appear after first insert.
            audit = run_story_e2e(
                StoryE2EInputs(
                    match_json=mj,
                    source_mp4=src,
                    out_dir=out,
                    phase5_dir=phase5,
                    events_json=ev,
                    skip_vlm=True,
                    enable_real_api=False,
                    smoke_render=False,
                    max_rounds=2,
                    confirm_issue_ids=[
                        "large_source_jump_",  # prefix: confirm structural jumps without scripting PTS
                    ],
                    phase8_round_fixtures=fixtures,
                )
            )

        r1_search = json.loads((out / "02_round_01" / "evidence_search.json").read_text())
        r1_plan = json.loads((out / "02_round_01" / "revision_plan.json").read_text())
        self.assertTrue(r1_search.get("search_success"))
        self.assertEqual(r1_search["verified_candidates"][0]["event_id"], "ev_cand_A")
        self.assertEqual(r1_plan.get("decision"), "REVISE")
        self.assertNotIn("fixture_intents", str(r1_plan.get("rationale") or ""))
        self.assertTrue(
            any(
                i.get("action") == "search_add"
                for i in (r1_plan.get("revision_intents") or [])
            )
        )
        win1 = (r1_plan.get("revision_intents") or [{}])[0].get("bound_source_window") or {}
        self.assertAlmostEqual(float(win1.get("start") or 0), 896.0, delta=2.0)
        self.assertTrue((out / "02_round_02").is_dir(), "CONTINUE_WORKING should open round 2")

        r2_search = json.loads((out / "02_round_02" / "evidence_search.json").read_text())
        r2_plan = json.loads((out / "02_round_02" / "revision_plan.json").read_text())
        filtered = [
            c.get("event_id") for c in (r2_search.get("feedback_filtered_candidates") or [])
        ]
        kept = [c.get("event_id") for c in (r2_search.get("verified_candidates") or [])]
        proof = {
            "r1_top": r1_search["verified_candidates"][0]["event_id"],
            "r1_window": win1,
            "r2_filtered": filtered,
            "r2_kept": kept,
            "r2_plan_window": (r2_plan.get("revision_intents") or [{}])[0].get(
                "bound_source_window"
            ),
            "r2_feedback_filter_applied": r2_search.get("feedback_filter_applied"),
            "no_scripted_intents": True,
            "mocked_only": ["_render_edl", "observe_layers"],
            "real": ["run_story_evidence_search", "plan_from_diagnosis"],
        }
        (out / "AUTONOMOUS_FEEDBACK_PROOF.json").write_text(
            json.dumps(proof, indent=2) + "\n", encoding="utf-8"
        )
        self.assertTrue(r2_search.get("feedback_filter_applied"), msg=proof)
        # Either A filtered out of verified, or B is the top remaining / planned window.
        self.assertTrue(
            "ev_cand_A" in filtered
            or (kept and kept[0] == "ev_cand_B")
            or abs(
                float(
                    ((r2_plan.get("revision_intents") or [{}])[0].get("bound_source_window") or {}).get(
                        "start"
                    )
                    or 0
                )
                - 1496.0
            )
            < 5.0,
            msg=proof,
        )
        self.assertFalse((audit.get("delivery") or {}).get("release_authorized"))


if __name__ == "__main__":
    unittest.main()
