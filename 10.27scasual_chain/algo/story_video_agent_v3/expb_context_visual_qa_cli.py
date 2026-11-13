"""Experiment B: source-bound football goal-context visual QA (images only).

A single-request, opt-in diagnostic. It NEVER changes EDL, BEST, or FIRST_LIVE.
Uses verified archived Stage3 goal anchors; independent from the paid E2E loop.
Do not use archived Stage3 inputs as held-out/full-E2E benchmark inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from story_video_agent.api_provider import ApiProvider, _encode_image, load_endpoint_configs
from story_video_agent.frames import FrameBudget, FrameStore
from story_video_agent.media import probe_video
from story_video_agent.vision_provider import _extract_json_obj

from .native_broadcast_observer import (
    match_archived_anchors_to_current_goal_issue,
    resolve_reverified_archived_goal_anchors,
)
from .story_paid_eval import provider_usage

SCHEMA = "v3a_expb_source_context_image_qa_v1"
ALLOWED = {
    "ACTIVE_PLAY_BEFORE", "GOAL_SHOT_NET", "IMMEDIATE_CELEBRATION",
    "POSSIBLE_PRE_GOAL_REPLAY", "PRE_GOAL_CELEBRATION",
    "LATER_SAME_ACTION_REPLAY", "MATCH_RESUMPTION",
}
# General-purpose goal-relative sampling; no fixture-specific timestamps.
OFFSETS_SHOT = (-24.0, -14.0, -7.0, -3.0, -0.3, 0.0)
OFFSETS_NET = (0.0, 1.0, 3.5, 7.0, 13.0, 23.0, 38.0)
MAX_FRAMES = len(OFFSETS_SHOT) + len(OFFSETS_NET)
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(2 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def extract_context_frames(*, video: Path, shot: float, net: float, out_dir: Path) -> list[dict]:
    media = probe_video(Path(video))
    times = []
    for t in [shot + x for x in OFFSETS_SHOT] + [net + x for x in OFFSETS_NET]:
        if 0 <= t <= float(media.duration_sec) - 0.15 and not any(abs(t - old) < 0.25 for old in times):
            times.append(t)
    if len(times) < 8 or shot - 3 < 0 or net + 7 > float(media.duration_sec):
        raise ValueError("insufficient_pre_goal_or_post_goal_video_context")
    store = FrameStore(
        media, out_dir=Path(out_dir),
        budget=FrameBudget(max_frames=len(times) + 2),
    )
    rows = []
    for t in times:
        r = store.extract_at(t, gap_id="expb_source_context", tool="source_pts_image_qa")
        actual = r.actual_media_sec
        if (
            actual is None or r.pts_status != "pts"
            or not math.isfinite(float(actual)) or abs(float(actual) - t) > 0.5
            or not Path(r.path).is_file()
        ):
            raise ValueError("frame_source_pts_not_reliably_decoded")
        rows.append({
            "frame_id": r.frame_id,
            "path": str(r.path),
            "requested_media_sec": float(t),
            "actual_media_sec": float(actual),
            "pts_status": r.pts_status,
            "sha256": sha256_file(Path(r.path)),
            "bytes": Path(r.path).stat().st_size,
        })
    if len({r["frame_id"] for r in rows}) != len(rows):
        raise ValueError("duplicate_context_frame_ids")
    if sum(r["bytes"] for r in rows) > MAX_IMAGE_BYTES:
        raise ValueError("source_context_frames_exceed_image_byte_cap")
    # Guard the relative zones, rather than claiming continuous video coverage.
    pts = [r["actual_media_sec"] for r in rows]
    if not (
        any(t <= shot - 3 for t in pts)
        and any(shot - 0.5 <= t <= net + 0.5 for t in pts)
        and any(net + 1 <= t <= net + 38.5 for t in pts)
    ):
        raise ValueError("required_context_zones_not_sampled")
    return rows


def context_prompt(*, shot: float, net: float, frames: Sequence[Mapping[str, Any]]) -> str:
    ids = ", ".join(
        "%s@%.3f" % (r["frame_id"], float(r["actual_media_sec"]))
        for r in frames
    )
    return (
        "You are given sparse, source-time-ordered STILL IMAGES from one original "
        "football broadcast. Images are NOT continuous video; do NOT infer unseen "
        "motions, same-action identity, no-replay, or first airing from frame gaps. "
        "Existing source-reverified Stage3 located a shot and net, but its 'live' "
        "opinion is NOT evidence of first broadcast. "
        "Your task is ONLY incremental match-broadcast context observation: "
        "Is there visibly ACTIVE PLAY before the goal, immediate celebration "
        "after it, later same-action replay clues, previous celebration/replay "
        "clues before it, or match resumption? State UNKNOWN if unclear. "
        "For each affirmative observation cite one provided frame_id, the exact "
        "source_pts_sec, and a concrete visible cue (not an assumption). "
        "Do not call camera cuts or unchanged score evidence of first live. "
        "Return strict JSON: {observations: [{phase,frame_id,source_pts_sec,"
        "visible_cue}], uncertainties: [strings], visual_limitations: [strings]}. "
        "Allowed phases: ACTIVE_PLAY_BEFORE, GOAL_SHOT_NET, "
        "IMMEDIATE_CELEBRATION, POSSIBLE_PRE_GOAL_REPLAY, "
        "PRE_GOAL_CELEBRATION, LATER_SAME_ACTION_REPLAY, MATCH_RESUMPTION. "
        "Omit unobserved phases; do not fabricate frame IDs. "
        "Goal shot approximately %.3f, net %.3f. Provided image frame IDs "
        "and source PTS: %s. This is not FIRST_LIVE verification."
        % (shot, net, ids)
    )


def validate_observations(
    parsed: Mapping[str, Any], *, frames: Sequence[Mapping[str, Any]],
    shot: float, net: float,
) -> dict:
    """Validate model citations and ordering, NOT visible truth or first airing."""
    rows = parsed.get("observations")
    if not isinstance(rows, list):
        return {"ok": False, "reason": "missing_observations_array", "status": "INSUFFICIENT_EVIDENCE"}
    by_id = {str(r["frame_id"]): r for r in frames}
    observed: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            return {"ok": False, "reason": "malformed_observation", "status": "INSUFFICIENT_EVIDENCE"}
        phase = row.get("phase")
        fid = str(row.get("frame_id") or "")
        if phase not in ALLOWED or phase in observed or fid not in by_id:
            return {"ok": False, "reason": "unknown_duplicate_or_uncited_phase", "status": "INSUFFICIENT_EVIDENCE"}
        try:
            t = float(row["source_pts_sec"])
        except (ValueError, TypeError, KeyError):
            return {"ok": False, "reason": "invalid_source_pts", "status": "INSUFFICIENT_EVIDENCE"}
        if (
            not math.isfinite(t) or abs(t - float(by_id[fid]["actual_media_sec"])) > 0.05
            or len(str(row.get("visible_cue") or "").strip()) < 12
        ):
            return {"ok": False, "reason": "uncertain_frame_citation_or_cue", "status": "INSUFFICIENT_EVIDENCE"}
        if (
            (phase in ("ACTIVE_PLAY_BEFORE", "POSSIBLE_PRE_GOAL_REPLAY", "PRE_GOAL_CELEBRATION") and t >= shot)
            or (phase == "GOAL_SHOT_NET" and not shot - 0.5 <= t <= net + 0.5)
            or (phase in ("IMMEDIATE_CELEBRATION", "LATER_SAME_ACTION_REPLAY", "MATCH_RESUMPTION") and t <= net)
        ):
            return {"ok": False, "reason": "phase_time_contradiction", "status": "INSUFFICIENT_EVIDENCE"}
        observed[str(phase)] = t
    if (
        observed.get("LATER_SAME_ACTION_REPLAY") is not None
        and observed.get("IMMEDIATE_CELEBRATION") is not None
        and observed["LATER_SAME_ACTION_REPLAY"] <= observed["IMMEDIATE_CELEBRATION"]
    ):
        return {"ok": False, "reason": "later_replay_before_reaction", "status": "INSUFFICIENT_EVIDENCE"}
    if {"POSSIBLE_PRE_GOAL_REPLAY", "PRE_GOAL_CELEBRATION"} & observed.keys():
        status = "REPLAY_SUSPECTED"
    elif {"ACTIVE_PLAY_BEFORE", "GOAL_SHOT_NET", "IMMEDIATE_CELEBRATION"} <= observed.keys():
        status = "LIVE_SEQUENCE_SUPPORTED"
    else:
        status = "INSUFFICIENT_EVIDENCE"
    return {
        "ok": True, "reason": None, "status": status,
        "phases_cited": sorted(observed),
        "phase_times_sec": observed,
        "model_reported_only": True,
        "first_live_verified": False,
    }


def run_context_qa(
    *,
    source_mp4: Path, source_sha256: str, frame_manifest: Path,
    semantic_log: Path, story_diagnosis: Path, out_dir: Path,
    execute_real: bool = False, approve_budget: bool = False,
    max_cost_usd: float = 0.10, api: Optional[Any] = None,
) -> dict:
    """Zero HTTP by default; one non-retrying image-only request when approved."""
    if out_dir.exists():
        raise ValueError("refuse_overwrite_existing_experiment_dir")
    if not (0 < max_cost_usd <= 0.10):
        raise ValueError("budget_must_be_at_most_0_10_usd")
    if execute_real != approve_budget:
        raise ValueError("paid_execution_requires_both_explicit_flags")
    out_dir.mkdir(parents=True)
    result: dict[str, Any] = {
        "schema": SCHEMA, "status": "INSUFFICIENT_EVIDENCE",
        "first_live_verified": False, "edl_modified": False,
        "best_modified": False, "n_real_http_calls": 0,
        "observation_only": True, "source_sha256": source_sha256,
        "input_mode": "source_pts_still_images_not_native_video",
        "total_budget_is_estimate_not_invoice_hard_cap": True,
    }
    try:
        if not source_mp4.is_file() or sha256_file(source_mp4) != source_sha256:
            raise ValueError("source_mp4_sha256_mismatch")
        archived = resolve_reverified_archived_goal_anchors(
            source_mp4=source_mp4, source_sha=source_sha256,
            original_frame_manifest=frame_manifest,
            original_semantic_log=semantic_log,
        )
        if not archived.get("ok"):
            raise ValueError("archived_stage3_source_reverification_failed:" + str(archived.get("reason")))
        diagnosis = json.loads(story_diagnosis.read_text(encoding="utf-8"))
        issue = match_archived_anchors_to_current_goal_issue(
            archived=archived, diagnosis=diagnosis,
        )
        if not issue.get("ok"):
            raise ValueError("archived_goal_issue_not_uniquely_bound:" + str(issue.get("reason")))
        shot, net = float(archived["shot_sec"]), float(archived["net_sec"])
        frames = extract_context_frames(
            video=source_mp4, shot=shot, net=net,
            out_dir=out_dir / "source_pts_context_frames",
        )
        prompt = context_prompt(shot=shot, net=net, frames=frames)
        result.update(
            "context_preflight_ready" and {
                "status": "READY_ZERO_HTTP_PREFLIGHT",
                "issue_id": issue["issue_id"],
                "shot_sec": shot, "net_sec": net,
                "archived_source_reverification": archived.get("status"),
                "frame_manifest_sha256": sha256_file(frame_manifest),
                "semantic_log_sha256": sha256_file(semantic_log),
                "story_diagnosis_sha256": sha256_file(story_diagnosis),
                "image_frames": frames,
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "first_live_verified": False,
            }
        )
        if not execute_real:
            return result
        if api is None:
            configs = load_endpoint_configs()
            if not configs["vision"].configured():
                raise ValueError("vision_endpoint_not_configured")
            configs["vision"] = replace(configs["vision"], max_retries=0)
            api = ApiProvider(
                force_mock=False, require_real=True, configs=configs,
                max_calls=1, max_cost_usd=max_cost_usd,
                required_roles=["vision"],
            )
        # With injected test providers, still insist upon a one-attempt cap.
        if int(api.max_calls) > 1 or int(api.configs["vision"].max_retries) != 0:
            raise ValueError("provider_not_limited_to_single_no_retry_call")
        if int(provider_usage(api).get("http_attempts") or 0) != 0:
            raise ValueError("provider_is_not_fresh")
        parts: list[dict] = [{"type": "text", "text": prompt}]
        for r in frames:
            parts.append({"type": "text", "text": (
                "source_frame_id=%s; source_pts_sec=%.3f" % (r["frame_id"], r["actual_media_sec"])
            )})
            parts.append({"type": "image_url", "image_url": {"url": _encode_image(Path(r["path"]))}})
        raw = api.chat(
            role="vision", stats_role="expb_context_visual_qa",
            messages=[
                {"role": "system", "content": "Only JSON. Evidence and UNKNOWN over guessing."},
                {"role": "user", "content": parts},
            ],
            temperature=0., cache_key=None, allow_degraded_fallback=False,
        )
        if raw.get("provider_mode") != "real" or not raw.get("content"):
            raise ValueError("model_response_not_real_or_empty")
        raw_path = out_dir / "original_model_response.txt"
        raw_path.write_text(str(raw["content"]), encoding="utf-8")
        result["raw_model_response_path"] = str(raw_path)
        result["raw_model_response_sha256"] = sha256_file(raw_path)
        result["model"] = raw.get("model")
        result["provider_mode"] = raw.get("provider_mode")
        result["response_audit"] = raw.get("response_audit")
        parsed = _extract_json_obj(str(raw["content"]))
        validation = validate_observations(parsed, frames=frames, shot=shot, net=net)
        result["validation"] = validation
        result["status"] = validation["status"]
        result["observations"] = parsed.get("observations") if validation["ok"] else None
        result["uncertainties"] = parsed.get("uncertainties")
        result["visual_limitations"] = parsed.get("visual_limitations")
    except Exception as exc:
        result["status"] = "INSUFFICIENT_EVIDENCE"
        result["blocked_or_failed_reason"] = type(exc).__name__ + ":" + str(exc)[:240]
    finally:
        if api is not None:
            result["n_real_http_calls"] = int(provider_usage(api).get("http_attempts") or 0)
            result["api_usage"] = provider_usage(api)
        write_json(out_dir / "expb_context_visual_qa_report.json", result)
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Experiment B source-PTS image context QA, offline unless explicitly opted in")
    p.add_argument("--source-mp4", required=True, type=Path)
    p.add_argument("--source-sha256", required=True)
    p.add_argument("--archived-frame-manifest", required=True, type=Path)
    p.add_argument("--archived-semantic-log", required=True, type=Path)
    p.add_argument("--story-diagnosis", required=True, type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--execute-real", action="store_true")
    p.add_argument("--i-approve-budget", action="store_true")
    p.add_argument("--max-cost-usd", type=float, default=0.10)
    args = p.parse_args(argv)
    result = run_context_qa(
        source_mp4=args.source_mp4, source_sha256=args.source_sha256,
        frame_manifest=args.archived_frame_manifest,
        semantic_log=args.archived_semantic_log,
        story_diagnosis=args.story_diagnosis,
        out_dir=args.out_dir, execute_real=args.execute_real,
        approve_budget=args.i_approve_budget,
        max_cost_usd=args.max_cost_usd,
    )
    print(json.dumps({
        "status": result["status"], "n_real_http_calls": result["n_real_http_calls"],
        "first_live_verified": False, "edl_modified": False,
        "report": str(args.out_dir / "expb_context_visual_qa_report.json"),
        "blocked_or_failed_reason": result.get("blocked_or_failed_reason"),
    }, ensure_ascii=False))
    return 0 if result["status"] in (
        "READY_ZERO_HTTP_PREFLIGHT", "LIVE_SEQUENCE_SUPPORTED",
        "REPLAY_SUSPECTED",
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main())
