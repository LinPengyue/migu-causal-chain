"""Unit / mock tests for Strip-Guided Round 2 (no gold, no real API)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent.v2_enhanced_events import (
    make_inferred_goal_event,
    merge_enhanced_events_payload,
    should_emit_inferred_goal,
)
from story_video_agent.v2_event_adapter import load_events_json
from story_video_agent.v2_missing_goal_detector import detect_missing_goals
from story_video_agent.v2_strip_reinfer import compare_strip_ab, events_to_timeline, norm_type


class TestMissingGoalDetector(unittest.TestCase):
    def test_croatia_plain_finds_missing_without_gold(self):
        path = Path(
            "/data2/lpy1/causal-chain2/8.31causal_chain/data/交付_out/2022-11-28 克罗地亚vs加拿大.json"
        )
        if not path.is_file():
            self.skipTest("croatia events missing")
        bundle = load_events_json(path)
        # Simulate prior 62-chain A without goalish coverage near early scores
        strips = [
            {
                "strip_chain_id": "strip_clip58",
                "t0_sec": 7632.52,
                "t1_sec": 7747.43,
                "predicted_category": "outcome",
                "last_event": "goal",
                "predicted_template_id": "outcome_other",
            }
        ]
        det = detect_missing_goals(
            events=bundle["events"], predicted_strips=strips, match_id=bundle.get("match_id")
        )
        self.assertGreaterEqual(det["n_missing"], 3)
        kinds = {c["kind"] for c in det["missing_goal_candidates"]}
        self.assertIn("initial_deficit_pending", kinds)
        # Must not invent exact action times
        for c in det["missing_goal_candidates"]:
            self.assertFalse(c["search_region"].get("invented_exact_action_time"))
            self.assertIn("score_confirmation_time", c)
            self.assertNotEqual(c.get("score_confirmation_time"), None)

    def test_covered_when_goal_event_present(self):
        events = [
            {
                "event_id": "e1",
                "event_type": "Throw_in",
                "event_time_sec": 100.0,
                "media_start_sec": 99.0,
                "media_end_sec": 101.0,
                "score_pair": [0, 0],
            },
            {
                "event_id": "g1",
                "event_type": "Goal",
                "event_time_sec": 150.0,
                "media_start_sec": 148.0,
                "media_end_sec": 152.0,
                "score_pair": [0, 0],
            },
            {
                "event_id": "e2",
                "event_type": "Throw_in",
                "event_time_sec": 160.0,
                "media_start_sec": 159.0,
                "media_end_sec": 161.0,
                "score_pair": [1, 0],
            },
        ]
        det = detect_missing_goals(events=events, predicted_strips=[])
        # Transition 0:0→1:0 covered by Goal
        self.assertTrue(any(c.get("kind") == "score_change_covered_by_goal_event" for c in det["covered_transitions"]))
        missing_ids = [c["candidate_id"] for c in det["missing_goal_candidates"] if c["kind"] == "score_change_missing_goal"]
        self.assertEqual(missing_ids, [])


class TestEnhancedEvents(unittest.TestCase):
    def test_emit_gate(self):
        self.assertFalse(should_emit_inferred_goal({"grade": "goal_candidate", "verification_status": "candidate_needs_refine"}))
        self.assertFalse(
            should_emit_inferred_goal(
                {
                    "grade": "action_localized",
                    "verification_status": "verified_action",
                    "live_or_replay": "replay",
                    "shooting_action_evidence": True,
                    "goal_result_evidence": True,
                }
            )
        )
        self.assertTrue(
            should_emit_inferred_goal(
                {
                    "grade": "action_localized",
                    "verification_status": "verified_action",
                    "live_or_replay": "live",
                    "shooting_action_evidence": True,
                    "goal_result_evidence": True,
                }
            )
        )

    def test_merge_does_not_overwrite_and_marks_source(self):
        path = Path(
            "/data2/lpy1/causal-chain2/8.31causal_chain/data/交付_out/2022-11-28 克罗地亚vs加拿大.json"
        )
        if not path.is_file():
            self.skipTest("croatia events missing")
        before = path.read_bytes()
        inf = make_inferred_goal_event(
            inferred_event_id="inferred_goal_test",
            media_time_sec=1000.0,
            media_start_sec=995.0,
            media_end_sec=1005.0,
            related_score_transition={"score_before": [0, 1], "score_after": [1, 1]},
            supporting_frame_ids=["f_001"],
            supporting_video_windows=[{"start": 990, "end": 1010}],
            verification_status="verified_action",
            confidence=0.8,
            uncertainty=0.2,
            live_or_replay="live",
        )
        self.assertEqual(inf["source"], "video_agent_inferred")
        bundle = merge_enhanced_events_payload(
            original_events_path=path, inferred_goals=[inf], match_id="test"
        )
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(bundle["n_original"] + 1, bundle["n_merged"])
        tl = events_to_timeline(bundle["merged_events_for_strip"])
        goals = [e for e in tl if e["type"] == "goal"]
        self.assertGreaterEqual(len(goals), 2)  # original 1 + inferred 1
        self.assertTrue(any(e["event_id"] == "inferred_goal_test" for e in goals))


class TestStripABCompare(unittest.TestCase):
    def test_compare_counts(self):
        a = {
            "n_chains": 2,
            "category_counts": {"special": 2},
            "chains": [
                {"t0_ms": 0, "t1_ms": 10, "template_id": "t1", "chain_category": "special"},
                {"t0_ms": 20, "t1_ms": 30, "template_id": "t2", "chain_category": "danger"},
            ],
        }
        b = {
            "n_chains": 3,
            "category_counts": {"special": 2, "outcome": 1},
            "chains": a["chains"]
            + [
                {
                    "t0_ms": 100,
                    "t1_ms": 200,
                    "template_id": "outcome_other",
                    "chain_category": "outcome",
                    "last_event": "goal",
                    "clip_id": "clip99",
                }
            ],
        }
        cmp = compare_strip_ab(
            strip_a=a,
            strip_b=b,
            missing_candidates=[
                {
                    "candidate_id": "mg1",
                    "score_confirmation_time": 0.15,
                    "score_before": [0, 1],
                    "score_after": [1, 1],
                }
            ],
        )
        self.assertEqual(cmp["n_only_in_B"], 1)
        self.assertEqual(cmp["n_outcome_or_goal_B"], 1)

    def test_norm_goal(self):
        self.assertEqual(norm_type("Goal"), "goal")
        self.assertEqual(norm_type("进球"), "goal")


if __name__ == "__main__":
    unittest.main()
