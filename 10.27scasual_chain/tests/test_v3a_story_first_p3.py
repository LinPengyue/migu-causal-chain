import json
from pathlib import Path

import pytest

from story_video_agent_v3 import story_first_p3 as p3
from story_video_agent_v3.story_timeline import build_story_timeline


BASE = [
    {"segment_id": "left", "role": "buildup_action", "media_in": 10, "media_out": 20},
    {"segment_id": "right", "role": "equalizer_goal_action", "media_in": 50, "media_out": 62},
]
TRIAL = [BASE[0], {
    "segment_id": "trial", "role": "buildup_bridge_action", "media_in": 25, "media_out": 43,
}, BASE[1]]
REVIEW = {"status": "READY_FOR_TRIAL", "intents": [{
    "action": "search_add", "story_first_trial_id": "accepted_p2", "new_segment_id": "trial",
    "role": "buildup_bridge_action", "bound_source_window": {"start": 25, "end": 43},
    "insert_after_segment_id": "left", "before_segment_id": "right",
}]}


class ScriptedAPI:
    max_cost_usd = 0.05

    def __init__(self, *responses, max_calls=4):
        self._http_attempts = 0
        self.max_calls = max_calls
        self.responses = iter(responses)
        self.roles = []

    def chat(self, **req):
        assert req["allow_degraded_fallback"] is False
        self._http_attempts += 1
        self.roles.append(req["stats_role"])
        data, finish = next(self.responses)
        return {"provider_mode": "real", "finish_reason": finish, "content": json.dumps(data)}


@pytest.fixture
def case(tmp_path, monkeypatch):
    def alignment(*, edl, mp4):
        timeline = build_story_timeline(edl)
        return {"aligned": Path(mp4).is_file(), "timeline": timeline,
                "mp4_duration_sec": timeline["story_duration_sec"]}

    def fake_clip(*, source_mp4, begin, end, output):
        output.write_bytes(b"native video fixture")
        return {"ok": True, "path": str(output), "sha256": "clipfixture", "bytes": 20}

    monkeypatch.setattr(p3, "timeline_mp4_aligned", alignment)
    monkeypatch.setattr(p3, "_source_context_video", fake_clip)
    baseline, trial = tmp_path / "base.mp4", tmp_path / "trial.mp4"
    baseline.write_bytes(b"baseline video")
    trial.write_bytes(b"existing P3 trial")
    return dict(
        baseline_edl=BASE, baseline_mp4=baseline, trial_edl=TRIAL, trial_mp4=trial,
        review=REVIEW, proposals=[{"proposal_id": "search-result"}],
        story_plan={"template_id": "comeback"}, out_dir=tmp_path / "p3",
    )


def test_p3_turns_caption_and_history_into_safe_trim_and_rerender(case):
    api = ScriptedAPI(
        ({"observations": [{"phase_id": "1:insert", "clip_id": "part_01", "story_range_sec": [10, 15],
                            "description": "Several players contest the ball."}],
          "hard_veto": True}, "stop"),
        ({"actions": [
            {"action": "TRIM", "segment_id": "right", "source_window_sec": [51, 59]},
            {"action": "TRIM", "segment_id": "trial", "source_window_sec": [28, 39]},
        ]}, "stop"),
        ({"uncertainties": ["Ball unclear just before the join."]}, "stop"),
        ({"actions": [{"action": "KEEP", "rationale": "Retain the shorter preview."}]}, "stop"),
    )

    def render(edl, directory):
        assert edl[0] == BASE[0] and edl[-1] == BASE[1]
        assert (edl[1]["media_in"], edl[1]["media_out"]) == (28, 39)
        directory.mkdir(parents=True)
        path = directory / "shorter_preview.mp4"
        path.write_bytes(b"new preview")
        return path

    result = p3.run_p3_revision(
        **case, api=api, render=render, max_rounds=2,
        prior_feedback=[{"note": "earlier placement attempted"}],
    )
    assert result["http_calls"] == 4
    assert result["completed_edits"] == 1
    assert [r["action"] for r in result["rounds"]] == ["TRIM", "KEEP"]
    assert result["rounds"][0]["rejected_actions"][0]["reason"].startswith("trim_requires")
    assert result["selected_preview_mp4"].endswith("shorter_preview.mp4")
    assert not result["promote_best"] and not result["release_authorized"]
    context = json.loads((case["out_dir"] / "round_01/planner_input.json").read_text())
    assert context["candidate_search_results"] == case["proposals"]
    assert context["prior_feedback"][0]["note"] == "earlier placement attempted"
    assert context["working_cut_caption"]["observations"]
    assert "hard_veto" not in context["working_cut_caption"]
    assert {c["phase"]: c["status"] for c in context["working_cut_caption"]["coverage"]} == {
        "before": "MISSING", "insert": "DESCRIBED", "after": "MISSING",
    }
    assert case["baseline_mp4"].read_bytes() == b"baseline video"


def test_p3_attempts_planning_even_when_caption_is_truncated(case):
    api = ScriptedAPI(
        ({}, "length"), ({"actions": [{"action": "STOP", "rationale": "Keep the base."}]}, "stop"),
    )
    result = p3.run_p3_revision(**case, api=api)
    assert result["stop_reason"] == "PLANNER_STOP"
    assert result["selected_preview_mp4"] == str(case["baseline_mp4"])
    assert api.roles == ["story_first_p3_caption", "story_first_p3_planner"]


def test_p3_no_budget_and_no_repeat_render(case):
    api = ScriptedAPI(max_calls=1)
    result = p3.run_p3_revision(**case, api=api)
    assert result["stop_reason"] == "API_BUDGET" and result["http_calls"] == 0
    with pytest.raises(ValueError, match="fresh_output"):
        p3.run_p3_revision(**case, api=api)


def test_p3_rejects_trial_that_edits_original_goal(case):
    case["trial_edl"] = [*TRIAL[:-1], {**TRIAL[-1], "media_out": 61}]
    with pytest.raises(ValueError, match="preserve_baseline"):
        p3.run_p3_revision(**case)


def test_replacement_requires_existing_source_review_before_rerender(case):
    proposal = {
        "proposal_id": "alternative", "summary": "A different buildup",
        "expected_story_contribution": "Show an earlier action",
        "falsification_conditions": [], "relations": [],
        "scope": {"source_interval_sec": [20, 50]},
        "events": [{"event_id": "e2", "source_pts_sec": 40, "known_replay_or_slowmo": False}],
    }
    case["proposals"] = [proposal]
    selection = {"selections": [{"proposal_id": "alternative", "event_ids": ["e2"]}]}
    api = ScriptedAPI(
        ({}, "stop"), ({"actions": [{"action": "REPLACE", "selection": selection}]}, "stop"),
        ({}, "stop"), ({"actions": [{"action": "KEEP"}]}, "stop"), max_calls=5,
    )

    def review(trial):
        assert trial["proposal_ids"] == ["alternative"]
        assert trial["windows"][0]["source_pts_start"] == 32
        return {"status": "NEEDS_REVISION", "intents": [],
                "feedback": [{"reason": "window_overlaps_replay_or_slowmo_annotation"}]}

    def render(edl, directory):
        pytest.fail("A rehearsal must not render the replay-blocked replacement")

    result = p3.run_p3_revision(
        **case, api=api, render=render, review_replacement=review, max_rounds=2,
    )
    assert result["stop_reason"] == "NO_STRUCTURED_PLANNER_ACTION"  # Response 3 is now a Planner call.
    first = result["rounds"][0]
    assert "window_overlaps_replay" in first["rejected_actions"][0]["reason"]
    assert api.roles == [
        "story_first_p3_caption", "story_first_p3_planner", "story_first_p3_planner",
    ]


def test_resume_records_second_edit_and_after_cut_evidence(case):
    original_bounds = {"trial": (25, 43)}
    first_edl, intents = p3._trim(TRIAL, {
        "segment_id": "trial", "source_window_sec": [28, 39],
    }, original_bounds)
    first_mp4 = case["out_dir"].parent / "first_edit.mp4"
    first_mp4.write_bytes(b"archived P3 edit")
    resume = {"intent": intents[0], "edl": first_edl, "mp4": first_mp4,
              "sha256": p3.sha256_file(first_mp4)}
    api = ScriptedAPI(
        ({"observations": [
            {"phase_id": "1:before", "clip_id": "part_01", "story_range_sec": [5, 10],
             "description": "Referee signals."},
            {"phase_id": "1:insert", "clip_id": "part_01", "story_range_sec": [10, 21],
             "description": "Midfield play."},
            {"phase_id": "1:after", "clip_id": "part_01", "story_range_sec": [21, 26],
             "description": "Next attack starts."},
        ]}, "stop"),
        ({"actions": [
            {"action": "TRIM", "segment_id": "trial", "source_window_sec": [28, 39]},
            {"action": "TRIM", "segment_id": "trial", "source_window_sec": [30, 37]},
        ]}, "stop"),
        ({}, "stop"),
        ({"actions": [
            {"action": "TRIM", "segment_id": "trial", "source_window_sec": [30, 37]},
            {"action": "KEEP"},
        ]}, "stop"),
    )

    def render(edl, directory):
        assert (edl[1]["media_in"], edl[1]["media_out"]) == (30, 37)
        directory.mkdir(parents=True)
        path = directory / "second_edit.mp4"
        path.write_bytes(b"second edit preview")
        return path

    result = p3.run_p3_revision(
        **case, api=api, render=render, max_rounds=2, resume_trim=resume,
    )
    assert [row["completed_edits"] for row in result["edit_count_comparison"]] == [0, 1, 2]
    assert result["completed_edits"] == 2 and result["http_calls"] == 4
    assert result["selected_preview_mp4"].endswith("second_edit.mp4")
    assert all(round_["rejected_actions"][0]["reason"] == "trim_does_not_change_current_cut"
               for round_ in result["rounds"])
    context = json.loads((case["out_dir"] / "round_01/planner_input.json").read_text())
    assert context["editable_trial_segment_ids_and_source_bounds"] == {"trial": [28, 39]}
    assert [c["status"] for c in context["working_cut_caption"]["coverage"]] == ["DESCRIBED"] * 3
