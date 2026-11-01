"""Strict video-evidence upgrade gate for G2+.

Fail closed: status strings alone never yield video_verified / verified_first_live.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


AUTOMATED = "automated_video_verified"
HUMAN_REVIEWED = "human_video_reviewed"
PENDING = "pending_human_video_review"
NOT_VERIFIED = "NOT_VERIFIED"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def assert_identity_binding(
    *,
    expected: Dict[str, str],
    claimed: Dict[str, Any],
) -> Dict[str, Any]:
    need = ("match_id", "video_sha256", "events_sha256", "strip_provenance")
    missing = [k for k in need if not claimed.get(k)]
    if missing:
        return {"ok": False, "reason": "missing_identity", "missing": missing, "render_ready": False}
    mism = {
        k: {"expected": expected.get(k), "claimed": claimed.get(k)}
        for k in need
        if str(expected.get(k)) != str(claimed.get(k))
    }
    if mism:
        return {"ok": False, "reason": "identity_mismatch", "mismatches": mism, "render_ready": False}
    return {"ok": True, "render_ready": False}


def assert_temporal_order(
    *,
    media_in: Optional[float],
    shot_sec: Optional[float],
    net_sec: Optional[float],
    media_out: Optional[float],
    video_duration_sec: Optional[float] = None,
) -> Dict[str, Any]:
    vals = {
        "media_in": media_in,
        "shot_sec": shot_sec,
        "net_sec": net_sec,
        "media_out": media_out,
    }
    if any(v is None for v in vals.values()):
        return {"ok": False, "reason": "missing_pts_fields", "fields": vals, "render_ready": False}
    mi, sh, ne, mo = float(media_in), float(shot_sec), float(net_sec), float(media_out)
    if not (mi <= sh <= ne <= mo):
        return {
            "ok": False,
            "reason": "pts_order_violation",
            "order": [mi, sh, ne, mo],
            "render_ready": False,
        }
    if video_duration_sec is not None and (mi < 0 or mo > float(video_duration_sec) + 1e-3):
        return {
            "ok": False,
            "reason": "pts_out_of_video_range",
            "media_out": mo,
            "video_duration_sec": video_duration_sec,
            "render_ready": False,
        }
    return {"ok": True, "render_ready": False}


def assert_continuous_clip_and_frames(
    *,
    clip_path: Optional[Path],
    frame_paths: Sequence[Path],
    require_frame_hashes: bool = True,
) -> Dict[str, Any]:
    if not clip_path or not Path(clip_path).is_file() or Path(clip_path).stat().st_size < 1000:
        return {"ok": False, "reason": "missing_or_tiny_continuous_clip", "path": str(clip_path), "render_ready": False}
    frames = list(frame_paths or [])
    if len(frames) < 2:
        return {"ok": False, "reason": "need_at_least_two_frames", "n": len(frames), "render_ready": False}
    missing = [str(p) for p in frames if not Path(p).is_file()]
    if missing:
        return {"ok": False, "reason": "missing_frame_files", "missing": missing, "render_ready": False}
    hashes: List[Dict[str, str]] = []
    if require_frame_hashes:
        for p in frames:
            hashes.append({"path": str(p), "sha256": _sha256_file(Path(p))})
    return {"ok": True, "frame_hashes": hashes, "clip_sha256": _sha256_file(Path(clip_path)), "render_ready": False}


def evaluate_video_verification_claim(
    *,
    goal: Dict[str, Any],
    expected_identity: Dict[str, str],
    video_duration_sec: Optional[float] = None,
    allow_human_reviewed: bool = False,
) -> Dict[str, Any]:
    """Return gate decision. Never upgrades on status string alone."""
    claimed_status = str(goal.get("verification_status") or goal.get("status") or "")
    semantic_class = str(goal.get("semantic_verification_class") or NOT_VERIFIED)

    # Explicit anti-patterns
    if goal.get("live_or_replay") in ("replay", "REPLAY", "mixed", "ambiguous"):
        return {
            "ok": False,
            "level": "rejected_replay_or_ambiguous",
            "reason": "replay_or_ambiguous_not_first_live",
            "claimed_status": claimed_status,
            "render_ready": False,
        }
    if goal.get("cross_window_stitch") or goal.get("spliced_from_multiple_windows"):
        return {
            "ok": False,
            "level": "rejected_stitch",
            "reason": "cross_window_stitch_forbidden",
            "render_ready": False,
        }
    if goal.get("scoreboard_only") and not goal.get("shot_sec"):
        return {
            "ok": False,
            "level": "score_only",
            "reason": "scoreboard_only_insufficient",
            "render_ready": False,
        }

    id_gate = assert_identity_binding(
        expected=expected_identity,
        claimed=goal.get("identity") or goal.get("provenance") or {},
    )
    if not id_gate.get("ok"):
        return {**id_gate, "level": "rejected_identity", "claimed_status": claimed_status}

    order = assert_temporal_order(
        media_in=goal.get("media_in"),
        shot_sec=goal.get("shot_sec"),
        net_sec=goal.get("net_sec"),
        media_out=goal.get("media_out"),
        video_duration_sec=video_duration_sec,
    )
    if not order.get("ok"):
        return {**order, "level": "rejected_pts", "claimed_status": claimed_status}

    clip_gate = assert_continuous_clip_and_frames(
        clip_path=Path(goal["clip_path"]) if goal.get("clip_path") else None,
        frame_paths=[Path(p) for p in (goal.get("frame_paths") or [])],
    )
    if not clip_gate.get("ok"):
        return {**clip_gate, "level": "rejected_media_artifacts", "claimed_status": claimed_status}

    # Semantic class must be explicit and backed; status string alone is ignored.
    if semantic_class == AUTOMATED and goal.get("automated_semantic_log_path"):
        log_p = Path(str(goal["automated_semantic_log_path"]))
        if not log_p.is_file():
            return {
                "ok": False,
                "level": PENDING,
                "reason": "missing_automated_semantic_log",
                "render_ready": False,
            }
        return {
            "ok": True,
            "level": "video_verified",
            "semantic_verification_class": AUTOMATED,
            "note": "automated_video_verified with artifacts+log",
            "frame_hashes": clip_gate.get("frame_hashes"),
            "render_ready": False,
        }

    if allow_human_reviewed and semantic_class == HUMAN_REVIEWED and goal.get("human_review_record"):
        return {
            "ok": True,
            "level": "video_verified",
            "semantic_verification_class": HUMAN_REVIEWED,
            "note": "human_video_reviewed — must not be labeled as agent auto-success",
            "agent_auto_verified": False,
            "render_ready": False,
        }

    # Default: evidence pack may exist but semantics not verified.
    if claimed_status in ("verified_first_live", "verified_action", "video_verified"):
        return {
            "ok": False,
            "level": PENDING,
            "reason": "status_string_without_semantic_class_fail_closed",
            "claimed_status": claimed_status,
            "render_ready": False,
        }

    return {
        "ok": False,
        "level": PENDING if clip_gate.get("ok") else "score_only",
        "reason": "pending_human_or_automated_semantic_review",
        "semantic_verification_class": semantic_class or NOT_VERIFIED,
        "render_ready": False,
    }


def verification_level_for_edl(
    goal: Optional[Dict[str, Any]],
    *,
    expected_identity: Optional[Dict[str, str]] = None,
    video_duration_sec: Optional[float] = None,
) -> str:
    """EDL-facing level — never trusts raw verification_status alone."""
    if not goal:
        return "score_only"
    if not expected_identity:
        # Without identity context, only non-verified labels are possible.
        if goal.get("nearby_predicted_strip_ids") or goal.get("strip_chain_id"):
            return "predicted_strip_candidate"
        if goal.get("candidate_event_ids") or goal.get("event_id"):
            return "event_candidate"
        return "score_only"
    decision = evaluate_video_verification_claim(
        goal=goal,
        expected_identity=expected_identity,
        video_duration_sec=video_duration_sec,
    )
    if decision.get("ok") and decision.get("level") == "video_verified":
        return "video_verified"
    if decision.get("level") == PENDING:
        return "event_candidate"
    if "strip" in str(decision.get("level") or ""):
        return "predicted_strip_candidate"
    return "score_only" if decision.get("level") in ("score_only", "rejected_identity") else "event_candidate"
