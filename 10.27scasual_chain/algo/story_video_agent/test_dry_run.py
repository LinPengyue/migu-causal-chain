"""Phase 1.5 dry-run / 语义回归。"""

from __future__ import annotations

import unittest
from pathlib import Path

from story_video_agent.runner import run_story_json, solve
from story_video_agent.state import detect_gaps, validate_plan_payload
from story_video_agent.tools import ToolArgumentError, ToolBox

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "story_t01"
FRANCE = REPORTS / "2022年11月23日 法国vs澳大利亚.json"
CROATIA = REPORTS / "2022-11-28 克罗地亚vs加拿大.json"


class Phase15Tests(unittest.TestCase):
    def test_france_separates_score_and_goal_anchors(self) -> None:
        self.assertTrue(FRANCE.is_file(), f"missing {FRANCE}")
        result = run_story_json(str(FRANCE), dry_run=True, max_steps=16)
        self.assertEqual(result["status"], "planned")
        self.assertTrue(result["structure_ok"], result.get("structure_problems"))
        self.assertFalse(result["verification_complete"])
        self.assertEqual(validate_plan_payload(result), [])
        gap_ids = {g["gap_id"] for g in result["gaps"]}
        self.assertIn("verify_equalizer_scoreboard", gap_ids)
        self.assertIn("verify_go_ahead_scoreboard", gap_ids)
        # 法国有进球事件：应有动作核实，而非 locate
        self.assertTrue(
            "verify_equalizer_goal_action" in gap_ids
            or "locate_equalizer_goal_action" in gap_ids
        )
        for task in result["evidence_tasks"]:
            self.assertEqual(task["status"], "pending")
            self.assertNotEqual(task["status"], "verified")
            self.assertTrue(task.get("search_intervals"))
        scoreboard = next(t for t in result["evidence_tasks"] if t["kind"] == "scoreboard")
        self.assertEqual(scoreboard["anchor_status"], "score_path")
        self.assertIsNotNone(scoreboard["score_anchor_sec"])

    def test_croatia_setup_uses_search_intervals_not_midpoint(self) -> None:
        self.assertTrue(CROATIA.is_file(), f"missing {CROATIA}")
        result = run_story_json(str(CROATIA), dry_run=True, max_steps=20)
        self.assertEqual(result["status"], "planned")
        self.assertTrue(result["is_candidate"])
        setup = next(g for g in result["gaps"] if g["gap_id"] == "missing_setup_visual")
        self.assertEqual(setup["anchor_status"], "needs_search")
        self.assertGreaterEqual(len(setup["search_intervals"]), 2)
        span = setup["search_intervals"][-1]["end"] - setup["search_intervals"][0]["start"]
        self.assertGreater(span, 60.0)
        # 不再是首次比分旁 ~10s 单窗
        single = setup["search_intervals"][0]
        self.assertFalse(
            len(setup["search_intervals"]) == 1 and (single["end"] - single["start"]) <= 12
        )
        buildup = next(g for g in result["gaps"] if g["gap_id"] == "missing_buildup_visual")
        self.assertGreaterEqual(len(buildup["search_intervals"]), 2)
        task = next(t for t in result["evidence_tasks"] if t["gap_id"] == "missing_setup_visual")
        self.assertEqual(task["status"], "pending")
        self.assertTrue(task["adaptive_expand"])

    def test_none_emits_no_gaps_or_tasks(self) -> None:
        story = {
            "schema_version": "story-t01-1",
            "match_id": "dummy-none",
            "has_story": False,
            "is_candidate": False,
            "story_tier": "none",
            "story_label_zh": "无故事",
            "no_story_reason": "no_comeback",
            "recognition": {"present": False, "tier": "none", "beats": {}},
            "score_path": [],
            "events": [],
        }
        self.assertEqual(detect_gaps(story), [])
        result = solve(story, dry_run=True, max_steps=4)
        self.assertEqual(result["status"], "planned")
        self.assertEqual(result["gaps"], [])
        self.assertEqual(result["evidence_tasks"], [])
        self.assertTrue(result["structure_ok"], result.get("structure_problems"))
        self.assertFalse(result["verification_complete"])

    def test_budget_exhaustion_marks_unresolved(self) -> None:
        result = run_story_json(str(CROATIA), dry_run=True, max_steps=2)
        self.assertEqual(result["status"], "budget_exhausted")
        self.assertFalse(result["verification_complete"])
        self.assertTrue(result["structure_ok"], result.get("structure_problems"))
        for task in result["evidence_tasks"]:
            self.assertNotEqual(task["status"], "verified")
            self.assertNotIn(task["status"], ("pending", "running"))
            self.assertEqual(task["status"], "unresolved")

    def test_invalid_window_rejected(self) -> None:
        box = ToolBox({"duration_sec": 100.0, "duration_known": True, "gaps": []}, dry_run=True)
        with self.assertRaises(ToolArgumentError):
            box.normalize_arguments("inspect_story_window", {"start": 10, "end": 40})
        with self.assertRaises(ToolArgumentError):
            box.normalize_arguments("inspect_story_window", {"start": 90, "end": 110})
        with self.assertRaises(ToolArgumentError):
            box.normalize_arguments("read_scoreboard_window", {"start": 50, "end": 40})

    def test_pending_localization_when_goal_anchor_missing(self) -> None:
        story = {
            "schema_version": "story-t01-1",
            "match_id": "no-goal-events",
            "has_story": True,
            "is_candidate": False,
            "story_tier": "story",
            "protagonist_side": "left",
            "recognition": {
                "present": True,
                "tier": "story",
                "beats": {"铺垫": ["e1"], "蓄力": ["e2"], "转折": ["e3"], "高潮": ["e4"]},
            },
            "score_path": [
                {"t_sec": 10.0, "score": "0:0", "opening": True},
                {"t_sec": 100.0, "score": "0:1", "opening": False, "delta_side": "right"},
                {"t_sec": 200.0, "score": "1:1", "opening": False, "delta_side": "left"},
                {"t_sec": 300.0, "score": "2:1", "opening": False, "delta_side": "left"},
            ],
            "events": [],
            "duration_sec": 400.0,
        }
        gaps = detect_gaps(story, duration_sec=400.0)
        ids = {g["gap_id"] for g in gaps}
        self.assertIn("locate_equalizer_goal_action", ids)
        locate = next(g for g in gaps if g["gap_id"] == "locate_equalizer_goal_action")
        self.assertEqual(locate["anchor_status"], "pending_localization")
        self.assertIsNone(locate["goal_anchor_sec"])
        scoreboard = next(g for g in gaps if g["gap_id"] == "verify_equalizer_scoreboard")
        self.assertEqual(scoreboard["score_anchor_sec"], 200.0)

    def test_semantic_validation_rejects_fake_verified(self) -> None:
        payload = {
            "schema_version": "story-video-agent-plan-2a",
            "algorithm": "x",
            "status": "planned",
            "match_id": "m",
            "story_tier": "story",
            "evidence_tasks": [
                {
                    "task_id": "t1",
                    "gap_id": "g1",
                    "tool_hint": "coarse_search_interval",
                    "status": "verified",
                    "anchor_status": "needs_search",
                    "kind": "setup",
                    "search_intervals": [{"start": 0, "end": 10}],
                    "window": {"start": 0, "end": 10},
                }
            ],
            "gaps": [],
            "trace": [],
            "dry_run": True,
            "verification_complete": True,
        }
        problems = validate_plan_payload(payload)
        self.assertIn("dry_run_cannot_claim_verification_complete", problems)
        self.assertTrue(any("dry_run_verified_forbidden" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
