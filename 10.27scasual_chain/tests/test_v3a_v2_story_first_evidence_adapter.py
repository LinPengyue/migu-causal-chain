"""V2 Evidence Search branch boundaries: zero HTTP, no Planner promotion."""
from __future__ import annotations

import json

from story_video_agent_v3.story_e2e_cli import build_parser
from story_video_agent_v3.story_first_evidence_adapter import (
    planner_safe_story_first_summary,
    read_story_first_observation_branch,
)
from story_video_agent_v3.story_first_hypotheses import (
    build_observation_plan,
    parse_hypotheses,
    prepare_story_input,
)


def _fixture():
    edl = [
        {"segment_id": "opening", "role": "opponent_opening_goal_action",
         "media_in": 100, "media_out": 112, "include_in_cut": True},
        {"segment_id": "equalizer", "role": "equalizer_goal_action",
         "media_in": 850, "media_out": 866, "include_in_cut": True},
    ]
    events = [
        {"event_id": eid, "event_type": typ,
         "media_time": {"start_time_sec": t - 3,
                        "event_time_sec": t, "end_time_sec": t + 3},
         "video_context": {"broadcast_phase": "LIVE"}}
        for eid, typ, t in (("a", "foul", 150), ("b", "shot", 700))
    ]
    plan = {"plot": "existing-V3R-story", "immutable": True}
    return edl, events, plan


def _write_poc(tmp_path, edl, events, plan, *, has_hypothesis=True):
    prepared = prepare_story_input(edl, events, story_plan=plan)
    if has_hypothesis:
        proposal = {
            "hypotheses": [{
                "hypothesis_id": "H1",
                "mechanism_key": "potential_shift",
                "narrative_summary": "可能存在尚未核验的转折关系",
                "supporting_event_ids": ["a", "b"],
                "proposed_long_range_relations": [{
                    "source_event_id": "a", "target_event_id": "b",
                    "relation_type": "causal_hypothesis",
                    "claim": "可能存在关联，未验证",
                }],
                "falsification_conditions": ["视频中不存在相关发展"],
                "observation_queries": [{
                    "target_id": "event:a",
                    "question": "是否出现可观测的转折？",
                    "discriminating_signal": "原视频证据",
                }],
            }],
            "insufficient_evidence_reason": "",
        }
    else:
        proposal = {"hypotheses": [], "insufficient_evidence_reason": "unknown"}
    validated = parse_hypotheses(proposal, prepared)
    assert len(validated["hypotheses"]) == int(has_hypothesis)
    for name, doc in (
        ("prepared_story_input.json", prepared),
        ("story_hypotheses.json", validated),
        ("observation_plan.json", build_observation_plan(prepared, validated)),
    ):
        (tmp_path / name).write_text(json.dumps(doc, ensure_ascii=False),
                                     encoding="utf-8")


def _call(tmp_path, edl, events, plan):
    return read_story_first_observation_branch(
        artifacts_dir=tmp_path,
        current_edl=edl,
        current_story_plan=plan,
        permitted_events=events,
        current_source_sha256="a" * 64,
    )


def test_observation_queue_is_not_planner_candidate(tmp_path):
    edl, events, plan = _fixture()
    _write_poc(tmp_path, edl, events, plan)
    out = _call(tmp_path, edl, events, plan)
    assert out["status"] == "OBSERVATION_QUEUE_ONLY"
    assert out["hypothesis_count"] == 1
    assert out["observation_target_count"] == 1
    assert out["observation_targets"][0]["source_interval_sec"] == [142.0, 158.0]
    assert out["planner_candidates"] == []
    assert not out["first_live_certified"]
    assert not out["edl_modified"]
    assert out["verified_long_range_causal_links"] == 0
    summary = planner_safe_story_first_summary(out)
    assert summary["planner_candidate_count"] == 0
    assert "hypotheses" not in summary
    assert "observation_targets" not in summary


def test_zero_valid_hypotheses_stays_zero(tmp_path):
    edl, events, plan = _fixture()
    _write_poc(tmp_path, edl, events, plan, has_hypothesis=False)
    out = _call(tmp_path, edl, events, plan)
    assert out["status"] == "NO_VALID_HYPOTHESES"
    assert out["hypothesis_count"] == 0
    assert out["planner_candidate_count"] == 0


def test_stale_event_pts_rejected(tmp_path):
    edl, events, plan = _fixture()
    _write_poc(tmp_path, edl, events, plan)
    events[0]["media_time"]["event_time_sec"] += 20
    out = _call(tmp_path, edl, events, plan)
    assert out["status"] == "REJECTED_NO_PROMOTION"
    assert "event_ids_or_pts_changed" in out["reason"]


def test_stale_story_or_anchor_rejected(tmp_path):
    edl, events, plan = _fixture()
    _write_poc(tmp_path, edl, events, plan)
    assert _call(tmp_path, edl, events, {"plot": "different"})["status"] == (
        "REJECTED_NO_PROMOTION"
    )
    edl[1]["media_in"] += 12
    assert _call(tmp_path, edl, events, plan)["status"] == (
        "REJECTED_NO_PROMOTION"
    )


def test_missing_artifacts_fail_closed(tmp_path):
    edl, events, plan = _fixture()
    out = _call(tmp_path, edl, events, plan)
    assert out["status"] == "REJECTED_NO_PROMOTION"
    assert out["http_calls_by_adapter"] == 0
    assert out["planner_candidates"] == []


def test_cli_artifacts_opt_in_not_default():
    p = build_parser()
    args = p.parse_args(["--match-json", "match.json", "--source-mp4", "match.mp4",
                         "--out-dir", "out"])
    assert args.story_first_artifacts_dir is None
    args = p.parse_args(["--match-json", "match.json", "--source-mp4", "match.mp4",
                         "--out-dir", "out", "--story-first-artifacts-dir", "poc"])
    assert str(args.story_first_artifacts_dir) == "poc"
