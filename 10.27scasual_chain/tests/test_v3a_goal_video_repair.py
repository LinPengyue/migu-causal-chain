"""V3-A goal-video repair gates: no external HTTP, no real match assertions.

A fake authenticated review tests only control-flow/safety; it is NOT a
claim that a model recognized a real football goal or first-broadcast shot.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from story_video_agent_v3.global_story_critic import detect_goal_coverage_hypotheses
from story_video_agent_v3.story_goal_video_repair import (
    _source_frames_match_decoded_video,
    apply_video_verified_goal_repair,
    assemble_live_goal_review_from_observation,
    audit_source_frame_redecode,
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


@pytest.fixture
def real_stage3_framestore_binding(tmp_path):
    """Tiny REAL FFmpeg/FrameStore extraction: q3 differs from q2 by design."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("actual_ffmpeg_and_ffprobe_required")
    from story_video_agent.frames import FrameStore, FrameBudget
    from story_video_agent.media import probe_video

    video = tmp_path / "synthetic_live_source.mp4"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25",
        "-t", "4.00", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(video),
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
    if proc.returncode != 0:
        pytest.skip("local ffmpeg lacks libx264:" + proc.stderr[-300:])
    store = FrameStore(
        probe_video(video), out_dir=tmp_path / "stage3_original_model_frames",
        budget=FrameBudget(max_frames=4),
    )
    records = [
        store.extract_at(t, gap_id="goal", tool="stage3_vlm_model_input")
        for t in (1.25, 2.25)
    ]
    if any(r.actual_media_sec is None or r.pts_status != "pts" for r in records):
        pytest.skip("test media PTS not available from local ffmpeg")
    sha = hashlib.sha256(video.read_bytes()).hexdigest()
    frames = [
        {
            "frame_id": r.frame_id, "path": str(r.path),
            "source_pts_sec": r.actual_media_sec,
            "requested_media_sec": r.requested_media_sec,
            "sha256": hashlib.sha256(Path(r.path).read_bytes()).hexdigest(),
        }
        for r in records
    ]
    return video, sha, {"frames": frames}


def test_historical_stage3_q3_extractor_exact_reproduction(
    real_stage3_framestore_binding,
):
    video, sha, binding = real_stage3_framestore_binding
    result = audit_source_frame_redecode(
        source_mp4=video, source_sha=sha, binding=binding,
    )
    assert result["ok"] is True, result
    assert result["source_sha_match"] is True
    assert result["first_live_verified"] is False
    assert result["visual_similarity_fallback_allowed"] is False
    assert all(x["matched"] for x in result["frames"])
    assert all(
        x["decoder_profile"] in (
            "stage3_framestore_q3_exact_bytes",
            "first_live_localize_q2_exact_bytes",
        )
        for x in result["frames"]
    )


def test_historical_stage3_frame_binding_rejects_wrong_source_sha(
    real_stage3_framestore_binding,
):
    video, _, binding = real_stage3_framestore_binding
    result = audit_source_frame_redecode(
        source_mp4=video, source_sha="f" * 64, binding=binding,
    )
    assert result["ok"] is False
    assert result["reason"] == "source_mp4_sha256_mismatch"


def test_historical_stage3_frame_binding_rejects_tampered_image(
    real_stage3_framestore_binding,
):
    video, sha, binding = real_stage3_framestore_binding
    frames = binding["frames"]
    Path(frames[0]["path"]).write_bytes(b"modified_after_model_call")
    result = audit_source_frame_redecode(
        source_mp4=video, source_sha=sha, binding=binding,
    )
    assert result["ok"] is False
    assert result["frames"][0]["reason"] == "stored_model_frame_sha256_mismatch"


def test_historical_stage3_frame_binding_rejects_wrong_pts(
    real_stage3_framestore_binding,
):
    video, sha, binding = real_stage3_framestore_binding
    frames = binding["frames"]
    frames[0]["source_pts_sec"] += 0.8
    result = audit_source_frame_redecode(
        source_mp4=video, source_sha=sha, binding=binding,
    )
    assert result["ok"] is False
    assert result["frames"][0]["matched"] is False


def test_archived_real_model_log_cli_binds_source_frames_without_first_live(
    real_stage3_framestore_binding, tmp_path,
):
    from story_video_agent_v3.source_frame_provenance_cli import (
        inspect_archived_real_goal_frames,
    )
    video, sha, binding = real_stage3_framestore_binding
    frame_manifest = tmp_path / "historical_frame_manifest.json"
    frame_manifest.write_text(json.dumps({"frames": [
        {
            "frame_id": fr["frame_id"],
            "path": fr["path"],
            "requested_media_sec": fr["requested_media_sec"],
            "actual_media_sec": fr["source_pts_sec"],
        }
        for fr in binding["frames"]
    ]}), encoding="utf-8")
    semantic_log = tmp_path / "automated_semantic_log.json"
    semantic_log.write_text(json.dumps({
        "provider_mode": "real",
        "observation_only": True,
        "vlm_inference": {
            "shot_frame_ids": [binding["frames"][0]["frame_id"]],
            "net_frame_ids": [binding["frames"][1]["frame_id"]],
        },
    }), encoding="utf-8")
    report = inspect_archived_real_goal_frames(
        source_mp4=video,
        source_sha256=sha,
        frame_manifest_path=frame_manifest,
        semantic_log_path=semantic_log,
    )
    assert report["stage3_source_frame_binding_valid"] is True, report
    assert report["n_original_model_frames"] == 2
    assert report["first_live_verified"] is False
    assert report["edl_modified"] is False
    assert report["api_calls"] == 0


def test_archived_real_model_log_cli_rejects_forged_cited_frame_ids(
    real_stage3_framestore_binding, tmp_path,
):
    from story_video_agent_v3.source_frame_provenance_cli import (
        inspect_archived_real_goal_frames,
    )
    video, sha, binding = real_stage3_framestore_binding
    frame_manifest = tmp_path / "historical_frame_manifest.json"
    frame_manifest.write_text(json.dumps({"frames": binding["frames"]}), encoding="utf-8")
    semantic_log = tmp_path / "fake_citation.json"
    semantic_log.write_text(json.dumps({
        "provider_mode": "real",
        "observation_only": True,
        "vlm_inference": {
            "shot_frame_ids": ["not_an_original_model_input"],
            "net_frame_ids": [binding["frames"][1]["frame_id"]],
        },
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="cited_model_frame_id_missing"):
        inspect_archived_real_goal_frames(
            source_mp4=video, source_sha256=sha,
            frame_manifest_path=frame_manifest,
            semantic_log_path=semantic_log,
        )


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


def test_confirmed_goal_defect_reaches_verified_mainchain_repair(
    tmp_path, monkeypatch,
):
    """A confirmed defect must not disappear before the existing repair executor."""
    gap, sha, review = _review(tmp_path)
    gap = {**gap, "diagnosis_status": "CONFIRMED_STORY_DEFECT"}
    monkeypatch.setattr(
        "story_video_agent_v3.story_goal_video_repair._source_frames_match_decoded_video",
        lambda **kwargs: True,
    )
    review_dir = tmp_path / "source_reviews"
    review_dir.mkdir()
    (review_dir / f"{gap['issue_id']}.json").write_text(
        json.dumps(review), encoding="utf-8",
    )
    video = tmp_path / "unit_source.mp4"
    video.write_bytes(b"fixture-only")
    # Different story template: no equalizer_scoreboard_anchor.
    old_edl = [x for x in _edl() if x["segment_id"] != "eq_board"]
    out = repair_goal_coverage_from_video_reviews(
        edl=old_edl, diagnosis={"issues": [gap]},
        source_sha=sha, review_dir=review_dir, source_mp4=video,
    )
    assert out["changed"] is True
    assert any(d["status"] == "EDL_REPAIR_APPLIED" for d in out["decisions"])
    new_rows = [r for r in out["edl"] if r.get("goal_coverage_repair")]
    assert len(new_rows) == 1
    assert new_rows[0]["role"] == "score_change_goal_action"
    assert new_rows[0]["agent_auto_verified"] is False
    assert out["candidate_quality_improved"] == "UNVERIFIED"
    assert out["release_authorized"] is False


def test_confirmed_goal_defect_without_review_never_mutates_edl(tmp_path):
    gap = {**_issue(), "diagnosis_status": "CONFIRMED_STORY_DEFECT"}
    old_edl = [x for x in _edl() if x["segment_id"] != "eq_board"]
    out = repair_goal_coverage_from_video_reviews(
        edl=old_edl, diagnosis={"issues": [gap]},
        source_sha="d" * 64, review_dir=None, source_mp4=tmp_path / "missing.mp4",
    )
    assert not out["changed"]
    assert out["edl"] == old_edl
    assert out["decisions"][0]["status"] == "UNRESOLVED"
    assert out["release_authorized"] is False



def _real_inprocess_observation(review, *, issue_id):
    semantic = review["video_semantic_observation"]
    return {
        "provider_mode": "real",
        "source_issue_id": issue_id,
        "source_window": [review["media_in"], review["media_out"]],
        "vlm_inference": semantic["vlm_inference"],
        "frame_records": [
            {
                "frame_id": f["frame_id"],
                "path": f["path"],
                "actual_media_sec": next(
                    b["source_pts_sec"] for b in review["first_live_evidence"]["frames"]
                    if b["frame_id"] == f["frame_id"]
                ),
            }
            for f in semantic["frames"]
        ],
        "model_response_audit": {
            "provider_mode": "real",
            "raw_response_excerpt": '{"observed_shot": true, "observed_net": true}',
        },
        "continuous_source_clip_path": semantic["continuous_source_clip_path"],
        "continuous_source_clip_sha256": semantic["continuous_source_clip_sha256"],
    }


def _evidence_store_for_review(review, sha):
    from story_video_agent_v3.first_live_window_evidence import window_key

    rec = {
        **review["first_live_evidence"],
        "broadcast_timeline_review": review["broadcast_timeline_review"],
    }
    return {"by_key": {window_key(sha, review["media_in"], review["media_out"]): rec}}


def test_inprocess_real_observation_can_reach_existing_goal_repair_executor(
    tmp_path, monkeypatch,
):
    """Control-flow fixture, not REAL model output or real first-broadcast proof."""
    gap, sha, review = _review(tmp_path)
    obs = _real_inprocess_observation(review, issue_id=gap["issue_id"])
    store = _evidence_store_for_review(review, sha)
    monkeypatch.setattr(
        "story_video_agent_v3.story_goal_video_repair._source_frames_match_decoded_video",
        lambda **kwargs: True,
    )
    vid = tmp_path / "fake_source.mp4"
    vid.write_bytes(b"synthetic")
    edl = [r for r in _edl() if r["segment_id"] != "eq_board"]
    result = repair_goal_coverage_from_video_reviews(
        edl=edl, diagnosis={"issues": [gap]}, source_sha=sha,
        review_dir=None, source_mp4=vid,
        video_observation=obs, first_live_evidence_store=store,
    )
    assert result["changed"] is True
    assert result["input_review_mode"] == "IN_PROCESS_REAL_VLM_OBSERVATION"
    assert result["decisions"][0]["status"] == "EDL_REPAIR_APPLIED"
    assert next(r for r in result["edl"] if r.get("goal_coverage_repair"))["agent_auto_verified"] is False
    assert result["candidate_quality_improved"] == "UNVERIFIED"
    assert result["release_authorized"] is False


def test_inprocess_observation_with_unknown_broadcast_phase_never_repairs(
    tmp_path, monkeypatch,
):
    gap, sha, review = _review(tmp_path)
    obs = _real_inprocess_observation(review, issue_id=gap["issue_id"])
    store = _evidence_store_for_review(review, sha)
    from story_video_agent_v3.first_live_window_evidence import window_key

    key = window_key(sha, review["media_in"], review["media_out"])
    store["by_key"][key]["broadcast_timeline_review"] = {
        **review["broadcast_timeline_review"], "outcome": "UNKNOWN"
    }
    monkeypatch.setattr(
        "story_video_agent_v3.story_goal_video_repair._source_frames_match_decoded_video",
        lambda **kwargs: True,
    )
    vid = tmp_path / "source.mp4"
    vid.write_bytes(b"synthetic")
    edl = _edl()
    result = repair_goal_coverage_from_video_reviews(
        edl=edl, diagnosis={"issues": [gap]}, source_sha=sha,
        review_dir=None, source_mp4=vid,
        video_observation=obs, first_live_evidence_store=store,
    )
    assert result["changed"] is False
    assert result["edl"] == edl
    assert result["decisions"][0]["status"] == "UNRESOLVED"
    assert result["release_authorized"] is False


def test_inprocess_model_observation_without_first_live_bundle_is_not_a_repair(
    tmp_path,
):
    gap, sha, review = _review(tmp_path)
    obs = _real_inprocess_observation(review, issue_id=gap["issue_id"])
    result = assemble_live_goal_review_from_observation(
        issue=gap, source_sha=sha, observation=obs, evidence_store={"by_key": {}},
    )
    assert result["review"] is None
    assert result["reason"] == "independent_first_live_evidence_missing_for_window"


def test_inprocess_model_frame_ids_must_match_actual_model_inputs(tmp_path):
    gap, sha, review = _review(tmp_path)
    obs = _real_inprocess_observation(review, issue_id=gap["issue_id"])
    obs["vlm_inference"] = {**obs["vlm_inference"], "shot_frame_ids": ["invented"]}
    result = assemble_live_goal_review_from_observation(
        issue=gap, source_sha=sha, observation=obs,
        evidence_store=_evidence_store_for_review(review, sha),
    )
    assert result["review"] is None
    assert result["reason"] == "source_model_frame_citations_missing_or_mismatched"


def test_inprocess_observation_rejects_mock_provider_and_missing_model_audit(tmp_path):
    gap, sha, review = _review(tmp_path)
    obs = _real_inprocess_observation(review, issue_id=gap["issue_id"])
    store = _evidence_store_for_review(review, sha)
    fake = {**obs, "provider_mode": "mock"}
    assert assemble_live_goal_review_from_observation(
        issue=gap, source_sha=sha, observation=fake, evidence_store=store,
    )["reason"] == "goal_video_observation_not_real_model"
    missing = {**obs, "model_response_audit": {}}
    assert assemble_live_goal_review_from_observation(
        issue=gap, source_sha=sha, observation=missing, evidence_store=store,
    )["reason"] == "real_video_model_response_audit_missing"


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
