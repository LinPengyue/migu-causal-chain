"""Zero-HTTP tests: ACL benchmark labels are human-only, evidence-linked."""
import copy
import unittest

from story_video_agent_v3.story_chain_annotation import (
    SCHEMA, validate_long_story_chain,
)


def sample():
    return {
        "schema": SCHEMA,
        "data_role": "BENCHMARK_GOLD",
        "match_id": "held_out_match",
        "story_id": "s1",
        "story_goal": "How a trailing side changed the result",
        "annotator_id": "human_1",
        "annotation_status": "draft",
        "source_video_sha256": "a" * 64,
        "split": "dev",
        "template_type": "comeback",
        "nodes": [
            {
                "node_id": "state_1", "node_type": "match_state",
                "narrative_role": "setup", "assertion_status": "confirmed",
                "description": "The home team is trailing",
                "event_ids": ["event_1"], "short_chain_ids": [],
                "source_windows": [{"start_sec": 10.0, "end_sec": 16.0, "live_status": "FIRST_LIVE"}],
            },
            {
                "node_id": "turn_2", "node_type": "atomic_event",
                "narrative_role": "climax", "assertion_status": "confirmed",
                "description": "An equalizer changes the score state",
                "event_ids": ["event_2"], "short_chain_ids": ["chain_2"],
                "source_windows": [{"start_sec": 30.0, "end_sec": 38.0, "live_status": "FIRST_LIVE"}],
            },
        ],
        "edges": [
            {
                "edge_id": "e1", "from_node": "state_1", "to_node": "turn_2",
                "relation": "temporal", "assertion_status": "confirmed",
                "rationale": "The deficit state predates the equalizer",
                "evidence": [],
            },
        ],
    }


class TestLongStoryAnnotation(unittest.TestCase):
    def test_valid_human_annotation(self):
        report = validate_long_story_chain(sample())
        self.assertTrue(report["valid"], report["errors"])
        self.assertFalse(report["semantic_truth_verified"])
        self.assertTrue(report["benchmark_only"])

    def test_never_accept_gold_as_agent_input(self):
        doc = sample()
        doc["data_role"] = "AGENT_INPUT"
        self.assertFalse(validate_long_story_chain(doc)["valid"])

    def test_replay_not_permitted(self):
        doc = sample()
        doc["nodes"][0]["source_windows"][0]["live_status"] = "REPLAY"
        self.assertFalse(validate_long_story_chain(doc)["valid"])

    def test_no_fake_or_reverse_pts(self):
        doc = sample()
        doc["nodes"][0]["source_windows"][0]["end_sec"] = 2
        self.assertFalse(validate_long_story_chain(doc)["valid"])
        doc = sample()
        doc["nodes"][0]["source_windows"][0]["end_sec"] = float("nan")
        self.assertFalse(validate_long_story_chain(doc)["valid"])

    def test_causal_claim_needs_cited_evidence(self):
        doc = sample()
        doc["edges"][0]["relation"] = "causal"
        self.assertFalse(validate_long_story_chain(doc)["valid"])
        doc["edges"][0]["evidence"] = [{"source": "short_chain_annotation", "ref": "chain_2"}]
        self.assertTrue(validate_long_story_chain(doc)["valid"])

    def test_no_ungrounded_long_story_node(self):
        doc = sample()
        doc["nodes"][1]["event_ids"] = []
        doc["nodes"][1]["short_chain_ids"] = []
        doc["nodes"][1]["source_windows"] = []
        self.assertFalse(validate_long_story_chain(doc)["valid"])

    def test_no_dangling_or_cyclic_dependencies(self):
        doc = sample()
        doc["edges"][0]["to_node"] = "unknown"
        self.assertFalse(validate_long_story_chain(doc)["valid"])
        doc = sample()
        doc["edges"].append({
            "edge_id": "e2", "from_node": "turn_2", "to_node": "state_1",
            "relation": "temporal", "assertion_status": "inferred",
            "rationale": "A false backward ordering", "evidence": [],
        })
        self.assertFalse(validate_long_story_chain(doc)["valid"])

    def test_unknown_live_is_warning_not_hallucinated_success(self):
        doc = sample()
        doc["nodes"][1]["source_windows"][0]["live_status"] = "UNVERIFIED"
        report = validate_long_story_chain(doc)
        self.assertTrue(report["valid"])
        self.assertTrue(report["warnings"])


if __name__ == "__main__":
    unittest.main()
