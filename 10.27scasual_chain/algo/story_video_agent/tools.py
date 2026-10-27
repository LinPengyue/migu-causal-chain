"""可扩展视频工具箱：Phase 1.5 参数校验 + dry-run stub，不碰真实视频推理。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class ToolArgumentError(ValueError):
    """Repairable before media/provider execution; not a provider failure."""


_ALLOWED_HINTS = frozenset(
    {"inspect_story_window", "read_scoreboard_window", "scan_reaction_window"}
)


class ToolBox:
    """Story Video Agent 工具面。execute 一律 dry-run，不调用外部 API。"""

    def __init__(self, item: Dict[str, Any], *, dry_run: bool = True) -> None:
        self.item = item
        self.dry_run = dry_run
        duration = float(item.get("duration_sec") or item.get("duration") or 0.0)
        self.duration = max(0.0, duration)
        self.duration_known = bool(item.get("duration_known")) or self.duration > 0

    def descriptions(self) -> Dict[str, str]:
        duration = self.duration
        time_hint = (
            f" Times: numeric seconds; require 0 <= start < end <= {duration:g}."
            if self.duration_known
            else " Times: numeric seconds; duration unknown — windows flagged, not hard-clipped."
        )
        return {
            "list_story_gaps": (
                "List narrative evidence gaps from the current T01 story state. "
                "Arguments {}. No media access."
            ),
            "register_evidence_task": (
                "Register one evidence task for a registerable gap. Arguments: gap_id (str). "
                "Optional overrides: tool_hint, start, end, note. "
                "Creates status=pending only; never verified."
                + time_hint
            ),
            "inspect_story_window": (
                "PHASE1 STUB. Would sample short visual frames in [start,end]. "
                "Arguments start,end; span <= 16s."
                + time_hint
            ),
            "read_scoreboard_window": (
                "PHASE1 STUB. Would OCR scoreboard in [start,end]. "
                "Arguments start,end; span <= 16s."
                + time_hint
            ),
            "scan_reaction_window": (
                "PHASE1 STUB. Would scan reaction/celebration in [start,end]. "
                "Arguments start,end; span <= 32s."
                + time_hint
            ),
            "finish_evidence_plan": (
                "Terminal action: freeze the evidence task list and stop the loop. Arguments {}."
            ),
        }

    def normalize_arguments(self, name: str, args: Any) -> Dict[str, Any]:
        if name not in self.descriptions():
            raise ToolArgumentError(f"unknown tool {name}; choose a listed tool")
        if not isinstance(args, dict):
            raise ToolArgumentError("arguments must be an object")

        if name in ("list_story_gaps", "finish_evidence_plan"):
            if args:
                raise ToolArgumentError(f"{name}: no arguments allowed")
            return {}

        if name == "register_evidence_task":
            if "gap_id" not in args:
                raise ToolArgumentError("register_evidence_task missing gap_id")
            allowed = {"gap_id", "tool_hint", "start", "end", "note"}
            extra = set(args) - allowed
            if extra:
                raise ToolArgumentError(f"register_evidence_task unsupported {sorted(extra)}")
            gap_id = str(args["gap_id"])
            gap = self._gap_by_id(gap_id)
            if gap is None:
                raise ToolArgumentError(f"unknown gap_id {gap_id}")
            if not gap.get("registerable", True):
                raise ToolArgumentError(f"gap {gap_id} is not registerable")
            hint = str(args.get("tool_hint") or gap.get("tool_hint") or "")
            if hint not in _ALLOWED_HINTS:
                raise ToolArgumentError(f"tool_hint must be one of {sorted(_ALLOWED_HINTS)}")
            if "start" in args or "end" in args:
                if not {"start", "end"} <= set(args):
                    raise ToolArgumentError("start and end must be provided together")
                start, end = self._window(name, args["start"], args["end"], max_span=None)
            else:
                seed = (gap.get("seed_windows") or [None])[0]
                interval = (gap.get("search_intervals") or [None])[0]
                source = seed or interval
                if not source:
                    raise ToolArgumentError(
                        f"gap {gap_id} has no seed_window/search_interval to register"
                    )
                start, end = self._window(
                    name, source["start"], source["end"], max_span=None
                )
            note = str(args.get("note") or gap.get("note") or "")
            return {
                "gap_id": gap_id,
                "tool_hint": hint,
                "start": start,
                "end": end,
                "note": note,
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

    def _gap_by_id(self, gap_id: str) -> Optional[Dict[str, Any]]:
        for gap in self.item.get("gaps") or []:
            if str(gap.get("gap_id")) == gap_id:
                return gap
        return None

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
        if not start < end:
            raise ToolArgumentError(f"{name}: require start < end (got {start:g},{end:g})")
        if self.duration_known:
            if start < 0 or end > self.duration + 1e-6:
                raise ToolArgumentError(
                    f"{name}: window [{start:g},{end:g}] outside [0,{self.duration:g}]"
                )
        span = end - start
        if max_span is not None and span > max_span + 1e-6:
            raise ToolArgumentError(f"{name}: span {span:g}s exceeds max {max_span:g}s")
        return start, end

    def execute(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        normalized = self.normalize_arguments(name, args)
        if not self.dry_run:
            raise RuntimeError(
                "phase1.5 ToolBox refuses non-dry-run execution; "
                "wire real video providers in a later stage"
            )
        if name == "list_story_gaps":
            gaps = list(self.item.get("gaps") or [])
            return {
                "dry_run": True,
                "gaps": gaps,
                "count": len(gaps),
                "registerable_count": sum(1 for g in gaps if g.get("registerable", True)),
            }
        if name == "register_evidence_task":
            gap = self._gap_by_id(normalized["gap_id"]) or {}
            task = {
                "task_id": f"task_{normalized['gap_id']}",
                "gap_id": normalized["gap_id"],
                "kind": gap.get("kind"),
                "tool_hint": normalized["tool_hint"],
                "window": {"start": normalized["start"], "end": normalized["end"]},
                "search_intervals": list(gap.get("search_intervals") or []),
                "seed_windows": list(gap.get("seed_windows") or []),
                "score_anchor_sec": gap.get("score_anchor_sec"),
                "goal_anchor_sec": gap.get("goal_anchor_sec"),
                "anchor_status": gap.get("anchor_status") or "unknown",
                "adaptive_expand": bool(gap.get("adaptive_expand")),
                "note": normalized["note"],
                "status": "pending",
                "provider": None,
                "duration_known": self.duration_known,
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
            "status": "pending",
        }
