"""Event-Guided unit tests (adapter whitelist + mock runner)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent.api_provider import ApiProvider
from story_video_agent.v2_event_adapter import (
    EventAdapterError,
    load_events_json,
    planner_event_digest,
    sanitize_raw_event,
    score_transition_anchors,
)
from story_video_agent.v2_event_guided_eval import eval_action_windows
from story_video_agent.v2_event_guided_runner import (
    _apply_score_anchor_override,
    run_event_guided,
)


def _sample_events_payload() -> dict:
    return {
        "match_id": "test_match",
        "teams": {
            "team_1": {"name": "Home", "color": "white"},
            "team_2": {"name": "Away", "color": "red"},
        },
        "events": [
            {
                "event_id": "e1",
                "event_type": "Throw_in",
                "event_type_zh": "界外球",
                "media_time": {
                    "event_time_sec": 100.0,
                    "start_time_sec": 95.0,
                    "end_time_sec": 105.0,
                },
                "video_context": {"broadcast_phase": "LIVE", "is_replay": False},
                "attributes": {
                    "Score_Recognition": ["0:1"],
                    "criticality": 0.9,  # must be stripped
                    "emotional_intensity": 0.8,  # stripped
                },
                "scores": {"model": 0.99},  # quality scores — not match scoreboard
                "story_role": "opening_goal",  # forbidden — should not pass through attrs
            },
            {
                "event_id": "e2",
                "event_type": "Shot",
                "media_time": {
                    "event_time_sec": 200.0,
                    "start_time_sec": 195.0,
                    "end_time_sec": 205.0,
                },
                "video_context": {"broadcast_phase": "LIVE", "is_replay": False},
                "attributes": {"Score_Recognition": ["1:1"], "Body_Part": "Right_foot"},
            },
            {
                "event_id": "e3",
                "event_type": "Goal",
                "media_time": {
                    "event_time_sec": 300.0,
                    "start_time_sec": 295.0,
                    "end_time_sec": 310.0,
                },
                "video_context": {"broadcast_phase": "LIVE", "is_replay": False},
                "attributes": {"Score_Recognition": ["2:1"]},
            },
        ],
    }


class TestEventAdapter(unittest.TestCase):
    def test_whitelist_strips_story_and_quality(self):
        raw = _sample_events_payload()["events"][0]
        std = sanitize_raw_event(raw)
        assert std is not None
        self.assertEqual(std["event_id"], "e1")
        self.assertEqual(std["scoreboard"], "0:1")
        self.assertEqual(std["score_pair"], [0, 1])
        self.assertNotIn("criticality", std["attributes"])
        self.assertNotIn("emotional_intensity", std["attributes"])
        self.assertNotIn("story_role", std)
        self.assertNotIn("scores", std)

    def test_refuse_causal_payload(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.json"
            p.write_text(
                json.dumps({"events": [], "causal_chains": [{"id": "x"}]}),
                encoding="utf-8",
            )
            with self.assertRaises(EventAdapterError):
                load_events_json(p, input_source="human_corrected")

    def test_score_anchors_and_input_source(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "events.json"
            p.write_text(json.dumps(_sample_events_payload()), encoding="utf-8")
            bundle = load_events_json(p, input_source="human_corrected")
            self.assertEqual(bundle["input_source"], "human_corrected")
            self.assertEqual(bundle["n_kept"], 3)
            anchors = score_transition_anchors(bundle["events"])
            changes = [a for a in anchors if a["kind"] == "score_change"]
            self.assertEqual(len(changes), 2)
            self.assertEqual(changes[0]["score_after"], [1, 1])
            self.assertEqual(changes[1]["score_after"], [2, 1])
            digest = planner_event_digest(bundle)
            self.assertIn("score_anchors", digest)
            # Ensure no story_role leaked into digest events
            for e in digest["events"]:
                self.assertNotIn("story_role", e)

    def test_upstream_detected_tag(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "events.json"
            p.write_text(json.dumps(_sample_events_payload()), encoding="utf-8")
            bundle = load_events_json(p, input_source="upstream_detected")
            self.assertEqual(bundle["input_source"], "upstream_detected")


class TestOfflineEval(unittest.TestCase):
    def test_action_recall_proximity(self):
        verified = [
            {
                "task_id": "a",
                "media_start_sec": 190.0,
                "media_end_sec": 200.0,
                "grade": {"grade": "action_localized"},
            }
        ]
        gold = [
            {
                "id": "g1",
                "role": "equalizer_goal_action",
                "media_start_sec": 195.0,
                "media_end_sec": 210.0,
            }
        ]
        ev = eval_action_windows(verified=verified, gold=gold)
        self.assertEqual(ev["n_hits"], 1)
        self.assertEqual(ev["recall"], 1.0)

    def test_override_false_no_comeback(self):
        anchors = [
            {"kind": "initial_score", "score_pair": [0, 1]},
            {"kind": "score_change", "score_after": [1, 1]},
            {"kind": "score_change", "score_after": [2, 1]},
        ]
        out = _apply_score_anchor_override(
            {"type": "answer", "answer": "no_comeback", "reason": "confused"},
            anchors,
        )
        self.assertEqual(out["answer"], "story_candidate")
        self.assertIn("override", out)


class TestMockRunner(unittest.TestCase):
    def test_mock_run_no_causal_input(self):
        candidates = [
            Path("/data2/lpy1/_story_va_previews/phase5/croatia_story_clean.mp4"),
            Path("/data2/lpy1/_story_va_previews/phase5/croatia_story_qc.mp4"),
        ]
        video = next((p for p in candidates if p.is_file()), None)
        if video is None:
            self.skipTest("no local mp4 for mock runner")

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            events = td_path / "events.json"
            # Scale event times into a short clip range if needed — use small times
            payload = _sample_events_payload()
            # Keep times small for short smokes
            for i, e in enumerate(payload["events"]):
                base = 5.0 + i * 8.0
                e["media_time"] = {
                    "event_time_sec": base + 2,
                    "start_time_sec": base,
                    "end_time_sec": base + 4,
                }
            events.write_text(json.dumps(payload), encoding="utf-8")
            out = td_path / "out"
            api = ApiProvider(force_mock=True, require_real=False, max_calls=20, max_cost_usd=0.1)
            result = run_event_guided(
                video=video,
                events_path=events,
                out_dir=out,
                api=api,
                input_source="human_corrected",
                max_steps=4,
                frame_budget=12,
                use_llm_planner=False,
            )
            self.assertFalse(result["render_ready"])
            self.assertIn(result["discovery"]["discovery_status"], {
                "story_candidate",
                "partial_story",
                "no_comeback",
                "unresolved",
            })
            self.assertTrue((out / "event_bundle_sanitized.json").is_file())
            sanitized = json.loads((out / "event_bundle_sanitized.json").read_text())
            for e in sanitized["events"]:
                self.assertNotIn("story_role", e)
                self.assertNotIn("causal", json.dumps(e))


if __name__ == "__main__":
    unittest.main()
