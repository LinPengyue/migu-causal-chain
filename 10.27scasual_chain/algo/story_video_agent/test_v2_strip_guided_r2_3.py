"""Round 2.3 unit tests — planner rule path, key-event coverage, EDL (no real API)."""

from __future__ import annotations

import unittest

from story_video_agent.api_provider import ApiProvider
from story_video_agent.v2_strip_guided_r2_3_edl import build_r23_candidate_edl
from story_video_agent.v2_strip_guided_r2_3_graph import build_full_story_graph
from story_video_agent.v2_strip_guided_r2_3_key_events import (
    build_full_match_key_events,
    find_unverified_original_goals,
)
from story_video_agent.v2_strip_guided_r2_3_memory import V2R23StoryMemory
from story_video_agent.v2_strip_guided_r2_3_planner import (
    V2R23StoryPlanner,
    apply_planner_decision,
    ensure_verified_goals_selected,
    finalize_relations,
    summarize_strips_for_planner,
)


class TestKeyEvents(unittest.TestCase):
    def test_finds_uncovered_original_goal(self):
        verified = [
            {
                "inferred_event_id": "inferred_goal_x",
                "verification_status": "verified_action",
                "media_time": {"event_time_sec": 1000.0},
                "goal_result": {"media_sec": 1000.0},
                "related_score_transition": {"score_after": [0, 1]},
            }
        ]
        events = [
            {
                "event_id": "event_000153",
                "event_type": "Goal",
                "event_time_sec": 7747.43,
                "media_start_sec": 7746.13,
                "media_end_sec": 7757.49,
            },
        ]
        anchors = [
            {"kind": "score_change", "score_before": [3, 1], "score_after": [4, 1], "event_time_sec": 7818.5, "event_id": "event_000154"},
        ]
        u = find_unverified_original_goals(events=events, verified_goals=verified, score_anchors=anchors)
        self.assertEqual(len(u), 1)
        self.assertEqual(u[0]["event_id"], "event_000153")
        self.assertEqual(u[0]["linked_score_transition"]["score_after"], [4, 1])


class TestPlannerRule(unittest.TestCase):
    def test_selects_goals_and_buildup_strip(self):
        api = ApiProvider(force_mock=True, require_real=False, max_calls=20, max_cost_usd=1, max_completion_tokens=256)
        planner = V2R23StoryPlanner(api=api, use_llm=False)
        mem = V2R23StoryMemory()
        mem.key_events = [
            {
                "key_event_id": "ke_1",
                "score_before": None,
                "score_after": [0, 1],
                "media_time_sec": 982.0,
                "verification_status": "verified_action",
                "inferred_event_id": "g0",
            },
            {
                "key_event_id": "ke_2",
                "score_before": [0, 1],
                "score_after": [1, 1],
                "media_time_sec": 3107.0,
                "verification_status": "verified_action",
                "inferred_event_id": "g1",
            },
            {
                "key_event_id": "ke_3",
                "score_before": [1, 1],
                "score_after": [2, 1],
                "media_time_sec": 3566.0,
                "verification_status": "verified_action",
                "inferred_event_id": "g2",
            },
        ]
        mem.strip_summaries = summarize_strips_for_planner(
            [
                {
                    "strip_chain_id": "clipA",
                    "t0_sec": 2800.0,
                    "t1_sec": 3000.0,
                    "predicted_category": "danger",
                    "first_event": "pass",
                    "last_event": "shot",
                    "event_sequence": ["pass", "shot"],
                },
                {
                    "strip_chain_id": "clipB",
                    "t0_sec": 3500.0,
                    "t1_sec": 3566.0,
                    "predicted_category": "outcome",
                    "first_event": "pass",
                    "last_event": "goal",
                    "event_sequence": ["pass", "goal"],
                },
            ],
            key_event_times=[982.0, 3107.0, 3566.0],
        )
        for step in range(20):
            d = planner.decide(mem, step, 20)
            apply_planner_decision(mem, d)
            if d.get("tool") == "finish_story":
                break
        self.assertIn("ke_1", mem.selected_node_ids)
        self.assertIn("ke_2", mem.selected_node_ids)
        self.assertTrue(any(n.startswith("strip_") for n in mem.selected_node_ids) or "strip_clipA" in mem.selected_node_ids or any("clipA" in n for n in mem.selected_node_ids))
        rel = finalize_relations(mem)
        self.assertGreaterEqual(len(rel["relations"]), 1)
        sg = build_full_story_graph(
            memory=mem,
            relations_doc=rel,
            score_anchors=[{"kind": "score_change", "score_after": [0, 1], "event_time_sec": 1079, "event_id": "e1"}],
            strip_chains=[],
        )
        edl = build_r23_candidate_edl(story_graph=sg)
        self.assertGreaterEqual(edl["n_goal_segments"], 2)
        self.assertFalse(edl["render_ready"])

    def test_ensure_adds_missing_verified_goals(self):
        mem = V2R23StoryMemory()
        mem.key_events = [
            {
                "key_event_id": "ke_1",
                "score_before": None,
                "score_after": [0, 1],
                "media_time_sec": 100.0,
                "inferred_event_id": "g0",
            },
            {
                "key_event_id": "ke_2",
                "score_before": [0, 1],
                "score_after": [1, 1],
                "media_time_sec": 200.0,
                "inferred_event_id": "g1",
            },
        ]
        # Simulate DeepSeek selecting only a strip
        apply_planner_decision(
            mem,
            {
                "type": "tool",
                "tool": "select_node",
                "arguments": {"node_id": "strip_clipX", "beat": "buildup", "why": "llm"},
            },
        )
        actions = ensure_verified_goals_selected(mem)
        self.assertTrue(actions)
        self.assertIn("ke_1", mem.selected_node_ids)
        self.assertIn("ke_2", mem.selected_node_ids)
        self.assertIn("strip_clipX", mem.selected_node_ids)
        rel = finalize_relations(mem)
        types = {r["relation_type"] for r in rel["relations"]}
        self.assertIn("temporal", types)


if __name__ == "__main__":
    unittest.main()
