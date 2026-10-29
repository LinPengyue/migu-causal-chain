"""Event-Guided Round 2 unit tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_video_agent.api_provider import ApiProvider
from story_video_agent.v2_event_adapter import (
    EventAdapterError,
    load_events_json,
    sanitize_raw_event,
    score_transition_anchors,
)
from story_video_agent.v2_event_guided_evidence import grade_with_frame_evidence
from story_video_agent.v2_event_guided_relation import review_relations
from story_video_agent.v2_event_guided_runner import (
    _apply_score_anchor_override,
    run_event_guided,
)
from story_video_agent.v2_event_guided_r2_audit import (
    evaluate_localization_against_refs,
    load_v1_reference_nodes,
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
                "media_time": {
                    "event_time_sec": 100.0,
                    "start_time_sec": 95.0,
                    "end_time_sec": 105.0,
                },
                "video_context": {"broadcast_phase": "LIVE", "is_replay": False},
                "attributes": {
                    "Score_Recognition": ["0:1"],
                    "criticality": 0.9,
                },
                "scores": {"model": 0.99},
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
                "attributes": {"Score_Recognition": ["1:1"]},
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
    def test_whitelist_strips_quality(self):
        std = sanitize_raw_event(_sample_events_payload()["events"][0])
        assert std is not None
        self.assertEqual(std["score_pair"], [0, 1])
        self.assertNotIn("criticality", std["attributes"])

    def test_refuse_causal_payload(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.json"
            p.write_text(json.dumps({"events": [], "causal_chains": [{"id": "x"}]}), encoding="utf-8")
            with self.assertRaises(EventAdapterError):
                load_events_json(p, input_source="human_corrected")

    def test_score_anchors(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "events.json"
            p.write_text(json.dumps(_sample_events_payload()), encoding="utf-8")
            bundle = load_events_json(p, input_source="human_corrected")
            changes = [a for a in score_transition_anchors(bundle["events"]) if a["kind"] == "score_change"]
            self.assertEqual(len(changes), 2)


class TestEvidenceStrict(unittest.TestCase):
    def test_keyword_without_frame_not_localized(self):
        obs = {
            "media_start_sec": 0,
            "media_end_sec": 8,
            "frames": [],
            "perception": {
                "notes": "Player shoots and ball into the net. Live.",
                "observed_actions": ["shot on goal", "ball in net"],
            },
        }
        g = grade_with_frame_evidence(observation=obs, window_span_sec=8)
        self.assertNotEqual(g["grade"], "action_localized")
        self.assertTrue(g["keyword_only_insufficient"])

    def test_frame_cite_allows_localized(self):
        obs = {
            "media_start_sec": 0,
            "media_end_sec": 8,
            "frames": [{"frame_id": "f_0012"}],
            "perception": {
                "notes": "f_0012 player shoots; f_0013 ball enters the net. Live broadcast.",
                "observed_actions": ["shot (f_0012)", "ball into the net (f_0013)"],
                "frame_ids": ["f_0012", "f_0013"],
            },
        }
        g = grade_with_frame_evidence(observation=obs, window_span_sec=8)
        self.assertEqual(g["grade"], "action_localized")
        self.assertTrue(g["shooting_action_evidence"])
        self.assertTrue(g["goal_result_evidence"])

    def test_replay_cutaway_does_not_block_shot_net(self):
        obs = {
            "media_start_sec": 0,
            "media_end_sec": 10,
            "frames": [{"frame_id": "f_0006"}, {"frame_id": "f_0007"}],
            "perception": {
                "notes": (
                    "f_0006 shows the shot trajectory. f_0007 ball is in the net. "
                    "f_0008 provides a close-up replay angle of the dribble."
                ),
                "observed_actions": [
                    "Attacker shoots ball towards goal (f_0006)",
                    "Ball enters the net (f_0007)",
                ],
                "frame_ids": ["f_0006", "f_0007"],
            },
        }
        g = grade_with_frame_evidence(observation=obs, window_span_sec=10)
        self.assertEqual(g["grade"], "action_localized")
        self.assertEqual(g["live_or_replay"], "mixed")


class TestRelationReview(unittest.TestCase):
    def test_causal_without_evidence_downgraded(self):
        out = review_relations(
            [
                {
                    "from_event_id": "a",
                    "to_event_id": "b",
                    "relation_type": "causal",
                    "explanation": "Equalizer shifts momentum leading to go-ahead",
                    "supporting_evidence_ids": [],
                }
            ]
        )
        self.assertEqual(out["n_downgraded"], 1)
        self.assertEqual(out["relations"][0]["relation_type"], "narrative")

    def test_temporal_accepted(self):
        out = review_relations(
            [
                {
                    "from_event_id": "a",
                    "to_event_id": "b",
                    "relation_type": "temporal",
                    "explanation": "a before b",
                    "supporting_evidence_ids": [],
                }
            ]
        )
        self.assertEqual(out["n_accepted"], 1)


class TestOverrideAndAudit(unittest.TestCase):
    def test_override_no_comeback(self):
        anchors = [
            {"kind": "initial_score", "score_pair": [0, 1]},
            {"kind": "score_change", "score_after": [2, 1]},
        ]
        out = _apply_score_anchor_override({"answer": "no_comeback", "reason": "x"}, anchors)
        self.assertEqual(out["answer"], "story_candidate")

    def test_strict_vs_loose_thresholds(self):
        preds = [
            {
                "task_id": "p",
                "window": (100.0, 110.0),
                "grade_keyword": "action_localized",
                "live_or_replay_keyword": "live",
                "observed_actions": [],
                "notes": "",
                "has_frame_cite": True,
            }
        ]
        refs = [
            {
                "id": "g",
                "role": "equalizer_goal_action",
                "category": "goal_action",
                "reference_strength": "weak_reference",
                "media_start_sec": 95.0,
                "media_end_sec": 115.0,
            }
        ]
        ev = evaluate_localization_against_refs(preds=preds, refs=refs)
        self.assertEqual(ev["n_strict_hits"], 1)


class TestModesMock(unittest.TestCase):
    def _video(self) -> Path:
        candidates = [
            Path("/data2/lpy1/_story_va_previews/phase5/croatia_story_clean.mp4"),
        ]
        video = next((p for p in candidates if p.is_file()), None)
        if video is None:
            self.skipTest("no local mp4")
        return video

    def test_fixed_and_rule_mock(self):
        video = self._video()
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            events = td_path / "events.json"
            payload = _sample_events_payload()
            for i, e in enumerate(payload["events"]):
                base = 5.0 + i * 8.0
                e["media_time"] = {
                    "event_time_sec": base + 2,
                    "start_time_sec": base,
                    "end_time_sec": base + 4,
                }
            events.write_text(json.dumps(payload), encoding="utf-8")
            api = ApiProvider(force_mock=True, require_real=False, max_calls=30, max_cost_usd=0.2)
            fixed = run_event_guided(
                video=video,
                events_path=events,
                out_dir=td_path / "fixed",
                api=api,
                planner_mode="fixed",
                export_review_clips=False,
            )
            self.assertEqual(fixed["discovery"]["mode"], "event_fixed")
            self.assertFalse(fixed["render_ready"])
            rule = run_event_guided(
                video=video,
                events_path=events,
                out_dir=td_path / "rule",
                api=api,
                planner_mode="rule",
                max_steps=4,
                frame_budget=12,
                use_llm_planner=False,
                export_review_clips=False,
            )
            self.assertIn("event_rule", rule["discovery"]["mode"])
            agent = run_event_guided(
                video=video,
                events_path=events,
                out_dir=td_path / "agent",
                api=api,
                planner_mode="agent",
                max_steps=4,
                frame_budget=12,
                use_llm_planner=True,
                export_review_clips=False,
            )
            # mock LLM still produces autonomy log entries
            self.assertTrue((td_path / "agent" / "autonomous_search_trace.json").is_file())
            self.assertFalse(agent["render_ready"])


if __name__ == "__main__":
    unittest.main()
