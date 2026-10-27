"""可扩展视频工具箱：dry-run / media-only / perception（抽帧 + VLM 描述）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from story_video_agent.frames import (
    COARSE_MAX_SPAN,
    LOCAL_MAX_SPAN,
    REACTION_MAX_SPAN,
    FrameBudgetExhausted,
    FrameStore,
    plan_sample_count,
)
from story_video_agent.media import MediaError, MediaInfo, probe_video
from story_video_agent.vision_provider import VisionProvider


class ToolArgumentError(ValueError):
    """Repairable before media/provider execution; not a provider failure."""


_ALLOWED_HINTS = frozenset(
    {
        "inspect_story_window",
        "read_scoreboard_window",
        "scan_reaction_window",
        "coarse_search_interval",
    }
)


class ToolBox:
    """Story Video Agent 工具面。

    - dry_run: stub
    - media_only: FFmpeg 抽帧 → sampled
    - perception: 抽帧 + inspect_visual_evidence → observed（≠ verified）
    """

    def __init__(
        self,
        item: Dict[str, Any],
        *,
        dry_run: bool = True,
        media_only: bool = False,
        perception: bool = False,
        frame_store: Optional[FrameStore] = None,
        media_info: Optional[MediaInfo] = None,
        vision: Optional[VisionProvider] = None,
        max_coarse_per_gap: int = 1,
        focus_gap_ids: Optional[Sequence[str]] = None,
    ) -> None:
        modes = sum(bool(x) for x in (dry_run, media_only, perception))
        if modes != 1:
            raise ValueError("exactly one of dry_run / media_only / perception required")
        self.item = item
        self.dry_run = dry_run
        self.media_only = media_only
        self.perception = perception
        self.media_info = media_info
        self.frame_store = frame_store
        self.vision = vision
        self.max_coarse_per_gap = max(1, int(max_coarse_per_gap))
        self.focus_gap_ids = set(focus_gap_ids or [])
        duration = float(item.get("duration_sec") or item.get("duration") or 0.0)
        if media_info is not None:
            duration = float(media_info.duration_sec)
        self.duration = max(0.0, duration)
        self.duration_known = bool(item.get("duration_known")) or self.duration > 0
        self._gap_search_cursor: Dict[str, int] = {}
        self._gap_seed_cursor: Dict[str, int] = {}
        self._gap_coarse_count: Dict[str, int] = {}
        self._probed = media_info is not None

    def descriptions(self) -> Dict[str, str]:
        duration = self.duration
        time_hint = (
            f" Times: numeric media seconds; require 0 <= start < end <= {duration:g}."
            if self.duration_known
            else " Times: numeric media seconds; duration unknown — windows flagged, not hard-clipped."
        )
        return {
            "probe_video_media": (
                "Probe local video via ffprobe (duration/fps/resolution). Arguments {}."
            ),
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
            "coarse_search_interval": (
                "Coarse visual search over a media interval up to 90s (sparse frames). "
                "Arguments: gap_id, start, end. Do NOT use inspect_story_window for 90s spans."
                + time_hint
            ),
            "inspect_story_window": (
                "Local visual observation in [start,end], span <= 16s. "
                "Arguments: start,end; optional gap_id."
                + time_hint
            ),
            "read_scoreboard_window": (
                "Local scoreboard window [start,end], span <= 16s (frames only, no OCR model). "
                "Arguments start,end; optional gap_id."
                + time_hint
            ),
            "scan_reaction_window": (
                "Reaction/celebration window [start,end], span <= 32s. "
                "Arguments start,end; optional gap_id."
                + time_hint
            ),
            "sample_next_evidence": (
                "Advance one sampling step for a gap: prefer seed_windows, else next "
                "search_interval via coarse_search. Arguments: gap_id."
            ),
            "inspect_visual_evidence": (
                "Run VLM over already extracted frames. Arguments: gap_id, frame_ids (list). "
                "Returns strict JSON observation; timestamps bound by program only. "
                "Success marks observed, never verified."
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

        if name in ("list_story_gaps", "finish_evidence_plan", "probe_video_media"):
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
            if self.focus_gap_ids and gap_id not in self.focus_gap_ids:
                raise ToolArgumentError(f"gap {gap_id} outside focus set")
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
                if end - start > LOCAL_MAX_SPAN + 1e-6 and hint == "inspect_story_window":
                    hint = "coarse_search_interval"
            note = str(args.get("note") or gap.get("note") or "")
            return {
                "gap_id": gap_id,
                "tool_hint": hint,
                "start": start,
                "end": end,
                "note": note,
            }

        if name == "sample_next_evidence":
            if set(args) != {"gap_id"}:
                raise ToolArgumentError("sample_next_evidence requires only gap_id")
            gap_id = str(args["gap_id"])
            if self._gap_by_id(gap_id) is None:
                raise ToolArgumentError(f"unknown gap_id {gap_id}")
            return {"gap_id": gap_id}

        if name == "inspect_visual_evidence":
            if "gap_id" not in args or "frame_ids" not in args:
                raise ToolArgumentError("inspect_visual_evidence requires gap_id, frame_ids")
            extra = set(args) - {"gap_id", "frame_ids"}
            if extra:
                raise ToolArgumentError(f"inspect_visual_evidence unsupported {sorted(extra)}")
            gap_id = str(args["gap_id"])
            if self._gap_by_id(gap_id) is None:
                raise ToolArgumentError(f"unknown gap_id {gap_id}")
            raw_ids = args["frame_ids"]
            if not isinstance(raw_ids, list) or not raw_ids:
                raise ToolArgumentError("frame_ids must be a non-empty list")
            frame_ids = [str(x) for x in raw_ids]
            return {"gap_id": gap_id, "frame_ids": frame_ids}

        if name == "coarse_search_interval":
            required = {"gap_id", "start", "end"}
            if set(args) != required:
                raise ToolArgumentError("coarse_search_interval requires gap_id,start,end")
            start, end = self._window(name, args["start"], args["end"], max_span=COARSE_MAX_SPAN)
            return {"gap_id": str(args["gap_id"]), "start": start, "end": end}

        if name in ("inspect_story_window", "read_scoreboard_window"):
            allowed = {"start", "end", "gap_id"}
            if not {"start", "end"} <= set(args) or set(args) - allowed:
                raise ToolArgumentError(f"{name} requires start,end and optional gap_id")
            start, end = self._window(name, args["start"], args["end"], max_span=LOCAL_MAX_SPAN)
            out = {"start": start, "end": end}
            if "gap_id" in args:
                out["gap_id"] = str(args["gap_id"])
            return out

        if name == "scan_reaction_window":
            allowed = {"start", "end", "gap_id"}
            if not {"start", "end"} <= set(args) or set(args) - allowed:
                raise ToolArgumentError(f"{name} requires start,end and optional gap_id")
            start, end = self._window(name, args["start"], args["end"], max_span=REACTION_MAX_SPAN)
            out = {"start": start, "end": end}
            if "gap_id" in args:
                out["gap_id"] = str(args["gap_id"])
            return out

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
        if self.dry_run:
            return self._execute_dry(name, normalized)
        return self._execute_media(name, normalized)

    def _execute_dry(self, name: str, normalized: Dict[str, Any]) -> Dict[str, Any]:
        if name == "probe_video_media":
            return {"dry_run": True, "probed": False, "message": "stub only; no ffprobe", "media": None}
        if name == "list_story_gaps":
            gaps = list(self.item.get("gaps") or [])
            if self.focus_gap_ids:
                gaps = [g for g in gaps if g.get("gap_id") in self.focus_gap_ids]
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
                "frames": [],
            }
            return {"dry_run": True, "registered": task}
        if name == "finish_evidence_plan":
            return {"dry_run": True, "finished": True}
        if name == "sample_next_evidence":
            return {
                "dry_run": True,
                "gap_id": normalized["gap_id"],
                "sampled": False,
                "message": "stub; no frames",
                "frames": [],
                "status": "pending",
            }
        if name == "inspect_visual_evidence":
            return {
                "dry_run": True,
                "gap_id": normalized["gap_id"],
                "frame_ids": normalized["frame_ids"],
                "message": "stub; no VLM",
                "status": "pending",
                "fact_verified": False,
            }
        return {
            "dry_run": True,
            "tool": name,
            "arguments": normalized,
            "message": "stub only; no frames sampled, no OCR, no ASR",
            "frames": [],
            "observation": None,
            "status": "pending",
        }

    def _require_store(self) -> FrameStore:
        if self.frame_store is None or self.media_info is None:
            raise MediaError("media/perception mode requires probed video and frame store")
        return self.frame_store

    def _execute_media(self, name: str, normalized: Dict[str, Any]) -> Dict[str, Any]:
        if name == "probe_video_media":
            path = self.item.get("video_path") or ""
            info = probe_video(path)
            self.media_info = info
            self.duration = info.duration_sec
            self.duration_known = True
            self.item["duration_sec"] = info.duration_sec
            self.item["duration"] = info.duration_sec
            self.item["duration_known"] = True
            self.item["media_info"] = info.to_dict()
            self._probed = True
            return {
                "dry_run": False,
                "media_only": self.media_only,
                "perception": self.perception,
                "probed": True,
                "media": info.to_dict(),
            }

        if name == "list_story_gaps":
            gaps = list(self.item.get("gaps") or [])
            if self.focus_gap_ids:
                gaps = [g for g in gaps if g.get("gap_id") in self.focus_gap_ids]
            return {
                "dry_run": False,
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
                "provider": "ffmpeg",
                "duration_known": self.duration_known,
                "frames": [],
            }
            return {"dry_run": False, "registered": task}

        if name == "finish_evidence_plan":
            return {"dry_run": False, "finished": True}

        if name == "sample_next_evidence":
            return self._sample_next(normalized["gap_id"])

        if name == "inspect_visual_evidence":
            return self._inspect_visual(normalized["gap_id"], normalized["frame_ids"])

        if name == "coarse_search_interval":
            return self._sample_window(
                tool=name,
                gap_id=normalized["gap_id"],
                start=normalized["start"],
                end=normalized["end"],
                coarse=True,
            )

        if name in ("inspect_story_window", "read_scoreboard_window", "scan_reaction_window"):
            return self._sample_window(
                tool=name,
                gap_id=str(normalized.get("gap_id") or ""),
                start=normalized["start"],
                end=normalized["end"],
                coarse=False,
            )

        raise MediaError(f"unhandled media tool {name}")

    def _sample_window(
        self,
        *,
        tool: str,
        gap_id: str,
        start: float,
        end: float,
        coarse: bool,
    ) -> Dict[str, Any]:
        store = self._require_store()
        span = end - start
        if coarse and span > COARSE_MAX_SPAN + 1e-6:
            raise ToolArgumentError(f"coarse span {span:g}s exceeds {COARSE_MAX_SPAN:g}s")
        if not coarse and tool != "scan_reaction_window" and span > LOCAL_MAX_SPAN + 1e-6:
            raise ToolArgumentError(
                f"{tool} rejects span {span:g}s; use coarse_search_interval for <=90s"
            )
        want = plan_sample_count(span, coarse=coarse)
        want = min(want, max(1, store.budget.remaining_for(gap_id or "unknown")))
        if store.budget.remaining_for(gap_id or "unknown") <= 0:
            raise FrameBudgetExhausted(f"no frame budget remaining for {gap_id}")
        frames = store.extract_window(
            start,
            end,
            gap_id=gap_id or "unknown",
            tool=tool,
            count=want,
            match_logic_calibrated=False,
        )
        return {
            "dry_run": False,
            "media_only": self.media_only,
            "perception": self.perception,
            "tool": tool,
            "gap_id": gap_id,
            "window": {"start": start, "end": end},
            "frames": [f.to_dict() for f in frames],
            "frame_count": len(frames),
            "budget_remaining": store.budget.remaining,
            "status": "sampled" if frames else "pending",
            "verification": False,
            "fact_verified": False,
        }

    def _sample_next(self, gap_id: str) -> Dict[str, Any]:
        gap = self._gap_by_id(gap_id) or {}
        seeds = list(gap.get("seed_windows") or [])
        intervals = list(gap.get("search_intervals") or [])
        seed_i = self._gap_seed_cursor.get(gap_id, 0)
        if seed_i < len(seeds):
            window = seeds[seed_i]
            self._gap_seed_cursor[gap_id] = seed_i + 1
            start, end = float(window["start"]), float(window["end"])
            span = end - start
            if span > LOCAL_MAX_SPAN + 1e-6:
                if span > COARSE_MAX_SPAN + 1e-6:
                    end = start + COARSE_MAX_SPAN
                return self._sample_window(
                    tool="coarse_search_interval",
                    gap_id=gap_id,
                    start=start,
                    end=end,
                    coarse=True,
                )
            hint = str(gap.get("tool_hint") or "inspect_story_window")
            tool = (
                hint
                if hint
                in ("inspect_story_window", "read_scoreboard_window", "scan_reaction_window")
                else "inspect_story_window"
            )
            return self._sample_window(
                tool=tool, gap_id=gap_id, start=start, end=end, coarse=False
            )

        coarse_used = self._gap_coarse_count.get(gap_id, 0)
        if coarse_used >= self.max_coarse_per_gap:
            return {
                "dry_run": False,
                "gap_id": gap_id,
                "sampled": False,
                "stopped": True,
                "reason": "gap_coarse_quota",
                "frames": [],
                "status": "sampled",
            }

        search_i = self._gap_search_cursor.get(gap_id, 0)
        if search_i >= len(intervals):
            return {
                "dry_run": False,
                "gap_id": gap_id,
                "sampled": False,
                "stopped": True,
                "reason": "no_more_intervals",
                "frames": [],
                "status": "sampled",
            }

        interval = intervals[search_i]
        self._gap_search_cursor[gap_id] = search_i + 1
        self._gap_coarse_count[gap_id] = coarse_used + 1
        start, end = float(interval["start"]), float(interval["end"])
        if end - start > COARSE_MAX_SPAN + 1e-6:
            end = start + COARSE_MAX_SPAN
        return self._sample_window(
            tool="coarse_search_interval",
            gap_id=gap_id,
            start=start,
            end=end,
            coarse=True,
        )

    def _inspect_visual(self, gap_id: str, frame_ids: List[str]) -> Dict[str, Any]:
        if not self.perception:
            raise MediaError("inspect_visual_evidence requires perception mode")
        if self.vision is None:
            raise MediaError("vision provider not configured")
        store = self._require_store()
        gap = self._gap_by_id(gap_id) or {}
        paths = []
        bindings = []
        for fid in frame_ids:
            rec = store.get_frame(fid)
            if rec is None:
                # try manifest
                hit = next((r for r in store.manifest if r.get("frame_id") == fid), None)
                if not hit or not Path(str(hit.get("path") or "")).is_file():
                    raise ToolArgumentError(f"unknown or missing frame_id {fid}")
                paths.append(Path(str(hit["path"])))
                bindings.append(hit)
            else:
                paths.append(Path(rec.path))
                bindings.append(rec.to_dict())
        evidence = self.vision.describe_frames(
            gap_id=gap_id,
            gap_note=str(gap.get("note") or ""),
            frame_paths=paths,
            frame_ids=frame_ids,
            frame_bindings=bindings,
        )
        ok = "error" not in evidence
        return {
            "dry_run": False,
            "perception": True,
            "gap_id": gap_id,
            "frame_ids": frame_ids,
            "visual_evidence": evidence,
            "status": "observed" if ok else "unresolved",
            "fact_verified": False,
            "observation_only": True,
        }
