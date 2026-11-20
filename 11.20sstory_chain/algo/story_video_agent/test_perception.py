"""Phase 2B：PTS、预算优先级、mock 感知闭环、API smoke 门控。"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from story_video_agent.api_provider import ApiProvider, api_enabled, smoke_enabled
from story_video_agent.frames import (
    FrameBudget,
    FrameStore,
    allocate_gap_caps,
    prioritize_gap_ids,
)
from story_video_agent.media import probe_video
from story_video_agent.memory import Memory
from story_video_agent.runner import run_story_json, solve
from story_video_agent.state import FRANCE_PERCEPTION_FOCUS, detect_gaps
from story_video_agent.vision_provider import VisionProvider

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "story_t01"
FRANCE = REPORTS / "2022年11月23日 法国vs澳大利亚.json"
CROATIA = REPORTS / "2022-11-28 克罗地亚vs加拿大.json"
CROATIA_VIDEO = Path("/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4")


def _make_test_video(path: Path, *, duration: float = 30.0, fps: int = 25) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg
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
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not path.is_file():
        raise RuntimeError(proc.stderr or "ffmpeg failed")
    return path


def _make_nonzero_start_video(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=6:size=160x120:rate=25",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-f",
        "mpegts",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not path.is_file():
        raise RuntimeError(proc.stderr or "ffmpeg mpegts failed")
    return path


def _france_like_story() -> dict:
    return {
        "schema_version": "story-t01-1",
        "match_id": "france-like-perception",
        "has_story": True,
        "is_candidate": False,
        "story_tier": "story",
        "protagonist_side": "left",
        "recognition": {
            "present": True,
            "tier": "story",
            "beats": {"铺垫": ["a"], "蓄力": ["b"], "转折": ["c"], "高潮": ["d"]},
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


class Phase2BTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.TemporaryDirectory(prefix="sva2b_")
        cls.video = _make_test_video(Path(cls._tmpdir.name) / "toy.mp4", duration=40.0)
        cls.nz_video = _make_nonzero_start_video(Path(cls._tmpdir.name) / "nz.ts")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmpdir.cleanup()

    def test_pts_not_confused_with_requested(self) -> None:
        info = probe_video(self.video)
        store = FrameStore(
            info,
            out_dir=Path(self._tmpdir.name) / "pts_frames",
            budget=FrameBudget(max_frames=4),
        )
        rec = store.extract_at(1.37, gap_id="g_pts", tool="inspect_story_window")
        self.assertEqual(rec.requested_media_sec, 1.37)
        self.assertEqual(rec.pts_status, "pts")
        self.assertIsNotNone(rec.actual_media_sec)
        self.assertNotEqual(rec.actual_media_sec, rec.requested_media_sec)
        self.assertIsNone(rec.match_logic_sec)
        self.assertEqual(rec.match_logic_status, "uncalibrated")

    def test_nonzero_start_time_not_used_as_match_logic(self) -> None:
        info = probe_video(self.nz_video)
        self.assertNotEqual(info.start_time_sec, 0.0)
        store = FrameStore(
            info,
            out_dir=Path(self._tmpdir.name) / "nz_frames",
            budget=FrameBudget(max_frames=2),
        )
        req = info.start_time_sec + 0.37
        if req >= info.duration_sec:
            self.skipTest("mpegts duration too short")
        rec = store.extract_at(req, gap_id="nz", tool="inspect_story_window")
        self.assertEqual(rec.media_start_time_sec, info.start_time_sec)
        self.assertIsNone(rec.match_logic_sec)
        self.assertEqual(rec.match_logic_status, "uncalibrated")

    def test_budget_prefers_goal_windows(self) -> None:
        ids = [
            "missing_setup_visual",
            "verify_equalizer_goal_action",
            "verify_go_ahead_scoreboard",
            "post_climax_reaction",
            "missing_buildup_visual",
        ]
        self.assertEqual(prioritize_gap_ids(ids)[0], "verify_equalizer_goal_action")
        caps = allocate_gap_caps(ids, global_budget=8)
        self.assertGreaterEqual(
            caps["verify_equalizer_goal_action"], caps["missing_setup_visual"]
        )
        self.assertEqual(sum(caps.values()), 8)

    def test_memory_rejects_verified_from_vlm(self) -> None:
        mem = Memory()
        mem.mark_sampled("g1")
        mem.mark_observed(
            "g1",
            {
                "gap_id": "g1",
                "fact_verified": False,
                "normalized_ok": True,
                "provider_mode": "mock",
                "frame_ids": ["f1"],
            },
        )
        self.assertEqual(mem.gap_stages["g1"], "observed")
        with self.assertRaises(ValueError):
            mem.set_stage("g1", "verified")

    def test_mock_api_provider_not_billed(self) -> None:
        api = ApiProvider(force_mock=True)
        out = api.plan_decision(
            system_prompt="x",
            user_prompt="y",
            mock_decision={"type": "answer", "answer": "finish_evidence_plan", "reason": "t"},
        )
        self.assertEqual(out["provider"], "mock")
        summary = api.stats.summary()
        self.assertEqual(summary["est_cost_usd_real"], 0.0)
        self.assertEqual(summary["total_tokens"], 0)

    def test_france_like_perception_loop_mock(self) -> None:
        story = _france_like_story()
        focus = list(FRANCE_PERCEPTION_FOCUS)
        ids = {g["gap_id"] for g in detect_gaps(story, duration_sec=40.0)}
        for gid in focus:
            self.assertIn(gid, ids)
        result = solve(
            story,
            video_path=str(self.video),
            dry_run=False,
            perception=True,
            force_mock_vlm=True,
            use_llm_planner=True,
            focus_gap_ids=focus,
            max_steps=24,
            frame_budget=12,
            frame_dir=str(Path(self._tmpdir.name) / "perc_frames"),
            manifest_path=str(Path(self._tmpdir.name) / "perc_manifest.json"),
        )
        self.assertTrue(result["perception"])
        self.assertFalse(result["verification_complete"])
        self.assertTrue(result["structure_ok"], result.get("structure_problems"))
        self.assertEqual(result["status"], "observed")
        self.assertEqual(len(result["evidence_tasks"]), 3)
        observed = [t for t in result["evidence_tasks"] if t["status"] == "observed"]
        self.assertEqual(len(observed), 3)
        for task in observed:
            ev = task["visual_evidence"]
            self.assertTrue(ev.get("observation_only"))
            self.assertFalse(ev.get("fact_verified"))
            self.assertTrue(ev.get("normalized_ok"))
            self.assertEqual(ev.get("provider_mode"), "mock")
            self.assertTrue(ev.get("frame_time_bindings"))
            for bind in ev["frame_time_bindings"]:
                self.assertIn("requested_media_sec", bind)
                self.assertIn("pts_status", bind)
        self.assertIn("api", result["diagnostics"])
        self.assertTrue(result["diagnostics"]["api"]["force_mock"])
        self.assertGreaterEqual(len(result.get("visual_evidence") or []), 1)

    def test_france_dryrun_focus_regression(self) -> None:
        self.assertTrue(FRANCE.is_file())
        result = run_story_json(str(FRANCE), dry_run=True, france_focus=True, max_steps=12)
        self.assertEqual(result["status"], "planned")
        self.assertEqual(
            {t["gap_id"] for t in result["evidence_tasks"]}, set(FRANCE_PERCEPTION_FOCUS)
        )
        self.assertFalse(result["verification_complete"])

    def test_croatia_setup_search_mock_if_video(self) -> None:
        if not CROATIA.is_file() or not CROATIA_VIDEO.is_file():
            self.skipTest("croatia assets missing")
        result = run_story_json(
            str(CROATIA),
            video_path=str(CROATIA_VIDEO),
            dry_run=False,
            perception=True,
            force_mock_vlm=True,
            focus_gap_ids=["missing_setup_visual"],
            max_steps=16,
            frame_budget=4,
            frame_dir=str(Path(self._tmpdir.name) / "croatia_setup"),
            manifest_path=str(Path(self._tmpdir.name) / "croatia_setup_manifest.json"),
        )
        self.assertEqual(result["focus_gap_ids"], ["missing_setup_visual"])
        self.assertFalse(result["verification_complete"])
        self.assertGreaterEqual(result["diagnostics"]["frame_count"], 1)
        # 不得扫完全部 search intervals
        setup = next(g for g in result["gaps"] if g["gap_id"] == "missing_setup_visual")
        self.assertGreater(len(setup["search_intervals"]), 5)
        self.assertLessEqual(result["diagnostics"]["frame_count"], 4)

    def test_api_smoke_gated(self) -> None:
        """真实 API smoke：仅 STORY_API_SMOKE=1 且密钥已配置时运行。"""
        if not smoke_enabled():
            self.skipTest("STORY_API_SMOKE not set — skip billed smoke")
        if not api_enabled():
            self.skipTest("STORY_API_ENABLE not set")
        api = ApiProvider(force_mock=False)
        if not api.configs["planner"].configured():
            self.skipTest("planner API key/model/base not configured")
        out = api.plan_decision(
            system_prompt="Reply with JSON {\"type\":\"answer\",\"answer\":\"finish_evidence_plan\",\"reason\":\"ok\"}",
            user_prompt="ping",
            mock_decision={"type": "answer", "answer": "finish_evidence_plan", "reason": "mock"},
        )
        self.assertIn(out["provider"], ("openai_compatible", "degraded_mock"))
        self.assertTrue(out.get("content"))


if __name__ == "__main__":
    unittest.main()
