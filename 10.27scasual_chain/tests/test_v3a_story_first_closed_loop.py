"""Story-First discovery, source evidence and actual revision-loop wiring, zero HTTP."""
import hashlib
import json

import pytest

from story_video_agent.api_provider import EndpointConfig

from story_video_agent_v3 import story_e2e_agent as agent
from story_video_agent_v3 import story_first_search as search
from story_video_agent_v3 import story_first_video_review as video
from story_video_agent_v3.continuous_broadcast_phase import (
    LATER_REPLAY_NOT_OBSERVED, PHASE_SCHEMA, STORY_ACTION_PHASES,
)
from story_video_agent_v3.first_live_window_evidence import (
    SCHEMA, TIMELINE_REVIEW_SCHEMA, validate_first_live_evidence_record, window_key,
)
from story_video_agent_v3.story_paid_eval import run_llm_revision_planner


EDL = [
    {"segment_id": "a", "role": "opponent_opening_goal_action", "media_in": 0, "media_out": 10},
    {"segment_id": "unused", "role": "scoreboard"},
    {"segment_id": "b", "role": "equalizer_goal_action", "media_in": 90, "media_out": 100},
    {"segment_id": "c", "role": "go_ahead_goal_action", "media_in": 170, "media_out": 180},
]
EVENTS = [{"event_id": eid, "pts_sec": t, "event_type": "event_" + eid,
           "video_context": {"broadcast_phase": "LIVE"}}
          for eid, t in zip("xyzwv", (30, 35, 60, 120, 125))]
PLAN = {"story": "test sequence"}


def _write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _hypotheses(ids):
    return {"hypotheses": [{
        "hypothesis_id": "H1", "mechanism_key": "reaction",
        "narrative_summary": "A plausible sequence",
        "supporting_event_ids": ids,
        "proposed_long_range_relations": [
            {"source_event_id": a, "target_event_id": b,
             "relation_type": "causal_hypothesis", "claim": "Possible effect"}
            for a, b in zip(ids, ids[1:])
        ],
        "falsification_conditions": ["Footage contradicts the change"],
        "observation_queries": [{"target_id": "event:" + ids[0], "question": "What happened?"}],
    }]}


class _DiscoveryAPI:
    configs = {"planner": EndpointConfig(role="planner", base_url="", api_key="", model="")}
    max_calls = 12
    max_cost_usd = 0.10
    _http_attempts = 0

    def __init__(self):
        self.roles = []

    def chat(self, **kwargs):
        role = kwargs["stats_role"]
        self.roles.append(role)
        self._http_attempts += 1
        context = json.loads(kwargs["messages"][1]["content"])
        assert role == "story_first_generator"
        result = _hypotheses([e["event_id"] for e in context["full_event_inventory"]])
        return {"provider_mode": "real", "content": json.dumps(result), "finish_reason": "stop"}


def _generate(tmp_path, monkeypatch):
    monkeypatch.setenv("STORY_FIRST_LLM_MODEL", "DeepSeek-V4.1-Flash")
    api = _DiscoveryAPI()
    pool = search.discover_story_first(
        edl=EDL, story_plan=PLAN, events=EVENTS, source_sha="a" * 64,
        out_dir=tmp_path, api=api,
    )
    assert api.roles == ["story_first_generator"] * 2
    return pool


def test_all_intervals_and_planner_receives_all_without_scorer(tmp_path, monkeypatch):
    pool = _generate(tmp_path, monkeypatch)
    assert [i["scope"]["source_interval_sec"] for i in pool["intervals"]] == [[10, 90], [100, 170]]
    assert [p["proposal_id"] for p in pool["proposals"]] == ["interval_01:H1", "interval_02:H1"]
    from story_video_agent_v3.story_first_revision import bind_story_first_trial

    proposal = pool["proposals"][0]
    duplicate = {k: proposal["relations"][0][k] for k in (
        "source_event_id", "target_event_id", "relation_type", "claim"
    )}
    bound = bind_story_first_trial({
        "selections": [{"proposal_id": proposal["proposal_id"],
                        "event_ids": ["x", "y"], "relation_ids": ["r1"]}],
        "revised_relations": [duplicate],
    }, pool["proposals"], EDL, set())
    assert [r["relation_id"] for r in bound["relations"]] == ["interval_01:H1:r1"]

    assert all(i["score_status"] == "OFFLINE_RESEARCH_ONLY" for i in pool["intervals"])
    rank_dir = tmp_path / "interval_01/scheme_a_ranking"
    assert not rank_dir.exists()

    # An unusable historical score cache cannot affect generator artifact reuse.
    rank_dir.mkdir()
    (rank_dir / "scheme_a_story_ranking.json").write_text("broken historical score")


    class Planner:
        def revise_decision(self, **kw):
            prompt = kw["user_prompt"]
            for proposal in pool["proposals"]:
                assert proposal["proposal_id"] in prompt
            for field in ("causal_combination_prior", "internal_causal_link", "model_priority_0_to_1",
                          "causal_mechanism", "major_uncertainty"):
                assert field not in prompt

            return {"provider_mode": "real", "content": '{"decision":"KEEP","story_first_trial":null}'}

    result = run_llm_revision_planner(
        Planner(), diagnosis={}, vlm_critic={}, protected_goal_ids=[],
        audit_dir=tmp_path / "planner", story_first_proposals=pool["proposals"],
    )
    assert result["ok"] and result["story_first_trial"] is None

    cached = search.discover_story_first(
        edl=EDL, story_plan=PLAN, events=EVENTS, source_sha="a" * 64,
        out_dir=tmp_path / "reuse", artifacts_dir=tmp_path,
    )
    assert [i["status"] for i in cached["intervals"]] == ["REUSED", "REUSED"]
    assert cached["proposals"] == pool["proposals"]


def _first_live_pack(root, sha, start=22, end=43):
    root.mkdir(parents=True, exist_ok=True)
    def write_bytes(name, payload):
        path = root / name
        path.write_bytes(payload)
        return {"path": str(path), "sha256": hashlib.sha256(payload).hexdigest()}
    pts = (start + 1, start + 8, end - 1)
    frames = [
        {"frame_id": f"f{i}", "source_pts_sec": t, **write_bytes(f"f{i}.jpg", str(t).encode())}
        for i, t in enumerate(pts)
    ]
    clip = {"source_sha256": sha, "source_pts_start": start - 4, "source_pts_end": end + 4,
            **write_bytes("context.mp4", b"fixture-only")}
    manifest = {"frame_sha256": [f["sha256"] for f in frames]}
    return {
        "schema": SCHEMA, "source_sha256": sha, "source_pts_start": start, "source_pts_end": end,
        "key": window_key(sha, start, end), "frames": frames, "manifest": manifest,
        "manifest_digest": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
        "broadcast_timeline_review": {
            "schema": TIMELINE_REVIEW_SCHEMA, "source_sha256": sha,
            "source_pts_start": start, "source_pts_end": end, "outcome": "FIRST_LIVE_VERIFIED",
            "phase_evidence": {
                "schema": PHASE_SCHEMA, "action_kind": "STORY_ACTION",
                "source_sha256": sha, "source_pts_start": start, "source_pts_end": end,
                "action_start_sec": start + 7, "action_end_sec": start + 10,
                "reviewer": {"kind": "HUMAN_CONTINUOUS_VIDEO_REVIEW", "review_record_id": "fixture"},
                "continuous_context_clip": clip,
                "phase_observations": [
                    {"phase": phase, "frame_id": f["frame_id"], "source_pts_sec": f["source_pts_sec"],
                     "visible_cue": "fixture observation explicitly bound to original frame"}
                    for phase, f in zip(STORY_ACTION_PHASES, frames)
                ],
                "later_replay_status": LATER_REPLAY_NOT_OBSERVED,
                "post_action_reviewed_through_sec": end,
                "prior_occurrence_reviewed": True,
                "prior_occurrence_method": "fixture_full_original_review",
                "prior_occurrence_result": "NO_EARLIER_SAME_ACTION",
                "timeline_context_complete": True,
            },
        },
    }


def test_non_goal_first_live_does_not_certify_goals(tmp_path):
    sha = "a" * 64
    pack = _first_live_pack(tmp_path, sha)
    kwargs = dict(source_sha=sha, pts_start=22, pts_end=43)
    assert validate_first_live_evidence_record(pack, **kwargs, allow_non_goal_action=True)["ok"]
    assert not validate_first_live_evidence_record(pack, **kwargs)["ok"]
    pack["broadcast_timeline_review"]["phase_evidence"]["prior_occurrence_reviewed"] = False
    assert not validate_first_live_evidence_record(pack, **kwargs, allow_non_goal_action=True)["ok"]


@pytest.mark.parametrize("strict_first_live", [True, False])
def test_main_loop_removes_contradicted_event_and_renders_bound_trial(
    tmp_path, monkeypatch, strict_first_live,
):
    _generate(tmp_path / "cache", monkeypatch)
    source = tmp_path / "match.mp4"
    source.write_bytes(b"offline source fixture")
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    first_live = _first_live_pack(tmp_path / "pack", sha)
    live_store = _write(tmp_path / "first_live.json", first_live) if strict_first_live else None
    phase5 = tmp_path / "phase5"
    _write(phase5 / "candidate_edl.json", EDL)
    _write(phase5 / "story_plan.json", PLAN)
    (phase5 / "story_clean.mp4").write_bytes(b"offline baseline fixture")
    match = _write(tmp_path / "events.json", {
        "events": [{**e, "annotation_quality": {"annotator_confidence": 1.0},
                    "notes": "human annotation"} for e in EVENTS],
        "teams": {"team_1": {"name": "A", "color": "red"}},
    })
    monkeypatch.setattr(agent, "observe_layers", lambda **kw: {})
    render_calls = []

    def render(**kw):
        render_calls.append(kw["edl"])
        path = kw["out_dir"] / "story_clean.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"offline candidate fixture")
        return {"ok": True, "story_clean": str(path)}

    def review(api, *, trial, source_mp4, source_sha, out_dir, source_event_context, teams):
        assert api is None
        assert teams["team_1"]["color"] == "red"
        assert [e["event_id"] for e in source_event_context][:3] == ["x", "y", "z"]
        assert source_event_context[0]["annotation_source"] == "annotated_delivery_event"
        if any(e["event_id"] == "z" for e in trial["events"]):
            return {"feedback": [{"event_id": "z", "status": "CONTRADICTED",
                                  "reason": "wrong possession"}], "event_observations": []}
        return {
            "feedback": [] if strict_first_live else [
                {"event_id": "x", "status": "UNCERTAIN", "reason": "contact not visible"},
            ],
            "event_observations": [
                {"event_id": event["event_id"], "reason": "visible action",
                 "status": "UNCERTAIN" if event["event_id"] == "x" and not strict_first_live else "SUPPORTED",
                 "frame_ids": [f"f{i}"]}
                for i, event in enumerate(trial["events"], 1)
            ],
        }

    monkeypatch.setattr(agent, "_render_edl", render)
    monkeypatch.setattr(video, "observe_story_first_trial", review)
    round_fixtures = [
        {"story_first_trial": {"selections": [
            {"proposal_id": "interval_01:H1", "event_ids": ids, "relation_ids": rels},
        ], "rationale": "Candidate explains the transition"},
         **({"phase8_safety": "PASS", "phase8_quality": "BETTER",
             "phase8_evidence": "SUFFICIENT", "issue_effect": "RESOLVED",
             "global_regression": "NO"} if not strict_first_live else {})}
        for ids, rels in ((["x", "y", "z"], ["r1", "r2"]), (["x", "y"], ["r1"]))
    ]
    audit = agent.run_story_e2e(agent.StoryE2EInputs(
        match_json=match, source_mp4=source, out_dir=tmp_path / "run", phase5_dir=phase5,
        enable_story_first=True, story_first_artifacts_dir=tmp_path / "cache",
        phase8_round_fixtures=round_fixtures, first_live_evidence_dir=live_store,
        smoke_render=False, max_rounds=2,
    ))
    assert audit["http_calls"] == 0
    assert [r["story_first_trial_status"] for r in audit["rounds"]] == [
        "NEEDS_REVISION", "READY_FOR_TRIAL",
    ]
    assert len(render_calls) == 1
    added = [r for r in render_calls[0] if str(r["segment_id"]).startswith("seg_story_first_")]
    assert len(added) == 1 and added[0]["event_ids"] == ["x", "y"]
    assert audit["delivery"]["release_authorized"] is False
    paths = tmp_path / "run/02_round_02"
    assert (paths / "verifier_report.json").is_file()
    from story_video_agent_v3.dual_video_vision_verifier import build_verifier_focus_from_revision_cases

    case_file = json.loads((paths / "revision_cases.json").read_text())
    focus = build_verifier_focus_from_revision_cases(case_file["cases"])
    assert focus["targets"][0]["original_defect"] is None
    assert focus["targets"][0]["story_first_trial_id"]
    assert "Candidate explains the transition" in focus["focus_lines"][0]
    assert "proposed editorial gain" in focus["focus_lines"][0]
    ledger = json.loads((paths / "first_live_window_ledger.json").read_text())
    if strict_first_live:
        assert ledger["windows"][0]["status"] == "FIRST_LIVE_VERIFIED"
    else:
        assert ledger["windows"][0]["status"] == "NOT_VERIFIED"
        assert added[0]["evidence_status"] == "NO_ANNOTATED_REPLAY_OVERLAP"
        assert added[0]["first_live_status"] == "NOT_VERIFIED"
        assert audit["phase8_delivery_version_id"] == "v0"
        transition = json.loads((paths / "phase8_transition.json").read_text())
        assert not transition["promote"] and transition["working_ref"] == "v0"
        preview = json.loads((tmp_path / "run/99_final/human_review_candidate/human_review_status.json").read_text())
        assert preview["story_first_preview_only"] and preview["safe_playable_preview"]
    feedback = json.loads((paths / "story_first_feedback.json").read_text())
    assert feedback[0]["findings"][0]["event_id"] == "z"
    if not strict_first_live:
        assert feedback[1]["advisory"][0]["status"] == "UNCERTAIN"


def test_source_observation_binds_event_frames_without_relation_or_fit_gate(tmp_path):
    import shutil
    import subprocess

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg unavailable")
    source = tmp_path / "source.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
        "-i", "testsrc2=duration=16:size=96x64:rate=25", "-c:v", "libx264", str(source),
    ], check=True, capture_output=True)
    trial = {
        "events": [{"event_id": "x", "source_pts_sec": 6.0}, {"event_id": "y", "source_pts_sec": 8.0}],
        "relations": [{"relation_id": "r", "source_event_id": "x", "target_event_id": "y"}],
        "windows": [{
            "candidate_id": "w", "source_pts_start": 4.0, "source_pts_end": 10.0,
            "event_ids": ["x", "y"], "issue_id": "f",
            "insert_after_segment_id": "a", "before_segment_id": "b",
        }],
    }

    class Vision:
        def vision_json(self, **kw):
            refs = kw["frame_bindings"]
            by_event = {eid: r["frame_id"] for r in refs for eid in r["event_ids"]}
            assert set(by_event) == {"x", "y"}
            assert all(r["pts_status"] == "pts" for r in refs)
            assert all(r["role"] == "candidate" and 4 <= r["source_pts_sec"] <= 10 for r in refs)
            assert len(refs) == 4
            assert "relation_id" not in kw["prompt"]
            assert "before_to_candidate" not in kw["prompt"]
            assert "source_event_context" in kw["prompt"]
            result = {
                "events": [{"event_id": eid, "status": "SUPPORTED", "frame_ids": [fid],
                            "reason": "Fixture observation at the referenced event frame"}
                           for eid, fid in by_event.items()],
                # Old-schema extras must not affect the result.
                "relations": [{"relation_id": "r", "status": "CONTRADICTED"}],
                "fit": [{"window_id": "w", "verdict": "REJECT_INSERT"}],
            }
            return {"provider_mode": "real", "finish_reason": "stop", "content": json.dumps(result)}

    result = video.observe_story_first_trial(
        Vision(), trial=trial, source_mp4=source,
        source_sha=hashlib.sha256(source.read_bytes()).hexdigest(), out_dir=tmp_path / "review",
    )
    assert result["feedback"] == []
    assert [(r["event_id"], r["status"]) for r in result["event_observations"]] == [
        ("x", "SUPPORTED"), ("y", "SUPPORTED"),
    ]

    class WrongCitation(Vision):
        def vision_json(self, **kw):
            raw = super().vision_json(**kw)
            parsed = json.loads(raw["content"])
            parsed["events"][0]["frame_ids"] = parsed["events"][1]["frame_ids"]
            return {**raw, "content": json.dumps(parsed)}

    wrong = video.observe_story_first_trial(
        WrongCitation(), trial=trial, source_mp4=source,
        source_sha=hashlib.sha256(source.read_bytes()).hexdigest(), out_dir=tmp_path / "wrong",
    )
    assert [row["event_id"] for row in wrong["feedback"]] == ["x"]
    assert wrong["feedback"][0]["status"] == "UNCERTAIN"


@pytest.mark.parametrize("phase, start, end, blocked", [
    ("REPLAY", 42, 46, True), ("SLOW_MOTION", 20, 23, True),
    ("REPLAY", 43, 46, False), ("LIVE", 42, 46, False),
    ("REPLAY", None, None, True),
])
def test_story_first_trial_respects_annotated_media_windows(
    tmp_path, monkeypatch, phase, start, end, blocked,
):
    from story_video_agent_v3 import story_first_revision as revision

    monkeypatch.setattr(video, "observe_story_first_trial", lambda *a, **kw: {
        "feedback": [],
        "event_observations": [
            {"event_id": "x", "status": "SUPPORTED", "reason": "visible", "frame_ids": ["f1"]},
        ],
    })
    trial = {
        "trial_id": "s", "narrative_purpose": "Show the buildup",
        "events": [{"event_id": "x", "source_pts_sec": 30.0, "event_type": "event_x"}],
        "windows": [{"candidate_id": "w", "event_ids": ["x"], "source_pts_start": 22.0,
                     "source_pts_end": 43.0, "issue_id": "s",
                     "insert_after_segment_id": "a", "before_segment_id": "b"}],
    }
    reviewed = revision.review_story_first_trial(
        trial, api=None, source_mp4=None, source_sha="a" * 64,
        out_dir=tmp_path, first_live_store={}, source_events=[EVENTS[0], {
            "event_id": "overlap", "event_type": "segment",
            "media_time": {"event_time_sec": 41 if start is None else start,
                           "start_time_sec": start, "end_time_sec": end},
            "video_context": {"broadcast_phase": phase},
        }],
    )
    if blocked:
        assert reviewed["status"] == "NEEDS_REVISION"
        assert reviewed["intents"] == []
        assert reviewed["feedback"][0]["status"] == "REPLAY_CONFIRMED"
    else:
        assert reviewed["status"] == "READY_FOR_TRIAL"
        assert reviewed["intents"][0]["story_first_preview_only"]
        assert reviewed["candidates"][0]["replay_overlap_status"] == "NO_ANNOTATED_REPLAY_OVERLAP"
        assert reviewed["candidates"][0]["first_live_status"] == "NOT_VERIFIED"


@pytest.mark.parametrize("annotated, expected_status", [(True, "READY_FOR_TRIAL"), (False, "NEEDS_REVISION")])
def test_annotations_are_required_to_trial_without_visual_review(tmp_path, annotated, expected_status):
    from story_video_agent_v3.story_first_revision import review_story_first_trial

    trial = {
        "trial_id": "s", "narrative_purpose": "Show the buildup",
        "events": [{"event_id": "x", "source_pts_sec": 30.0, "event_type": "event_x"}],
        "windows": [{"candidate_id": "w", "event_ids": ["x"], "source_pts_start": 22.0,
                     "source_pts_end": 43.0, "issue_id": "s",
                     "insert_after_segment_id": "a", "before_segment_id": "b"}],
    }
    event = dict(EVENTS[0])
    if annotated:
        event["enrichment"] = {"provenance": "independent_atomic_annotation"}
    reviewed = review_story_first_trial(
        trial, api=None, source_mp4=None, source_sha="a" * 64, out_dir=tmp_path,
        first_live_store={}, source_events=[event],
    )
    assert reviewed["status"] == expected_status
    if annotated:
        assert reviewed["intents"][0]["story_first_preview_only"]
        assert reviewed["advisory"][0]["status"] == "AWAITING_VIDEO_REVIEW"
    else:
        assert reviewed["intents"] == []
        assert reviewed["feedback"][0]["status"] == "AWAITING_VIDEO_REVIEW"


def test_multi_clip_story_in_one_gap_preserves_source_order(tmp_path, monkeypatch):
    from story_video_agent_v3 import story_first_revision as revision
    from story_video_agent_v3.self_revise_agent import apply_candidate_revision

    monkeypatch.setattr(video, "observe_story_first_trial", lambda *a, **kw: {
        "feedback": [], "event_observations": [],
    })
    monkeypatch.setattr(revision, "_annotate_first_live_tier", lambda window, **kw: {
        **window, "executable_safe_revision": True, "first_live_status": "FIRST_LIVE_VERIFIED",
    })
    windows = [
        {
            "candidate_id": f"w{i}", "event_ids": [f"e{i}"], "source_pts_start": t,
            "source_pts_end": t + 5, "issue_id": "s", "insert_after_segment_id": "a",
            "before_segment_id": "b",
        } for i, t in enumerate((21, 40))
    ]
    review = revision.review_story_first_trial(
        {"trial_id": "s", "windows": windows, "events": [],
         "narrative_purpose": "Show the buildup"},
        api=None, source_mp4=None, source_sha=None, out_dir=tmp_path, first_live_store={},
    )
    candidate, _ = apply_candidate_revision(EDL, review["intents"], [])
    assert [row["segment_id"] for row in candidate if row["segment_id"].startswith("seg_w")] == [
        "seg_w0", "seg_w1",
    ]


@pytest.mark.parametrize("replay_bounds, expected", [
    ((19, 27), [(27, 38)]),
    ((34, 40), [(22, 34)]),
    ((33, 35), [(22, 33), (35, 38)]),
])
def test_replay_replacement_persists_and_rebinds(
    tmp_path, monkeypatch, replay_bounds, expected,
):
    from story_video_agent_v3 import story_first_revision as revision

    monkeypatch.setenv("STORY_FIRST_LLM_MODEL", "DeepSeek-V4.1-Flash")
    replay = {
        "event_id": "broadcast_replay", "event_type": "segment",
        "media_time": {"event_time_sec": sum(replay_bounds) / 2,
                       "start_time_sec": replay_bounds[0], "end_time_sec": replay_bounds[1]},
        "video_context": {"broadcast_phase": "REPLAY"},
    }
    source_events = [*EVENTS, replay]
    class API(_DiscoveryAPI):
        def chat(self, **kwargs):
            self._http_attempts += 1
            context = json.loads(kwargs["messages"][1]["content"])
            result = _hypotheses([e["event_id"] for e in context["full_event_inventory"]
                                  if e["event_id"] != replay["event_id"]])
            return {"provider_mode": "real", "content": json.dumps(result), "finish_reason": "stop"}

    prior_run = tmp_path / "prior"
    prior = prior_run / "story_first"
    pool = search.discover_story_first(edl=EDL, story_plan=PLAN, events=source_events,
                                      source_sha="a" * 64, out_dir=prior, api=API())
    original = pool["proposals"][0]
    untouched = pool["proposals"][1]
    selection = {"selections": [{"proposal_id": original["proposal_id"], "event_ids": ["x"]}]}
    trial = revision.bind_story_first_trial(selection, pool["proposals"], EDL, set())
    declined = revision.review_story_first_trial(
        trial, api=None, source_mp4=None, source_sha="a" * 64,
        out_dir=tmp_path / "rejected", first_live_store={}, source_events=source_events,
    )
    assert declined["feedback"][0]["status"] == "REPLAY_CONFIRMED"
    _write(prior_run / "02_round_01/story_first_trial.json", {"trial": trial, "review": declined})
    for n in range(2):
        next_dir = tmp_path / f"resume_{n}" / "story_first"
        updated = search.discover_story_first(edl=EDL, story_plan=PLAN, events=source_events,
                                              source_sha="a" * 64, out_dir=next_dir, artifacts_dir=prior)
        assert updated["proposals"][1] == untouched
        assert updated["proposals"][0]["proposal_id"] == original["proposal_id"]
        assert len(updated["replay_revision_history"]) == 1
        assert [i["status"] for i in updated["intervals"]] == ["REUSED", "REUSED"]
        prior = next_dir
    rebound = revision.bind_story_first_trial(selection, updated["proposals"], EDL, {trial["trial_id"]})
    assert [(w["source_pts_start"], w["source_pts_end"]) for w in rebound["windows"]] == expected
    monkeypatch.setattr(video, "observe_story_first_trial", lambda *a, **kw: {
        "feedback": [], "event_observations": [],
    })
    reviewed = revision.review_story_first_trial(
        rebound, api=None, source_mp4=None, source_sha="a" * 64,
        out_dir=tmp_path / "reviewed", first_live_store={}, source_events=source_events,
    )
    assert reviewed["status"] == "READY_FOR_TRIAL"
    assert len(reviewed["intents"]) == len(expected)
    from story_video_agent_v3.self_revise_agent import apply_candidate_revision
    revised, applied = apply_candidate_revision(EDL, reviewed["intents"], [])
    assert not applied["rejected"]
    assert [(w["media_in"], w["media_out"]) for w in revised
            if w["segment_id"].startswith("seg_story_first_")] == expected


@pytest.mark.parametrize("outer_rounds, replay, initial_replay", [
    (1, False, False), (2, False, False), (2, True, False), (1, False, True),
])
def test_e2e_rendered_story_first_routes_to_caption_p3(
    tmp_path, monkeypatch, outer_rounds, replay, initial_replay,
):
    from story_video_agent_v3 import story_first_outer as outer
    from story_video_agent_v3 import story_first_p3 as p3
    from story_video_agent_v3 import story_paid_eval as paid
    from story_video_agent_v3.story_timeline import build_story_timeline

    _generate(tmp_path / "cache", monkeypatch)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source fixture")
    phase5 = tmp_path / "phase5"
    _write(phase5 / "candidate_edl.json", EDL)
    _write(phase5 / "story_plan.json", PLAN)
    (phase5 / "story_clean.mp4").write_bytes(b"baseline fixture")
    events = [{**e, "annotation_quality": {"annotator_confidence": 1.0},
               "notes": "human annotation"} for e in EVENTS]
    if replay or initial_replay:
        left, right = (42, 46) if initial_replay else (127, 129)
        events.append({"event_id": "replay", "event_type": "segment",
                       "media_time": {"event_time_sec": left, "start_time_sec": left, "end_time_sec": right},
                       "video_context": {"broadcast_phase": "REPLAY"}})
    match = _write(tmp_path / "events.json", {"events": events})
    roles = []

    class API(_DiscoveryAPI):
        max_completion_tokens = 1200

        def status(self):
            return {"planner_ready": True, "vision_ready": True}

        def revise_decision(self, **kwargs):
            roles.append("initial_planner")
            self._http_attempts += 1
            selection = {"selections": [
                {"proposal_id": "interval_01:H1", "event_ids": ["x", "y"], "relation_ids": ["r1"]},
            ], "rationale": "Try new buildup"}
            return {"provider_mode": "real", "finish_reason": "stop", "content": json.dumps(
                {"decision": "KEEP", "story_first_trial": selection}
            )}

        def chat(self, **kwargs):
            role = kwargs["stats_role"]
            roles.append(role)
            self._http_attempts += 1
            if role == "story_first_generator":
                context = json.loads(kwargs["messages"][1]["content"])
                if "revision_context" in context:
                    assert context["revision_context"]["tried_event_ids"] == ["x", "y"]
                content = _hypotheses([e["event_id"] for e in context["full_event_inventory"]
                                       if e["event_id"] != "replay"])
            elif role == "story_first_p35_planner":
                pid, ids = ("interval_01:H1", ["x", "y"]) if initial_replay else ("interval_02:H1", ["w"])
                content = {"selection": {"selections": [
                    {"proposal_id": pid, "event_ids": ids},
                ]}}
            elif role == "story_first_p3_caption":
                parts = kwargs["messages"][0]["content"]
                targets = json.loads(parts[0]["text"].split("Observation targets: ")[-1].rstrip(". "))
                phase = next(t for t in targets if t["phase"] == "insert")
                start = phase["story_range_sec"][0]
                for part in parts[1::2]:
                    clip, span = part["text"].split(" story seconds ")
                    lo, hi = json.loads(span)
                    if lo <= start and start + 0.1 <= hi:
                        break
                content = {"observations": [{"phase_id": phase["phase_id"], "clip_id": clip,
                                             "story_range_sec": [start, start + 0.1],
                                             "description": "Midfield play."}]}
            else:
                assert role == "story_first_p3_planner"
                content = {"actions": [{"action": "KEEP", "rationale": "Review this preview"}]}
            return {"provider_mode": "real", "finish_reason": "stop", "content": json.dumps(content)}

    def review(api, **kwargs):
        roles.append("existing_source_review")
        assert api is not None
        return {"feedback": [], "event_observations": []}

    def alignment(*, edl, mp4):
        timeline = build_story_timeline(edl)
        return {"aligned": mp4.is_file(), "timeline": timeline,
                "mp4_duration_sec": timeline["story_duration_sec"]}

    def fake_clip(*, source_mp4, begin, end, output):
        output.write_bytes(b"native video fixture")
        return {"ok": True, "path": str(output), "sha256": "fixture", "bytes": 20}

    def render(*, out_dir, edl, **kwargs):
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "story_clean.mp4"
        path.write_text(json.dumps(edl))
        return {"ok": True, "story_clean": str(path)}

    def obsolete(*args, **kwargs):
        pytest.fail("The Story-First trial must not enter the old finished-cut judging")

    monkeypatch.setattr(paid, "build_capped_provider", lambda **kwargs: API())
    monkeypatch.setattr(paid, "run_llm_verifier", obsolete)
    monkeypatch.setattr(paid, "run_vlm_story_critic", obsolete)
    monkeypatch.setattr(video, "observe_story_first_trial", review)
    monkeypatch.setattr(agent, "_render_edl", render)
    monkeypatch.setattr(agent, "observe_layers", lambda **kwargs: {})
    monkeypatch.setattr(p3, "timeline_mp4_aligned", alignment)
    monkeypatch.setattr(outer, "timeline_mp4_aligned", alignment)
    monkeypatch.setattr(p3, "_source_context_video", fake_clip)
    audit = agent.run_story_e2e(agent.StoryE2EInputs(
        match_json=match, source_mp4=source, out_dir=tmp_path / "run", phase5_dir=phase5,
        enable_story_first=True, story_first_artifacts_dir=tmp_path / "cache",
        story_first_outer_rounds=outer_rounds,
        enable_real_api=True, i_approve_budget=True, smoke_render=False,
        max_rounds=2 if initial_replay else 1, phase8_paid_multi_round=initial_replay,
    ))
    roles = roles[roles.index("initial_planner"):]
    if initial_replay:
        assert roles[1] == "story_first_p35_planner"
        roles.pop(1)
        assert [r["story_first_trial_status"] for r in audit["rounds"]] == ["NEEDS_REVISION", "READY_FOR_TRIAL"]
        planner_path = tmp_path / "run/02_round_02/paid_api/story_first_replay_replan/planner_input.json"
        reranked = json.loads(planner_path.read_text())["fresh_p1_candidates"]
        assert reranked[0]["replay_window_edits"][0]["retained_source_windows_sec"] == [[22, 42]]
    assert roles[:4] == ["initial_planner", "existing_source_review",
                         "story_first_p3_caption", "story_first_p3_planner"]
    assert audit["story_first_p3"]["stop_reason"] == "PLANNER_KEEP"
    assert audit["story_first_p3"]["http_calls"] == 2
    assert audit["story_first_p3"]["selected_preview_mp4"].endswith("candidate_render/story_clean.mp4")
    assert audit["delivery"]["release_authorized"] is False
    report = audit["story_first_outer"]
    assert report["attempted_outer_rounds"] == outer_rounds
    assert not report["release_authorized"]
    v0, v1, *continued = report["comparison"]
    assert v0["mp4_sha256"] != v1["mp4_sha256"]
    if continued:
        assert roles[4:7] == ["story_first_generator", "story_first_generator", "story_first_p35_planner"]
        v2 = continued[0]
        if replay:
            assert roles[7:] == ["story_first_p35_planner", "existing_source_review",
                                 "story_first_p3_caption", "story_first_p3_planner"]
            assert v2["status"] == "ACCEPTED_PREVIEW"
            assert v1["mp4_sha256"] != v2["mp4_sha256"]
            assert report["round_history"][-1]["source_windows_sec"] == [(112, 127)]
            p2_dir = tmp_path / "run/story_first_outer/round_02"
            initial = json.loads((p2_dir / "p2_review.json").read_text())
            planner_input = json.loads((p2_dir / "replay_replan/planner_input.json").read_text())
            assert initial["review"]["feedback"][0]["status"] == "REPLAY_CONFIRMED"
            replacement = next(p for p in planner_input["fresh_p1_candidates"]
                               if p["proposal_id"] == "interval_02:H1")
            assert replacement["replay_window_edits"][0]["retained_source_windows_sec"] == [[112, 127]]
        else:
            assert roles[7:] == ["existing_source_review", "story_first_p3_caption", "story_first_p3_planner"]
            assert v2["status"] == "ACCEPTED_PREVIEW"
            assert v1["mp4_sha256"] != v2["mp4_sha256"]
            final = json.loads((tmp_path / "run/story_first_outer/v2_edl.json").read_text())
            parent = json.loads((tmp_path / "run/story_first_outer/v1_edl.json").read_text())
            assert [r for r in final if r["segment_id"] in {p["segment_id"] for p in parent}] == parent
