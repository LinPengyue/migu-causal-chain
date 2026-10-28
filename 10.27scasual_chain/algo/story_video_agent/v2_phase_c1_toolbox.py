"""Phase C-1 localization tools with denser sampling inside candidate windows."""

from __future__ import annotations

from math import ceil
from typing import Any, Dict, List, Optional

from story_video_agent.frames import FrameBudgetExhausted, FrameStore
from story_video_agent.tools import ToolArgumentError
from story_video_agent.vision_provider import VisionProvider

COARSE_MAX = 120.0
REFINE_MAX = 20.0
DENSE_MAX = 12.0
SCORE_MAX = 16.0


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


class V2PhaseC1Toolbox:
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
            "Localize live football goal actions for a T01 candidate. "
            "Sparse/dense samples still do not fill unobserved gaps. "
            "Separate scoreboard-only vs shot/net action. Flag live vs replay."
        )
        self._call_log: List[Dict[str, Any]] = []

    def descriptions(self) -> Dict[str, str]:
        return {
            "coarse_search": (
                f"Coarse search in a candidate score-change neighborhood "
                f"(8 < span <= {COARSE_MAX:g}s, ~6 frames). Args: start,end,task_id."
            ),
            "refine_window": (
                f"Shrink to a smaller candidate (2 < span <= {REFINE_MAX:g}s, ~6 frames). "
                "Args: start,end,task_id."
            ),
            "dense_action_inspect": (
                f"Dense sampling inside a short action window "
                f"(0.5 < span <= {DENSE_MAX:g}s, up to 10 frames ~0.5–1s step). "
                "Args: start,end,task_id."
            ),
            "read_scoreboard_window": (
                f"Scoreboard focus (<= {SCORE_MAX:g}s). Args: start,end,task_id?"
            ),
            "verify_live_replay": (
                f"Check live vs replay cues in a short window (<= {SCORE_MAX:g}s). "
                "Args: start,end,task_id."
            ),
        }

    def normalize_arguments(self, name: str, args: Any) -> Dict[str, Any]:
        if name not in self.descriptions():
            raise ToolArgumentError(f"unknown tool {name}")
        if not isinstance(args, dict):
            raise ToolArgumentError("arguments must be object")
        allowed = {"start", "end", "task_id"}
        if set(args) - allowed:
            raise ToolArgumentError(f"unsupported keys {sorted(set(args) - allowed)}")
        if not {"start", "end"} <= set(args):
            raise ToolArgumentError(f"{name} requires start,end")
        start, end = _seconds(args["start"]), _seconds(args["end"])
        if not 0 <= start < end <= self.duration + 1e-6:
            raise ToolArgumentError(f"need 0<=start<end<={self.duration:g}")
        span = end - start
        # Auto-shrink oversized windows instead of aborting the whole run.
        if name == "coarse_search":
            if span <= 8.0:
                end = min(self.duration, start + 20.0)
                span = end - start
            if span > COARSE_MAX:
                end = start + COARSE_MAX
                span = end - start
            if not (8.0 < span <= COARSE_MAX + 1e-6):
                raise ToolArgumentError(f"coarse_search span {span:g} invalid")
        if name == "refine_window":
            if span > REFINE_MAX:
                mid = 0.5 * (start + end)
                start = max(0.0, mid - REFINE_MAX / 2)
                end = min(self.duration, start + REFINE_MAX)
                span = end - start
            if not (2.0 < span <= REFINE_MAX + 1e-6):
                raise ToolArgumentError(f"refine_window span {span:g} invalid")
        if name == "dense_action_inspect":
            if span > DENSE_MAX:
                mid = 0.5 * (start + end)
                start = max(0.0, mid - DENSE_MAX / 2)
                end = min(self.duration, start + DENSE_MAX)
                span = end - start
            if not (0.5 < span <= DENSE_MAX + 1e-6):
                raise ToolArgumentError(f"dense_action_inspect span {span:g} invalid")
        if name in ("read_scoreboard_window", "verify_live_replay"):
            if span > SCORE_MAX:
                mid = 0.5 * (start + end)
                start = max(0.0, mid - SCORE_MAX / 2)
                end = min(self.duration, start + SCORE_MAX)
                span = end - start
            if span > SCORE_MAX + 1e-6:
                raise ToolArgumentError(f"{name} span {span:g} > {SCORE_MAX:g}")
        out = {"start": start, "end": end}
        if args.get("task_id"):
            out["task_id"] = str(args["task_id"])
        return out

    def _safe_window(self, start: float, end: float) -> tuple:
        margin = min(1.0, max(0.5, self.duration * 0.02)) if self.duration > 5 else 0.05
        hi = max(0.0, self.duration - margin)
        s = max(0.0, min(float(start), hi))
        e = max(s + 0.05, min(float(end), hi + 1e-6))
        return s, e

    def execute(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        norm = self.normalize_arguments(name, args)
        try:
            if name == "coarse_search":
                out = self._visual(norm["start"], norm["end"], count=6, purpose=name, dense=False)
            elif name == "refine_window":
                out = self._visual(norm["start"], norm["end"], count=6, purpose=name, dense=False)
            elif name == "dense_action_inspect":
                span = norm["end"] - norm["start"]
                # ~0.5–1.0s steps, cap 10 frames
                count = min(10, max(4, int(ceil(span / 0.75)) + 1))
                out = self._visual(norm["start"], norm["end"], count=count, purpose=name, dense=True)
            elif name == "read_scoreboard_window":
                out = self._visual(
                    norm["start"], norm["end"], count=4, purpose=name, dense=False, scoreboard=True
                )
            elif name == "verify_live_replay":
                out = self._visual(norm["start"], norm["end"], count=4, purpose=name, dense=False)
            else:
                raise ToolArgumentError(name)
            out["task_id"] = norm.get("task_id")
        except FrameBudgetExhausted as exc:
            out = {
                "error": "FrameBudgetExhausted",
                "message": str(exc),
                "purpose": name,
                "task_id": norm.get("task_id"),
                "media_start_sec": norm.get("start"),
                "media_end_sec": norm.get("end"),
            }
        self._call_log.append({"tool": name, "arguments": norm, "ok": "error" not in out})
        return out

    def _visual(
        self,
        start: float,
        end: float,
        *,
        count: int,
        purpose: str,
        dense: bool,
        scoreboard: bool = False,
    ) -> Dict[str, Any]:
        start, end = self._safe_window(start, end)
        gap_id = f"v2c1_{purpose}"
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
            f"purpose={purpose}; dense={dense}; media=[{start:.3f},{end:.3f}]; "
            f"{self.task_note} "
            "If only scoreboard/celebration without shot/net, say so. "
            "Do not invent unobserved contacts between frames."
        )
        if scoreboard:
            note += " Focus on scoreboard digits."
        if dense:
            note += " Frames are denser but still discrete samples."
        evidence = self.vision.describe_frames(
            gap_id=gap_id,
            gap_note=note,
            frame_paths=paths,
            frame_ids=frame_ids,
            frame_bindings=bindings,
        )
        return {
            "purpose": purpose,
            "dense": dense,
            "media_start_sec": start,
            "media_end_sec": end,
            "sampled_media_times": [r.requested_media_sec for r in records],
            "frames": [
                {
                    "frame_id": r.frame_id,
                    "requested_media_sec": r.requested_media_sec,
                    "actual_media_sec": r.actual_media_sec,
                    "pts_status": r.pts_status,
                    "path": r.path,
                }
                for r in records
            ],
            "perception": evidence,
            "fact_verified": False,
            "observation_only": True,
        }

    @property
    def call_log(self) -> List[Dict[str, Any]]:
        return list(self._call_log)
