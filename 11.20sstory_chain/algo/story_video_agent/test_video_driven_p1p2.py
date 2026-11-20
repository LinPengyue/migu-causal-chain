"""Unit tests for video-driven P1/P2 (synthetic; no events JSON)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_chain.score_path import find_comeback_arc
from story_video_agent.global_video_index import (
    build_index_from_synthetic_observations,
    densify_centers_from_observations,
    observations_to_score_nodes,
    sample_times,
    sample_times_fullspan,
    sampling_coverage,
)
from story_video_agent.scoreboard_ocr import parse_score_candidates
from story_video_agent.story_discovery_video import (
    discover_and_write,
    discover_t01_from_score_timeline,
    dynamic_search_window,
)
from story_chain.score_path import ScoreNode


def _obs(t: float, a: int, b: int, status: str = "ok") -> dict:
    return {
        "t_sec": t,
        "status": status,
        "score": f"{a}:{b}",
        "score_tuple": (a, b),
        "confidence": 0.9,
        "scoreboard_detected": True,
    }


class TestSampling(unittest.TestCase):
    def test_fullspan_covers_end(self):
        times = sample_times(8000.0, step_sec=45.0, max_frames=80)
        cov = sampling_coverage(times, 8000.0)
        self.assertTrue(cov["fullspan"])
        self.assertGreaterEqual(times[-1], 8000 * 0.95)
        self.assertEqual(len(times), 80)

    def test_uniform_helper(self):
        times = sample_times_fullspan(100.0, max_frames=5)
        self.assertEqual(times[0], 0.0)
        self.assertAlmostEqual(times[-1], 99.95, places=1)

    def test_densify_on_unknowns(self):
        obs = [
            {"t_sec": 0, "status": "unknown"},
            {"t_sec": 100, "status": "unknown"},
            {"t_sec": 200, "status": "conflict"},
            {"t_sec": 300, "status": "unknown"},
        ]
        centers = densify_centers_from_observations(obs, 400.0)
        self.assertTrue(any(c > 0 for c in centers))


class TestScoreParse(unittest.TestCase):
    def test_reject_clock(self):
        p = parse_score_candidates("44:46")
        self.assertEqual(p["scores"], [])
        self.assertTrue(p["clocks"])

    def test_accept_score_and_v(self):
        self.assertIn((2, 1), parse_score_candidates("2:1")["scores"])
        self.assertIn((0, 1), parse_score_candidates("0 V 1")["scores"])
        self.assertIn((0, 0), parse_score_candidates("0-0")["scores"])
        self.assertIn((0, 0), parse_score_candidates("04:12 ITH 0 | 0 eee")["scores"])
        self.assertIn((2, 1), parse_score_candidates("克罗地亚 2 ho 1 加拿大")["scores"])


class TestDebounce(unittest.TestCase):
    def test_plus_one_comeback_path(self):
        obs = []
        for t, sc in [
            (10, (0, 0)),
            (20, (0, 0)),
            (30, (0, 0)),
            (100, (0, 1)),
            (110, (0, 1)),
            (120, (0, 1)),
            (200, (1, 1)),
            (210, (1, 1)),
            (220, (1, 1)),
            (300, (2, 1)),
            (310, (2, 1)),
            (320, (2, 1)),
        ]:
            obs.append(_obs(t, *sc))
        nodes, diag, meta = observations_to_score_nodes(obs, confirm_hits=2, establish_hits=2)
        self.assertTrue(meta["established"])
        self.assertGreaterEqual(len(nodes), 4)
        arc = find_comeback_arc(nodes)
        self.assertIsNotNone(arc)
        self.assertEqual(arc["protagonist_side"], "left")

    def test_no_assume_first_garbage(self):
        obs = [_obs(0, 4, 2), _obs(10, 0, 0), _obs(20, 0, 0), _obs(30, 0, 0)]
        nodes, _, meta = observations_to_score_nodes(obs, confirm_hits=2, establish_hits=3)
        self.assertTrue(meta["established"])
        self.assertEqual(nodes[0].score, (0, 0))

    def test_unestablished_stays_empty(self):
        obs = [_obs(0, 4, 2), _obs(100, 1, 0)]  # single hits only
        nodes, _, meta = observations_to_score_nodes(obs, confirm_hits=3, establish_hits=3)
        self.assertFalse(meta["established"])
        self.assertEqual(nodes, [])

    def test_ocr_noise_rejected(self):
        obs = [
            _obs(0, 0, 0),
            _obs(10, 0, 0),
            _obs(20, 0, 0),
            _obs(30, 5, 5),
            _obs(40, 0, 0),
            _obs(50, 0, 0),
        ]
        nodes, diag, _ = observations_to_score_nodes(obs, confirm_hits=2, establish_hits=2)
        self.assertEqual(nodes[-1].score, (0, 0))
        self.assertTrue(any("not_plus_one" in str(d.get("rejected", d.get("status", ""))) for d in diag))


class TestDiscovery(unittest.TestCase):
    def test_story_grade_and_tasks(self):
        timeline = build_index_from_synthetic_observations(
            [
                _obs(0, 0, 0),
                _obs(5, 0, 0),
                _obs(10, 0, 0),
                _obs(100, 0, 1),
                _obs(105, 0, 1),
                _obs(110, 0, 1),
                _obs(200, 1, 1),
                _obs(205, 1, 1),
                _obs(210, 1, 1),
                _obs(300, 2, 1),
                _obs(305, 2, 1),
                _obs(310, 2, 1),
            ],
            duration_sec=400,
            confirm_hits=2,
            establish_hits=2,
        )
        disc = discover_t01_from_score_timeline(timeline)
        self.assertEqual(disc["grade"], "story")
        with tempfile.TemporaryDirectory() as td:
            out = discover_and_write(timeline, td)
            tasks = out["evidence_tasks"]["tasks"]
            self.assertTrue(any(t["task_id"] == "locate_equalizer_goal" for t in tasks))
            eq = next(t for t in tasks if t["task_id"] == "locate_equalizer_goal")
            self.assertFalse(eq["search_media_range"].get("hard_bound", True))
            self.assertTrue(eq["search_media_range"].get("expandable"))

    def test_degraded_is_unresolved_not_none(self):
        timeline = {
            "nodes": [],
            "degraded": True,
            "degrade_reasons": ["no_usable_ocr"],
            "usable_ocr_count": 1,
            "observation_count": 8,
            "path_meta": {"established": False},
            "perception_quality": {"usable_score_obs_rate": 0.1},
        }
        disc = discover_t01_from_score_timeline(timeline)
        self.assertEqual(disc["grade"], "unresolved")

    def test_no_comeback_when_path_sufficient(self):
        timeline = build_index_from_synthetic_observations(
            [
                _obs(0, 0, 0),
                _obs(5, 0, 0),
                _obs(10, 0, 0),
                _obs(100, 1, 0),
                _obs(105, 1, 0),
                _obs(110, 1, 0),
                _obs(200, 2, 0),
                _obs(205, 2, 0),
                _obs(210, 2, 0),
            ],
            confirm_hits=2,
            establish_hits=2,
        )
        # mark not degraded
        timeline["degraded"] = False
        timeline["perception_quality"] = {"usable_score_obs_rate": 0.9}
        disc = discover_t01_from_score_timeline(timeline)
        self.assertEqual(disc["grade"], "none")

    def test_dynamic_window_uses_prev_stable(self):
        path = [
            ScoreNode(100, (0, 1), opening=True),
            ScoreNode(400, (1, 1), delta_side="left"),
        ]
        w = dynamic_search_window(path[1], path, duration_sec=1000)
        self.assertLessEqual(w["media_start_sec"], 100)
        self.assertFalse(w["hard_bound"])


class TestCliSynthetic(unittest.TestCase):
    def test_cli_synthetic(self):
        from story_video_agent.video_only_p1p2 import main

        with tempfile.TemporaryDirectory() as td:
            obs_path = Path(td) / "obs.json"
            obs = []
            for t, sc in [
                (0, (0, 0)),
                (5, (0, 0)),
                (10, (0, 0)),
                (80, (1, 0)),
                (85, (1, 0)),
                (90, (1, 0)),
                (160, (1, 1)),
                (165, (1, 1)),
                (170, (1, 1)),
                (240, (1, 2)),
                (245, (1, 2)),
                (250, (1, 2)),
            ]:
                obs.append(_obs(t, *sc))
            obs_path.write_text(json.dumps(obs), encoding="utf-8")
            out = Path(td) / "out"
            code = main(
                [
                    "--synthetic-obs",
                    str(obs_path),
                    "--out-dir",
                    str(out),
                    "--confirm-hits",
                    "2",
                    "--establish-hits",
                    "2",
                ]
            )
            self.assertEqual(code, 0)
            report = json.loads((out / "p1p2_run_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["discovery_grade"], "story")
            self.assertIn("commit_sha", report)


if __name__ == "__main__":
    unittest.main()
