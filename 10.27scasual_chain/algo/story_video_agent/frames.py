"""FFmpeg 抽帧：粗搜索 / 局部观察；全局预算、缓存、manifest。

时间戳一律来自请求采样点与媒体时钟，禁止模型虚构。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from story_video_agent.media import MediaError, MediaInfo

PathLike = Union[str, Path]

COARSE_MAX_SPAN = 90.0
LOCAL_MAX_SPAN = 16.0
REACTION_MAX_SPAN = 32.0


class FrameBudgetExhausted(RuntimeError):
    """全局抽帧预算耗尽。"""


@dataclass
class FrameRecord:
    frame_id: str
    gap_id: str
    requested_media_sec: float
    actual_media_sec: float
    path: str
    tool: str
    cached: bool = False
    match_logic_sec: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FrameBudget:
    max_frames: int
    used: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.max_frames - self.used)

    def consume(self, n: int = 1) -> None:
        if n <= 0:
            return
        if self.used + n > self.max_frames:
            raise FrameBudgetExhausted(
                f"frame budget {self.max_frames} exhausted (used={self.used}, need={n})"
            )
        self.used += n


class FrameStore:
    """抽帧执行器：预算 + 同视频时刻缓存 + manifest。"""

    def __init__(
        self,
        media: MediaInfo,
        *,
        out_dir: PathLike,
        budget: FrameBudget,
    ) -> None:
        self.media = media
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.budget = budget
        self.manifest: List[Dict[str, Any]] = []
        self._ffmpeg = shutil.which("ffmpeg")
        if not self._ffmpeg:
            raise MediaError("ffmpeg not found on PATH")
        self._by_request: Dict[Tuple[str, float], FrameRecord] = {}

    def _cache_get(self, requested_sec: float) -> Optional[FrameRecord]:
        key = (self.media.path, round(requested_sec, 3))
        hit = self._by_request.get(key)
        if hit and Path(hit.path).is_file():
            return hit
        return None

    def _cache_put(self, record: FrameRecord) -> None:
        key = (self.media.path, round(record.requested_media_sec, 3))
        self._by_request[key] = record

    def sample_times(self, start: float, end: float, *, count: int) -> List[float]:
        if end <= start:
            raise MediaError(f"invalid sample window [{start}, {end}]")
        if count <= 1:
            return [round((start + end) / 2.0, 3)]
        span = end - start
        pad = min(0.05, span * 0.02)
        t0, t1 = start + pad, end - pad
        if t1 <= t0:
            t0, t1 = start, end
        step = (t1 - t0) / (count - 1)
        return [round(t0 + i * step, 3) for i in range(count)]

    def extract_at(
        self,
        requested_sec: float,
        *,
        gap_id: str,
        tool: str,
        match_logic_sec: Optional[float] = None,
    ) -> FrameRecord:
        if requested_sec < -1e-6 or requested_sec > self.media.duration_sec + 1e-3:
            raise MediaError(
                f"requested media time {requested_sec:.3f}s outside "
                f"[0, {self.media.duration_sec:.3f}]"
            )
        requested_sec = max(0.0, min(requested_sec, max(0.0, self.media.duration_sec - 0.05)))

        cached = self._cache_get(requested_sec)
        if cached is not None:
            clone = FrameRecord(
                frame_id=cached.frame_id,
                gap_id=gap_id,
                requested_media_sec=requested_sec,
                actual_media_sec=cached.actual_media_sec,
                path=cached.path,
                tool=tool,
                cached=True,
                match_logic_sec=match_logic_sec
                if match_logic_sec is not None
                else requested_sec,
                width=cached.width,
                height=cached.height,
            )
            row = clone.to_dict()
            row["time_basis"] = "media_clock"
            row["match_logic_note"] = (
                "match_logic_sec mirrors T01 story seconds when clocks align; "
                "never invented by a model"
            )
            self.manifest.append(row)
            return clone

        self.budget.consume(1)
        frame_id = f"f_{len(self.manifest):04d}_{int(round(requested_sec * 1000))}"
        out_path = self.out_dir / f"{frame_id}.jpg"
        cmd = [
            self._ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{requested_sec:.3f}",
            "-i",
            self.media.path,
            "-frames:v",
            "1",
            "-q:v",
            "3",
            "-y",
            str(out_path),
        ]
        t0 = time.perf_counter()
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=120)
        elapsed = time.perf_counter() - t0
        if proc.returncode != 0 or not out_path.is_file():
            self.budget.used = max(0, self.budget.used - 1)
            err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
            raise MediaError(f"ffmpeg extract failed at {requested_sec:.3f}s: {err}")

        # 单帧 seek 无独立 pts 回报时，实际媒体时间记为请求采样点（媒体时钟，非模型生成）
        actual = requested_sec
        record = FrameRecord(
            frame_id=frame_id,
            gap_id=gap_id,
            requested_media_sec=requested_sec,
            actual_media_sec=actual,
            path=str(out_path.resolve()),
            tool=tool,
            cached=False,
            match_logic_sec=match_logic_sec if match_logic_sec is not None else requested_sec,
            width=self.media.width,
            height=self.media.height,
        )
        row = record.to_dict()
        row["extract_sec"] = round(elapsed, 4)
        row["time_basis"] = "media_clock"
        row["match_logic_note"] = (
            "match_logic_sec mirrors T01 story seconds when clocks align; "
            "never invented by a model"
        )
        self.manifest.append(row)
        self._cache_put(record)
        return record

    def extract_window(
        self,
        start: float,
        end: float,
        *,
        gap_id: str,
        tool: str,
        count: int,
        match_logic_start: Optional[float] = None,
    ) -> List[FrameRecord]:
        times = self.sample_times(start, end, count=count)
        rows: List[FrameRecord] = []
        logic_base = match_logic_start if match_logic_start is not None else start
        for t in times:
            if self.budget.remaining <= 0:
                break
            logic_t = logic_base + (t - start)
            rows.append(
                self.extract_at(
                    t,
                    gap_id=gap_id,
                    tool=tool,
                    match_logic_sec=logic_t,
                )
            )
        return rows

    def write_manifest(self, path: PathLike) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "video": self.media.to_dict(),
            "budget": {"max_frames": self.budget.max_frames, "used": self.budget.used},
            "frames": self.manifest,
            "frame_count": len(self.manifest),
            "unique_files": len({r["path"] for r in self.manifest}),
        }
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return out


def plan_sample_count(span: float, *, coarse: bool) -> int:
    if coarse:
        if span <= 10:
            return 2
        if span <= 45:
            return 3
        return 4
    if span <= 4:
        return 2
    if span <= 10:
        return 3
    return 4
