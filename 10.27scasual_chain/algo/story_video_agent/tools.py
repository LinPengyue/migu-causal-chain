"""可扩展视频工具箱：第一阶段只做参数校验与 dry-run stub，不碰真实视频推理。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class ToolArgumentError(ValueError):
    """Repairable before media/provider execution; not a provider failure."""


class ToolBox:
    """Story Video Agent 工具面。execute 一律返回 dry-run 占位，不调用外部 API。"""

    def __init__(self, item: Dict[str, Any], *, dry_run: bool = True) -> None:
        self.item = item
        self.dry_run = dry_run
        duration = float(item.get("duration_sec") or item.get("duration") or 0.0)
        self.duration = max(0.0, duration)

    def descriptions(self) -> Dict[str, str]:
        duration = self.duration
        time_hint = (
            f" Times: numeric seconds; require 0 <= start < end <= {duration:g}."
            if duration > 0
            else " Times: numeric seconds; duration unknown until video meta is attached."
        )
        return {
            "list_story_gaps": (
                "List narrative evidence gaps from the current T01 story state. "
                "Arguments {}. No media access."
            ),
            "register_evidence_task": (
                "Register one evidence task for a gap. Arguments: "
                "gap_id (str), tool_hint (one of inspect_story_window|read_scoreboard_window|"
                "scan_reaction_window), start (sec), end (sec), note (str)."
                + time_hint
            ),
            "inspect_story_window": (
                "PHASE1 STUB. Would sample short visual frames in [start,end] for action detail. "
                "Arguments start,end; span <= 16s."
                + time_hint
            ),
            "read_scoreboard_window": (
                "PHASE1 STUB. Would OCR scoreboard/text in [start,end]. "
                "Arguments start,end; span <= 16s."
                + time_hint
            ),
            "scan_reaction_window": (
                "PHASE1 STUB. Would scan a short post-event window for celebration/reaction shots. "
                "Arguments start,end; span <= 32s."
                + time_hint
            ),
            "finish_evidence_plan": (
                "Terminal action: freeze the evidence task list and stop the loop. Arguments {}."
            ),
        }

    def normalize_arguments(self, name: str, args: Any) -> Dict[str, Any]:
        """Single source for pre-dispatch repair and execution validation. No IO."""
        if name not in self.descriptions():
            raise ToolArgumentError(f"unknown tool {name}; choose a listed tool")
        if not isinstance(args, dict):
            raise ToolArgumentError("arguments must be an object")

        if name in ("list_story_gaps", "finish_evidence_plan"):
            if args:
                raise ToolArgumentError(f"{name}: no arguments allowed")
            return {}

        if name == "register_evidence_task":
            required = {"gap_id", "tool_hint", "start", "end", "note"}
            missing = required - set(args)
            if missing:
                raise ToolArgumentError(f"register_evidence_task missing {sorted(missing)}")
            extra = set(args) - required
            if extra:
                raise ToolArgumentError(f"register_evidence_task unsupported {sorted(extra)}")
            hint = str(args["tool_hint"])
            allowed_hints = {
                "inspect_story_window",
                "read_scoreboard_window",
                "scan_reaction_window",
            }
            if hint not in allowed_hints:
                raise ToolArgumentError(
                    f"tool_hint must be one of {sorted(allowed_hints)}; got {hint}"
                )
            start, end = self._window(name, args["start"], args["end"], max_span=None)
            return {
                "gap_id": str(args["gap_id"]),
                "tool_hint": hint,
                "start": start,
                "end": end,
                "note": str(args["note"]),
            }

        if name in ("inspect_story_window", "read_scoreboard_window"):
            if set(args) != {"start", "end"}:
                raise ToolArgumentError(f"{name} requires only start,end")
            start, end = self._window(name, args["start"], args["end"], max_span=16.0)
            return {"start": start, "end": end}

        if name == "scan_reaction_window":
            if set(args) != {"start", "end"}:
                raise ToolArgumentError(f"{name} requires only start,end")
            start, end = self._window(name, args["start"], args["end"], max_span=32.0)
            return {"start": start, "end": end}

        raise ToolArgumentError(f"unhandled tool {name}")

    def _window(
        self,
        name: str,
        start_raw: Any,
        end_raw: Any,
        *,
        max_span: Optional[float],
    ) -> tuple:
        try:
            start = float(start_raw)
            end = float(end_raw)
        except (TypeError, ValueError) as exc:
            raise ToolArgumentError(f"{name}: start/end must be numeric seconds") from exc
        if self.duration > 0:
            if not 0 <= start < end <= self.duration + 1e-6:
                raise ToolArgumentError(
                    f"{name}: requested start={start:g}, end={end:g}; "
                    f"require 0 <= start < end <= {self.duration:g}"
                )
        elif not start < end:
            raise ToolArgumentError(f"{name}: require start < end")
        span = end - start
        if max_span is not None and span > max_span + 1e-6:
            raise ToolArgumentError(f"{name}: span {span:g}s exceeds max {max_span:g}s")
        return start, end

    def execute(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        normalized = self.normalize_arguments(name, args)
        if not self.dry_run:
            raise RuntimeError(
                "phase1 ToolBox refuses non-dry-run execution; "
                "wire real video providers in a later stage"
            )
        if name == "list_story_gaps":
            gaps = list(self.item.get("gaps") or [])
            return {"dry_run": True, "gaps": gaps, "count": len(gaps)}
        if name == "register_evidence_task":
            task = {
                "task_id": f"task_{normalized['gap_id']}",
                "gap_id": normalized["gap_id"],
                "tool_hint": normalized["tool_hint"],
                "window": {"start": normalized["start"], "end": normalized["end"]},
                "note": normalized["note"],
                "status": "planned",
                "provider": None,
            }
            return {"dry_run": True, "registered": task}
        if name == "finish_evidence_plan":
            return {"dry_run": True, "finished": True}
        return {
            "dry_run": True,
            "tool": name,
            "arguments": normalized,
            "message": "stub only; no frames sampled, no OCR, no ASR",
            "observation": None,
        }
