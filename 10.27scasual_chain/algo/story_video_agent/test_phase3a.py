"""Phase 3A：Verifier + Composer 无计费单测（法国 story / 克罗地亚 candidate / none）。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent.narrative_composer import compose_from_paths, compose_story_plan
from story_video_agent.story_output_schema import (
    BEATS,
    SCHEMA_VERSION,
    render_narrative_report,
    validate_compose_plan,
)
from story_video_agent.story_verifier import classify_visual_evidence, verify_story

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "story_t01"
FRANCE = REPORTS / "2022年11月23日 法国vs澳大利亚.json"
CROATIA = REPORTS / "2022-11-28 克罗地亚vs加拿大.json"
NONE = next(REPORTS.glob("01_1*.json"), None)
CAUSAL_FR = ROOT / "data" / "交付_out" / "2022年11月23日 法国vs澳大利亚_causal.json"
CAUSAL_HR = ROOT / "data" / "交付_out" / "2022-11-28 克罗地亚vs加拿大_causal.json"


def _mock_visual(gap_id: str, frame_ids=None) -> dict:
    return {
        "gap_id": gap_id,
        "provider_mode": "mock",
        "normalized_ok": True,
        "frame_ids": frame_ids or ["mock_f1"],
        "observed_actions": ["mock scene"],
        "story_relation": "fixture only",
        "notes": "mock VLM — not factual verification",
        "is_mock": True,
        "fact_verified": False,
    }


class Phase3ATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.assertTrue(FRANCE.is_file(), FRANCE)
        cls.assertTrue(CROATIA.is_file(), CROATIA)
        cls.france = json.loads(FRANCE.read_text(encoding="utf-8"))
        cls.croatia = json.loads(CROATIA.read_text(encoding="utf-8"))
        cls.causal_fr = (
            json.loads(CAUSAL_FR.read_text(encoding="utf-8"))
            if CAUSAL_FR.is_file()
            else None
        )
        cls.causal_hr = (
            json.loads(CAUSAL_HR.read_text(encoding="utf-8"))
            if CAUSAL_HR.is_file()
            else None
        )

    def test_mock_not_factual(self) -> None:
        cl = classify_visual_evidence(_mock_visual("missing_setup_visual"))
        self.assertEqual(cl["kind"], "mock")
        self.assertFalse(cl["used_as_fact"])

    def test_verifier_france_score_path(self) -> None:
        rep = verify_story(self.france, visual_evidence=[_mock_visual("x")], causal=self.causal_fr)
        self.assertEqual(rep["story_tier"], "story")
        self.assertTrue(any(f.get("fact") == "score_node" for f in rep["rule_facts"]))
        self.assertTrue(rep["mock_evidence"])
        self.assertTrue(all(not m.get("used_as_fact") for m in rep["mock_evidence"]))

    def test_france_full_compose_structure(self) -> None:
        plan = compose_story_plan(
            self.france,
            visual_evidence=[
                _mock_visual("verify_equalizer_goal_action", ["mf1"]),
                _mock_visual("verify_go_ahead_goal_action", ["mf2"]),
                _mock_visual("post_climax_reaction", ["mf3"]),
            ],
            causal=self.causal_fr,
            use_llm=False,
        )
        self.assertEqual(plan["schema_version"], SCHEMA_VERSION)
        self.assertEqual(plan["story_tier"], "story")
        self.assertEqual(plan["beats"], list(BEATS))
        ok, problems = validate_compose_plan(plan)
        self.assertTrue(ok, problems)
        beats_present = {s["beat"] for s in plan["segments"]}
        for b in ("铺垫", "蓄力", "转折", "高潮"):
            self.assertIn(b, beats_present)
        # mock 不得 used_as_fact
        for ref in plan["evidence_refs"]:
            if ref.get("kind") == "mock":
                self.assertFalse(ref.get("used_as_fact"))
        self.assertTrue(any("mock_only" in m for m in plan["missing_evidence"]))
        # EDL / report
        self.assertTrue(plan["edl"])
        md = render_narrative_report(plan)
        self.assertIn("铺垫", md)
        self.assertIn(plan["match_id"], md)

    def test_replay_not_marked_live(self) -> None:
        plan = compose_story_plan(self.france, causal=self.causal_fr, use_llm=False)
        for seg in plan["segments"]:
            if seg.get("is_replay"):
                self.assertEqual(seg.get("shot_kind"), "replay_supplement")
        ok, problems = validate_compose_plan(plan)
        self.assertTrue(ok, problems)
        self.assertFalse(any("replay_marked_live" in p for p in problems))

    def test_live_timeline_non_decreasing(self) -> None:
        plan = compose_story_plan(self.france, causal=self.causal_fr, use_llm=False)
        times = [
            float(s["media_in"])
            for s in plan["segments"]
            if s.get("shot_kind") == "live" and s.get("media_in") is not None
        ]
        self.assertEqual(times, sorted(times))

    def test_croatia_candidate_partial(self) -> None:
        plan = compose_story_plan(
            self.croatia, causal=self.causal_hr, use_llm=False
        )
        self.assertEqual(plan["story_tier"], "candidate")
        self.assertEqual(plan["verification_status"], "partial")
        self.assertTrue(plan["missing_evidence"])
        ok, problems = validate_compose_plan(plan)
        self.assertTrue(ok, problems)
        # candidate 允许不完整但仍有转折/高潮候选
        beats = {s["beat"] for s in plan["segments"]}
        self.assertTrue({"转折", "高潮"} & beats)

    def test_none_blocks_comeback(self) -> None:
        if NONE is None or not NONE.is_file():
            self.skipTest("none fixture missing")
        none_story = json.loads(NONE.read_text(encoding="utf-8"))
        plan = compose_story_plan(none_story, use_llm=False)
        self.assertEqual(plan["story_tier"], "none")
        self.assertEqual(plan["verification_status"], "blocked_none")
        self.assertEqual(plan["segments"], [])
        ok, problems = validate_compose_plan(plan)
        self.assertTrue(ok, problems)

    def test_pending_localization_no_fake_precision(self) -> None:
        story = dict(self.croatia)
        # strip ending events to force pending ending
        story["events"] = [
            e
            for e in (story.get("events") or [])
            if e.get("story_role") != "收尾" and e.get("type") not in ("比赛结束",)
        ]
        plan = compose_story_plan(story, use_llm=False)
        pending = [
            s
            for s in plan["segments"]
            if s.get("time_status") == "pending_localization"
        ]
        self.assertTrue(pending)
        for s in pending:
            self.assertFalse(s.get("precise_claim"))
            # 允许 null 时间；若有数值也不得标 calibrated
            self.assertNotEqual(s.get("time_status"), "calibrated")

    def test_unrelated_event_not_forced(self) -> None:
        # 注入无关事件不应进入高潮 live（非进球/射门）
        story = json.loads(json.dumps(self.france))
        story.setdefault("events", []).append(
            {
                "event_id": "event_unrelated_pass",
                "type": "传球",
                "t_ms": 1000,
                "story_role": "高潮",
                "is_replay": False,
            }
        )
        story["recognition"]["beats"]["高潮"] = list(
            story["recognition"]["beats"].get("高潮") or []
        ) + ["event_unrelated_pass"]
        plan = compose_story_plan(story, use_llm=False)
        ids = []
        for s in plan["segments"]:
            if s.get("beat") == "高潮" and s.get("shot_kind") == "live":
                ids.extend(s.get("event_ids") or [])
        self.assertNotIn("event_unrelated_pass", ids)

    def test_compose_from_paths_writes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_json = Path(td) / "plan.json"
            out_md = Path(td) / "plan.md"
            plan = compose_from_paths(
                str(FRANCE),
                causal_path=str(CAUSAL_FR) if CAUSAL_FR.is_file() else None,
                out_json=str(out_json),
                out_report=str(out_md),
            )
            self.assertTrue(out_json.is_file())
            self.assertTrue(out_md.is_file())
            loaded = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(loaded["match_id"], plan["match_id"])


if __name__ == "__main__":
    unittest.main()
