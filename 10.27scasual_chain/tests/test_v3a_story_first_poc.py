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
    build_shared_story_first_provider, main,
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


def _set_shared_gateway_env(monkeypatch):
    # Existing V4 Pro / Qwen VL provider convention; never use new secrets.
    monkeypatch.setenv("STORY_LLM_BASE_URL", "https://provider.example.test/v1")
    monkeypatch.setenv("STORY_LLM_API_KEY", "unit-test-shared-credential")
    monkeypatch.setenv("STORY_LLM_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("STORY_FIRST_LLM_MODEL", "DeepSeek-V4.1-Flash")
    monkeypatch.setenv("STORY_API_ENABLE", "0")
    monkeypatch.delenv("STORY_API_MAX_COMPLETION_TOKENS", raising=False)
    monkeypatch.delenv("STORY_PLANNER_MAX_COMPLETION_TOKENS", raising=False)
    monkeypatch.delenv("STORY_PLANNER_REQUEST_PROFILE", raising=False)
    monkeypatch.delenv("STORY_PLANNER_TOKEN_PARAM", raising=False)


@pytest.mark.parametrize("disable_style", ["thinking_object", "enable_thinking_false"])
def test_reuses_shared_gateway_and_explicitly_disables_thinking(
    monkeypatch, disable_style
):
    _set_shared_gateway_env(monkeypatch)
    api, preflight = build_shared_story_first_provider(
        max_cost_usd=0.01, max_completion_tokens=1000,
        disable_thinking_style=disable_style,
    )
    assert preflight["model"] == "DeepSeek-V4.1-Flash"
    assert preflight["gateway"] == "existing_story_planner_service"
    assert api.configs["planner"].base_url == "https://provider.example.test/v1"
    assert api.configs["planner"].api_key == "unit-test-shared-credential"
    assert api.configs["planner"].model != "deepseek-v4-pro"
    assert api.stats.summary()["http_attempts"] == 0
    assert "unit-test-shared-credential" not in json.dumps(preflight)
    cfg = api.configs["planner"]
    body, _ = api.build_chat_request_body(
        cfg, messages=[{"role": "user", "content": "test"}], temperature=0.0
    )
    if disable_style == "thinking_object":
        assert body["thinking"] == {"type": "disabled"}
        assert "enable_thinking" not in body
    else:
        assert body["enable_thinking"] is False
        assert "thinking" not in body
    assert "thinking_budget" not in body
    assert body["model"] == "DeepSeek-V4.1-Flash"
    assert body["stream"] is False


def test_provider_model_id_not_guessed_or_falls_back_to_v4_pro(monkeypatch):
    _set_shared_gateway_env(monkeypatch)
    monkeypatch.delenv("STORY_FIRST_LLM_MODEL")
    with pytest.raises(ValueError, match="STORY_FIRST_LLM_MODEL_required"):
        build_shared_story_first_provider(max_cost_usd=0.01, max_completion_tokens=1000)
    monkeypatch.setenv("STORY_FIRST_LLM_MODEL", "deepseek-v4-pro")
    with pytest.raises(ValueError, match="expected_deepseek_flash"):
        build_shared_story_first_provider(max_cost_usd=0.01, max_completion_tokens=1000)


def test_shared_gateway_nonthinking_config_check_does_zero_http(
    monkeypatch, tmp_path
):
    _set_shared_gateway_env(monkeypatch)
    edl, events = fixtures()
    edl_file, ev_file = tmp_path/"edl.json", tmp_path/"events.json"
    edl_file.write_text(json.dumps(edl))
    ev_file.write_text(json.dumps(events))
    out = tmp_path/"preflight_only"
    result = main([
        "--edl", str(edl_file), "--events", str(ev_file),
        "--out-dir", str(out), "--check-provider-config-only",
    ])
    assert result == 0
    audit = json.loads((out/"hypothesis_generation_audit.json").read_text())
    assert audit["http_attempts"] == 0
    assert audit["status"] == "SHARED_GATEWAY_PREFLIGHT_ONLY_ZERO_HTTP"
    assert audit["api_preflight"]["model"] == "DeepSeek-V4.1-Flash"
    assert audit["api_preflight"]["request_thinking"] == {"type": "disabled"}



def test_complete_compact_inventory_even_when_rich_detail_cap_is_low():
    edl, _ = fixtures()
    events = [event("standard-%03d" % i, 118 + 8*i, "shot")
              for i in range(80)]
    events.append(event("rare-foul", 750, "foul"))
    p = prepare_story_input(edl, events, max_events=12)
    assert p["counts"]["distinct_events_inside_scope"] == 81
    assert p["counts"]["events_in_full_inventory"] == 81
    assert p["counts"]["events_in_llm_context"] == 12
    assert p["counts"]["events_not_in_rich_detail_context"] == 69
    assert p["counts"]["events_omitted_entirely_from_prompt"] == 0
    assert "rare-foul" in {e["event_id"] for e in p["events"]}
    inventory_ids = {e["event_id"] for e in p["event_inventory"]}
    assert inventory_ids == {e["event_id"] for e in events}
    assert {x["event_id"] for x in p["events"]}.issubset(inventory_ids)
    assert len(p["probes"]) >= 81
    msgs = model_messages(p, 3)
    assert "rare-foul" in msgs[1]["content"]
    assert '"full_event_inventory"' in msgs[1]["content"]
    assert '"rich_detail_events"' in msgs[1]["content"]


def test_hypothesis_can_cite_real_compact_only_event_but_not_fabricated():
    edl, _ = fixtures()
    events = [event("id-%d" % i, 120 + 10*i, "shot") for i in range(45)]
    p = prepare_story_input(edl, events, max_events=6)
    detailed = {e["event_id"] for e in p["events"]}
    compact_only = next(
        e["event_id"] for e in p["event_inventory"]
        if e["event_id"] not in detailed
    )
    obj = model_result(
        event_id=compact_only, probe_id="event:" + compact_only
    )
    obj["hypotheses"][0]["proposed_long_range_relations"][0][
        "target_event_id"
    ] = "id-15"
    res = parse_hypotheses(obj, p)
    assert res["status"] == "UNVERIFIED_HYPOTHESES"
    assert res["hypotheses"][0]["supporting_event_ids"] == [compact_only]
    plan = build_observation_plan(p, res)
    assert plan["targets"][0]["probe_id"] == "event:" + compact_only
    assert plan["targets"][0]["video_caption_status"] == "NOT_OBSERVED"


def test_gap_probes_use_full_event_series_not_sample_artifacts():
    edl, _ = fixtures()
    # Every 10 sec there is a true annotation; a rich cap of 3 must
    # NOT manufacture 120-second source gaps among sampled events.
    events = [event("e-%03d" % i, 120 + 10*i) for i in range(72)]
    p = prepare_story_input(
        edl, events, max_events=3, gap_threshold_sec=120
    )
    assert p["counts"]["events_in_llm_context"] == 3
    assert p["counts"]["gap_probes"] == 0


def test_explicit_replays_not_promoted_to_observation_candidates():
    edl, _ = fixtures()
    events = [
        event("replay-1", 180, "goal", "REPLAY"),
        event("live-1", 190, "foul", "LIVE"),
    ]
    p = prepare_story_input(edl, events)
    assert {e["event_id"] for e in p["event_inventory"]} == {
        "replay-1", "live-1"
    }
    ids = {x["probe_id"] for x in p["probes"]}
    assert "event:replay-1" not in ids
    assert "event:live-1" in ids



def test_paid_mode_blocks_unmeasured_input_token_budget(tmp_path, monkeypatch):
    edl, events = fixtures()
    edl_path, events_path = tmp_path/"edl.json", tmp_path/"events.json"
    edl_path.write_text(json.dumps(edl))
    events_path.write_text(json.dumps(events))
    monkeypatch.setenv("STORY_API_ENABLE", "1")
    # Must refuse BEFORE opening any output directory or loading a key.
    base = ["--edl", str(edl_path), "--events", str(events_path),
            "--out-dir", str(tmp_path/"paid"), "--enable-real-api",
            "--i-approve-budget", "--max-completion-tokens", "3200"]
    assert main(base) == 2
    assert main(base + ["--verified-context-window-tokens", "8192",
                        "--measured-input-tokens", "6000"]) == 2
    assert not (tmp_path/"paid").exists()



def test_paid_length_response_saved_before_rejection(tmp_path, monkeypatch):
    import story_video_agent_v3.story_first_poc_cli as cli

    edl, events = fixtures()
    edl_file, ev_file = tmp_path/"edl.json", tmp_path/"events.json"
    edl_file.write_text(json.dumps(edl))
    ev_file.write_text(json.dumps(events))
    monkeypatch.setenv("STORY_API_ENABLE", "1")
    monkeypatch.setenv("STORY_FIRST_LLM_MODEL", "DeepSeek-V4.1-Flash")
    partial = '{"hypotheses":[{"hypothesis_id":"H1"'
    class FakeStats:
        def summary(self):
            return {"http_attempts": 1, "prompt_tokens": 500,
                    "completion_tokens": 3200, "est_cost_usd_real": 0.01}
    class FakeApi:
        stats = FakeStats()
        def chat(self, **kwargs):
            return {
                "provider_mode": "real", "model": "DeepSeek-V4.1-Flash",
                "finish_reason": "length", "content": partial,
                "usage": {"prompt_tokens": 500, "completion_tokens": 3200},
                "response_audit": {"reasoning_tokens": 0},
            }
    monkeypatch.setattr(cli, "build_shared_story_first_provider",
                        lambda **kwargs: (FakeApi(), {"gateway_configured": True}))
    out = tmp_path/"failed"
    assert cli.main([
        "--edl", str(edl_file), "--events", str(ev_file),
        "--out-dir", str(out), "--enable-real-api", "--i-approve-budget",
        "--verified-context-window-tokens", "1000000",
        "--measured-input-tokens", "500",
    ]) == 3
    assert (out/"llm_raw_response.txt").read_text() == partial
    audit = json.loads((out/"hypothesis_generation_audit.json").read_text())
    assert audit["status"] == "FAILED_NO_PROMOTION"
    assert audit["finish_reason"] == "length"
    assert audit["raw_response_saved"] is True
    assert audit["hypotheses_promoted"] is False
    assert not (out/"story_hypotheses.json").exists()
    assert not (out/"observation_plan.json").exists()



def test_compact_stage_one_prompt_and_minimal_hypothesis_fixture():
    p = prepare_story_input(*fixtures())
    messages = model_messages(p, max_hypotheses=2)
    assert "STAGE 1 ONLY" in messages[0]["content"]
    assert "EXACTLY one object" in messages[0]["content"]
    assert "full_event_inventory" in messages[1]["content"]
    assert "rich_detail_events" in messages[1]["content"]
    assert json.loads(messages[1]["content"])["K"] == 2

    # Stage one must not need the old wordy optional fields.
    compact = model_result()
    hyp = compact["hypotheses"][0]
    del hyp["possible_intermediate_states"]
    del hyp["uncertain_claims"]
    del hyp["expected_story_contribution"]
    hyp["supporting_event_ids"] = ["foul-1", "shot-1"]
    parsed = parse_hypotheses(compact, p, max_hypotheses=2)
    assert parsed["status"] == "UNVERIFIED_HYPOTHESES"
    assert parsed["hypotheses"][0]["possible_intermediate_states"] == []
    assert parsed["hypotheses"][0]["uncertain_claims"] == []
    assert parsed["hypotheses"][0]["expected_story_contribution"] == ""
    obs = build_observation_plan(p, parsed)
    assert len(obs["targets"]) == 1
    assert obs["first_live_certified"] is False
    assert obs["edl_modified"] is False
    assert obs["targets"][0]["automatic_edl_insert"] is False


@pytest.mark.parametrize("missing_key", [
    "proposed_long_range_relations", "observation_queries",
    "falsification_conditions", "narrative_summary",
])
def test_compact_stage_one_requires_nonempty_mechanism_and_test(missing_key):
    p = prepare_story_input(*fixtures())
    hyp = model_result()["hypotheses"][0]
    hyp[missing_key] = [] if missing_key != "narrative_summary" else ""
    parsed = parse_hypotheses({"hypotheses": [hyp]}, p)
    assert not parsed["hypotheses"]
    assert parsed["rejected"][0]["reason"] == "missing_evidence_or_test"
