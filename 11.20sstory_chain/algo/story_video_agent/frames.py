"""FFmpeg 抽帧：粗搜索 / 局部观察；PTS 媒体时间、预算、缓存、manifest。

actual_media_sec 优先取解码帧 PTS；失败则 pts_status=requested_only。
未经校准不得把 media_sec 当作 match_logic_sec。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from story_video_agent.media import MediaError, MediaInfo

PathLike = Union[str, Path]

COARSE_MAX_SPAN = 90.0
LOCAL_MAX_SPAN = 16.0
REACTION_MAX_SPAN = 32.0

_PTS_RE = re.compile(r"pts_time:(?P<pts>-?\d+(?:\.\d+)?)")

# 缺口优先级：扳平/反超动作与比分 > 反应 > 定位 > 铺垫/蓄力
GAP_PRIORITY = {
    "verify_equalizer_goal_action": 0,
    "verify_go_ahead_goal_action": 0,
    "verify_equalizer_scoreboard": 1,
    "verify_go_ahead_scoreboard": 1,
    "post_climax_reaction": 2,
    "locate_equalizer_goal_action": 3,
    "locate_go_ahead_goal_action": 3,
    "missing_setup_visual": 4,
    "missing_buildup_visual": 4,
}

DEFAULT_GAP_CAPS = {
    0: 4,  # climax actions
    1: 3,  # scoreboard
    2: 3,  # reaction
    3: 2,  # locate
    4: 2,  # setup/buildup coarse
}


class FrameBudgetExhausted(RuntimeError):
    """全局或 per-gap 抽帧预算耗尽。"""


@dataclass
class FrameRecord:
    frame_id: str
    gap_id: str
    requested_media_sec: float
    actual_media_sec: Optional[float]
    path: str
    tool: str
    pts_status: str  # "pts" | "requested_only"
    cached: bool = False
    match_logic_sec: Optional[float] = None
    match_logic_status: str = "uncalibrated"  # uncalibrated | caller_calibrated
    media_start_time_sec: float = 0.0
    width: Optional[int] = None
    height: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FrameBudget:
    max_frames: int
    used: int = 0
    per_gap_used: Dict[str, int] = field(default_factory=dict)
    per_gap_caps: Dict[str, int] = field(default_factory=dict)

    @property
    def remaining(self) -> int:
        return max(0, self.max_frames - self.used)

    def remaining_for(self, gap_id: str) -> int:
        cap = self.per_gap_caps.get(gap_id)
        if cap is None:
            return self.remaining
        used_g = self.per_gap_used.get(gap_id, 0)
        return max(0, min(self.remaining, cap - used_g))

    def consume(self, n: int = 1, *, gap_id: str = "") -> None:
        if n <= 0:
            return
        if gap_id and self.remaining_for(gap_id) < n:
            raise FrameBudgetExhausted(
                f"gap {gap_id} frame budget exhausted "
                f"(cap={self.per_gap_caps.get(gap_id)}, used={self.per_gap_used.get(gap_id, 0)})"
            )
        if self.used + n > self.max_frames:
            raise FrameBudgetExhausted(
                f"frame budget {self.max_frames} exhausted (used={self.used}, need={n})"
            )
        self.used += n
        if gap_id:
            self.per_gap_used[gap_id] = self.per_gap_used.get(gap_id, 0) + n


def gap_priority(gap_id: str) -> int:
    return int(GAP_PRIORITY.get(gap_id, 9))


def allocate_gap_caps(
    gap_ids: Sequence[str],
    *,
    global_budget: int,
    caps_by_priority: Optional[Dict[int, int]] = None,
) -> Dict[str, int]:
    """优先保证扳平/反超动作与比分窗，再分给 setup/buildup。"""
    table = caps_by_priority or DEFAULT_GAP_CAPS
    ordered = sorted(gap_ids, key=lambda g: (gap_priority(g), g))
    caps: Dict[str, int] = {}
    remaining = max(0, int(global_budget))
    for gap_id in ordered:
        want = int(table.get(gap_priority(gap_id), 1))
        give = min(want, remaining)
        caps[gap_id] = give
        remaining -= give
    return caps


def prioritize_gap_ids(gap_ids: Sequence[str]) -> List[str]:
    return sorted(gap_ids, key=lambda g: (gap_priority(g), g))


class FrameStore:
    """抽帧执行器：PTS、预算、同视频时刻缓存、manifest。"""

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
        self._by_id: Dict[str, FrameRecord] = {}
        self._ffmpeg = shutil.which("ffmpeg")
        if not self._ffmpeg:
            raise MediaError("ffmpeg not found on PATH")
        self._by_request: Dict[Tuple[str, float], FrameRecord] = {}

    def get_frame(self, frame_id: str) -> Optional[FrameRecord]:
        return self._by_id.get(frame_id)

    def _cache_get(self, requested_sec: float) -> Optional[FrameRecord]:
        key = (self.media.path, round(requested_sec, 3))
        hit = self._by_request.get(key)
        if hit and Path(hit.path).is_file():
            return hit
        return None

    def _cache_put(self, record: FrameRecord) -> None:
        key = (self.media.path, round(record.requested_media_sec, 3))
        self._by_request[key] = record
        self._by_id[record.frame_id] = record

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

    def _parse_pts(self, stderr: str) -> Optional[float]:
        match = _PTS_RE.search(stderr or "")
        if not match:
            return None
        try:
            return float(match.group("pts"))
        except ValueError:
            return None

    def _ffmpeg_extract(
        self, out_path: Path, requested_sec: float
    ) -> Tuple[Optional[subprocess.CompletedProcess], Optional[float]]:
        """优先快速 seek+copyts；失败则回退 select 绝对时间抽帧。"""
        cmds = [
            [
                self._ffmpeg,
                "-hide_banner",
                "-ss",
                f"{requested_sec:.3f}",
                "-i",
                self.media.path,
                "-copyts",
                "-frames:v",
                "1",
                "-vf",
                "showinfo",
                "-q:v",
                "3",
                "-y",
                str(out_path),
            ],
            [
                self._ffmpeg,
                "-hide_banner",
                "-i",
                self.media.path,
                "-vf",
                f"select='gte(t\\,{requested_sec:.3f})',showinfo",
                "-frames:v",
                "1",
                "-q:v",
                "3",
                "-y",
                str(out_path),
            ],
        ]
        last: Optional[subprocess.CompletedProcess] = None
        for cmd in cmds:
            if out_path.exists():
                try:
                    out_path.unlink()
                except OSError:
                    pass
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=180)
            last = proc
            if proc.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 0:
                return proc, self._parse_pts(proc.stderr or "")
        return last, None

    def extract_at(
        self,
        requested_sec: float,
        *,
        gap_id: str,
        tool: str,
        match_logic_sec: Optional[float] = None,
        match_logic_calibrated: bool = False,
    ) -> FrameRecord:
        if requested_sec < -1e-6 or requested_sec > self.media.duration_sec + 1e-3:
            raise MediaError(
                f"requested media time {requested_sec:.3f}s outside "
                f"[0, {self.media.duration_sec:.3f}]"
            )
        # 允许落在媒体起点偏移之后的有效区间；尾部留足余量避免 HEVC seek 空帧
        lo = max(0.0, self.media.start_time_sec)
        tail = min(1.0, max(0.5, self.media.duration_sec * 0.02))
        hi = max(lo, self.media.duration_sec - tail)
        requested_sec = min(max(requested_sec, lo), hi)

        cached = self._cache_get(requested_sec)
        if cached is not None:
            clone = FrameRecord(
                frame_id=cached.frame_id,
                gap_id=gap_id,
                requested_media_sec=requested_sec,
                actual_media_sec=cached.actual_media_sec,
                path=cached.path,
                tool=tool,
                pts_status=cached.pts_status,
                cached=True,
                match_logic_sec=match_logic_sec if match_logic_calibrated else None,
                match_logic_status="caller_calibrated" if match_logic_calibrated else "uncalibrated",
                media_start_time_sec=self.media.start_time_sec,
                width=cached.width,
                height=cached.height,
            )
            self._append_manifest(clone, extract_sec=0.0)
            return clone

        if self.budget.remaining_for(gap_id) <= 0:
            raise FrameBudgetExhausted(f"no frame budget remaining for gap {gap_id}")
        self.budget.consume(1, gap_id=gap_id)

        frame_id = f"f_{len(self.manifest):04d}_{int(round(requested_sec * 1000))}"
        out_path = self.out_dir / f"{frame_id}.jpg"
        t0 = time.perf_counter()
        proc, pts = self._ffmpeg_extract(out_path, requested_sec)
        elapsed = time.perf_counter() - t0
        if proc is None or not out_path.is_file():
            self.budget.used = max(0, self.budget.used - 1)
            if gap_id:
                self.budget.per_gap_used[gap_id] = max(
                    0, self.budget.per_gap_used.get(gap_id, 0) - 1
                )
            err = ""
            if proc is not None:
                err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
            raise MediaError(f"ffmpeg extract failed at {requested_sec:.3f}s: {err}")

        if pts is not None:
            actual: Optional[float] = pts
            pts_status = "pts"
        else:
            actual = None
            pts_status = "requested_only"

        record = FrameRecord(
            frame_id=frame_id,
            gap_id=gap_id,
            requested_media_sec=requested_sec,
            actual_media_sec=actual,
            path=str(out_path.resolve()),
            tool=tool,
            pts_status=pts_status,
            cached=False,
            match_logic_sec=match_logic_sec if match_logic_calibrated else None,
            match_logic_status="caller_calibrated" if match_logic_calibrated else "uncalibrated",
            media_start_time_sec=self.media.start_time_sec,
            width=self.media.width,
            height=self.media.height,
        )
        self._append_manifest(record, extract_sec=elapsed)
        self._cache_put(record)
        return record

    def _append_manifest(self, record: FrameRecord, *, extract_sec: float) -> None:
        row = record.to_dict()
        row["extract_sec"] = round(extract_sec, 4)
        row["time_basis"] = "media_clock"
        row["match_logic_note"] = (
            "match_logic_sec is set only when caller_calibrated; "
            "never copied from media_sec without calibration; never invented by a model"
        )
        if record.pts_status == "requested_only":
            row["pts_note"] = "decoder PTS unavailable; actual_media_sec left null"
        self.manifest.append(row)

    def extract_window(
        self,
        start: float,
        end: float,
        *,
        gap_id: str,
        tool: str,
        count: int,
        match_logic_start: Optional[float] = None,
        match_logic_calibrated: bool = False,
    ) -> List[FrameRecord]:
        times = self.sample_times(start, end, count=count)
        rows: List[FrameRecord] = []
        for t in times:
            if self.budget.remaining_for(gap_id) <= 0:
                break
            logic_t = None
            calibrated = False
            if match_logic_calibrated and match_logic_start is not None:
                logic_t = match_logic_start + (t - start)
                calibrated = True
            rows.append(
                self.extract_at(
                    t,
                    gap_id=gap_id,
                    tool=tool,
                    match_logic_sec=logic_t,
                    match_logic_calibrated=calibrated,
                )
            )
        return rows

    def write_manifest(self, path: PathLike) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "video": self.media.to_dict(),
            "budget": {
                "max_frames": self.budget.max_frames,
                "used": self.budget.used,
                "per_gap_used": dict(self.budget.per_gap_used),
                "per_gap_caps": dict(self.budget.per_gap_caps),
            },
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
