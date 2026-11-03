"""Tests for V3-A Stage-2 evidence-task Planner (offline, zero billed calls)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "algo"))
from story_video_agent_v3.planner_stage2 import (  # noqa: E402
    MAX_WINDOW_SPAN_SEC, compile_proposal, compile_safe_candidates, main, select_ids,
)


def example(missing=True):
    story = {
        "match_id": "france_australia_test", "story_tier": "complete",
        "events": [{"event_id": "unverified_wrong_goal", "t_ms": 1351000, "type": "Goal"}],
    }
    plan = {
        "match_id": "france_australia_test",
        "story_tier": "complete",
        "story_scope": {
            "selected_arc": {
                "behind_start": {"score": "0:1", "t_sec": 150.0},
                "equalizer": {"score": "1:1", "t_sec": 250.0},
                "go_ahead": {"score": "2:1", "t_sec": 350.0},
            }
        },
    }
    edl = [
        {"segment_id": "eq", "role": "equalizer_goal_action", "media_in": 245, "media_out": 263,
         "event_ids": ["e2"], "beat": "转折"},
    ]
    issue = {
        "kind": "missing_story_element", "severity": "P0",
        "target": "opponent_opening", "detail": "missing LIVE shot",
    }
    audit = {
        "schema": "v3a_story_quality_audit_v1",
        "match_id": story["match_id"],
        "render_ready": False,
        "release_decision": "NOT_AUTHORIZED",
        "revision_requests": [issue] if missing else [],
        "diagnostic_issues": [issue] if missing else [
            {"kind": "possible_image_anomaly", "severity": "P2", "target": "rendered_video"}
        ],
    }
    return story, plan, edl, audit


class V3APlannerStage2Tests(unittest.TestCase):
    def test_fr_missing_goal_creates_bounded_search_not_goal_label(self):
        s, p, e, a = example()
        out = compile_proposal(s, p, e, a)
        self.assertEqual(1, len(out["selected_tasks"]))
        task = out["selected_tasks"][0]
        self.assertEqual("add_missing_role_after_evidence_verification", task["repair_intent"])
        self.assertEqual("opponent_opening_goal_action", task["required_role"])
        self.assertEqual(150.0, task["score_anchor_sec"])
        self.assertTrue(task["search_windows"])
        self.assertTrue(all(0 < w["end"] - w["start"] <= MAX_WINDOW_SPAN_SEC
                            for w in task["search_windows"]))
        self.assertFalse(task["may_edit_edl"])
        self.assertEqual("UNVERIFIED", task["evidence_status"])
        self.assertEqual("SOURCE_ANCHOR_ONLY", task["evidence_refs"][0]["verification"])
        self.assertNotIn("unverified_wrong_goal", json.dumps(task))
        self.assertFalse(out["edl_modified"])
        self.assertFalse(out["render_ready"])
        self.assertEqual("NOT_AUTHORIZED", out["release_decision"])

    def test_structurally_ok_a_b_c_does_not_generate_revision_for_freeze_p2(self):
        s, p, e, a = example(missing=False)
        out = compile_proposal(s, p, e, a)
        self.assertEqual([], out["selected_tasks"])
        self.assertEqual(0, out["candidate_task_count"])

    def test_llm_can_reorder_only_existing_ids(self):
        s, p, e, a = example()
        a["revision_requests"].append({
            "kind": "goal_window_incomplete", "severity": "P0",
            "target": "eq",
        })
        tasks = compile_safe_candidates(s, p, e, a)
        ids = [t["task_id"] for t in tasks]
        out = compile_proposal(s, p, e, a, llm_response={"selected_task_ids": list(reversed(ids))})
        self.assertEqual(list(reversed(ids)), [t["task_id"] for t in out["selected_tasks"]])
        self.assertEqual("validated_llm_selection", out["mode"])
        self.assertEqual("inspect_existing_segment_before_any_change", out["selected_tasks"][0]["repair_intent"])

    def test_llm_invented_event_time_or_task_is_rejected(self):
        s, p, e, a = example()
        for proposed in (
            {"selected_task_ids": ["fabricated"]},
            {"selected_task_ids": ["issue_000"], "media_in": 1351.0},
            {"selected_task_ids": ["issue_000", "issue_000"]},
        ):
            out = compile_proposal(s, p, e, a, llm_response=proposed)
            self.assertEqual("rule_fallback", out["mode"])
            self.assertIn("llm_rejected", out["mode_reason"])
            self.assertEqual("issue_000", out["selected_tasks"][0]["task_id"])
            self.assertFalse(out["edl_modified"])

    def test_empty_model_selection_cannot_skip_p0(self):
        s, p, e, a = example()
        out = compile_proposal(s, p, e, a, llm_response={"selected_task_ids": []})
        self.assertEqual(1, len(out["selected_tasks"]))
        self.assertEqual("rule_fallback", out["mode"])
        self.assertIn("cannot skip unresolved P0", out["mode_reason"])
        self.assertEqual(1, out["candidate_task_count"])

    def test_cross_match_leakage_rejected(self):
        s, p, e, a = example()
        a["match_id"] = "some_other_match"
        with self.assertRaisesRegex(ValueError, "cross-match"):
            compile_proposal(s, p, e, a)

    def test_no_anchor_refuses_to_invent_media_time(self):
        s, p, e, a = example()
        p["story_scope"]["selected_arc"]["behind_start"] = {"score": "0:1"}
        out = compile_proposal(s, p, e, a)
        self.assertEqual([], out["selected_tasks"])

    def test_bad_audit_authorization_rejected(self):
        s, p, e, a = example()
        a["render_ready"] = True
        with self.assertRaises(ValueError):
            compile_proposal(s, p, e, a)

    def test_unknown_issue_cannot_be_turned_into_edit(self):
        s, p, e, a = example()
        a["revision_requests"] = [{
            "kind": "add_fake_goal", "severity": "P0", "target": "opponent_opening"
        }]
        self.assertEqual([], compile_proposal(s, p, e, a)["selected_tasks"])

    def test_cli_default_no_remote_calls_and_preserves_inputs(self):
        s, p, e, a = example()
        with tempfile.TemporaryDirectory() as tmp:
            phase = Path(tmp) / "04_phase5"
            phase.mkdir()
            for name, obj in (
                ("t01_story.json", s), ("story_plan.json", p),
                ("candidate_edl.json", e), ("v3a_quality_audit.json", a)
            ):
                (phase / name).write_text(json.dumps(obj), encoding="utf-8")
            original = (phase / "candidate_edl.json").read_bytes()
            out = Path(tmp) / "proposal.json"
            self.assertEqual(0, main(["--phase5-dir", str(phase), "--out", str(out)]))
            result = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(0, result["planner_execution"]["api_usage"]["real_requests"])
            self.assertFalse(result["edl_modified"])
            self.assertEqual(original, (phase / "candidate_edl.json").read_bytes())
            with self.assertRaises(SystemExit):
                main(["--phase5-dir", str(phase), "--out", str(out)])
            self.assertEqual(original, (phase / "candidate_edl.json").read_bytes())

    def test_model_selection_schema_is_exact(self):
        s, p, e, a = example()
        candidates = compile_safe_candidates(s, p, e, a)
        with self.assertRaises(ValueError):
            select_ids({"selected_task_ids": ["issue_000"], "new_t": 1}, candidates)


if __name__ == "__main__":
    unittest.main()
