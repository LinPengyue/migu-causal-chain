"""Zero-cost tests: evidence search → executable revise → no match hardcoding."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from story_video_agent_v3.self_revise_agent import apply_candidate_revision
from story_video_agent_v3.story_evidence_search import (
    run_story_evidence_search,
    search_candidates_to_observations,
    search_window_for_issue,
    verify_search_candidate,
)
from story_video_agent_v3.story_revision_planner import plan_from_diagnosis


def _edl_bridge_gap():
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
            "segment_id": "seg_setup",
            "role": "deficit_scoreboard_anchor",
            "include_in_cut": True,
            "media_in": 200.0,
            "media_out": 205.0,
            "is_replay": False,
        },
        {
            "segment_id": "seg_turn",
            "role": "equalizer_goal_action",
            "include_in_cut": True,
            "media_in": 2000.0,
            "media_out": 2020.0,
            "is_replay": False,
        },
        {
            "segment_id": "seg_climax",
            "role": "go_ahead_goal_action",
            "include_in_cut": True,
            "media_in": 3000.0,
            "media_out": 3020.0,
            "is_replay": False,
        },
        {
            "segment_id": "seg_sb",
            "role": "go_ahead_scoreboard_anchor",
            "include_in_cut": True,
            "media_in": 3100.0,
            "media_out": 3104.0,
            "is_replay": False,
        },
    ]


def _synthetic_events(path: Path) -> Path:
    events = {
        "events": [
            {
                "event_id": "ev_bridge_shot",
                "event_type": "Shot",
                "event_type_zh": "射门",
                "media_time": {
                    "event_time_sec": 900.0,
                    "start_time_sec": 896.0,
                    "end_time_sec": 908.0,
                },
                "video_context": {
                    "broadcast_phase": "LIVE",
                    "is_replay": False,
                    "is_slow_motion": False,
                },
                "scores": {
                    "overall_score": 4.0,
                    "emotional_heat_score": 3.0,
                    "criticality_score": 2.0,
                },
            },
            {
                "event_id": "ev_replay_trap",
                "event_type": "Shot",
                "media_time": {
                    "event_time_sec": 950.0,
                    "start_time_sec": 946.0,
                    "end_time_sec": 958.0,
                },
                "video_context": {
                    "broadcast_phase": "REPLAY",
                    "is_replay": True,
                    "is_slow_motion": True,
                },
                "scores": {"overall_score": 9.0, "emotional_heat_score": 9.0},
            },
            {
                "event_id": "ev_ending",
                "event_type": "Defensive_action",
                "media_time": {
                    "event_time_sec": 3040.0,
                    "start_time_sec": 3035.0,
                    "end_time_sec": 3048.0,
                },
                "video_context": {
                    "broadcast_phase": "LIVE",
                    "is_replay": False,
                    "is_slow_motion": False,
                },
                "scores": {"overall_score": 3.0, "emotional_heat_score": 2.0},
            },
        ]
    }
    path.write_text(json.dumps(events), encoding="utf-8")
    return path


class EvidenceSearchTests(unittest.TestCase):
    def test_search_finds_live_not_replay(self):
        edl = _edl_bridge_gap()
        with tempfile.TemporaryDirectory() as td:
            ev = _synthetic_events(Path(td) / "events.json")
            diag = {
                "issues": [
                    {
                        "issue_id": "large_source_jump_seg_setup_to_seg_turn",
                        "category": "transition",
                        "severity": "minor",
                        "evidence_sufficiency": "needs_video_verify",
                        "segment_ids": ["seg_setup", "seg_turn"],
                        "narrative_problem": "abrupt jump",
                        "suggested_fix": "insert_bridge",
                    }
                ],
                "protected_goal_segment_ids": [
                    "seg_open_goal",
                    "seg_turn",
                    "seg_climax",
                ],
            }
            report = run_story_evidence_search(
                diagnosis=diag, edl=edl, match_json=ev
            )
            self.assertTrue(report["search_success"])
            ids = {c["event_id"] for c in report["verified_candidates"]}
            self.assertIn("ev_bridge_shot", ids)
            self.assertNotIn("ev_replay_trap", ids)
            for c in report["verified_candidates"]:
                self.assertGreater(c["source_pts_start"], 205.0)
                self.assertLess(c["source_pts_end"], 2000.0)

    def test_reject_overlap_goal_window(self):
        cand = {
            "source_pts_start": 110.0,
            "source_pts_end": 118.0,
            "confidence": 0.9,
            "live": {"live_ok": True, "is_replay": False, "is_slow_motion": False},
        }
        gate = verify_search_candidate(cand, edl=_edl_bridge_gap())
        self.assertFalse(gate["ok"])
        self.assertTrue(any("overlaps_protected_goal" in r for r in gate["reasons"]))


class PlannerSearchReviseTests(unittest.TestCase):
    def test_search_success_yields_revise_not_unresolved(self):
        diag = {
            "issues": [
                {
                    "issue_id": "sparse_pre_turn_bridge",
                    "category": "buildup",
                    "severity": "minor",
                    "evidence_sufficiency": "needs_video_verify",
                    "segment_ids": ["seg_setup"],
                    "narrative_problem": "thin buildup",
                    "suggested_fix": "search",
                }
            ],
            "protected_goal_segment_ids": ["seg_turn"],
        }
        search = {
            "search_success": True,
            "verified_candidates": [
                {
                    "candidate_id": "cand_x",
                    "issue_id": "sparse_pre_turn_bridge",
                    "role": "buildup_bridge_action",
                    "source_pts_start": 500.0,
                    "source_pts_end": 508.0,
                    "insert_after_segment_id": "seg_setup",
                    "event_id": "ev1",
                    "live": {"broadcast_phase": "LIVE"},
                    "confidence": 0.6,
                    "risks": [],
                    "narrative_function": "supplement_buildup_or_transition_bridge",
                }
            ],
        }
        plan = plan_from_diagnosis(diag, offline=True, search_results=search)
        self.assertEqual(plan["decision"], "REVISE")
        acts = {i["action"] for i in plan["revision_intents"]}
        self.assertIn("search_add", acts)
        self.assertTrue(all("goal_action" not in str(i.get("role") or "") for i in plan["revision_intents"]))

    def test_no_search_stays_unresolved(self):
        diag = {
            "issues": [
                {
                    "issue_id": "thin_post_climax_tail",
                    "category": "ending",
                    "severity": "minor",
                    "evidence_sufficiency": "needs_video_verify",
                    "segment_ids": ["seg_sb"],
                    "narrative_problem": "abrupt ending",
                    "suggested_fix": "extend",
                }
            ],
            "protected_goal_segment_ids": ["seg_climax"],
        }
        plan = plan_from_diagnosis(
            diag, offline=True, search_results={"search_success": False, "verified_candidates": []}
        )
        self.assertEqual(plan["decision"], "UNRESOLVED")


class ApplySearchBoundTests(unittest.TestCase):
    def test_search_add_mutates_edl_with_real_pts(self):
        edl = _edl_bridge_gap()
        intents = [
            {
                "intent_id": "i1",
                "action": "search_add",
                "role": "buildup_bridge_action",
                "insert_after_segment_id": "seg_setup",
                "bound_source_window": {"start": 900.0, "end": 908.0},
                "new_segment_id": "seg_buildup_bridge_action_cand_x",
                "event_ids": ["ev_bridge_shot"],
                "narrative_purpose": "supplement_buildup",
            }
        ]
        out, report = apply_candidate_revision(edl, intents, observations=[])
        self.assertNotEqual(out, edl)
        applied = [a for a in report["applied"] if a.get("status") == "applied_evidence_bound"]
        self.assertEqual(len(applied), 1)
        ids = [r["segment_id"] for r in out if r.get("include_in_cut", True) is not False]
        self.assertIn("seg_buildup_bridge_action_cand_x", ids)
        # Inserted after setup, before turn
        self.assertLess(
            ids.index("seg_setup"),
            ids.index("seg_buildup_bridge_action_cand_x"),
        )
        self.assertLess(
            ids.index("seg_buildup_bridge_action_cand_x"),
            ids.index("seg_turn"),
        )
        # Goals untouched
        goals = {
            r["segment_id"]: (r["media_in"], r["media_out"])
            for r in out
            if "goal_action" in str(r.get("role") or "")
        }
        self.assertEqual(goals["seg_open_goal"], (100.0, 120.0))
        self.assertEqual(goals["seg_turn"], (2000.0, 2020.0))
        self.assertEqual(goals["seg_climax"], (3000.0, 3020.0))

    def test_observations_roundtrip_from_search(self):
        search = {
            "verified_candidates": [
                {
                    "candidate_id": "c1",
                    "issue_id": "iss",
                    "source_pts_start": 10.0,
                    "source_pts_end": 18.0,
                    "event_id": "e1",
                    "evidence_verification": {"ok": True},
                }
            ]
        }
        obs = search_candidates_to_observations(search)
        self.assertEqual(len(obs), 1)
        self.assertTrue(obs[0]["ok"])
        self.assertEqual(obs[0]["window"]["start"], 10.0)

    def test_ending_search_window_clamped_before_scoreboard(self):
        """Aftermath search must not extend past following scoreboard media_in."""
        edl = _edl_bridge_gap()
        win = search_window_for_issue(
            {
                "issue_id": "thin_post_climax_tail",
                "category": "ending",
                "segment_ids": ["seg_sb"],
            },
            edl,
        )
        self.assertIsNotNone(win)
        assert win is not None
        # climax media_out=3020, scoreboard media_in=3100 → hi < 3100
        self.assertLess(float(win["hi"]), 3100.0)
        self.assertGreater(float(win["hi"]), float(win["lo"]))
        self.assertEqual(win["insert_after_segment_id"], "seg_climax")
        self.assertEqual(win["before_segment_id"], "seg_sb")

    def test_search_add_rejects_pts_order_break_vs_next(self):
        """Insert before scoreboard cannot use footage that ends after scoreboard PTS."""
        edl = _edl_bridge_gap()
        intents = [
            {
                "intent_id": "bad_ending",
                "action": "search_add",
                "role": "ending_closure_action",
                "insert_after_segment_id": "seg_climax",
                "before_segment_id": "seg_sb",
                "bound_source_window": {"start": 3110.0, "end": 3120.0},
                "new_segment_id": "seg_ending_bad",
                "event_ids": ["ev_ending_late"],
                "narrative_purpose": "extend_ending_closure",
            }
        ]
        out, report = apply_candidate_revision(edl, intents, observations=[])
        rejected = report.get("rejected") or []
        self.assertTrue(
            any(r.get("reason") == "search_add_breaks_source_pts_order_vs_next" for r in rejected),
            msg=rejected,
        )
        ids = [r["segment_id"] for r in out if r.get("include_in_cut", True) is not False]
        self.assertNotIn("seg_ending_bad", ids)


class MatchAgnosticGuard(unittest.TestCase):
    def test_no_match_names_in_search_module(self):
        root = Path(__file__).resolve().parents[1] / "algo" / "story_video_agent_v3"
        banned = ("阿曼", "奥萨苏纳", "克罗地亚", "阿联酋", "塞尔塔", "canada", "oman")
        for name in ("story_evidence_search.py", "story_revision_planner.py", "story_e2e_agent.py"):
            text = (root / name).read_text(encoding="utf-8").lower()
            for b in banned:
                self.assertNotIn(b.lower(), text, msg=f"{name} contains {b}")


@unittest.skipUnless(
    os.environ.get("V3A_RUN_REAL_SEARCH_INTEGRATION") == "1",
    "set V3A_RUN_REAL_SEARCH_INTEGRATION=1 for real A phase5+json search",
)
class RealMatchSearchIntegration(unittest.TestCase):
    def test_a_phase5_search_finds_candidates(self):
        phase5 = Path(
            "/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_A_uae_oman/"
            "fresh_e2e_A_real_20261105_183136/01_to_04_fresh_v3r/04_phase5"
        )
        match_json = Path(
            "/data2/lpy1/causal-chain2/causal_chain/examples/交付_out/"
            "10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语.json"
        )
        if not phase5.is_dir() or not match_json.is_file():
            self.skipTest("A assets missing")
        edl = json.loads((phase5 / "candidate_edl.json").read_text(encoding="utf-8"))
        from story_video_agent_v3.global_story_critic import structural_diagnosis

        diag = structural_diagnosis(
            edl=edl,
            story_plan=json.loads((phase5 / "story_plan.json").read_text(encoding="utf-8")),
            initial_story_mp4=phase5 / "story_clean.mp4",
            source_video=None,
        )
        report = run_story_evidence_search(
            diagnosis=diag, edl=edl, match_json=match_json
        )
        self.assertTrue(report["events_loaded"] > 0)
        # Prefer success when transition gaps exist; tolerate empty if critic quiet.
        if any(i.get("category") in ("transition", "ending", "buildup") for i in diag.get("issues") or []):
            self.assertTrue(report["search_success"])


if __name__ == "__main__":
    unittest.main()
