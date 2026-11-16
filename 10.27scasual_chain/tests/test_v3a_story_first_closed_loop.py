"""Story-First discovery, source evidence and actual revision-loop wiring, zero HTTP."""
import hashlib
import json

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
        if role.endswith("generator"):
            result = _hypotheses([e["event_id"] for e in context["full_event_inventory"]])
        else:
            item = context["candidate_stories"][0]
            result = {"evaluations": [{
                "hypothesis_id": item["hypothesis_id"],
                **dict.fromkeys(("internal_causal_link", "anchor_causal_bridge",
                                 "joint_causal_gain", "factual_support"), 1),
                "cited_event_ids": item["supporting_event_ids"],
                "causal_mechanism": "A possible connection",
                "major_uncertainty": "Actors need visual confirmation",
            }]}
        return {"provider_mode": "real", "content": json.dumps(result), "finish_reason": "stop"}


def _generate(tmp_path, monkeypatch):
    monkeypatch.setenv("STORY_FIRST_LLM_MODEL", "DeepSeek-V4.1-Flash")
    api = _DiscoveryAPI()
    pool = search.discover_story_first(
        edl=EDL, story_plan=PLAN, events=EVENTS, source_sha="a" * 64,
        out_dir=tmp_path, api=api,
    )
    assert api.roles == ["story_first_generator"] * 2 + ["story_first_scorer"] * 2
    return pool


def test_all_intervals_and_planner_receives_all_without_numeric_score(tmp_path, monkeypatch):
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

    rank_path = tmp_path / "interval_01/scheme_a_ranking/scheme_a_story_ranking.json"
    assert json.loads(rank_path.read_text())["ranked_hypotheses"][0]["causal_combination_prior"] == .25

    class Planner:
        def revise_decision(self, **kw):
            prompt = kw["user_prompt"]
            for proposal in pool["proposals"]:
                assert proposal["proposal_id"] in prompt
            for field in ("causal_combination_prior", "internal_causal_link", "model_priority_0_to_1"):
                assert field not in prompt
            assert "Actors need visual confirmation" in prompt
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


def test_main_loop_removes_contradicted_event_and_renders_bound_trial(tmp_path, monkeypatch):
    from story_video_agent_v3.story_narrative_fit import SCHEMA as FIT_SCHEMA, context_for_candidate

    _generate(tmp_path / "cache", monkeypatch)
    source = tmp_path / "match.mp4"
    source.write_bytes(b"offline source fixture")
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    first_live = _first_live_pack(tmp_path / "pack", sha)
    live_store = _write(tmp_path / "first_live.json", first_live)
    phase5 = tmp_path / "phase5"
    _write(phase5 / "candidate_edl.json", EDL)
    _write(phase5 / "story_plan.json", PLAN)
    (phase5 / "story_clean.mp4").write_bytes(b"offline baseline fixture")
    match = _write(tmp_path / "events.json", {"events": EVENTS})
    monkeypatch.setattr(agent, "observe_layers", lambda **kw: {})
    render_calls = []

    def render(**kw):
        render_calls.append(kw["edl"])
        path = kw["out_dir"] / "story_clean.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"offline candidate fixture")
        return {"ok": True, "story_clean": str(path)}

    def review(api, *, trial, edl, source_mp4, source_sha, out_dir):
        assert api is None
        if any(e["event_id"] == "z" for e in trial["events"]):
            return {"feedback": [{"event_id": "z", "status": "CONTRADICTED",
                                  "reason": "wrong possession"}], "fit_records": {}}
        window, = trial["windows"]
        ctx = context_for_candidate(window, edl)
        frame = first_live["frames"][0]
        refs = [{"role": role, "frame_id": role, "path": frame["path"], "sha256": frame["sha256"],
                 "source_pts_sec": (ctx[role]["source_pts_start"] + ctx[role]["source_pts_end"]) / 2}
                for role in ("before", "candidate", "after")]
        return {"feedback": [], "fit_records": {window["candidate_id"]: {
            "schema": FIT_SCHEMA, "source_sha256": sha, "issue_id": window["issue_id"],
            "source_pts_start": 22, "source_pts_end": 43, "verdict": "SUPPORTS_INSERT",
            "review_method": "human_video_triplet",
            **{f"{role}_segment_id": ctx[role]["segment_id"] for role in ("before", "after")},
            **{f"{role}_pts_{k}": ctx[role][f"source_pts_{k}"]
               for role in ("before", "after") for k in ("start", "end")},
            "frame_refs": refs,
            "narrative_review": dict.fromkeys(
                ("before_to_candidate", "candidate_to_after", "new_story_information",
                 "baseline_comparison", "missing_information_addressed", "falsifiable_gain"),
                "fixture value for test binding only",
            ),
        }}}

    monkeypatch.setattr(agent, "_render_edl", render)
    monkeypatch.setattr(video, "observe_story_first_trial", review)
    round_fixtures = [
        {"story_first_trial": {"selections": [
            {"proposal_id": "interval_01:H1", "event_ids": ids, "relation_ids": rels},
        ], "rationale": "Candidate explains the transition"}}
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
    ledger = json.loads((paths / "first_live_window_ledger.json").read_text())
    assert ledger["windows"][0]["status"] == "FIRST_LIVE_VERIFIED"
    feedback = json.loads((paths / "story_first_feedback.json").read_text())
    assert feedback[0]["findings"][0]["event_id"] == "z"


def test_source_observation_uses_decoded_pts_and_relation_specific_citations(tmp_path):
    import shutil
    import subprocess

    import pytest

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg unavailable")
    source = tmp_path / "source.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
        "-i", "testsrc2=duration=16:size=96x64:rate=25", "-c:v", "libx264", str(source),
    ], check=True, capture_output=True)
    edl = [
        {"segment_id": "a", "media_in": 0.0, "media_out": 1.0},
        {"segment_id": "b", "media_in": 13.0, "media_out": 15.0},
    ]
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
            by_role = {role: [r["source_pts_sec"] for r in refs if r["role"] == role]
                       for role in ("before", "candidate", "after", "source_leadin", "source_followthrough")}
            assert all(by_role.values())
            assert all(0 <= pts <= 1 for pts in by_role["before"])
            assert all(1 < pts < 4 for pts in by_role["source_leadin"])
            assert all(10 < pts < 13 for pts in by_role["source_followthrough"])
            assert all(13 <= pts <= 15 for pts in by_role["after"])
            result = {
                "events": [{"event_id": eid, "status": "SUPPORTED", "frame_ids": [fid],
                            "reason": "Fixture observation at the referenced event frame"}
                           for eid, fid in by_event.items()],
                # A citation to x alone can't support the relationship to y.
                "relations": [{"relation_id": "r", "status": "SUPPORTED", "frame_ids": [by_event["x"]]}],
                "fit": [{
                    "window_id": "w", "verdict": "REJECT_INSERT",
                    "before_to_candidate": "Prior cut does not motivate insertion",
                    "candidate_to_after": "The later cut starts a different attack",
                    "new_story_information": "The clips show possession changed several times",
                    "baseline_comparison": "The baseline already conveys the narrative transition",
                    "evidence_frame_ids": [
                        next(r["frame_id"] for r in refs if r["role"] == role)
                        for role in ("before", "candidate", "after")
                    ],
                }],
            }
            return {"provider_mode": "real", "finish_reason": "stop", "content": json.dumps(result)}

    result = video.observe_story_first_trial(
        Vision(), trial=trial, edl=edl, source_mp4=source,
        source_sha=hashlib.sha256(source.read_bytes()).hexdigest(), out_dir=tmp_path / "review",
    )
    assert result["feedback"] == [{
        "relation_id": "r", "event_ids": ["x", "y"], "status": "UNCERTAIN",
        "reason": "missing_bound_visual_support",
    }]
    from story_video_agent_v3.story_narrative_fit import validate_narrative_fit_review
    fit = validate_narrative_fit_review(
        result["fit_records"]["w"], candidate=trial["windows"][0],
        source_sha=hashlib.sha256(source.read_bytes()).hexdigest(), edl=edl,
    )
    assert fit["status"] == "REVIEW_REJECTED"
    assert fit["before_to_candidate"] == "Prior cut does not motivate insertion"


def test_multi_clip_story_in_one_gap_preserves_source_order(tmp_path, monkeypatch):
    from story_video_agent_v3 import story_first_revision as revision
    from story_video_agent_v3.self_revise_agent import apply_candidate_revision

    monkeypatch.setattr(video, "observe_story_first_trial", lambda *a, **kw: {
        "feedback": [], "fit_records": {},
    })
    monkeypatch.setattr(revision, "_annotate_first_live_tier", lambda window, **kw: {
        **window, "executable_safe_revision": True,
    })
    monkeypatch.setattr(revision, "validate_narrative_fit_review", lambda *a, **kw: {
        "status": "REVIEW_SUPPORTED", "reason": "fixture",
        "new_story_information": "new", "falsifiable_gain": "context",
    })
    windows = [
        {
            "candidate_id": f"w{i}", "event_ids": [f"e{i}"], "source_pts_start": t,
            "source_pts_end": t + 5, "issue_id": "s", "insert_after_segment_id": "a",
            "before_segment_id": "b",
        } for i, t in enumerate((21, 40))
    ]
    review = revision.review_story_first_trial(
        {"trial_id": "s", "windows": windows, "narrative_purpose": "fit"},
        api=None, edl=EDL, source_mp4=None, source_sha=None, out_dir=tmp_path,
        first_live_store={},
    )
    candidate, _ = apply_candidate_revision(EDL, review["intents"], [])
    assert [row["segment_id"] for row in candidate if row["segment_id"].startswith("seg_w")] == [
        "seg_w0", "seg_w1",
    ]
