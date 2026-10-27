"""Story Video Agent 求解循环：对齐 Video-RSI main.solve，不含 Editor/RSI/Gate。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from story_video_agent.agent import Agent
from story_video_agent.memory import Memory
from story_video_agent.state import build_agent_item, load_t01_story, validate_plan_payload
from story_video_agent.tools import ToolBox

ALGORITHM_ID = "t01_story_video_agent_dryrun"
SCHEMA_VERSION = "story-video-agent-plan-1"


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
            "gaps": item.get("gaps") or [],
            "evidence_tasks": evidence_tasks,
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
            return finish("planned")

        try:
            observation = (
                agent.argument_error
                if agent.argument_error is not None
                else toolbox.execute(decision["tool"], decision.get("arguments", {}))
            )
        except Exception as exc:  # noqa: BLE001 — harness records tool failures
            observation = {"error": type(exc).__name__, "message": str(exc)}
            memory.add(decision, observation)
            trace[-1]["observation"] = observation
            return finish("invalid_decision", error=str(exc))

        memory.add(decision, observation)
        trace[-1]["observation"] = observation

        if decision["tool"] == "list_story_gaps":
            agent.mark_listed()
        elif decision["tool"] == "register_evidence_task":
            registered = (observation or {}).get("registered")
            if isinstance(registered, dict):
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
