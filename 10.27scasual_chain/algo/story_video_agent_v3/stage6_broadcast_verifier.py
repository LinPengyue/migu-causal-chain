"""Video-first broadcast audit; OCR is OPTIONAL, never a hard prerequisite.

The algorithm compares source-bound frames of the goal action with frames
from an earlier broadcast interval. It identifies earlier near-duplicates
but does not claim that a negative retrieval proves first-live. Zero HTTP.
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


def _hash_frame(frame: np.ndarray) -> int:
    """64-bit DCT perceptual hash; intentionally independent of scoreboard OCR."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(np.float32(gray))
    block = dct[:8, :8].copy()
    vals = block.flatten()[1:]
    med = float(np.median(vals))
    bits = (block.flatten() >= med).astype(np.uint8)
    result = 0
    for bit in bits:
        result = (result << 1) | int(bit)
    return result


def _read_at(cap: cv2.VideoCapture, sec: float) -> Optional[np.ndarray]:
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, sec) * 1000.0)
    ok, frame = cap.read()
    return frame if ok else None


def _distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def audit(
    *,
    source_mp4: Path,
    stage4_queue: Path,
    out_dir: Path,
    scan_step_sec: float = 1.0,
    earlier_lookback_sec: float = 180.0,
    hamming_threshold: int = 8,
) -> Dict[str, Any]:
    if out_dir.exists():
        raise FileExistsError("refuse_overwrite")
    if not (0.25 <= scan_step_sec <= 4.0):
        raise ValueError("scan_step_out_of_bounds")
    if not (30 <= earlier_lookback_sec <= 900):
        raise ValueError("lookback_out_of_bounds")
    if not (0 <= hamming_threshold <= 16):
        raise ValueError("hamming_threshold_out_of_bounds")
    q = json.loads(stage4_queue.read_text(encoding="utf-8"))
    if q.get("schema") != "v3a_stage4_first_live_review_queue_v1":
        raise ValueError("wrong_queue_schema")
    source_sha = _sha(source_mp4)
    if source_sha != q.get("source_sha256"):
        raise ValueError("source_sha_mismatch")
    observations = q.get("semantic_observations") or []
    times = []
    for o in observations:
        try:
            a, b = float(o["shot_sec"]), float(o["net_sec"])
            if a < b and o.get("shot_frame_ids") and o.get("net_frame_ids"):
                times.append((a, b))
        except (KeyError, ValueError, TypeError):
            continue
    if not times:
        raise ValueError("missing_cited_goal_action")
    shot = min(x[0] for x in times)
    net = max(x[1] for x in times)
    if not (float(q["source_pts_start"]) <= shot < net <= float(q["source_pts_end"])):
        raise ValueError("goal_action_outside_candidate")
    cap = cv2.VideoCapture(str(source_mp4))
    if not cap.isOpened():
        raise RuntimeError("cannot_open_original_video")
    try:
        # Sample the action, not the entire candidate's generic pitch imagery.
        targets = [shot + (net - shot) * i / 4 for i in range(5)]
        goal_hashes = []
        for t in targets:
            fr = _read_at(cap, t)
            if fr is None:
                raise RuntimeError("cannot_decode_goal_frame")
            goal_hashes.append(_hash_frame(fr))
        # The earlier window is derived from candidate PTS, never Gold.
        # Exclude the candidate's immediate lead-in to avoid self-matches.
        scan_end = max(0.0, float(q["source_pts_start"]) - 2.0)
        scan_start = max(0.0, scan_end - earlier_lookback_sec)
        matches: List[Dict[str, Any]] = []
        attempted, decoded = 0, 0
        t = scan_start
        while t < scan_end - 1e-6:
            attempted += 1
            fr = _read_at(cap, t)
            if fr is not None:
                decoded += 1
                ph = _hash_frame(fr)
                distances = [_distance(ph, h) for h in goal_hashes]
                best = min(distances)
                if best <= hamming_threshold:
                    matches.append({
                        "earlier_pts_sec": round(t, 3),
                        "goal_sample_pts_sec": round(targets[distances.index(best)], 3),
                        "hamming_distance": best,
                    })
            t += scan_step_sec
    finally:
        cap.release()
    # pHash is a retrieval hint, not a semantic proof of the same action.
    # Similar football pitch frames can be false positives; missing a replay
    # can be a false negative due to camera angle, compression, or sampling.
    out_dir.mkdir(parents=True)
    report = {
        "schema": "v3a_stage6_video_broadcast_audit_v1",
        "source_sha256": source_sha,
        "stage4_queue_sha256": _sha(stage4_queue),
        "issue_id": q["issue_id"],
        "candidate_id": q["candidate_id"],
        "goal_action_pts": {"shot": shot, "net": net},
        "earlier_scan_pts": [scan_start, scan_end],
        "scan_step_sec": scan_step_sec,
        "attempted_frames": attempted,
        "decoded_frames": decoded,
        "coverage_fraction": round(decoded / attempted, 4) if attempted else 0.0,
        "hamming_threshold": hamming_threshold,
        "near_duplicate_matches": sorted(matches, key=lambda x: x["hamming_distance"])[:100],
        "ocr_required": False,
        "same_action_replay_confirmed": False,
        "first_live_verified": False,
        "edl_repaired": False,
        "http_requests": 0,
        "status": (
            "EARLIER_VISUAL_SIMILARITY_REVIEW_REQUIRED"
            if matches else "NO_EARLIER_PHASH_MATCH_WITHIN_SCANNED_WINDOW"
        ),
        "limitations": [
            "perceptual hash is not action identity or replay classification",
            "negative match in a bounded window is not first-live proof",
            "unscanned earlier footage may contain the same action",
            "shot and net are existing real-model observations, not Gold",
        ],
    }
    (out_dir / "video_broadcast_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Zero-HTTP OCR-optional broadcast video audit")
    p.add_argument("--source-mp4", type=Path, required=True)
    p.add_argument("--stage4-queue", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--scan-step-sec", type=float, default=1.0)
    p.add_argument("--earlier-lookback-sec", type=float, default=180.0)
    a = p.parse_args(argv)
    r = audit(source_mp4=a.source_mp4, stage4_queue=a.stage4_queue,
              out_dir=a.out_dir, scan_step_sec=a.scan_step_sec,
              earlier_lookback_sec=a.earlier_lookback_sec)
    print(json.dumps({k: r[k] for k in (
        "status", "coverage_fraction", "first_live_verified",
        "edl_repaired", "http_requests"
    )}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
