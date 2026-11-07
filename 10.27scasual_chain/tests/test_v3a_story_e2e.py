"""Unit + offline integration tests for V3-A story-level E2E (HTTP=0)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent_v3.global_story_critic import structural_diagnosis
from story_video_agent_v3.story_e2e_agent import StoryE2EInputs, run_story_e2e
from story_video_agent_v3.story_revision_planner import plan_from_diagnosis
from story_video_agent_v3.story_timeline import (
    build_story_timeline,
    protected_goal_segment_ids,
    story_time_to_media,
)
from story_video_agent_v3.story_video_verifier import empty_status_gates, verify_story_revision


import os

# Optional integration assets via env (never hard-require one match).
def _env_path(key: str, default: str = "") -> Path:
    return Path(os.environ.get(key, default))


CROSS_MATCH_CASES = [
    {
        "id": "A",
        "phase5": _env_path(
            "V3A_MATCH_A_PHASE5",
            "/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_A_uae_oman/"
            "fresh_e2e_A_real_20261105_183136/01_to_04_fresh_v3r/04_phase5",
        ),
        "mp4": _env_path(
            "V3A_MATCH_A_MP4",
            "/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4",
        ),
        "json": _env_path(
            "V3A_MATCH_A_JSON",
            "/data2/lpy1/causal-chain2/causal_chain/examples/交付_out/"
            "10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语.json",
        ),
    },
    {
        "id": "B",
        "phase5": _env_path(
            "V3A_MATCH_B_PHASE5",
            "/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_B_osasuna_celta/04_phase5",
        ),
        "mp4": _env_path(
            "V3A_MATCH_B_MP4",
            "/mnt/data4/migu/10月27日 25-26赛季西甲第10轮 奥萨苏纳VS塞尔塔 国语.mp4",
        ),
        "json": _env_path(
            "V3A_MATCH_B_JSON",
            "/data2/lpy1/causal-chain2/causal_chain/examples/交付_out/"
            "10月27日_25-26赛季西甲第10轮_奥萨苏纳VS塞尔塔_国语.json",
        ),
    },
    {
        "id": "C",
        "phase5": _env_path(
            "V3A_MATCH_C_PHASE5",
            "/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_C_croatia_canada/04_phase5",
        ),
        "mp4": _env_path(
            "V3A_MATCH_C_MP4",
            "/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4",
        ),
        # Held-out style: leave JSON unset by default so C can serve as final-validation reserve
        # unless V3A_MATCH_C_JSON is provided.
        "json": _env_path("V3A_MATCH_C_JSON", ""),
    },
]


def _sample_edl():
    return [
        {
            "segment_id": "seg_title_open",
            "role": "story_title",
            "include_in_cut": True,
            "media_in": None,
            "media_out": None,
            "is_replay": False,
        },
        {
            "segment_id": "seg_open_goal",
            "role": "opponent_opening_goal_action",
            "include_in_cut": True,
            "media_in": 100.0,
            "media_out": 120.0,
            "is_replay": False,
        },
        {
            "segment_id": "seg_build",
            "role": "buildup_action",
            "include_in_cut": True,
            "media_in": 500.0,
            "media_out": 512.0,
            "is_replay": False,
        },
        {
            "segment_id": "seg_eq",
            "role": "equalizer_goal_action",
            "include_in_cut": True,
            "media_in": 800.0,
            "media_out": 820.0,
            "is_replay": False,
        },
        {
            "segment_id": "seg_ga",
            "role": "go_ahead_goal_action",
            "include_in_cut": True,
            "media_in": 900.0,
            "media_out": 920.0,
            "is_replay": False,
        },
        {
            "segment_id": "seg_sb",
            "role": "go_ahead_scoreboard_anchor",
            "include_in_cut": True,
            "media_in": 950.0,
            "media_out": 953.0,
            "is_replay": False,
        },
    ]


class TestStoryTimeline(unittest.TestCase):
    def test_timeline_and_mapping(self):
        tl = build_story_timeline(_sample_edl())
        # 2.5s title placeholder + 20+12+20+20+3 media = 77.5
        self.assertAlmostEqual(tl["story_duration_sec"], 77.5, places=2)
        hit = story_time_to_media(tl, 40.0)  # after title+open+build → equalizer
        self.assertIsNotNone(hit)
        self.assertEqual(hit["segment_id"], "seg_eq")
        goals = protected_goal_segment_ids(_sample_edl())
        self.assertEqual(
            goals,
            ["seg_open_goal", "seg_eq", "seg_ga"],
        )


class TestGlobalCritic(unittest.TestCase):
    def test_diagnosis_schema_and_no_user_hint_injection(self):
        diag = structural_diagnosis(edl=_sample_edl(), story_plan={"beats": []})
        self.assertEqual(diag["schema"], "v3a_story_diagnosis_v1")
        self.assertIn("issues", diag)
        blob = json.dumps(diag, ensure_ascii=False)
        # Must not bake prior human review complaints as preset answers
        for banned in ("铺垫可能有瑕疵", "结局可能有瑕疵", "user said opening is weak"):
            self.assertNotIn(banned, blob)
        for iss in diag["issues"]:
            self.assertIn(iss["evidence_sufficiency"], (
                "observed", "needs_video_verify", "structure_inferred",
            ))
            self.assertIn("issue_id", iss)
            self.assertIn("story_time_range", iss)
            self.assertIn("suggested_fix", iss)

    def test_replay_flag_critical(self):
        edl = _sample_edl()
        edl[2]["is_replay"] = True
        diag = structural_diagnosis(edl=edl)
        kinds = [i["category"] for i in diag["issues"]]
        self.assertIn("replay_risk", kinds)


class TestRevisionPlanner(unittest.TestCase):
    def test_unresolved_not_disguised_as_keep(self):
        diag = structural_diagnosis(edl=_sample_edl())
        # Force only needs_video_verify issues
        diag["issues"] = [
            {
                "issue_id": "x",
                "story_time_range": [0, 1],
                "segment_ids": ["seg_build"],
                "observation": "sparse bridge",
                "narrative_problem": "maybe thin",
                "severity": "minor",
                "suggested_fix": "verify",
                "evidence_sufficiency": "needs_video_verify",
                "category": "buildup",
            }
        ]
        plan = plan_from_diagnosis(diag, offline=True)
        self.assertEqual(plan["decision"], "UNRESOLVED")
        self.assertTrue(all(i["action"] == "mark_unresolved" for i in plan["revision_intents"]))

    def test_keep_when_clean(self):
        diag = {
            "issues": [],
            "protected_goal_segment_ids": ["seg_eq"],
            "timeline": {"segments": []},
        }
        plan = plan_from_diagnosis(diag, offline=True)
        self.assertEqual(plan["decision"], "KEEP")

    def test_goal_protection_blocks_drop(self):
        diag = {
            "issues": [],
            "protected_goal_segment_ids": ["seg_eq"],
            "timeline": {"segments": []},
        }
        plan = plan_from_diagnosis(
            diag,
            offline=True,
            fixture_intents=[
                {
                    "intent_id": "bad",
                    "action": "drop",
                    "target_segment_id": "seg_eq",
                    "narrative_purpose": "should_be_blocked",
                }
            ],
        )
        self.assertEqual(plan["revision_intents"][0]["action"], "keep")
        self.assertIn("protected_goal", plan["revision_intents"][0]["block_reason"])


class TestVerifierGates(unittest.TestCase):
    def test_status_gates_keys(self):
        g = empty_status_gates()
        for k in (
            "workflow_completed",
            "story_diagnosis_valid",
            "revision_applied",
            "candidate_rendered",
            "semantic_verification_passed",
            "release_authorized",
            "final_mp4_exists",
        ):
            self.assertIn(k, g)
            self.assertIs(g[k], False)

    def test_refuse_accept_without_semantic(self):
        edl = _sample_edl()
        with tempfile.TemporaryDirectory() as td:
            # missing mp4s → hard veto; still semantic not evaluated
            report = verify_story_revision(
                story={},
                plan={},
                baseline_edl=edl,
                candidate_edl=edl,
                baseline_mp4=Path(td) / "missing.mp4",
                candidate_mp4=None,
                decision="REVISE",
            )
            self.assertFalse(report["candidate_accepted"])
            self.assertTrue(report["retain_baseline"])


class TestCrossMatchOfflineDryRun(unittest.TestCase):
    """Same algorithm config across A/B/C; skip only when assets missing."""

    def _run_case(self, case: dict, *, smoke: bool) -> dict:
        phase5 = Path(case["phase5"])
        mp4 = Path(case["mp4"])
        if not phase5.is_dir() or not mp4.is_file():
            self.skipTest(f"assets unavailable for match {case['id']}")
        mj = Path(case["json"]) if case.get("json") else None
        if mj is None or not mj.is_file():
            # Placeholder match json — E2E requires a file path for audit lineage.
            tmp = Path(tempfile.mkdtemp(prefix=f"match_{case['id']}_"))
            mj = tmp / "match_placeholder.json"
            mj.write_text("{}", encoding="utf-8")
        out_root = Path("/data2/lpy1/_story_va_outputs/v3/plan2")
        out_root.mkdir(parents=True, exist_ok=True)
        out = Path(tempfile.mkdtemp(prefix=f"cross_{case['id']}_e2e_", dir=str(out_root)))
        return run_story_e2e(
            StoryE2EInputs(
                match_json=mj,
                source_mp4=mp4,
                out_dir=out,
                phase5_dir=phase5,
                skip_vlm=True,
                enable_real_api=False,
                smoke_render=smoke,
                max_rounds=1,
            )
        )

    def test_cross_match_offline_same_gates(self):
        results = []
        for case in CROSS_MATCH_CASES:
            with self.subTest(match=case["id"]):
                # Smoke render only on first available case to save time.
                smoke = case["id"] == "A"
                try:
                    audit = self._run_case(case, smoke=smoke)
                except unittest.SkipTest:
                    raise
                self.assertTrue(audit.get("ok"), audit.get("error"))
                self.assertEqual(audit.get("http_calls"), 0)
                gates = audit["status_gates"]
                self.assertTrue(gates["workflow_completed"])
                self.assertTrue(gates["story_diagnosis_valid"])
                self.assertTrue(gates["final_mp4_exists"])
                self.assertFalse(gates["release_authorized"])
                self.assertFalse(gates["semantic_verification_passed"])
                delivery = audit["delivery"]
                # Non-release labels: preview, or human-review candidate (no auto publish).
                self.assertIn(
                    delivery["delivery_label"],
                    (
                        "RELEASE_READY",
                        "HUMAN_REVIEW_REQUIRED",
                        "BLOCKED",
                        # legacy alias still accepted during transition
                        "INTERNAL_PREVIEW_NOT_FOR_DELIVERY",
                    ),
                )
                self.assertFalse(
                    delivery.get("delivery_label") == "RELEASE_READY"
                    and not gates.get("release_authorized")
                )
                self.assertIn(delivery["decision"], ("KEEP", "UNRESOLVED", "REVISE"))
                out_dir = Path(audit["out_dir"])
                diag_file = out_dir / "02_round_01" / "story_diagnosis.json"
                self.assertTrue(diag_file.is_file())
                text = diag_file.read_text(encoding="utf-8")
                self.assertNotIn("铺垫可能有瑕疵", text)
                # Match-agnostic: never bake opponent names into search/revise logic outputs.
                for banned in ("硬编码进球数", "three_goals_required"):
                    self.assertNotIn(banned, text)
                results.append({
                    "id": case["id"],
                    "decision": delivery["decision"],
                    "label": delivery["delivery_label"],
                    "edl_changed": bool(audit.get("edl_changed_any")),
                    "candidate_rendered": bool(gates.get("candidate_rendered")),
                    "out": str(out_dir),
                })
        if not results:
            self.skipTest("no cross-match assets available")
        print("CROSS_MATCH_RESULTS", results)


if __name__ == "__main__":
    unittest.main()
