"""Phase B hierarchical video tools for long-match story discovery.

Layers: global_overview → partition_scan → localize_event → verify_evidence
(+ read_scoreboard_window for score focus).
"""

from __future__ import annotations

from math import ceil
from typing import Any, Dict, List, Optional

from story_video_agent.frames import FrameBudgetExhausted, FrameStore
from story_video_agent.tools import ToolArgumentError
from story_video_agent.vision_provider import VisionProvider

# Phase B spans (seconds) — larger than Phase A COARSE_MAX_SPAN=90 for long video.
PARTITION_MIN_SPAN = 60.0
PARTITION_MAX_SPAN = 900.0  # up to 15 min partition
LOCALIZE_MAX_SPAN = 45.0
VERIFY_MAX_SPAN = 20.0


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


class V2PhaseBToolbox:
    def __init__(
        self,
        *,
        duration: float,
        store: FrameStore,
        vision: VisionProvider,
        task_note: str = "",
        overview_frames: int = 8,
        partition_frames: int = 4,
    ) -> None:
        self.duration = float(duration)
        self.store = store
        self.vision = vision
        self.overview_frames = int(overview_frames)
        self.partition_frames = int(partition_frames)
        self.task_note = task_note or (
            "Football broadcast analysis for possible T01 comeback story type. "
            "Report only what is visible. Sparse frames ≠ full interval watched. "
            "Do not invent media timestamps."
        )
        self._call_log: List[Dict[str, Any]] = []

    def descriptions(self) -> Dict[str, str]:
        d = self.duration
        return {
            "global_overview": (
                f"Layer1 sparse overview across [0,{d:g}] with ~{self.overview_frames} frames. "
                "Clues only; unknown intervals remain. Arguments: {}."
            ),
            "partition_scan": (
                f"Layer2 scan a partition. Require {PARTITION_MIN_SPAN:g} < end-start <= "
                f"{min(PARTITION_MAX_SPAN, max(d, PARTITION_MIN_SPAN + 1)):g}s. "
                f"~{self.partition_frames} uniform frames. Arguments: start, end."
            ),
            "localize_event": (
                f"Layer3 narrow a suspected goal/score-change/celebration window "
                f"(<= {LOCALIZE_MAX_SPAN:g}s). Arguments: start, end."
            ),
            "verify_evidence": (
                f"Layer4 verify live/replay, team/score clues in a short window "
                f"(<= {VERIFY_MAX_SPAN:g}s). Arguments: start, end."
            ),
            "read_scoreboard_window": (
                f"Scoreboard-focused read (<= {VERIFY_MAX_SPAN:g}s). Arguments: start, end."
            ),
        }

    def normalize_arguments(self, name: str, args: Any) -> Dict[str, Any]:
        if name not in self.descriptions():
            raise ToolArgumentError(f"unknown tool {name}")
        if not isinstance(args, dict):
            raise ToolArgumentError("arguments must be an object")
        if name == "global_overview":
            if set(args):
                raise ToolArgumentError("global_overview takes no arguments")
            return {}
        if set(args) - {"start", "end"}:
            raise ToolArgumentError(f"{name}: only start,end allowed")
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
        if name == "partition_scan":
            max_span = min(PARTITION_MAX_SPAN, max(self.duration, PARTITION_MIN_SPAN + 1))
            if not PARTITION_MIN_SPAN < span <= max_span + 1e-6:
                raise ToolArgumentError(
                    f"partition_scan span {span:g}; require {PARTITION_MIN_SPAN:g} < span <= {max_span:g}"
                )
        if name == "localize_event" and span > LOCALIZE_MAX_SPAN + 1e-6:
            raise ToolArgumentError(f"localize_event span {span:g} > {LOCALIZE_MAX_SPAN:g}")
        if name in ("verify_evidence", "read_scoreboard_window") and span > VERIFY_MAX_SPAN + 1e-6:
            raise ToolArgumentError(f"{name} span {span:g} > {VERIFY_MAX_SPAN:g}")
        return {"start": start, "end": end}

    def _safe_window(self, start: float, end: float) -> tuple:
        margin = min(1.0, max(0.5, self.duration * 0.02)) if self.duration > 5 else 0.05
        hi = max(0.0, self.duration - margin)
        s = max(0.0, min(float(start), hi))
        e = max(s + 0.05, min(float(end), hi + 1e-6))
        return s, e

    def execute(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        normalized = self.normalize_arguments(name, args)
        try:
            if name == "global_overview":
                count = min(self.overview_frames, max(4, 4 if self.duration <= 120 else self.overview_frames))
                if self.duration > 3600:
                    count = min(12, max(6, self.overview_frames))
                out = self._visual(0.0, self.duration, count=count, purpose="global_overview", layer=1)
            elif name == "partition_scan":
                out = self._visual(
                    normalized["start"],
                    normalized["end"],
                    count=self.partition_frames,
                    purpose="partition_scan",
                    layer=2,
                )
            elif name == "localize_event":
                span = normalized["end"] - normalized["start"]
                count = min(6, max(3, ceil(span / 8.0)))
                out = self._visual(
                    normalized["start"],
                    normalized["end"],
                    count=count,
                    purpose="localize_event",
                    layer=3,
                )
            elif name == "verify_evidence":
                out = self._visual(
                    normalized["start"],
                    normalized["end"],
                    count=4,
                    purpose="verify_evidence",
                    layer=4,
                )
            elif name == "read_scoreboard_window":
                out = self._visual(
                    normalized["start"],
                    normalized["end"],
                    count=4,
                    purpose="read_scoreboard_window",
                    layer=4,
                    scoreboard_focus=True,
                )
            else:
                raise ToolArgumentError(f"unhandled {name}")
        except FrameBudgetExhausted as exc:
            out = {
                "error": "FrameBudgetExhausted",
                "message": str(exc),
                "unresolved": True,
                "purpose": name,
                "media_start_sec": normalized.get("start"),
                "media_end_sec": normalized.get("end"),
            }
        self._call_log.append({"tool": name, "arguments": normalized, "ok": "error" not in out})
        return out

    def _visual(
        self,
        start: float,
        end: float,
        *,
        count: int,
        purpose: str,
        layer: int,
        scoreboard_focus: bool = False,
    ) -> Dict[str, Any]:
        start, end = self._safe_window(start, end)
        gap_id = f"v2b_{purpose}"
        records = self.store.extract_window(
            start=start, end=end, count=count, gap_id=gap_id, tool=purpose
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
            f"layer={layer}; purpose={purpose}; media_window=[{start:.3f},{end:.3f}]; "
            f"task={self.task_note}; "
            "Samples are SPARSE — not continuous video. "
            "Never invent events between frames. "
            "Separate visible facts vs uncertain guesses. "
            "Flag live vs replay if visible. "
            "Scoreboard change ≠ proven goal action localization."
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
        return {
            "purpose": purpose,
            "layer": layer,
            "media_start_sec": start,
            "media_end_sec": end,
            "sampled_media_times": [r.requested_media_sec for r in records],
            "frames": [
                {
                    "frame_id": r.frame_id,
                    "requested_media_sec": r.requested_media_sec,
                    "actual_media_sec": r.actual_media_sec,
                    "pts_status": r.pts_status,
                }
                for r in records
            ],
            "sampling_note": "sparse hierarchical sample",
            "perception": evidence,
            "fact_verified": False,
            "observation_only": True,
        }

    @property
    def call_log(self) -> List[Dict[str, Any]]:
        return list(self._call_log)
