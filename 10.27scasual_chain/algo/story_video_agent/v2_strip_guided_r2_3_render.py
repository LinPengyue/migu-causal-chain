"""Render Round 2.3 clean + QC candidate story videos (preview only, render_ready=false)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from story_video_agent.media import probe_video
from story_video_agent.video_renderer import (
    DEFAULT_AUDIO_RATE,
    DEFAULT_FPS,
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    RenderError,
    _cut_segment,
    _font_file,
    _make_placeholder,
    _require_ffmpeg,
    _run_ffmpeg,
)


def _concat(ffmpeg: str, clip_paths: List[Path], out_mp4: Path) -> Dict[str, Any]:
    lst = out_mp4.parent / f"{out_mp4.stem}_concat.txt"
    lines = []
    for p in clip_paths:
        # ffmpeg concat demuxer
        esc = str(p).replace("'", "'\\''")
        lines.append(f"file '{esc}'")
    lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(lst),
        "-c",
        "copy",
        str(out_mp4),
    ]
    return _run_ffmpeg(cmd, label="concat")


def render_r23_candidates(
    *,
    video: Path,
    edl: Dict[str, Any],
    out_dir: Path,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    fps: int = DEFAULT_FPS,
) -> Dict[str, Any]:
    """Write story_clean_candidate.mp4 and story_qc_candidate.mp4."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = _require_ffmpeg()
    media = probe_video(video)
    has_audio = bool(media.audio_codec)
    work = out_dir / "_render_work"
    work.mkdir(parents=True, exist_ok=True)

    clean_clips: List[Path] = []
    qc_clips: List[Path] = []
    log: List[Dict[str, Any]] = []
    seg_meta: List[Dict[str, Any]] = []

    for i, seg in enumerate(edl.get("segments") or []):
        sid = str(seg.get("segment_id") or f"seg_{i}")
        clean_p = work / f"clean_{i:03d}_{sid}.mp4"
        qc_p = work / f"qc_{i:03d}_{sid}.mp4"
        eligibility = seg.get("render_eligibility")
        tin, tout = seg.get("media_in"), seg.get("media_out")

        meta = {
            "segment_id": sid,
            "beat": seg.get("beat"),
            "role": seg.get("role"),
            "source_node_ids": seg.get("source_node_ids"),
            "why": seg.get("why"),
            "time_status": seg.get("time_status"),
            "render_eligibility": eligibility,
        }

        # Title / missing → placeholder cards
        if eligibility in {"placeholder_title", "blocked"} or tin is None or tout is None:
            title = str(seg.get("title_text") or f"镜头待定位 | {sid}")
            lines_clean = [title]
            lines_qc = [
                "QC INTERNAL",
                title,
                f"beat={seg.get('beat')} role={seg.get('role')}",
                f"status={seg.get('time_status')} | render_ready=false",
            ]
            dur = float(seg.get("duration_sec") or 2.5)
            log.append(
                _make_placeholder(
                    ffmpeg=ffmpeg,
                    out_path=clean_p,
                    lines=lines_clean,
                    duration=dur,
                    width=width,
                    height=height,
                    fps=fps,
                )
            )
            log.append(
                _make_placeholder(
                    ffmpeg=ffmpeg,
                    out_path=qc_p,
                    lines=lines_qc,
                    duration=dur,
                    width=width,
                    height=height,
                    fps=fps,
                )
            )
            meta["placeholder"] = True
            clean_clips.append(clean_p)
            qc_clips.append(qc_p)
            seg_meta.append(meta)
            continue

        a, b = float(tin), float(tout)
        # Clean: no evidence overlay text
        log.append(
            _cut_segment(
                ffmpeg=ffmpeg,
                src=Path(media.path),
                media_in=a,
                media_out=b,
                out_path=clean_p,
                width=width,
                height=height,
                fps=fps,
                has_audio=has_audio,
                overlay_lines=[],
            )
        )
        # QC: node / source / evidence status
        qc_lines = [
            "QC INTERNAL | render_ready=false",
            f"{seg.get('beat')} | {sid}",
            f"nodes={','.join(seg.get('source_node_ids') or [])}",
            f"t={a:.1f}-{b:.1f} | {seg.get('time_status')} | {eligibility}",
        ]
        if seg.get("why"):
            qc_lines.append(str(seg.get("why"))[:80])
        log.append(
            _cut_segment(
                ffmpeg=ffmpeg,
                src=Path(media.path),
                media_in=a,
                media_out=b,
                out_path=qc_p,
                width=width,
                height=height,
                fps=fps,
                has_audio=has_audio,
                overlay_lines=qc_lines,
            )
        )
        meta.update({"cut": True, "media_in": a, "media_out": b, "placeholder": False})
        clean_clips.append(clean_p)
        qc_clips.append(qc_p)
        seg_meta.append(meta)

    clean_out = out_dir / "story_clean_candidate.mp4"
    qc_out = out_dir / "story_qc_candidate.mp4"
    log.append(_concat(ffmpeg, clean_clips, clean_out))
    log.append(_concat(ffmpeg, qc_clips, qc_out))

    manifest = {
        "schema": "v2_r23_render_manifest_v1",
        "story_clean_candidate": str(clean_out),
        "story_qc_candidate": str(qc_out),
        "n_segments": len(seg_meta),
        "segments": seg_meta,
        "ffmpeg_log_tail": log[-4:],
        "render_ready": False,
        "note": "Internal candidates only; natural audio kept when source has audio",
    }
    (out_dir / "render_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest
