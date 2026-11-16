"""Zero-paid contract tests for Scheme A whole-story LLM ranking.

These tests verify structural safety and candidate ranking only, not whether
a generated football story is factual or improves the edited video.
"""
from __future__ import annotations

import json

import pytest

from story_video_agent_v3.story_first_a_ranker import (
    build_score_messages, main, rank_model_evaluations,
)
from story_video_agent_v3.story_first_hypotheses import (
    build_observation_plan, parse_hypotheses, prepare_story_input,
)
from story_video_agent_v3.story_first_evidence_adapter import (
    read_story_first_observation_branch,
)


def _fixture():
    edl = [
        {"segment_id": "behind", "role": "opening_goal_action",
         "media_in": 100, "media_out": 110, "include_in_cut": True},
        {"segment_id": "pressure", "role": "pressure_shift",
         "media_in": 600, "media_out": 615, "include_in_cut": True},
    ]
    events = [
        {"event_id": eid, "event_type": label,
         "media_time": {"start_time_sec": t-2,
                        "event_time_sec": t, "end_time_sec": t+2},
         "video_context": {"broadcast_phase": "LIVE"}}
        for eid, label, t in (
            ("a", "substitution", 150),
            ("b", "foul", 220),
            ("c", "interception", 315),
            ("d", "shot", 420),
        )
    ]
    prepared = prepare_story_input(
        edl, events, story_plan={"plot": "behind_to_pressure"},
        from_segment_id="behind", to_segment_id="pressure",
    )
    def h(hid, mechanism, e1, e2):
        return {
            "hypothesis_id": hid, "mechanism_key": mechanism,
            "narrative_summary": "尚未验证的事件组合：" + hid,
            "supporting_event_ids": [e1, e2],
            "proposed_long_range_relations": [{
                "source_event_id": e1, "target_event_id": e2,
                "relation_type": "causal_hypothesis",
                "claim": "可能相关，但暂无视频证据",
            }],
            "falsification_conditions": ["视频不存在对应过程"],
            "observation_queries": [{
                "target_id": "event:" + e2,
                "question": "是否形成连续情节？",
                "discriminating_signal": "原视频证据",
            }],
        }
    validated = parse_hypotheses({
        "hypotheses": [h("H1", "substitution", "a", "b"),
                       h("H2", "pressure", "c", "d")],
        "insufficient_evidence_reason": "",
    }, prepared)
    assert len(validated["hypotheses"]) == 2
    return prepared, validated


def _score(hid, ids, gain):
    return {
        "hypothesis_id": hid,
        "internal_causal_link": 3, "anchor_causal_bridge": 3,
        "joint_causal_gain": gain, "factual_support": 3,
        "cited_event_ids": ids,
        "causal_mechanism": "可能构成多事件因果关联，但未验证",
        "major_uncertainty": "缺少原视频连续过程证据",
    }


def test_whole_story_rank_and_no_edl_promotion():
    prepared, valid = _fixture()
    data = {"evaluations": [_score("H1", ["a", "b"], 1),
                            _score("H2", ["c", "d"], 4)]}
    ranked = rank_model_evaluations(data, valid, top_k=1)
    assert ranked["selected_for_video_observation"] == ["H2"]
    assert ranked["ranked_hypotheses"][0]["hypothesis_id"] == "H2"
    assert ranked["ranked_hypotheses"][0]["model_priority_0_to_1"] > (
        ranked["ranked_hypotheses"][1]["model_priority_0_to_1"])
    assert ranked["planner_candidates"] == []
    assert ranked["causal_claims_verified"] == 0
    assert ranked["first_live_certified"] is False
    assert ranked["edl_modified"] is False
    assert "existing-V3R" not in build_score_messages(prepared, valid)[0]["content"]


def test_score_request_uses_active_edl_full_plan_and_compact_event_notes():
    plan = {"plot": "behind_to_pressure", "details": "长" * 10000, "tail": "retained"}
    edl = [
        {"segment_id": "title", "role": "title_card", "placeholder_lines": ["Comeback"]},
        {"segment_id": "before", "role": "goal_action", "media_in": 100, "media_out": 110},
        {"segment_id": "already_shown", "role": "buildup", "media_in": 140, "media_out": 170,
         "event_ids": ["a"], "narration": "已经呈现的换人"},
        {"segment_id": "excluded", "include_in_cut": False},
        {"segment_id": "after", "role": "goal_action", "media_in": 600, "media_out": 615},
    ]
    events = [
        {"event_id": "a", "pts_sec": 150, "event_type": "substitution",
         "notes": "2队9号换下2队7号"},
        {"event_id": "b", "pts_sec": 220, "event_type": "foul",
         "description": "对抗后犯规"},
    ]
    prepared = prepare_story_input(edl, events, story_plan=plan, max_events=1)
    assert [e["event_id"] for e in prepared["events"]] == ["b"]
    _, both = _fixture()
    validated = parse_hypotheses({"hypotheses": both["hypotheses"][:1]}, prepared)
    request = json.loads(build_score_messages(prepared, validated)[1]["content"])
    assert request["frozen_story_plan"] == plan
    assert request["current_edl"] == [edl[i] for i in (0, 1, 2, 4)]
    assert request["current_edl"][2]["event_ids"] == ["a"]
    assert request["event_context"][0]["annotation_notes"] == events[0]["notes"]
    assert request["event_context"][0]["description"] is None
    assert request["event_context"][1]["description"] == events[1]["description"]


@pytest.mark.parametrize("change", ["hallucinated_id", "bool_score",
                                    "missing_candidate", "invalid_reason"])
def test_score_fails_closed(change):
    _, valid = _fixture()
    rows = [_score("H1", ["a", "b"], 2),
            _score("H2", ["c", "d"], 3)]
    if change == "hallucinated_id":
        rows[0]["cited_event_ids"] = ["a", "invented"]
    elif change == "bool_score":
        rows[0]["joint_causal_gain"] = True
    elif change == "missing_candidate":
        rows = rows[:1]
    else:
        rows[1]["major_uncertainty"] = ""
    with pytest.raises(ValueError):
        rank_model_evaluations({"evaluations": rows}, valid)


def test_no_candidates_zero_scoring():
    _, valid = _fixture()
    empty = {**valid, "hypotheses": []}
    out = rank_model_evaluations({"evaluations": []}, empty)
    assert out["status"] == "NO_CANDIDATES"
    assert out["selected_for_video_observation"] == []


def test_cli_fixture_ranks_without_http(tmp_path, monkeypatch):
    prepared, valid = _fixture()
    p = tmp_path / "prepared.json"
    h = tmp_path / "hypotheses.json"
    f = tmp_path / "score.json"
    p.write_text(json.dumps(prepared), encoding="utf-8")
    h.write_text(json.dumps(valid), encoding="utf-8")
    f.write_text(json.dumps({
        "evaluations": [_score("H1", ["a", "b"], 1),
                        _score("H2", ["c", "d"], 4)]}), encoding="utf-8")
    monkeypatch.setenv("STORY_API_ENABLE", "1")
    out = tmp_path / "ranking"
    assert main(["--prepared-story-input", str(p),
                 "--story-hypotheses", str(h),
                 "--fixture-score-json", str(f),
                 "--out-dir", str(out), "--top-k", "1"]) == 0
    audit = json.loads((out / "scheme_a_audit.json").read_text())
    result = json.loads((out / "scheme_a_story_ranking.json").read_text())
    assert audit["http_attempts"] == 0
    assert audit["status"] == "OFFLINE_FIXTURE_NOT_REAL_LLM"
    assert result["selected_for_video_observation"] == ["H2"]
    assert result["planner_candidates"] == []


def test_cli_real_mode_requires_explicit_budget(tmp_path):
    prepared, valid = _fixture()
    p = tmp_path / "prepared.json"
    h = tmp_path / "hypotheses.json"
    p.write_text(json.dumps(prepared), encoding="utf-8")
    h.write_text(json.dumps(valid), encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--prepared-story-input", str(p),
              "--story-hypotheses", str(h),
              "--out-dir", str(tmp_path / "paid"),
              "--enable-real-api"])
    assert not (tmp_path / "paid").exists()


def test_legacy_artifacts_can_be_inspected_but_cannot_start_paid_scoring(
        tmp_path, monkeypatch):
    prepared, valid = _fixture()
    prepared.pop("frozen_story_plan")
    prepared.pop("current_edl")
    p = tmp_path / "prepared.json"
    h = tmp_path / "hypotheses.json"
    p.write_text(json.dumps(prepared), encoding="utf-8")
    h.write_text(json.dumps(valid), encoding="utf-8")
    monkeypatch.setenv("STORY_API_ENABLE", "1")

    def network_disallowed(**kwargs):
        pytest.fail("provider must not be built for a legacy prepared file")

    monkeypatch.setattr(
        "story_video_agent_v3.story_first_a_ranker.build_shared_story_first_provider",
        network_disallowed,
    )
    command = ["--prepared-story-input", str(p), "--story-hypotheses", str(h)]
    dry = tmp_path / "dry"
    assert main(command + ["--out-dir", str(dry)]) == 0
    dry_audit = json.loads((dry / "scheme_a_audit.json").read_text())
    assert dry_audit["scoring_context_complete"] is False
    paid = tmp_path / "paid"
    assert main(command + [
        "--out-dir", str(paid), "--enable-real-api", "--i-approve-budget",
        "--measured-input-tokens", "10000", "--verified-context-window-tokens", "20000",
    ]) == 3
    audit = json.loads((paid / "scheme_a_audit.json").read_text())
    assert audit["status"] == "FAILED_NO_PROMOTION"
    assert audit["http_attempts"] == 0
    assert "reprepare_stage1_from_original_story_plan_and_edl" in audit["error"]


def test_scheme_a_ranking_integrates_to_observation_queue_only(tmp_path):
    prepared, valid = _fixture()
    poc = tmp_path / "stage1"
    poc.mkdir()
    ranking_dir = poc / "scheme_a_ranking"
    output = rank_model_evaluations({
        "evaluations": [_score("H1", ["a", "b"], 1),
                        _score("H2", ["c", "d"], 4)],
    }, valid, top_k=1)
    docs = {
        "prepared_story_input.json": prepared,
        "story_hypotheses.json": valid,
        "observation_plan.json": build_observation_plan(prepared, valid),
    }
    for filename, doc in docs.items():
        (poc / filename).write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    edl = [
        {"segment_id": "behind", "role": "opening_goal_action",
         "media_in": 100, "media_out": 110, "include_in_cut": True},
        {"segment_id": "pressure", "role": "pressure_shift",
         "media_in": 600, "media_out": 615, "include_in_cut": True},
    ]
    events = [
        {"event_id": e["event_id"], "event_type": e["event_type"],
         "media_time": {
             "start_time_sec": e["media_span_sec"][0],
             "event_time_sec": e["source_pts_sec"],
             "end_time_sec": e["media_span_sec"][1],
         }, "video_context": {
             "broadcast_phase": e["broadcast_phase_metadata"]}}
        for e in prepared["events"]
    ]
    def run():
        return read_story_first_observation_branch(
            artifacts_dir=poc,
            current_edl=edl,
            current_story_plan={"plot": "behind_to_pressure"},
            permitted_events=events,
            current_source_sha256="a" * 64,
        )
    assert main(["--prepared-story-input", str(poc / "prepared_story_input.json"),
                 "--story-hypotheses", str(poc / "story_hypotheses.json"),
                 "--out-dir", str(ranking_dir)]) == 0
    awaiting = run()
    assert awaiting["status"] == "OBSERVATION_QUEUE_ONLY"
    assert awaiting["scheme_a_ranking_status"] == "PREPARED_ONLY_ZERO_HTTP"
    assert awaiting["scheme_a_selected_for_observation"] == []
    assert awaiting["observation_targets"][0]["hypothesis_id"] == "H1"
    (ranking_dir / "scheme_a_story_ranking.json").write_text(
        json.dumps(output, ensure_ascii=False), encoding="utf-8")
    (ranking_dir / "scheme_a_audit.json").write_text(
        json.dumps({"status": "OFFLINE_FIXTURE_NOT_REAL_LLM"}),
        encoding="utf-8")
    result = run()
    assert result["status"] == "OBSERVATION_QUEUE_ONLY"
    assert result["scheme_a_selected_for_observation"] == ["H2"]
    assert result["scheme_a_ranking"] == output["ranked_hypotheses"]
    assert result["observation_targets"][0]["hypothesis_id"] == "H2"
    assert result["planner_candidates"] == []
    assert result["first_live_certified"] is False
    edl.insert(1, {"segment_id": "new_buildup", "role": "buildup",
                   "media_in": 215, "media_out": 225})
    stale = run()
    assert stale["status"] == "REJECTED_NO_PROMOTION"
    assert "current_edl_changed_since_scheme_a_input" in stale["reason"]
    assert stale["observation_targets"] == []
    edl.pop(1)
    # A changed score file cannot silently change the search queue.
    changed = dict(output)
    changed["ranked_hypotheses"] = [
        dict(x) for x in output["ranked_hypotheses"]]
    changed["ranked_hypotheses"][0]["model_priority_0_to_1"] = 1.0
    (ranking_dir / "scheme_a_story_ranking.json").write_text(
        json.dumps(changed), encoding="utf-8")
    rejected = run()
    assert rejected["status"] == "REJECTED_NO_PROMOTION"
    assert "scheme_a_ranking_not_reproducible" in rejected["reason"]
    assert rejected["observation_targets"] == []
    assert rejected["hypotheses"] == []

    legacy_schema = "v2_story_first_scheme_a_whole_story_prior_v1"
    (ranking_dir / "scheme_a_story_ranking.json").write_text(
        json.dumps({**output, "schema": legacy_schema}), encoding="utf-8")
    (ranking_dir / "scheme_a_audit.json").write_text(
        json.dumps({"schema": legacy_schema,
                    "status": "OFFLINE_FIXTURE_NOT_REAL_LLM"}),
        encoding="utf-8")
    legacy = run()
    assert legacy["status"] == "OBSERVATION_QUEUE_ONLY"
    assert legacy["scheme_a_ranking_status"] == "LEGACY_RANKING_IGNORED"
    assert legacy["scheme_a_selected_for_observation"] == []
    assert legacy["observation_targets"] == awaiting["observation_targets"]
    (poc / "prepared_story_input.json").write_text(json.dumps(prepared) + "\n")
    assert "scheme_a_source_artifacts_changed" in run()["reason"]
