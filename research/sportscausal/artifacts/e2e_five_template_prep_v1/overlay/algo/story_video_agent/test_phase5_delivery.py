"""Phase 5.1 unit tests: glitch+goal integrity, story graph structure."""

from __future__ import annotations

import json

import pytest

from story_video_agent.phase5_delivery import (
    apply_glitch_avoidance,
    assess_goal_completeness,
    build_story_graph,
    decide_arc_background_plan,
    plan_goal_clips_around_glitch,
    resolve_delivery_window_conflicts,
    select_delivery_rows,
    validate_story_graph,
)
from story_video_agent.phase5_pipeline import run_phase5
from story_video_agent_v3.global_story_critic import detect_goal_coverage_hypotheses
from story_video_agent_v3.story_first_hypotheses import adjacent_story_anchor_pairs


@pytest.mark.parametrize(
    ("opening_goals", "expect_opening"),
    [
        ([(225.0, False), (218.0, True), (190.0, False)], True),
        ([(225.0, False), (218.0, False)], False),
        ([(225.0, True)], False),
    ],
    ids=["unique-live-goal", "ambiguous-goals", "replay-only"],
)
def test_phase5_opening_goal_between_sparse_score_observations(tmp_path, opening_goals, expect_opening):
    observations = [
        (100.0, "0:0", False),
        (200.0, "0:0", False),
        (410.0, "0:0", True),
        (420.0, "0:1", False),
        (430.0, "0:1", False),
        (620.0, "1:1", False),
        (630.0, "1:1", False),
        (820.0, "2:1", False),
        (830.0, "2:1", False),
    ]
    events = [
        {
            "event_id": f"board_{index}",
            "event_type": "Pass",
            "event_type_zh": "传球",
            "media_time": {"event_time_sec": t_sec},
            "scores": {"score_recognition": score},
            "video_context": {"is_replay": replay},
        }
        for index, (t_sec, score, replay) in enumerate(observations)
    ]
    chains = [
        {
            "annotation_id": f"chain_{index}",
            "is_replay": replay,
            "events": [{
                "event_id": f"goal_{index}",
                "type": "进球",
                "type_en": "Goal",
                "t_ms": t_sec * 1000,
            }],
        }
        for index, (t_sec, replay) in enumerate([*opening_goals, (590.0, False), (790.0, False)])
    ]
    events_path = tmp_path / "events.json"
    causal_path = tmp_path / "causal.json"
    out_dir = tmp_path / "phase5"
    events_path.write_text(json.dumps({"events": events}), encoding="utf-8")
    causal_path.write_text(json.dumps({"causal_chains": chains}), encoding="utf-8")
    run_phase5(
        video=tmp_path / "source.mp4", events=events_path, causal=causal_path,
        out_dir=out_dir, skip_render=True,
    )
    edl = json.loads((out_dir / "candidate_edl.json").read_text(encoding="utf-8"))
    opening = [row for row in edl if row["role"] == "opponent_opening_goal_action"]
    issues = detect_goal_coverage_hypotheses(raw_events=events, edl=edl)
    opening_issues = [issue for issue in issues if issue["issue_id"] == "goal_coverage_00_to_01"]
    if expect_opening:
        assert [row["goal_anchor_t_sec"] for row in opening] == [225.0]
        assert adjacent_story_anchor_pairs(edl)[0] == (
            "seg_opponent_opening_goal_action", "seg_equalizer_goal_action",
        )
        assert not opening_issues
    else:
        assert not opening
        assert [issue["possible_action_interval"]["media_in"] for issue in opening_issues] == [200.0]


def test_glitch_split_keeps_approach_and_result():
    # Croatia-like: glitch before ball-in-net → approach + result, no bad frames
    clips, notes, fail = plan_goal_clips_around_glitch(
        6305.199,
        6327.199,
        [(6315.8, 6316.7, "neon")],
        must_cover=6317.199,
    )
    assert fail is None, (fail, notes, clips)
    parts = {c["part"]: c for c in clips}
    assert "approach" in parts and "result" in parts
    assert parts["approach"]["media_out"] <= 6315.8 + 1e-6
    assert parts["result"]["media_in"] >= 6316.7 - 1e-6
    assert parts["result"]["media_in"] <= 6317.199 <= parts["result"]["media_out"]
    facets = assess_goal_completeness(
        media_in=parts["result"]["media_in"],
        media_out=parts["result"]["media_out"],
        anchor=6317.199,
        has_approach_clip=True,
        glitch_break=True,
        approach_media_in=parts["approach"]["media_in"],
        approach_media_out=parts["approach"]["media_out"],
    )
    assert facets["result_visible"] and facets["approach_visible"]
    assert facets["goal_action_complete"] is True


def test_anchor_only_without_approach_is_incomplete():
    facets = assess_goal_completeness(
        media_in=6316.7,
        media_out=6327.2,
        anchor=6317.2,
        has_approach_clip=False,
        glitch_break=True,
    )
    assert facets["result_visible"] is True
    assert facets["approach_visible"] is False
    assert facets["goal_action_complete"] is False


def test_glitch_on_anchor_marks_failure():
    a, b, notes, fail = apply_glitch_avoidance(
        100.0,
        120.0,
        [(109.0, 111.0, "bad")],
        must_cover=110.0,
    )
    assert fail is not None
    assert "glitch" in fail or "anchor" in fail


def test_select_delivery_demotes_incomplete_goal():
    plan = {
        "segments": [
            {
                "segment_id": "seg_g",
                "beat": "高潮",
                "role": "lead_extend_1_goal_action",
                "shot_kind": "live",
                "media_in": 100.0,
                "media_out": 120.0,
                "time_status": "linked_event_ms",
                "time_provenance": {"t_sec": 110.0, "source": "linked_live_goal_event"},
                "event_ids": ["e1"],
                "render_eligibility": "candidate_only",
                "blocking_reasons": [],
                "narrative_order": 1,
                "evidence_refs": [],
            }
        ]
    }
    rows = select_delivery_rows(
        plan, glitch_ranges=[(109.0, 111.0, "bad")]
    )
    assert len(rows) == 1
    assert rows[0]["goal_action_complete"] is False
    assert "incomplete" in rows[0]["role"]


def test_story_graph_no_dangling_and_event_nodes():
    plan = {"match_id": "m", "story_tier": "story", "blocking_reasons": []}
    story = {
        "match_id": "m",
        "score_path": [
            {"score": "0:1", "t_sec": 10.0, "delta_side": "right"},
            {"score": "1:1", "t_sec": 20.0, "delta_side": "left"},
        ],
    }
    delivery = [
        {
            "segment_id": "seg_a",
            "beat": "铺垫",
            "role": "opponent_opening_goal_action",
            "shot_kind": "live",
            "media_in": 5.0,
            "media_out": 15.0,
            "time_status": "linked_event_ms",
            "event_ids": ["event_0001"],
            "goal_action_complete": True,
            "evidence_refs": [
                {
                    "used_as_fact": True,
                    "source": "opponent_opening_live_goal",
                    "event_id": "event_0001",
                }
            ],
        },
        {
            "segment_id": "seg_b",
            "beat": "转折",
            "role": "equalizer_goal_action",
            "shot_kind": "live",
            "media_in": 18.0,
            "media_out": 28.0,
            "time_status": "linked_event_ms",
            "event_ids": ["event_0002"],
            "goal_action_complete": True,
            "evidence_refs": [],
        },
    ]
    g = build_story_graph(plan=plan, story=story, delivery_edl=delivery)
    ok, problems = validate_story_graph(g)
    assert ok, problems
    ids = {n["id"] for n in g["nodes"]}
    assert "event:event_0001" in ids
    assert "event:event_0002" in ids
    assert any(n["type"] == "score_state" for n in g["nodes"])
    for e in g["edges"]:
        assert e["source"] in ids and e["target"] in ids
        assert e.get("semantic_verified") is not True or e["relation"] == "never"


def test_validate_detects_dangling():
    g = {
        "nodes": [{"id": "a", "type": "story_segment"}],
        "edges": [{"source": "a", "target": "missing", "relation": "event_association"}],
        "relation_types": ["event_association"],
    }
    ok, problems = validate_story_graph(g)
    assert not ok
    assert any("target_missing" in p for p in problems)


def test_ending_wrap_dropped_when_overlaps_go_ahead_board():
    rows = [
        {
            "segment_id": "seg_ga_board",
            "beat": "高潮",
            "role": "go_ahead_scoreboard_anchor",
            "media_in": 6956.12,
            "media_out": 6959.62,
            "blocking_reasons": [],
        },
        {
            "segment_id": "seg_wrap",
            "beat": "收尾",
            "role": "ending_story_wrap_score",
            "media_in": 6956.12,
            "media_out": 6961.12,
            "blocking_reasons": [],
        },
    ]
    out = resolve_delivery_window_conflicts(rows)
    roles = [r["role"] for r in out]
    assert "go_ahead_scoreboard_anchor" in roles
    assert "ending_story_wrap_score" not in roles


def test_arc_background_plan_for_multi_turn_prior():
    prior = [
        {"score": "0:1", "t_sec": 100.0, "delta_side": "right"},
        {"score": "1:1", "t_sec": 200.0, "delta_side": "left"},
    ]
    # protagonist right led, then arc starts later at 2:1 deficit
    dec = decide_arc_background_plan(
        prior=prior,
        protagonist_side="right",
        behind={"score": "2:1", "t_sec": 300.0},
    )
    assert dec["affects_comeback_understanding"] is True
    assert dec["mode"] == "title_and_key_boards"
    assert len(dec["boards_to_include"]) >= 1


def test_legacy_far_match_end_skipped_in_delivery():
    plan = {
        "segments": [
            {
                "segment_id": "seg_ending",
                "beat": "收尾",
                "role": "ending",
                "shot_kind": "live",
                "media_in": 7942.0,
                "media_out": 7954.0,
                "time_status": "event_ms",
                "time_provenance": {"t_sec": 7946.0},
                "event_ids": ["event_end"],
                "selection_reason": "ending_event",
                "render_eligibility": "candidate_only",
                "blocking_reasons": [],
                "narrative_order": 1,
                "evidence_refs": [],
            },
            {
                "segment_id": "seg_ending_story_wrap_score",
                "beat": "收尾",
                "role": "ending_story_wrap_score",
                "shot_kind": "scoreboard_anchor",
                "media_in": 7857.0,
                "media_out": 7862.0,
                "time_status": "score_path_only",
                "time_provenance": {
                    "t_sec": 7858.0,
                    "ending_status": "unverified_story_wrap",
                },
                "event_ids": [],
                "selection_reason": "ending_story_wrap_score",
                "render_eligibility": "candidate_only",
                "blocking_reasons": [],
                "narrative_order": 2,
                "evidence_refs": [],
            },
        ]
    }
    rows = select_delivery_rows(plan, glitch_ranges=[])
    roles = [r["role"] for r in rows]
    assert "ending" not in roles
    assert "ending_story_wrap_score" in roles
