"""Regression: Scheme A generation is interval-local and preserves output schema."""
import json

from algo.story_video_agent_v3.story_first_hypotheses import model_messages, select_story_interval


def test_local_patterns_prompt_stays_within_selected_interval():
    prepared = {
        "scope": {"from_role": "deficit", "to_role": "buildup", "source_interval_sec": [100, 200]},
        "story_plan_reference": "frozen",
        "event_inventory": [], "events": [], "probes": [],
    }
    messages = model_messages(prepared, max_hypotheses=5)
    assert "LOCAL NARRATIVE PATTERNS" in messages[0]["content"]
    assert "Do not work backward" in messages[0]["content"]
    payload = json.loads(messages[1]["content"])
    assert payload["story_scope"]["source_interval_sec"] == [100, 200]
    assert payload["generation_strategy"] == "interval_local_patterns_then_story_combinations"


def test_semantic_story_anchors_preferred_to_goal_fallback():
    edl = {"clips": [
        {"segment_id": "goal0", "role": "goal_action", "media_in": 10, "media_out": 20},
        {"segment_id": "deficit", "role": "deficit", "story_anchor": True,
         "media_in": 30, "media_out": 40},
        {"segment_id": "buildup", "role": "buildup", "story_anchor": True,
         "media_in": 80, "media_out": 90},
        {"segment_id": "goal1", "role": "goal_action", "media_in": 100, "media_out": 110},
    ]}
    scope = select_story_interval(edl)
    assert scope["from_segment_id"] == "deficit"
    assert scope["to_segment_id"] == "buildup"
    assert scope["source_interval_sec"] == [40.0, 80.0]
