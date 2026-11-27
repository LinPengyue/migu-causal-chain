"""FFprobe 媒体探测：真实时长/帧率/分辨率；无效视频明确报错。"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Union

PathLike = Union[str, Path]


class MediaError(RuntimeError):
    """无可探测的有效视频或 ffprobe 失败。"""


@dataclass(frozen=True)
class MediaInfo:
    path: str
    duration_sec: float
    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str
    start_time_sec: float
    format_name: str
    size_bytes: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _require_ffprobe() -> str:
    path = shutil.which("ffprobe")
    if not path:
        raise MediaError("ffprobe not found on PATH")
    return path


def _parse_fps(rate: str) -> float:
    if not rate or rate in ("0/0", "N/A"):
        return 0.0
    if "/" in rate:
        num_s, den_s = rate.split("/", 1)
        try:
            num, den = float(num_s), float(den_s)
        except ValueError:
            return 0.0
        return num / den if den else 0.0
    try:
        return float(rate)
    except ValueError:
        return 0.0


def probe_video(path: PathLike) -> MediaInfo:
    """探测本地视频；路径缺失、非文件或无视频流时抛 MediaError。"""
    video = Path(path)
    if not str(path):
        raise MediaError("video_path is empty")
    if not video.is_file():
        raise MediaError(f"video not found or not a file: {video}")

    ffprobe = _require_ffprobe()
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration,start_time,format_name,size:stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,start_time",
        "-of",
        "json",
        str(video),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=60)
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"ffprobe timed out on {video}") from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise MediaError(f"ffprobe failed: {err}")

    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise MediaError("ffprobe returned non-JSON output") from exc

    fmt = payload.get("format") or {}
    streams = payload.get("streams") or []
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video_stream is None:
        raise MediaError(f"no video stream in {video}")

    try:
        duration = float(fmt.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        raise MediaError(f"invalid duration from ffprobe: {fmt.get('duration')!r}")

    fps = _parse_fps(str(video_stream.get("avg_frame_rate") or ""))
    if fps <= 0:
        fps = _parse_fps(str(video_stream.get("r_frame_rate") or ""))

    try:
        start_time = float(fmt.get("start_time") or video_stream.get("start_time") or 0.0)
    except (TypeError, ValueError):
        start_time = 0.0

    try:
        size_bytes = int(float(fmt.get("size") or video.stat().st_size))
    except (TypeError, ValueError, OSError):
        size_bytes = 0

    return MediaInfo(
        path=str(video.resolve()),
        duration_sec=duration,
        width=int(video_stream.get("width") or 0),
        height=int(video_stream.get("height") or 0),
        fps=fps,
        video_codec=str(video_stream.get("codec_name") or ""),
        audio_codec=str(audio_stream.get("codec_name") or "") if audio_stream else "",
        start_time_sec=start_time,
        format_name=str(fmt.get("format_name") or ""),
        size_bytes=size_bytes,
    )


def optional_probe(path: Optional[PathLike]) -> Optional[MediaInfo]:
    if not path:
        return None
    return probe_video(path)
