"""Phase 2A：本地媒体探测 / 抽帧 / 预算 / 多次落后比分。"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from story_video_agent.frames import FrameBudget, FrameStore, COARSE_MAX_SPAN, LOCAL_MAX_SPAN
from story_video_agent.media import MediaError, probe_video
from story_video_agent.runner import run_story_json, solve
from story_video_agent.state import _comeback_score_steps, detect_gaps
from story_video_agent.tools import ToolArgumentError, ToolBox

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "story_t01"
CROATIA = REPORTS / "2022-11-28 克罗地亚vs加拿大.json"
CROATIA_VIDEO = Path("/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4")


def _make_test_video(path: Path, *, duration: float = 30.0, fps: int = 10) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "ffmpeg required for Phase 2A tests"
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration}:size=320x240:rate={fps}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={duration}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not path.is_file():
        raise RuntimeError(proc.stderr or "ffmpeg test video failed")
    return path


class Phase2AMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.TemporaryDirectory(prefix="sva2a_")
        cls.video = _make_test_video(Path(cls._tmpdir.name) / "toy.mp4", duration=40.0)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmpdir.cleanup()

    def test_probe_ok_and_bad_video(self) -> None:
        info = probe_video(self.video)
        self.assertGreater(info.duration_sec, 35.0)
        self.assertEqual(info.width, 320)
        self.assertEqual(info.height, 240)
        self.assertGreater(info.fps, 0)
        with self.assertRaises(MediaError):
            probe_video("/no/such/video.mp4")
        with self.assertRaises(MediaError):
            probe_video("")
        bad = Path(self._tmpdir.name) / "not_video.txt"
        bad.write_text("hello", encoding="utf-8")
        with self.assertRaises(MediaError):
            probe_video(bad)

    def test_extract_and_cache(self) -> None:
        info = probe_video(self.video)
        out = Path(self._tmpdir.name) / "frames_cache"
        store = FrameStore(info, out_dir=out, budget=FrameBudget(max_frames=8))
        a = store.extract_at(1.0, gap_id="g1", tool="inspect_story_window")
        b = store.extract_at(1.0, gap_id="g2", tool="inspect_story_window")
        self.assertFalse(a.cached)
        self.assertTrue(b.cached)
        self.assertEqual(a.path, b.path)
        self.assertEqual(store.budget.used, 1)
        self.assertEqual(a.requested_media_sec, 1.0)
        self.assertIsNotNone(a.actual_media_sec)
        self.assertEqual(a.gap_id, "g1")
        self.assertTrue(Path(a.path).is_file())

    def test_oob_and_span_limits(self) -> None:
        info = probe_video(self.video)
        box = ToolBox(
            {
                "duration_sec": info.duration_sec,
                "duration_known": True,
                "gaps": [],
                "video_path": str(self.video),
            },
            dry_run=False,
            media_only=True,
            media_info=info,
            frame_store=FrameStore(
                info,
                out_dir=Path(self._tmpdir.name) / "frames_oob",
                budget=FrameBudget(8),
            ),
        )
        with self.assertRaises(ToolArgumentError):
            box.normalize_arguments("inspect_story_window", {"start": 1, "end": 1 + LOCAL_MAX_SPAN + 1})
        with self.assertRaises(ToolArgumentError):
            box.normalize_arguments(
                "coarse_search_interval",
                {"gap_id": "x", "start": 0, "end": COARSE_MAX_SPAN + 1},
            )
        with self.assertRaises(ToolArgumentError):
            box.normalize_arguments("inspect_story_window", {"start": 0, "end": info.duration_sec + 5})

    def test_unknown_duration_flag(self) -> None:
        box = ToolBox({"duration_sec": 0, "duration_known": False, "gaps": []}, dry_run=True)
        self.assertFalse(box.duration_known)
        # 未知时长不硬裁；仍要求 start < end
        args = box.normalize_arguments("inspect_story_window", {"start": 1, "end": 5})
        self.assertEqual(args["start"], 1.0)
        self.assertEqual(args["end"], 5.0)

    def test_frame_budget_stops(self) -> None:
        info = probe_video(self.video)
        store = FrameStore(
            info,
            out_dir=Path(self._tmpdir.name) / "frames_budget",
            budget=FrameBudget(max_frames=2),
        )
        store.extract_window(0.5, 8.0, gap_id="g", tool="inspect_story_window", count=2)
        self.assertEqual(store.budget.used, 2)
        with self.assertRaises(Exception):
            store.extract_at(9.0, gap_id="g", tool="inspect_story_window")

    def test_media_only_solve_marks_sampled_not_verified(self) -> None:
        story = {
            "schema_version": "story-t01-1",
            "match_id": "toy-media",
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
                {"t_sec": 1.0, "score": "0:0", "opening": True},
                {"t_sec": 5.0, "score": "0:1", "opening": False, "delta_side": "right"},
                {"t_sec": 12.0, "score": "1:1", "opening": False, "delta_side": "left"},
                {"t_sec": 20.0, "score": "2:1", "opening": False, "delta_side": "left"},
            ],
            "events": [
                {"event_id": "g1", "type": "进球", "story_role": "转折", "t_ms": 11000},
                {"event_id": "g2", "type": "进球", "story_role": "高潮", "t_ms": 19000},
            ],
        }
        frame_dir = Path(self._tmpdir.name) / "media_only_frames"
        manifest = Path(self._tmpdir.name) / "manifest.json"
        result = solve(
            story,
            video_path=str(self.video),
            dry_run=False,
            media_only=True,
            max_steps=20,
            frame_budget=12,
            frame_dir=str(frame_dir),
            manifest_path=str(manifest),
        )
        self.assertIn(result["status"], ("sampled", "planned", "frame_budget_exhausted"))
        self.assertTrue(result["media_only"])
        self.assertFalse(result["dry_run"])
        self.assertFalse(result["verification_complete"])
        self.assertTrue(result["structure_ok"], result.get("structure_problems"))
        self.assertGreater(result["diagnostics"]["frame_count"], 0)
        for task in result["evidence_tasks"]:
            self.assertNotEqual(task["status"], "verified")
            if task.get("frames"):
                self.assertEqual(task["status"], "sampled")
                for fr in task["frames"]:
                    self.assertIn("frame_id", fr)
                    self.assertIn("requested_media_sec", fr)
                    self.assertIn("actual_media_sec", fr)
                    self.assertIn("path", fr)
                    self.assertIn("gap_id", fr)
        self.assertTrue(manifest.is_file())

    def test_last_deficit_equalizer_not_first_tie(self) -> None:
        story = {
            "protagonist_side": "left",
            "score_path": [
                {"t_sec": 10, "score": "0:0"},
                {"t_sec": 100, "score": "0:1"},
                {"t_sec": 200, "score": "1:1"},
                {"t_sec": 300, "score": "1:2"},
                {"t_sec": 500, "score": "2:2"},
                {"t_sec": 800, "score": "3:2"},
            ],
        }
        steps = _comeback_score_steps(story)
        self.assertEqual(steps["equalizer"]["score"], "2:2")
        self.assertEqual(steps["equalizer"]["t_sec"], 500)
        self.assertEqual(steps["go_ahead"]["score"], "3:2")
        self.assertEqual(steps["behind_start"]["score"], "1:2")
        gaps = detect_gaps(
            {
                **story,
                "story_tier": "story",
                "recognition": {
                    "beats": {"铺垫": ["a"], "蓄力": ["b"], "转折": ["c"], "高潮": ["d"]}
                },
                "events": [],
            },
            duration_sec=900,
        )
        eq = next(g for g in gaps if g["gap_id"] == "verify_equalizer_scoreboard")
        self.assertEqual(eq["score_anchor_sec"], 500.0)

    def test_croatia_media_only_if_video_present(self) -> None:
        if not CROATIA.is_file() or not CROATIA_VIDEO.is_file():
            self.skipTest("croatia story/video not available")
        frame_dir = Path(self._tmpdir.name) / "croatia_frames"
        manifest = Path(self._tmpdir.name) / "croatia_manifest.json"
        result = run_story_json(
            str(CROATIA),
            video_path=str(CROATIA_VIDEO),
            dry_run=False,
            media_only=True,
            max_steps=30,
            frame_budget=8,
            frame_dir=str(frame_dir),
            manifest_path=str(manifest),
            max_coarse_per_gap=1,
        )
        self.assertFalse(result["verification_complete"])
        self.assertTrue(result["media_only"])
        self.assertGreaterEqual(result["diagnostics"]["frame_count"], 1)
        self.assertLessEqual(result["diagnostics"]["frame_budget_used"], 8)
        # 不得一次扫完 setup 的全部 search_intervals
        setup_frames = [
            fr
            for t in result["evidence_tasks"]
            if t.get("gap_id") == "missing_setup_visual"
            for fr in (t.get("frames") or [])
        ]
        setup_gap = next(g for g in result["gaps"] if g["gap_id"] == "missing_setup_visual")
        self.assertGreater(len(setup_gap["search_intervals"]), 5)
        # 粗搜配额限制：帧数远小于 intervals*4
        self.assertLessEqual(len(setup_frames), 8)


if __name__ == "__main__":
    unittest.main()
