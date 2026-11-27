"""Phase 4D：动态种子接入回归（无计费）。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_video_agent.phase4a_config import (
    SEED_MODE_CROATIA_LEGACY,
    SEED_MODE_STORY,
    resolve_seed_targets,
    seed_targets_from_story,
)
from story_video_agent.phase4a_optimize import preflight_phase4a

ROOT = Path(__file__).resolve().parents[2]
FRANCE_STORY = ROOT / "reports" / "story_t01" / "2022年11月23日 法国vs澳大利亚.json"
FRANCE_CAUSAL = ROOT / "data" / "交付_out" / "2022年11月23日 法国vs澳大利亚_causal.json"
CROATIA_STORY = ROOT / "reports" / "story_t01" / "2022-11-28 克罗地亚vs加拿大.json"
CROATIA_CAUSAL = ROOT / "data" / "交付_out" / "2022-11-28 克罗地亚vs加拿大_causal.json"
NO_COMEBACK = (
    ROOT
    / "reports"
    / "story_t01"
    / "10月4日_25-26赛季西甲第8轮_皇家奥维耶多VS莱万特_国语.json"
)


class FranceSeedRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not FRANCE_STORY.is_file():
            raise unittest.SkipTest(f"missing {FRANCE_STORY}")
        cls.story = json.loads(FRANCE_STORY.read_text(encoding="utf-8"))
        cls.causal = (
            json.loads(FRANCE_CAUSAL.read_text(encoding="utf-8"))
            if FRANCE_CAUSAL.is_file()
            else None
        )

    def test_france_seeds_not_croatia_hardcode(self) -> None:
        seeds = seed_targets_from_story(self.story, causal=self.causal)
        by_id = {s["target_id"]: s for s in seeds}
        self.assertIn("equalizer_goal", by_id)
        self.assertIn("go_ahead_goal", by_id)
        # 法国扳平 board≈2513，反超 board≈2904；不得落在克罗地亚 3065/3697
        self.assertAlmostEqual(float(by_id["equalizer_goal"]["score_anchor_sec"]), 2513.29, places=1)
        self.assertAlmostEqual(float(by_id["go_ahead_goal"]["score_anchor_sec"]), 2904.31, places=1)
        for tid in ("equalizer_goal", "go_ahead_goal"):
            seed = float(by_id[tid]["seed_center_sec"])
            board = float(by_id[tid]["score_anchor_sec"])
            self.assertGreaterEqual(abs(seed - board), 1.0)
            self.assertNotAlmostEqual(seed, 3065.903, places=0)
            self.assertNotAlmostEqual(seed, 3697.35, places=0)

    def test_preflight_uses_story_seeds(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            vid = Path(td) / "v.mp4"
            vid.write_bytes(b"\x00")
            pf = preflight_phase4a(
                mode="vlm-only",
                story_json=FRANCE_STORY,
                video_path=vid,
                force_mock=True,
                raise_on_problems=False,
                causal_json=FRANCE_CAUSAL if FRANCE_CAUSAL.is_file() else None,
                seed_mode=SEED_MODE_STORY,
                targets=("equalizer_goal", "go_ahead_goal"),
            )
        self.assertEqual(pf["seed_mode"], SEED_MODE_STORY)
        self.assertEqual(pf["seed_source"], "seed_targets_from_story")
        self.assertEqual(len(pf["seed_windows"]), 2)
        centers = {w["target_id"]: float(w["seed_center_sec"]) for w in pf["seed_windows"]}
        self.assertNotAlmostEqual(centers["equalizer_goal"], 3065.903, places=0)


class NoComebackSeedTests(unittest.TestCase):
    def test_synthetic_no_comeback_refuses_board_as_action(self) -> None:
        story = {
            "protagonist_side": "left",
            "score_path": [
                {"t_sec": 100.0, "score": "0:0", "delta_side": None},
                {"t_sec": 500.0, "score": "0:1", "delta_side": "right"},
            ],
            "events": [],
        }
        with self.assertRaises(ValueError) as ctx:
            seed_targets_from_story(story)
        self.assertIn("no equalizer/go_ahead", str(ctx.exception).lower())

    def test_real_no_comeback_story_file(self) -> None:
        if not NO_COMEBACK.is_file():
            self.skipTest(f"missing {NO_COMEBACK}")
        story = json.loads(NO_COMEBACK.read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            seed_targets_from_story(story)


class PreflightRunSeedConsistency(unittest.TestCase):
    def test_resolve_matches_preflight_for_croatia(self) -> None:
        if not CROATIA_STORY.is_file():
            self.skipTest("croatia story missing")
        story = json.loads(CROATIA_STORY.read_text(encoding="utf-8"))
        causal = (
            json.loads(CROATIA_CAUSAL.read_text(encoding="utf-8"))
            if CROATIA_CAUSAL.is_file()
            else None
        )
        resolved = resolve_seed_targets(
            ["equalizer_goal", "go_ahead_goal"],
            story=story,
            causal=causal,
            seed_mode=SEED_MODE_STORY,
        )
        with tempfile.TemporaryDirectory() as td:
            vid = Path(td) / "v.mp4"
            vid.write_bytes(b"\x00")
            pf = preflight_phase4a(
                mode="vlm-only",
                story_json=CROATIA_STORY,
                video_path=vid,
                force_mock=True,
                raise_on_problems=False,
                causal_json=CROATIA_CAUSAL if CROATIA_CAUSAL.is_file() else None,
                seed_mode=SEED_MODE_STORY,
            )
        pf_tuple = [
            (w["target_id"], round(float(w["seed_center_sec"]), 3), round(float(w["score_anchor_sec"]), 3))
            for w in pf["seed_windows"]
        ]
        run_tuple = [
            (t["target_id"], round(float(t["seed_center_sec"]), 3), round(float(t["score_anchor_sec"]), 3))
            for t in resolved
        ]
        self.assertEqual(pf_tuple, run_tuple)

    def test_legacy_mode_explicit(self) -> None:
        seeds = resolve_seed_targets(
            ["go_ahead_goal"], seed_mode=SEED_MODE_CROATIA_LEGACY
        )
        self.assertEqual(seeds[0]["target_id"], "go_ahead_goal")
        # legacy 窗过窄：3525 不在内
        win = seeds[0]["window"]
        self.assertFalse(float(win["start"]) <= 3525.0 <= float(win["end"]))

    def test_story_mode_requires_story(self) -> None:
        with self.assertRaises(ValueError):
            resolve_seed_targets(["equalizer_goal"], seed_mode=SEED_MODE_STORY, story=None)


if __name__ == "__main__":
    unittest.main()
