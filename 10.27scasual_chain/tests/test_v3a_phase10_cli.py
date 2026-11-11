"""Phase10 offline public CLI smoke tests. No external model calls."""
import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent_v3.story_quality_cli import main
from story_video_agent_v3.story_chain_annotation import SCHEMA
from story_video_agent_v3.story_quality_protocol import (
    G0_GATES, DIMENSIONS, RATING_SCHEMA, ALLOCATION_SCHEMA,
)


def write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


class TestPhase10CLI(unittest.TestCase):
    def test_valid_chain_command_and_reject_invalid_gold_role(self):
        doc = {
            "schema": SCHEMA, "data_role": "BENCHMARK_GOLD",
            "match_id": "m1", "story_id": "s1", "story_goal": "match state change",
            "annotator_id": "rater_1", "source_video_sha256": "b" * 64,
            "annotation_status": "draft", "template_type": "open", "split": "dev",
            "nodes": [
                {"node_id": "n1", "node_type": "match_state", "narrative_role": "setup",
                 "assertion_status": "confirmed", "description": "first state",
                 "event_ids": ["e1"], "source_windows": []},
                {"node_id": "n2", "node_type": "atomic_event", "narrative_role": "climax",
                 "assertion_status": "confirmed", "description": "later event",
                 "event_ids": ["e2"], "source_windows": []},
            ],
            "edges": [{"edge_id": "r1", "from_node": "n1", "to_node": "n2",
                       "relation": "temporal", "assertion_status": "confirmed",
                       "rationale": "event order", "evidence": []}],
        }
        with tempfile.TemporaryDirectory() as d:
            inp, out = Path(d) / "chain.json", Path(d) / "validation.json"
            write_json(inp, doc)
            self.assertEqual(main(["validate-chain", "--input", str(inp), "--out", str(out)]), 0)
            self.assertTrue(json.loads(out.read_text())["valid"])
            doc["data_role"] = "AGENT_INFERRED"
            write_json(inp, doc)
            self.assertEqual(main(["validate-chain", "--input", str(inp), "--out", str(out)]), 2)

    def test_blind_pair_cli_no_automatic_best(self):
        scores = {k: 4 for k in DIMENSIONS}
        reviews = {
            "schema": RATING_SCHEMA, "pair_id": "p1",
            "reviews": [
                {"rater_id": "h%d" % i, "preference": "Y_SLIGHT",
                 "scores": {"X": {k: 3 for k in DIMENSIONS}, "Y": scores},
                 "issues": []}
                for i in range(3)
            ],
        }
        allocation = {"schema": ALLOCATION_SCHEMA, "pair_id": "p1",
                      "X": "baseline", "Y": "candidate"}
        gates = {"gates": {side: {key: "PASS" for key in G0_GATES} for side in ("X", "Y")}}
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name, data in [("reviews", reviews), ("allocation", allocation), ("gates", gates)]:
                write_json(root / (name + ".json"), data)
            out = root / "verdict.json"
            self.assertEqual(main([
                "blind-pair", "--reviews", str(root / "reviews.json"),
                "--allocation", str(root / "allocation.json"),
                "--gates", str(root / "gates.json"), "--out", str(out),
            ]), 0)
            result = json.loads(out.read_text())
            self.assertEqual(result["decision"], "IMPROVED_HUMAN_EVIDENCE")
            self.assertFalse(result["automatic_best_update_allowed"])


if __name__ == "__main__":
    unittest.main()
