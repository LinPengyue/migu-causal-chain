"""Export short clips + keyframes for human review (not render-ready delivery)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not found")
    return exe


def export_candidate_review_pack(
    *,
    video: Path,
    records: List[Dict[str, Any]],
    frames_dir: Optional[Path],
    out_dir: Path,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    clips_dir = out_dir / "clips"
    keys_dir = out_dir / "keyframes"
    clips_dir.mkdir(parents=True, exist_ok=True)
    keys_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = _ffmpeg()
    exported: List[Dict[str, Any]] = []

    for i, rec in enumerate(records):
        eid = str(rec.get("candidate_event_id") or f"cand_{i}")
        start = rec.get("localized_media_in")
        end = rec.get("localized_media_out")
        if start is None or end is None:
            continue
        start_f, end_f = float(start), float(end)
        if end_f <= start_f:
            continue
        # pad slightly for review
        pad_in = max(0.0, start_f - 1.0)
        dur = max(0.5, (end_f + 1.0) - pad_in)
        clip_path = clips_dir / f"{eid}_{int(start_f)}_{int(end_f)}.mp4"
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{pad_in:.3f}",
            "-i",
            str(video),
            "-t",
            f"{dur:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-an",
            str(clip_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        key_copied = []
        for fid in rec.get("supporting_frame_ids") or []:
            if not frames_dir:
                break
            # frame files look like f_0000_1004110.jpg
            matches = list(Path(frames_dir).glob(f"{fid}*.jpg")) + list(
                Path(frames_dir).glob(f"*{fid}*.jpg")
            )
            for src in matches[:3]:
                dst = keys_dir / f"{eid}_{src.name}"
                if not dst.exists():
                    shutil.copy2(src, dst)
                key_copied.append(str(dst))
        exported.append(
            {
                "candidate_event_id": eid,
                "clip": str(clip_path) if proc.returncode == 0 else None,
                "ffmpeg_ok": proc.returncode == 0,
                "ffmpeg_stderr": (proc.stderr or "")[-300:],
                "media_in": start_f,
                "media_out": end_f,
                "keyframes": key_copied,
                "verification_status": rec.get("verification_status"),
                "grade": rec.get("grade"),
            }
        )

    manifest = {
        "schema": "v2_r2_review_pack_v1",
        "n_exported": len(exported),
        "items": exported,
        "render_ready": False,
        "note": "Human review packs only; not production delivery",
    }
    (out_dir / "review_pack_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest
