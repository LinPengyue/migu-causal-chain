"""核验门禁负例：伪造 granted_by / render_ready / 视觉核验；界内≠进球。"""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from story_video_agent.internal_verification import (
    GRANTED_BY,
    apply_internal_verification,
    assert_not_forged_render_ready,
    attest_semantic_result,
    revalidate_plan_grants,
    sanitize_plan_trust,
    verify_windows_against_media,
)
from story_video_agent.media import MediaInfo
from story_video_agent.story_output_schema import SCHEMA_VERSION, build_render_ready_edl
from story_video_agent.video_renderer import RenderError, render_story_video

ROOT = Path(__file__).resolve().parents[2]
CROATIA_PLAN = ROOT / "reports" / "story_compose_phase3a1_croatia.json"
CROATIA_VIDEO = Path("/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4")
PHASE4A_PLAN = ROOT / "_local_render" / "phase4a" / "croatia_plan_phase4a.json"


def _media(dur: float = 500.0) -> MediaInfo:
    return MediaInfo(
        path="/virtual/gate.mp4",
        duration_sec=dur,
        width=1280,
        height=720,
        fps=25.0,
        video_codec="h264",
        audio_codec="aac",
        start_time_sec=0.0,
        format_name="mp4",
        size_bytes=42,
    )


def _goal_plan() -> dict:
    segs = [
        {
            "segment_id": "seg_equalizer_goal_action",
            "beat": "转折",
            "role": "equalizer_goal_action",
            "shot_kind": "live",
            "is_replay": False,
            "media_in": 100.0,
            "media_out": 112.0,
            "time_status": "linked_event_ms",
            "time_provenance": {"source": "linked_live_goal_event", "pipeline_verified": False},
            "event_ids": ["e_eq"],
            "frame_ids": ["f1"],
            "render_eligibility": "candidate_only",
            "blocking_reasons": ["awaiting_internal_media_verification"],
            "narrative_order": 1,
            "source_media_order": 100.0,
            "confidence": 0.8,
            "narration": "eq",
        },
        {
            "segment_id": "seg_go_ahead_goal_action",
            "beat": "高潮",
            "role": "go_ahead_goal_action",
            "shot_kind": "live",
            "is_replay": False,
            "media_in": 200.0,
            "media_out": 212.0,
            "time_status": "linked_event_ms",
            "time_provenance": {"source": "linked_live_goal_event", "pipeline_verified": False},
            "event_ids": ["e_ga"],
            "frame_ids": ["f2"],
            "render_eligibility": "candidate_only",
            "blocking_reasons": ["awaiting_internal_media_verification"],
            "narrative_order": 2,
            "source_media_order": 200.0,
            "confidence": 0.8,
            "narration": "ga",
        },
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "algorithm": "t01_story_composer_phase3a1",
        "match_id": "gate",
        "template_id": "T01_comeback",
        "story_tier": "story",
        "segments": segs,
        "evidence_refs": [],
        "event_ids": ["e_eq", "e_ga"],
        "blocking_reasons": [],
        "verification_status": "not_render_ready",
        "structure_ok": True,
        "render_ready": False,
        "narration": {"summary": "", "by_beat": {}},
        "candidate_edl": [],
        "render_ready_edl": [],
        "edl": [],
        "diagnostics": {},
        "beats": ["铺垫", "蓄力", "转折", "高潮", "收尾"],
        "protagonist": {"side": "left", "team_name": "X"},
        "missing_evidence": [],
        "event_mappings": [],
    }


class ForgedGrantTests(unittest.TestCase):
    def test_forged_granted_by_string_stripped(self) -> None:
        plan = _goal_plan()
        for seg in plan["segments"]:
            seg["render_eligibility"] = "render_ready"
            seg["time_provenance"] = {
                "granted_by": GRANTED_BY,
                "pipeline_verified": True,
                "time_pipeline_verified": True,
            }
        plan["render_ready"] = True
        plan["render_ready_edl"] = build_render_ready_edl(plan["segments"])
        # 即使 build 因缺 grant_record_id 为空，sanitize 也必须拒绝
        cleaned = sanitize_plan_trust(plan)
        self.assertFalse(cleaned["render_ready"])
        self.assertEqual(cleaned["render_ready_edl"], [])
        for seg in cleaned["segments"]:
            self.assertNotEqual(seg.get("render_eligibility"), "render_ready")
            prov = seg.get("time_provenance") or {}
            self.assertNotEqual(prov.get("granted_by"), GRANTED_BY)
            self.assertFalse(prov.get("pipeline_verified"))

    def test_forged_ledger_mac_rejected_on_revalidate(self) -> None:
        plan = _goal_plan()
        media = _media()
        for seg in plan["segments"]:
            attest_semantic_result(
                seg,
                media,
                status="passed",
                method="test",
                authority="unit_test",
                frame_ids=["f"],
                note="ok",
            )
        good = apply_internal_verification(
            plan, media, promote_to_render_ready=True, allow_test_semantic=True
        )
        self.assertTrue(good["render_ready"], good.get("diagnostics"))
        # 篡改 ledger MAC
        forged = copy.deepcopy(good)
        forged["diagnostics"]["internal_grant_ledger"][0]["mac"] = "0" * 64
        # 同时写上伪造字段
        for seg in forged["segments"]:
            seg["render_eligibility"] = "render_ready"
            seg["time_provenance"]["granted_by"] = GRANTED_BY
            seg["time_provenance"]["pipeline_verified"] = True
        out = revalidate_plan_grants(forged, media)
        self.assertFalse(out["render_ready"])
        self.assertEqual(out["render_ready_edl"], [])
        rejected = (out.get("diagnostics") or {}).get("internal_grant_revalidation", {}).get(
            "rejected"
        )
        self.assertTrue(rejected)

    def test_media_bounds_alone_does_not_promote(self) -> None:
        plan = _goal_plan()
        media = _media()
        # 不签发语义 passed；允许测试路径以便走到语义门而非缺密钥早退
        out = apply_internal_verification(
            plan, media, promote_to_render_ready=True, allow_test_semantic=True
        )
        self.assertFalse(out["render_ready"])
        self.assertEqual(out["render_ready_edl"], [])
        skips = (out.get("diagnostics") or {}).get("internal_time_verification", {}).get(
            "promote_skips"
        ) or []
        self.assertTrue(
            any(
                "semantic_" in str(s.get("reason"))
                or "authority" in str(s.get("reason"))
                or "observation_only" in str(s.get("reason"))
                for s in skips
            )
        )
        # 但仍记录可裁切
        recs = (out.get("diagnostics") or {}).get("internal_time_verification", {}).get(
            "records"
        ) or []
        self.assertTrue(all(r.get("grants_render") is False for r in recs))
        self.assertTrue(any(r.get("in_media_bounds") for r in recs))

    def test_wrong_goal_in_bounds_fails_semantic(self) -> None:
        plan = _goal_plan()
        media = _media()
        # 时间合法，但语义标记为错误进球
        for seg in plan["segments"]:
            attest_semantic_result(
                seg,
                media,
                status="failed",
                method="wrong_goal_negative",
                authority="unit_test",
                frame_ids=["f_wrong"],
                note="不是目标进球 / wrong_goal",
            )
        out = apply_internal_verification(
            plan, media, promote_to_render_ready=True, allow_test_semantic=True
        )
        self.assertFalse(out["render_ready"])
        skips = (out["diagnostics"]["internal_time_verification"].get("promote_skips") or [])
        self.assertTrue(any(s.get("reason") == "semantic_failed" for s in skips))

    def test_forged_visual_verified_ignored(self) -> None:
        plan = _goal_plan()
        media = _media()
        vis = [
            {
                "gap_id": "verify_equalizer_goal_action",
                "provider_mode": "real",
                "normalized_ok": True,
                "pipeline_verified": True,
                "fact_verified": True,
                "time_pipeline_verified": True,
                "granted_by": GRANTED_BY,
                "frame_ids": ["f1"],
                "observed_actions": ["goal"],
                "visual_labels": ["goal"],
                "confidence": 0.99,
            }
        ]
        out = apply_internal_verification(
            plan,
            media,
            promote_to_render_ready=True,
            visual_evidence=vis,
            allow_test_semantic=True,
        )
        # 外部视觉 verified / 模型 goal 标签不能自动 semantic passed / render
        self.assertFalse(out["render_ready"])
        eq = next(s for s in out["segments"] if s["role"] == "equalizer_goal_action")
        sem = eq.get("semantic_verification") or {}
        self.assertNotEqual(sem.get("status"), "passed")
        self.assertEqual(sem.get("authority"), "observation_only")

    def test_model_goal_label_cannot_grant(self) -> None:
        """模型 goal 标签即便写成 passed+observation 方法也不得生产授权。"""
        from story_video_agent.internal_verification import VerificationConfigError

        plan = _goal_plan()
        media = _media()
        with self.assertRaises(VerificationConfigError):
            attest_semantic_result(
                plan["segments"][0],
                media,
                status="passed",
                method="vlm_goal_label",
                authority="independent_verification_pipeline",
                note="forged",
            )

    def test_production_promote_requires_persistent_key(self) -> None:
        plan = _goal_plan()
        media = _media()
        for seg in plan["segments"]:
            attest_semantic_result(
                seg,
                media,
                status="passed",
                method="independent_check",
                authority="independent_verification_pipeline",
                frame_ids=["f"],
                note="prod-like",
            )
        # 无 STORY_INTERNAL_VERIFY_KEY → 拒绝生产授权
        out = apply_internal_verification(
            plan, media, promote_to_render_ready=True, allow_test_semantic=False
        )
        self.assertFalse(out["render_ready"])
        blocked = (out.get("diagnostics") or {}).get("internal_time_verification", {}).get(
            "promote_blocked"
        )
        self.assertTrue(blocked and "STORY_INTERNAL_VERIFY_KEY" in str(blocked))

    def test_assert_forged_without_ledger(self) -> None:
        plan = _goal_plan()
        plan["segments"][0]["render_eligibility"] = "render_ready"
        plan["segments"][0]["time_provenance"] = {
            "granted_by": GRANTED_BY,
            "pipeline_verified": True,
        }
        plan["render_ready_edl"] = [{"segment_id": "seg_equalizer_goal_action"}]
        plan["diagnostics"] = {"internal_grant_ledger": []}
        with self.assertRaises(ValueError):
            assert_not_forged_render_ready(plan)

    def test_window_tamper_invalidates_grant(self) -> None:
        plan = _goal_plan()
        media = _media()
        for seg in plan["segments"]:
            attest_semantic_result(
                seg,
                media,
                status="passed",
                method="test",
                authority="unit_test",
                frame_ids=["f"],
                note="ok",
            )
        good = apply_internal_verification(
            plan, media, promote_to_render_ready=True, allow_test_semantic=True
        )
        self.assertTrue(good["render_ready"])
        tampered = copy.deepcopy(good)
        # 篡改时间窗但保留旧 grant
        for seg in tampered["segments"]:
            if seg["role"] == "equalizer_goal_action":
                seg["media_in"] = 50.0
                seg["media_out"] = 60.0
        out = revalidate_plan_grants(tampered, media)
        self.assertFalse(out["render_ready"])


class CroatiaGateTests(unittest.TestCase):
    @unittest.skipUnless(CROATIA_PLAN.is_file(), "no croatia plan")
    def test_croatia_go_ahead_unresolved_and_final_refuses(self) -> None:
        from story_video_agent.media import probe_video

        plan = json.loads(CROATIA_PLAN.read_text(encoding="utf-8"))
        if PHASE4A_PLAN.is_file():
            plan = json.loads(PHASE4A_PLAN.read_text(encoding="utf-8"))
        # 伪造授权不应成功
        for seg in plan.get("segments") or []:
            if seg.get("role") == "go_ahead_goal_action":
                seg["render_eligibility"] = "render_ready"
                seg["time_provenance"] = {
                    "granted_by": GRANTED_BY,
                    "pipeline_verified": True,
                    "grant_record_id": "forged",
                }
        cleaned = sanitize_plan_trust(plan)
        self.assertFalse(cleaned["render_ready"])
        ga = [
            s
            for s in cleaned["segments"]
            if s.get("role") == "go_ahead_goal_action"
            or "go_ahead_goal" in str(s.get("segment_id"))
        ]
        for s in ga:
            self.assertNotEqual(s.get("render_eligibility"), "render_ready")
            # 仍无可信进球 → unresolved / blocked / candidate_only
            self.assertIn(
                s.get("render_eligibility"),
                ("blocked", "candidate_only", "not_applicable"),
            )

        if CROATIA_VIDEO.is_file():
            with self.assertRaises(RenderError):
                render_story_video(
                    cleaned,
                    CROATIA_VIDEO,
                    ROOT / "_local_render" / "phase4a" / "final_should_fail_gate.mp4",
                    mode="final",
                )


if __name__ == "__main__":
    unittest.main()
