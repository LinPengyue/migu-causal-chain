"""Story Video Agent：Phase 2B dry-run / media-only / perception。"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from story_video_agent.agent import Agent
from story_video_agent.frames import (
    FrameBudget,
    FrameBudgetExhausted,
    FrameStore,
    allocate_gap_caps,
)
from story_video_agent.media import MediaError, probe_video
from story_video_agent.memory import Memory
from story_video_agent.state import (
    FRANCE_PERCEPTION_FOCUS,
    build_agent_item,
    detect_gaps,
    load_t01_story,
    validate_plan_payload,
)
from story_video_agent.api_provider import ApiProvider, api_enabled
from story_video_agent.tools import ToolBox
from story_video_agent.vision_provider import VisionProvider

ALGORITHM_ID = "t01_story_video_agent_phase2b"
SCHEMA_VERSION = "story-video-agent-plan-2b"


def _close_open_tasks(tasks: List[Dict[str, Any]], reason: str) -> None:
    for task in tasks:
        if task.get("status") in ("pending", "running", "sampled"):
            # sampled 但未观察完成 → unresolved（无有效视觉证据闭环）
            if task.get("status") == "sampled" and reason.startswith("frame"):
                task["status"] = "unresolved"
            elif task.get("status") in ("pending", "running"):
                task["status"] = "unresolved"
            task["unresolved_reason"] = reason


def _verification_complete(
    tasks: List[Dict[str, Any]], *, dry_run: bool, media_only: bool, perception: bool
) -> bool:
    if dry_run or media_only or perception:
        return False
    if not tasks:
        return False
    return all(task.get("status") == "verified" for task in tasks)


def _attach_frames_to_task(
    tasks: List[Dict[str, Any]], gap_id: str, frames: List[Dict[str, Any]]
) -> None:
    for task in tasks:
        if str(task.get("gap_id")) != gap_id:
            continue
        existing = list(task.get("frames") or [])
        existing.extend(frames)
        task["frames"] = existing
        if frames and task.get("status") in ("pending", "running", "sampled"):
            task["status"] = "sampled"
        return


def solve(
    story: Dict[str, Any],
    *,
    video_path: Optional[str] = None,
    duration_sec: Optional[float] = None,
    max_steps: int = 32,
    dry_run: bool = True,
    media_only: bool = False,
    perception: bool = False,
    frame_budget: int = 24,
    frame_dir: Optional[str] = None,
    manifest_path: Optional[str] = None,
    max_coarse_per_gap: int = 1,
    focus_gap_ids: Optional[Sequence[str]] = None,
    force_mock_vlm: bool = False,
    use_llm_planner: Optional[bool] = None,
) -> Dict[str, Any]:
    mode_flags = (dry_run, media_only, perception)
    if sum(bool(x) for x in mode_flags) != 1:
        raise ValueError("exactly one of dry_run / media_only / perception")

    media_info = None
    store = None
    vision = None
    # dry-run 强制 mock；perception/media 默认 mock，仅 STORY_API_ENABLE=1 走真实远程 API
    api = ApiProvider(force_mock=force_mock_vlm or dry_run or not api_enabled())
    if perception:
        vision = VisionProvider(api, force_mock=api.force_mock)

    if media_only or perception:
        if not video_path:
            raise MediaError("media_only/perception requires video_path")
        media_info = probe_video(video_path)
        duration_sec = media_info.duration_sec

    item = build_agent_item(story, video_path=video_path, duration_sec=duration_sec)
    if media_info is not None:
        item["duration_sec"] = media_info.duration_sec
        item["duration"] = media_info.duration_sec
        item["duration_known"] = True
        item["media_info"] = media_info.to_dict()
        item["gaps"] = detect_gaps(story, duration_sec=media_info.duration_sec)

    focus = list(focus_gap_ids) if focus_gap_ids is not None else []
    if focus:
        item["gaps"] = [g for g in item["gaps"] if g.get("gap_id") in set(focus)]

    if media_info is not None:
        gap_ids = [str(g.get("gap_id")) for g in item.get("gaps") or []]
        caps = allocate_gap_caps(gap_ids, global_budget=max(1, int(frame_budget)))
        out_dir = Path(frame_dir) if frame_dir else Path("reports") / "story_video_agent_frames_tmp"
        store = FrameStore(
            media_info,
            out_dir=out_dir,
            budget=FrameBudget(
                max_frames=max(1, int(frame_budget)),
                per_gap_caps=caps,
            ),
        )

    memory = Memory()
    toolbox = ToolBox(
        item,
        dry_run=dry_run,
        media_only=media_only,
        perception=perception,
        frame_store=store,
        media_info=media_info,
        vision=vision,
        max_coarse_per_gap=max_coarse_per_gap,
        focus_gap_ids=focus or None,
    )
    # 真实 LLM 规划：perception 默认开（若 API 可用）；dry-run 永远规则
    if use_llm_planner is None:
        use_llm_planner = bool(perception) and (not api.force_mock)
    agent = Agent(
        item,
        toolbox,
        api=api,
        use_llm_planner=bool(use_llm_planner) and not dry_run,
    )
    if media_info is not None:
        agent.mark_probed()
    trace: List[Dict[str, Any]] = []
    evidence_tasks: List[Dict[str, Any]] = []
    t_start = time.perf_counter()

    def finish(status: str, **extra: Any) -> Dict[str, Any]:
        if status in ("budget_exhausted", "frame_budget_exhausted"):
            _close_open_tasks(evidence_tasks, status)
            for task in evidence_tasks:
                if task.get("status") == "unresolved":
                    memory.mark_unresolved(str(task.get("gap_id")), status)
        # 感知模式：仍无 visual_evidence 的 sampled → unresolved
        if perception and status in ("sampled", "planned", "observed"):
            for task in evidence_tasks:
                gid = str(task.get("gap_id") or "")
                if task.get("status") == "sampled" and not task.get("visual_evidence"):
                    task["status"] = "unresolved"
                    task["unresolved_reason"] = "no_visual_evidence"
                    memory.mark_unresolved(gid, "no_visual_evidence")
        attempts = [a for t in trace for a in t.get("decision_attempts", [])]
        frame_rows = list(store.manifest) if store is not None else []
        written_manifest = None
        if store is not None and manifest_path:
            written_manifest = str(store.write_manifest(manifest_path))
        diagnostics = {
            "tool_argument_errors": sum(
                a.get("error_kind") == "tool_arguments" for a in attempts
            ),
            "decision_repair_calls": sum(a.get("attempt", 0) > 0 for a in attempts),
            "tool_execution_errors": sum(
                isinstance(t.get("observation"), dict)
                and "error" in t["observation"]
                and t["observation"].get("stage") != "pre_dispatch"
                for t in trace
            ),
            "open_task_count": sum(
                1 for t in evidence_tasks if t.get("status") in ("pending", "running")
            ),
            "unresolved_count": sum(
                1 for t in evidence_tasks if t.get("status") == "unresolved"
            ),
            "sampled_count": sum(1 for t in evidence_tasks if t.get("status") == "sampled"),
            "observed_count": sum(1 for t in evidence_tasks if t.get("status") == "observed"),
            "frame_count": len(frame_rows),
            "unique_frame_files": len({r.get("path") for r in frame_rows}),
            "frame_budget_used": store.budget.used if store else 0,
            "frame_budget_max": store.budget.max_frames if store else 0,
            "per_gap_caps": dict(store.budget.per_gap_caps) if store else {},
            "per_gap_used": dict(store.budget.per_gap_used) if store else {},
            "elapsed_sec": round(time.perf_counter() - t_start, 4),
            "vision": (vision.stats.to_dict() if vision else {}),
            "api": api.status(),
            "planner_modes": list(agent.planner_mode_log),
        }
        payload = {
            "schema_version": SCHEMA_VERSION,
            "algorithm": ALGORITHM_ID,
            "status": status,
            "match_id": item.get("match_id") or "",
            "video_name": item.get("video_name") or "",
            "video_path": item.get("video_path") or video_path or "",
            "story_tier": item.get("story_tier"),
            "has_story": item.get("has_story"),
            "is_candidate": item.get("is_candidate"),
            "story_label_zh": item.get("story_label_zh"),
            "dry_run": dry_run,
            "media_only": media_only,
            "perception": perception,
            "focus_gap_ids": list(focus),
            "duration_known": bool(item.get("duration_known")),
            "media_info": item.get("media_info"),
            "gaps": item.get("gaps") or [],
            "evidence_tasks": evidence_tasks,
            "visual_evidence": memory.visual_evidence,
            "memory_stages": memory.gap_stages,
            "frame_manifest": frame_rows,
            "frame_manifest_path": written_manifest,
            "verification_complete": _verification_complete(
                evidence_tasks,
                dry_run=dry_run,
                media_only=media_only,
                perception=perception,
            ),
            "trace": trace,
            "memory": memory.snapshot(),
            "diagnostics": diagnostics,
            **extra,
        }
        problems = validate_plan_payload(payload)
        payload["structure_ok"] = not problems
        payload["structure_problems"] = problems
        return payload

    for step in range(max_steps):
        try:
            decision = agent.decide(memory, step, max_steps)
        except ValueError as exc:
            if not str(exc).startswith("invalid_decision:"):
                raise
            trace.append(
                {
                    "step": step,
                    "error": str(exc),
                    "decision_attempts": agent.decision_attempts,
                }
            )
            _close_open_tasks(evidence_tasks, "invalid_decision")
            return finish("invalid_decision", error=str(exc))

        trace.append(
            {
                "step": step,
                "decision": decision,
                "decision_attempts": agent.decision_attempts,
            }
        )

        if decision["type"] == "answer" or decision.get("tool") == "finish_evidence_plan":
            if decision.get("tool") == "finish_evidence_plan":
                observation = (
                    agent.argument_error
                    if agent.argument_error is not None
                    else toolbox.execute("finish_evidence_plan", {})
                )
                memory.add(decision, observation)
                trace[-1]["observation"] = observation
            registered_ids = {str(t.get("gap_id")) for t in evidence_tasks}
            unfinished_gaps = [
                g
                for g in (item.get("gaps") or [])
                if g.get("registerable", True)
                and str(g.get("gap_id") or "") not in registered_ids
                and str(g.get("gap_id") or "") not in agent.skipped_gap_ids()
            ]
            reason = str(decision.get("reason") or "")
            if reason == "frame_budget_exhausted":
                return finish("frame_budget_exhausted")
            forced_stop = decision.get("type") == "answer" and reason == "last_step"
            if forced_stop and unfinished_gaps:
                return finish("budget_exhausted")
            if perception:
                return finish("observed")
            if media_only:
                return finish("sampled")
            return finish("planned")

        try:
            observation = (
                agent.argument_error
                if agent.argument_error is not None
                else toolbox.execute(decision["tool"], decision.get("arguments", {}))
            )
        except FrameBudgetExhausted as exc:
            observation = {"error": "FrameBudgetExhausted", "message": str(exc)}
            memory.add(decision, observation)
            trace[-1]["observation"] = observation
            return finish("frame_budget_exhausted", error=str(exc))
        except MediaError as exc:
            observation = {"error": "MediaError", "message": str(exc)}
            memory.add(decision, observation)
            trace[-1]["observation"] = observation
            _close_open_tasks(evidence_tasks, "media_error")
            return finish("media_error", error=str(exc))
        except Exception as exc:  # noqa: BLE001
            observation = {"error": type(exc).__name__, "message": str(exc)}
            memory.add(decision, observation)
            trace[-1]["observation"] = observation
            _close_open_tasks(evidence_tasks, "tool_error")
            return finish("invalid_decision", error=str(exc))

        memory.add(decision, observation)
        trace[-1]["observation"] = observation

        tool = decision["tool"]
        if tool == "probe_video_media":
            agent.mark_probed()
        elif tool == "list_story_gaps":
            agent.mark_listed()
        elif tool == "register_evidence_task":
            registered = (observation or {}).get("registered")
            if isinstance(registered, dict):
                if registered.get("status") == "verified":
                    registered = dict(registered, status="pending")
                evidence_tasks.append(registered)
                agent.mark_registered(str(registered.get("gap_id") or ""))
        elif tool == "sample_next_evidence":
            gap_id = str((decision.get("arguments") or {}).get("gap_id") or "")
            frames = list((observation or {}).get("frames") or [])
            if gap_id and frames:
                _attach_frames_to_task(evidence_tasks, gap_id, frames)
                memory.mark_sampled(gap_id)
            elif gap_id and (observation or {}).get("status") == "sampled":
                for task in evidence_tasks:
                    if task.get("gap_id") == gap_id and task.get("status") == "pending":
                        task["status"] = "sampled"
                        memory.mark_sampled(gap_id)
            agent.mark_sample_result(gap_id, observation or {})
        elif tool == "inspect_visual_evidence":
            gap_id = str((decision.get("arguments") or {}).get("gap_id") or "")
            evidence = (observation or {}).get("visual_evidence") or {}
            status = (observation or {}).get("status")
            for task in evidence_tasks:
                if task.get("gap_id") != gap_id:
                    continue
                task["visual_evidence"] = evidence
                if status == "observed":
                    task["status"] = "observed"
                    memory.mark_observed(gap_id, evidence)
                else:
                    task["status"] = "unresolved"
                    task["unresolved_reason"] = evidence.get("message") or "vision_failed"
                    memory.mark_unresolved(gap_id, task["unresolved_reason"])
                break
            agent.mark_observe_result(gap_id, observation or {})
        elif tool in (
            "coarse_search_interval",
            "inspect_story_window",
            "read_scoreboard_window",
            "scan_reaction_window",
        ):
            gap_id = str((decision.get("arguments") or {}).get("gap_id") or "")
            frames = list((observation or {}).get("frames") or [])
            if gap_id and frames:
                _attach_frames_to_task(evidence_tasks, gap_id, frames)
                memory.mark_sampled(gap_id)

    return finish("budget_exhausted")


def run_story_json(
    story_path: str,
    *,
    video_path: Optional[str] = None,
    duration_sec: Optional[float] = None,
    max_steps: int = 32,
    dry_run: bool = True,
    media_only: bool = False,
    perception: bool = False,
    frame_budget: int = 24,
    frame_dir: Optional[str] = None,
    manifest_path: Optional[str] = None,
    max_coarse_per_gap: int = 1,
    focus_gap_ids: Optional[Sequence[str]] = None,
    force_mock_vlm: bool = False,
    france_focus: bool = False,
    use_llm_planner: Optional[bool] = None,
) -> Dict[str, Any]:
    story = load_t01_story(story_path)
    focus = list(focus_gap_ids) if focus_gap_ids is not None else None
    if france_focus:
        focus = list(FRANCE_PERCEPTION_FOCUS)
    result = solve(
        story,
        video_path=video_path,
        duration_sec=duration_sec,
        max_steps=max_steps,
        dry_run=dry_run,
        media_only=media_only,
        perception=perception,
        frame_budget=frame_budget,
        frame_dir=frame_dir,
        manifest_path=manifest_path,
        max_coarse_per_gap=max_coarse_per_gap,
        focus_gap_ids=focus,
        force_mock_vlm=force_mock_vlm,
        use_llm_planner=use_llm_planner,
    )
    result["story_file"] = str(story_path)
    return result
