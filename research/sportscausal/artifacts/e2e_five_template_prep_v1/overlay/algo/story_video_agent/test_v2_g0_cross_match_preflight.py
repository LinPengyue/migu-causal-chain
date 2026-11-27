"""G0 synthetic isolation tests (no API, no production mutation)."""
from __future__ import annotations

import unittest
from pathlib import Path

from story_video_agent.v2_g0_cross_match_preflight import (
    assert_cache_binding,
    cache_isolation_key,
    classify_side_protagonist,
    reject_forbidden_input_path,
    reject_forbidden_payload,
    t01_arc_roles_for_goal_count,
)
from story_video_agent.v2_event_adapter import EventAdapterError, load_events_json
import json
import tempfile


class TestG0CacheIsolation(unittest.TestCase):
    def test_mismatch_rejected(self):
        expected = {
            "match_id": "match_A",
            "video_sha256": "vA",
            "events_sha256": "eA",
            "strip_provenance": "stripA",
        }
        bad = dict(expected)
        bad["match_id"] = "match_CROATIA"
        out = assert_cache_binding(expected=expected, cached=bad)
        self.assertFalse(out["ok"])
        self.assertEqual(out["action"], "reject_cache")
        self.assertFalse(out["render_ready"])

    def test_missing_provenance_rejected(self):
        out = assert_cache_binding(
            expected={"match_id": "a", "video_sha256": "v", "events_sha256": "e", "strip_provenance": "s"},
            cached={"match_id": "a"},
        )
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason"], "missing_provenance")

    def test_keys_differ_by_match(self):
        k1 = cache_isolation_key(match_id="A", video_sha256="v", events_sha256="e", strip_provenance="s")
        k2 = cache_isolation_key(match_id="B", video_sha256="v", events_sha256="e", strip_provenance="s")
        self.assertNotEqual(k1, k2)


class TestG0ForbiddenInputs(unittest.TestCase):
    def test_reject_causal_filename(self):
        out = reject_forbidden_input_path(Path("/data/foo_causal.json"))
        self.assertFalse(out["ok"])

    def test_reject_strip_gold_filename(self):
        out = reject_forbidden_input_path(Path("/data/strip_gold.json"))
        self.assertFalse(out["ok"])

    def test_reject_payload_keys(self):
        out = reject_forbidden_payload({"events": [], "causal_chains": []})
        self.assertFalse(out["ok"])

    def test_adapter_refuses_causal_top_key(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "events.json"
            p.write_text(json.dumps({"match_id": "x", "events": [], "causal_chains": []}), encoding="utf-8")
            with self.assertRaises(EventAdapterError):
                load_events_json(p, input_source="human_corrected")


class TestG0VariableT01(unittest.TestCase):
    def test_three_and_five_goal_arcs(self):
        a3 = t01_arc_roles_for_goal_count(3)
        a5 = t01_arc_roles_for_goal_count(5)
        self.assertEqual(a3["status"], "t01_minimal_arc")
        self.assertEqual(a5["status"], "t01_extended_arc")
        self.assertFalse(a3["render_ready"])
        self.assertFalse(a5["render_ready"])
        self.assertNotEqual(len(a3["roles"]), 5)  # roles != fixed five requirement

    def test_zero_goals_no_fabricated_story(self):
        z = t01_arc_roles_for_goal_count(0)
        self.assertIn("no_comeback", z["status"])
        self.assertEqual(z["roles"], [])

    def test_right_side_comeback(self):
        # left leads early, right trails then wins: 1-0, 1-1, 1-2
        path = [(1, 0), (1, 1), (1, 2)]
        out = classify_side_protagonist(score_path=path)
        self.assertTrue(out["comeback"])
        self.assertEqual(out["protagonist_side"], "right")
        self.assertFalse(out["render_ready"])

    def test_no_comeback_not_forced(self):
        path = [(1, 0), (2, 0), (3, 0)]
        out = classify_side_protagonist(score_path=path)
        self.assertFalse(out["comeback"])
        self.assertEqual(out.get("status"), "no_comeback")


if __name__ == "__main__":
    unittest.main()
