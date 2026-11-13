"""Positive, source-bound FIRST_LIVE broadcast phase evidence protocol.

A phase review is a sequence of original-footage observations, NOT a single
VLM 'live' label, lack of a perceptual-hash match, or a camera-cut detector.
FIRST_LIVE can only be recommended after all cited frames and the continuous
context clip are source-bound, and a reviewer provides a coherent LIVE play ->
shot/net -> immediate reaction -> later SAME-action replay timeline.

This checker verifies the structure, citations, bytes and PTS; it does NOT
infer the visual meaning of a frame. That remains an independent continuous
broadcast reviewer, whose exact model/human provenance must be retained.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any, Dict, Mapping

PHASE_SCHEMA = "v3a_continuous_broadcast_phase_evidence_v1"

# Four distinct role labels require temporal, *positive* evidence.
REQUIRED_PHASES = (
    "CONTINUOUS_LIVE_PLAY",
    "GOAL_SHOT_NET",
    "IMMEDIATE_LIVE_REACTION",
    "SAME_ACTION_REPLAY_AFTER",
)
CONTRA_PHASES = {
    "REPLAY_BEFORE_ACTION",
    "REPLAY_WITHIN_ACTION",
    "SLOW_MOTION_WITHIN_ACTION",
    "EARLIER_SAME_ACTION_BROADCAST",
    "SOURCE_TIMELINE_DISCONTINUITY",
}


def _valid_hash(value: Any) -> bool:
    text = str(value or "").lower()
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text)


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_continuous_broadcast_phase_proof(
    review: Mapping[str, Any],
    *,
    source_sha: str,
    pts_start: float,
    pts_end: float,
    bound_frames: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Validate provenance + temporal phase narrative for FIRST_LIVE.

    This adds *positive* evidence requirements but does not independently
    classify pixels. VLM/human conclusions remain fallible, therefore failed,
    contradictory or incomplete proof always yields UNKNOWN. Test fixtures
    are not real-video validation.
    """
    def fail(reason: str) -> Dict[str, Any]:
        return {
            "ok": False, "reason": reason, "first_live_verified": False,
            "phase_provenance_verified": False,
        }

    if not isinstance(review, Mapping) or review.get("schema") != PHASE_SCHEMA:
        return fail("missing_structured_continuous_phase_evidence")
    if review.get("source_sha256") != source_sha or not _valid_hash(source_sha):
        return fail("phase_proof_source_sha_mismatch")
    try:
        a, b = float(review["source_pts_start"]), float(review["source_pts_end"])
        shot, net = float(review["shot_sec"]), float(review["net_sec"])
    except (ValueError, TypeError, KeyError):
        return fail("invalid_action_shot_net_pts")
    if not (
        abs(a - float(pts_start)) <= 0.05
        and abs(b - float(pts_end)) <= 0.05
        and a <= shot < net <= b
        and all(math.isfinite(v) for v in (a, b, shot, net))
    ):
        return fail("phase_action_pts_mismatch")

    reviewer = review.get("reviewer")
    if not isinstance(reviewer, Mapping):
        return fail("missing_independent_reviewer_audit")
    kind = str(reviewer.get("kind") or "")
    if kind == "REAL_VIDEO_MODEL_REVIEW":
        if str(reviewer.get("provider_mode") or "") != "real":
            return fail("model_phase_review_not_real")
        if not str(reviewer.get("model_id") or "").strip():
            return fail("model_phase_review_missing_model_id")
        if not _valid_hash(reviewer.get("response_sha256")):
            return fail("model_phase_review_missing_response_digest")
        original_response = Path(str(reviewer.get("response_path") or ""))
        if not original_response.is_file() or _sha_file(original_response) != str(
            reviewer["response_sha256"]
        ):
            return fail("model_phase_review_raw_response_hash_mismatch")
        sent = reviewer.get("frame_ids_sent")
        if not isinstance(sent, list) or len(sent) < 4:
            return fail("model_phase_review_sent_frame_ids_missing")
        if any(not isinstance(fid, str) or not fid for fid in sent):
            return fail("model_phase_review_sent_frame_ids_malformed")
    elif kind == "HUMAN_CONTINUOUS_VIDEO_REVIEW":
        if not str(reviewer.get("review_record_id") or "").strip():
            return fail("human_review_missing_record_id")
    else:
        return fail("unsupported_independent_reviewer_kind")

    clip = review.get("continuous_context_clip")
    if not isinstance(clip, Mapping):
        return fail("missing_continuous_context_clip")
    try:
        lo = float(clip["source_pts_start"])
        hi = float(clip["source_pts_end"])
    except (ValueError, TypeError, KeyError):
        return fail("invalid_context_clip_pts")
    # Requires pre-live buildup and a later replay of the same action.
    if not lo < shot - 3.0 or not hi > net + 3.0:
        return fail("insufficient_pre_or_post_action_coverage")
    if str(clip.get("source_sha256") or "") != source_sha:
        return fail("context_clip_wrong_original_source")
    clip_path = Path(str(clip.get("path") or ""))
    if not clip_path.is_file() or not _valid_hash(clip.get("sha256")):
        return fail("continuous_context_clip_missing_or_unhashed")
    if _sha_file(clip_path) != str(clip["sha256"]):
        return fail("continuous_context_clip_hash_mismatch")

    rows = review.get("phase_observations")
    if not isinstance(rows, list):
        return fail("missing_temporal_phase_observations")
    seen: Dict[str, Dict[str, Any]] = {}
    used_frame_ids = set()
    for item in rows:
        if not isinstance(item, Mapping):
            return fail("malformed_phase_observation")
        phase = str(item.get("phase") or "")
        if phase in CONTRA_PHASES or item.get("contradicts_first_live") is True:
            return fail("explicit_replay_or_timeline_contradiction")
        if phase not in REQUIRED_PHASES or phase in seen:
            return fail("duplicate_or_unknown_phase")
        fid = str(item.get("frame_id") or "")
        if not fid or fid in used_frame_ids or fid not in bound_frames:
            return fail("phase_frame_not_uniquely_bound_to_model_input")
        used_frame_ids.add(fid)
        bound = bound_frames[fid]
        if str(bound.get("frame_id") or "") != fid:
            return fail("bound_source_frame_id_mismatch")
        try:
            pt = float(item["source_pts_sec"])
            original_pt = float(bound["source_pts_sec"])
        except (ValueError, TypeError, KeyError):
            return fail("phase_frame_pts_missing")
        if not math.isfinite(pt) or abs(pt - original_pt) > 0.05:
            return fail("phase_frame_pts_mismatch")
        if not lo - 0.05 <= pt <= hi + 0.05:
            return fail("phase_frame_outside_continuous_context")
        explanation = str(item.get("visible_cue") or "").strip()
        if len(explanation) < 12:
            return fail("missing_positive_visual_phase_cue")
        seen[phase] = {"pts": pt, "frame_id": fid}

    if kind == "REAL_VIDEO_MODEL_REVIEW":
        # These are the ONLY images the independent phase reviewer actually saw.
        # Do not accept citations invented after the VLM call.
        if not used_frame_ids <= set(reviewer["frame_ids_sent"]):
            return fail("phase_citations_not_in_actual_model_inputs")
    if set(seen) != set(REQUIRED_PHASES):
        return fail("incomplete_pre_goal_reaction_replay_sequence")
    pre = seen["CONTINUOUS_LIVE_PLAY"]["pts"]
    during = seen["GOAL_SHOT_NET"]["pts"]
    reaction = seen["IMMEDIATE_LIVE_REACTION"]["pts"]
    replay = seen["SAME_ACTION_REPLAY_AFTER"]["pts"]
    if not (
        lo <= pre <= shot - 2.0
        and shot - 0.5 <= during <= net + 0.5
        and net < reaction < replay <= hi
        and replay >= net + 3.0
    ):
        return fail("phase_sequence_not_chronologically_consistent")

    if review.get("same_action_identity_evidence") is None or not str(
        review.get("same_action_identity_evidence") or ""
    ).strip():
        return fail("later_replay_not_explicitly_linked_to_same_goal_action")
    if review.get("prior_occurrence_reviewed") is not True:
        # A bounded negative pHash scan by itself must not assert first airing.
        return fail("earlier_same_action_broadcast_not_independently_reviewed")
    if review.get("prior_occurrence_method") in (
        None, "", "phash_only", "stage7_cuts_only",
        "no_matching_hash", "vlm_live_label_only",
    ):
        return fail("prior_occurrence_method_not_sufficient")
    if str(review.get("prior_occurrence_result") or "") != "NO_EARLIER_SAME_ACTION":
        return fail("earlier_occurrence_not_excluded_by_independent_review")
    if review.get("timeline_context_complete") is not True:
        return fail("full_context_coverage_not_attested")

    return {
        "ok": True,
        "reason": None,
        "first_live_verified": True,
        "phase_provenance_verified": True,
        "phase_method": "POSITIVE_CONTINUOUS_PHASE_AND_PRIOR_OCCURRENCE_REVIEW",
        "source_sha256": source_sha,
        "phase_frame_ids": [seen[k]["frame_id"] for k in REQUIRED_PHASES],
        "note": (
            "Positive original-broadcast sequence with independent reviewer audit. "
            "Not a mathematical guarantee; still requires original-frame redetection "
            "and story-level video verifier before EDL release."
        ),
    }
