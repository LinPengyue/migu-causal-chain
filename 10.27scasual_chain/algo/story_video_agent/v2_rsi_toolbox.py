"""V2 Phase A: Video-RSI-style visual tools for football story evidence.

Tools: overview / scan_interval / inspect_interval / read_scoreboard_window.
Uses FrameStore + VisionProvider (Qwen). No events/causal JSON required.
"""

from __future__ import annotations

import json
from math import ceil
from typing import Any, Dict, List, Optional, Sequence

from story_video_agent.frames import COARSE_MAX_SPAN, LOCAL_MAX_SPAN, FrameBudgetExhausted, FrameStore
from story_video_agent.tools import ToolArgumentError
from story_video_agent.vision_provider import VisionProvider, normalize_evidence


def _seconds(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if ":" in text:
        parts = [float(p) for p in text.split(":")]
        if len(parts) == 2:
            return parts[0] * 60.0 + parts[1]
        if len(parts) == 3:
            return parts[0] * 3600.0 + parts[1] * 60.0 + parts[2]
    return float(text)


class V2RSIToolbox:
    """Open-ended story tools (not MCQ options)."""

    def __init__(
        self,
        *,
        duration: float,
        store: FrameStore,
        vision: VisionProvider,
        task_note: str = "",
    ) -> None:
        self.duration = float(duration)
        self.store = store
        self.vision = vision
        self.task_note = task_note or (
            "Discover T01 comeback evidence: scoreboard scores, live goals, "
            "celebrations, replay vs live. Do not invent times."
        )
        self._call_log: List[Dict[str, Any]] = []

    def descriptions(self) -> Dict[str, str]:
        d = self.duration
        half = max(d / 2.0, 1.0)
        return {
            "overview": (
                "Sparse global overview: uniform frames across the whole clip/video "
                "(default 8 for Phase A budget; not continuous action). Arguments: {}."
            ),
            "scan_interval": (
                f"Coarse localization in a window. Require 8 < end-start <= {min(half, COARSE_MAX_SPAN):g}s. "
                "Uniform frames (default 6). Arguments: start, end."
            ),
            "inspect_interval": (
                f"Local action check: 0 < end-start <= {LOCAL_MAX_SPAN:g}s. "
                "At most 6 uniform frames. Arguments: start, end."
            ),
            "read_scoreboard_window": (
                f"Focus on scoreboard / on-screen score text in a short window "
                f"(<= {LOCAL_MAX_SPAN:g}s). Arguments: start, end."
            ),
        }

    def normalize_arguments(self, name: str, args: Any) -> Dict[str, Any]:
        if name not in self.descriptions():
            raise ToolArgumentError(f"unknown tool {name}; choose a listed tool")
        if not isinstance(args, dict):
            raise ToolArgumentError("arguments must be an object")
        if name == "overview":
            if set(args) - set():
                raise ToolArgumentError("overview takes no arguments")
            return {}
        allowed = {"start", "end"}
        if set(args) - allowed:
            raise ToolArgumentError(
                f"{name}: unsupported {sorted(set(args) - allowed)}; allowed {sorted(allowed)}"
            )
        if not {"start", "end"} <= set(args):
            raise ToolArgumentError(f"{name} requires start and end")
        try:
            start, end = _seconds(args["start"]), _seconds(args["end"])
        except ValueError as exc:
            raise ToolArgumentError(str(exc)) from None
        if not 0 <= start < end <= self.duration + 1e-6:
            raise ToolArgumentError(
                f"{name}: need 0 <= start < end <= {self.duration:g}; got {start:g},{end:g}"
            )
        span = end - start
        if name == "scan_interval":
            max_span = min(self.duration / 2.0, COARSE_MAX_SPAN)
            if not 8.0 < span <= max_span + 1e-6:
                raise ToolArgumentError(
                    f"scan_interval span {span:g}s; require 8 < span <= {max_span:g}"
                )
        if name in ("inspect_interval", "read_scoreboard_window") and span > LOCAL_MAX_SPAN + 1e-6:
            raise ToolArgumentError(
                f"{name} span {span:g}s exceeds {LOCAL_MAX_SPAN:g}s; use scan_interval first"
            )
        return {"start": start, "end": end}

    def execute(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        normalized = self.normalize_arguments(name, args)
        try:
            if name == "overview":
                # Short clips: keep overview sparse so later scan/inspect still have budget.
                if self.duration <= 90:
                    ov_count = 4
                else:
                    ov_count = min(8, max(4, int(self.duration // 60) + 4))
                out = self._visual(0.0, self.duration, count=ov_count, purpose="overview")
            elif name == "scan_interval":
                out = self._visual(normalized["start"], normalized["end"], count=6, purpose="scan_interval")
            elif name == "inspect_interval":
                span = normalized["end"] - normalized["start"]
                count = min(6, max(2, ceil(span)))
                out = self._visual(normalized["start"], normalized["end"], count=count, purpose="inspect_interval")
            elif name == "read_scoreboard_window":
                out = self._visual(
                    normalized["start"],
                    normalized["end"],
                    count=4,
                    purpose="read_scoreboard_window",
                    scoreboard_focus=True,
                )
            else:
                raise ToolArgumentError(f"unhandled tool {name}")
        except FrameBudgetExhausted as exc:
            out = {"error": "FrameBudgetExhausted", "message": str(exc), "unresolved": True}
        self._call_log.append({"tool": name, "arguments": normalized, "ok": "error" not in out})
        return out

    def _safe_window(self, start: float, end: float) -> tuple[float, float]:
        """Keep seeks off the HEVC trailer — last ~1s often yields empty ffmpeg frames."""
        margin = min(1.0, max(0.5, self.duration * 0.02))
        hi = max(0.0, self.duration - margin)
        s = max(0.0, min(float(start), hi))
        e = max(s + 0.05, min(float(end), hi + 1e-6))
        if e <= s:
            e = min(hi, s + 0.05)
        return s, e

    def _visual(
        self,
        start: float,
        end: float,
        *,
        count: int,
        purpose: str,
        scoreboard_focus: bool = False,
    ) -> Dict[str, Any]:
        start, end = self._safe_window(start, end)
        gap_id = f"v2_{purpose}"
        records = self.store.extract_window(
            start=start,
            end=end,
            count=count,
            gap_id=gap_id,
            tool=purpose,
        )
        frame_ids = [r.frame_id for r in records]
        paths = [r.path for r in records]
        bindings = [
            {
                "frame_id": r.frame_id,
                "requested_media_sec": r.requested_media_sec,
                "actual_media_sec": r.actual_media_sec,
                "pts_status": r.pts_status,
            }
            for r in records
        ]
        note = (
            f"purpose={purpose}; media_window=[{start:.3f},{end:.3f}]; "
            f"task={self.task_note}; "
            "Samples are sparse — not continuous video. "
            "Do not invent events between frames. "
            "Separate visible facts vs uncertain guesses. "
            "Flag live vs replay if visible."
        )
        if scoreboard_focus:
            note += " Focus on scoreboard digits/team abbreviations if visible."

        evidence = self.vision.describe_frames(
            gap_id=gap_id,
            gap_note=note,
            frame_paths=paths,
            frame_ids=frame_ids,
            frame_bindings=bindings,
        )
        sampling_note = {
            "overview": "sparse whole-clip overview",
            "scan_interval": "coarse localization",
            "inspect_interval": "local action samples",
            "read_scoreboard_window": "scoreboard-focused samples",
        }.get(purpose, purpose)
        return {
            "purpose": purpose,
            "media_start_sec": start,
            "media_end_sec": end,
            "frames": [
                {
                    "frame_id": r.frame_id,
                    "requested_media_sec": r.requested_media_sec,
                    "actual_media_sec": r.actual_media_sec,
                    "pts_status": r.pts_status,
                }
                for r in records
            ],
            "sampling_note": sampling_note,
            "perception": evidence,
            "fact_verified": False,
            "observation_only": True,
        }

    @property
    def call_log(self) -> List[Dict[str, Any]]:
        return list(self._call_log)
