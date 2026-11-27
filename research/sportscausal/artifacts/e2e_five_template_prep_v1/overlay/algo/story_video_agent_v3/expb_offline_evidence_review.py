"""Offline audit of the *existing* truncated Experiment B response and source JPEGs.

No provider imports, HTTP, model inference, EDL edits, or reconstruction of cut text.
Run against the actual saved raw response and source-bound image manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

ALLOWED = {
    "ACTIVE_PLAY_BEFORE", "GOAL_SHOT_NET", "IMMEDIATE_CELEBRATION",
    "POSSIBLE_PRE_GOAL_REPLAY", "PRE_GOAL_CELEBRATION",
    "LATER_SAME_ACTION_REPLAY", "MATCH_RESUMPTION",
}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def extract_complete_objects(raw: str) -> list[dict[str, Any]]:
    """Only JSON objects completely terminated inside the observations array.

    Duplicate phases remain separate; incomplete trailing objects are never fixed.
    """
    decoder = json.JSONDecoder()
    pos = raw.find('"observations"')
    if pos < 0:
        return []
    pos = raw.find("[", pos)
    if pos < 0:
        return []
    pos += 1
    out = []
    while pos < len(raw):
        while pos < len(raw) and raw[pos] in " \t\r\n,":
            pos += 1
        if pos >= len(raw) or raw[pos] != "{":
            break
        try:
            item, end = decoder.raw_decode(raw, pos)
        except json.JSONDecodeError:
            break
        if not isinstance(item, dict):
            break
        out.append(item)
        pos = end
    return out


def review(*, response: Path, frames_manifest: Path, source_sha: str,
           out_dir: Path, expected_response_sha: str | None = None) -> dict:
    if out_dir.exists():
        raise ValueError("refuse_overwrite_output_dir")
    if not response.is_file() or not frames_manifest.is_file():
        raise ValueError("missing_raw_response_or_frame_manifest")
    actual_response_sha = sha256_file(response)
    if expected_response_sha and actual_response_sha != expected_response_sha:
        raise ValueError("raw_response_sha_mismatch")
    data = json.loads(frames_manifest.read_text(encoding="utf-8"))
    frames = data.get("image_frames")
    if not isinstance(frames, list) or not frames:
        raise ValueError("missing_image_frames")
    if str(data.get("source_sha256")) != source_sha:
        raise ValueError("source_sha_mismatch")
    by_id = {}
    for frame in frames:
        fid = str(frame["frame_id"])
        p = Path(frame.get("path") or frame.get("local_path_not_committed") or "")
        if fid in by_id or not p.is_file() or sha256_file(p) != frame["sha256"]:
            raise ValueError("duplicate_missing_or_changed_frame:" + fid)
        by_id[fid] = (frame, p)
    raw = response.read_text(encoding="utf-8")
    complete = extract_complete_objects(raw)
    observations = []
    for i, row in enumerate(complete):
        fid = str(row.get("frame_id") or "")
        phase = str(row.get("phase") or "")
        cue = str(row.get("visible_cue") or "")
        try:
            pts = float(row["source_pts_sec"])
        except (KeyError, TypeError, ValueError):
            pts = None
        valid = (
            phase in ALLOWED and fid in by_id and pts is not None
            and abs(pts - float(by_id[fid][0]["actual_media_sec"])) <= .05
            and len(cue.strip()) >= 12
        )
        observations.append({
            "index": i, "phase": phase, "frame_id": fid, "claimed_pts": pts,
            "visible_cue_original": cue, "citation_valid": valid,
            "visual_truth_verified": False,
            "source_frame_sha256": by_id[fid][0]["sha256"] if fid in by_id else None,
            "note": "model_claim_only_not_human_or_video_verified",
        })
    counts = {}
    for o in observations:
        counts[o["phase"]] = counts.get(o["phase"], 0) + 1
    out_dir.mkdir(parents=True)
    report = {
        "schema": "expb_offline_partial_evidence_review_v1",
        "status": "PARTIAL_MODEL_CITATIONS_NOT_VISUAL_VERIFICATION",
        "source_sha256": source_sha, "raw_response_sha256": actual_response_sha,
        "n_complete_observations": len(observations),
        "duplicate_phases_preserved": sorted(k for k, v in counts.items() if v > 1),
        "trailing_incomplete_observation_ignored": True,
        "observations": observations, "frame_count": len(frames),
        "first_live_verified": False, "edl_modified": False,
        "api_calls": 0, "no_inference": True,
        "replay_identity": "UNVERIFIED_REQUIRES_VISUAL_COMPARISON",
    }
    (out_dir / "offline_review.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # Contact sheet preserves frame IDs and source PTS. Never use image ordering as
    # proof of continuous temporal action.
    try:
        from PIL import Image, ImageDraw, ImageOps
        from math import ceil
        w, h, cols = 380, 270, 3
        ordered = sorted(frames, key=lambda x: float(x["actual_media_sec"]))
        sheet = Image.new("RGB", (w * cols, h * ceil(len(ordered) / cols)), "white")
        draw = ImageDraw.Draw(sheet)
        for i, frame in enumerate(ordered):
            fid = frame["frame_id"]
            with Image.open(by_id[fid][1]) as im:
                thumb = ImageOps.contain(im.convert("RGB"), (w - 12, h - 40))
                x, y = (i % cols) * w, (i // cols) * h
                sheet.paste(thumb, (x + (w - thumb.width) // 2, y + 3))
                draw.text((x + 8, y + h - 32),
                          "%s  PTS=%.3fs" % (fid, frame["actual_media_sec"]),
                          fill="black")
        sheet.save(out_dir / "contact_sheet.jpg", quality=92)
        report["contact_sheet_sha256"] = sha256_file(out_dir / "contact_sheet.jpg")
    except ImportError:
        report["contact_sheet_error"] = "Pillow_unavailable"
    (out_dir / "offline_review.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--raw-response", type=Path, required=True)
    p.add_argument("--frames-manifest", type=Path, required=True)
    p.add_argument("--source-sha256", required=True)
    p.add_argument("--expected-response-sha256")
    p.add_argument("--out-dir", type=Path, required=True)
    a = p.parse_args()
    result = review(
        response=a.raw_response, frames_manifest=a.frames_manifest,
        source_sha=a.source_sha256, out_dir=a.out_dir,
        expected_response_sha=a.expected_response_sha256,
    )
    print(json.dumps({
        "status": result["status"], "n_complete_observations": result["n_complete_observations"],
        "api_calls": 0, "first_live_verified": False,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
