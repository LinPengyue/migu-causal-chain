"""Regression for P8/P9: Planner must see source-cited Critic observations.

No HTTP, video model or real-video claim. Frozen P10-D-inspired example checks
that a sampled-frame KEEP finding and possible lost buildup function are carried
to the Planner, rather than silently dropped from its context.
"""
from __future__ import annotations

import json

from story_video_agent_v3.story_paid_eval import (
    _planner_video_critic_context,
    run_llm_revision_planner,
)
from story_video_agent_v3.story_timeline import build_story_timeline


class FakeTextPlanner:
    def __init__(self):
        self.payload = None

    def revise_decision(self, *, system_prompt, user_prompt, mock_decision):
        assert "video_critic_observations" in user_prompt
        self.payload = json.loads(
            user_prompt.split("INPUT:\n", 1)[1].split("\nReturn JSON:", 1)[0]
        )
        return {
            "provider_mode": "openai_compatible",
            "content": json.dumps({
                "decision": "KEEP", "revision_intents": [],
                "exploratory_intents": [],
                "rationale": "No visually supported improvement identified.",
            }),
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 30, "completion_tokens": 14},
        }


def _diag():
    return {
        "timeline": build_story_timeline([
            {"segment_id": "deficit", "role": "deficit_scoreboard_anchor",
             "media_in": 10.0, "media_out": 13.0},
            {"segment_id": "effort", "role": "buildup_action",
             "media_in": 16.0, "media_out": 28.0},
            {"segment_id": "turn", "role": "equalizer_goal_action",
             "media_in": 60.0, "media_out": 68.0},
        ]),
        "issues": [
            {"issue_id": "jump_deficit_to_effort", "category": "transition",
             "evidence_sufficiency": "needs_video_verify"}
        ],
        "protected_goal_segment_ids": ["turn"],
    }


def _critic():
    return {
        "ok": True, "provider_mode": "real",
        "parsed": {
            "keep_story_if_no_defect": True,
            "overall_narrative_quality": "coherent in sampled frames",
            # Raw hallucinated IDs must never bypass normalized evidence below.
            "semantic_evidence": [{
                "issue_id": "fake", "observed_fact": "UNVERIFIED_RAW",
                "evidence_refs": [{"frame_id": "invented"}],
            }],
        },
        "semantic_evidence": [{
            "issue_id": "jump_deficit_to_effort",
            "evidence_tier": "FRAME_CITED",
            "frame_refs": ["f_before", "f_after"],
            "observed_fact": "The score remains constant across sampled frames.",
            "defect_hypothesis": "Time compressed but no missing state identified.",
            "supports_original_issue": False,
        }],
        "frame_coverage": {
            "covered_segment_ids": ["deficit", "effort"],
            "unobserved_media_segment_ids": ["turn"],
        },
    }


def test_real_sampled_critic_observations_reach_planner_without_false_authority(tmp_path):
    fake = FakeTextPlanner()
    result = run_llm_revision_planner(
        fake, diagnosis=_diag(), vlm_critic=_critic(),
        protected_goal_ids=["turn"], audit_dir=tmp_path,
        allow_exploratory_proposals=True,
    )
    assert result["ok"] and result["decision"] == "KEEP"
    obs = fake.payload["video_critic_observations"]
    assert obs["observation_status"] == "REAL_SAMPLED_FRAMES"
    assert obs["keep_story_if_no_defect_in_observed_frames"] is True
    assert obs["claims_full_video_watch"] is False
    assert obs["unobserved_media_segment_ids"] == ["turn"]
    facts = obs["visual_evidence_with_checkable_frame_ids"]
    assert len(facts) == 1
    assert facts[0]["frame_refs"] == ["f_before", "f_after"]
    assert facts[0]["evidence_tier"] == "FRAME_CITED"
    assert facts[0]["supports_original_issue"] is False
    assert "UNVERIFIED_RAW" not in json.dumps(fake.payload)
    hints = fake.payload["existing_clip_narrative_function_hints"]
    assert len(hints) == 1
    assert hints[0]["target_segment_id"] == "effort"
    assert hints[0]["before_role_hint"] == "deficit_scoreboard_anchor"
    assert hints[0]["after_role_hint"] == "equalizer_goal_action"
    assert hints[0]["narrative_function_status"] == "UNVERIFIED_ROLE_HINT"
    assert not any(h["target_segment_id"] == "turn" for h in hints)


def test_failed_or_mock_critic_cannot_transfer_keep_or_uncited_visual_claims():
    bad = _critic()
    bad["ok"] = False
    bad["provider_mode"] = "degraded"
    bad["semantic_evidence"] = [{
        "issue_id": "fake", "frame_refs": ["invented"],
        "observed_fact": "A fully invented video conclusion",
    }]
    out = _planner_video_critic_context(bad)
    assert out["observation_status"] == "UNAVAILABLE"
    assert out["keep_story_if_no_defect_in_observed_frames"] is None
    assert out["visual_evidence_with_checkable_frame_ids"] == []
    assert out["covered_segment_ids"] == []


def test_evidence_packet_is_bounded_and_uncited_text_not_transferred():
    critic = _critic()
    critic["semantic_evidence"] = [
        {"issue_id": f"issue_{i}", "frame_refs": [f"f{i}"],
         "observed_fact": "OK" * 1000}
        for i in range(9)
    ] + [{"issue_id": "uncited", "observed_fact": "ignore"}]
    out = _planner_video_critic_context(critic, max_items=3)
    rows = out["visual_evidence_with_checkable_frame_ids"]
    assert len(rows) == 3
    assert all(len(x["observed_fact"]) <= 420 for x in rows)
    assert all(x["issue_id"] != "uncited" for x in rows)
