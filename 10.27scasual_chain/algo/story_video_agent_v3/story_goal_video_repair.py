"""Missing-story-goal repair using independent source-video evidence.

Critic score transitions only OPEN a review queue. Neither an event Goal label
nor a nearby score confirmation may authorize a Goal EDL insertion. A repair
requires a source-hash/PTS-bound frame pack, a distinct first-broadcast timeline
review, and a cited shot→net semantic video review. This module does not
contain or import any reference/Gold EDL or match-specific goal timestamp.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .first_live_window_evidence import validate_first_live_evidence_record
from .remote_vlm_verify import cross_check_visible_evidence
from .story_edl_safety import check_source_pts_monotonic

SCHEMA = "v3a_goal_video_repair_v1"


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def goal_coverage_issues(diagnosis: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [
        dict(x) for x in diagnosis.get("issues") or []
        if isinstance(x, Mapping)
        and str(x.get("category") or "") == "goal_coverage"
        and str(x.get("diagnosis_status") or "") in (
            "HYPOTHESIS_NEEDS_VIDEO", "CONFIRMED_STORY_DEFECT"
        )
    ]


def prepare_source_video_goal_queue(
    *,
    diagnosis: Mapping[str, Any],
    source_mp4: Path,
    events_path: Optional[Path],
    out_dir: Path,
    max_issues: int = 1,
    max_candidates_per_issue: int = 3,
    max_video_read_sec: float = 75.0,
) -> Dict[str, Any]:
    """Reuse P13 first_live_localize (no VLM, no human hints, zero HTTP).

    Generates continuous candidate clips and dense source frames. It NEVER
    returns a verified action, and cannot mutate EDL.
    """
    from .first_live_localize import run_first_live_localization

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    issues = goal_coverage_issues(diagnosis)
    rows: List[Dict[str, Any]] = []
    for issue in issues[:max(0, int(max_issues))]:
        iid = str(issue.get("issue_id") or "")
        task = {
            "score_before": issue.get("score_before"),
            "score_after": issue.get("score_after"),
            "score_confirmation_sec": issue.get("score_confirmation_sec"),
        }
        if task["score_confirmation_sec"] is None or not Path(source_mp4).is_file():
            rows.append({"issue_id": iid, "status": "MISSING_VIDEO_OR_SCORE_CONFIRMATION"})
            continue
        try:
            # The localization role is a neutral issue identifier, never a
            # storyboard role or a preview of the missing ground truth.
            result = run_first_live_localization(
                video=Path(source_mp4),
                role="goal_gap_" + iid[:80],
                task_row=task,
                out_dir=out_dir / iid,
                events_path=events_path,
                historical_clues=[],
                identity={"issue_id": iid, "evidence_type": "goal_action_search"},
                max_candidates=max_candidates_per_issue,
                max_video_read_sec=max_video_read_sec,
                # Critical for delayed TV score confirmation: P13's OCR
                # tightened first-after-score from the later event carrier,
                # keeping the original goal action within the candidate pool.
                skip_ocr=False,
            )
            rows.append({
                "issue_id": iid,
                "status": "SOURCE_CLIPS_READY_UNVERIFIED",
                "score_before": task["score_before"],
                "score_after": task["score_after"],
                "score_confirmation_sec": task["score_confirmation_sec"],
                "candidate_count": len(result.get("audits") or []),
                "continuous_candidate_clips": [
                    {
                        "candidate_id": a.get("candidate_id"),
                        "clip_path": a.get("clip_path"),
                        "media_in": a.get("media_in"),
                        "media_out": a.get("media_out"),
                        "frame_paths": a.get("frame_paths") or [],
                        "semantic_label": a.get("semantic_label"),
                        "first_live_status": a.get("verification_status"),
                    }
                    for a in (result.get("audits") or [])
                ],
                "no_goal_action_verified": True,
                "first_live_verified": False,
                "auto_edl_insert_authorized": False,
            })
        except Exception as exc:  # noqa: BLE001
            rows.append({
                "issue_id": iid,
                "status": "SOURCE_LOCALIZATION_FAILED",
                "error": f"{type(exc).__name__}:{exc}",
            })
    report = {
        "schema": SCHEMA,
        "status": "VIDEO_REVIEW_PENDING" if rows else "NO_GOAL_GAP_ISSUES",
        "source_video": str(source_mp4),
        "events_path": str(events_path) if events_path else None,
        "issues": rows,
        "zero_http": True,
        "no_oracle_used": True,
        "no_autonomous_goal_verification_claim": True,
    }
    _write(out_dir / "source_goal_video_review_queue.json", report)
    return report


def observe_source_goal_video_with_shared_vlm(
    *,
    queue: Mapping[str, Any],
    source_mp4: Path,
    api: Any,
    out_dir: Path,
    max_calls: int,
    max_cost_usd: float,
) -> Dict[str, Any]:
    """Optional, explicitly authorized REAL source VLM observation (one call).

    Reuses the caller's ApiProvider, so global Critic/goal observation/Planner
    share the SAME call/cost ceilings. Never creates a first-live certificate
    or emits an EDL mutation from a single sampled-frame VLM opinion.
    """
    from .story_paid_eval import provider_usage
    from .remote_vlm_verify import (
        call_goal_verify_round, cross_check_visible_evidence, extract_dense_frames,
    )

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result: Dict[str, Any] = {
        "schema": SCHEMA,
        "status": "SKIPPED_UNAUTHORIZED_OR_INSUFFICIENT_BUDGET",
        "observation_only": True,
        "first_live_verified": False,
        "goal_edl_insertion_authorized": False,
        "n_real_vlm_calls": 0,
    }
    before = provider_usage(api)
    attempts = int(before.get("http_attempts") or 0)
    spent = float(before.get("est_cost_usd_real") or 0.0)
    if attempts + 3 > int(max_calls) or spent >= float(max_cost_usd):
        _write(out_dir / "source_goal_vlm_observation.json", result)
        return result
    candidates = []
    for issue in queue.get("issues") or []:
        if not isinstance(issue, Mapping):
            continue
        if issue.get("status") != "SOURCE_CLIPS_READY_UNVERIFIED":
            continue
        conf = issue.get("score_confirmation_sec")
        for c in issue.get("continuous_candidate_clips") or []:
            if not isinstance(c, Mapping):
                continue
            p = Path(str(c.get("clip_path") or ""))
            if not p.is_file() or str(c.get("semantic_label") or "") in (
                "replay", "wrong_attacking_side", "post_goal_celebration"
            ):
                continue
            try:
                mi, mo = float(c["media_in"]), float(c["media_out"])
                delta = abs(float(conf) - min(mo, float(conf)))
            except (TypeError, ValueError, KeyError):
                continue
            candidates.append((delta, issue, c, mi, mo))
    if not candidates:
        result["status"] = "NO_LOCALIZED_VIDEO_CLIPS"
        _write(out_dir / "source_goal_vlm_observation.json", result)
        return result
    # Prefer a window near the score change; score proximity is only a
    # retrieval heuristic, not evidence that the goal is there.
    _, issue, candidate, mi, mo = min(candidates, key=lambda x: x[0])
    cid = str(candidate.get("candidate_id") or "candidate")
    goal_frames = []
    try:
        _, goal_frames = extract_dense_frames(
            video=Path(source_mp4),
            media_in=mi, media_out=mo,
            out_dir=out_dir / "dense_goal_frames",
            count=8,
            gap_id="goal_gap_" + str(issue.get("issue_id") or "")[:60],
            tool="source_goal_action_video_observe",
        )
        visual = call_goal_verify_round(
            api=api,
            frames=goal_frames,
            gap_id=str(issue.get("issue_id") or "goal_gap"),
            media_in=mi,
            media_out=mo,
            score_before=issue.get("score_before"),
            score_after=issue.get("score_after"),
            attacking_team_hint="scoring side indicated by score_before→score_after",
            round_name="v3a_goal_gap_source_semantic_probe",
        )
        if not visual.get("ok") or visual.get("provider_mode") != "real":
            result.update({
                "status": "VIDEO_SEMANTIC_UNRESOLVED",
                "error": visual.get("error"),
                "provider_mode": visual.get("provider_mode"),
            })
        else:
            clip = Path(str(candidate.get("clip_path") or ""))
            cross = cross_check_visible_evidence(
                vlm_inference=visual.get("vlm_inference"),
                frames=goal_frames,
                score_bounds={
                    "first_after_obs": {"media_sec": issue.get("score_confirmation_sec")},
                },
                media_in=mi,
                media_out=mo,
                continuous_clip_ok=clip.is_file(),
                continuous_clip_path=str(clip),
            )
            result.update({
                # Preserve the exact REAL model-input frame references for
                # subsequent source-video provenance checks. These fields do
                # not attest first broadcast or authorize any edit.
                "frame_records": [dict(f) for f in goal_frames],
                "continuous_source_clip_path": str(clip),
                "continuous_source_clip_sha256": (
                    hashlib.sha256(clip.read_bytes()).hexdigest()
                    if clip.is_file() else None
                ),
                "model_response_audit": {
                    "provider_mode": "real",
                    "raw_response_excerpt": visual.get("raw_response_excerpt"),
                    "normalized_evidence": visual.get("normalized_evidence"),
                    "cited_frame_ids": visual.get("cited_frame_ids"),
                    "round": "v3a_goal_gap_source_semantic_probe",
                },
                "status": (
                    "GOAL_SEMANTIC_CANDIDATE_OBSERVED_FIRST_LIVE_UNVERIFIED"
                    if cross.get("structurally_ready_for_automated_verify")
                    else "VIDEO_SEMANTIC_UNRESOLVED"
                ),
                "provider_mode": "real",
                "source_issue_id": issue.get("issue_id"),
                "candidate_id": cid,
                "source_window": [mi, mo],
                "frame_ids_sent": [f.get("frame_id") for f in goal_frames],
                "source_video_crosscheck": cross,
                "vlm_inference": visual.get("vlm_inference"),
                "model_raw_response_excerpt": visual.get("raw_response_excerpt"),
                "first_live_verified": False,
                "not_native_continuous_video_ingest": True,
                "next_requirement": (
                    "independent SHA/PTS-bound full broadcast-timeline review "
                    "and exact original source binding before authorization"
                ),
            })
    except Exception as exc:  # noqa: BLE001
        result.update({
            "status": "VIDEO_SEMANTIC_UNRESOLVED",
            "error": f"{type(exc).__name__}:{exc}",
        })
    after = provider_usage(api)
    result["n_real_vlm_calls"] = (
        int(after.get("http_attempts") or 0) - attempts
    )
    result["api_usage_after"] = after
    _write(out_dir / "source_goal_vlm_observation.json", result)
    return result


def _source_frames_match_decoded_video(
    *,
    source_mp4: Path,
    source_sha: str,
    binding: Mapping[str, Any],
) -> bool:
    """Re-decode original source PTS to reject self-hashed fabricated JPGs.

    A manifest SHA matching arbitrary local JPG bytes is not sufficient to
    prove those JPGs came from the named original football video.
    """
    from tempfile import TemporaryDirectory
    from .first_live_localize import extract_frame_accurate

    video = Path(source_mp4)
    if not video.is_file():
        return False
    digest = hashlib.sha256()
    with video.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != str(source_sha):
        return False
    frames = list(binding.get("frames") or [])
    if len(frames) < 2:
        return False
    with TemporaryDirectory(prefix="v3a_goal_redecode_") as tmp:
        for i, fr in enumerate(frames):
            if not isinstance(fr, Mapping):
                return False
            t = fr.get("source_pts_sec")
            if t is None:
                return False
            redecoded = extract_frame_accurate(
                video, float(t), Path(tmp) / f"source_{i}.jpg"
            )
            if not redecoded.get("ok") or str(redecoded.get("sha256")) != str(fr.get("sha256")):
                return False
    return True


def _valid_issue_binding(review: Mapping[str, Any], issue: Mapping[str, Any]) -> bool:
    return bool(
        str(review.get("issue_id") or "") == str(issue.get("issue_id") or "")
        and list(review.get("score_before") or []) == list(issue.get("score_before") or [])
        and list(review.get("score_after") or []) == list(issue.get("score_after") or [])
    )


def validate_goal_video_review(
    *,
    review: Optional[Mapping[str, Any]],
    issue: Mapping[str, Any],
    source_sha: str,
    source_mp4: Optional[Path] = None,
) -> Dict[str, Any]:
    """Independent action evidence AND first broadcast must pass.

    A manually edited JSON claiming shot/net=true, without real frame bytes
    and source-bound review, does not pass. This is an audit protocol; the
    origin of the semantic reviewer is recorded and not misreported as
    autonomous if it was a human.
    """
    fail = lambda why: {
        "ok": False, "status": "UNRESOLVED", "reason": why,
        "first_live_verified": False, "goal_video_semantic_verified": False,
    }
    if not isinstance(review, Mapping) or not _valid_issue_binding(review, issue):
        return fail("missing_or_mismatched_issue_and_score_transition")
    if str(review.get("source_sha256") or "") != str(source_sha) or len(source_sha) != 64:
        return fail("source_sha256_mismatch")
    try:
        mi, mo = float(review["media_in"]), float(review["media_out"])
    except (KeyError, TypeError, ValueError):
        return fail("invalid_source_clip_window")
    if not 0 <= mi < mo or mo - mi > 45:
        return fail("clip_duration_invalid_or_over_45s")
    bounds = issue.get("possible_action_interval") or {}
    try:
        lo, hi = float(bounds["media_in"]), float(bounds["media_out"])
        confirm = float(issue["score_confirmation_sec"])
    except (TypeError, ValueError, KeyError):
        return fail("invalid_score_search_bracket")
    # A real action has to occur before the scoreboard says the new score;
    # allow the candidate clip to extend outside the search bracket by
    # at most 15s for lead-in/celebration, without admitting a replay.
    if mo < lo - 15.0 or mi > hi + 5.0 or mi >= confirm - 0.5:
        return fail("candidate_outside_observed_score_transition_bracket")

    binding = review.get("first_live_evidence")
    timeline_review = review.get("broadcast_timeline_review")
    first_live = validate_first_live_evidence_record(
        binding if isinstance(binding, Mapping) else None,
        source_sha=source_sha, pts_start=mi, pts_end=mo,
        timeline_review=timeline_review if isinstance(timeline_review, Mapping) else None,
        require_files_exist=True,
    )
    if not first_live.get("ok"):
        return fail("no_bound_independent_first_broadcast_proof:" + str(first_live.get("reason")))
    if source_mp4 is None or not _source_frames_match_decoded_video(
        source_mp4=Path(source_mp4),
        source_sha=source_sha,
        binding=binding,
    ):
        return fail("source_frame_bytes_not_redecoded_from_original_mp4")

    observation = review.get("video_semantic_observation") or {}
    if not isinstance(observation, Mapping):
        return fail("missing_video_semantic_observation")
    provenance = str(observation.get("reviewer_type") or "")
    if provenance not in ("REAL_VIDEO_MODEL_REVIEW", "HUMAN_CONTINUOUS_VIDEO_REVIEW"):
        return fail("semantic_reviewer_unverifiable_or_fixture")
    if provenance == "REAL_VIDEO_MODEL_REVIEW" and not observation.get("model_response_audit"):
        return fail("real_model_review_missing_auditable_response")
    inference = observation.get("vlm_inference") or {}
    if not isinstance(inference, Mapping):
        return fail("missing_structured_shot_net_inference")
    rows = list(observation.get("frames") or [])
    if len(rows) < 2:
        return fail("insufficient_original_video_frame_evidence")
    validated_frames = []
    manifest_frames = {
        str(f.get("frame_id")): f
        for f in (binding.get("frames") or []) if isinstance(f, Mapping)
    }
    for row in rows:
        if not isinstance(row, Mapping):
            return fail("malformed_observation_frame")
        fid = str(row.get("frame_id") or "")
        bound = manifest_frames.get(fid)
        if bound is None:
            return fail("observation_frame_not_in_source_binding")
        if str(bound.get("path") or "") != str(row.get("path") or ""):
            return fail("observation_frame_path_binding_mismatch")
        t = bound.get("source_pts_sec")
        if t is None:
            return fail("bound_frame_missing_original_source_pts")
        validated_frames.append({
            "frame_id": fid,
            "path": str(bound.get("path")),
            "actual_media_sec": float(t),
        })
    semantic = cross_check_visible_evidence(
        vlm_inference=dict(inference),
        frames=validated_frames,
        score_bounds={
            "first_after_obs": {"media_sec": confirm},
        },
        media_in=mi,
        media_out=mo,
        continuous_clip_ok=bool(observation.get("continuous_source_clip_sha256")),
        continuous_clip_path=observation.get("continuous_source_clip_path"),
    )
    if not semantic.get("structurally_ready_for_automated_verify"):
        return fail("video_semantic_shot_net_or_live_crosscheck_incomplete")
    # Make continuous footage auditable: source clip hash must match actual bytes.
    clip = Path(str(observation.get("continuous_source_clip_path") or ""))
    clip_sha = str(observation.get("continuous_source_clip_sha256") or "")
    if not clip.is_file() or not clip_sha or (
        hashlib.sha256(clip.read_bytes()).hexdigest() != clip_sha
    ):
        return fail("continuous_clip_bytes_hash_mismatch")
    action_sec = (semantic.get("derived_times") or {}).get("net_sec")
    if action_sec is None or not lo - 5.0 <= float(action_sec) <= confirm - 0.5:
        return fail("net_action_pts_not_bounded_by_preconfirmation_score_state")
    return {
        "ok": True,
        "status": "ACTION_AND_FIRST_LIVE_VIDEO_BOUND",
        "issue_id": issue.get("issue_id"),
        "source_sha256": source_sha,
        "media_in": mi, "media_out": mo,
        "action_sec": float(action_sec),
        "shot_sec": (semantic.get("derived_times") or {}).get("shot_sec"),
        "reviewer_type": provenance,
        "first_live_verified": True,
        "goal_video_semantic_verified": True,
        "first_live_evidence": dict(binding),
        "broadcast_timeline_review": dict(timeline_review),
        "frame_refs": list(inference.get("shot_frame_ids") or [])
                      + list(inference.get("net_frame_ids") or []),
        "note": "Review-backed action, not inferred from scoreboard timestamps.",
    }


def apply_video_verified_goal_repair(
    *,
    edl: Sequence[Mapping[str, Any]],
    issue: Mapping[str, Any],
    validated: Mapping[str, Any],
) -> Dict[str, Any]:
    """Insert one previously absent goal action at chronological story position.

    This is a guarded *apply* stage, never a search heuristic. Existing goals,
    scoreboard rows and their order must be preserved. Final story-level video
    verification/acceptance remains the existing V3-A Verifier's decision.
    """
    result: Dict[str, Any] = {
        "applied": False, "reason": "unverified_goal_video_evidence",
        "edl": [dict(x) for x in edl],
        "new_segment_id": None,
    }
    if not validated.get("ok") or not (
        validated.get("first_live_verified")
        and validated.get("goal_video_semantic_verified")
    ):
        return result
    a, b = float(validated["media_in"]), float(validated["media_out"])
    rows = [dict(x) for x in edl]
    from .story_timeline import active_cut_rows

    active = active_cut_rows(rows)
    for r in active:
        try:
            ri, ro = float(r.get("media_in")), float(r.get("media_out"))
        except (TypeError, ValueError):
            continue
        if ri < b and a < ro:
            result["reason"] = "new_window_overlaps_existing_footage"
            return result

    # Prefer an existing score-confirmation beat if it can be placed in
    # chronological source order. Different story templates may not contain a
    # "*_scoreboard_anchor" role at all: in that case place the VIDEO-VERIFIED
    # goal in the unique chronological source gap, with a neutral goal role.
    # Story fit remains UNVERIFIED until the post-render video Verifier.
    score_confirm = float(issue.get("score_confirmation_sec") or 0)
    board_indices = []
    for idx, r in enumerate(rows):
        if r.get("include_in_cut", True) is False:
            continue
        if "scoreboard" not in str(r.get("role") or "").lower():
            continue
        try:
            board_start = float(r["media_in"])
        except (KeyError, TypeError, ValueError):
            continue
        if board_start >= b and abs(board_start - score_confirm) <= 35.0:
            board_indices.append((idx, r, board_start))

    insert_idx = None
    role = "score_change_goal_action"
    placement_basis = "source_chronology_no_template_scoreboard"
    if board_indices:
        idx, board, _ = min(
            board_indices, key=lambda item: abs(item[2] - score_confirm)
        )
        insert_idx = idx
        stem = str(board.get("role") or "")
        for suffix in ("_scoreboard_anchor", "_scoreboard"):
            if stem.endswith(suffix):
                stem = stem[:-len(suffix)]
                break
        if stem and stem != str(board.get("role") or ""):
            role = stem + "_goal_action"
            placement_basis = "paired_existing_scoreboard_beat"
        else:
            placement_basis = "generic_scoreboard_beat"

    if insert_idx is None:
        # A generic story may have a scoreboard-free climax, a tactical
        # turning point or an ending. Insert before the first later source
        # media cut, retaining non-media titles and the existing cut order.
        active_media = []
        for idx, r in enumerate(rows):
            if r.get("include_in_cut", True) is False:
                continue
            try:
                ri, ro = float(r["media_in"]), float(r["media_out"])
            except (KeyError, TypeError, ValueError):
                continue
            if ro > ri:
                active_media.append((idx, ri, ro))
        if not active_media:
            result["reason"] = "no_source_chronology_anchor_in_story"
            return result
        following = next(
            (idx for idx, ri, _ in active_media if ri >= b), None
        )
        insert_idx = (
            following if following is not None else active_media[-1][0] + 1
        )
    sid = "seg_goal_video_repair_" + str(issue["issue_id"])[:80]
    if any(str(r.get("segment_id")) == sid for r in rows):
        result["reason"] = "duplicate_goal_video_repair_id"
        return result
    row = {
        "segment_id": sid,
        "role": role,
        "media_in": round(a, 3), "media_out": round(b, 3),
        "goal_anchor_t_sec": round(float(validated["action_sec"]), 3),
        "include_in_cut": True, "is_replay": False,
        "shot_kind": "live",
        "goal_action_complete": True,
        "first_live_status": "FIRST_LIVE_VERIFIED",
        # External reviewed files, even when originating from a real model,
        # are not independently authenticated as an active Agent VLM call.
        "agent_auto_verified": False,
        "goal_coverage_repair": True,
        "repair_issue_id": issue.get("issue_id"),
        "placement_basis": placement_basis,
        "narrative_fit_status": "UNVERIFIED_PENDING_RENDERED_VIDEO_REVIEW",
        "evidence_status": "SOURCE_VIDEO_GOAL_SEMANTIC_AND_FIRST_LIVE_BOUND",
        "reviewer_type": validated.get("reviewer_type"),
        "validated_evidence": validated.get("first_live_evidence"),
        "broadcast_timeline_review": validated.get("broadcast_timeline_review"),
    }
    rows.insert(insert_idx, row)
    pts = check_source_pts_monotonic(rows)
    if not pts.get("ok"):
        result["reason"] = "repaired_edl_fails_source_pts_chronology"
        result["pts_breaks"] = pts.get("breaks") or []
        return result
    result.update({
        "applied": True,
        "reason": "video_evidence_bound_goal_edl_insert",
        "edl": rows,
        "new_segment_id": sid,
        "new_role": role,
        "placement_basis": placement_basis,
        "source_pts": [a, b],
        "action_sec": float(validated["action_sec"]),
        "reviewer_type": validated.get("reviewer_type"),
        "does_not_claim_story_improvement": True,
    })
    return result


def load_goal_review_for_issue(
    review_dir: Optional[Path], issue_id: str,
) -> Optional[Dict[str, Any]]:
    """Explicit source-video review input; never scans private evaluation dirs."""
    if review_dir is None:
        return None
    path = Path(review_dir)
    if not path.is_dir():
        return None
    safe = "".join(x for x in str(issue_id) if x.isascii() and (x.isalnum() or x in "_-"))
    if safe != str(issue_id):
        return None
    target = path / (safe + ".json")
    if not target.is_file():
        return None
    obj = json.loads(target.read_text(encoding="utf-8"))
    return obj if isinstance(obj, dict) else None


def assemble_live_goal_review_from_observation(
    *,
    issue: Mapping[str, Any],
    source_sha: str,
    observation: Optional[Mapping[str, Any]],
    evidence_store: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Bridge an agent's REAL model observation to the existing repair contract.

    This DOES NOT create first-broadcast proof. It only reuses an independently
    provided source-window binding and timeline review, with exact model-input
    frame IDs and paths. Validation/redecode still happens in the unmodified
    validate_goal_video_review path. No external/gold data are searched.
    """
    def reject(reason: str) -> Dict[str, Any]:
        return {"status": "UNRESOLVED", "reason": reason, "review": None}

    if not isinstance(observation, Mapping):
        return reject("no_agent_goal_video_observation")
    if str(observation.get("provider_mode") or "") != "real":
        return reject("goal_video_observation_not_real_model")
    if str(observation.get("source_issue_id") or "") != str(issue.get("issue_id") or ""):
        return reject("goal_video_observation_issue_mismatch")
    try:
        mi, mo = [float(t) for t in observation["source_window"]]
    except (KeyError, ValueError, TypeError):
        return reject("goal_video_observation_window_missing")
    if not (0 <= mi < mo <= mi + 45):
        return reject("goal_video_observation_window_invalid")
    inf = observation.get("vlm_inference")
    if not isinstance(inf, Mapping):
        return reject("goal_video_observation_inference_missing")
    audit = observation.get("model_response_audit")
    if not isinstance(audit, Mapping) or (
        str(audit.get("provider_mode") or "") != "real"
        or not str(audit.get("raw_response_excerpt") or "").strip()
    ):
        return reject("real_video_model_response_audit_missing")

    frame_records = observation.get("frame_records")
    if not isinstance(frame_records, list) or not frame_records:
        return reject("original_model_input_frame_records_missing")

    # A locally generated frame pack is merely a source binding. Its presence
    # does not assert FIRST_LIVE; that is independently verified downstream.
    from .first_live_window_evidence import window_key

    key = window_key(source_sha, mi, mo)
    by_key = (
        evidence_store.get("by_key")
        if isinstance(evidence_store, Mapping) else None
    )
    bound = by_key.get(key) if isinstance(by_key, Mapping) else None
    if not isinstance(bound, Mapping):
        return reject("independent_first_live_evidence_missing_for_window")
    timeline = bound.get("broadcast_timeline_review")
    if not isinstance(timeline, Mapping):
        return reject("independent_broadcast_timeline_review_missing")

    frame_by_id = {
        str(f.get("frame_id")): f for f in frame_records
        if isinstance(f, Mapping) and f.get("frame_id")
    }
    cited_ids = {
        str(i) for i in list(inf.get("shot_frame_ids") or [])
        + list(inf.get("net_frame_ids") or [])
    }
    if not cited_ids or not cited_ids <= set(frame_by_id):
        return reject("source_model_frame_citations_missing_or_mismatched")

    frames = []
    for fid, fr in frame_by_id.items():
        if not fr.get("path") or fr.get("actual_media_sec") is None:
            return reject("original_model_input_frame_path_or_pts_missing")
        frames.append({"frame_id": fid, "path": str(fr["path"])})

    clip_path = str(observation.get("continuous_source_clip_path") or "")
    clip_sha = str(observation.get("continuous_source_clip_sha256") or "")
    if not clip_path or not clip_sha:
        return reject("continuous_source_clip_hash_missing")

    # Do not copy model assertions into first-live status. Keep the timeline
    # object exactly as independently recorded; validator must cross-check it.
    review = {
        "issue_id": issue["issue_id"],
        "score_before": issue.get("score_before"),
        "score_after": issue.get("score_after"),
        "source_sha256": source_sha,
        "media_in": mi,
        "media_out": mo,
        "first_live_evidence": dict(bound),
        "broadcast_timeline_review": dict(timeline),
        "video_semantic_observation": {
            "reviewer_type": "REAL_VIDEO_MODEL_REVIEW",
            "model_response_audit": dict(audit),
            "frames": frames,
            "vlm_inference": dict(inf),
            "continuous_source_clip_path": clip_path,
            "continuous_source_clip_sha256": clip_sha,
        },
    }
    return {
        "status": "ASSEMBLED_FOR_INDEPENDENT_VALIDATION",
        "reason": None,
        "review": review,
    }


def repair_goal_coverage_from_video_reviews(
    *,
    edl: Sequence[Mapping[str, Any]],
    diagnosis: Mapping[str, Any],
    source_sha: str,
    review_dir: Optional[Path],
    source_mp4: Optional[Path] = None,
    video_observation: Optional[Mapping[str, Any]] = None,
    first_live_evidence_store: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Produce at most one video-authorized edit; no other Agent action mutated."""
    working = [dict(r) for r in edl]
    decisions = []
    used_external_review = False
    used_inprocess_observation = False
    for issue in goal_coverage_issues(diagnosis):
        review = load_goal_review_for_issue(review_dir, str(issue.get("issue_id") or ""))
        if review is not None:
            used_external_review = True
        bridge = None
        if review is None and video_observation is not None:
            bridge = assemble_live_goal_review_from_observation(
                issue=issue, source_sha=source_sha,
                observation=video_observation,
                evidence_store=first_live_evidence_store,
            )
            review = bridge.get("review")
            if review is not None:
                used_inprocess_observation = True
        validated = validate_goal_video_review(
            review=review, issue=issue, source_sha=source_sha,
            source_mp4=source_mp4,
        )
        if not validated.get("ok"):
            decisions.append({
                "issue_id": issue.get("issue_id"),
                "status": "UNRESOLVED",
                "reason": (
                    (bridge or {}).get("reason")
                    if review is None and bridge is not None
                    else validated.get("reason")
                ),
                "review_provided": review is not None,
                "observation_bridge_status": (bridge or {}).get("status"),
            })
            continue
        proposal = apply_video_verified_goal_repair(
            edl=working, issue=issue, validated=validated,
        )
        decisions.append({
            "issue_id": issue.get("issue_id"),
            "status": "EDL_REPAIR_APPLIED" if proposal.get("applied") else "UNRESOLVED",
            "reason": proposal.get("reason"),
            "reviewer_type": validated.get("reviewer_type"),
            "new_segment_id": proposal.get("new_segment_id"),
        })
        if proposal.get("applied"):
            working = proposal["edl"]
            break
    return {
        "schema": SCHEMA,
        "edl": working,
        "changed": working != [dict(r) for r in edl],
        "decisions": decisions,
        "auto_succeeded_without_video_proof": False,
        "release_authorized": False,
        "candidate_quality_improved": "UNVERIFIED",
        "input_review_mode": (
            "EXTERNALLY_SUPPLIED_VIDEO_REVIEW" if used_external_review
            else (
                "IN_PROCESS_REAL_VLM_OBSERVATION"
                if used_inprocess_observation
                else (
                    "IN_PROCESS_OBSERVATION_INCOMPLETE"
                    if video_observation is not None
                    else "NO_EXTERNAL_REVIEW"
                )
            )
        ),
    }
