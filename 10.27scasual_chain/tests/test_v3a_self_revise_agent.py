"""Offline tests for V3-A LLM+VLM self-revision Agent (no paid HTTP)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent_v3.self_revise_agent import (
    apply_candidate_revision,
    build_trusted_anchors,
    compact_context,
    decide_accept,
    expand_windows_from_anchor,
    run_self_revise,
    validate_planner_output,
    validate_verifier_output,
)


def _mini_artifacts():
    story = {"match_id": "test_match", "title": "t", "protagonist": "left"}
    plan = {
        "match_id": "test_match",
        "story_tier": "story",
        "title": "t",
        "story_scope": {
            "selected_arc": {
                "behind_start": {"t_sec": 100.0, "score": "0:1"},
                "equalizer": {"t_sec": 200.0, "score": "1:1"},
                "go_ahead": {"t_sec": 300.0, "score": "2:1"},
            }
        },
        "missing_evidence": [],
    }
    edl = [
        {
            "segment_id": "seg_title",
            "role": "story_title",
            "media_in": 0.0,
            "media_out": 3.0,
            "include_in_cut": True,
            "shot_kind": "title_card",
        },
        {
            "segment_id": "seg_equalizer_goal_action",
            "role": "equalizer_goal_action",
            "media_in": 180.0,
            "media_out": 200.0,
            "include_in_cut": True,
            "event_ids": ["e2"],
            "is_replay": False,
        },
        {
            "segment_id": "seg_go_ahead_goal_action",
            "role": "go_ahead_goal_action",
            "media_in": 280.0,
            "media_out": 300.0,
            "include_in_cut": True,
            "event_ids": ["e3"],
            "is_replay": False,
        },
    ]
    return story, plan, edl


class V3ASelfReviseAgentTests(unittest.TestCase):
    def test_windows_expand_from_score_anchor_not_free_time(self):
        anchors = build_trusted_anchors(_mini_artifacts()[1], _mini_artifacts()[2])
        score = next(a for a in anchors if a["anchor_id"] == "score_node:behind_start")
        wins = expand_windows_from_anchor(score, video_duration=500.0)
        self.assertTrue(wins)
        self.assertAlmostEqual(wins[0]["start"], 0.0)  # 100-180 clipped to 0
        self.assertLessEqual(wins[-1]["end"], 115.0 + 1e-6)
        self.assertTrue(all(w["end"] - w["start"] <= 30.0 + 1e-6 for w in wins))

    def test_planner_rejects_uncited_anchor(self):
        _, plan, edl = _mini_artifacts()
        anchors = build_trusted_anchors(plan, edl)
        with self.assertRaises(ValueError):
            validate_planner_output(
                {
                    "diagnoses": [],
                    "revision_intents": [],
                    "video_tool_requests": [{
                        "tool": "vlm_observe",
                        "anchor_id": "invented_time:999",
                        "question": "x",
                    }],
                },
                trusted_anchors=anchors,
                video_duration=500.0,
            )

    def test_planner_accepts_score_anchored_tool(self):
        _, plan, edl = _mini_artifacts()
        anchors = build_trusted_anchors(plan, edl)
        out = validate_planner_output(
            {
                "diagnoses": [{
                    "issue_id": "d0",
                    "problem": "missing opening goal action",
                    "severity": "P0",
                    "story_element": "opponent_opening",
                    "evidence_refs": [{"kind": "stage1", "ref": "missing_story_element"}],
                    "expected_improvement": "recover opening live goal visual",
                }],
                "revision_intents": [{
                    "action": "search_add",
                    "issue_id": "d0",
                    "role": "opponent_opening_goal_action",
                    "anchor_id": "score_node:behind_start",
                    "rationale": "need LIVE opening",
                    "expected_improvement": "cover missing role",
                    "risk": "wrong shot",
                }],
                "video_tool_requests": [{
                    "tool": "vlm_observe",
                    "issue_id": "d0",
                    "anchor_id": "score_node:behind_start",
                    "question": "Is there a LIVE goal action before 0:1 board?",
                    "window_indices": [0, 1],
                }],
            },
            trusted_anchors=anchors,
            video_duration=500.0,
        )
        self.assertEqual(out["video_tool_requests"][0]["windows_source"], "trusted_anchor_expansion")
        self.assertTrue(out["video_tool_requests"][0]["search_windows"])

    def test_search_add_does_not_invent_media_times(self):
        edl, meta = apply_candidate_revision(
            _mini_artifacts()[2],
            [{"intent_id": "i0", "action": "search_add", "role": "opponent_opening_goal_action",
              "anchor_id": "score_node:behind_start"}],
            [],
        )
        self.assertEqual(len(edl), 3)
        self.assertEqual(meta["applied"][0]["status"], "pending_evidence_slot")
        self.assertTrue(all("media_in" not in a or a.get("status") for a in meta["applied"]))

    def test_accept_requires_improvement_and_verifier_ok(self):
        base = {"hard_gate_findings": [{"severity": "P0", "kind": "missing_story_element"}]}
        cand = {"hard_gate_findings": [{"severity": "P0", "kind": "missing_story_element"}]}
        d = decide_accept(
            baseline_audit=base,
            candidate_audit=cand,
            verifier={"ok": True, "validated": {"quality_delta_vs_baseline": "none"}},
            revision_meta={"applied": [{"action": "search_add", "status": "pending_evidence_slot"}]},
        )
        self.assertFalse(d["accept"])

    def test_fixture_loop_does_not_claim_real_api_success(self):
        story, plan, edl = _mini_artifacts()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            phase = root / "phase5"
            phase.mkdir()
            (phase / "t01_story.json").write_text(json.dumps(story), encoding="utf-8")
            (phase / "story_plan.json").write_text(json.dumps(plan), encoding="utf-8")
            (phase / "candidate_edl.json").write_text(json.dumps(edl), encoding="utf-8")
            audit = {
                "schema": "v3a_story_quality_audit_v1",
                "match_id": "test_match",
                "hard_gate_findings": [{
                    "kind": "missing_story_element", "severity": "P0",
                    "target": "opponent_opening", "detail": "missing",
                }],
                "diagnostic_issues": [],
                "revision_requests": [{
                    "kind": "missing_story_element", "severity": "P0",
                    "target": "opponent_opening", "detail": "missing",
                }],
                "unverified": ["live_vs_replay_visual_truth"],
                "structural_proxy_pass": False,
                "render_ready": False,
                "release_decision": "NOT_AUTHORIZED",
            }
            (phase / "v3a_quality_audit.json").write_text(json.dumps(audit), encoding="utf-8")
            planner_fix = {
                "diagnoses": [{
                    "issue_id": "d0", "problem": "missing opening", "severity": "P0",
                    "story_element": "opponent_opening",
                    "evidence_refs": [{"kind": "stage1"}],
                    "expected_improvement": "add opening",
                }],
                "revision_intents": [{
                    "action": "search_add", "issue_id": "d0",
                    "role": "opponent_opening_goal_action",
                    "anchor_id": "score_node:behind_start",
                    "rationale": "search", "expected_improvement": "cover", "risk": "miss",
                }],
                "video_tool_requests": [{
                    "tool": "vlm_observe", "issue_id": "d0",
                    "anchor_id": "score_node:behind_start",
                    "question": "find opening goal",
                }],
                "notes": "fixture",
            }
            verifier_fix = {
                "issues": [{
                    "issue_id": "v0", "severity": "P0",
                    "dimension": "story_element_coverage",
                    "problem": "still missing opening",
                    "evidence_refs": [], "suggested_fix": "continue search",
                }],
                "dimension_notes": {},
                "revision_suggestions": [],
                "quality_delta_vs_baseline": "no structural improvement yet",
            }
            pf = root / "planner.json"
            vf = root / "verifier.json"
            pf.write_text(json.dumps(planner_fix), encoding="utf-8")
            vf.write_text(json.dumps(verifier_fix), encoding="utf-8")
            out = root / "out"
            summary = run_self_revise(
                phase5_dir=phase,
                out_dir=out,
                enable_real_api=False,
                i_approve_budget=False,
                max_rounds=1,
                planner_fixture=pf,
                verifier_fixture=vf,
                skip_vlm=True,
            )
            self.assertEqual(summary["schema"], "v3a_self_revise_run_v1")
            self.assertFalse(summary["edl_modified_frozen_phase5"])
            self.assertFalse(summary["render_ready"])
            self.assertTrue(summary["fixture_mode"])
            # Fixture path may complete but must not pretend paid real API succeeded.
            self.assertNotEqual(summary.get("rounds", [{}])[0].get("planner_provider_mode"), "real")
            self.assertEqual(_sha_file(phase / "candidate_edl.json"), summary["source_sha256"]["edl"])


def _sha_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


if __name__ == "__main__":
    unittest.main()
