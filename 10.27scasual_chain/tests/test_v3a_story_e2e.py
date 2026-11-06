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


OMAN_PHASE5 = Path(
    "/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_A_uae_oman/"
    "fresh_e2e_A_real_20261105_183136/01_to_04_fresh_v3r/04_phase5"
)
OMAN_MP4 = Path("/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4")
OMAN_JSON = Path(
    "/data2/lpy1/causal-chain2/causal_chain/examples/交付_out/"
    "10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语.json"
)


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
        self.assertAlmostEqual(tl["story_duration_sec"], 75.0, places=2)
        hit = story_time_to_media(tl, 40.0)  # 20+12=32 → equalizer
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


@unittest.skipUnless(
    OMAN_PHASE5.is_dir() and OMAN_MP4.is_file() and OMAN_JSON.is_file(),
    "Oman baseline assets unavailable",
)
class TestOmanOfflineDryRun(unittest.TestCase):
    def test_offline_e2e_dry_run(self):
        out = Path(
            tempfile.mkdtemp(prefix="A_story_e2e_test_", dir="/data2/lpy1/_story_va_outputs/v3/plan2")
        )
        audit = run_story_e2e(
            StoryE2EInputs(
                match_json=OMAN_JSON,
                source_mp4=OMAN_MP4,
                out_dir=out,
                phase5_dir=OMAN_PHASE5,
                skip_vlm=True,
                enable_real_api=False,
                smoke_render=True,
                max_rounds=1,
            )
        )
        self.assertTrue(audit.get("ok"))
        self.assertEqual(audit.get("http_calls"), 0)
        gates = audit["status_gates"]
        self.assertTrue(gates["workflow_completed"])
        self.assertTrue(gates["story_diagnosis_valid"])
        self.assertTrue(gates["final_mp4_exists"])
        self.assertFalse(gates["release_authorized"])  # offline: no semantic pass
        self.assertFalse(gates["semantic_verification_passed"])
        delivery = audit["delivery"]
        self.assertEqual(delivery["delivery_label"], "INTERNAL_PREVIEW_NOT_FOR_DELIVERY")
        self.assertIn(delivery["decision"], ("KEEP", "UNRESOLVED", "REVISE"))
        # Must not claim KEEP when unresolved path taken for verify-only issues
        diag_path = out / "02_round_01" / "story_diagnosis.json"
        self.assertTrue(diag_path.is_file())
        # Smoke render proves renderer wiring
        smoke = audit.get("render_smoke") or {}
        self.assertTrue(smoke.get("ok"), msg=smoke)
        self.assertTrue(Path(smoke["story_clean"]).is_file())
        print("OMAN_OUT", out)


if __name__ == "__main__":
    unittest.main()
