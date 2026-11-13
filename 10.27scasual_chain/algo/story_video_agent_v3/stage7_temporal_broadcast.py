"""Zero-HTTP broadcast temporal diagnostics using original video only.

This is NOT an automatic FIRST_LIVE verifier. Shot changes and replay
candidates are evidence for subsequent phase analysis, never sufficient
to unlock EDL. Works on Python 3.9.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import cv2
import numpy as np


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def _frame_features(frame: np.ndarray) -> Dict[str, Any]:
    """Downsampled image for temporal discontinuity, no OCR/model."""
    small = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [24, 16], [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    return {"hist": hist, "gray": cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)}


def _change(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, float]:
    # Histogram and grayscale difference measure cut likelihood, NOT replay.
    h = float(cv2.compareHist(a["hist"], b["hist"], cv2.HISTCMP_BHATTACHARYYA))
    d = float(np.mean(cv2.absdiff(a["gray"], b["gray"]))) / 255.0
    return {"hist_distance": round(h, 5), "pixel_change": round(d, 5)}


def analyze(
    *,
    source_mp4: Path,
    stage4_queue: Path,
    out_dir: Path,
    step_sec: float = 0.5,
    context_sec: float = 25.0,
) -> Dict[str, Any]:
    if out_dir.exists():
        raise FileExistsError("refuse_overwrite")
    if not 0.2 <= step_sec <= 2:
        raise ValueError("step_sec_out_of_bounds")
    if not 8 <= context_sec <= 45:
        raise ValueError("context_sec_out_of_bounds")
    q = json.loads(stage4_queue.read_text(encoding="utf-8"))
    if q.get("schema") != "v3a_stage4_first_live_review_queue_v1":
        raise ValueError("wrong_queue_schema")
    sha = _sha(source_mp4)
    if sha != q.get("source_sha256"):
        raise ValueError("source_sha_mismatch")
    observations = []
    for o in q.get("semantic_observations") or []:
        try:
            shot, net = float(o["shot_sec"]), float(o["net_sec"])
            if 0 <= shot < net and o.get("shot_frame_ids") and o.get("net_frame_ids"):
                observations.append((shot, net))
        except (ValueError, TypeError, KeyError):
            continue
    if not observations:
        raise ValueError("missing_source_cited_shot_net")
    shot = min(x[0] for x in observations)
    net = max(x[1] for x in observations)
    mi = max(0.0, shot - context_sec)
    mo = net + context_sec
    cap = cv2.VideoCapture(str(source_mp4))
    if not cap.isOpened():
        raise RuntimeError("cannot_open_original_video")
    changes: List[Dict[str, Any]] = []
    decoded = 0
    attempted = 0
    prev = None
    prev_t = None
    try:
        t = mi
        while t <= mo + 1e-6:
            attempted += 1
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, fr = cap.read()
            if ok:
                decoded += 1
                features = _frame_features(fr)
                if prev is not None:
                    delta = _change(prev, features)
                    changes.append({
                        "pts_from": round(prev_t, 3),
                        "pts_to": round(t, 3),
                        **delta,
                    })
                prev, prev_t = features, t
            else:
                prev, prev_t = None, None
            t += step_sec
    finally:
        cap.release()
    if changes:
        hist = np.asarray([x["hist_distance"] for x in changes], dtype=np.float64)
        pix = np.asarray([x["pixel_change"] for x in changes], dtype=np.float64)
        # Adaptive percentile produces *candidates*, not classifications.
        hist_threshold = float(np.quantile(hist, 0.9))
        pix_threshold = float(np.quantile(pix, 0.9))
        cut_candidates = [
            x for x in changes
            if x["hist_distance"] >= hist_threshold
            and x["pixel_change"] >= pix_threshold
        ]
    else:
        hist_threshold = pix_threshold = None
        cut_candidates = []
    out_dir.mkdir(parents=True)
    report = {
        "schema": "v3a_stage7_temporal_broadcast_diagnostics_v1",
        "source_sha256": sha,
        "stage4_queue_sha256": _sha(stage4_queue),
        "issue_id": q["issue_id"],
        "source_window": [round(mi, 3), round(mo, 3)],
        "shot_net_pts": [shot, net],
        "sampling_step_sec": step_sec,
        "attempted_frames": attempted,
        "decoded_frames": decoded,
        "coverage_fraction": round(decoded / attempted, 4) if attempted else 0,
        "cut_candidates": cut_candidates,
        "thresholds": {
            "hist_distance_p90": hist_threshold,
            "pixel_change_p90": pix_threshold,
        },
        "all_frame_deltas": changes,
        "ocr_required": False,
        "first_live_verified": False,
        "edl_repaired": False,
        "http_requests": 0,
        "status": "BROADCAST_CUT_CANDIDATES_ONLY",
        "limitations": [
            "shot cuts alone cannot distinguish live from replay",
            "camera change does not prove slow motion or a replay",
            "no earlier same-action sequence verification in this module",
            "percentile thresholds are diagnostic and uncalibrated",
        ],
    }
    (out_dir / "temporal_broadcast_diagnostics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--source-mp4", type=Path, required=True)
    p.add_argument("--stage4-queue", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--step-sec", type=float, default=0.5)
    a = p.parse_args(argv)
    result = analyze(
        source_mp4=a.source_mp4, stage4_queue=a.stage4_queue,
        out_dir=a.out_dir, step_sec=a.step_sec,
    )
    print(json.dumps({
        "status": result["status"],
        "coverage_fraction": result["coverage_fraction"],
        "cut_candidates": len(result["cut_candidates"]),
        "first_live_verified": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
