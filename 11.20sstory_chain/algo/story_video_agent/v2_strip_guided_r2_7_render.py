"""R2.7 robust render: accurate HEVC seek + filter-concat re-encode (no stream-copy concat)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from story_video_agent.media import probe_video
from story_video_agent.video_renderer import (
    DEFAULT_AUDIO_RATE,
    DEFAULT_FPS,
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    _cut_segment,
    _make_placeholder,
    _require_ffmpeg,
    _run_ffmpeg,
)


def _filter_concat_reencode(
    *,
    ffmpeg: str,
    clip_paths: Sequence[Path],
    out_mp4: Path,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    fps: int = DEFAULT_FPS,
) -> Dict[str, Any]:
    """Concat via filter_complex and re-encode — avoids -c copy timestamp/GOP seams."""
    if not clip_paths:
        raise ValueError("no clips to concat")
    out_mp4 = Path(out_mp4)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    cmd: List[str] = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for p in clip_paths:
        cmd += ["-i", str(p)]
    n = len(clip_paths)
    vlabels = "".join(f"[{i}:v][{i}:a]" for i in range(n))
    filt = (
        f"{vlabels}concat=n={n}:v=1:a=1[v][a];"
        f"[v]scale={width}:{height}:flags=lanczos,fps={fps},format=yuv420p[vout]"
    )
    cmd += [
        "-filter_complex",
        filt,
        "-map",
        "[vout]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-force_key_frames",
        "expr:eq(n,0)",
        "-c:a",
        "aac",
        "-ar",
        str(DEFAULT_AUDIO_RATE),
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(out_mp4),
    ]
    return _run_ffmpeg(cmd, label=f"filter_concat:{out_mp4.name}")


def cut_segment_r27(
    *,
    ffmpeg: str,
    src: Path,
    media_in: float,
    media_out: float,
    out_path: Path,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    fps: int = DEFAULT_FPS,
    has_audio: bool = True,
    overlay_lines: Optional[Sequence[str]] = None,
    seek_pad_sec: float = 30.0,
) -> Dict[str, Any]:
    """Cut with longer HEVC pad; same normalize path as R2.3 but safer seek defaults."""
    return _cut_segment(
        ffmpeg=ffmpeg,
        src=src,
        media_in=float(media_in),
        media_out=float(media_out),
        out_path=Path(out_path),
        width=width,
        height=height,
        fps=fps,
        has_audio=has_audio,
        overlay_lines=list(overlay_lines or []),
        accurate_seek=True,
        seek_pad_sec=seek_pad_sec,
    )


def render_r27_candidates(
    *,
    video: Path,
    edl: Dict[str, Any],
    out_dir: Path,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    fps: int = DEFAULT_FPS,
) -> Dict[str, Any]:
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
        meta: Dict[str, Any] = {
            "segment_id": sid,
            "beat": seg.get("beat"),
            "role": seg.get("role"),
            "source_node_ids": seg.get("source_node_ids"),
            "why": seg.get("why"),
            "render_eligibility": eligibility,
        }
        if eligibility in {"placeholder_title", "blocked"} or tin is None or tout is None:
            # R2.7: do not emit tech-status end cards into the clean story.
            if seg.get("omit_from_clean"):
                meta["omitted_from_clean"] = True
                seg_meta.append(meta)
                continue
            title = str(seg.get("title_text") or f"镜头待定位 | {sid}")
            dur = float(seg.get("duration_sec") or 2.5)
            # Only allow non-tech titles in clean if explicitly story-facing.
            if seg.get("story_facing_title"):
                log.append(
                    _make_placeholder(
                        ffmpeg=ffmpeg,
                        out_path=clean_p,
                        lines=[title],
                        duration=dur,
                        width=width,
                        height=height,
                        fps=fps,
                    )
                )
                clean_clips.append(clean_p)
            log.append(
                _make_placeholder(
                    ffmpeg=ffmpeg,
                    out_path=qc_p,
                    lines=["QC INTERNAL", title, "render_ready=false"],
                    duration=dur,
                    width=width,
                    height=height,
                    fps=fps,
                )
            )
            qc_clips.append(qc_p)
            meta["placeholder"] = True
            seg_meta.append(meta)
            continue

        a, b = float(tin), float(tout)
        log.append(
            cut_segment_r27(
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
        qc_lines = [
            "QC INTERNAL | render_ready=false",
            f"{seg.get('beat')} | {sid}",
            f"t={a:.1f}-{b:.1f}",
        ]
        log.append(
            cut_segment_r27(
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
    log.append(_filter_concat_reencode(ffmpeg=ffmpeg, clip_paths=clean_clips, out_mp4=clean_out))
    log.append(_filter_concat_reencode(ffmpeg=ffmpeg, clip_paths=qc_clips, out_mp4=qc_out))

    manifest = {
        "schema": "v2_r27_render_manifest_v1",
        "story_clean_candidate": str(clean_out),
        "story_qc_candidate": str(qc_out),
        "n_segments": len(seg_meta),
        "n_clean_clips": len(clean_clips),
        "segments": seg_meta,
        "concat_mode": "filter_complex_reencode",
        "seek_pad_sec": 30.0,
        "ffmpeg_log_tail": log[-6:],
        "render_ready": False,
        "note": "R2.7: filter-concat re-encode; tech end cards omitted from clean when flagged",
    }
    (out_dir / "render_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def detect_gray_or_corrupt_frames(
    *,
    video: Path,
    start_sec: float = 0.0,
    end_sec: Optional[float] = None,
    step_sec: float = 1.0,
    dense_ranges: Optional[Sequence[Dict[str, float]]] = None,
    out_dir: Optional[Path] = None,
    gray_std_thresh: float = 8.0,
) -> Dict[str, Any]:
    """Sample frames and flag near-uniform gray / ultra-low-detail drops."""
    import numpy as np
    from PIL import Image

    video = Path(video)
    probe = probe_video(video)
    end = float(end_sec if end_sec is not None else probe.duration_sec)
    times: List[float] = []
    t = float(start_sec)
    while t <= end - 0.01:
        times.append(round(t, 3))
        t += step_sec
    for rng in dense_ranges or []:
        a, b = float(rng["start"]), float(rng["end"])
        step = float(rng.get("step", 0.2))
        u = a
        while u <= b:
            times.append(round(u, 3))
            u += step
    times = sorted(set(times))
    out_dir = Path(out_dir) if out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    anomalies: List[Dict[str, Any]] = []
    samples: List[Dict[str, Any]] = []
    for ts in times:
        dest = (out_dir / f"t_{ts:.3f}.jpg") if out_dir else Path("/tmp/_r27_qc_frame.jpg")
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{ts:.3f}", "-i", str(video), "-frames:v", "1", "-q:v", "3", str(dest)],
            capture_output=True,
            check=False,
        )
        if not dest.is_file() or dest.stat().st_size < 1000:
            anomalies.append({"t": ts, "kind": "missing_or_tiny_frame"})
            continue
        im = np.asarray(Image.open(dest).convert("RGB"), dtype=np.float32)
        std = float(im.std())
        mean = float(im.mean())
        row = {"t": ts, "mean": round(mean, 2), "std": round(std, 2), "bytes": dest.stat().st_size}
        samples.append(row)
        if std < gray_std_thresh:
            anomalies.append({"t": ts, "kind": "near_uniform_gray", **row})
    return {
        "schema": "v2_r27_visual_frame_scan_v1",
        "video": str(video),
        "n_samples": len(samples),
        "n_anomalies": len(anomalies),
        "anomalies": anomalies,
        "gray_std_thresh": gray_std_thresh,
        "render_ready": False,
    }
