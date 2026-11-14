"""v2 Story-First offline contract tests. Never make HTTP or load video."""
from __future__ import annotations

import json

import pytest

from story_video_agent_v3.story_first_hypotheses import (
    baseline_candidates, build_observation_plan, evidence_matrix,
    model_messages, parse_hypotheses, prepare_story_input,
    select_story_interval,
)
from story_video_agent_v3.story_first_poc_cli import (
    build_deepseek_provider, main,
)


def row(segment_id, role, a, b):
    return {"segment_id": segment_id, "role": role, "media_in": a,
            "media_out": b, "include_in_cut": True}


def event(eid, t, typ="shot", phase="LIVE"):
    return {
        "event_id": eid, "event_type": typ,
        "media_time": {
            "start_time_sec": t - 3, "event_time_sec": t,
            "end_time_sec": t + 3,
        },
        "video_context": {"broadcast_phase": phase},
    }


def fixtures(offset=0):
    edl = [
        row("first", "opponent_opening_goal_action", 100+offset, 112+offset),
        row("build", "buildup_action", 330+offset, 342+offset),
        row("equal", "equalizer_goal_action", 850+offset, 868+offset),
        row("later", "go_ahead_goal_action", 1200+offset, 1212+offset),
    ]
    events = [
        event("foul-1", 150+offset, "foul"),
        event("sub-1", 365+offset, "substitution"),
        event("lost-1", 640+offset, "turnover"),
        event("shot-1", 800+offset, "shot"),
        event("outside", 1900+offset, "shot"),
    ]
    return edl, events


def model_result(event_id="foul-1", probe_id="event:foul-1"):
    return {
        "hypotheses": [{
            "hypothesis_id": "H1", "mechanism_key": "gradual_pressure",
            "narrative_summary": "可能出现逐步加强的进攻，但尚未验证",
            "supporting_event_ids": [event_id],
            "proposed_long_range_relations": [{
                "source_event_id": event_id, "target_event_id": "shot-1",
                "relation_type": "causal_hypothesis", "claim": "可能具有长程联系",
            }],
            "possible_intermediate_states": ["攻防态势可能变化"],
            "uncertain_claims": ["是否真的加强了攻势"],
            "falsification_conditions": ["验证换人前后进攻密度无变化"],
            "observation_queries": [{
                "target_id": probe_id,
                "question": "有没有可观察的进攻组织变化？",
                "discriminating_signal": "反复出现在进攻三区",
            }],
            "expected_story_contribution": "可能作为故事铺垫",
        }],
        "insufficient_evidence_reason": "",
    }


def test_full_interval_not_180_seconds():
    edl, events = fixtures()
    prepared = prepare_story_input(edl, events)
    assert prepared["scope"]["source_interval_sec"] == [112.0, 850.0]
    assert {e["event_id"] for e in prepared["events"]} == {
        "foul-1", "sub-1", "lost-1", "shot-1"
    }
    assert prepared["counts"]["supplied_event_rows"] == 5
    assert prepared["data_tier"] == "HUMAN_ATOM_ENRICHED_DEV"
    assert all(p["first_live_status"] == "UNRESOLVED" for p in prepared["probes"])
    assert prepared["verified_long_range_causal_links"] == 0
    assert "event:foul-1" in {p["probe_id"] for p in prepared["probes"]}
    assert any(p["probe_id"].startswith("gap:") for p in prepared["probes"])


def test_other_match_time_axis_same_behavior():
    edl, events = fixtures(5000)
    prepared = prepare_story_input(edl, events)
    assert prepared["scope"]["source_interval_sec"] == [5112.0, 5850.0]
    assert prepared["counts"]["distinct_events_inside_scope"] == 4


def test_explicit_non_goal_anchor_story_template():
    edl = [row("pressure", "pressure_shift", 1000, 1010),
           row("closing", "ending", 1280, 1300)]
    obj = select_story_interval(
        edl, from_segment_id="pressure", to_segment_id="closing"
    )
    assert obj["source_interval_sec"] == [1010.0, 1280.0]


def test_model_hypothesis_binds_events_and_planning_without_video():
    edl, events = fixtures()
    p = prepare_story_input(edl, events)
    valid = parse_hypotheses(model_result(), p)
    assert valid["status"] == "UNVERIFIED_HYPOTHESES"
    assert len(valid["hypotheses"]) == 1
    h = valid["hypotheses"][0]
    assert h["causal_claim_validated"] is False
    assert h["eligible_for_edl"] is False
    assert h["proposed_long_range_relations"][0]["evidence_status"] == (
        "UNVERIFIED_MODEL_HYPOTHESIS"
    )
    matrix = evidence_matrix(p, valid)
    assert matrix["video_evidence_inspected"] is False
    observation = build_observation_plan(p, valid)
    assert len(observation["targets"]) == 1
    assert observation["targets"][0]["source_interval_sec"] == [142.0, 158.0]
    assert observation["targets"][0]["automatic_edl_insert"] is False


def test_model_invented_ids_or_timestamp_refused():
    p = prepare_story_input(*fixtures())
    fabricated = model_result(event_id="hallucinated")
    result = parse_hypotheses(fabricated, p)
    assert result["hypotheses"] == []
    assert result["rejected"][0]["reason"] == "unrecognized_event_id"
    fabricated = model_result()
    fabricated["hypotheses"][0]["observation_queries"][0]["source_pts_start"] = 150
    result = parse_hypotheses(fabricated, p)
    assert result["rejected"][0]["reason"] == "invalid_observation_probe"


def test_duplicate_mechanism_refused():
    p = prepare_story_input(*fixtures())
    obj = model_result()
    second = dict(obj["hypotheses"][0])
    second["hypothesis_id"] = "H2"
    obj["hypotheses"].append(second)
    result = parse_hypotheses(obj, p)
    assert len(result["hypotheses"]) == 1
    assert result["rejected"][0]["reason"] == "empty_or_duplicate_identity"


def test_empty_hypothesis_is_valid_not_forced():
    p = prepare_story_input(*fixtures())
    result = parse_hypotheses({
        "hypotheses": [], "insufficient_evidence_reason": "insufficient detail"
    }, p)
    assert result["status"] == "NO_VALID_HYPOTHESES"
    assert build_observation_plan(p, result)["targets"] == []


def test_same_story_has_event_only_baselines():
    p = prepare_story_input(*fixtures())
    base = baseline_candidates(p)
    assert base["chronological_event_ids"][0] == "foul-1"
    assert set(base["importance_ranked_event_ids"]) == set(base["chronological_event_ids"])
    assert len(model_messages(p, 3)) == 2


def test_cli_offline_zero_http_even_if_story_api_env_on(tmp_path, monkeypatch):
    edl, events = fixtures()
    edl_path, events_path = tmp_path/"edl.json", tmp_path/"events.json"
    edl_path.write_text(json.dumps(edl), encoding="utf-8")
    events_path.write_text(json.dumps(events), encoding="utf-8")
    monkeypatch.setenv("STORY_API_ENABLE", "1")
    out = tmp_path/"out"
    assert main(["--edl", str(edl_path), "--events", str(events_path),
                 "--out-dir", str(out)]) == 0
    audit = json.loads((out/"hypothesis_generation_audit.json").read_text())
    assert audit["http_attempts"] == 0
    assert audit["status"] == "PREPARED_ONLY_ZERO_HTTP"
    assert json.loads((out/"story_hypotheses.json").read_text())["hypotheses"] == []


def test_cli_real_request_requires_consent(tmp_path, monkeypatch):
    edl, events = fixtures()
    e, v = tmp_path/"e.json", tmp_path/"v.json"
    e.write_text(json.dumps(edl))
    v.write_text(json.dumps(events))
    monkeypatch.setenv("STORY_API_ENABLE", "0")
    assert main(["--edl", str(e), "--events", str(v),
                 "--out-dir", str(tmp_path/"result"),
                 "--enable-real-api"]) == 2
    assert not (tmp_path/"result").exists()


def test_fixture_only_does_not_claim_real_llm(tmp_path):
    edl, events = fixtures()
    e, v, f = tmp_path/"e.json", tmp_path/"v.json", tmp_path/"fixture.json"
    e.write_text(json.dumps(edl))
    v.write_text(json.dumps(events))
    f.write_text(json.dumps(model_result(), ensure_ascii=False))
    out = tmp_path/"out"
    assert main(["--edl", str(e), "--events", str(v),
                 "--fixture-model-json", str(f), "--out-dir", str(out)]) == 0
    audit = json.loads((out/"hypothesis_generation_audit.json").read_text())
    assert audit["source_mode"] == "OFFLINE_FIXTURE_NOT_REAL_MODEL_RESULT"
    assert audit["http_attempts"] == 0
    assert len(json.loads((out/"observation_plan.json").read_text())["targets"]) == 1


def test_non_thinking_deepseek_request_preflight_has_no_http(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-dummy-key")
    monkeypatch.setenv("STORY_API_ENABLE", "0")
    api, preflight = build_deepseek_provider(
        max_cost_usd=0.01, max_completion_tokens=1000
    )
    assert preflight["model"] == "deepseek-flash"
    assert preflight["request_thinking"] == {"type": "disabled"}
    assert preflight["http_attempt_cap"] == 1
    assert api.stats.summary()["http_attempts"] == 0
