"""Phase 4C：从 Story JSON 生成搜索目标（无计费）。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from story_video_agent.phase4a_config import (
    CROATIA_SEED_EQUALIZER_LIVE_SEC,
    CROATIA_SEED_GO_AHEAD_BOARD_SEC,
    croatia_seed_targets,
    seed_targets_from_story,
    select_seed_targets,
)

ROOT = Path(__file__).resolve().parents[2]
CROATIA_STORY = ROOT / "reports" / "story_t01" / "2022-11-28 克罗地亚vs加拿大.json"
CROATIA_CAUSAL = ROOT / "data" / "交付_out" / "2022-11-28 克罗地亚vs加拿大_causal.json"


class SeedFromStoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not CROATIA_STORY.is_file():
            raise unittest.SkipTest(f"missing {CROATIA_STORY}")
        cls.story = json.loads(CROATIA_STORY.read_text(encoding="utf-8"))
        cls.causal = (
            json.loads(CROATIA_CAUSAL.read_text(encoding="utf-8"))
            if CROATIA_CAUSAL.is_file()
            else None
        )

    def test_equalizer_seed_from_story_goal_event(self) -> None:
        seeds = seed_targets_from_story(self.story, causal=self.causal)
        by_id = {s["target_id"]: s for s in seeds}
        self.assertIn("equalizer_goal", by_id)
        eq = by_id["equalizer_goal"]
        self.assertAlmostEqual(float(eq["seed_center_sec"]), CROATIA_SEED_EQUALIZER_LIVE_SEC, places=2)
        self.assertAlmostEqual(float(eq["score_anchor_sec"]), 3145.98, places=2)
        self.assertEqual(eq["seed_provenance"]["source"], "story_events")

    def test_go_ahead_prefers_causal_goal_not_board_shot(self) -> None:
        seeds = seed_targets_from_story(self.story, causal=self.causal)
        ga = {s["target_id"]: s for s in seeds}["go_ahead_goal"]
        # board 3697.35；causal Goal @3523.574 应优于 board-40 fallback
        self.assertLess(float(ga["seed_center_sec"]), float(ga["score_anchor_sec"]) - 50.0)
        self.assertAlmostEqual(float(ga["score_anchor_sec"]), CROATIA_SEED_GO_AHEAD_BOARD_SEC, places=2)
        # 不得把 3697.35 射门当动作中心
        self.assertGreater(abs(float(ga["seed_center_sec"]) - 3697.35), 5.0)
        if self.causal:
            self.assertEqual(ga["seed_provenance"]["source"], "causal_chain")
            self.assertAlmostEqual(float(ga["seed_center_sec"]), 3523.574, places=2)

    def test_legacy_croatia_hardcode_window_too_narrow_for_this_match(self) -> None:
        legacy = {t["target_id"]: t for t in croatia_seed_targets()}["go_ahead_goal"]
        # 3525 live 落在 legacy 窗外 → 证明需通用化扩大搜索
        live = 3525.0
        self.assertFalse(
            float(legacy["window"]["start"])
            <= live
            <= float(legacy["window"]["end"])
        )
        generalized = {
            t["target_id"]: t
            for t in seed_targets_from_story(self.story, causal=self.causal)
        }["go_ahead_goal"]
        self.assertTrue(
            float(generalized["window"]["start"])
            <= live
            <= float(generalized["window"]["end"])
        )

    def test_select_prefer_story_vs_hardcode(self) -> None:
        hard = select_seed_targets(["go_ahead_goal"], prefer_story=False)[0]
        story_driven = select_seed_targets(
            ["go_ahead_goal"], story=self.story, causal=self.causal, prefer_story=True
        )[0]
        self.assertNotAlmostEqual(
            float(hard["seed_center_sec"]),
            float(story_driven["seed_center_sec"]),
            places=0,
        )

    def test_synthetic_match_without_hardcoded_croatia_times(self) -> None:
        story = {
            "protagonist_side": "left",
            "score_path": [
                {"t_sec": 100.0, "score": "0:1", "delta_side": None},
                {"t_sec": 500.0, "score": "1:1", "delta_side": "left"},
                {"t_sec": 800.0, "score": "2:1", "delta_side": "left"},
            ],
            "events": [
                {
                    "event_id": "g1",
                    "type": "进球",
                    "t_ms": 430000.0,
                    "is_replay": False,
                    "story_role": "转折",
                }
            ],
        }
        seeds = seed_targets_from_story(story)
        by_id = {s["target_id"]: s for s in seeds}
        self.assertAlmostEqual(float(by_id["equalizer_goal"]["seed_center_sec"]), 430.0, places=2)
        # go_ahead 无 goal 事件 → board-40 fallback + 宽窗
        ga = by_id["go_ahead_goal"]
        self.assertAlmostEqual(float(ga["seed_center_sec"]), 760.0, places=2)
        self.assertLessEqual(float(ga["window"]["start"]), 600.0)


if __name__ == "__main__":
    unittest.main()
