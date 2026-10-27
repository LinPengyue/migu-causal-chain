"""最小 dry-run：读 T01 → 生成证据任务 → 结构合法。"""

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


class DryRunTests(unittest.TestCase):
    def test_france_story_plans_scoreboard_and_reaction_tasks(self) -> None:
        self.assertTrue(FRANCE.is_file(), f"missing {FRANCE}")
        result = run_story_json(str(FRANCE), dry_run=True, max_steps=12)
        self.assertEqual(result["status"], "planned")
        self.assertTrue(result["dry_run"])
        self.assertTrue(result["structure_ok"], result.get("structure_problems"))
        self.assertEqual(validate_plan_payload(result), [])
        self.assertEqual(result["story_tier"], "story")
        gap_ids = {g["gap_id"] for g in result["gaps"]}
        self.assertIn("verify_equalizer_scoreboard", gap_ids)
        self.assertIn("verify_go_ahead_scoreboard", gap_ids)
        self.assertIn("post_climax_reaction", gap_ids)
        self.assertGreaterEqual(len(result["evidence_tasks"]), 3)
        for task in result["evidence_tasks"]:
            self.assertEqual(task["status"], "planned")
            self.assertIsNone(task["provider"])
            self.assertLess(task["window"]["start"], task["window"]["end"])

    def test_croatia_candidate_includes_setup_gap(self) -> None:
        self.assertTrue(CROATIA.is_file(), f"missing {CROATIA}")
        result = run_story_json(str(CROATIA), dry_run=True)
        self.assertEqual(result["status"], "planned")
        self.assertTrue(result["is_candidate"])
        gap_ids = {g["gap_id"] for g in result["gaps"]}
        self.assertIn("missing_setup_visual", gap_ids)
        task_gaps = {t["gap_id"] for t in result["evidence_tasks"]}
        self.assertIn("missing_setup_visual", task_gaps)

    def test_toolbox_rejects_bad_window_before_execute(self) -> None:
        box = ToolBox({"duration_sec": 100.0, "gaps": []}, dry_run=True)
        with self.assertRaises(ToolArgumentError):
            box.normalize_arguments("inspect_story_window", {"start": 10, "end": 40})

    def test_none_story_still_emits_valid_payload(self) -> None:
        story = {
            "schema_version": "story-t01-1",
            "match_id": "dummy",
            "has_story": False,
            "is_candidate": False,
            "story_tier": "none",
            "story_label_zh": "无故事",
            "no_story_reason": "no_comeback",
            "recognition": {"present": False, "tier": "none", "beats": {}},
            "score_path": [],
            "events": [],
            "duration_sec": 90.0,
        }
        gaps = detect_gaps(story)
        self.assertEqual(gaps[0]["gap_id"], "no_t01_arc")
        result = solve(story, dry_run=True, max_steps=4)
        self.assertTrue(result["structure_ok"])
        self.assertEqual(result["status"], "planned")


if __name__ == "__main__":
    unittest.main()
