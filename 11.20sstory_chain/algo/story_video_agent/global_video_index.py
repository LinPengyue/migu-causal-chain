"""P1: Lightweight global video index — full-span sampling + score timeline.

Input: full-match MP4 only. Never reads events/causal JSON.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from story_chain.score_path import ScoreNode, _plus_one, parse_score
from story_video_agent.media import probe_video
from story_video_agent.scoreboard_ocr import (
    RoiBox,
    detect_and_read_scoreboard,
    ocr_stats,
    ocr_stats_reset,
    update_tracked_roi,
)

PathLike = Union[str, Path]


class GlobalIndexError(RuntimeError):
    pass


def _require_bin(name: str) -> str:
    import shutil

    p = shutil.which(name)
    if not p:
        raise GlobalIndexError(f"{name} not found on PATH")
    return p


def extract_frame_bgr(video: Path, t_sec: float, *, width: Optional[int] = None) -> np.ndarray:
    """Fast seek + high-quality MJPEG (accurate seek too slow on long HEVC)."""
    ffmpeg = _require_bin("ffmpeg")
    import cv2

    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{max(0.0, t_sec):.3f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, check=False, timeout=60)
    if proc.returncode != 0 or not proc.stdout:
        raise GlobalIndexError(f"frame extract failed @ {t_sec}")
    arr = np.frombuffer(proc.stdout, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise GlobalIndexError(f"image decode failed @ {t_sec}")
    if width and img.shape[1] != width:
        h = int(img.shape[0] * (width / img.shape[1]))
        img = cv2.resize(img, (width, h))
    return img


def sample_times_fullspan(duration: float, *, max_frames: int) -> List[float]:
    """Uniform coverage of [0, duration] under a fixed frame budget."""
    if duration <= 0 or max_frames <= 0:
        return []
    if max_frames == 1:
        return [0.0]
    end = max(0.0, duration - 0.05)
    return [round(i * end / (max_frames - 1), 3) for i in range(max_frames)]


def sample_times(duration: float, *, step_sec: float, max_frames: int) -> List[float]:
    """Backward-compatible wrapper: prefer full-span when step would truncate."""
    if duration <= 0:
        return []
    needed = int(duration / max(step_sec, 1e-6)) + 1
    if needed > max_frames:
        return sample_times_fullspan(duration, max_frames=max_frames)
    times = []
    t = 0.0
    while t <= duration + 1e-9 and len(times) < max_frames:
        times.append(round(min(t, max(0.0, duration - 0.05)), 3))
        t += step_sec
    if times and times[-1] < duration - 1.0 and len(times) < max_frames:
        times.append(round(max(0.0, duration - 0.05), 3))
    return times


def sampling_coverage(times: Sequence[float], duration: float) -> Dict[str, Any]:
    if duration <= 0:
        return {"coverage_ratio": 0.0, "max_gap_sec": 0.0, "uncovered_intervals": []}
    ts = sorted(set(float(t) for t in times))
    if not ts:
        return {
            "coverage_ratio": 0.0,
            "max_gap_sec": round(duration, 3),
            "uncovered_intervals": [{"start": 0.0, "end": round(duration, 3)}],
        }
    gaps = []
    # leading / trailing / internal gaps
    points = [0.0] + ts + [duration]
    max_gap = 0.0
    uncovered = []
    for a, b in zip(points, points[1:]):
        gap = b - a
        max_gap = max(max_gap, gap)
        gaps.append(gap)
        # treat large gaps as poorly covered (half of median intended spacing)
    # coverage proxy: 1 - (max_gap / duration) clipped, plus span fraction
    span = (ts[-1] - ts[0]) / duration if duration else 0
    # mark intervals larger than 1.5x median gap as uncovered
    pos_gaps = [g for g in gaps if g > 0]
    med = sorted(pos_gaps)[len(pos_gaps) // 2] if pos_gaps else duration
    thresh = max(med * 1.5, 1.0)
    for a, b in zip(points, points[1:]):
        if b - a > thresh:
            uncovered.append({"start": round(a, 3), "end": round(b, 3), "gap_sec": round(b - a, 3)})
    return {
        "n_samples": len(ts),
        "first_sec": ts[0],
        "last_sec": ts[-1],
        "span_ratio": round(span, 4),
        "max_gap_sec": round(max_gap, 3),
        "median_gap_sec": round(med, 3),
        "coverage_ratio": round(min(1.0, span * (1.0 - max_gap / (2 * duration))), 4),
        "uncovered_intervals": uncovered[:20],
        "fullspan": abs(ts[0]) < 1.0 and ts[-1] >= duration * 0.95,
    }


def densify_around(
    centers: Sequence[float],
    duration: float,
    *,
    radius: float,
    step: float,
    existing: Sequence[float],
    max_extra: int,
) -> List[float]:
    have = set(round(x, 3) for x in existing)
    extra: List[float] = []
    for c in centers:
        t = max(0.0, c - radius)
        while t <= min(duration, c + radius) + 1e-9 and len(extra) < max_extra:
            rt = round(t, 3)
            if rt not in have:
                extra.append(rt)
                have.add(rt)
            t += step
    return sorted(extra)


def densify_centers_from_observations(
    observations: Sequence[Dict[str, Any]],
    duration: float,
) -> List[float]:
    """Centers for adaptive densify — including failures, not only successful changes."""
    centers: List[float] = []
    last_ok: Optional[Tuple[int, int]] = None
    unknown_run: List[float] = []
    for obs in sorted(observations, key=lambda o: float(o.get("t_sec") or 0)):
        t = float(obs.get("t_sec") or 0)
        st = obs.get("status")
        if st in ("ok", "weak") and obs.get("score_tuple"):
            sc = tuple(obs["score_tuple"])
            if last_ok is not None and sc != last_ok:
                centers.append(t)
            last_ok = sc  # type: ignore[assignment]
            if unknown_run:
                # densify middle of prior unknown stretch
                centers.append(unknown_run[len(unknown_run) // 2])
                unknown_run = []
        elif st in ("unknown", "conflict", "clock_only", "error"):
            unknown_run.append(t)
            if st == "conflict":
                centers.append(t)
        # long unknown runs: sample midpoint periodically
        if len(unknown_run) >= 3:
            centers.append(unknown_run[len(unknown_run) // 2])
            unknown_run = unknown_run[-1:]
    # also densify largest coarse gaps (even if all OCR failed)
    times = [float(o["t_sec"]) for o in observations if "t_sec" in o]
    cov = sampling_coverage(times, duration)
    for iv in cov.get("uncovered_intervals") or []:
        mid = 0.5 * (iv["start"] + iv["end"])
        centers.append(mid)
    # unique preserve order
    out: List[float] = []
    seen = set()
    for c in centers:
        rc = round(c, 3)
        if rc not in seen:
            seen.add(rc)
            out.append(rc)
    return out


def observations_to_score_nodes(
    observations: Sequence[Dict[str, Any]],
    *,
    confirm_hits: int = 3,
    confirm_window_sec: float = 180.0,
    establish_hits: int = 3,
) -> Tuple[List[ScoreNode], List[Dict[str, Any]], Dict[str, Any]]:
    """State machine: unknown → established → tracking; unresolved jumps kept."""
    points: List[Tuple[float, Tuple[int, int], float]] = []
    for obs in observations:
        if obs.get("status") not in ("ok", "weak"):
            continue
        st = obs.get("score_tuple")
        if not st:
            sc = parse_score(obs.get("score"))
            if not sc:
                continue
            st = sc
        # soccer sanity
        if st[0] > 9 or st[1] > 9:
            continue
        points.append((float(obs["t_sec"]), (int(st[0]), int(st[1])), float(obs.get("confidence") or 0)))
    points.sort(key=lambda x: x[0])
    diagnostics: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []
    meta: Dict[str, Any] = {
        "initial_state": "unknown",
        "established": False,
        "revoked_initial": False,
    }
    if not points:
        return [], [{"note": "no_usable_score_observations"}], meta

    path: List[ScoreNode] = []

    # --- establish initial score: need multi-frame agreement; do NOT force 0:0 ---
    # slide windows of establish_hits consecutive identical scores
    established_score: Optional[Tuple[int, int]] = None
    established_t: Optional[float] = None
    for i in range(len(points)):
        sc = points[i][1]
        window = [p for p in points if points[i][0] <= p[0] <= points[i][0] + confirm_window_sec]
        hits = sum(1 for p in window if p[1] == sc)
        if hits >= establish_hits:
            # require it to be the mode in window
            mode = Counter_score(window)
            if mode == sc:
                established_score = sc
                established_t = points[i][0]
                break
    if established_score is None:
        meta["initial_state"] = "unknown"
        diagnostics.append({"note": "initial_score_unestablished", "n_points": len(points)})
        return [], diagnostics, meta

    meta["initial_state"] = f"{established_score[0]}:{established_score[1]}"
    meta["established"] = True
    path.append(
        ScoreNode(
            t_sec=float(established_t or points[0][0]),
            score=established_score,
            opening=True,
            carrier_event_id=f"ocr@{established_t}",
        )
    )
    diagnostics.append(
        {
            "t_sec": established_t,
            "committed": f"{established_score[0]}:{established_score[1]}",
            "role": "initial_established",
            "hits": establish_hits,
        }
    )

    # revoke if soon contradicted by a different multi-confirmed score without plus-one path
    # (handled implicitly: we only advance via plus-one or record unresolved)

    for t, sc, conf in points:
        if t < path[0].t_sec:
            continue
        prev = path[-1]
        if sc == prev.score:
            continue
        side = _plus_one(prev.score, sc)
        if side is None:
            # possible replay of older score
            if any(n.score == sc for n in path[:-1]):
                diagnostics.append({"t_sec": t, "to": f"{sc[0]}:{sc[1]}", "rejected": "replay_or_old_score"})
                continue
            # jump > 1: unresolved transition (do not invent intermediates, do not freeze forever)
            window = [p for p in points if t <= p[0] <= t + confirm_window_sec]
            hits = sum(1 for p in window if p[1] == sc)
            if hits >= confirm_hits:
                unresolved.append(
                    {
                        "t_sec": t,
                        "from": f"{prev.score[0]}:{prev.score[1]}",
                        "to": f"{sc[0]}:{sc[1]}",
                        "status": "unresolved_transition",
                        "hits": hits,
                        "note": "not_plus_one; densify/manual review needed",
                    }
                )
                diagnostics.append(unresolved[-1])
                # soft re-init only if jump looks like broadcast reset and many hits dominate
                if hits >= confirm_hits + 1 and sum(1 for p in window if p[1] == prev.score) == 0:
                    path.append(
                        ScoreNode(
                            t_sec=t,
                            score=sc,
                            opening=False,
                            delta_side=None,
                            carrier_event_id=f"ocr_reinit@{t}",
                        )
                    )
                    meta["revoked_initial"] = True
                    diagnostics.append({"t_sec": t, "committed": f"{sc[0]}:{sc[1]}", "role": "reinit_after_gap"})
            else:
                diagnostics.append(
                    {
                        "t_sec": t,
                        "from": f"{prev.score[0]}:{prev.score[1]}",
                        "to": f"{sc[0]}:{sc[1]}",
                        "rejected": "not_plus_one_unconfirmed",
                    }
                )
            continue
        window = [p for p in points if t <= p[0] <= t + confirm_window_sec]
        hits = sum(1 for p in window if p[1] == sc)
        prev_hits = sum(1 for p in window if p[1] == prev.score)
        if hits < confirm_hits or hits <= prev_hits:
            diagnostics.append(
                {
                    "t_sec": t,
                    "to": f"{sc[0]}:{sc[1]}",
                    "rejected": "unconfirmed",
                    "hits": hits,
                    "prev_hits": prev_hits,
                }
            )
            continue
        path.append(
            ScoreNode(
                t_sec=t,
                score=sc,
                opening=False,
                delta_side=side,
                carrier_event_id=f"ocr@{t}",
            )
        )
        diagnostics.append(
            {
                "t_sec": t,
                "committed": f"{sc[0]}:{sc[1]}",
                "delta_side": side,
                "hits": hits,
                "confidence_sample": conf,
            }
        )
    meta["unresolved_transitions"] = unresolved
    return path, diagnostics, meta


def Counter_score(window: Sequence[Tuple[float, Tuple[int, int], float]]) -> Optional[Tuple[int, int]]:
    from collections import Counter

    c = Counter(p[1] for p in window)
    if not c:
        return None
    return c.most_common(1)[0][0]


def build_global_video_index(
    video: PathLike,
    *,
    out_dir: Optional[PathLike] = None,
    coarse_step_sec: float = 45.0,
    max_coarse_frames: int = 80,
    densify_radius_sec: float = 40.0,
    densify_step_sec: float = 8.0,
    max_dense_extra: int = 40,
    frame_width: int = 0,  # 0 = native resolution (better OCR); else target width
    confirm_hits: int = 3,
    establish_hits: int = 3,
    save_frames: bool = False,
    save_roi_evidence: bool = True,
    commit_sha: Optional[str] = None,
) -> Dict[str, Any]:
    """Run P1 indexing with full-span coarse sampling + adaptive densify."""
    t0 = time.time()
    ocr_stats_reset()
    video_path = Path(video)
    media = probe_video(video_path)
    out: Optional[Path] = Path(out_dir) if out_dir else None
    frames_dir: Optional[Path] = None
    evidence_dir: Optional[Path] = None
    if out:
        out.mkdir(parents=True, exist_ok=True)
        if save_frames:
            frames_dir = out / "frames"
            frames_dir.mkdir(exist_ok=True)
        if save_roi_evidence:
            evidence_dir = out / "roi_evidence"
            evidence_dir.mkdir(exist_ok=True)

    times = sample_times(media.duration_sec, step_sec=coarse_step_sec, max_frames=max_coarse_frames)
    observations: List[Dict[str, Any]] = []
    errors: List[str] = []
    tracked: Optional[RoiBox] = None
    scoreboard_hits = 0

    def _observe(t: float) -> None:
        nonlocal tracked, scoreboard_hits
        try:
            frame = extract_frame_bgr(
                video_path, t, width=(frame_width if frame_width and frame_width > 0 else None)
            )
            if frames_dir is not None:
                import cv2

                cv2.imwrite(str(frames_dir / f"t{t:08.1f}.jpg"), frame)
            # refresh tracked roi periodically from history
            if len(observations) >= 5 and tracked is None:
                tracked = update_tracked_roi(observations, min_hits=2)
            reading = detect_and_read_scoreboard(
                frame,
                tracked_roi=tracked,
                evidence_dir=evidence_dir if (evidence_dir and len(observations) < 12) else None,
                t_sec=t,
            )
            reading["t_sec"] = t
            # strip bulky nested readings for index size except first few
            if len(observations) >= 15 and "readings" in reading:
                reading = {k: v for k, v in reading.items() if k != "readings"}
                reading["readings_omitted"] = True
            observations.append(reading)
            if reading.get("scoreboard_detected"):
                scoreboard_hits += 1
            tr = reading.get("tracked_roi")
            if tr and reading.get("status") in ("ok", "weak"):
                tracked = RoiBox(tr.get("name") or "tracked", tr["x0"], tr["y0"], tr["x1"], tr["y1"])
        except Exception as exc:  # noqa: BLE001
            errors.append(f"t={t}:{exc}"[:160])
            observations.append({"t_sec": t, "status": "error", "score": None, "error": str(exc)[:120]})

    for t in times:
        _observe(t)

    densify_centers = densify_centers_from_observations(observations, media.duration_sec)
    extra = densify_around(
        densify_centers,
        media.duration_sec,
        radius=densify_radius_sec,
        step=densify_step_sec,
        existing=times,
        max_extra=max_dense_extra,
    )
    for t in extra:
        _observe(t)

    all_times = [float(o["t_sec"]) for o in observations if "t_sec" in o]
    coverage = sampling_coverage(all_times, media.duration_sec)

    nodes, commit_diag, path_meta = observations_to_score_nodes(
        observations,
        confirm_hits=confirm_hits,
        establish_hits=establish_hits,
    )
    usable = sum(1 for o in observations if o.get("status") in ("ok", "weak"))
    sb_rate = scoreboard_hits / max(1, len(observations))
    usable_rate = usable / max(1, len(observations))

    degrade_reasons: List[str] = []
    if usable == 0:
        degrade_reasons.append("no_usable_ocr")
    if len(nodes) == 0:
        degrade_reasons.append("empty_score_path")
    if not path_meta.get("established"):
        degrade_reasons.append("initial_unestablished")
    if usable_rate < 0.15:
        degrade_reasons.append("low_usable_ocr_rate")
    if not coverage.get("fullspan"):
        degrade_reasons.append("incomplete_time_span")
    if path_meta.get("unresolved_transitions"):
        degrade_reasons.append("unresolved_transitions")
    degraded = bool(degrade_reasons)

    perception_quality = {
        "scoreboard_detect_rate": round(sb_rate, 4),
        "usable_score_obs_rate": round(usable_rate, 4),
        "usable_ocr_count": usable,
        "observation_count": len(observations),
        "n_score_nodes": len(nodes),
        "ocr": ocr_stats(),
    }

    score_timeline = {
        "schema": "video_driven_score_timeline_v2",
        "video": str(video_path),
        "duration_sec": media.duration_sec,
        "commit_sha": commit_sha,
        "nodes": [n.to_dict() for n in nodes],
        "observation_count": len(observations),
        "usable_ocr_count": usable,
        "commit_diagnostics": commit_diag,
        "path_meta": path_meta,
        "unresolved_transitions": path_meta.get("unresolved_transitions") or [],
        "degraded": degraded,
        "degrade_reasons": degrade_reasons,
        "sampling_coverage": coverage,
        "perception_quality": perception_quality,
        "notes": [
            "t_sec is media PTS / seek time, not match clock",
            "scoreboard change time is confirmation observation, not goal action time",
            "initial score requires multi-frame establishment; 0:0 is not assumed",
            "semantic_verified=false",
        ],
        "semantic_verified": False,
    }

    index = {
        "schema": "video_driven_global_video_index_v2",
        "commit_sha": commit_sha,
        "video": str(video_path.resolve()),
        "media": media.to_dict(),
        "teams_hypothesis": {
            "left": None,
            "right": None,
            "status": "unresolved",
            "note": "P1 does not resolve team names from video alone",
        },
        "scoreboard": {
            "ocr_engine": "tesseract_cli",
            "tracked_roi": tracked.to_dict() if tracked else None,
            "detect_hits": scoreboard_hits,
        },
        "sampling": {
            "policy": "fullspan_uniform_then_adaptive_densify",
            "coarse_step_sec": coarse_step_sec,
            "max_coarse_frames": max_coarse_frames,
            "n_coarse": len(times),
            "n_dense_extra": len(extra),
            "densify_centers": densify_centers[:40],
            "coverage": coverage,
        },
        "observations": observations,
        "anomalies": {"ocr_errors": errors[:50], "degraded": degraded, "degrade_reasons": degrade_reasons},
        "perception_quality": perception_quality,
        "score_timeline_ref": "score_timeline.json",
        "elapsed_sec": round(time.time() - t0, 3),
        "semantic_verified": False,
        "gates": {"no_events_json": True, "no_causal_json": True, "no_paid_api": True},
    }

    if out:
        (out / "global_video_index.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (out / "score_timeline.json").write_text(
            json.dumps(score_timeline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        run_meta = {
            "commit_sha": commit_sha,
            "video": str(video_path),
            "params": {
                "coarse_step_sec": coarse_step_sec,
                "max_coarse_frames": max_coarse_frames,
                "max_dense_extra": max_dense_extra,
                "confirm_hits": confirm_hits,
                "establish_hits": establish_hits,
                "frame_width": frame_width,
            },
            "elapsed_sec": index["elapsed_sec"],
            "perception_quality": perception_quality,
            "degraded": degraded,
            "degrade_reasons": degrade_reasons,
        }
        (out / "run_meta.json").write_text(
            json.dumps(run_meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    index["score_timeline"] = score_timeline
    return index


def build_index_from_synthetic_observations(
    observations: Sequence[Dict[str, Any]],
    *,
    duration_sec: float = 0.0,
    confirm_hits: int = 2,
    establish_hits: int = 2,
) -> Dict[str, Any]:
    nodes, diag, meta = observations_to_score_nodes(
        list(observations), confirm_hits=confirm_hits, establish_hits=establish_hits
    )
    degraded = len(nodes) == 0 or not meta.get("established")
    return {
        "schema": "video_driven_score_timeline_v2",
        "video": None,
        "duration_sec": duration_sec,
        "nodes": [n.to_dict() for n in nodes],
        "observation_count": len(observations),
        "commit_diagnostics": diag,
        "path_meta": meta,
        "degraded": degraded,
        "degrade_reasons": [] if not degraded else ["synthetic_or_empty"],
        "semantic_verified": False,
        "synthetic": True,
    }
