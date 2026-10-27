"""Phase 4A：镜头搜索闭环、信任门控、Mock 回归（无计费）。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_video_agent.internal_verification import sanitize_plan_trust
from story_video_agent.phase4a_config import (
    Phase4AConfig,
    billing_allowed,
    croatia_seed_targets,
    phase4a_real_enabled,
)
from story_video_agent.phase4a_optimize import (
    Phase4AError,
    apply_search_to_plan,
    classify_observation_labels,
    compare_plans,
    preflight_phase4a,
    rule_decide_next_window,
    run_phase4a,
)
from story_video_agent.media import MediaInfo
from story_video_agent.story_output_schema import SCHEMA_VERSION
from story_video_agent.test_media import _make_test_video

ROOT = Path(__file__).resolve().parents[2]
CROATIA_STORY = ROOT / "reports" / "story_t01" / "2022-11-28 克罗地亚vs加拿大.json"
CROATIA_PLAN = ROOT / "reports" / "story_compose_phase3a1_croatia.json"
CROATIA_VIDEO = Path("/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4")


def _toy_media(dur: float = 100.0) -> MediaInfo:
    return MediaInfo(
        path="/virtual.mp4",
        duration_sec=dur,
        width=320,
        height=240,
        fps=10.0,
        video_codec="h264",
        audio_codec="aac",
        start_time_sec=0.0,
        format_name="mp4",
        size_bytes=1,
    )


class Phase4AGateTests(unittest.TestCase):
    def test_billing_off_by_default(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("STORY_")}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertFalse(phase4a_real_enabled())
            self.assertFalse(billing_allowed())

    def test_real_preflight_requires_flags(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            story = Path(td) / "s.json"
            story.write_text("{}", encoding="utf-8")
            vid = Path(td) / "v.mp4"
            vid.write_bytes(b"x")
            with mock.patch.dict(os.environ, {}, clear=False):
                # clear phase4a flags
                os.environ.pop("STORY_PHASE4A_REAL", None)
                os.environ.pop("STORY_API_ENABLE", None)
                os.environ.pop("STORY_API_SMOKE", None)
                with self.assertRaises(Phase4AError):
                    preflight_phase4a(
                        mode="vlm-only",
                        story_json=story,
                        video_path=vid,
                        force_mock=False,
                    )

    def test_mock_preflight_ok(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            story = Path(td) / "s.json"
            story.write_text("{}", encoding="utf-8")
            vid = _make_test_video(Path(td) / "v.mp4", duration=5.0)
            pf = preflight_phase4a(
                mode="vlm-only",
                story_json=story,
                video_path=vid,
                force_mock=True,
            )
            self.assertTrue(pf["ok"])
            self.assertTrue(pf["force_mock"])


class Phase4ALogicTests(unittest.TestCase):
    def test_classify_labels(self) -> None:
        lab = classify_observation_labels(
            {
                "observed_actions": ["shot", "goal"],
                "story_relation": "possible goal",
                "confidence": 0.7,
                "normalized_ok": True,
                "frame_ids": ["f1"],
                "provider_mode": "mock",
            }
        )
        self.assertIn("shot", lab["labels"])
        self.assertIn("goal", lab["labels"])
        self.assertFalse(lab["fact_verified"])
        self.assertTrue(lab["observation_only"])

    def test_rule_expand_on_unrelated(self) -> None:
        target = croatia_seed_targets()[0]
        media = _toy_media(8000.0)
        dec = rule_decide_next_window(
            target=target,
            window=target["window"],
            labels={
                "labels": ["unrelated"],
                "primary": "unrelated",
                "confidence": 0.1,
            },
            media=media,
            cfg=Phase4AConfig(),
            round_idx=0,
        )
        self.assertIn(dec["action"], ("expand", "shift_earlier"))

    def test_forged_verified_stripped_on_apply(self) -> None:
        plan = {
            "schema_version": SCHEMA_VERSION,
            "algorithm": "t01_story_composer_phase3a1",
            "match_id": "toy",
            "template_id": "T01_comeback",
            "story_tier": "candidate",
            "segments": [
                {
                    "segment_id": "seg_equalizer_goal_action",
                    "beat": "转折",
                    "role": "equalizer_goal_action",
                    "media_in": 10.0,
                    "media_out": 20.0,
                    "time_status": "linked_event_ms",
                    "shot_kind": "live",
                    "render_eligibility": "candidate_only",
                    "blocking_reasons": [],
                    "time_provenance": {"pipeline_verified": False},
                    "event_ids": ["e1"],
                    "frame_ids": [],
                    "narrative_order": 1,
                    "source_media_order": 10.0,
                }
            ],
            "evidence_refs": [],
            "candidate_edl": [],
            "render_ready_edl": [],
            "render_ready": False,
            "diagnostics": {},
        }
        search = {
            "target_id": "equalizer_goal",
            "role": "equalizer_goal_action",
            "seed_center_sec": 15.0,
            "seed_window": {"start": 10.0, "end": 20.0},
            "best": {
                "window": {"start": 12.0, "end": 18.0},
                "labels": {
                    "labels": ["goal", "shot"],
                    "confidence": 0.8,
                    "frame_ids": ["f1"],
                    "provider_mode": "mock",
                },
                "evidence": {
                    "gap_id": "verify_equalizer_goal_action",
                    "provider_mode": "mock",
                    "normalized_ok": True,
                    "pipeline_verified": True,  # forged — must not elevate
                    "fact_verified": True,
                    "frame_ids": ["f1"],
                    "confidence": 0.8,
                    "observed_actions": ["goal"],
                },
            },
        }
        cfg = Phase4AConfig(allow_mock_window_adjust=True)
        out = apply_search_to_plan(plan, [search], cfg=cfg)
        self.assertFalse(out["render_ready"])
        self.assertEqual(out["render_ready_edl"], [])
        seg = out["segments"][0]
        self.assertEqual(seg["media_in"], 12.0)
        self.assertNotEqual(seg.get("render_eligibility"), "render_ready")
        prov = seg.get("time_provenance") or {}
        self.assertFalse(prov.get("pipeline_verified"))
        self.assertIsNone(prov.get("granted_by"))

    def test_compare_plans(self) -> None:
        v1 = {
            "segments": [
                {
                    "segment_id": "a",
                    "media_in": 1,
                    "media_out": 2,
                    "render_eligibility": "candidate_only",
                }
            ],
            "candidate_edl": [{}],
            "render_ready": False,
        }
        v2 = {
            "segments": [
                {
                    "segment_id": "a",
                    "media_in": 3,
                    "media_out": 5,
                    "render_eligibility": "candidate_only",
                    "role": "equalizer_goal_action",
                }
            ],
            "candidate_edl": [{}, {}],
            "render_ready": False,
            "diagnostics": {"phase4a": {"updates": []}},
        }
        c = compare_plans(v1, v2)
        self.assertEqual(len(c["windows_changed"]), 1)


class Phase4AIntegrationMock(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.TemporaryDirectory(prefix="sva4a_")
        cls.video = _make_test_video(
            Path(cls._tmpdir.name) / "toy.mp4", duration=40.0
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmpdir.cleanup()

    def test_run_mock_pipeline_synthetic(self) -> None:
        """合成视频 + Mock VLM：完整搜索/回填/预览路径。"""
        # 迷你 story + plan 指向合成视频时间轴
        story = {
            "match_id": "toy",
            "story_tier": "story",
            "protagonist_side": "left",
            "has_story": True,
            "recognition": {"tier": "story", "beats": {}},
            "score_path": [
                {"t_sec": 10.0, "score": "0:1", "delta_side": "right"},
                {"t_sec": 20.0, "score": "1:1", "delta_side": "left", "carrier_event_id": "g"},
                {"t_sec": 30.0, "score": "2:1", "delta_side": "left", "carrier_event_id": "g2"},
            ],
            "events": [
                {
                    "event_id": "g",
                    "type": "进球",
                    "t_ms": 15000,
                    "is_replay": False,
                    "story_role": "转折",
                    "source": "delivery_event",
                },
                {
                    "event_id": "g2",
                    "type": "进球",
                    "t_ms": 25000,
                    "is_replay": False,
                    "story_role": "高潮",
                    "source": "delivery_event",
                },
            ],
        }
        story_path = Path(self._tmpdir.name) / "story.json"
        story_path.write_text(json.dumps(story), encoding="utf-8")
        out = Path(self._tmpdir.name) / "out"
        # patch seeds to synthetic times
        with mock.patch(
            "story_video_agent.phase4a_optimize.croatia_seed_targets",
            return_value=[
                {
                    "target_id": "equalizer_goal",
                    "role": "equalizer_goal_action",
                    "beat": "转折",
                    "gap_id": "verify_equalizer_goal_action",
                    "kind": "action_verify",
                    "seed_center_sec": 15.0,
                    "score_anchor_sec": 20.0,
                    "seed_note": "toy seed",
                    "window": {"start": 12.0, "end": 18.0},
                    "segment_id_hints": ["seg_equalizer_goal_action"],
                }
            ],
        ):
            cfg = Phase4AConfig(
                mode="vlm-only",
                force_mock=True,
                max_rounds=2,
                frames_per_round=2,
                frame_budget=8,
            )
            report = run_phase4a(
                story_json=story_path,
                video_path=self.video,
                out_dir=out,
                cfg=cfg,
                render_preview=True,
            )
        self.assertFalse(report["real_api_executed"])
        self.assertEqual(report["api_mode"], "mock")
        self.assertTrue(Path(report["plan_v2_path"]).is_file())
        self.assertTrue((out / "croatia_preview_v2.mp4").is_file())
        plan = json.loads(Path(report["plan_v2_path"]).read_text(encoding="utf-8"))
        self.assertFalse(plan["render_ready"])
        # 模型 forged 字段不可信
        cleaned = sanitize_plan_trust(plan)
        self.assertFalse(cleaned["render_ready"])


@unittest.skipUnless(CROATIA_VIDEO.is_file() and CROATIA_PLAN.is_file(), "Croatia assets missing")
class Phase4ACroatiaMock(unittest.TestCase):
    def test_croatia_mock_optimize_preview_v2(self) -> None:
        out = ROOT / "_local_render" / "phase4a"
        out.mkdir(parents=True, exist_ok=True)
        v1_sum = ROOT / "_local_render" / "phase3b" / "croatia_preview_summary.json"
        cfg = Phase4AConfig(
            mode="vlm-only",
            force_mock=True,
            max_rounds=2,
            frames_per_round=2,
            frame_budget=12,
        )
        report = run_phase4a(
            story_json=CROATIA_STORY,
            video_path=CROATIA_VIDEO,
            plan_json=CROATIA_PLAN,
            out_dir=out,
            cfg=cfg,
            render_preview=True,
            v1_preview_summary=v1_sum if v1_sum.is_file() else None,
        )
        self.assertFalse(report["real_api_executed"])
        self.assertTrue(Path(report["report_path"]).is_file())
        self.assertTrue((out / "croatia_preview_v2.mp4").is_file())
        # also write markdown-friendly compare snippet
        (out / "compare_v1_v2.json").write_text(
            json.dumps(report.get("comparison") or {}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
