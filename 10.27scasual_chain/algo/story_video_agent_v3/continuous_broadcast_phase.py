"""Positive, source-bound FIRST_LIVE broadcast phase evidence protocol.

A phase review is a sequence of original-footage observations, NOT a single
VLM 'live' label, lack of a perceptual-hash match, or a camera-cut detector.
FIRST_LIVE can only be recommended after all cited frames and the continuous
context clip are source-bound, and a reviewer provides an auditable LIVE play -> shot/net -> immediate
reaction timeline. A later replay is corroboration when present, never a
prerequisite: broadcasts can legitimately contain no replay.

This checker verifies the structure, citations, bytes and PTS; it does NOT
infer the visual meaning of a frame. That remains an independent continuous
broadcast reviewer, whose exact model/human provenance must be retained.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, Mapping

PHASE_SCHEMA = "v3a_continuous_broadcast_phase_evidence_v1"

# Three core phases must appear in both legitimate live-broadcast cases.
# The optional replay is a *corroborating observation*, not proof by absence.
CORE_PHASES = (
    "CONTINUOUS_LIVE_PLAY",
    "GOAL_SHOT_NET",
    "IMMEDIATE_LIVE_REACTION",
)
OPTIONAL_REPLAY_PHASE = "SAME_ACTION_REPLAY_AFTER"
ALLOWED_PHASES = set(CORE_PHASES) | {OPTIONAL_REPLAY_PHASE}
LATER_REPLAY_OBSERVED = "SAME_ACTION_REPLAY_OBSERVED"
LATER_REPLAY_NOT_OBSERVED = "NO_REPLAY_OBSERVED_IN_REVIEWED_CONTEXT"
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
        # Minimum is three distinct, cited core phases. Validate scalar
        # strings before set() so a malformed list cannot raise TypeError.
        if not isinstance(sent, list) or len(sent) < len(CORE_PHASES):
            return fail("model_phase_review_sent_frame_ids_missing")
        if any(not isinstance(fid, str) or not fid for fid in sent):
            return fail("model_phase_review_sent_frame_ids_malformed")
        if len(set(sent)) < len(CORE_PHASES):
            return fail("model_phase_review_sent_frame_ids_missing")
        # Prevent a post-hoc invented phase label from being attached to an
        # unrelated, but properly hashed, REAL model response.
        try:
            parsed_response = json.loads(original_response.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError, OSError):
            return fail("phase_model_response_not_auditable_json")
        if not isinstance(parsed_response, Mapping):
            return fail("phase_model_response_not_auditable_json")
        original_phase_rows = parsed_response.get("phase_observations")
        if not isinstance(original_phase_rows, list):
            return fail("model_response_lacks_original_phase_observations")
        if original_phase_rows != review.get("phase_observations"):
            return fail("phase_observations_modified_after_model_response")
        # The optional-replay decision must itself come from the actual model
        # output, not from a post-hoc operator claiming no replay was shown.
        if parsed_response.get("later_replay_status") != review.get(
            "later_replay_status"
        ):
            return fail("replay_status_modified_after_model_response")
        if parsed_response.get("post_action_reviewed_through_sec") != review.get(
            "post_action_reviewed_through_sec"
        ):
            return fail("post_action_coverage_modified_after_model_response")
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
    # Require meaningful lead-in and post-goal context, but NOT a later replay.
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
    replay_status = str(review.get("later_replay_status") or "")
    if replay_status not in (
        LATER_REPLAY_OBSERVED, LATER_REPLAY_NOT_OBSERVED
    ):
        return fail("later_replay_review_status_missing_or_invalid")
    seen: Dict[str, Dict[str, Any]] = {}
    used_frame_ids = set()
    for item in rows:
        if not isinstance(item, Mapping):
            return fail("malformed_phase_observation")
        phase = str(item.get("phase") or "")
        if phase in CONTRA_PHASES or item.get("contradicts_first_live") is True:
            return fail("explicit_replay_or_timeline_contradiction")
        if phase not in ALLOWED_PHASES or phase in seen:
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
    if not set(CORE_PHASES) <= set(seen):
        return fail("incomplete_live_play_goal_reaction_sequence")
    pre = seen["CONTINUOUS_LIVE_PLAY"]["pts"]
    during = seen["GOAL_SHOT_NET"]["pts"]
    reaction = seen["IMMEDIATE_LIVE_REACTION"]["pts"]
    if not (
        lo <= pre <= shot - 2.0
        and shot - 0.5 <= during <= net + 0.5
        and net < reaction <= hi
    ):
        return fail("phase_sequence_not_chronologically_consistent")

    replay_cited = OPTIONAL_REPLAY_PHASE in seen
    if replay_status == LATER_REPLAY_OBSERVED:
        if not replay_cited:
            return fail("later_replay_claim_without_cited_frame")
        replay = seen[OPTIONAL_REPLAY_PHASE]["pts"]
        if not (replay > reaction and replay >= net + 3.0):
            return fail("later_replay_not_after_live_reaction")
        if not str(review.get("same_action_identity_evidence") or "").strip():
            return fail("later_replay_not_explicitly_linked_to_same_goal_action")
    else:
        # Missing replay footage is never a negative-match certificate.
        # Require an explicit review of the source context after the action;
        # the earlier-occurrence proof remains strictly mandatory below.
        if replay_cited:
            return fail("replay_status_contradicts_observed_replay_frame")
        try:
            reviewed_to = float(review["post_action_reviewed_through_sec"])
        except (ValueError, TypeError, KeyError):
            return fail("post_action_review_window_missing")
        if not (
            math.isfinite(reviewed_to)
            and net + 3.0 <= reviewed_to <= hi + 0.05
            and reviewed_to >= reaction
        ):
            return fail("post_action_review_window_invalid")
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
        "phase_frame_ids": [
            seen[k]["frame_id"] for k in CORE_PHASES
        ] + ([seen[OPTIONAL_REPLAY_PHASE]["frame_id"]] if replay_cited else []),
        "later_replay_status": replay_status,
        "replay_corroboration_used": replay_cited,
        "note": (
            "Positive original-broadcast sequence with independent reviewer audit. "
            "Optional later replay is corroboration, never mandatory nor a "
            "first-airing proof by absence. Not a mathematical guarantee; "
            "still requires original-frame redetection "
            "and story-level video verifier before EDL release."
        ),
    }
