"""One explicitly authorized native-video broadcast phase observation.

Uses original-source continuous time-ordered MP4 (Qwen video_url) plus exact
source-PTS JPEG anchors, unlike the previous sparse-frame-only live opinions.
This module makes an *observation*, never a FIRST_LIVE certificate, timeline
review, evidence-store entry, EDL modification, or story-quality claim.

The adapter uses the existing shared capped ApiProvider; no extra credentials,
background HTTP, repeated searches, or independent Agent loop.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from story_video_agent.api_provider import _encode_image
from story_video_agent.vision_provider import _extract_json_obj

from story_video_agent.frames import FrameBudget, FrameStore
from story_video_agent.media import probe_video

from .story_paid_eval import provider_usage

SCHEMA = "v3a_native_video_broadcast_phase_observation_v1"
MAX_VIDEO_BYTES = 12 * 1024 * 1024
MAX_CONTEXT_SEC = 60.0


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(2 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write(path: Path, obj: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(obj), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _source_context_video(
    *, source_mp4: Path, begin: float, end: float, output: Path,
) -> Dict[str, Any]:
    """Compress original consecutive video frames; never splice disjoint shots."""
    if not 0 <= begin < end or end - begin > MAX_CONTEXT_SEC:
        return {"ok": False, "reason": "invalid_continuous_source_window"}
    output.parent.mkdir(parents=True, exist_ok=True)
    coarse = max(0.0, begin - 8.0)
    fine = begin - coarse
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{coarse:.3f}", "-i", str(source_mp4),
        "-ss", f"{fine:.3f}", "-t", f"{end-begin:.3f}",
        "-vf", "fps=5,scale=-2:360",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "29",
        "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart",
        str(output),
    ]
    try:
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "reason": type(exc).__name__}
    if run.returncode != 0 or not output.is_file() or output.stat().st_size < 4096:
        return {"ok": False, "reason": "native_context_ffmpeg_failed",
                "stderr_tail": (run.stderr or "")[-350:]}
    if output.stat().st_size > MAX_VIDEO_BYTES:
        return {"ok": False, "reason": "native_context_exceeds_payload_cap",
                "bytes": output.stat().st_size}
    return {
        "ok": True, "path": str(output),
        "sha256": _hash_file(output),
        "bytes": output.stat().st_size,
        "source_pts_start": begin, "source_pts_end": end,
        "video_input_mode": "native_video_url_data_uri",
        "temporal_continuity": "single_transcoded_original_source_interval",
        "audio_included": False, "fps_transcoded": 5,
        "claims_frame_accurate_video_model_timestamps": False,
    }


def extract_phase_anchored_frames(
    *,
    video: Path,
    shot: float,
    net: float,
    begin: float,
    end: float,
    out_dir: Path,
) -> list[Dict[str, Any]]:
    """Source-PTS anchors dense at the actual action, sparse in distant context.

    Uniform sampling across 40-55 seconds can entirely miss a 3-second goal.
    Reuse the deployed q3 FrameStore with source-PTS and byte-hash provenance,
    while a native VIDEO input provides the continuous temporal sequence.
    """
    offsets = (
        shot - 16., shot - 9., shot - 5., shot - 2.5,
        shot - 0.25, shot, shot + 0.65,
        net - 0.5, net, net + 0.7,
        net + 2.0, net + 4.5, net + 8.,
        net + 13., net + 20.,
    )
    times: list[float] = []
    for t in offsets:
        if not begin <= t <= end or not 0 <= t:
            continue
        if any(abs(t - prev) < 0.2 for prev in times):
            continue
        times.append(t)
    store = FrameStore(
        probe_video(Path(video)),
        out_dir=Path(out_dir),
        budget=FrameBudget(max_frames=len(times) + 2),
    )
    rows: list[Dict[str, Any]] = []
    for t in times:
        r = store.extract_at(
            t, gap_id="broadcast_phase_source_video",
            tool="original_source_phase_pts_anchor",
        )
        rows.append({
            "frame_id": r.frame_id,
            "path": str(r.path),
            "requested_media_sec": r.requested_media_sec,
            "actual_media_sec": r.actual_media_sec,
            "pts_status": r.pts_status,
        })
    return rows


def _phase_prompt(
    *, shot_sec: float, net_sec: float, begin: float, end: float,
    frames: list[Dict[str, Any]],
) -> str:
    ids = ", ".join(
        f"{f['frame_id']}@{float(f['actual_media_sec']):.3f}"
        for f in frames if f.get("actual_media_sec") is not None
    )
    return (
        "You are observing ONE continuous original football broadcast VIDEO "
        "(not an edited highlight), followed by source-video JPG anchor images. "
        "Treat the anchors as exact source PTS citations; the video was transcoded "
        "from a single uninterrupted source interval. "
        "Find whether the visible temporal sequence contains: (1) continuous "
        "live match play before a shot; (2) shot/ball entering net; "
        "(3) immediate live reaction; (4) optionally a later SAME-ACTION replay. "
        "Do not infer LIVE from scoreboards, no earlier perceptual hash hit, "
        "a single camera cut, or a close-up. Normal-speed replay or alternate "
        "camera replay can look identical to live: explicitly mark uncertainty. "
        "Do not infer absence of any earlier same-action broadcast from this clip. "
        "Do not invent frame IDs or source timestamps. For each observed phase "
        "cite ONE provided anchor frame_id and its exact supplied source_pts_sec, "
        "with a concrete visible cue, or OMIT uncertain phase entirely. "
        "Return strict JSON with keys: phase_observations (list of "
        "{phase,frame_id,source_pts_sec,visible_cue}), later_replay_status "
        "('SAME_ACTION_REPLAY_OBSERVED' or 'NO_REPLAY_OBSERVED_IN_REVIEWED_CONTEXT' "
        "or 'UNKNOWN'), post_action_reviewed_through_sec (number or null), "
        "same_action_identity_evidence (string or null), "
        "replay_or_slowmo_inside_action (true/false/null), "
        "timeline_uncertainties (list of strings). "
        "Phase labels must be CONTINUOUS_LIVE_PLAY, GOAL_SHOT_NET, "
        "IMMEDIATE_LIVE_REACTION, SAME_ACTION_REPLAY_AFTER. "
        f"Source interval [{begin:.3f},{end:.3f}] seconds; "
        f"shot ~{shot_sec:.3f}, net ~{net_sec:.3f}; "
        f"available exact source-JPG anchors: {ids}. "
        "This is observation ONLY, not a FIRST_LIVE verdict."
    )


def _validate_model_temporal_observation(
    parsed: Mapping[str, Any],
    *,
    sent: list[Dict[str, Any]],
    shot: float,
    net: float,
    clip_end: float,
) -> Dict[str, Any]:
    """Check actual cited source frames before recording any phase hypothesis.

    This is NOT the P16 FIRST_LIVE validator. It only checks temporal
    grounding of the model's proposed phases; no earlier occurrence review
    is performed or assumed. Lack of phase evidence remains UNRESOLVED.
    """
    ids = {str(f["frame_id"]): f for f in sent}
    rows = parsed.get("phase_observations")
    if not isinstance(rows, list) or not rows:
        return {"ok": False, "reason": "no_observed_temporal_phases"}
    core = {"CONTINUOUS_LIVE_PLAY", "GOAL_SHOT_NET", "IMMEDIATE_LIVE_REACTION"}
    allowed = core | {"SAME_ACTION_REPLAY_AFTER"}
    seen: Dict[str, float] = {}
    used_ids = set()
    for row in rows:
        if not isinstance(row, Mapping):
            return {"ok": False, "reason": "malformed_phase_observation"}
        phase = str(row.get("phase") or "")
        fid = str(row.get("frame_id") or "")
        if phase not in allowed or phase in seen:
            return {"ok": False, "reason": "unknown_or_duplicate_phase"}
        if fid not in ids or fid in used_ids:
            return {"ok": False, "reason": "uncited_or_reused_model_input_frame"}
        used_ids.add(fid)
        try:
            pts = float(row["source_pts_sec"])
        except (TypeError, ValueError, KeyError):
            return {"ok": False, "reason": "missing_model_phase_pts"}
        if not math.isfinite(pts) or abs(
            pts - float(ids[fid]["actual_media_sec"])
        ) > 0.05:
            return {"ok": False, "reason": "model_frame_pts_mismatch"}
        if len(str(row.get("visible_cue") or "").strip()) < 12:
            return {"ok": False, "reason": "insufficient_visible_phase_cue"}
        seen[phase] = pts
    if not core <= set(seen):
        return {"ok": False, "reason": "incomplete_live_goal_reaction"}
    pre, during, reaction = (
        seen["CONTINUOUS_LIVE_PLAY"], seen["GOAL_SHOT_NET"],
        seen["IMMEDIATE_LIVE_REACTION"],
    )
    if not (
        pre <= shot - 2.
        and shot - 0.5 <= during <= net + 0.5
        and net < reaction <= clip_end
    ):
        return {"ok": False, "reason": "phase_timing_inconsistent"}
    replay = seen.get("SAME_ACTION_REPLAY_AFTER")
    status = str(parsed.get("later_replay_status") or "UNKNOWN")
    if replay is not None:
        if (status != "SAME_ACTION_REPLAY_OBSERVED"
            or replay <= reaction or replay < net + 3.):
            return {"ok": False, "reason": "replay_phase_contradiction"}
    elif status == "SAME_ACTION_REPLAY_OBSERVED":
        return {"ok": False, "reason": "replay_claim_without_cited_frame"}
    if status == "NO_REPLAY_OBSERVED_IN_REVIEWED_CONTEXT":
        # Absence of a replay is bounded to what the model actually received.
        try:
            reviewed_to = float(parsed["post_action_reviewed_through_sec"])
        except (ValueError, TypeError, KeyError):
            return {"ok": False, "reason": "post_action_coverage_not_grounded"}
        if not (
            math.isfinite(reviewed_to)
            and net + 3. <= reviewed_to <= clip_end + 0.05
            and reviewed_to >= reaction
        ):
            return {"ok": False, "reason": "post_action_coverage_outside_video"}
    if parsed.get("replay_or_slowmo_inside_action") is True:
        return {"ok": False, "reason": "replay_inside_goal_action"}
    return {
        "ok": True,
        "reason": None,
        "phase_types": sorted(seen),
        "later_replay_status": status,
        "first_live_verified": False,
    }


def resolve_reverified_archived_goal_anchors(
    *,
    source_mp4: Path,
    source_sha: str,
    original_frame_manifest: Path,
    original_semantic_log: Path,
) -> Dict[str, Any]:
    """Reuse archived REAL Stage3 *only* after exact source redecoding.

    The original Qwen frame IDs, original JPEG bytes, requested/actual PTS,
    and entire source MP4 hash are revalidated. A prior report string alone
    has no authority. This returns shot/net source locations, NOT first-live
    evidence and cannot certify an editor candidate.
    """
    from .source_frame_provenance_cli import inspect_archived_real_goal_frames

    result: Dict[str, Any] = {
        "ok": False, "status": "ARCHIVED_REAL_GOAL_ANCHORS_UNRESOLVED",
        "first_live_verified": False, "paid_calls": 0,
    }
    try:
        audit = inspect_archived_real_goal_frames(
            source_mp4=Path(source_mp4),
            source_sha256=str(source_sha),
            frame_manifest_path=Path(original_frame_manifest),
            semantic_log_path=Path(original_semantic_log),
        )
        if not audit.get("stage3_source_frame_binding_valid"):
            result["reason"] = "archived_original_source_frames_not_reproduced"
            result["source_binding_audit"] = audit.get("source_frame_redecode")
            return result
        log = json.loads(Path(original_semantic_log).read_text(encoding="utf-8"))
        original = json.loads(Path(original_frame_manifest).read_text(encoding="utf-8"))
        inf = log.get("vlm_inference") or {}
        if not (
            log.get("provider_mode") == "real"
            and log.get("observation_only") is True
            and inf.get("observed_shot") is True
            and inf.get("observed_net") is True
        ):
            result["reason"] = "archived_real_goal_model_semantics_not_confirmed"
            return result
        by_id = {
            str(fr["frame_id"]): fr for fr in original.get("frames") or []
            if isinstance(fr, Mapping) and fr.get("frame_id")
        }
        shots = [str(i) for i in inf.get("shot_frame_ids") or []]
        nets = [str(i) for i in inf.get("net_frame_ids") or []]
        if not shots or not nets or any(i not in by_id for i in shots + nets):
            result["reason"] = "archived_model_source_frame_ids_mismatch"
            return result
        shot = min(float(by_id[i]["actual_media_sec"]) for i in shots)
        net = max(float(by_id[i]["actual_media_sec"]) for i in nets)
        if not (
            math.isfinite(shot) and math.isfinite(net)
            and 0 <= shot < net and net-shot <= 15.
        ):
            result["reason"] = "archived_goal_shot_net_time_inconsistent"
            return result
        result.update({
            "ok": True, "status": "ARCHIVED_REAL_GOAL_SOURCE_ANCHORS_REVALIDATED",
            "shot_sec": shot, "net_sec": net,
            "cited_shot_frame_ids": shots, "cited_net_frame_ids": nets,
            "source_sha256": source_sha,
            "source_manifest_sha256": audit.get("frame_manifest_sha256"),
            "original_semantic_log_sha256": audit.get("semantic_log_sha256"),
            "original_video_frame_redecode": "EXACT_BYTES_AND_PTS_MATCH",
            "first_live_verified": False, "paid_calls": 0,
        })
    except (OSError, ValueError, TypeError, KeyError) as exc:
        result["reason"] = type(exc).__name__ + ":" + str(exc)
    return result


def observe_native_broadcast_phase(
    *,
    source_mp4: Path,
    source_sha: str,
    shot_sec: float,
    net_sec: float,
    api: Any,
    out_dir: Path,
    approved: bool,
    max_calls: int,
    max_cost_usd: float,
) -> Dict[str, Any]:
    """At most ONE real native-video request after explicit caller approval.

    Presence of a real ApiProvider is not consent. Caller must also set
    approved=True; the E2E CLI exposes a separate opt-in switch.
    """
    dest = Path(out_dir) / "native_broadcast_phase_observation.json"
    result: Dict[str, Any] = {
        "schema": SCHEMA,
        "status": "SKIPPED_NOT_EXPLICITLY_AUTHORIZED",
        "observation_only": True, "first_live_verified": False,
        "edl_modified": False, "n_real_http_calls": 0,
        "prior_same_action_reviewed": False,
    }
    if not approved:
        _write(dest, result)
        return result
    before = provider_usage(api)
    attempts = int(before.get("http_attempts") or 0)
    estimated = float(before.get("est_cost_usd_real") or 0.0)
    if attempts >= int(max_calls) or estimated >= float(max_cost_usd):
        result["status"] = "SKIPPED_SHARED_PROVIDER_BUDGET_EXHAUSTED"
        _write(dest, result)
        return result
    try:
        video = Path(source_mp4)
        if not video.is_file() or _hash_file(video) != str(source_sha):
            result["status"] = "SOURCE_SHA_MISMATCH_OR_VIDEO_MISSING"
            _write(dest, result)
            return result
        shot, net = float(shot_sec), float(net_sec)
        if (not math.isfinite(shot) or not math.isfinite(net)
            or not 0 <= shot < net or net - shot > 15.0):
            result["status"] = "INVALID_SHOT_NET_ANCHORS"
            _write(dest, result)
            return result
        media = probe_video(video)
        begin = max(0., shot - 18.)
        end = min(float(media.duration_sec) - 0.15, net + 24.)
        if end < net + 3. or end - begin > MAX_CONTEXT_SEC:
            result["status"] = "INSUFFICIENT_CONTINUOUS_SOURCE_CONTEXT"
            _write(dest, result)
            return result

        clip = _source_context_video(
            source_mp4=video, begin=begin, end=end,
            output=Path(out_dir) / "original_context_native_360p.mp4",
        )
        if not clip.get("ok"):
            result.update(status="NATIVE_VIDEO_CLIP_PREPARATION_FAILED", clip=clip)
            _write(dest, result)
            return result
        frames = extract_phase_anchored_frames(
            video=video, shot=shot, net=net, begin=begin, end=end,
            out_dir=Path(out_dir) / "native_phase_source_anchors",
        )
        sent = [
            f for f in frames if f.get("actual_media_sec") is not None
            and f.get("pts_status") == "pts" and Path(str(f.get("path") or "")).is_file()
        ]
        if len(sent) < 3:
            result["status"] = "INSUFFICIENT_ACTUAL_SOURCE_PTS_ANCHORS"
            _write(dest, result)
            return result

        clip_bytes = Path(clip["path"]).read_bytes()
        video_url = "data:video/mp4;base64," + base64.b64encode(clip_bytes).decode("ascii")
        content: list[Dict[str, Any]] = [
            {"type": "text", "text": _phase_prompt(
                shot_sec=shot, net_sec=net, begin=begin, end=end, frames=sent,
            )},
            {"type": "video_url", "video_url": {"url": video_url}},
        ]
        for row in sent:
            content.extend([
                {"type": "text", "text": (
                    f"Original source anchor: frame_id={row['frame_id']}; "
                    f"source_pts_sec={float(row['actual_media_sec']):.3f}; "
                    f"requested_sec={float(row['requested_media_sec']):.3f}"
                )},
                {"type": "image_url", "image_url": {
                    "url": _encode_image(Path(row["path"]))
                }},
            ])
        response = api.chat(
            role="vision", stats_role="native_broadcast_phase",
            messages=[
                {"role": "system", "content": "Return only strict JSON. Uncertain is allowed."},
                {"role": "user", "content": content},
            ],
            temperature=0., allow_degraded_fallback=False,
            cache_key=None,
        )
        result["n_real_http_calls"] = max(
            0, int(provider_usage(api).get("http_attempts") or 0) - attempts
        )
        mode = str(response.get("provider_mode") or "")
        if mode != "real" or not response.get("content"):
            result["status"] = "NON_REAL_OR_EMPTY_VIDEO_MODEL_RESPONSE"
            _write(dest, result)
            return result
        raw_text = str(response["content"])
        raw_path = Path(out_dir) / "original_native_video_model_response.txt"
        raw_path.write_text(raw_text, encoding="utf-8")
        parsed = _extract_json_obj(raw_text)
        original_rows = parsed.get("phase_observations")
        temporal = _validate_model_temporal_observation(
            parsed, sent=sent, shot=shot, net=net, clip_end=end,
        )
        valid_rows = bool(temporal.get("ok"))
        result.update({
            "status": (
                "REAL_NATIVE_VIDEO_PHASE_OBSERVATION_ONLY"
                if valid_rows else "NATIVE_VIDEO_PHASE_CITATION_OR_TIMELINE_UNRESOLVED"
            ),
            "temporal_observation_validation": temporal,
            "model": response.get("model"),
            "provider_mode": "real",
            "source_sha256": source_sha,
            "source_window": [begin, end],
            "shot_sec": shot, "net_sec": net,
            "native_video_context": clip,
            "source_anchor_frames": [
                {**f, "sha256": _hash_file(Path(f["path"]))} for f in sent
            ],
            "frame_ids_sent": [f["frame_id"] for f in sent],
            "model_response_path": str(raw_path),
            "model_response_sha256": _hash_file(raw_path),
            "phase_observations": (
                original_rows if valid_rows else None
            ),
            "later_replay_status": (
                parsed.get("later_replay_status") if valid_rows else "UNKNOWN"
            ),
            "post_action_reviewed_through_sec": (
                parsed.get("post_action_reviewed_through_sec") if valid_rows else None
            ),
            "timeline_uncertainties": parsed.get("timeline_uncertainties"),
            "provider_usage": provider_usage(api),
            "native_video_model_input": True,
            "independent_prior_occurrence_check": "NOT_PERFORMED",
            "first_live_verified": False,
            "next_requirement": (
                "independent earlier same-action timeline review and source-bound "
                "broadcast phase verification; never promote on this result"
            ),
        })
    except Exception as exc:  # noqa: BLE001
        result.update(status="NATIVE_VIDEO_PHASE_OBSERVATION_UNRESOLVED",
                      error=type(exc).__name__)
        result["n_real_http_calls"] = max(
            0, int(provider_usage(api).get("http_attempts") or 0) - attempts
        )
    _write(dest, result)
    return result
