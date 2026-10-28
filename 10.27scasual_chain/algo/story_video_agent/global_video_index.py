"""P1: Lightweight global video index — scoreboard OCR timeline (local only).

Input: full-match MP4 only. Never reads events/causal JSON.
OCR via tesseract CLI + OpenCV/NumPy; no paid VLM.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from story_chain.score_path import ScoreNode, _plus_one, parse_score
from story_video_agent.media import probe_video

PathLike = Union[str, Path]
_SCORE_LOOSE = re.compile(r"(\d{1,2})\s*[:：\-]\s*(\d{1,2})")


class GlobalIndexError(RuntimeError):
    pass


def _require_bin(name: str) -> str:
    import shutil

    p = shutil.which(name)
    if not p:
        raise GlobalIndexError(f"{name} not found on PATH")
    return p


def extract_frame_bgr(video: Path, t_sec: float, *, width: Optional[int] = None) -> np.ndarray:
    """Decode one frame at media time via ffmpeg → BGR ndarray."""
    ffmpeg = _require_bin("ffmpeg")
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
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, check=False, timeout=60)
    if proc.returncode != 0 or not proc.stdout:
        raise GlobalIndexError(f"frame extract failed @ {t_sec}: {(proc.stderr or b'')[-200:]!r}")
    import cv2

    arr = np.frombuffer(proc.stdout, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise GlobalIndexError(f"png decode failed @ {t_sec}")
    if width and img.shape[1] != width:
        h = int(img.shape[0] * (width / img.shape[1]))
        img = cv2.resize(img, (width, h))
    return img


def scoreboard_rois(frame_bgr: np.ndarray) -> List[Tuple[str, np.ndarray]]:
    """Heuristic crops where broadcast scorebugs often sit (priority order)."""
    h, w = frame_bgr.shape[:2]
    rois = [
        ("top_left", frame_bgr[0 : int(h * 0.18), 0 : int(w * 0.32)]),
        ("top_left_wide", frame_bgr[0 : int(h * 0.20), 0 : int(w * 0.45)]),
        ("top_center", frame_bgr[0 : int(h * 0.16), int(w * 0.25) : int(w * 0.75)]),
        ("top_right", frame_bgr[0 : int(h * 0.18), int(w * 0.55) : w]),
    ]
    return [(name, crop) for name, crop in rois if crop.size > 0]


def _ocr_variants(crop_bgr: np.ndarray) -> List[np.ndarray]:
    """Few light preprocessions; prefer raw upscale over aggressive Otsu."""
    import cv2

    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    up = cv2.resize(gray, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
    return [up, 255 - up]


def ocr_tesseract_image(img: np.ndarray, *, psm: str = "7", whitelist: bool = True) -> str:
    """Run tesseract CLI on a grayscale/BGR image; return raw text."""
    import cv2

    tess = _require_bin("tesseract")
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    with tempfile.TemporaryDirectory(prefix="gvi_ocr_") as td:
        png = Path(td) / "roi.png"
        cv2.imwrite(str(png), img)
        cmd = [
            tess,
            str(png),
            "stdout",
            "-l",
            "eng",
            "--psm",
            psm,
            "--dpi",
            "300",
        ]
        if whitelist:
            cmd.extend(["-c", "tessedit_char_whitelist=0123456789:：-"])
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30)
        return (proc.stdout or "").strip()


def parse_scores_from_text(text: str) -> List[Tuple[int, int]]:
    found: List[Tuple[int, int]] = []
    for m in _SCORE_LOOSE.finditer(text or ""):
        a, b = int(m.group(1)), int(m.group(2))
        if a <= 15 and b <= 15:
            found.append((a, b))
    for line in (text or "").splitlines():
        ps = parse_score(line.strip())
        if ps and ps not in found:
            found.append(ps)
    return found


def _rank_score(
    sc: Tuple[int, int],
    *,
    prev: Optional[Tuple[int, int]],
) -> Tuple[int, int]:
    """Higher is better: prefer continuity / plus-one over wild jumps."""
    if prev is None:
        return (0, -abs(sc[0]) - abs(sc[1]))
    if sc == prev:
        return (3, 0)
    if _plus_one(prev, sc) is not None:
        return (2, 0)
    return (-1, -abs(sc[0] - prev[0]) - abs(sc[1] - prev[1]))


def read_score_from_frame(
    frame_bgr: np.ndarray,
    *,
    prev_score: Optional[Tuple[int, int]] = None,
) -> Dict[str, Any]:
    """OCR ROIs; return best score hypothesis or unknown/conflict."""
    votes: Counter = Counter()
    evidence: List[Dict[str, Any]] = []
    for name, crop in scoreboard_rois(frame_bgr):
        texts: List[str] = []
        scores_found: List[Tuple[int, int]] = []
        try:
            for var in _ocr_variants(crop):
                for psm in ("7", "6"):
                    text = ocr_tesseract_image(var, psm=psm, whitelist=True)
                    if text:
                        texts.append(text)
                    scores_found.extend(parse_scores_from_text(text))
                    if scores_found:
                        break
                if scores_found:
                    break
        except Exception as exc:  # noqa: BLE001
            evidence.append({"roi": name, "error": str(exc)[:120]})
            continue
        for sc in scores_found:
            votes[sc] += 1
        evidence.append(
            {
                "roi": name,
                "text": (texts[0] if texts else "")[:80],
                "scores": [f"{a}:{b}" for a, b in scores_found],
            }
        )
        # stop after first ROI that yielded football-like scores
        if scores_found:
            break
    if not votes:
        return {
            "status": "unknown",
            "score": None,
            "confidence": 0.0,
            "evidence": evidence,
        }
    ranked = sorted(votes.keys(), key=lambda s: (_rank_score(s, prev=prev_score), votes[s]), reverse=True)
    best = ranked[0]
    # reject wild OCR if prev known and neither same nor plus-one
    if prev_score is not None and best != prev_score and _plus_one(prev_score, best) is None:
        return {
            "status": "unknown",
            "score": None,
            "confidence": 0.0,
            "rejected": f"{best[0]}:{best[1]}",
            "reason": "not_same_or_plus_one_vs_prev",
            "evidence": evidence,
        }
    n = votes[best]
    total = sum(votes.values())
    conf = n / max(1, total)
    status = "ok" if conf >= 0.5 else "weak"
    return {
        "status": status,
        "score": f"{best[0]}:{best[1]}",
        "score_tuple": best,
        "confidence": round(conf, 3),
        "votes": {f"{a}:{b}": c for (a, b), c in votes.items()},
        "evidence": evidence,
    }


def sample_times(duration: float, *, step_sec: float, max_frames: int) -> List[float]:
    if duration <= 0:
        return []
    times = []
    t = 0.0
    while t < duration - 0.05 and len(times) < max_frames:
        times.append(round(t, 3))
        t += step_sec
    # always try near end
    end_t = max(0.0, duration - 1.0)
    if times and abs(times[-1] - end_t) > step_sec * 0.5 and len(times) < max_frames:
        times.append(round(end_t, 3))
    return times


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


def observations_to_score_nodes(
    observations: Sequence[Dict[str, Any]],
    *,
    confirm_hits: int = 2,
    confirm_window_sec: float = 120.0,
) -> Tuple[List[ScoreNode], List[Dict[str, Any]]]:
    """Debounce OCR observations into ScoreNode path (plus-one only)."""
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
        points.append((float(obs["t_sec"]), (int(st[0]), int(st[1])), float(obs.get("confidence") or 0)))
    points.sort(key=lambda x: x[0])
    diagnostics: List[Dict[str, Any]] = []
    if not points:
        return [], [{"note": "no_usable_score_observations"}]

    # opening: prefer first sustained 0:0 else first reading
    path: List[ScoreNode] = []
    zero = next((p for p in points if p[1] == (0, 0)), None)
    if zero:
        path.append(ScoreNode(t_sec=zero[0], score=(0, 0), opening=True, carrier_event_id=f"ocr@{zero[0]}"))
    else:
        t0, s0, _ = points[0]
        path.append(ScoreNode(t_sec=t0, score=s0, opening=True, carrier_event_id=f"ocr@{t0}"))

    for i, (t, sc, conf) in enumerate(points):
        prev = path[-1]
        if t < prev.t_sec:
            continue
        side = _plus_one(prev.score, sc)
        if side is None:
            if sc != prev.score:
                diagnostics.append(
                    {
                        "t_sec": t,
                        "from": f"{prev.score[0]}:{prev.score[1]}",
                        "to": f"{sc[0]}:{sc[1]}",
                        "rejected": "not_plus_one",
                    }
                )
            continue
        # confirm: enough hits of new score in window
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
    return path, diagnostics


def build_global_video_index(
    video: PathLike,
    *,
    out_dir: Optional[PathLike] = None,
    coarse_step_sec: float = 45.0,
    max_coarse_frames: int = 80,
    densify_radius_sec: float = 25.0,
    densify_step_sec: float = 5.0,
    max_dense_extra: int = 40,
    frame_width: int = 960,
    confirm_hits: int = 2,
    save_frames: bool = False,
) -> Dict[str, Any]:
    """Run P1 indexing. Writes JSON under out_dir when provided."""
    t0 = time.time()
    video_path = Path(video)
    media = probe_video(video_path)
    out: Optional[Path] = Path(out_dir) if out_dir else None
    frames_dir: Optional[Path] = None
    if out:
        out.mkdir(parents=True, exist_ok=True)
        if save_frames:
            frames_dir = out / "frames"
            frames_dir.mkdir(exist_ok=True)

    times = sample_times(media.duration_sec, step_sec=coarse_step_sec, max_frames=max_coarse_frames)
    observations: List[Dict[str, Any]] = []
    change_hints: List[float] = []
    last_score: Optional[Tuple[int, int]] = None
    errors: List[str] = []

    def _observe(t: float) -> None:
        nonlocal last_score
        try:
            frame = extract_frame_bgr(video_path, t, width=frame_width)
            if frames_dir is not None:
                import cv2

                cv2.imwrite(str(frames_dir / f"t{t:08.1f}.jpg"), frame)
            reading = read_score_from_frame(frame, prev_score=last_score)
            reading["t_sec"] = t
            observations.append(reading)
            st = reading.get("score_tuple")
            if reading.get("status") in ("ok", "weak") and st:
                if last_score is not None and st != last_score:
                    change_hints.append(t)
                last_score = st
        except Exception as exc:  # noqa: BLE001
            errors.append(f"t={t}:{exc}"[:160])
            observations.append({"t_sec": t, "status": "error", "score": None, "error": str(exc)[:120]})

    for t in times:
        _observe(t)

    # adaptive densify around suspected changes
    extra = densify_around(
        change_hints,
        media.duration_sec,
        radius=densify_radius_sec,
        step=densify_step_sec,
        existing=times,
        max_extra=max_dense_extra,
    )
    for t in extra:
        _observe(t)

    nodes, commit_diag = observations_to_score_nodes(
        observations, confirm_hits=confirm_hits
    )
    usable = sum(1 for o in observations if o.get("status") in ("ok", "weak"))
    opening_ok = bool(nodes) and nodes[0].score == (0, 0)
    degraded = usable == 0 or len(nodes) == 0 or not opening_ok or usable < max(2, len(observations) // 5)
    degrade_reasons: List[str] = []
    if usable == 0:
        degrade_reasons.append("no_usable_ocr")
    if len(nodes) == 0:
        degrade_reasons.append("empty_score_path")
    if nodes and not opening_ok:
        degrade_reasons.append("opening_not_0_0")
    if usable < max(2, len(observations) // 5):
        degrade_reasons.append("sparse_usable_ocr")

    score_timeline = {
        "schema": "video_driven_score_timeline_v1",
        "video": str(video_path),
        "duration_sec": media.duration_sec,
        "nodes": [n.to_dict() for n in nodes],
        "observation_count": len(observations),
        "usable_ocr_count": usable,
        "commit_diagnostics": commit_diag,
        "degraded": degraded,
        "degrade_reasons": degrade_reasons,
        "notes": [
            "t_sec is media PTS / seek time, not match clock",
            "scoreboard change time is confirmation observation, not goal action time",
            "semantic_verified=false",
            "broadcast OCR is best-effort; unknown/conflict preferred over invented scores",
        ],
        "semantic_verified": False,
    }

    index = {
        "schema": "video_driven_global_video_index_v1",
        "video": str(video_path.resolve()),
        "media": media.to_dict(),
        "teams_hypothesis": {
            "left": None,
            "right": None,
            "status": "unresolved",
            "note": "P1 MVP does not yet resolve team names from video alone",
        },
        "scoreboard": {
            "roi_policy": ["top_left", "top_center", "top_right", "bottom_left"],
            "ocr_engine": "tesseract_cli",
        },
        "sampling": {
            "coarse_step_sec": coarse_step_sec,
            "max_coarse_frames": max_coarse_frames,
            "n_coarse": len(times),
            "n_dense_extra": len(extra),
            "change_hints": change_hints,
        },
        "observations": observations,
        "anomalies": {
            "ocr_errors": errors[:50],
            "degraded": degraded,
        },
        "score_timeline_ref": "score_timeline.json",
        "elapsed_sec": round(time.time() - t0, 3),
        "semantic_verified": False,
        "gates": {
            "no_events_json": True,
            "no_causal_json": True,
            "no_paid_api": True,
        },
    }

    if out:
        (out / "global_video_index.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (out / "score_timeline.json").write_text(
            json.dumps(score_timeline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    index["score_timeline"] = score_timeline
    return index


def build_index_from_synthetic_observations(
    observations: Sequence[Dict[str, Any]],
    *,
    duration_sec: float = 0.0,
) -> Dict[str, Any]:
    """Test helper: skip video I/O; build timeline from synthetic OCR-like obs."""
    nodes, diag = observations_to_score_nodes(list(observations))
    return {
        "schema": "video_driven_score_timeline_v1",
        "video": None,
        "duration_sec": duration_sec,
        "nodes": [n.to_dict() for n in nodes],
        "observation_count": len(observations),
        "commit_diagnostics": diag,
        "degraded": len(nodes) == 0,
        "semantic_verified": False,
        "synthetic": True,
    }
