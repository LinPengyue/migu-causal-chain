"""Phase 5.1 unit tests: glitch+goal integrity, story graph structure."""

from __future__ import annotations

from story_video_agent.phase5_delivery import (
    apply_glitch_avoidance,
    build_story_graph,
    select_delivery_rows,
    validate_story_graph,
)


def test_glitch_avoidance_keeps_goal_anchor_after_glitch():
    # Croatia-like: glitch just before ball-in-net; must not crop to attack-only
    a, b, notes, fail = apply_glitch_avoidance(
        6305.199,
        6327.199,
        [(6315.8, 6316.7, "neon")],
        must_cover=6317.199,
    )
    assert fail is None, (fail, notes, a, b)
    assert a >= 6316.7 - 1e-6
    assert a < 6317.199 < b
    assert b - 6317.199 >= 2.5 - 1e-6


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
                "segment_id": "seg_ending_final_scoreboard",
                "beat": "收尾",
                "role": "ending_final_scoreboard",
                "shot_kind": "scoreboard_anchor",
                "media_in": 7857.0,
                "media_out": 7862.0,
                "time_status": "score_path_only",
                "time_provenance": {"t_sec": 7858.0},
                "event_ids": [],
                "selection_reason": "ending_final_scoreboard_preferred",
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
    assert "ending_final_scoreboard" in roles
