"""Phase 3B：信任边界、preview/final 隔离、合成视频裁切、克罗地亚 preview。"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from story_video_agent.internal_verification import (
    GRANTED_BY,
    apply_internal_verification,
    assert_not_forged_render_ready,
    sanitize_plan_trust,
    strip_external_trust_flags,
)
from story_video_agent.media import probe_video
from story_video_agent.narrative_composer import compose_story_plan
from story_video_agent.review_assist import (
    build_review_manifest,
    import_review_decisions,
)
from story_video_agent.story_output_schema import SCHEMA_VERSION, validate_render_ready
from story_video_agent.video_renderer import RenderError, render_story_video

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "story_t01"
CROATIA_STORY = REPORTS / "2022-11-28 克罗地亚vs加拿大.json"
CROATIA_PLAN = ROOT / "reports" / "story_compose_phase3a1_croatia.json"
CROATIA_VIDEO = Path("/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4")
LOCAL_RENDER = ROOT / "_local_render" / "phase3b"


def _ffmpeg() -> str:
    p = shutil.which("ffmpeg")
    assert p, "ffmpeg required"
    return p


def _make_video(
    path: Path,
    *,
    duration: float = 20.0,
    fps: int = 10,
    size: str = "320x240",
    with_audio: bool = True,
    bitrate: str = "500k",
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = _ffmpeg()
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration}:size={size}:rate={fps}",
    ]
    if with_audio:
        cmd += [
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration}",
            "-c:v",
            "libx264",
            "-b:v",
            bitrate,
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
        ]
    else:
        cmd += [
            "-c:v",
            "libx264",
            "-b:v",
            bitrate,
            "-pix_fmt",
            "yuv420p",
            "-an",
        ]
    cmd.append(str(path))
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not path.is_file():
        raise RuntimeError(proc.stderr or "ffmpeg failed")
    return path


def _toy_plan(*, with_windows: bool = True) -> dict:
    segs = [
        {
            "segment_id": "seg_a",
            "beat": "转折",
            "role": "equalizer_goal_action",
            "shot_kind": "live",
            "is_replay": False,
            "media_in": 2.0 if with_windows else None,
            "media_out": 5.0 if with_windows else None,
            "time_status": "linked_event_ms" if with_windows else "pending_localization",
            "time_provenance": {
                "source": "linked_live_goal_event",
                "pipeline_verified": False,
            },
            "event_ids": ["e1"],
            "frame_ids": [],
            "linked_live_event_id": None,
            "narrative_order": 1,
            "source_media_order": 2.0 if with_windows else None,
            "render_eligibility": "candidate_only",
            "blocking_reasons": ["awaiting_internal_media_verification"],
            "confidence": 0.8,
            "narration": "eq",
        },
        {
            "segment_id": "seg_b",
            "beat": "高潮",
            "role": "go_ahead_goal_action",
            "shot_kind": "live",
            "is_replay": False,
            "media_in": 8.0 if with_windows else None,
            "media_out": 11.0 if with_windows else None,
            "time_status": "linked_event_ms" if with_windows else "pending_localization",
            "time_provenance": {
                "source": "linked_live_goal_event",
                "pipeline_verified": False,
            },
            "event_ids": ["e2"],
            "frame_ids": [],
            "linked_live_event_id": None,
            "narrative_order": 2,
            "source_media_order": 8.0 if with_windows else None,
            "render_eligibility": "candidate_only",
            "blocking_reasons": ["awaiting_internal_media_verification"],
            "confidence": 0.8,
            "narration": "ga",
        },
        {
            "segment_id": "seg_pending",
            "beat": "蓄力",
            "role": "buildup",
            "shot_kind": "unknown",
            "is_replay": False,
            "media_in": None,
            "media_out": None,
            "time_status": "pending_localization",
            "time_provenance": {"source": "none", "pipeline_verified": False},
            "event_ids": [],
            "frame_ids": [],
            "linked_live_event_id": None,
            "narrative_order": 3,
            "source_media_order": None,
            "render_eligibility": "blocked",
            "blocking_reasons": ["missing"],
            "confidence": 0.0,
            "narration": "pending",
        },
    ]
    from story_video_agent.story_output_schema import (
        build_candidate_edl,
        build_render_ready_edl,
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "algorithm": "t01_story_composer_phase3a1",
        "match_id": "toy",
        "template_id": "T01_comeback",
        "story_tier": "story",
        "protagonist": {"side": "left", "team_name": "Toy"},
        "beats": ["铺垫", "蓄力", "转折", "高潮", "收尾"],
        "segments": segs,
        "evidence_refs": [],
        "event_ids": ["e1", "e2"],
        "event_mappings": [],
        "missing_evidence": [],
        "blocking_reasons": [],
        "verification_status": "not_render_ready",
        "structure_ok": True,
        "render_ready": False,
        "narration": {"summary": "toy", "by_beat": {}},
        "candidate_edl": build_candidate_edl(segs),
        "render_ready_edl": build_render_ready_edl(segs),
        "edl": build_candidate_edl(segs),
        "diagnostics": {},
    }


class Phase3BTrustTests(unittest.TestCase):
    def test_strip_external_trust(self) -> None:
        obj = {
            "pipeline_verified": True,
            "time_pipeline_verified": True,
            "nested": {"fact_verified": True, "keep": 1},
        }
        cleaned = strip_external_trust_flags(obj)
        self.assertNotIn("pipeline_verified", cleaned)
        self.assertNotIn("time_pipeline_verified", cleaned)
        self.assertNotIn("fact_verified", cleaned["nested"])
        self.assertEqual(cleaned["nested"]["keep"], 1)

    def test_forged_render_ready_stripped(self) -> None:
        plan = _toy_plan()
        plan["segments"][0]["render_eligibility"] = "render_ready"
        plan["segments"][0]["time_provenance"] = {
            "pipeline_verified": True,
            "granted_by": "external_json",
        }
        plan["render_ready_edl"] = [
            {"segment_id": "seg_a", "media_in": 1, "media_out": 2}
        ]
        plan["render_ready"] = True
        cleaned = sanitize_plan_trust(plan)
        self.assertFalse(cleaned["render_ready"])
        self.assertEqual(cleaned["render_ready_edl"], [])
        self.assertEqual(
            cleaned["segments"][0]["render_eligibility"], "candidate_only"
        )
        with self.assertRaises(ValueError):
            forged = _toy_plan()
            forged["segments"][0]["render_eligibility"] = "render_ready"
            forged["segments"][0]["time_provenance"] = {
                "pipeline_verified": True,
            }
            forged["render_ready_edl"] = [{"segment_id": "seg_a"}]
            assert_not_forged_render_ready(forged)

    def test_external_vis_cannot_compose_render_ready(self) -> None:
        story = {
            "match_id": "toy",
            "story_tier": "story",
            "protagonist_side": "left",
            "has_story": True,
            "recognition": {
                "tier": "story",
                "beats": {"转折": ["g_eq"], "高潮": ["g_ga"]},
            },
            "score_path": [
                {"t_sec": 100.0, "score": "0:1", "delta_side": "right"},
                {
                    "t_sec": 200.0,
                    "score": "1:1",
                    "delta_side": "left",
                    "carrier_event_id": "g_eq",
                },
                {
                    "t_sec": 300.0,
                    "score": "2:1",
                    "delta_side": "left",
                    "carrier_event_id": "g_ga",
                },
            ],
            "events": [
                {
                    "event_id": "g_eq",
                    "type": "进球",
                    "t_ms": 195000,
                    "is_replay": False,
                    "story_role": "转折",
                    "source": "delivery_event",
                },
                {
                    "event_id": "g_ga",
                    "type": "进球",
                    "t_ms": 295000,
                    "is_replay": False,
                    "story_role": "高潮",
                    "source": "delivery_event",
                },
            ],
        }
        vis = [
            {
                "gap_id": "verify_equalizer_goal_action",
                "provider_mode": "real",
                "normalized_ok": True,
                "pipeline_verified": True,
                "time_pipeline_verified": True,
                "frame_ids": ["f"],
            },
            {
                "gap_id": "verify_go_ahead_goal_action",
                "provider_mode": "real",
                "normalized_ok": True,
                "pipeline_verified": True,
                "time_pipeline_verified": True,
                "frame_ids": ["f2"],
            },
        ]
        plan = compose_story_plan(story, visual_evidence=vis, use_llm=False)
        self.assertFalse(plan["render_ready"])
        self.assertEqual(plan["render_ready_edl"], [])


class Phase3BRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.TemporaryDirectory(prefix="sva3b_")
        base = Path(cls._tmpdir.name)
        cls.video = _make_video(base / "toy.mp4", duration=20.0, bitrate="400k")
        cls.video_hi = _make_video(
            base / "toy_hi.mp4", duration=15.0, bitrate="2000k", size="640x360"
        )
        cls.video_no_audio = _make_video(
            base / "toy_na.mp4", duration=12.0, with_audio=False
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmpdir.cleanup()

    def test_preview_cut_and_placeholder(self) -> None:
        out = Path(self._tmpdir.name) / "preview.mp4"
        plan = _toy_plan()
        # 重复镜头
        plan["candidate_edl"].append(dict(plan["candidate_edl"][0]))
        plan["candidate_edl"][-1]["edl_index"] = 99
        plan["candidate_edl"][-1]["narrative_order"] = 4
        result = render_story_video(
            plan, self.video, out, mode="preview", work_dir=Path(self._tmpdir.name) / "w1"
        )
        self.assertTrue(out.is_file())
        self.assertGreater(result["n_cut"], 0)
        self.assertGreaterEqual(result["n_placeholder"], 1)
        info = probe_video(out)
        self.assertEqual(info.width, 1280)
        self.assertEqual(info.height, 720)
        self.assertGreater(info.duration_sec, 1.0)
        self.assertTrue(result["evidence_unchanged"])
        self.assertFalse(result["render_ready"])

    def test_out_of_bounds_becomes_placeholder_in_preview(self) -> None:
        plan = _toy_plan()
        plan["segments"][0]["media_in"] = 1000.0
        plan["segments"][0]["media_out"] = 1010.0
        plan["candidate_edl"][0]["media_in"] = 1000.0
        plan["candidate_edl"][0]["media_out"] = 1010.0
        out = Path(self._tmpdir.name) / "oob.mp4"
        result = render_story_video(
            plan, self.video, out, mode="preview", work_dir=Path(self._tmpdir.name) / "w_oob"
        )
        oob = next(s for s in result["segments"] if s["segment_id"] == "seg_a")
        self.assertTrue(oob["placeholder"] or oob.get("skip_reason"))
        self.assertTrue(out.is_file())

    def test_no_audio_and_bitrate_mix_via_reencode(self) -> None:
        plan = _toy_plan()
        out = Path(self._tmpdir.name) / "na.mp4"
        result = render_story_video(
            plan,
            self.video_no_audio,
            out,
            mode="preview",
            work_dir=Path(self._tmpdir.name) / "w_na",
            max_clip_sec=2.0,
        )
        self.assertTrue(out.is_file())
        self.assertGreater(result["n_cut"], 0)

    def test_empty_edl_fails(self) -> None:
        plan = _toy_plan()
        plan["candidate_edl"] = []
        plan["segments"] = []
        with self.assertRaises(RenderError):
            render_story_video(
                plan,
                self.video,
                Path(self._tmpdir.name) / "empty.mp4",
                mode="preview",
            )

    def test_none_tier_refused(self) -> None:
        plan = _toy_plan()
        plan["story_tier"] = "none"
        with self.assertRaises(RenderError):
            render_story_video(
                plan, self.video, Path(self._tmpdir.name) / "none.mp4", mode="preview"
            )

    def test_final_hard_fail_without_render_ready(self) -> None:
        plan = _toy_plan()
        self.assertFalse(plan["render_ready"])
        with self.assertRaises(RenderError) as ctx:
            render_story_video(
                plan,
                self.video,
                Path(self._tmpdir.name) / "final_bad.mp4",
                mode="final",
            )
        self.assertIn("hard-fail", str(ctx.exception).lower())

    def test_final_ok_after_internal_promote(self) -> None:
        plan = _toy_plan()
        media = probe_video(self.video)
        promoted = apply_internal_verification(
            plan, media, promote_to_render_ready=True
        )
        self.assertTrue(promoted["render_ready"], promoted.get("diagnostics"))
        out = Path(self._tmpdir.name) / "final_ok.mp4"
        result = render_story_video(
            promoted,
            self.video,
            out,
            mode="final",
            work_dir=Path(self._tmpdir.name) / "w_final",
            max_clip_sec=2.0,
        )
        self.assertTrue(out.is_file())
        self.assertEqual(result["mode"], "final")
        self.assertEqual(result["n_placeholder"], 0)

    def test_import_cannot_elevate(self) -> None:
        plan = _toy_plan()
        updated = import_review_decisions(
            plan,
            [
                {
                    "segment_id": "seg_a",
                    "human_confirmed": True,
                    "grant_render_ready": True,
                    "render_eligibility": "render_ready",
                }
            ],
        )
        self.assertFalse(updated["render_ready"])
        self.assertEqual(updated["render_ready_edl"], [])
        self.assertNotEqual(
            updated["segments"][0].get("render_eligibility"), "render_ready"
        )
        rej = updated["diagnostics"]["review_import"]["rejected_elevations"]
        self.assertTrue(rej)

    def test_review_manifest_orders(self) -> None:
        plan = _toy_plan()
        out_dir = Path(self._tmpdir.name) / "review"
        man = build_review_manifest(plan, self.video, out_dir)
        self.assertTrue(Path(man["path"]).is_file())
        self.assertTrue(man.get("contact_sheet"))
        for seg in man["segments"]:
            self.assertIn("narrative_order", seg)
            self.assertIn("source_media_order", seg)
            self.assertIn("order_note", seg)


@unittest.skipUnless(CROATIA_VIDEO.is_file(), "Croatia match video not mounted")
@unittest.skipUnless(CROATIA_PLAN.is_file() or CROATIA_STORY.is_file(), "no croatia plan")
class Phase3BCroatiaPreview(unittest.TestCase):
    def test_croatia_short_preview(self) -> None:
        if CROATIA_PLAN.is_file():
            plan = json.loads(CROATIA_PLAN.read_text(encoding="utf-8"))
        else:
            story = json.loads(CROATIA_STORY.read_text(encoding="utf-8"))
            plan = compose_story_plan(story, use_llm=False)

        LOCAL_RENDER.mkdir(parents=True, exist_ok=True)
        out = LOCAL_RENDER / "croatia_preview_short.mp4"
        work = LOCAL_RENDER / "work_croatia"
        result = render_story_video(
            plan,
            CROATIA_VIDEO,
            out,
            mode="preview",
            work_dir=work,
            max_clip_sec=3.0,
            placeholder_sec=2.0,
        )
        self.assertTrue(out.is_file())
        self.assertGreater(result["n_cut"] + result["n_placeholder"], 0)
        info = probe_video(out)
        summary = {
            "out_mp4": str(out),
            "duration_sec": info.duration_sec,
            "width": info.width,
            "height": info.height,
            "fps": info.fps,
            "n_segments": result["n_segments"],
            "n_cut": result["n_cut"],
            "n_placeholder": result["n_placeholder"],
            "segments": [
                {
                    "segment_id": s["segment_id"],
                    "beat": s["beat"],
                    "media_in": s["media_in"],
                    "media_out": s["media_out"],
                    "cut": s["cut"],
                    "placeholder": s["placeholder"],
                    "source_media_order": s.get("source_media_order"),
                    "narrative_order": s.get("narrative_order"),
                }
                for s in result["segments"]
            ],
            "ffmpeg_ok": all(r.get("returncode") == 0 for r in result["ffmpeg_log"]),
        }
        (LOCAL_RENDER / "croatia_preview_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # final must refuse
        with self.assertRaises(RenderError):
            render_story_video(
                plan,
                CROATIA_VIDEO,
                LOCAL_RENDER / "croatia_final_should_fail.mp4",
                mode="final",
            )

        man = build_review_manifest(
            plan, CROATIA_VIDEO, LOCAL_RENDER / "croatia_review", max_segments=6
        )
        self.assertTrue(Path(man["path"]).is_file())
        self.assertTrue(man.get("contact_sheet"))


if __name__ == "__main__":
    unittest.main()
