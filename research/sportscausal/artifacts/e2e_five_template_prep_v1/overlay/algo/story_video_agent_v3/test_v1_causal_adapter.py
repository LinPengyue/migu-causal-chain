"""Unit tests for V1 causal adapter (no gold, no network)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from .v1_causal_adapter import score_transitions_from_events, strip_chains_to_v1_causal


class TestV1CausalAdapter(unittest.TestCase):
    def test_no_goal_invention_and_unresolved_transitions(self):
        raw = [
            {
                "event_id": "e1",
                "event_type": "Pass",
                "media_time": {"event_time_sec": 10.0, "start_time_sec": 9.0, "end_time_sec": 11.0},
                "video_context": {"is_replay": False, "broadcast_phase": "LIVE"},
                "attributes": {"Score_Recognition": ["0:0"]},
            },
            {
                "event_id": "e2",
                "event_type": "Shot",
                "media_time": {"event_time_sec": 20.0, "start_time_sec": 19.0, "end_time_sec": 21.0},
                "video_context": {"is_replay": False, "broadcast_phase": "LIVE"},
                "attributes": {"Score_Recognition": ["0:0"]},
            },
            {
                "event_id": "e3",
                "event_type": "Pass",
                "media_time": {"event_time_sec": 100.0, "start_time_sec": 99.0, "end_time_sec": 101.0},
                "video_context": {"is_replay": False, "broadcast_phase": "LIVE"},
                "attributes": {"Score_Recognition": ["1:0"]},
            },
        ]
        strip = {
            "mode": "reinfer_A_original",
            "chains": [{
                "chain_category": "danger",
                "template_id": "shot_save_chain",
                "t0_ms": 19000,
                "t1_ms": 21000,
                "event_ids": ["e2"],
                "clip_id": "c1",
            }],
        }
        doc = strip_chains_to_v1_causal(
            strip=strip, raw_events=raw, match_id="m", video_name="m.mp4",
        )
        self.assertEqual(doc["schema_version"], "1.0-min")
        self.assertEqual(doc["causal_chains"][0]["chain_category"], "险情链")
        self.assertEqual(doc["causal_chains"][0]["events"][0]["type"], "射门")
        types = [e["type"] for c in doc["causal_chains"] for e in c["events"]]
        self.assertNotIn("进球", types)
        meta = doc["v3_adapter"]
        self.assertEqual(meta["n_goal_terminals_in_adapted_chains"], 0)
        self.assertGreaterEqual(meta["n_unresolved_goal_actions"], 1)
        self.assertFalse(meta["render_ready"])

    def test_refuse_human_shaped_via_build_paths_guard(self):
        from .v1_causal_adapter import build_from_paths
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            human = {
                "schema_version": "1.0-min",
                "causal_chains": [{"events": [{"type": "进球", "t_ms": 1}]}],
            }
            sp = td / "fake_strip.json"
            sp.write_text(json.dumps(human), encoding="utf-8")
            ev = td / "events.json"
            ev.write_text(json.dumps({"events": []}), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                build_from_paths(
                    strip_path=sp, events_path=ev, out_path=td / "out.json",
                    match_id="m", video_name="m.mp4",
                )


if __name__ == "__main__":
    unittest.main()
