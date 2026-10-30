"""R2.8 visual QC: gray + color-band / macroblock / local color-rupture detection.

Gray-only scans (R2.7) missed obvious source band glitches. This module keeps
candidates + evidence paths and never upgrades to render_ready=true.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _grab_frame(video: Path, t: float, dest: Path) -> bool:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    ts = float(t)
    if ts > 3.0:
        coarse = max(0.0, ts - 3.0)
        fine = ts - coarse
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{coarse:.3f}",
            "-i",
            str(video),
            "-ss",
            f"{fine:.3f}",
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(dest),
        ]
    else:
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{ts:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(dest),
        ]
    subprocess.run(cmd, capture_output=True, check=False)
    return dest.is_file() and dest.stat().st_size >= 1000


def frame_corruption_features(im) -> Dict[str, float]:
    """Spatial features for band / macroblock / neon color rupture."""
    import numpy as np

    h, w, _ = im.shape
    y0, y1 = int(0.12 * h), int(0.78 * h)
    mid = im[y0:y1]
    r, g, b = mid[:, :, 0], mid[:, :, 1], mid[:, :, 2]

    magenta = ((r > 145) & (b > 145) & (g < 115)).mean()
    cyan = ((g > 145) & (b > 145) & (r < 115)).mean()
    neon_green = ((g > 190) & (r < 120) & (b < 140) & ((g - r) > 70)).mean()
    orange = ((r > 170) & (g > 90) & (g < 175) & (b < 70)).mean()
    neon = float(magenta + cyan + neon_green + orange)

    # 8x8 block-edge energy (macroblock discontinuities)
    bh, bw = h // 8, w // 8
    blk = im[: bh * 8, : bw * 8].reshape(bh, 8, bw, 8, 3).mean((1, 3))
    block_edge = float(
        np.abs(np.diff(blk, axis=1)).mean() + np.abs(np.diff(blk, axis=0)).mean()
    )

    # Horizontal neon band rows (upper/mid): saturated magenta/cyan density per row
    chroma = im.max(2) - im.min(2)
    mag_row = ((im[:, :, 0] > 145) & (im[:, :, 2] > 145) & (im[:, :, 1] < 115)).mean(1)
    cyn_row = ((im[:, :, 1] > 145) & (im[:, :, 2] > 145) & (im[:, :, 0] < 115)).mean(1)
    neon_row = mag_row + cyn_row
    # focus rows away from scorebug extremes
    band_zone = neon_row[int(0.08 * h) : int(0.55 * h)]
    band_rows = int((band_zone > 0.04).sum())
    band_peak = float(band_zone.max()) if len(band_zone) else 0.0

    # Local high-gradient smear proxy on mid pitch
    gx = np.abs(np.diff(mid.mean(2), axis=1))
    high_gx = float((gx > 45).mean())

    std = float(im.std())
    mean = float(im.mean())
    return {
        "std": std,
        "mean": mean,
        "neon": neon,
        "magenta": float(magenta),
        "cyan": float(cyan),
        "neon_green": float(neon_green),
        "block_edge": block_edge,
        "band_rows": float(band_rows),
        "band_peak": band_peak,
        "high_gx": high_gx,
        "chroma_mean": float(chroma.mean()),
    }


def classify_frame_features(
    feat: Dict[str, float],
    *,
    gray_std_thresh: float = 8.0,
    prev_feat: Optional[Dict[str, float]] = None,
) -> Tuple[Optional[str], float, Dict[str, Any]]:
    """Return (kind|None, score, detail). Conservative: obvious examples must BLOCK."""
    detail: Dict[str, Any] = dict(feat)
    if feat["std"] < gray_std_thresh:
        return "near_uniform_gray", 10.0, detail

    score = 0.0
    reasons: List[str] = []

    # Strong neon + macroblock edges (classic HEVC salad / band glitch)
    if feat["neon"] >= 0.006 and feat["block_edge"] >= 16.5:
        score += 6.0 + min(feat["neon"] * 80.0, 6.0)
        reasons.append("neon_with_macroblock_edges")
    elif feat["neon"] >= 0.018:
        score += 5.0 + min(feat["neon"] * 40.0, 5.0)
        reasons.append("high_neon_color_rupture")

    # Horizontal color band strip
    if feat["band_rows"] >= 6 and feat["band_peak"] >= 0.05 and feat["neon"] >= 0.004:
        score += 4.0 + min(feat["band_rows"] / 10.0, 3.0)
        reasons.append("horizontal_neon_band_rows")

    # Extreme block edges alone are insufficient (fast motion); require neon or bands
    if feat["block_edge"] >= 18.5 and (feat["neon"] >= 0.004 or feat["band_rows"] >= 4):
        score += 3.0
        reasons.append("extreme_block_edge_with_color_anomaly")

    # Temporal local jump with neon persistence
    if prev_feat is not None:
        d_neon = abs(feat["neon"] - prev_feat["neon"])
        d_blk = abs(feat["block_edge"] - prev_feat["block_edge"])
        if feat["neon"] >= 0.005 and d_blk >= 3.0 and d_neon >= 0.003:
            score += 2.5
            reasons.append("temporal_neon_block_jump")

    detail["score"] = round(score, 3)
    detail["reasons"] = reasons
    if score >= 4.0:
        kind = reasons[0] if reasons else "spatial_corruption_candidate"
        return kind, score, detail
    return None, score, detail


def sample_times(
    *,
    start_sec: float,
    end_sec: float,
    step_sec: float,
    dense_ranges: Optional[Sequence[Dict[str, float]]] = None,
) -> List[float]:
    times: List[float] = []
    t = float(start_sec)
    while t <= float(end_sec) - 0.01:
        times.append(round(t, 3))
        t += float(step_sec)
    for rng in dense_ranges or []:
        a, b = float(rng["start"]), float(rng["end"])
        step = float(rng.get("step", 0.1))
        u = a
        while u <= b + 1e-9:
            times.append(round(u, 3))
            u += step
    return sorted(set(times))


def detect_visual_corruption(
    *,
    video: Path,
    start_sec: float = 0.0,
    end_sec: Optional[float] = None,
    step_sec: float = 1.0,
    dense_ranges: Optional[Sequence[Dict[str, float]]] = None,
    out_dir: Optional[Path] = None,
    gray_std_thresh: float = 8.0,
) -> Dict[str, Any]:
    """Full visual scan: gray + band/macroblock/color rupture. render_ready always false."""
    import numpy as np
    from PIL import Image

    from story_video_agent.media import probe_video

    video = Path(video)
    probe = probe_video(video)
    end = float(end_sec if end_sec is not None else probe.duration_sec)
    times = sample_times(
        start_sec=start_sec, end_sec=end, step_sec=step_sec, dense_ranges=dense_ranges
    )
    out_dir = Path(out_dir) if out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    anomalies: List[Dict[str, Any]] = []
    candidates: List[Dict[str, Any]] = []
    samples: List[Dict[str, Any]] = []
    prev_feat: Optional[Dict[str, float]] = None

    for ts in times:
        dest = (out_dir / f"t_{ts:.3f}.jpg") if out_dir else Path("/tmp/_r28_qc_frame.jpg")
        ok = _grab_frame(video, ts, dest)
        if not ok:
            row = {"t": ts, "kind": "missing_or_tiny_frame"}
            anomalies.append(row)
            candidates.append(row)
            continue
        im = np.asarray(Image.open(dest).convert("RGB"), dtype=np.float32)
        feat = frame_corruption_features(im)
        kind, score, detail = classify_frame_features(
            feat, gray_std_thresh=gray_std_thresh, prev_feat=prev_feat
        )
        sample = {
            "t": ts,
            "std": round(feat["std"], 2),
            "mean": round(feat["mean"], 2),
            "neon": round(feat["neon"], 4),
            "block_edge": round(feat["block_edge"], 2),
            "band_rows": int(feat["band_rows"]),
            "score": round(score, 3),
            "frame": str(dest) if out_dir else None,
        }
        samples.append(sample)
        if kind:
            hit = {
                "t": ts,
                "kind": kind,
                "score": round(score, 3),
                "reasons": detail.get("reasons", []),
                "neon": round(feat["neon"], 4),
                "block_edge": round(feat["block_edge"], 2),
                "band_rows": int(feat["band_rows"]),
                "std": round(feat["std"], 2),
                "evidence_frame": str(dest) if out_dir else None,
            }
            anomalies.append(hit)
            candidates.append(hit)
        elif score >= 2.0:
            candidates.append(
                {
                    "t": ts,
                    "kind": "soft_candidate_below_block",
                    "score": round(score, 3),
                    "neon": round(feat["neon"], 4),
                    "block_edge": round(feat["block_edge"], 2),
                    "band_rows": int(feat["band_rows"]),
                    "evidence_frame": str(dest) if out_dir else None,
                }
            )
        prev_feat = feat

    gray_hits = [a for a in anomalies if a.get("kind") == "near_uniform_gray"]
    band_hits = [a for a in anomalies if a.get("kind") != "near_uniform_gray"]
    blocked = len(anomalies) > 0
    return {
        "schema": "v2_r28_visual_corruption_scan_v1",
        "video": str(video),
        "n_samples": len(samples),
        "n_anomalies": len(anomalies),
        "n_gray_anomalies": len(gray_hits),
        "n_band_macroblock_anomalies": len(band_hits),
        "n_soft_candidates": len(candidates),
        "anomalies": anomalies,
        "candidates": candidates,
        "samples_head": samples[:12],
        "samples_tail": samples[-8:],
        "coverage": {
            "start_sec": start_sec,
            "end_sec": end,
            "step_sec": step_sec,
            "dense_ranges": list(dense_ranges or []),
            "note": "Frame count alone does not prove visual integrity; band/macroblock must also be clear.",
        },
        "gates": {
            "gray_clean": len(gray_hits) == 0,
            "band_macroblock_clean": len(band_hits) == 0,
            "visual_qc_pass": False,  # never auto-pass for delivery
            "blocked_source_corruption": blocked,
            "render_ready": False,
        },
        "render_ready": False,
    }


def assert_negative_ranges_detected(
    scan: Dict[str, Any],
    must_hit_ranges: Sequence[Tuple[float, float]],
) -> Dict[str, Any]:
    """Regression: known corrupt windows must produce at least one anomaly."""
    hits = []
    misses = []
    times = [float(a["t"]) for a in scan.get("anomalies") or []]
    for a, b in must_hit_ranges:
        ok = any(a - 1e-6 <= t <= b + 1e-6 for t in times)
        (hits if ok else misses).append({"start": a, "end": b, "detected": ok})
    return {
        "all_negatives_detected": len(misses) == 0,
        "hits": hits,
        "misses": misses,
        "n_anomalies_in_scan": scan.get("n_anomalies"),
        "n_gray_only": scan.get("n_gray_anomalies"),
        "policy": "gray_zero_is_insufficient_when_band_negatives_exist",
    }


def write_json(path: Path, obj: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
