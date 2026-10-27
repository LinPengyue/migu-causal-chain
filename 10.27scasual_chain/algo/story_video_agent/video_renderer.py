"""Phase 3B：FFmpeg 双模式渲染（preview / final）严格隔离。

- preview：可用 candidate_edl 数值时间窗生成内部审核样片；不提升证据等级
- final：必须 render_ready + render_ready_edl；否则硬失败，禁止降级渲染
- blocked / 无时间窗：占位卡「镜头待定位」，不虚构视频内容
- none：不生成翻盘故事片
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from story_video_agent.internal_verification import (
    GRANTED_BY,
    apply_internal_verification,
    assert_not_forged_render_ready,
    revalidate_plan_grants,
)
from story_video_agent.media import MediaError, MediaInfo, probe_video

PathLike = Union[str, Path]

DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720
DEFAULT_FPS = 25
DEFAULT_AUDIO_RATE = 44100
CJK_FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"


class RenderError(RuntimeError):
    """渲染硬失败（含 final 未就绪、无媒体、FFmpeg 失败）。"""


def _require_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise RenderError("ffmpeg not found on PATH")
    return path


def _font_file() -> str:
    if Path(CJK_FONT).is_file():
        return CJK_FONT
    # fallbacks
    for p in (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(p).is_file():
            return p
    return CJK_FONT


def _esc_drawtext(text: str) -> str:
    """Escape for ffmpeg drawtext."""
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
    )


def _run_ffmpeg(cmd: List[str], *, label: str) -> Dict[str, Any]:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=1200)
    rec = {
        "label": label,
        "cmd": cmd,
        "returncode": proc.returncode,
        "stderr_tail": (proc.stderr or "")[-800:],
    }
    if proc.returncode != 0:
        raise RenderError(f"ffmpeg failed ({label}): {(proc.stderr or '')[-400:]}")
    return rec


def _normalize_clip_filter(
    *,
    width: int,
    height: int,
    fps: int,
    overlay_lines: Sequence[str],
) -> str:
    font = _esc_drawtext(_font_file())
    # scale+pad to exact canvas, then drawtext overlays
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
        f"fps={fps},setsar=1"
    )
    y = 40
    for line in overlay_lines:
        if not line:
            continue
        t = _esc_drawtext(line)
        vf += (
            f",drawtext=fontfile={font}:text='{t}':fontsize=28:"
            f"fontcolor=white:borderw=2:bordercolor=black:x=40:y={y}"
        )
        y += 40
    return vf


def _cut_segment(
    *,
    ffmpeg: str,
    src: Path,
    media_in: float,
    media_out: float,
    out_path: Path,
    width: int,
    height: int,
    fps: int,
    has_audio: bool,
    overlay_lines: Sequence[str],
    accurate_seek: bool = True,
    seek_pad_sec: float = 20.0,
    audio_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """Cut+reencode one segment.

    accurate_seek (default True): hybrid seek — coarse ``-ss`` before ``-i``,
    then fine ``-ss`` after ``-i``. Reduces mid-GOP decode ambiguity on HEVC
    while remaining much faster than decoding from file start.
    """
    dur = max(0.04, float(media_out) - float(media_in))
    media_in = float(media_in)
    vf = _normalize_clip_filter(
        width=width, height=height, fps=fps, overlay_lines=overlay_lines
    )
    af = audio_filter or f"aresample={DEFAULT_AUDIO_RATE}"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd: List[str] = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
    ]
    if accurate_seek and media_in > 0.05:
        pad = min(float(seek_pad_sec), media_in)
        coarse = max(0.0, media_in - pad)
        fine = media_in - coarse
        cmd += ["-ss", f"{coarse:.3f}", "-i", str(src), "-ss", f"{fine:.3f}", "-t", f"{dur:.3f}"]
    else:
        cmd += ["-ss", f"{media_in:.3f}", "-t", f"{dur:.3f}", "-i", str(src)]
    if has_audio:
        cmd += [
            "-vf",
            vf,
            "-af",
            af,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-force_key_frames",
            "expr:eq(n,0)",
            "-c:a",
            "aac",
            "-ar",
            str(DEFAULT_AUDIO_RATE),
            "-ac",
            "2",
            "-shortest",
        ]
    else:
        # 无音频源：合成静音
        cmd += [
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=channel_layout=stereo:sample_rate={DEFAULT_AUDIO_RATE}",
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-force_key_frames",
            "expr:eq(n,0)",
            "-c:a",
            "aac",
            "-ar",
            str(DEFAULT_AUDIO_RATE),
            "-ac",
            "2",
            "-shortest",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
        ]
    cmd.append(str(out_path))
    return _run_ffmpeg(cmd, label=f"cut:{out_path.name}")


def _make_placeholder(
    *,
    ffmpeg: str,
    out_path: Path,
    duration: float,
    width: int,
    height: int,
    fps: int,
    lines: Sequence[str],
) -> Dict[str, Any]:
    font = _esc_drawtext(_font_file())
    y = height // 2 - 60
    vf_parts = [f"fps={fps}", "setsar=1"]
    for line in lines:
        t = _esc_drawtext(line)
        vf_parts.append(
            f"drawtext=fontfile={font}:text='{t}':fontsize=36:"
            f"fontcolor=white:x=(w-text_w)/2:y={y}"
        )
        y += 48
    vf = ",".join(vf_parts)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x1a1a2e:s={width}x{height}:d={duration:.3f}:r={fps}",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=channel_layout=stereo:sample_rate={DEFAULT_AUDIO_RATE}",
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-ar",
        str(DEFAULT_AUDIO_RATE),
        "-ac",
        "2",
        "-shortest",
        str(out_path),
    ]
    return _run_ffmpeg(cmd, label=f"placeholder:{out_path.name}")


def _concat_clips(
    *,
    ffmpeg: str,
    clip_paths: Sequence[Path],
    out_mp4: Path,
) -> Dict[str, Any]:
    if not clip_paths:
        raise RenderError("no clips to concat")
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    list_file = out_mp4.with_suffix(".concat.txt")
    lines = []
    for p in clip_paths:
        # concat demuxer requires escaped single quotes
        ap = str(p.resolve()).replace("'", "'\\''")
        lines.append(f"file '{ap}'")
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
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
        str(list_file),
        "-c",
        "copy",
        str(out_mp4),
    ]
    try:
        return _run_ffmpeg(cmd, label="concat")
    except RenderError:
        # 回退重新编码拼接
        cmd2 = [
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
            str(list_file),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(out_mp4),
        ]
        return _run_ffmpeg(cmd2, label="concat_reencode")


def _row_from_plan_segment(seg: Dict[str, Any], edl_index: int) -> Dict[str, Any]:
    return {
        "edl_index": edl_index,
        "segment_id": seg.get("segment_id"),
        "beat": seg.get("beat"),
        "role": seg.get("role"),
        "shot_kind": seg.get("shot_kind"),
        "is_replay": bool(seg.get("is_replay")),
        "media_in": seg.get("media_in"),
        "media_out": seg.get("media_out"),
        "time_status": seg.get("time_status"),
        "time_provenance": seg.get("time_provenance") or {},
        "event_ids": list(seg.get("event_ids") or []),
        "frame_ids": list(seg.get("frame_ids") or []),
        "linked_live_event_id": seg.get("linked_live_event_id"),
        "narrative_order": seg.get("narrative_order"),
        "source_media_order": seg.get("source_media_order"),
        "render_eligibility": seg.get("render_eligibility"),
        "blocking_reasons": list(seg.get("blocking_reasons") or []),
        "confidence": seg.get("confidence"),
        "selection_reason": seg.get("selection_reason"),
        "narration": seg.get("narration") or "",
    }


def _select_preview_rows(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """按 narrative_order 使用 candidate_edl；缺省则从 segments 重建。"""
    rows = list(plan.get("candidate_edl") or [])
    if rows:
        return sorted(rows, key=lambda r: (r.get("narrative_order") or 0, r.get("edl_index") or 0))
    segs = sorted(
        plan.get("segments") or [],
        key=lambda s: (s.get("narrative_order") or 0, s.get("segment_id") or ""),
    )
    return [_row_from_plan_segment(s, i + 1) for i, s in enumerate(segs)]


def _select_final_rows(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = list(plan.get("render_ready_edl") or [])
    return sorted(rows, key=lambda r: (r.get("narrative_order") or 0, r.get("edl_index") or 0))


def _can_cut_row(row: Dict[str, Any], media: MediaInfo) -> tuple:
    """返回 (ok, reason)。blocked / 无窗 / 越界 → 不可裁切。"""
    if row.get("render_eligibility") == "blocked":
        return False, "blocked"
    tin, tout = row.get("media_in"), row.get("media_out")
    if tin is None or tout is None:
        return False, "missing_time_window"
    try:
        a, b = float(tin), float(tout)
    except (TypeError, ValueError):
        return False, "non_numeric_time"
    if not (a < b):
        return False, "start_not_before_end"
    if a < -1e-3 or b > float(media.duration_sec) + 1e-3:
        return False, f"out_of_bounds:[{a},{b}]"
    ts = row.get("time_status")
    if ts in ("pending_localization", "pending_review", "unavailable"):
        return False, f"time_status:{ts}"
    return True, ""


def render_story_video(
    plan: Dict[str, Any],
    video_path: PathLike,
    out_mp4: PathLike,
    *,
    mode: str = "preview",
    work_dir: Optional[PathLike] = None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    fps: int = DEFAULT_FPS,
    max_clip_sec: Optional[float] = None,
    placeholder_sec: float = 2.5,
    promote_for_final: bool = False,
) -> Dict[str, Any]:
    """渲染故事片。

    mode=preview|final
    promote_for_final：仅测试用——在 final 前走内部核验授予（生产默认 False）。
    """
    mode = str(mode or "preview").lower().strip()
    if mode not in ("preview", "final"):
        raise RenderError(f"unknown render mode: {mode}")

    ffmpeg = _require_ffmpeg()
    media = probe_video(video_path)
    has_audio = bool(media.audio_codec)

    if plan.get("story_tier") == "none":
        raise RenderError("story_tier=none: 不生成翻盘故事片")

    if mode == "final":
        if promote_for_final:
            # 测试辅助：现场 promote（仍要求语义签发；允许 unit_test authority）
            plan = apply_internal_verification(
                plan,
                media,
                promote_to_render_ready=True,
                allow_test_semantic=True,
            )
        else:
            # 重新验证 ledger+媒体绑定；JSON 字符串 granted_by 无效
            plan = revalidate_plan_grants(plan, media)
            try:
                assert_not_forged_render_ready(plan, media)
            except ValueError as exc:
                raise RenderError(str(exc)) from exc
            if not plan.get("render_ready") or not plan.get("render_ready_edl"):
                problems = (plan.get("diagnostics") or {}).get(
                    "revalidate_render_problems"
                ) or ["render_ready=false"]
                raise RenderError(
                    "final mode hard-fail: render_ready=false; "
                    f"problems={problems}; 禁止降级为 preview"
                )
        if not plan.get("render_ready") or not plan.get("render_ready_edl"):
            raise RenderError(
                "final mode hard-fail: render_ready EDL empty or flag false; "
                "禁止降级渲染"
            )
        rows = _select_final_rows(plan)
        banner = ["正式成片", f"granted_by={GRANTED_BY}"]
    else:
        # preview：媒体时间核验 / 可裁切；不提升证据等级、不成片授权
        plan = apply_internal_verification(plan, media, promote_to_render_ready=False)
        rows = _select_preview_rows(plan)
        if not rows:
            raise RenderError("preview: empty candidate_edl")
        banner = ["内部审核样片", "镜头未核实"]

    out_mp4 = Path(out_mp4)
    work = Path(work_dir) if work_dir else out_mp4.parent / f"_work_{out_mp4.stem}"
    work.mkdir(parents=True, exist_ok=True)
    clips_dir = work / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg_log: List[Dict[str, Any]] = []
    segment_results: List[Dict[str, Any]] = []
    clip_paths: List[Path] = []

    for i, row in enumerate(rows):
        sid = str(row.get("segment_id") or f"seg_{i}")
        clip_path = clips_dir / f"{i:03d}_{sid}.mp4"
        ok_cut, reason = _can_cut_row(row, media)
        meta = {
            "segment_id": sid,
            "beat": row.get("beat"),
            "role": row.get("role"),
            "event_ids": list(row.get("event_ids") or []),
            "time_status": row.get("time_status"),
            "time_provenance": row.get("time_provenance") or {},
            "render_eligibility": row.get("render_eligibility"),
            "blocking_reasons": list(row.get("blocking_reasons") or []),
            "narrative_order": row.get("narrative_order"),
            "source_media_order": row.get("source_media_order"),
            "media_in": row.get("media_in"),
            "media_out": row.get("media_out"),
            "cut": False,
            "placeholder": False,
            "clip_path": str(clip_path),
            "skip_reason": None,
        }

        if ok_cut:
            a = float(row["media_in"])
            b = float(row["media_out"])
            if max_clip_sec is not None and (b - a) > float(max_clip_sec):
                b = a + float(max_clip_sec)
            overlays = list(banner) + [
                f"{row.get('beat') or ''} | {sid}",
                f"t={a:.1f}-{b:.1f}s | {row.get('time_status')}",
            ]
            if mode == "preview":
                overlays.append(f"candidate:{row.get('render_eligibility')}")
            try:
                rec = _cut_segment(
                    ffmpeg=ffmpeg,
                    src=Path(media.path),
                    media_in=a,
                    media_out=b,
                    out_path=clip_path,
                    width=width,
                    height=height,
                    fps=fps,
                    has_audio=has_audio,
                    overlay_lines=overlays,
                )
                ffmpeg_log.append(rec)
                meta["cut"] = True
                meta["media_in"] = a
                meta["media_out"] = b
                clip_paths.append(clip_path)
            except RenderError as exc:
                meta["skip_reason"] = f"cut_failed:{exc}"
                # preview：裁切失败也用占位，不虚构原片内容
                if mode == "final":
                    raise
                lines = [
                    "镜头待定位",
                    f"{row.get('beat') or ''} | {sid}",
                    f"裁切失败: {reason or 'error'}",
                ]
                rec = _make_placeholder(
                    ffmpeg=ffmpeg,
                    out_path=clip_path,
                    duration=placeholder_sec,
                    width=width,
                    height=height,
                    fps=fps,
                    lines=lines,
                )
                ffmpeg_log.append(rec)
                meta["placeholder"] = True
                clip_paths.append(clip_path)
        else:
            meta["skip_reason"] = reason
            if mode == "final":
                raise RenderError(
                    f"final mode: segment {sid} not cuttable ({reason})"
                )
            lines = [
                "镜头待定位",
                f"{row.get('beat') or ''} | {sid}",
                f"状态: {row.get('time_status') or reason}",
                f"eligibility: {row.get('render_eligibility')}",
            ]
            rec = _make_placeholder(
                ffmpeg=ffmpeg,
                out_path=clip_path,
                duration=placeholder_sec,
                width=width,
                height=height,
                fps=fps,
                lines=lines,
            )
            ffmpeg_log.append(rec)
            meta["placeholder"] = True
            clip_paths.append(clip_path)

        segment_results.append(meta)

    concat_rec = _concat_clips(ffmpeg=ffmpeg, clip_paths=clip_paths, out_mp4=out_mp4)
    ffmpeg_log.append(concat_rec)

    out_info: Optional[MediaInfo] = None
    try:
        out_info = probe_video(out_mp4)
    except MediaError:
        out_info = None

    result = {
        "ok": True,
        "mode": mode,
        "out_mp4": str(Path(out_mp4).resolve()),
        "work_dir": str(work.resolve()),
        "source_video": media.to_dict(),
        "output_media": out_info.to_dict() if out_info else None,
        "width": width,
        "height": height,
        "fps": fps,
        "n_segments": len(segment_results),
        "n_cut": sum(1 for s in segment_results if s.get("cut")),
        "n_placeholder": sum(1 for s in segment_results if s.get("placeholder")),
        "segments": segment_results,
        "ffmpeg_log": [
            {k: v for k, v in r.items() if k != "cmd"} | {"cmd_preview": " ".join(r.get("cmd") or [])[:200]}
            for r in ffmpeg_log
        ],
        "render_ready": bool(plan.get("render_ready")),
        "story_tier": plan.get("story_tier"),
        "evidence_unchanged": mode == "preview",
        "diagnostics": {
            "internal_time_verification": (plan.get("diagnostics") or {}).get(
                "internal_time_verification"
            ),
        },
    }
    manifest_path = Path(out_mp4).with_suffix(".render_manifest.json")
    manifest_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result["render_manifest"] = str(manifest_path)
    return result


def render_from_paths(
    plan_path: PathLike,
    video_path: PathLike,
    out_mp4: PathLike,
    **kwargs: Any,
) -> Dict[str, Any]:
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    return render_story_video(plan, video_path, out_mp4, **kwargs)
