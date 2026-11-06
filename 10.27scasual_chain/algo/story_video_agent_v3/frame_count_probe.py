#!/usr/bin/env python3
"""V3-A opening-goal frame-count probe (4 historical / 8 / 16).

Independent of run_self_revise() sampling. Historical 4-frame Qwen responses are
reused offline. Only the 8-frame and 16-frame arms may spend real Vision HTTP
(max 2 calls total). DeepSeek is never called.

Sampling must NOT use strip_gold.json or human goal timestamps.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from story_video_agent.api_provider import (
    COST_DISCLAIMER,
    ApiCallError,
    ApiConfigError,
    ApiProvider,
    _estimate_cost,
    load_endpoint_configs,
)
from story_video_agent.frames import FrameBudget, FrameStore
from story_video_agent.media import probe_video
from story_video_agent.vision_provider import _extract_json_obj

from .vlm_evidence_semantics import (
    classify_goal_action_evidence,
    persist_visible_model_output,
)

SCHEMA = "v3a_frame_count_probe_v1"
EXPECTED_VIDEO_SHA256 = (
    "a66147f79609c8fbf831a8bd29de4c6d7f746b314b2b18a88ffb1fc5f319da9c"
)
DEFAULT_VIDEO = Path("/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4")
WINDOW = {"start": 1325.123, "end": 1347.123}
# Historical actual PTS from prior real runs (byte-identical frames across OLD/NEW).
HIST_ACTUAL_PTS = [1334.64, 1336.36, 1337.76, 1339.16]
HIST_REQUESTED_PTS = [1334.623, 1336.323, 1337.723, 1339.123]
HIST_FRAME_NAMES = [
    "f_0000_1334623.jpg",
    "f_0001_1336323.jpg",
    "f_0002_1337723.jpg",
    "f_0003_1339123.jpg",
]
OLD_RUN = Path(
    "/data2/lpy1/_story_va_outputs/v3/plan2/A_one_round_opening_20261106_133900"
)
NEW_RUN = Path(
    "/data2/lpy1/_story_va_outputs/v3/plan2/A_post_vlm_real_20261106_151951"
)
# Soft estimate budget for THIS probe only (not a vendor hard invoice cap).
MAX_COST_USD = 0.05
MAX_VISION_HTTP = 2
MAX_COMPLETION_TOKENS = 2048
# Conservative image-token scaling from historical 4-frame prompt_tokens=8616.
HIST_PROMPT_TOKENS_4 = 8616
HIST_TEXT_TOKEN_EST = 700
MIN_SEP_SEC = 1.0

PROBE_PROMPT = """You are inspecting football broadcast frames for ONE candidate goal-action window.
Describe only what is visible. Reply with STRICT JSON only (no markdown).

Window (program media_sec): [{start:.3f}, {end:.3f}]
EDL segment under inspection: seg_opponent_opening_goal_action
Frame bindings are provided as text before each image; use those frame_id values.

Field meanings (do NOT collapse):
- observed_shot: a shot attempt is visible in the frames
- observed_net / goalmouth_or_net_visible: goalmouth/net structure visible ONLY
  (NOT goal-result confirmation)
- ball_crosses_goal_line: ball clearly crosses the goal line
- goal_result_confirmed: outcome confirmed from visible evidence (celebration after
  clear entry, etc.) — NOT from scoreboard alone
- supports_bound_segment: whether THIS window's evidence is enough to bind the EDL
  segment as a goal-action cut candidate (still NOT FIRST_LIVE_VERIFIED)
- Scoreboard 0-0 alone neither proves nor disproves a goal
- Never set fact_verified true; never claim FIRST_LIVE_VERIFIED

Required JSON keys:
{{
  "visible_content": "string",
  "story_relation": "string",
  "observed_shot": true/false,
  "shot_frame_ids": ["frame_id", ...],
  "ball_crosses_goal_line": true/false,
  "goal_result_confirmed": true/false,
  "goal_result_basis": "string or null",
  "observed_net": true/false,
  "goalmouth_or_net_visible": true/false,
  "candidate_goal_action_span": {{"start": float, "end": float}} or null,
  "live_or_replay": "live"|"replay"|"unknown",
  "replay_or_slowmo_or_repeat_observed": true/false,
  "supports_bound_segment": true/false,
  "uncertain": ["string", ...],
  "uncertain_reasons": ["string", ...],
  "scoreboard_only": false,
  "fact_verified": false,
  "observation_only": true,
  "cited_frame_ids": ["frame_id", ...]
}}
""".format(
    start=WINDOW["start"], end=WINDOW["end"]
)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _frame_id_for_pts(actual_sec: float, index: int) -> str:
    ms = int(round(float(actual_sec) * 1000.0))
    return f"f_{index:04d}_{ms}"


def estimate_prompt_tokens(n_frames: int) -> int:
    """Scale from historical 4-frame prompt_tokens without inventing vendor pricing."""
    per_image = max(1, (HIST_PROMPT_TOKENS_4 - HIST_TEXT_TOKEN_EST) // 4)
    return int(HIST_TEXT_TOKEN_EST + per_image * int(n_frames))


def estimate_call_cost(n_frames: int, completion_tokens: int = MAX_COMPLETION_TOKENS) -> float:
    return float(_estimate_cost(estimate_prompt_tokens(n_frames), int(completion_tokens)))


def load_historical_four(out_frames: Path) -> Dict[str, Any]:
    """Copy NEW-run historical frames (byte-identical to OLD) into OUT and attach both VLM JSON."""
    src_dir = NEW_RUN / "round_01" / "vlm" / "frames"
    old_obs = _load_json(OLD_RUN / "round_01" / "vlm_observations.json")["observations"][0]
    new_obs = _load_json(NEW_RUN / "round_01" / "vlm_observations.json")["observations"][0]
    out_frames.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, Any]] = []
    for i, name in enumerate(HIST_FRAME_NAMES):
        src = src_dir / name
        if not src.is_file():
            raise FileNotFoundError(f"missing historical frame: {src}")
        sha = _sha256_file(src)
        # Cross-check OLD identity
        old_src = OLD_RUN / "round_01" / "vlm" / "frames" / name
        if old_src.is_file() and _sha256_file(old_src) != sha:
            raise RuntimeError(f"OLD/NEW frame SHA mismatch for {name}")
        dst = out_frames / name
        if not dst.is_file() or _sha256_file(dst) != sha:
            shutil.copy2(src, dst)
        actual = HIST_ACTUAL_PTS[i]
        requested = HIST_REQUESTED_PTS[i]
        fid = _frame_id_for_pts(actual, i)
        # Keep filename-derived id consistent with historical naming when possible
        m = re.match(r"(f_\d+_\d+)\.jpg$", name)
        if m:
            fid = m.group(1)
        rows.append({
            "index": i,
            "frame_id": fid,
            "filename": name,
            "path": str(dst),
            "requested_media_sec": requested,
            "actual_media_sec": actual,
            "pts_status": "pts",
            "sha256": sha,
            "source": "historical_reuse",
            "arm": "4",
        })
    return {
        "arm": "4_historical",
        "n_frames": 4,
        "frames": rows,
        "historical_vlm": {
            "note": (
                "Reused offline; prompts/models differ slightly from this probe's "
                "prompt — not a strict frame-count causal baseline."
            ),
            "old_run": str(OLD_RUN),
            "new_run": str(NEW_RUN),
            "old": {
                "model": old_obs.get("model"),
                "usage": old_obs.get("usage"),
                "vlm": old_obs.get("vlm"),
                "raw_excerpt": old_obs.get("raw_excerpt"),
                "evidence_classification": classify_goal_action_evidence(
                    old_obs.get("vlm") or {}
                ),
            },
            "new": {
                "model": new_obs.get("model"),
                "usage": new_obs.get("usage"),
                "vlm": new_obs.get("vlm"),
                "raw_excerpt": new_obs.get("raw_excerpt"),
                "evidence_classification": classify_goal_action_evidence(
                    new_obs.get("vlm") or {}
                ),
            },
        },
    }


def _even_times(start: float, end: float, count: int) -> List[float]:
    if count <= 0:
        return []
    if count == 1:
        return [round(0.5 * (start + end), 3)]
    step = (end - start) / (count + 1)
    return [round(start + step * (i + 1), 3) for i in range(count)]


def plan_eight_requested_times(hist_actual: Sequence[float]) -> Dict[str, Any]:
    """Keep historical 4; add 4 covering early/late unobserved spans (no gold times)."""
    ws, we = WINDOW["start"], WINDOW["end"]
    hist = [float(x) for x in hist_actual]
    early_lo, early_hi = ws + 0.5, min(hist) - 0.75
    late_lo, late_hi = max(hist) + 0.75, we - 0.5
    added: List[float] = []
    reasons: List[Dict[str, Any]] = []
    if early_hi > early_lo + 1.0:
        et = _even_times(early_lo, early_hi, 2)
        added.extend(et)
        reasons.append({
            "region": "early_unobserved_before_historical_cluster",
            "span": [early_lo, early_hi],
            "times": et,
            "rationale": (
                "Historical 4 frames cluster mid-window; cover onset/buildup "
                "without using human goal labels."
            ),
        })
    else:
        et = _even_times(ws + 0.8, min(hist) - 0.5, 2)
        added.extend(et)
        reasons.append({"region": "early_fallback", "times": et})
    if late_hi > late_lo + 1.0:
        lt = _even_times(late_lo, late_hi, 2)
        added.extend(lt)
        reasons.append({
            "region": "late_unobserved_after_historical_cluster",
            "span": [late_lo, late_hi],
            "times": lt,
            "rationale": (
                "Cover post-cluster aftermath / possible scoreboard or cutaway "
                "without gold timestamps."
            ),
        })
    else:
        lt = _even_times(max(hist) + 0.5, we - 0.8, 2)
        added.extend(lt)
        reasons.append({"region": "late_fallback", "times": lt})
    # Ensure uniqueness & separation from hist
    cleaned: List[float] = []
    for t in added:
        if any(abs(t - h) < MIN_SEP_SEC for h in hist):
            continue
        if any(abs(t - c) < MIN_SEP_SEC for c in cleaned):
            continue
        if t < ws - 1e-6 or t > we + 1e-6:
            continue
        cleaned.append(round(t, 3))
    while len(cleaned) < 4:
        # Fill remaining from mid-gaps between hist frames / window edges
        candidates = _even_times(ws + 0.5, we - 0.5, 12)
        for t in candidates:
            if len(cleaned) >= 4:
                break
            if any(abs(t - h) < MIN_SEP_SEC for h in list(hist) + cleaned):
                continue
            cleaned.append(round(t, 3))
        break
    cleaned = cleaned[:4]
    return {
        "historical_actual_pts": hist,
        "added_requested_pts": cleaned,
        "all_requested_pts_for_new_extracts": cleaned,
        "selection_reasons": reasons,
        "forbidden": [
            "strip_gold.json",
            "human_labeled_goal_time",
            "hardcoded_goal_moment",
        ],
    }


def _motion_scores(
    video: Path,
    *,
    start: float,
    end: float,
    step: float = 0.5,
    work_dir: Path,
) -> List[Dict[str, Any]]:
    """Local grayscale consecutive-frame L1 motion proxy (no gold labels)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    # Extract small grayscale strip via ffmpeg fps filter into a temporary pattern.
    # Use select at discrete times for robustness on long VODs.
    times = []
    t = start
    while t <= end + 1e-9:
        times.append(round(t, 3))
        t += step
    scores: List[Dict[str, Any]] = []
    prev_path: Optional[Path] = None
    for i, ts in enumerate(times):
        out = work_dir / f"m_{i:04d}.jpg"
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-ss", f"{ts:.3f}", "-i", str(video),
            "-frames:v", "1",
            "-vf", "scale=160:-1,format=gray",
            "-q:v", "5", "-y", str(out),
        ]
        subprocess.run(cmd, check=False, capture_output=True)
        if not out.is_file():
            continue
        score = 0.0
        if prev_path and prev_path.is_file():
            # Pure-Python L1 on downsampled bytes via optional PIL; fallback size delta.
            try:
                from PIL import Image  # type: ignore
                import numpy as np  # type: ignore

                a = np.asarray(Image.open(prev_path), dtype="float32")
                b = np.asarray(Image.open(out), dtype="float32")
                if a.shape == b.shape:
                    score = float(np.mean(np.abs(a - b)))
            except Exception:
                score = abs(out.stat().st_size - prev_path.stat().st_size)
        scores.append({"t": ts, "motion": score, "path": str(out)})
        prev_path = out
    return scores


def plan_sixteen_requested_times(
    *,
    kept_actual: Sequence[float],
    video: Path,
    work_dir: Path,
    vlm8: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Keep all 8-arm frames; add 8 more via motion + unobserved densify (no gold)."""
    ws, we = WINDOW["start"], WINDOW["end"]
    kept = [float(x) for x in kept_actual]
    motion = _motion_scores(video, start=ws, end=we, step=0.5, work_dir=work_dir / "motion")
    ranked = sorted(motion, key=lambda r: float(r.get("motion") or 0.0), reverse=True)
    added: List[float] = []
    motion_picks: List[Dict[str, Any]] = []
    for row in ranked:
        t = float(row["t"])
        if any(abs(t - k) < MIN_SEP_SEC for k in kept + added):
            continue
        added.append(round(t, 3))
        motion_picks.append({"t": round(t, 3), "motion": row.get("motion")})
        if len(added) >= 6:
            break
    # Bias remaining fills using 8-frame VLM hints WITHOUT trusting gold times:
    # if model gave a candidate span, densify *inside that claimed span* and also
    # outside historical cluster; if null, densify gaps.
    hint_span = None
    if isinstance(vlm8, Mapping):
        span = vlm8.get("candidate_goal_action_span")
        if isinstance(span, dict):
            try:
                a, b = float(span["start"]), float(span["end"])
                if b > a and a >= ws - 1.0 and b <= we + 1.0:
                    hint_span = (a, b)
            except (TypeError, ValueError, KeyError):
                hint_span = None
    fill_regions: List[Tuple[float, float]] = []
    if hint_span:
        fill_regions.append(hint_span)
    fill_regions.append((ws + 0.3, min(kept) - 0.3))
    fill_regions.append((max(kept) + 0.3, we - 0.3))
    for lo, hi in fill_regions:
        if hi <= lo + 0.5:
            continue
        for t in _even_times(lo, hi, 4):
            if len(added) >= 8:
                break
            if any(abs(t - k) < MIN_SEP_SEC for k in kept + added):
                continue
            added.append(round(t, 3))
        if len(added) >= 8:
            break
    # Final even fill if still short
    if len(added) < 8:
        for t in _even_times(ws + 0.4, we - 0.4, 24):
            if len(added) >= 8:
                break
            if any(abs(t - k) < MIN_SEP_SEC for k in kept + added):
                continue
            added.append(round(t, 3))
    added = added[:8]
    return {
        "kept_actual_pts": kept,
        "added_requested_pts": added,
        "motion_top_picks": motion_picks[:8],
        "used_vlm8_candidate_span_as_soft_hint_only": hint_span,
        "note": (
            "Additional times from local motion ranking + densify; "
            "optional soft hint from 8-frame VLM span (not human gold)."
        ),
        "forbidden": [
            "strip_gold.json",
            "human_labeled_goal_time",
            "hardcoded_goal_moment",
        ],
    }


def extract_frames_at(
    *,
    video: Path,
    times: Sequence[float],
    out_dir: Path,
    start_index: int,
    arm: str,
) -> List[Dict[str, Any]]:
    media = probe_video(video)
    store = FrameStore(
        media,
        out_dir=out_dir,
        budget=FrameBudget(max_frames=max(32, len(times) + start_index + 2)),
    )
    rows: List[Dict[str, Any]] = []
    for j, t in enumerate(times):
        idx = start_index + j
        rec = store.extract_at(
            float(t),
            gap_id=f"frame_count_probe_{arm}",
            tool="frame_count_probe",
        )
        d = rec.to_dict()
        actual = d.get("actual_media_sec")
        if actual is None:
            actual = float(t)
            pts_status = "requested_only"
        else:
            pts_status = str(d.get("pts_status") or "pts")
        path = Path(d["path"])
        fid = _frame_id_for_pts(float(actual), idx)
        # Rename/copy to stable id filename for audit
        stable = out_dir / f"{fid}.jpg"
        if path.resolve() != stable.resolve():
            shutil.copy2(path, stable)
        rows.append({
            "index": idx,
            "frame_id": fid,
            "filename": stable.name,
            "path": str(stable),
            "requested_media_sec": float(t),
            "actual_media_sec": float(actual),
            "pts_status": pts_status,
            "sha256": _sha256_file(stable),
            "source": "extracted",
            "arm": arm,
        })
    return rows


def merge_frame_sets(
    base: Sequence[Mapping[str, Any]],
    extra: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    rows = [dict(x) for x in base] + [dict(x) for x in extra]
    rows.sort(key=lambda r: float(r["actual_media_sec"]))
    # Reindex for display but keep frame_id stable
    for i, r in enumerate(rows):
        r["sorted_index"] = i
    return rows


def verify_video(video: Path, *, verify_sha: bool) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "path": str(video),
        "exists": video.is_file(),
        "expected_sha256": EXPECTED_VIDEO_SHA256,
    }
    if not video.is_file():
        out["ok"] = False
        out["error"] = "video_missing"
        return out
    out["size_bytes"] = video.stat().st_size
    if verify_sha:
        got = _sha256_file(video)
        out["sha256"] = got
        out["sha_match"] = got == EXPECTED_VIDEO_SHA256
        out["ok"] = bool(out["sha_match"])
        if not out["ok"]:
            out["error"] = "video_sha_mismatch"
    else:
        # Accept prior verified manifest SHA if size matches known VOD.
        out["sha256"] = EXPECTED_VIDEO_SHA256
        out["sha_match"] = None
        out["sha_verification"] = "deferred_or_trusted_manifest_size_check"
        out["ok"] = out["size_bytes"] == 6113318593
        if not out["ok"]:
            out["error"] = "video_size_unexpected_refusing_without_sha"
    return out


def preflight(
    *,
    video: Path,
    out_dir: Path,
    verify_video_sha: bool,
) -> Dict[str, Any]:
    issues: List[str] = []
    vid = verify_video(video, verify_sha=verify_video_sha)
    if not vid.get("ok"):
        issues.append(str(vid.get("error") or "video_not_ok"))

    # Historical frames present
    for name in HIST_FRAME_NAMES:
        if not (NEW_RUN / "round_01/vlm/frames" / name).is_file():
            issues.append(f"missing_hist_frame:{name}")
        if not (OLD_RUN / "round_01/vlm_observations.json").is_file():
            issues.append("missing_old_vlm_obs")
            break
    if not (NEW_RUN / "round_01/vlm_observations.json").is_file():
        issues.append("missing_new_vlm_obs")

    # API config — vision only
    try:
        configs = load_endpoint_configs()
        vcfg = configs["vision"]
        vision_info = {
            "configured": vcfg.configured(),
            "model": vcfg.model,
            "base_url": vcfg.base_url,
            "token_param": vcfg.token_param,
            "max_completion_tokens": vcfg.max_completion_tokens,
            "default_temperature": vcfg.default_temperature,
            "api_key_set": bool(vcfg.api_key),
        }
        if not vcfg.configured():
            issues.append("vision_endpoint_not_configured")
        if not os.environ.get("STORY_API_ENABLE"):
            issues.append("STORY_API_ENABLE_not_set")
    except Exception as exc:  # noqa: BLE001
        vision_info = {"error": f"{type(exc).__name__}:{exc}"}
        issues.append("vision_config_load_failed")

    # Capacity / cost estimates (local; not vendor invoice)
    est8 = estimate_call_cost(8)
    est16 = estimate_call_cost(16)
    est_total = est8 + est16
    cost_ok = est_total <= MAX_COST_USD
    if not cost_ok:
        issues.append("estimated_cost_exceeds_soft_cap")

    # Model image count: Qwen-VL class commonly accepts ≥16 images; flag if env override lower.
    max_images_env = os.environ.get("STORY_VLM_MAX_IMAGES")
    max_images = int(max_images_env) if max_images_env else 16
    if max_images < 16:
        issues.append(f"STORY_VLM_MAX_IMAGES={max_images}_lt_16")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        issues.append("ffmpeg_missing")

    result = {
        "schema": "v3a_frame_count_probe_preflight_v1",
        "ok": len(issues) == 0,
        "issues": issues,
        "video": vid,
        "window": WINDOW,
        "historical_pts_actual": HIST_ACTUAL_PTS,
        "vision": vision_info,
        "budget": {
            "max_vision_http": MAX_VISION_HTTP,
            "deepseek_http": 0,
            "max_retries": 0,
            "max_completion_tokens": MAX_COMPLETION_TOKENS,
            "max_cost_usd_soft": MAX_COST_USD,
            "cost_disclaimer": COST_DISCLAIMER,
        },
        "cost_estimate": {
            "prompt_token_model": {
                "hist_4_prompt_tokens": HIST_PROMPT_TOKENS_4,
                "text_token_est": HIST_TEXT_TOKEN_EST,
                "est_8_prompt_tokens": estimate_prompt_tokens(8),
                "est_16_prompt_tokens": estimate_prompt_tokens(16),
            },
            "est_cost_usd_8_at_max_completion": round(est8, 6),
            "est_cost_usd_16_at_max_completion": round(est16, 6),
            "est_cost_usd_total_worst_case": round(est_total, 6),
            "within_soft_cap": cost_ok,
        },
        "image_capacity": {
            "planned_max_images": 16,
            "configured_max_images": max_images,
            "note": (
                "No vendor hard reject expected for 16 JPEG frames on Qwen3.6-Plus; "
                "context is image-dominated. Soft cost cap is local estimate only."
            ),
        },
        "ffmpeg": ffmpeg,
        "out_dir": str(out_dir),
        "baseline_commit_expected": "c51a7cd",
    }
    _dump(out_dir / "preflight.json", result)
    return result


def call_qwen_vision(
    *,
    api: ApiProvider,
    frames: Sequence[Mapping[str, Any]],
    audit_dir: Path,
    request_id: str,
) -> Dict[str, Any]:
    paths = [Path(f["path"]) for f in frames]
    fids = [str(f["frame_id"]) for f in frames]
    bindings = [{
        "frame_id": f["frame_id"],
        "requested_media_sec": f.get("requested_media_sec"),
        "actual_media_sec": f.get("actual_media_sec"),
        "pts_status": f.get("pts_status"),
    } for f in frames]
    mock_obj = {
        "visible_content": "mock_forbidden",
        "fact_verified": False,
        "observation_only": True,
        "cited_frame_ids": fids[:1],
    }
    t0 = time.time()
    try:
        resp = api.vision_json(
            prompt=PROBE_PROMPT,
            frame_paths=paths,
            frame_ids=fids,
            mock_obj=mock_obj,
            frame_bindings=bindings,
        )
    except (ApiConfigError, ApiCallError) as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}:{exc}",
            "provider_mode": "degraded",
            "elapsed_sec": time.time() - t0,
        }
    content = str(resp.get("content") or "")
    usage = resp.get("usage") or {}
    finish_reason = str(resp.get("finish_reason") or "")
    visible = persist_visible_model_output(
        audit_dir,
        role="vision",
        request_id=request_id,
        content=content,
        meta={
            "model": resp.get("model"),
            "provider_mode": resp.get("provider_mode"),
            "finish_reason": finish_reason,
            "usage": usage,
            "frame_ids": fids,
            "n_frames": len(fids),
        },
    )
    parsed = None
    parse_error = None
    try:
        parsed = _extract_json_obj(content)
    except Exception as exc:  # noqa: BLE001
        parse_error = f"{type(exc).__name__}:{exc}"
    if isinstance(parsed, dict):
        parsed["fact_verified"] = False
        parsed["observation_only"] = True
        # Map legacy net
        if "goalmouth_or_net_visible" not in parsed and "observed_net" in parsed:
            parsed["goalmouth_or_net_visible"] = parsed.get("observed_net")
    evidence = classify_goal_action_evidence(parsed or {})
    truncated = finish_reason == "length" or (
        int(usage.get("completion_tokens") or 0) >= MAX_COMPLETION_TOKENS
    )
    mode = str(resp.get("provider_mode") or "")
    if mode == "openai_compatible":
        mode = "real"
    ok = mode == "real" and not resp.get("error") and parsed is not None and not parse_error
    return {
        "ok": ok,
        "provider_mode": mode,
        "model": resp.get("model"),
        "error": None if ok else (str(resp.get("error") or parse_error or "vision_failed")),
        "parse_error": parse_error,
        "finish_reason": finish_reason,
        "truncated_or_length_finish": truncated,
        "usage": usage,
        "est_cost_usd": resp.get("est_cost_usd"),
        "elapsed_sec": time.time() - t0,
        "vlm": parsed,
        "evidence_classification": evidence,
        "raw_excerpt": content[:2000],
        "observed_net_is_not_goal_confirmation": True,
        "frame_ids": fids,
        "n_frames": len(fids),
        **visible,
    }


def build_report(
    *,
    out_dir: Path,
    preflight_doc: Mapping[str, Any],
    arm4: Mapping[str, Any],
    arm8: Mapping[str, Any],
    arm16: Mapping[str, Any],
    http_calls: int,
    total_cost: float,
    human_review: Mapping[str, Any],
) -> str:
    def _brief(arm: Mapping[str, Any]) -> str:
        vlm = arm.get("vlm_result") or {}
        v = vlm.get("vlm") if isinstance(vlm.get("vlm"), dict) else {}
        ev = vlm.get("evidence_classification") or {}
        return (
            f"- n_frames={arm.get('n_frames')}\n"
            f"- observed_shot={v.get('observed_shot')} shot_frame_ids={v.get('shot_frame_ids')}\n"
            f"- ball_crosses_goal_line={v.get('ball_crosses_goal_line')}\n"
            f"- goal_result_confirmed={v.get('goal_result_confirmed')} "
            f"basis={v.get('goal_result_basis')!r}\n"
            f"- candidate_goal_action_span={v.get('candidate_goal_action_span')}\n"
            f"- supports_bound_segment={v.get('supports_bound_segment')}\n"
            f"- live_or_replay={v.get('live_or_replay')} "
            f"replay_flags={v.get('replay_or_slowmo_or_repeat_observed')}\n"
            f"- evidence_status={ev.get('status')} bindable={ev.get('bindable')}\n"
            f"- uncertain={v.get('uncertain')}\n"
            f"- usage={vlm.get('usage')} est_cost={vlm.get('est_cost_usd')} "
            f"finish_reason={vlm.get('finish_reason')} truncated={vlm.get('truncated_or_length_finish')}\n"
        )

    hist = arm4.get("historical_vlm") or {}
    old_ev = ((hist.get("old") or {}).get("evidence_classification") or {}).get("status")
    new_ev = ((hist.get("new") or {}).get("evidence_classification") or {}).get("status")
    v8 = ((arm8.get("vlm_result") or {}).get("vlm") or {})
    v16 = ((arm16.get("vlm_result") or {}).get("vlm") or {})
    e8 = ((arm8.get("vlm_result") or {}).get("evidence_classification") or {})
    e16 = ((arm16.get("vlm_result") or {}).get("evidence_classification") or {})

    # Answers A–D (evidence-based, cautious)
    a_lines = []
    if arm8.get("vlm_result", {}).get("ok"):
        if e8.get("status") != new_ev or v8.get("supports_bound_segment") != (
            (hist.get("new") or {}).get("vlm") or {}
        ).get("supports_bound_segment"):
            a_lines.append(
                "8-frame structured judgment differs from NEW historical 4-frame "
                f"(hist NEW status={new_ev}, 8-frame status={e8.get('status')})."
            )
        if v8.get("ball_crosses_goal_line") or v8.get("goal_result_confirmed"):
            a_lines.append(
                "8-frame reports stronger goal fields "
                f"(crosses={v8.get('ball_crosses_goal_line')}, "
                f"confirmed={v8.get('goal_result_confirmed')})."
            )
        if v8.get("candidate_goal_action_span"):
            a_lines.append(
                f"8-frame provided candidate span {v8.get('candidate_goal_action_span')} "
                "(NEW historical span was null)."
            )
        if not a_lines:
            a_lines.append(
                "8-frame ran successfully but did not clearly add stronger bindable "
                "goal confirmation beyond historical disagreement; treat as weak/new "
                "localization signal only."
            )
        a_lines.append(
            "NOTE: historical 4-frame prompt ≠ this probe prompt; not a strict "
            "causal frame-count A/B."
        )
    else:
        a_lines.append("8-frame call failed or did not parse; cannot claim new evidence.")

    b_lines = []
    if arm16.get("vlm_result", {}).get("ok") and arm8.get("vlm_result", {}).get("ok"):
        if e16.get("status") != e8.get("status"):
            b_lines.append(
                f"16-frame evidence status changed vs 8-frame: "
                f"{e8.get('status')} → {e16.get('status')}."
            )
        span8, span16 = v8.get("candidate_goal_action_span"), v16.get("candidate_goal_action_span")
        if span8 != span16:
            b_lines.append(f"Action span changed: 8={span8} → 16={span16}.")
        for key in (
            "observed_shot",
            "ball_crosses_goal_line",
            "goal_result_confirmed",
            "supports_bound_segment",
        ):
            if v8.get(key) != v16.get(key):
                b_lines.append(f"Field {key}: 8={v8.get(key)} → 16={v16.get(key)}.")
        if not b_lines:
            b_lines.append(
                "16-frame did not materially change core structured judgments vs 8-frame."
            )
    else:
        b_lines.append("Cannot compare 16 vs 8 (missing successful parse on one arm).")

    def _field_prose_conflict(v: Mapping[str, Any]) -> List[str]:
        probs = []
        if not isinstance(v, dict) or not v:
            return probs
        prose = f"{v.get('visible_content') or ''} {v.get('story_relation') or ''}".lower()
        if v.get("supports_bound_segment") is False and (
            v.get("observed_shot") is True and v.get("observed_net") is True
        ):
            probs.append("supports_false_with_shot_and_net_true")
        if v.get("goal_result_confirmed") is True and "no goal" in prose:
            probs.append("goal_confirmed_true_but_prose_denies_goal")
        if v.get("goal_result_confirmed") is False and v.get("ball_crosses_goal_line") is True:
            probs.append("crosses_true_but_goal_not_confirmed")
        if v.get("observed_net") is True and v.get("goal_result_confirmed") is True:
            # not necessarily conflict, but flag net≠confirmation reminder
            pass
        if "0-0" in prose.replace(" ", "") or "0-0" in prose:
            if v.get("goal_result_confirmed") is False and v.get("supports_bound_segment") is False:
                probs.append(
                    "prose_mentions_0-0_with_negative_support_—"
                    "0-0_alone_must_not_decide"
                )
        return probs

    c_conflicts = {
        "historical_old": _field_prose_conflict((hist.get("old") or {}).get("vlm") or {}),
        "historical_new": _field_prose_conflict((hist.get("new") or {}).get("vlm") or {}),
        "arm8": _field_prose_conflict(v8),
        "arm16": _field_prose_conflict(v16),
    }

    # D recommendation
    improved = (
        e16.get("bindable") and not e8.get("bindable")
    ) or (
        v16.get("goal_result_confirmed") and not v8.get("goal_result_confirmed")
    )
    if improved:
        d_rec = (
            "If 16-frame uniquely unlocked bindable/confirmed fields, a modest denser "
            "still-frame pass may help — but prefer a short continuous clip / multi-frame "
            "temporal model next for ball-crossing dynamics that sparse stills miss."
        )
    else:
        d_rec = (
            "Diminishing returns likely from more still frames alone; next step should "
            "prefer a continuous short video segment (or denser temporal sampling with "
            "explicit cross-frame tracking) rather than only raising still-frame count."
        )

    lines = [
        "# V3-A Frame Count Probe Report (Opening Goal)",
        "",
        f"- Schema: `{SCHEMA}`",
        f"- Out dir: `{out_dir}`",
        f"- Baseline branch commit expected: `c51a7cd`",
        f"- Window: `{WINDOW['start']}–{WINDOW['end']}s`",
        f"- Video: `{preflight_doc.get('video', {}).get('path')}`",
        f"- Video SHA256: `{preflight_doc.get('video', {}).get('sha256')}` "
        f"(match={preflight_doc.get('video', {}).get('sha_match')})",
        f"- HTTP vision calls used: **{http_calls}** / {MAX_VISION_HTTP}",
        f"- DeepSeek calls: **0**",
        f"- Est. cost USD (local): **{total_cost:.6f}** soft cap {MAX_COST_USD}",
        f"- {COST_DISCLAIMER}",
        "",
        "## Preflight",
        f"- ok={preflight_doc.get('ok')} issues={preflight_doc.get('issues')}",
        f"- worst-case est 8+16=${(preflight_doc.get('cost_estimate') or {}).get('est_cost_usd_total_worst_case')}",
        "",
        "## Arm 4 (historical reuse — NOT re-called)",
        f"- OLD evidence_status={old_ev}; NEW evidence_status={new_ev}",
        "- Prompt differs from 8/16 probe prompt → reference only.",
        "",
        "## Arm 8 (real Qwen)",
        _brief(arm8),
        "",
        "## Arm 16 (real Qwen)",
        _brief(arm16),
        "",
        "## Focus questions",
        "",
        "### A. Did 8 frames add useful evidence vs historical 4?",
        *[f"- {x}" for x in a_lines],
        "",
        "### B. Did 16 frames further improve vs 8?",
        *[f"- {x}" for x in b_lines],
        "",
        "### C. Remaining prose ↔ field contradictions?",
        f"- {json.dumps(c_conflicts, ensure_ascii=False)}",
        "",
        "### D. Next: more frames or continuous clip?",
        f"- {d_rec}",
        "",
        "## Human verification",
        f"- {json.dumps(human_review, ensure_ascii=False)}",
        "",
        "## Artifacts",
        "- `preflight.json`, `frame_manifest_*.json`, `sample_plan_*.json`",
        "- `model_visible/` full visible outputs (secrets redacted)",
        "- `vlm_result_8.json`, `vlm_result_16.json`",
        "- `summary.json`",
        "",
    ]
    text = "\n".join(lines) + "\n"
    (out_dir / "FRAME_COUNT_EXPERIMENT_REPORT.md").write_text(text, encoding="utf-8")
    return text


def run(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Independent OUT directory for this probe",
    )
    p.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    p.add_argument(
        "--verify-video-sha",
        action="store_true",
        help="Hash full VOD (slow). Default trusts size+expected SHA from prior manifest.",
    )
    p.add_argument(
        "--preflight-only",
        action="store_true",
        help="Stop after zero-cost preflight (no HTTP)",
    )
    p.add_argument(
        "--i-approve-budget",
        action="store_true",
        help="Required to place the two authorized Vision HTTP calls",
    )
    args = p.parse_args(list(argv) if argv is not None else None)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = args.out_dir or Path(
        f"/data2/lpy1/_story_va_outputs/v3/plan2/A_frame_count_probe_{ts}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    # Optional: if a concurrent sha256sum finished, prefer live match.
    verify_sha = bool(args.verify_video_sha)
    sha_cache = Path("/tmp/uae_oman_video.sha256")
    if sha_cache.is_file():
        txt = sha_cache.read_text(encoding="utf-8", errors="replace").strip()
        if txt and " " in txt and not txt.startswith("nohup"):
            # format: "<hash>  <path>"
            got = txt.split()[0]
            if re.fullmatch(r"[0-9a-f]{64}", got):
                verify_sha = True
                # store for preflight path below via monkey env
                os.environ["_PROBE_LIVE_VIDEO_SHA"] = got

    pf = preflight(video=args.video, out_dir=out_dir, verify_video_sha=verify_sha)
    live = os.environ.get("_PROBE_LIVE_VIDEO_SHA")
    if live:
        pf["video"]["sha256"] = live
        pf["video"]["sha_match"] = live == EXPECTED_VIDEO_SHA256
        pf["video"]["sha_verification"] = "live_sha256sum"
        pf["video"]["ok"] = pf["video"]["sha_match"]
        if not pf["video"]["ok"]:
            pf["ok"] = False
            pf.setdefault("issues", []).append("video_sha_mismatch_live")
        _dump(out_dir / "preflight.json", pf)

    if not pf.get("ok"):
        print(json.dumps({"stop": "preflight_failed", "issues": pf.get("issues")}, ensure_ascii=False, indent=2))
        return 2
    if args.preflight_only:
        print(json.dumps({"stop": "preflight_only_ok", "out_dir": str(out_dir)}, ensure_ascii=False, indent=2))
        return 0
    if not args.i_approve_budget:
        print(json.dumps({
            "stop": "need_i_approve_budget",
            "out_dir": str(out_dir),
            "note": "Preflight passed; pass --i-approve-budget to spend ≤2 Vision HTTP.",
        }, ensure_ascii=False, indent=2))
        return 3

    # --- Arm 4 historical ---
    frames4_dir = out_dir / "frames_4_historical"
    arm4 = load_historical_four(frames4_dir)
    _dump(out_dir / "frame_manifest_4.json", arm4)
    _dump(out_dir / "historical_vlm_reuse.json", arm4["historical_vlm"])

    # --- Plan + extract 8 ---
    plan8 = plan_eight_requested_times(HIST_ACTUAL_PTS)
    _dump(out_dir / "sample_plan_8.json", plan8)
    frames8_new_dir = out_dir / "frames_8_extra"
    extra8 = extract_frames_at(
        video=args.video,
        times=plan8["added_requested_pts"],
        out_dir=frames8_new_dir,
        start_index=4,
        arm="8",
    )
    frames8 = merge_frame_sets(arm4["frames"], extra8)
    _dump(out_dir / "frame_manifest_8.json", {
        "arm": "8",
        "n_frames": len(frames8),
        "frames": frames8,
        "sample_plan": plan8,
    })

    # Budget gate before first HTTP
    est8 = estimate_call_cost(8)
    est16 = estimate_call_cost(16)
    if est8 + est16 > MAX_COST_USD:
        _dump(out_dir / "abort.json", {
            "reason": "projected_8_plus_16_exceeds_soft_cap",
            "est8": est8, "est16": est16,
        })
        return 4

    configs = load_endpoint_configs()
    # Force completion ceiling + zero retries on vision role only.
    vcfg = configs["vision"]
    vcfg.max_completion_tokens = MAX_COMPLETION_TOKENS
    vcfg.max_retries = 0
    api = ApiProvider(
        force_mock=False,
        require_real=True,
        configs=configs,
        max_calls=MAX_VISION_HTTP,
        max_cost_usd=MAX_COST_USD,
        max_completion_tokens=MAX_COMPLETION_TOKENS,
        required_roles=["vision"],
    )

    audit_dir = out_dir / "model_visible"
    print("Calling Qwen vision arm=8 ...", flush=True)
    vlm8 = call_qwen_vision(
        api=api, frames=frames8, audit_dir=audit_dir, request_id="arm8",
    )
    _dump(out_dir / "vlm_result_8.json", vlm8)
    arm8_doc = {
        "arm": "8",
        "n_frames": len(frames8),
        "frames": frames8,
        "vlm_result": vlm8,
    }
    _dump(out_dir / "arm8_summary.json", arm8_doc)

    spent = float(vlm8.get("est_cost_usd") or 0.0)
    # Re-estimate 16 with updated remaining budget
    if spent + est16 > MAX_COST_USD:
        _dump(out_dir / "abort_after_8.json", {
            "reason": "remaining_budget_insufficient_for_projected_16",
            "spent_est_usd": spent,
            "projected_16": est16,
            "soft_cap": MAX_COST_USD,
        })
        human_review = {
            "status": "NOT_VERIFIED",
            "note": "No human video review performed in this automated run.",
        }
        build_report(
            out_dir=out_dir,
            preflight_doc=pf,
            arm4=arm4,
            arm8=arm8_doc,
            arm16={"arm": "16", "n_frames": 0, "vlm_result": {"ok": False, "error": "aborted_budget"}},
            http_calls=1,
            total_cost=spent,
            human_review=human_review,
        )
        print(json.dumps({"stop": "budget_stop_after_8", "out_dir": str(out_dir)}, ensure_ascii=False))
        return 5

    # --- Plan + extract 16 ---
    kept_actual = [float(f["actual_media_sec"]) for f in frames8]
    plan16 = plan_sixteen_requested_times(
        kept_actual=kept_actual,
        video=args.video,
        work_dir=out_dir / "motion_scan",
        vlm8=vlm8.get("vlm") if isinstance(vlm8.get("vlm"), dict) else None,
    )
    _dump(out_dir / "sample_plan_16.json", plan16)
    frames16_extra_dir = out_dir / "frames_16_extra"
    extra16 = extract_frames_at(
        video=args.video,
        times=plan16["added_requested_pts"],
        out_dir=frames16_extra_dir,
        start_index=8,
        arm="16",
    )
    frames16 = merge_frame_sets(frames8, extra16)
    _dump(out_dir / "frame_manifest_16.json", {
        "arm": "16",
        "n_frames": len(frames16),
        "frames": frames16,
        "sample_plan": plan16,
    })

    print("Calling Qwen vision arm=16 ...", flush=True)
    vlm16 = call_qwen_vision(
        api=api, frames=frames16, audit_dir=audit_dir, request_id="arm16",
    )
    _dump(out_dir / "vlm_result_16.json", vlm16)
    arm16_doc = {
        "arm": "16",
        "n_frames": len(frames16),
        "frames": frames16,
        "vlm_result": vlm16,
    }
    _dump(out_dir / "arm16_summary.json", arm16_doc)

    usage = api.stats.summary()
    http_calls = int(usage.get("http_attempts") or usage.get("real_requests") or 0)
    total_cost = float(usage.get("est_cost_usd_real") or (spent + float(vlm16.get("est_cost_usd") or 0)))
    human_review = {
        "status": "NOT_VERIFIED",
        "note": (
            "Automated probe did not perform human visual verification of correctness; "
            "only model self-consistency / field-prose checks are reported."
        ),
    }
    summary = {
        "schema": SCHEMA,
        "out_dir": str(out_dir),
        "http_vision_calls": http_calls,
        "deepseek_calls": 0,
        "est_cost_usd_real": total_cost,
        "api_usage": usage,
        "preflight_ok": True,
        "arm4_historical": {
            "n_frames": 4,
            "old_evidence": ((arm4.get("historical_vlm") or {}).get("old") or {}).get(
                "evidence_classification"
            ),
            "new_evidence": ((arm4.get("historical_vlm") or {}).get("new") or {}).get(
                "evidence_classification"
            ),
        },
        "arm8": {
            "ok": vlm8.get("ok"),
            "evidence": vlm8.get("evidence_classification"),
            "usage": vlm8.get("usage"),
            "est_cost_usd": vlm8.get("est_cost_usd"),
            "truncated": vlm8.get("truncated_or_length_finish"),
        },
        "arm16": {
            "ok": vlm16.get("ok"),
            "evidence": vlm16.get("evidence_classification"),
            "usage": vlm16.get("usage"),
            "est_cost_usd": vlm16.get("est_cost_usd"),
            "truncated": vlm16.get("truncated_or_length_finish"),
        },
        "human_review": human_review,
        "cost_disclaimer": COST_DISCLAIMER,
    }
    _dump(out_dir / "summary.json", summary)
    build_report(
        out_dir=out_dir,
        preflight_doc=pf,
        arm4=arm4,
        arm8=arm8_doc,
        arm16=arm16_doc,
        http_calls=http_calls,
        total_cost=total_cost,
        human_review=human_review,
    )
    print(json.dumps({"done": True, "out_dir": str(out_dir), "summary": summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(run())
