"""P10-B zero-HTTP tests for inference-only long-range narrative graph.

Synthetic frames and mocked provider prove wiring/binding, NOT narrative quality.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent_v3.story_inferred_narrative_graph import (
    GRAPH_ROLE,
    GRAPH_SCHEMA,
    attach_validated_video_review,
    build_inferred_narrative_graph,
    graph_observation_targets,
    graph_planner_context,
)
from story_video_agent_v3.story_paid_eval import (
    run_llm_revision_planner,
    run_vlm_story_critic,
)
from story_video_agent_v3.story_revision_planner import plan_from_diagnosis
from story_video_agent_v3.story_timeline import build_story_timeline


def _edl():
    return [
        {"segment_id": "setup", "role": "opponent_opening",
         "media_in": 10.0, "media_out": 18.0, "event_id": "ev_1"},
        {"segment_id": "pressure", "role": "buildup_action",
         "media_in": 30.0, "media_out": 38.0,
         "event_ids": ["ev_2"], "short_chain_ids": ["short_2"]},
        {"segment_id": "goal", "role": "equalizer_goal_action",
         "media_in": 60.0, "media_out": 69.0, "event_id": "ev_goal"},
        {"segment_id": "ending", "role": "ending_wrap",
         "media_in": 76.0, "media_out": 82.0},
    ]


def _graph():
    return build_inferred_narrative_graph(
        edl=_edl(), story_plan={"story_goal": "How the deficit was reversed"},
        source_sha256="d" * 64,
    )


class _MockModel:
    def __init__(self):
        self.planner_prompt = ""
        self.vision_prompt = ""

    def revise_decision(self, *, system_prompt, user_prompt, mock_decision):
        self.planner_prompt = user_prompt
        return {
            "content": json.dumps({
                "decision": "UNRESOLVED", "revision_intents": [],
                "rationale": "Need story video evidence",
            }),
            "provider_mode": "openai_compatible",
            "usage": {"prompt_tokens": 1, "completion_tokens": 10},
        }

    def vision_json(self, *, prompt, frame_paths, frame_ids, mock_obj, frame_bindings=None):
        self.vision_prompt = prompt
        return {
            "content": json.dumps({
                "semantic_evidence": [],
                "keep_story_if_no_defect": True,
                "overall_narrative_quality": "unknown",
            }),
            "provider_mode": "openai_compatible",
            "usage": {"prompt_tokens": 1, "completion_tokens": 10},
        }


def _semantic_review(*, valid=True, claim_status="SEMANTIC_HYPOTHESIS"):
    return {
        "semantic_provider_used": True,
        "fixture_or_offline": False,
        "observation_scope": {"sent_frame_ids": ["frame_1", "frame_2"]},
        "semantic_evidence": [{
            "schema": "v3a_semantic_evidence_item_v1",
            "issue_id": "issue_transition",
            "citation_status": "FRAME_CITED",
            "claim_status": claim_status,
            "frame_refs": ["frame_1", "frame_2" if valid else "forged_frame"],
            "observation_scope": {
                "method": "ordered_multi_frame_vlm",
                "claims_full_video_watch": False,
            },
        }],
    }


class TestAgentInferredStoryGraph(unittest.TestCase):
    def test_graph_has_story_edges_not_fake_causal_facts(self):
        graph = _graph()
        self.assertEqual(graph["schema"], GRAPH_SCHEMA)
        self.assertEqual(graph["data_role"], GRAPH_ROLE)
        self.assertEqual(len(graph["nodes"]), 4)
        self.assertEqual(len(graph["edges"]), 3)
        self.assertTrue(all(not x["is_match_causal_claim"] for x in graph["edges"]))
        self.assertTrue(all(x["relation"] == "editorial_adjacency" for x in graph["edges"]))
        self.assertEqual(graph["nodes"][1]["short_chain_ids"], ["short_2"])
        self.assertTrue(any(x["from_node"] == "short_chain:short_2"
                            for x in graph["evidence_links"]))
        self.assertFalse(graph_planner_context(graph)["graph_edges_are_causal_facts"])

    def test_graph_bound_to_source_and_exact_edl_version(self):
        first = _graph()
        second_edl = _edl()
        second_edl[1]["media_out"] = 42
        updated = build_inferred_narrative_graph(
            edl=second_edl,
            story_plan={"story_goal": "How the deficit was reversed"},
            source_sha256="d" * 64,
        )
        self.assertNotEqual(first["edl_sha256"], updated["edl_sha256"])
        self.assertEqual(first["source_sha256"], updated["source_sha256"])
        self.assertEqual(first["story_goal_hint"], updated["story_goal_hint"])

    def test_targeted_observation_prioritizes_story_state_not_largest_pts_jump(self):
        graph = _graph()
        targets = graph_observation_targets(graph, max_targets=2)
        self.assertEqual(len(targets), 2)
        self.assertTrue(all(x["category"] == "graph_transition_review_only"
                            for x in targets))
        self.assertTrue(all(x["story_defect_confirmed"] is False for x in targets))
        self.assertTrue(all(len(x["segment_ids"]) == 2 for x in targets))
        self.assertTrue(any("goal" in x["segment_ids"] for x in targets))

    def test_no_false_intent_on_unobserved_graph(self):
        graph = _graph()
        diag = {
            "issues": [],
            "timeline": build_story_timeline(_edl()),
            "protected_goal_segment_ids": ["goal"],
            "agent_narrative_graph": graph,
        }
        out = plan_from_diagnosis(diag, offline=True)
        self.assertNotEqual(out["decision"], "REVISE")
        self.assertFalse((out.get("agent_narrative_graph_context") or {}).get("authorizes_revision", True))

    def test_gold_leak_rejected_top_level_and_nested(self):
        plan = {"data_role": "BENCHMARK_GOLD", "story_goal": "leaked"}
        with self.assertRaises(ValueError):
            build_inferred_narrative_graph(edl=_edl(), story_plan=plan)
        plan2 = {"title": "normal", "nested": {"schema": "migu_long_range_story_chain_v1"}}
        with self.assertRaises(ValueError):
            build_inferred_narrative_graph(edl=_edl(), story_plan=plan2)
        corrupt_edl = _edl()
        corrupt_edl[0]["benchmark"] = {"data_role": "BENCHMARK_GOLD"}
        with self.assertRaises(ValueError):
            build_inferred_narrative_graph(edl=corrupt_edl)

    def test_no_match_specific_pts_or_team_shortcuts(self):
        graph = _graph()
        self.assertEqual(graph["nodes"][0]["source_window"], [10.0, 18.0])
        self.assertNotIn("match_id", graph)
        self.assertFalse(any("UAE" in repr(x) for x in graph["nodes"]))

    def test_unverified_or_fake_observation_does_not_update_graph(self):
        graph = _graph()
        issues = [{"issue_id": "issue_transition", "segment_ids": ["pressure", "goal"]}]
        for obs in (
            {"semantic_provider_used": False, "fixture_or_offline": True},
            _semantic_review(valid=False),
            {
                "semantic_provider_used": True, "fixture_or_offline": False,
                "observation_scope": {"sent_frame_ids": ["frame_1", "frame_2"]},
                "semantic_evidence": [{
                    "issue_id": "issue_transition", "citation_status": "FRAME_CITED",
                    "frame_refs": ["frame_1", "frame_2"], "claim_status": "DEFECT_CONFIRMED",
                }],
            },
        ):
            updated = attach_validated_video_review(graph, observations=obs, diagnosis_issues=issues)
            self.assertEqual(updated["summary"]["model_reviewed_transitions"], 0)
            self.assertEqual(graph["summary"]["model_reviewed_transitions"], 0)

    def test_valid_normalized_video_claim_is_not_human_ground_truth(self):
        graph = _graph()
        issues = [{"issue_id": "issue_transition", "segment_ids": ["pressure", "goal"]}]
        updated = attach_validated_video_review(
            graph, observations=_semantic_review(), diagnosis_issues=issues,
        )
        self.assertGreater(updated["summary"]["model_reviewed_transitions"], 0)
        self.assertTrue(any(
            edge["narrative_evidence_status"] == "MODEL_REVIEWED_NOT_HUMAN_VERIFIED"
            for edge in updated["edges"]
        ))
        self.assertTrue(all(not edge["is_match_causal_claim"] for edge in updated["edges"]))
        self.assertEqual(graph["summary"]["model_reviewed_transitions"], 0)

    def test_unknown_issue_ref_cannot_annotate_graph(self):
        graph = _graph()
        updated = attach_validated_video_review(
            graph, observations=_semantic_review(),
            diagnosis_issues=[{"issue_id": "other_issue", "segment_ids": ["goal"]}],
        )
        self.assertEqual(updated["summary"]["model_reviewed_transitions"], 0)

    def test_planner_receives_graph_context_without_extra_http(self):
        model = _MockModel()
        graph = _graph()
        diag = {
            "issues": [], "timeline": build_story_timeline(_edl()),
            "agent_narrative_graph": graph,
        }
        with tempfile.TemporaryDirectory() as d:
            response = run_llm_revision_planner(
                model, diagnosis=diag, vlm_critic={},
                protected_goal_ids=["goal"], audit_dir=Path(d),
            )
        self.assertTrue(response["ok"])
        self.assertEqual(response["decision"], "UNRESOLVED")
        self.assertIn('"agent_inferred_narrative_graph"', model.planner_prompt)
        self.assertIn("AGENT_INFERRED", model.planner_prompt)
        self.assertIn("STRUCTURAL HYPOTHESIS", model.planner_prompt)

    def test_vlm_critic_receives_graph_hints_and_keeps_stills_scope(self):
        model = _MockModel()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            frames = []
            for i, t in enumerate([2.0, 15.0]):
                path = root / f"frame_{i}.jpg"
                path.write_bytes(b"dummy synthetic frame")
                frames.append({"frame_id": "frame_%d" % i, "story_sec": t,
                               "path": str(path)})
            diag = {
                "issues": [], "timeline": build_story_timeline(_edl()),
                "agent_narrative_graph": _graph(),
                "protected_goal_segment_ids": ["goal"],
            }
            result = run_vlm_story_critic(
                model,
                observations={"layers": {"global": {"frames": frames}}},
                diagnosis=diag,
                audit_dir=root,
            )
        self.assertTrue(result["ok"])
        self.assertIn("AGENT_NARRATIVE_GRAPH_HINTS", model.vision_prompt)
        self.assertIn("not evidence of a defect", model.vision_prompt)
        self.assertFalse(result["claims_full_video_watch"])


if __name__ == "__main__":
    unittest.main()
