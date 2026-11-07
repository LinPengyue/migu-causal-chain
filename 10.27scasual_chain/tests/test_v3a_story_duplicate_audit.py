"""Tests for cross-role duplicate audit (B-style containment + preference)."""
from __future__ import annotations

import unittest

from story_video_agent_v3.global_story_critic import structural_diagnosis
from story_video_agent_v3.story_duplicate_audit import (
    apply_auto_drops,
    audit_edl_duplicates,
    choose_keep_drop,
    find_media_window_duplicates,
)
from story_video_agent_v3.story_revision_planner import plan_from_diagnosis


def _b_style_edl():
    """Minimal B-like EDL: buildup fill contained inside equalizer goal window."""
    return [
        {
            "segment_id": "seg_open",
            "role": "opponent_opening_goal_action",
            "include_in_cut": True,
            "media_in": 100.0,
            "media_out": 120.0,
            "is_replay": False,
        },
        {
            "segment_id": "seg_buildup_atom_fill",
            "role": "buildup_action",
            "include_in_cut": True,
            "media_in": 5653.158,
            "media_out": 5665.158,
            "is_replay": False,
        },
        {
            "segment_id": "seg_equalizer_goal_action",
            "role": "equalizer_goal_action",
            "include_in_cut": True,
            "media_in": 5645.621,
            "media_out": 5667.621,
            "is_replay": False,
            "first_live_status": "FIRST_LIVE_VERIFIED",
        },
        {
            "segment_id": "seg_go_ahead_goal_action",
            "role": "go_ahead_goal_action",
            "include_in_cut": True,
            "media_in": 6779.0,
            "media_out": 6801.0,
            "is_replay": False,
        },
    ]


class ContainmentAndPreferenceTests(unittest.TestCase):
    def test_b_style_containment_auto_drops_non_goal(self):
        findings = find_media_window_duplicates(_b_style_edl())
        kinds = {f["kind"] for f in findings}
        self.assertIn("media_containment", kinds)
        hit = next(f for f in findings if "seg_buildup_atom_fill" in f["segment_ids"])
        self.assertEqual(hit["decision"], "auto_drop")
        self.assertEqual(hit["drop_segment_id"], "seg_buildup_atom_fill")
        self.assertEqual(hit["keep_segment_id"], "seg_equalizer_goal_action")

    def test_apply_auto_drops_keeps_goals(self):
        audit = audit_edl_duplicates(_b_style_edl())
        out, report = apply_auto_drops(_b_style_edl(), audit)
        self.assertTrue(report["changed"])
        self.assertIn("seg_buildup_atom_fill", report["dropped"])
        active = [r for r in out if r.get("include_in_cut", True) is not False]
        ids = [r["segment_id"] for r in active]
        self.assertNotIn("seg_buildup_atom_fill", ids)
        self.assertIn("seg_equalizer_goal_action", ids)
        self.assertIn("seg_go_ahead_goal_action", ids)
        self.assertIn("seg_open", ids)

    def test_overlapping_goals_require_human_review(self):
        a = {
            "segment_id": "g1",
            "role": "equalizer_goal_action",
            "media_in": 10.0,
            "media_out": 30.0,
        }
        b = {
            "segment_id": "g2",
            "role": "go_ahead_goal_action",
            "media_in": 20.0,
            "media_out": 40.0,
        }
        pref = choose_keep_drop(a, b, contain=None)
        self.assertEqual(pref["decision"], "human_review")

    def test_partial_overlap_never_auto_drops_on_length_or_priority(self):
        # Partial overlap between non-goals (or non-contained) → human_review only.
        edl = [
            {
                "segment_id": "a",
                "role": "buildup_action",
                "include_in_cut": True,
                "media_in": 100.0,
                "media_out": 112.0,
            },
            {
                "segment_id": "b",
                "role": "buildup_bridge_action",
                "include_in_cut": True,
                "media_in": 108.0,
                "media_out": 120.0,
            },
        ]
        findings = find_media_window_duplicates(edl)
        self.assertTrue(findings)
        self.assertTrue(all(f["decision"] == "human_review" for f in findings))
        self.assertTrue(all(not f.get("drop_segment_id") for f in findings))

    def test_different_length_containment_still_drops_inner(self):
        edl = [
            {
                "segment_id": "short",
                "role": "buildup_bridge_action",
                "include_in_cut": True,
                "media_in": 50.0,
                "media_out": 55.0,
            },
            {
                "segment_id": "long_goal",
                "role": "equalizer_goal_action",
                "include_in_cut": True,
                "media_in": 40.0,
                "media_out": 70.0,
            },
        ]
        audit = audit_edl_duplicates(edl)
        self.assertIn("short", audit["auto_drop_segment_ids"])

    def test_same_camera_adjacent_no_media_overlap_not_structural(self):
        # Distinct PTS windows (different attacks) → no structural duplicate.
        edl = [
            {
                "segment_id": "att1",
                "role": "buildup_action",
                "include_in_cut": True,
                "media_in": 100.0,
                "media_out": 110.0,
            },
            {
                "segment_id": "att2",
                "role": "buildup_action",
                "include_in_cut": True,
                "media_in": 200.0,
                "media_out": 210.0,
            },
        ]
        findings = find_media_window_duplicates(edl)
        self.assertEqual(findings, [])


class CriticAndPlannerIntegration(unittest.TestCase):
    def test_critic_emits_redundancy_with_preferred_drop(self):
        diag = structural_diagnosis(edl=_b_style_edl(), story_plan={})
        red = [i for i in diag["issues"] if i.get("category") == "redundancy"]
        self.assertTrue(red)
        self.assertTrue(
            any(i.get("preferred_drop_segment_id") == "seg_buildup_atom_fill" for i in red)
        )

    def test_planner_drops_preferred_not_goal(self):
        diag = structural_diagnosis(edl=_b_style_edl(), story_plan={})
        # Isolate redundancy (input_integrity from missing paths would otherwise block).
        diag = {
            **diag,
            "issues": [i for i in diag["issues"] if i.get("category") == "redundancy"],
            "protected_goal_segment_ids": [
                "seg_open",
                "seg_equalizer_goal_action",
                "seg_go_ahead_goal_action",
            ],
        }
        plan = plan_from_diagnosis(diag, offline=True, search_results=None)
        drops = [
            i for i in plan["revision_intents"]
            if i.get("action") == "drop"
        ]
        self.assertTrue(drops)
        self.assertTrue(all(i.get("target_segment_id") != "seg_equalizer_goal_action" for i in drops))
        self.assertTrue(any(i.get("target_segment_id") == "seg_buildup_atom_fill" for i in drops))


class MatchAgnosticGuard(unittest.TestCase):
    def test_no_match_names(self):
        from pathlib import Path
        text = (
            Path(__file__).resolve().parents[1]
            / "algo/story_video_agent_v3/story_duplicate_audit.py"
        ).read_text(encoding="utf-8").lower()
        for ban in ("阿曼", "奥萨苏纳", "克罗地亚", "osasuna", "oman"):
            self.assertNotIn(ban.lower(), text)


if __name__ == "__main__":
    unittest.main()
