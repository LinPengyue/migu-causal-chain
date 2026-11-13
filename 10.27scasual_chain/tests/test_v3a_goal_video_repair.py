"""V3-A goal-video repair gates: no external HTTP, no real match assertions.

A fake authenticated review tests only control-flow/safety; it is NOT a
claim that a model recognized a real football goal or first-broadcast shot.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from story_video_agent_v3.global_story_critic import detect_goal_coverage_hypotheses
from story_video_agent_v3.story_goal_video_repair import (
    _source_frames_match_decoded_video,
    apply_video_verified_goal_repair,
    goal_coverage_issues,
    prepare_source_video_goal_queue,
    repair_goal_coverage_from_video_reviews,
    validate_goal_video_review,
)


def _event(eid, sec, score=None, kind="Shot"):
    d = {
        "event_id": eid, "event_type": kind,
        "media_time": {"event_time_sec": sec},
        "video_context": {"broadcast_phase": "LIVE", "is_replay": False},
    }
    if score:
        d["scores"] = {"score_recognition": score}
    return d


def _edl():
    return [
        {"segment_id": "open", "role": "opponent_opening_goal_action",
         "media_in": 45., "media_out": 57., "goal_anchor_t_sec": 51.},
        {"segment_id": "deficit", "role": "deficit_scoreboard_anchor",
         "media_in": 63., "media_out": 67.},
        {"segment_id": "buildup", "role": "buildup_action",
         "media_in": 110., "media_out": 120.},
        {"segment_id": "eq_board", "role": "equalizer_scoreboard_anchor",
         "media_in": 163., "media_out": 167.},
        {"segment_id": "winner", "role": "go_ahead_goal_action",
         "media_in": 224., "media_out": 238., "goal_anchor_t_sec": 231.},
        {"segment_id": "win_board", "role": "go_ahead_scoreboard_anchor",
         "media_in": 243., "media_out": 247.},
    ]


def _issue():
    events = [
        _event("b0", 3., "0:0"),
        _event("op", 51., "0:0"),
        _event("b01", 64., "0:1"),
        _event("still", 132., "0:1"),
        _event("eqshot", 151., "0:1"),
        _event("b11", 164., "1:1"),
        _event("still1", 192., "1:1"),
        _event("winshot", 231., "1:1"),
        _event("b21", 244., "2:1"),
    ]
    issues = detect_goal_coverage_hypotheses(edl=_edl(), raw_events=events)
    assert len(issues) == 1
    return issues[0]


def _review(tmp_path):
    issue = _issue()
    sha = "d" * 64
    media_in, media_out = 145.0, 157.0
    frame_rows = []
    for i, sec in enumerate((150.0, 153.0)):
        path = tmp_path / f"frame{i}.jpg"
        path.write_bytes(f"synthetic_frame_{i}".encode())
        frame_rows.append({
            "frame_id": f"frame_{i}", "path": str(path),
            "source_pts_sec": sec,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    manifest = {"test": "fixture", "source_sha256": sha,
                "source_pts_start": media_in, "source_pts_end": media_out}
    binding = {
        "schema": "v3a_first_live_window_evidence_v1",
        "source_sha256": sha,
        "source_pts_start": media_in,
        "source_pts_end": media_out,
        "frames": frame_rows,
        "manifest": manifest,
        "manifest_digest": hashlib.sha256(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest(),
    }
    timeline_review = {
        "schema": "v3a_broadcast_timeline_review_v1",
        "source_sha256": sha,
        "source_pts_start": media_in,
        "source_pts_end": media_out,
        "outcome": "FIRST_LIVE_VERIFIED",
        "method": "FAKE_UNIT_TEST_EXPLICIT_REVIEW",
        "replay_hits": [],
    }
    clip = tmp_path / "continuous.mp4"
    clip.write_bytes(b"synthetic_continuous_clip_for_unit_test")
    review = {
        "issue_id": issue["issue_id"],
        "score_before": [0, 1],
        "score_after": [1, 1],
        "source_sha256": sha,
        "media_in": media_in, "media_out": media_out,
        "first_live_evidence": binding,
        "broadcast_timeline_review": timeline_review,
        "video_semantic_observation": {
            "reviewer_type": "HUMAN_CONTINUOUS_VIDEO_REVIEW",
            "frames": [{
                "frame_id": f["frame_id"],
                "path": f["path"],
            } for f in frame_rows],
            "vlm_inference": {
                "observed_shot": True,
                "observed_net": True,
                "live_or_replay": "live",
                "attacking_team_match": True,
                "claims_continuous_live": True,
                "shot_frame_ids": ["frame_0"],
                "net_frame_ids": ["frame_1"],
                "uncertain": [],
            },
            "continuous_source_clip_path": str(clip),
            "continuous_source_clip_sha256": hashlib.sha256(
                clip.read_bytes()
            ).hexdigest(),
        },
    }
    return issue, sha, review


def test_unreviewed_goal_gap_only_returns_unresolved():
    gap = _issue()
    out = repair_goal_coverage_from_video_reviews(
        edl=_edl(), diagnosis={"issues": [gap]},
        source_sha="d" * 64, review_dir=None,
    )
    assert not out["changed"]
    assert out["edl"] == _edl()
    assert out["decisions"][0]["status"] == "UNRESOLVED"
    assert out["release_authorized"] is False


def test_claimed_first_live_without_bound_video_and_real_source_redecode_rejected(tmp_path):
    gap, sha, review = _review(tmp_path)
    actual_video = tmp_path / "nonmatching_source.mp4"
    actual_video.write_bytes(b"not_the_claimed_source")
    result = validate_goal_video_review(
        review=review, issue=gap,
        source_sha=sha, source_mp4=actual_video,
    )
    assert not result["ok"]
    assert result["reason"] == "source_frame_bytes_not_redecoded_from_original_mp4"


def test_no_independent_broadcast_review_cannot_authorize_repair(tmp_path):
    gap, sha, review = _review(tmp_path)
    del review["broadcast_timeline_review"]
    result = validate_goal_video_review(
        review=review, issue=gap, source_sha=sha,
    )
    assert not result["ok"]
    assert "no_bound_independent_first_broadcast_proof" in result["reason"]


def test_forged_semantic_frame_id_refused_even_with_valid_timeline(tmp_path, monkeypatch):
    gap, sha, review = _review(tmp_path)
    monkeypatch.setattr(
        "story_video_agent_v3.story_goal_video_repair._source_frames_match_decoded_video",
        lambda **kwargs: True,
    )
    review["video_semantic_observation"]["vlm_inference"]["net_frame_ids"] = ["made_up"]
    result = validate_goal_video_review(
        review=review, issue=gap,
        source_sha=sha, source_mp4=tmp_path / "unit_source.mp4",
    )
    assert not result["ok"]
    assert result["reason"] == "video_semantic_shot_net_or_live_crosscheck_incomplete"


def test_positive_review_wires_action_insertion_without_claiming_story_quality(
    tmp_path, monkeypatch,
):
    gap, sha, review = _review(tmp_path)
    # Synthetic unit-test-only substitution. Real main run requires decoding
    # the actual original MP4 and checking all frame content hashes.
    monkeypatch.setattr(
        "story_video_agent_v3.story_goal_video_repair._source_frames_match_decoded_video",
        lambda **kwargs: True,
    )
    video = tmp_path / "unit_source.mp4"
    video.write_bytes(b"unit-only")
    check = validate_goal_video_review(
        review=review, issue=gap,
        source_sha=sha, source_mp4=video,
    )
    assert check["ok"]
    assert check["action_sec"] == 153.
    applied = apply_video_verified_goal_repair(
        edl=_edl(), issue=gap, validated=check,
    )
    assert applied["applied"] is True
    assert applied["new_role"] == "equalizer_goal_action"
    segments = applied["edl"]
    assert [r["segment_id"] for r in segments][:5] == [
        "open", "deficit", "buildup",
        applied["new_segment_id"], "eq_board"
    ]
    new = segments[3]
    assert new["goal_anchor_t_sec"] == 153.
    assert new["agent_auto_verified"] is False
    assert new["first_live_status"] == "FIRST_LIVE_VERIFIED"
    assert applied["does_not_claim_story_improvement"]


def test_repaired_goal_rejected_if_any_source_window_overlap(tmp_path, monkeypatch):
    gap, sha, review = _review(tmp_path)
    monkeypatch.setattr(
        "story_video_agent_v3.story_goal_video_repair._source_frames_match_decoded_video",
        lambda **kwargs: True,
    )
    video = tmp_path / "unit_source.mp4"
    video.write_bytes(b"fake")
    authorized = validate_goal_video_review(
        review=review, issue=gap,
        source_sha=sha, source_mp4=video,
    )
    assert authorized["ok"]
    old = _edl()
    old.insert(3, {
        "segment_id": "existing", "role": "unrelated_cut",
        "media_in": 148., "media_out": 151.,
    })
    result = apply_video_verified_goal_repair(
        edl=old, issue=gap, validated=authorized,
    )
    assert not result["applied"]
    assert result["reason"] == "new_window_overlaps_existing_footage"
    assert result["edl"] == old


def test_no_matching_scoreboard_allows_video_verified_generic_story_goal(
    tmp_path, monkeypatch,
):
    """Different story templates can omit scoreboard beats altogether."""
    gap, sha, review = _review(tmp_path)
    monkeypatch.setattr(
        "story_video_agent_v3.story_goal_video_repair._source_frames_match_decoded_video",
        lambda **kwargs: True,
    )
    video = tmp_path / "unit_source.mp4"
    video.write_bytes(b"fake")
    authorized = validate_goal_video_review(
        review=review, issue=gap, source_sha=sha, source_mp4=video,
    )
    edl = [x for x in _edl() if x["segment_id"] != "eq_board"]
    out = apply_video_verified_goal_repair(
        edl=edl, issue=gap, validated=authorized,
    )
    assert out["applied"] is True
    assert out["new_role"] == "score_change_goal_action"
    assert out["placement_basis"] == "source_chronology_no_template_scoreboard"
    assert [r["segment_id"] for r in out["edl"]][3] == out["new_segment_id"]
    row = out["edl"][3]
    assert row["narrative_fit_status"] == "UNVERIFIED_PENDING_RENDERED_VIDEO_REVIEW"
    assert row["agent_auto_verified"] is False
    assert out["does_not_claim_story_improvement"]


def test_generic_scoreboard_role_does_not_require_template_prefix():
    gap = _issue()
    edl = [
        {"segment_id": "opening", "role": "opening", "media_in": 100, "media_out": 110},
        {"segment_id": "graphic", "role": "scoreboard", "media_in": 163, "media_out": 167},
        {"segment_id": "ending", "role": "ending_title"},
    ]
    validated = {
        "ok": True, "first_live_verified": True, "goal_video_semantic_verified": True,
        "media_in": 145.0, "media_out": 157.0, "action_sec": 153.0,
        "reviewer_type": "UNIT_TEST_ONLY",
    }
    out = apply_video_verified_goal_repair(edl=edl, issue=gap, validated=validated)
    assert out["applied"] is True
    assert out["placement_basis"] == "generic_scoreboard_beat"
    assert out["new_role"] == "score_change_goal_action"
    assert [r["segment_id"] for r in out["edl"]][-1] == "ending"


def test_source_chronology_fallback_preserves_trailing_title():
    gap = _issue()
    edl = [
        {"segment_id": "opening", "role": "opening", "media_in": 90, "media_out": 110},
        {"segment_id": "title", "role": "ending_title", "placeholder_sec": 3},
    ]
    validated = {
        "ok": True, "first_live_verified": True, "goal_video_semantic_verified": True,
        "media_in": 145.0, "media_out": 157.0, "action_sec": 153.0,
        "reviewer_type": "UNIT_TEST_ONLY",
    }
    out = apply_video_verified_goal_repair(edl=edl, issue=gap, validated=validated)
    assert out["applied"] is True
    assert [r["segment_id"] for r in out["edl"]] == [
        "opening", out["new_segment_id"], "title",
    ]


def test_goal_coverage_confirmed_state_still_enters_video_repair():
    gap = _issue()
    confirmed = {**gap, "diagnosis_status": "CONFIRMED_STORY_DEFECT"}
    assert [x["issue_id"] for x in goal_coverage_issues({"issues": [confirmed]})] == [
        gap["issue_id"],
    ]
    assert goal_coverage_issues({"issues": []}) == []


def test_generic_insertion_refuses_story_without_any_media_anchor():
    gap = _issue()
    validated = {
        "ok": True, "first_live_verified": True, "goal_video_semantic_verified": True,
        "media_in": 145.0, "media_out": 157.0, "action_sec": 153.0,
        "reviewer_type": "UNIT_TEST_ONLY",
    }
    out = apply_video_verified_goal_repair(
        edl=[{"segment_id": "title", "role": "opening_title"}],
        issue=gap, validated=validated,
    )
    assert out["applied"] is False
    assert out["reason"] == "no_source_chronology_anchor_in_story"


def test_localization_queue_skips_if_no_gap(tmp_path):
    report = prepare_source_video_goal_queue(
        diagnosis={"issues": []}, source_mp4=tmp_path / "nonexistent.mp4",
        events_path=None, out_dir=tmp_path / "queue",
    )
    assert report["issues"] == []
    assert report["status"] == "NO_GOAL_GAP_ISSUES"
    assert (tmp_path / "queue/source_goal_video_review_queue.json").is_file()
    assert report["zero_http"] is True


def test_source_video_review_external_mode_is_not_autonomous(tmp_path, monkeypatch):
    gap, sha, review = _review(tmp_path)
    monkeypatch.setattr(
        "story_video_agent_v3.story_goal_video_repair._source_frames_match_decoded_video",
        lambda **kwargs: True,
    )
    review_dir = tmp_path / "external"
    review_dir.mkdir()
    (review_dir / f"{gap['issue_id']}.json").write_text(
        json.dumps(review), encoding="utf-8",
    )
    video = tmp_path / "unit_source.mp4"
    video.write_bytes(b"fake")
    out = repair_goal_coverage_from_video_reviews(
        edl=_edl(), diagnosis={"issues": [gap]},
        source_sha=sha, review_dir=review_dir, source_mp4=video,
    )
    assert out["changed"] is True
    assert out["input_review_mode"] == "EXTERNALLY_SUPPLIED_VIDEO_REVIEW"
    assert out["candidate_quality_improved"] == "UNVERIFIED"
    assert out["release_authorized"] is False
    assert not next(
        r for r in out["edl"] if r.get("goal_coverage_repair")
    )["agent_auto_verified"]


def test_provider_probe_does_not_call_api_when_budget_insufficient(tmp_path):
    from story_video_agent_v3.story_goal_video_repair import (
        observe_source_goal_video_with_shared_vlm,
    )
    class NoHttpApi:
        pass
    # provider_usage reads .stats in the real runtime; monkeypatch its read
    # so this test can enforce budget without network setup.
    from story_video_agent_v3 import story_paid_eval

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            story_paid_eval, "provider_usage",
            lambda api: {"http_attempts": 4, "est_cost_usd_real": 0.01},
        )
        result = observe_source_goal_video_with_shared_vlm(
            queue={"issues": []}, source_mp4=tmp_path / "missing.mp4",
            api=NoHttpApi(), out_dir=tmp_path / "probe",
            max_calls=5, max_cost_usd=0.10,
        )
    assert result["n_real_vlm_calls"] == 0
    assert result["status"] == "SKIPPED_UNAUTHORIZED_OR_INSUFFICIENT_BUDGET"


def test_existing_p13_localizer_reused_without_gold_or_paid_api(tmp_path, monkeypatch):
    issue = _issue()
    video = tmp_path / "source.mp4"
    video.write_bytes(b"fake_football_source_unit_only")
    events = tmp_path / "original_events.json"
    events.write_text(json.dumps({"events": []}), encoding="utf-8")
    called = {}

    def fake_localizer(**kwargs):
        called.update(kwargs)
        return {
            "audits": [{
                "candidate_id": "sample_1",
                "clip_path": str(tmp_path / "sample.mp4"),
                "media_in": 145.0, "media_out": 157.0,
                "frame_paths": [str(tmp_path / "frame.jpg")],
                "semantic_label": "unresolved",
                "verification_status": "unresolved",
            }],
        }

    monkeypatch.setattr(
        "story_video_agent_v3.first_live_localize.run_first_live_localization",
        fake_localizer,
    )
    report = prepare_source_video_goal_queue(
        diagnosis={"issues": [issue]},
        source_mp4=video, events_path=events,
        out_dir=tmp_path / "queue", max_issues=1,
    )
    assert called["video"] == video
    assert called["events_path"] == events
    assert called.get("human_review_by_candidate") in (None, {})
    assert called["skip_ocr"] is False  # score confirmation may lag the action
    assert called["historical_clues"] == []
    assert report["issues"][0]["status"] == "SOURCE_CLIPS_READY_UNVERIFIED"
    assert report["issues"][0]["auto_edl_insert_authorized"] is False


def test_real_source_video_semantic_probe_remains_observation_only(
    tmp_path, monkeypatch,
):
    from story_video_agent_v3.story_goal_video_repair import (
        observe_source_goal_video_with_shared_vlm,
    )
    from story_video_agent_v3 import story_paid_eval
    from story_video_agent_v3 import remote_vlm_verify

    class FakeSharedApi:
        calls = 0

    api = FakeSharedApi()
    monkeypatch.setattr(
        story_paid_eval, "provider_usage",
        lambda got: {"http_attempts": got.calls, "est_cost_usd_real": 0.001},
    )
    source = tmp_path / "source.mp4"
    source.write_bytes(b"synthetic_source")
    clip = tmp_path / "continuous.mp4"
    clip.write_bytes(b"synthetic_clip")
    img_paths = []
    for i in range(2):
        p = tmp_path / f"f{i}.jpg"
        p.write_bytes(f"frame{i}".encode())
        img_paths.append(p)
    monkeypatch.setattr(
        remote_vlm_verify, "extract_dense_frames",
        lambda **kwargs: (None, [
            {"frame_id": f"f{i}", "path": str(p),
             "actual_media_sec": sec, "requested_media_sec": sec}
            for i, (p, sec) in enumerate(zip(img_paths, (149.0, 153.0)))
        ]),
    )

    def fake_call(**kwargs):
        assert kwargs["api"] is api
        api.calls += 1
        return {
            "ok": True, "provider_mode": "real",
            "vlm_inference": {
                "observed_shot": True,
                "observed_net": True,
                "live_or_replay": "live",
                "attacking_team_match": True,
                "claims_continuous_live": True,
                "shot_frame_ids": ["f0"],
                "net_frame_ids": ["f1"],
                "uncertain": [],
            },
        }

    monkeypatch.setattr(remote_vlm_verify, "call_goal_verify_round", fake_call)
    queue = {"issues": [{
        "status": "SOURCE_CLIPS_READY_UNVERIFIED",
        "issue_id": "goal_coverage_01_to_11",
        "score_before": [0, 1], "score_after": [1, 1],
        "score_confirmation_sec": 164.0,
        "continuous_candidate_clips": [{
            "candidate_id": "candidate",
            "clip_path": str(clip),
            "media_in": 145., "media_out": 157.,
        }],
    }]}
    out = observe_source_goal_video_with_shared_vlm(
        queue=queue, source_mp4=source, api=api,
        out_dir=tmp_path / "probe",
        max_calls=5, max_cost_usd=0.1,
    )
    assert api.calls == 1
    assert out["n_real_vlm_calls"] == 1
    assert out["status"] == "GOAL_SEMANTIC_CANDIDATE_OBSERVED_FIRST_LIVE_UNVERIFIED"
    assert out["first_live_verified"] is False
    assert out["goal_edl_insertion_authorized"] is False
    assert (tmp_path / "probe/source_goal_vlm_observation.json").is_file()
