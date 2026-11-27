"""Strip-Guided unit tests (adapter + mock runner)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent.api_provider import ApiProvider
from story_video_agent.v2_strip_adapter import (
    StripAdapterError,
    adapt_strip_bundle,
    sanitize_predicted_chain,
)
from story_video_agent.v2_strip_guided_runner import run_strip_guided


def _mini_strip() -> dict:
    return {
        "match_id": "test",
        "chains": [
            {
                "clip_id": "clip00",
                "t0_ms": 1000000,
                "t1_ms": 1020000,
                "chain_category": "danger",
                "pred_chain_template_id": "shot_save_chain",
                "pred_chain_label_zh": "射门扑救链",
                "prob_top1": 0.8,
                "margin": 0.2,
                "event_ids": ["e1", "e2"],
                "events": [
                    {"event_id": "e1", "type": "shot", "t_ms": 1005000},
                    {"event_id": "e2", "type": "save", "t_ms": 1010000},
                ],
            }
        ],
    }


class TestStripAdapter(unittest.TestCase):
    def test_sanitize_and_source(self):
        row, diags = sanitize_predicted_chain(
            _mini_strip()["chains"][0], match_id="test", index=0, known_event_ids={"e1", "e2"}
        )
        self.assertEqual(row["prediction_source"], "causal_chain6_predicted")
        self.assertEqual(row["verification_status"], "unverified")
        self.assertEqual(row["confidence"], 0.8)
        self.assertEqual(row["t0_sec"], 1000.0)
        self.assertFalse(diags)

    def test_refuse_gold_payload(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.json"
            p.write_text(json.dumps({"chains": [], "strip_gold": []}), encoding="utf-8")
            with self.assertRaises(StripAdapterError):
                adapt_strip_bundle(p)

    def test_missing_event_diag(self):
        row, diags = sanitize_predicted_chain(
            _mini_strip()["chains"][0], match_id="test", index=0, known_event_ids={"e1"}
        )
        self.assertTrue(any("event_ids_not_in_events_json" in d for d in diags))
        self.assertEqual(row["event_sequence"][1]["mapping_status"], "unconfirmed")


class TestStripGuidedMock(unittest.TestCase):
    def test_mock_run(self):
        video = Path("/data2/lpy1/_story_va_previews/phase5/croatia_story_clean.mp4")
        if not video.is_file():
            self.skipTest("no preview mp4")
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            strip = td_path / "strip.json"
            events = td_path / "events.json"
            # strip times inside short preview (~131s)
            s = _mini_strip()
            s["chains"][0]["t0_ms"] = 20000
            s["chains"][0]["t1_ms"] = 35000
            strip.write_text(json.dumps(s), encoding="utf-8")
            events.write_text(
                json.dumps(
                    {
                        "match_id": "test",
                        "events": [
                            {
                                "event_id": "e1",
                                "event_type": "Shot",
                                "media_time": {
                                    "event_time_sec": 25,
                                    "start_time_sec": 20,
                                    "end_time_sec": 30,
                                },
                                "video_context": {"is_replay": False, "broadcast_phase": "LIVE"},
                                "attributes": {"Score_Recognition": ["0:1"]},
                            },
                            {
                                "event_id": "e2",
                                "event_type": "Save",
                                "media_time": {
                                    "event_time_sec": 32,
                                    "start_time_sec": 30,
                                    "end_time_sec": 35,
                                },
                                "video_context": {"is_replay": False, "broadcast_phase": "LIVE"},
                                "attributes": {"Score_Recognition": ["1:1"]},
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            api = ApiProvider(force_mock=True, require_real=False, max_calls=20, max_cost_usd=0.2)
            result = run_strip_guided(
                video=video,
                events_path=events,
                strip_path=strip,
                out_dir=td_path / "out",
                api=api,
                max_steps=4,
                frame_budget=12,
                use_llm_planner=False,
                export_review_clips=False,
            )
            self.assertFalse(result["render_ready"])
            self.assertTrue((td_path / "out" / "predicted_strip_chains.json").is_file())
            self.assertTrue((td_path / "out" / "story_candidates.json").is_file())
            self.assertTrue((td_path / "out" / "story_beats.json").is_file())
            self.assertTrue((td_path / "out" / "story_relations.json").is_file())
            self.assertTrue((td_path / "out" / "localized_story_clips.json").is_file())
            self.assertTrue((td_path / "out" / "story_agent_trace.json").is_file())
            bundle = json.loads((td_path / "out" / "predicted_strip_chains.json").read_text())
            self.assertEqual(bundle["prediction_source"], "causal_chain6_predicted")
            for c in bundle["chains"]:
                self.assertEqual(c["verification_status"], "unverified")


if __name__ == "__main__":
    unittest.main()
