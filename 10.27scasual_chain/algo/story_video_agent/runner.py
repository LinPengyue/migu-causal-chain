"""Story Video Agent 求解循环：Phase 1.5，无 Editor/RSI/Gate。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from story_video_agent.agent import Agent
from story_video_agent.memory import Memory
from story_video_agent.state import build_agent_item, load_t01_story, validate_plan_payload
from story_video_agent.tools import ToolBox

ALGORITHM_ID = "t01_story_video_agent_dryrun"
SCHEMA_VERSION = "story-video-agent-plan-1.5"


def _close_open_tasks(tasks: List[Dict[str, Any]], reason: str) -> None:
    for task in tasks:
        if task.get("status") in ("pending", "running"):
            task["status"] = "unresolved"
            task["unresolved_reason"] = reason


def _verification_complete(tasks: List[Dict[str, Any]], *, dry_run: bool) -> bool:
    if dry_run:
        return False
    if not tasks:
        return False
    return all(task.get("status") == "verified" for task in tasks)


def solve(
    story: Dict[str, Any],
    *,
    video_path: Optional[str] = None,
    duration_sec: Optional[float] = None,
    max_steps: int = 12,
    dry_run: bool = True,
) -> Dict[str, Any]:
    item = build_agent_item(story, video_path=video_path, duration_sec=duration_sec)
    memory = Memory()
    toolbox = ToolBox(item, dry_run=dry_run)
    agent = Agent(item, toolbox)
    trace: List[Dict[str, Any]] = []
    evidence_tasks: List[Dict[str, Any]] = []

    def finish(status: str, **extra: Any) -> Dict[str, Any]:
        if status == "budget_exhausted":
            _close_open_tasks(evidence_tasks, "budget_exhausted")
        attempts = [a for t in trace for a in t.get("decision_attempts", [])]
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
        }
        payload = {
            "schema_version": SCHEMA_VERSION,
            "algorithm": ALGORITHM_ID,
            "status": status,
            "match_id": item.get("match_id") or "",
            "video_name": item.get("video_name") or "",
            "video_path": item.get("video_path") or "",
            "story_tier": item.get("story_tier"),
            "has_story": item.get("has_story"),
            "is_candidate": item.get("is_candidate"),
            "story_label_zh": item.get("story_label_zh"),
            "dry_run": dry_run,
            "duration_known": bool(item.get("duration_known")),
            "gaps": item.get("gaps") or [],
            "evidence_tasks": evidence_tasks,
            "verification_complete": _verification_complete(evidence_tasks, dry_run=dry_run),
            "trace": trace,
            "memory": memory.items,
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
            # 末步被迫收工且仍有未注册缺口 → 预算耗尽；否则规划完成（pending 不得标 verified）
            registered_ids = {str(t.get("gap_id")) for t in evidence_tasks}
            unfinished_gaps = [
                g
                for g in (item.get("gaps") or [])
                if g.get("registerable", True)
                and str(g.get("gap_id") or "") not in registered_ids
                and str(g.get("gap_id") or "") not in agent.skipped_gap_ids()
            ]
            forced_stop = decision.get("type") == "answer" and decision.get("reason") == "last_step"
            if forced_stop and unfinished_gaps:
                return finish("budget_exhausted")
            return finish("planned")

        try:
            observation = (
                agent.argument_error
                if agent.argument_error is not None
                else toolbox.execute(decision["tool"], decision.get("arguments", {}))
            )
        except Exception as exc:  # noqa: BLE001
            observation = {"error": type(exc).__name__, "message": str(exc)}
            memory.add(decision, observation)
            trace[-1]["observation"] = observation
            _close_open_tasks(evidence_tasks, "tool_error")
            return finish("invalid_decision", error=str(exc))

        memory.add(decision, observation)
        trace[-1]["observation"] = observation

        if decision["tool"] == "list_story_gaps":
            agent.mark_listed()
        elif decision["tool"] == "register_evidence_task":
            registered = (observation or {}).get("registered")
            if isinstance(registered, dict):
                if registered.get("status") == "verified":
                    registered = dict(registered, status="pending")
                evidence_tasks.append(registered)
                agent.mark_registered(str(registered.get("gap_id") or ""))

    return finish("budget_exhausted")


def run_story_json(
    story_path: str,
    *,
    video_path: Optional[str] = None,
    duration_sec: Optional[float] = None,
    max_steps: int = 12,
    dry_run: bool = True,
) -> Dict[str, Any]:
    story = load_t01_story(story_path)
    result = solve(
        story,
        video_path=video_path,
        duration_sec=duration_sec,
        max_steps=max_steps,
        dry_run=dry_run,
    )
    result["story_file"] = str(story_path)
    return result
