"""Unit tests for video-driven P1/P2 (synthetic; no events JSON)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_chain.score_path import ScoreNode, find_comeback_arc
from story_video_agent.global_video_index import (
    build_index_from_synthetic_observations,
    observations_to_score_nodes,
    parse_scores_from_text,
)
from story_video_agent.story_discovery_video import (
    build_evidence_tasks,
    discover_and_write,
    discover_t01_from_score_timeline,
)


def _obs(t: float, a: int, b: int, status: str = "ok") -> dict:
    return {
        "t_sec": t,
        "status": status,
        "score": f"{a}:{b}",
        "score_tuple": (a, b),
        "confidence": 0.9,
    }


class TestScoreParse(unittest.TestCase):
    def test_loose_parse(self):
        self.assertIn((1, 0), parse_scores_from_text("1:0"))
        self.assertIn((2, 1), parse_scores_from_text("foo 2：1 bar"))


class TestDebounce(unittest.TestCase):
    def test_plus_one_comeback_path(self):
        # Croatia-like: 0:0 → 0:1 → 1:1 → 2:1 → 3:1
        obs = []
        for t, sc in [
            (10, (0, 0)),
            (20, (0, 0)),
            (100, (0, 1)),
            (110, (0, 1)),
            (200, (1, 1)),
            (210, (1, 1)),
            (300, (2, 1)),
            (310, (2, 1)),
            (400, (3, 1)),
            (410, (3, 1)),
        ]:
            obs.append(_obs(t, *sc))
        nodes, diag = observations_to_score_nodes(obs, confirm_hits=2, confirm_window_sec=60)
        self.assertGreaterEqual(len(nodes), 4)
        scores = [n.score for n in nodes]
        self.assertEqual(scores[0], (0, 0))
        self.assertIn((0, 1), scores)
        self.assertIn((1, 1), scores)
        self.assertIn((2, 1), scores)
        arc = find_comeback_arc(nodes)
        self.assertIsNotNone(arc)
        self.assertEqual(arc["protagonist_side"], "left")

    def test_ocr_noise_rejected(self):
        obs = [
            _obs(0, 0, 0),
            _obs(10, 0, 0),
            _obs(20, 5, 5),  # flash garbage
            _obs(30, 0, 0),
            _obs(40, 0, 0),
        ]
        nodes, diag = observations_to_score_nodes(obs, confirm_hits=2)
        self.assertTrue(any(d.get("rejected") == "not_plus_one" for d in diag))
        self.assertEqual(nodes[-1].score, (0, 0))

    def test_unconfirmed_single_hit(self):
        obs = [
            _obs(0, 0, 0),
            _obs(10, 0, 0),
            _obs(100, 1, 0),  # single hit only
            _obs(200, 0, 0),
        ]
        nodes, _ = observations_to_score_nodes(obs, confirm_hits=2, confirm_window_sec=30)
        self.assertEqual([n.score for n in nodes], [(0, 0)])


class TestDiscovery(unittest.TestCase):
    def test_story_grade_and_tasks(self):
        timeline = build_index_from_synthetic_observations(
            [
                _obs(0, 0, 0),
                _obs(5, 0, 0),
                _obs(100, 0, 1),
                _obs(105, 0, 1),
                _obs(200, 1, 1),
                _obs(205, 1, 1),
                _obs(300, 2, 1),
                _obs(305, 2, 1),
            ],
            duration_sec=400,
        )
        disc = discover_t01_from_score_timeline(timeline)
        self.assertEqual(disc["grade"], "story")
        self.assertEqual(disc["protagonist_side"], "left")
        self.assertFalse(disc["semantic_verified"])
        with tempfile.TemporaryDirectory() as td:
            out = discover_and_write(timeline, td)
            tasks = out["evidence_tasks"]["tasks"]
            ids = {t["task_id"] for t in tasks}
            self.assertIn("locate_equalizer_goal", ids)
            self.assertIn("locate_go_ahead_goal", ids)
            self.assertIn("locate_opponent_opening_goal", ids)
            self.assertTrue(all(t["evidence_status"] == "missing" for t in tasks))
            self.assertFalse(out["evidence_tasks"]["gates"]["render_ready"])
            # no events json leaked
            raw = Path(td, "story_evidence_tasks.json").read_text(encoding="utf-8")
            self.assertNotIn("交付", raw)

    def test_no_comeback(self):
        timeline = build_index_from_synthetic_observations(
            [
                _obs(0, 0, 0),
                _obs(5, 0, 0),
                _obs(100, 1, 0),
                _obs(105, 1, 0),
                _obs(200, 2, 0),
                _obs(205, 2, 0),
            ]
        )
        disc = discover_t01_from_score_timeline(timeline)
        self.assertEqual(disc["grade"], "none")

    def test_replay_like_jump_not_committed(self):
        # jump 0:0 → 3:1 is not plus-one
        timeline = build_index_from_synthetic_observations(
            [
                _obs(0, 0, 0),
                _obs(10, 0, 0),
                _obs(50, 3, 1),
                _obs(55, 3, 1),
                _obs(60, 0, 0),
            ]
        )
        self.assertLessEqual(len(timeline["nodes"]), 1)


class TestCliSynthetic(unittest.TestCase):
    def test_cli_synthetic(self):
        from story_video_agent.video_only_p1p2 import main

        with tempfile.TemporaryDirectory() as td:
            obs_path = Path(td) / "obs.json"
            obs = [
                _obs(0, 0, 0),
                _obs(5, 0, 0),
                _obs(80, 1, 0),
                _obs(85, 1, 0),
                _obs(160, 1, 1),
                _obs(165, 1, 1),
                _obs(240, 1, 2),
                _obs(245, 1, 2),
            ]
            obs_path.write_text(json.dumps(obs), encoding="utf-8")
            out = Path(td) / "out"
            code = main(["--synthetic-obs", str(obs_path), "--out-dir", str(out)])
            self.assertEqual(code, 0)
            self.assertTrue((out / "score_timeline.json").is_file())
            self.assertTrue((out / "story_discovery.json").is_file())
            self.assertTrue((out / "story_evidence_tasks.json").is_file())
            report = json.loads((out / "p1p2_run_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["discovery_grade"], "story")
            self.assertFalse(report["render_ready"])


if __name__ == "__main__":
    unittest.main()
