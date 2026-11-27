"""Phase 3A.1：事件溯源、EDL 门禁、伪造 verified、多次落后。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from story_video_agent.event_mapping import (
    find_live_goal_candidates,
    index_story_events,
    link_score_carrier,
)
from story_video_agent.narrative_composer import _find_score_milestones, compose_story_plan
from story_video_agent.state import _comeback_score_steps
from story_video_agent.story_output_schema import (
    SCHEMA_VERSION,
    validate_compose_plan,
    validate_render_ready,
)
from story_video_agent.story_verifier import (
    check_narration_grounding,
    classify_visual_evidence,
    verify_story,
)

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "story_t01"
FRANCE = REPORTS / "2022年11月23日 法国vs澳大利亚.json"
CROATIA = REPORTS / "2022-11-28 克罗地亚vs加拿大.json"
NONE = next(REPORTS.glob("01_1*.json"), None)


class Phase3A1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.france = json.loads(FRANCE.read_text(encoding="utf-8"))
        cls.croatia = json.loads(CROATIA.read_text(encoding="utf-8"))

    def test_france_carrier_not_blind_link(self) -> None:
        events = index_story_events(self.france)
        behind = _comeback_score_steps(self.france)["behind_start"]
        link = link_score_carrier(
            carrier_event_id=behind.get("carrier_event_id"),
            score_node=behind,
            events=events,
        )
        self.assertEqual(link["status"], "unresolved_mapping")
        self.assertTrue(any("time_mismatch" in r for r in link["reasons"]))
        self.assertTrue(any("助攻" in r or "type_incompatible" in r for r in link["reasons"]))

    def test_france_setup_excludes_bad_replay(self) -> None:
        plan = compose_story_plan(self.france, use_llm=False)
        setup = next(s for s in plan["segments"] if s["segment_id"] == "seg_setup_deficit")
        self.assertNotIn("event_000027", setup.get("event_ids") or [])
        self.assertEqual(setup["shot_kind"], "scoreboard_anchor")
        self.assertEqual(setup["time_status"], "score_path_only")
        # 不得再有把 2450s 回放挂到铺垫的 segment
        bad = [
            s
            for s in plan["segments"]
            if s.get("beat") == "铺垫"
            and "event_000027" in (s.get("event_ids") or [])
        ]
        self.assertEqual(bad, [])
        mappings = [
            m for m in plan["event_mappings"] if m.get("context") == "behind_score"
        ]
        self.assertEqual(mappings[0]["status"], "unresolved_mapping")

    def test_milestones_match_phase2a_last_arc(self) -> None:
        a = _comeback_score_steps(self.france)
        b = _find_score_milestones(self.france, "left")
        self.assertEqual(a["equalizer"], b["equalizer"])
        self.assertEqual(a["go_ahead"], b["go_ahead"])
        self.assertEqual(a["behind_start"], b["behind"])

    def test_multiple_deficits_uses_last_arc(self) -> None:
        story = {
            "story_tier": "story",
            "protagonist_side": "left",
            "has_story": True,
            "recognition": {"tier": "story", "beats": {}},
            "events": [],
            "score_path": [
                {"t_sec": 100, "score": "0:1", "delta_side": "right", "carrier_event_id": "c1"},
                {"t_sec": 200, "score": "1:1", "delta_side": "left", "carrier_event_id": "c2"},
                {"t_sec": 300, "score": "1:2", "delta_side": "right", "carrier_event_id": "c3"},
                {"t_sec": 400, "score": "2:2", "delta_side": "left", "carrier_event_id": "c4"},
                {"t_sec": 500, "score": "3:2", "delta_side": "left", "carrier_event_id": "c5"},
            ],
        }
        steps = _find_score_milestones(story, "left")
        self.assertEqual(steps["behind"]["t_sec"], 300)  # last deficit spell start
        self.assertEqual(steps["equalizer"]["score"], "2:2")
        self.assertEqual(steps["go_ahead"]["score"], "3:2")

    def test_score_path_not_goal_time(self) -> None:
        plan = compose_story_plan(self.france, use_llm=False)
        eq_goal = [
            s for s in plan["segments"] if s.get("role") == "equalizer_goal_action"
        ]
        self.assertTrue(eq_goal)
        # 无 live goal → pending；不得用 2513 score 冒充进球成片
        self.assertEqual(eq_goal[0]["time_status"], "pending_localization")
        self.assertEqual(eq_goal[0]["render_eligibility"], "blocked")
        self.assertFalse(plan["render_ready"])
        self.assertEqual(plan["render_ready_edl"], [])

    def test_candidate_vs_render_edl(self) -> None:
        plan = compose_story_plan(self.france, use_llm=False)
        self.assertTrue(plan["candidate_edl"])
        self.assertEqual(plan["render_ready_edl"], [])
        for row in plan["candidate_edl"]:
            if row.get("time_status") in (
                "score_path_only",
                "pending_localization",
                "pending_review",
                "event_ms",
            ):
                self.assertNotEqual(row.get("render_eligibility"), "render_ready")

    def test_event_id_collision(self) -> None:
        story = {
            "story_tier": "candidate",
            "protagonist_side": "left",
            "recognition": {"tier": "candidate", "beats": {}},
            "score_path": [
                {"t_sec": 10, "score": "0:1", "delta_side": "right", "carrier_event_id": "dup"},
                {"t_sec": 20, "score": "1:1", "delta_side": "left", "carrier_event_id": "g1"},
            ],
            "events": [
                {
                    "event_id": "dup",
                    "type": "进球",
                    "t_ms": 10000,
                    "is_replay": False,
                    "source": "delivery_event",
                },
                {
                    "event_id": "dup",
                    "type": "助攻",
                    "t_ms": 999999,
                    "is_replay": True,
                    "source": "causal_chain",
                },
            ],
        }
        events = index_story_events(story)
        self.assertTrue(events["dup"].get("_id_collision"))
        link = link_score_carrier(
            carrier_event_id="dup",
            score_node=story["score_path"][0],
            events=events,
        )
        self.assertEqual(link["status"], "unresolved_mapping")
        self.assertIn("event_id_collision", link["reasons"])

    def test_forged_verified_rejected(self) -> None:
        cl = classify_visual_evidence(
            {
                "gap_id": "g",
                "fact_verified": True,
                "normalized_ok": True,
                "provider_mode": "real",
                "frame_ids": ["f1"],
            }
        )
        self.assertTrue(cl["forged_verified_flag"])
        self.assertNotEqual(cl["kind"], "verified")
        self.assertFalse(cl["used_as_fact"])
        rep = verify_story(
            self.croatia,
            visual_evidence=[
                {
                    "gap_id": "g",
                    "fact_verified": True,
                    "normalized_ok": True,
                    "provider_mode": "real",
                    "frame_ids": ["f1"],
                }
            ],
        )
        self.assertTrue(
            any(c.get("type") == "forged_verified_flag" for c in rep["conflicts"])
        )

    def test_pipeline_verified_can_render(self) -> None:
        """外部 JSON 的 pipeline_verified 无效；须经 internal_verification 授予。"""
        from story_video_agent.internal_verification import (
            GRANTED_BY,
            apply_internal_verification,
            attest_semantic_result,
        )
        from story_video_agent.media import MediaInfo

        story = {
            "match_id": "toy",
            "story_tier": "story",
            "protagonist_side": "left",
            "has_story": True,
            "recognition": {
                "tier": "story",
                "beats": {"蓄力": [], "转折": ["g_eq"], "高潮": ["g_ga"]},
            },
            "score_path": [
                {
                    "t_sec": 100.0,
                    "score": "0:1",
                    "delta_side": "right",
                    "carrier_event_id": "",
                },
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
                    "score_context": "1:1",
                },
                {
                    "event_id": "g_ga",
                    "type": "进球",
                    "t_ms": 295000,
                    "is_replay": False,
                    "story_role": "高潮",
                    "source": "delivery_event",
                    "score_context": "2:1",
                },
                {
                    "event_id": "end",
                    "type": "比赛结束",
                    "t_ms": 400000,
                    "is_replay": False,
                    "story_role": "收尾",
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
                "frame_ids": ["f_eq"],
            },
            {
                "gap_id": "verify_go_ahead_goal_action",
                "provider_mode": "real",
                "normalized_ok": True,
                "pipeline_verified": True,
                "time_pipeline_verified": True,
                "frame_ids": ["f_ga"],
            },
        ]
        plan = compose_story_plan(story, visual_evidence=vis, use_llm=False)
        self.assertEqual(plan["schema_version"], SCHEMA_VERSION)
        # 外部字段不得直接成片
        self.assertFalse(plan["render_ready"], plan["blocking_reasons"])
        self.assertEqual(plan["render_ready_edl"], [])
        # 内部核验 + 虚拟媒体边界（覆盖候选窗）
        media = MediaInfo(
            path="/virtual/toy.mp4",
            duration_sec=600.0,
            width=1280,
            height=720,
            fps=25.0,
            video_codec="h264",
            audio_codec="aac",
            start_time_sec=0.0,
            format_name="mp4",
            size_bytes=1,
        )
        # 界内可裁切 ≠ 语义通过；须内部语义签发后再 promote
        for seg in plan["segments"]:
            if seg.get("role") in (
                "equalizer_goal_action",
                "go_ahead_goal_action",
            ):
                attest_semantic_result(
                    seg,
                    media,
                    status="passed",
                    method="test_attestation",
                    authority="unit_test",
                    frame_ids=list(seg.get("frame_ids") or ["f_test"]),
                    note="unit-test semantic pass",
                )
        promoted = apply_internal_verification(
            plan, media, promote_to_render_ready=True, allow_test_semantic=True
        )
        self.assertTrue(promoted["render_ready"], promoted.get("diagnostics"))
        self.assertTrue(promoted["render_ready_edl"])
        roles = {r.get("role") for r in promoted["render_ready_edl"]}
        self.assertIn("equalizer_goal_action", roles)
        self.assertIn("go_ahead_goal_action", roles)
        for row in promoted["render_ready_edl"]:
            self.assertEqual(row.get("granted_by"), GRANTED_BY)
            self.assertTrue(row.get("grant_record_id"))
        ok, problems = validate_render_ready(promoted)
        self.assertTrue(ok, problems)
        # 仅写 granted_by 字符串的 JSON 不能再抬升
        forged = json.loads(json.dumps(promoted))
        forged["diagnostics"]["internal_grant_ledger"] = []
        for seg in forged["segments"]:
            if seg.get("role") == "equalizer_goal_action":
                seg["time_provenance"] = {
                    "granted_by": GRANTED_BY,
                    "pipeline_verified": True,
                }
                seg["render_eligibility"] = "render_ready"
        from story_video_agent.internal_verification import sanitize_plan_trust

        cleaned = sanitize_plan_trust(forged)
        self.assertFalse(cleaned["render_ready"])
        self.assertEqual(cleaned["render_ready_edl"], [])

    def test_replay_requires_live_link_for_render(self) -> None:
        plan = compose_story_plan(self.france, use_llm=False)
        for seg in plan["segments"]:
            if seg.get("shot_kind") == "replay_supplement":
                self.assertNotEqual(seg.get("render_eligibility"), "render_ready")
                if seg.get("render_eligibility") == "render_ready":
                    self.assertTrue(seg.get("linked_live_event_id"))

    def test_narration_grounding(self) -> None:
        plan = compose_story_plan(self.france, use_llm=False)
        plan["narration"]["summary"] = "法国 9:9 神奇逆转 @ 12.34567s"
        issues = check_narration_grounding(plan)
        self.assertIn("9:9", issues["ungrounded"])
        self.assertTrue(issues["fake_precision_time"])

    def test_croatia_and_none(self) -> None:
        hr = compose_story_plan(self.croatia, use_llm=False)
        # 修复 opening 失球后，克罗地亚可升为正式 story（铺垫+蓄力齐）
        self.assertIn(hr["story_tier"], ("candidate", "story"))
        self.assertFalse(hr["render_ready"])
        ok, _ = validate_compose_plan(hr)
        self.assertTrue(ok)
        if NONE and NONE.is_file():
            none_story = json.loads(NONE.read_text(encoding="utf-8"))
            n = compose_story_plan(none_story, use_llm=False)
            self.assertEqual(n["verification_status"], "blocked_none")
            self.assertFalse(n["render_ready"])
            self.assertEqual(n["segments"], [])

    def test_croatia_opponent_opening_goal_before_scoreboard(self) -> None:
        """开场失球：因果 live 进球必须先于 0:1 记分牌，且不得用记分牌冒充动作。"""
        causal_path = ROOT / "data" / "交付_out" / "2022-11-28 克罗地亚vs加拿大_causal.json"
        if not causal_path.is_file():
            self.skipTest("no croatia causal")
        causal = json.loads(causal_path.read_text(encoding="utf-8"))
        plan = compose_story_plan(self.croatia, use_llm=False, causal=causal)
        opener = next(
            s
            for s in plan["segments"]
            if s.get("segment_id") == "seg_opponent_opening_goal_action"
        )
        setup = next(
            s for s in plan["segments"] if s.get("segment_id") == "seg_setup_deficit"
        )
        self.assertEqual(opener["role"], "opponent_opening_goal_action")
        self.assertEqual(opener["shot_kind"], "live")
        self.assertIsNotNone(opener.get("media_in"))
        self.assertLess(float(opener["media_in"]), float(setup["media_in"]))
        # 因果 Goal @980.137 → 动作窗应覆盖入网附近，远离 1079 记分牌
        self.assertLess(float(opener["media_out"]), 1020.0)
        self.assertGreaterEqual(float(setup["media_in"]), 1070.0)
        # 记分牌窗缩短（约 4s）
        self.assertLessEqual(
            float(setup["media_out"]) - float(setup["media_in"]), 6.0
        )
        self.assertNotEqual(opener.get("time_status"), "score_path_only")
        self.assertFalse(plan["render_ready"])

    def test_synthetic_opening_deficit_requires_opponent_goal_segment(self) -> None:
        story = {
            "story_tier": "candidate",
            "protagonist_side": "left",
            "has_story": True,
            "recognition": {"tier": "candidate", "beats": {"铺垫": [], "转折": ["g_eq"], "高潮": ["g_ga"]}},
            "score_path": [
                {"t_sec": 100.0, "score": "0:1", "opening": True, "delta_side": "right", "carrier_event_id": "board"},
                {"t_sec": 200.0, "score": "1:1", "delta_side": "left", "carrier_event_id": "g_eq"},
                {"t_sec": 300.0, "score": "2:1", "delta_side": "left", "carrier_event_id": "g_ga"},
            ],
            "events": [
                {
                    "event_id": "g_open",
                    "type": "进球",
                    "t_ms": 20000,
                    "is_replay": False,
                    "story_role": "铺垫",
                },
                {
                    "event_id": "g_eq",
                    "type": "进球",
                    "t_ms": 190000,
                    "is_replay": False,
                    "story_role": "转折",
                },
                {
                    "event_id": "g_ga",
                    "type": "进球",
                    "t_ms": 290000,
                    "is_replay": False,
                    "story_role": "高潮",
                },
            ],
        }
        plan = compose_story_plan(story, use_llm=False)
        roles = [s.get("role") for s in plan["segments"]]
        self.assertIn("opponent_opening_goal_action", roles)
        opener = next(
            s for s in plan["segments"] if s.get("role") == "opponent_opening_goal_action"
        )
        self.assertEqual(opener.get("event_ids"), ["g_open"])
        self.assertAlmostEqual(float(opener["media_in"]), 8.0, places=1)


if __name__ == "__main__":
    unittest.main()
