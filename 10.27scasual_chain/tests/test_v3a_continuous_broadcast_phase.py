"""P16: positive phase proof for first airing, no real-video claim/no HTTP."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from story_video_agent_v3.continuous_broadcast_phase import (
    validate_continuous_broadcast_phase_proof,
)
from story_video_agent_v3.first_live_window_evidence import (
    validate_first_live_evidence_record,
)


def _case(tmp_path: Path):
    source = "a" * 64
    context = tmp_path / "fake_continuous_video.mp4"
    context.write_bytes(b"synthetic fixture: NOT A REAL BROADCAST")
    frames = []
    specs = [
        ("pre", 40., "CONTINUOUS_LIVE_PLAY"),
        ("shot", 49., "GOAL_SHOT_NET"),
        ("reaction", 54., "IMMEDIATE_LIVE_REACTION"),
        ("replay", 61., "SAME_ACTION_REPLAY_AFTER"),
    ]
    obs = []
    for fid, pts, phase in specs:
        p = tmp_path / (fid + ".jpg")
        p.write_bytes(("synthetic_" + fid).encode())
        frames.append({
            "frame_id": fid, "source_pts_sec": pts, "path": str(p),
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        })
        obs.append({
            "frame_id": fid, "source_pts_sec": pts, "phase": phase,
            "visible_cue": "fixture-only synthetic visual cue: " + phase,
        })
    phase = {
        "schema": "v3a_continuous_broadcast_phase_evidence_v1",
        "source_sha256": source,
        "source_pts_start": 45., "source_pts_end": 53.,
        "shot_sec": 49., "net_sec": 51.,
        "reviewer": {"kind": "HUMAN_CONTINUOUS_VIDEO_REVIEW",
                     "review_record_id": "FAKE_FOR_CONTROL_FLOW"},
        "continuous_context_clip": {
            "source_sha256": source,
            "source_pts_start": 35., "source_pts_end": 65.,
            "path": str(context),
            "sha256": hashlib.sha256(context.read_bytes()).hexdigest(),
        },
        "phase_observations": obs,
        "same_action_identity_evidence": "fake same action is shown later as replay",
        "prior_occurrence_reviewed": True,
        "prior_occurrence_method": "HUMAN_FULL_SOURCE_TIMELINE_REVIEW_FIXTURE",
        "prior_occurrence_result": "NO_EARLIER_SAME_ACTION",
        "timeline_context_complete": True,
    }
    return source, frames, phase


def _phase_check(case):
    sha, frames, phase = case
    return validate_continuous_broadcast_phase_proof(
        phase,
        source_sha=sha, pts_start=45., pts_end=53.,
        bound_frames={x["frame_id"]: x for x in frames},
    )


def test_structural_positive_is_only_fixture_not_real_video(tmp_path):
    result = _phase_check(_case(tmp_path))
    assert result["ok"] is True
    assert result["first_live_verified"] is True
    assert result["phase_provenance_verified"] is True


def test_first_live_label_without_positive_phase_proof_cannot_unlock_ledger(tmp_path):
    sha, frames, _ = _case(tmp_path)
    import json

    manifest = {"fake": True}
    binding = {
        "source_sha256": sha,
        "source_pts_start": 45., "source_pts_end": 53.,
        "frames": frames,
        "manifest": manifest,
        "manifest_digest": hashlib.sha256(
            json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
    }
    timeline = {
        "schema": "v3a_broadcast_timeline_review_v1",
        "source_sha256": sha,
        "source_pts_start": 45., "source_pts_end": 53.,
        "outcome": "FIRST_LIVE_VERIFIED",
        "method": "INVENTED_LABEL_WITHOUT_VIDEO_PROOF",
        "rationale": ["one reviewer said live"],
    }
    result = validate_first_live_evidence_record(
        binding, source_sha=sha,
        pts_start=45., pts_end=53., timeline_review=timeline,
    )
    assert result["binding_valid"] is True
    assert result["ok"] is False
    assert result["first_live_verified"] is False
    assert result["positive_phase_evidence_reason"] == (
        "missing_structured_continuous_phase_evidence"
    )


def test_real_model_phase_review_requires_actual_response_and_sent_frame_ids(tmp_path):
    case = _case(tmp_path)
    proof = case[2]
    import json

    raw = tmp_path / "phase_model_response.json"
    raw.write_text(json.dumps({
        "phase_observations": proof["phase_observations"],
    }), encoding="utf-8")
    proof["reviewer"] = {
        "kind": "REAL_VIDEO_MODEL_REVIEW",
        "provider_mode": "real",
        "model_id": "test-model-no-actual-call",
        "response_path": str(raw),
        "response_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
        "frame_ids_sent": [x["frame_id"] for x in case[1]],
    }
    assert _phase_check(case)["ok"], _phase_check(case)
    proof["reviewer"]["frame_ids_sent"].remove("replay")
    # Three sent frames fail the independent minimum-count check first.
    assert _phase_check(case)["reason"] == "model_phase_review_sent_frame_ids_missing"
    # Keep the minimum count satisfied, but replace the cited replay image
    # with an unrelated frame. This exercises the distinct citation-subset gate.
    proof["reviewer"]["frame_ids_sent"].append("unrelated_context_frame")
    assert _phase_check(case)["reason"] == "phase_citations_not_in_actual_model_inputs"
    proof["reviewer"]["frame_ids_sent"].remove("unrelated_context_frame")
    proof["reviewer"]["frame_ids_sent"].append("replay")
    assert _phase_check(case)["ok"] is True
    raw.write_text("changed_model_response", encoding="utf-8")
    assert _phase_check(case)["reason"] == "model_phase_review_raw_response_hash_mismatch"
    # Even a correctly hashed response must contain exactly the visual
    # observations copied into the asserted FIRST_LIVE timeline.
    altered = json.dumps({"phase_observations": []})
    raw.write_text(altered, encoding="utf-8")
    proof["reviewer"]["response_sha256"] = hashlib.sha256(raw.read_bytes()).hexdigest()
    assert _phase_check(case)["reason"] == "phase_observations_modified_after_model_response"


@pytest.mark.parametrize("mutator, expected", [
    (lambda p: p.update(prior_occurrence_method="phash_only"),
     "prior_occurrence_method_not_sufficient"),
    (lambda p: p.update(prior_occurrence_result="UNKNOWN"),
     "earlier_occurrence_not_excluded_by_independent_review"),
    (lambda p: p.update(timeline_context_complete=False),
     "full_context_coverage_not_attested"),
    (lambda p: p["phase_observations"][0].update(
        frame_id="invented_model_frame_id"),
     "phase_frame_not_uniquely_bound_to_model_input"),
    (lambda p: p["phase_observations"][3].update(
        phase="REPLAY_WITHIN_ACTION"),
     "explicit_replay_or_timeline_contradiction"),
    (lambda p: p["phase_observations"][3].update(
        source_pts_sec=49.0),
     "phase_frame_pts_mismatch"),
    (lambda p: p["continuous_context_clip"].update(
        sha256="b" * 64),
     "continuous_context_clip_hash_mismatch"),
    (lambda p: p["reviewer"].update(kind="REAL_VIDEO_MODEL_REVIEW"),
     "model_phase_review_not_real"),
])
def test_phase_evidence_negative_cases(tmp_path, mutator, expected):
    case = _case(tmp_path)
    mutator(case[2])
    result = _phase_check(case)
    assert result["ok"] is False
    assert result["reason"] == expected
