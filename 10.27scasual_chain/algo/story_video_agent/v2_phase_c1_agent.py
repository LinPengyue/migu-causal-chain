"""Phase C-1 DeepSeek planner for goal localization tasks."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from story_video_agent.api_provider import ApiProvider
from story_video_agent.tools import ToolArgumentError
from story_video_agent.v2_phase_c1_toolbox import V2PhaseC1Toolbox

_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)

PLANNER_SYSTEM = """You localize football GOAL ACTIONS for open evidence tasks.
You already may have a T01 story_candidate from scoreboard transitions — that is NOT proof
of localized live goal actions.

Return one JSON object:
- Tool: {"type":"tool","tool":"<name>","arguments":{"start":..,"end":..,"task_id":"..."}}
- Finish: {"type":"answer","answer":"finish_localization","reason":"...","task_updates":[]}

Rules:
1. Prefer hierarchy: coarse_search → refine_window → dense_action_inspect → verify_live_replay.
2. Never invent timestamps; use candidate_window / prior observations.
3. Scoreboard-only is not action_localized.
4. Keep windows shrinking; avoid repeating identical spans.
5. One tool call per turn; include task_id.
6. Compact JSON only.
"""


class V2PhaseC1Agent:
    def __init__(
        self,
        *,
        duration: float,
        tools: V2PhaseC1Toolbox,
        api: ApiProvider,
        use_llm_planner: bool = True,
    ) -> None:
        self.duration = float(duration)
        self.tools = tools
        self.api = api
        self.use_llm_planner = bool(use_llm_planner)
        self.decision_attempts: List[Dict[str, Any]] = []
        self.argument_error: Optional[Dict[str, Any]] = None
        self.planner_mode_log: List[str] = []

    def decide(self, memory_facts: Dict[str, Any], step: int, max_steps: int) -> Dict[str, Any]:
        self.decision_attempts = []
        self.argument_error = None
        remaining = max_steps - step
        rule = self._rule_policy(memory_facts, remaining)
        for attempt in range(2):
            raw = rule
            parse_mode = "rule_policy"
            if self.use_llm_planner:
                try:
                    llm = self._propose_llm(memory_facts, remaining, step=step, max_steps=max_steps)
                    if isinstance(llm, dict) and "type" in llm:
                        raw = llm
                        parse_mode = "llm_api"
                        self.planner_mode_log.append("llm")
                    else:
                        self.planner_mode_log.append("llm_fallback_rule")
                except Exception:  # noqa: BLE001
                    self.planner_mode_log.append("llm_error_fallback_rule")
                    raw = rule
            else:
                self.planner_mode_log.append("rule")
            record: Dict[str, Any] = {
                "attempt": attempt,
                "raw_response": raw,
                "parse_mode": parse_mode,
                "rule_fallback": rule,
            }
            self.decision_attempts.append(record)
            try:
                decision = self._normalize(raw, remaining)
                if decision["type"] == "tool":
                    decision = dict(
                        decision,
                        arguments=self.tools.normalize_arguments(
                            decision["tool"], decision.get("arguments") or {}
                        ),
                    )
                record.update(status="accepted", decision=decision)
                return decision
            except (ValueError, TypeError, ToolArgumentError) as exc:
                record.update(status="rejected", error=str(exc))
                if remaining <= 1 and "last step" in str(exc):
                    terminal = {
                        "type": "answer",
                        "answer": "finish_localization",
                        "reason": "last_step_fallback",
                    }
                    record.update(status="accepted_terminal_fallback", decision=terminal)
                    return terminal
                if attempt:
                    if isinstance(exc, ToolArgumentError):
                        self.argument_error = {
                            "error": "ToolArgumentError",
                            "message": str(exc),
                        }
                        return {
                            "type": "answer",
                            "answer": "finish_localization",
                            "reason": f"repair_exhausted:{exc}",
                        }
                    raise ValueError("invalid_decision: " + str(exc)) from exc
                continue
        raise ValueError("invalid_decision: exhausted")

    def _rule_policy(self, facts: Dict[str, Any], remaining: int) -> Dict[str, Any]:
        if remaining <= 1:
            return {
                "type": "answer",
                "answer": "finish_localization",
                "reason": "budget_or_last_step",
            }
        open_tasks = facts.get("open_tasks") or []
        if not open_tasks:
            return {
                "type": "answer",
                "answer": "finish_localization",
                "reason": "no_open_tasks",
            }
        # Prefer goal tasks over final verify
        goal_tasks = [t for t in open_tasks if "goal" in str(t.get("task_id"))]
        task = (goal_tasks or open_tasks)[0]
        tid = task["task_id"]
        grade = task.get("localization_grade")
        cand = task.get("refined_window") or task.get("candidate_window")
        if not cand:
            # no prior window — ask for a coarse band near duration mid as last resort
            mid = self.duration * 0.4
            return {
                "type": "tool",
                "tool": "coarse_search",
                "arguments": {
                    "start": round(max(0.0, mid - 45), 2),
                    "end": round(min(self.duration, mid + 45), 2),
                    "task_id": tid,
                },
            }
        start, end = float(cand["start"]), float(cand["end"])
        start = max(0.0, start)
        end = min(self.duration, end)
        span = end - start
        if grade in (None, "unresolved", "scoreboard_only") and span > 20:
            if span > 120.0:
                end = start + 120.0
            if end - start <= 8:
                end = min(self.duration, start + 20)
            return {
                "type": "tool",
                "tool": "coarse_search",
                "arguments": {
                    "start": round(start, 2),
                    "end": round(end, 2),
                    "task_id": tid,
                },
            }
        if grade in ("scoreboard_only", "goal_candidate", None) and span > 8:
            mid = 0.5 * (start + end)
            s, e = max(0.0, mid - 8), min(self.duration, mid + 8)
            return {
                "type": "tool",
                "tool": "refine_window",
                "arguments": {"start": round(s, 2), "end": round(e, 2), "task_id": tid},
            }
        mid = 0.5 * (start + end)
        s, e = max(0.0, mid - 4), min(self.duration, mid + 4)
        if e - s < 1.0:
            e = min(self.duration, s + 2.0)
        return {
            "type": "tool",
            "tool": "dense_action_inspect",
            "arguments": {"start": round(s, 2), "end": round(e, 2), "task_id": tid},
        }

    def _propose_llm(
        self, facts: Dict[str, Any], remaining: int, *, step: int, max_steps: int
    ) -> Dict[str, Any]:
        payload = {
            "duration_sec": self.duration,
            "tools": self.tools.descriptions(),
            "memory": facts,
            "step": step,
            "remaining_steps": remaining,
            "max_steps": max_steps,
            "frame_budget_remaining": self.tools.store.budget.remaining,
        }
        messages = [
            {"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        mock = json.dumps(self._rule_policy(facts, remaining), ensure_ascii=False)
        resp = self.api.chat(role="planner", messages=messages, temperature=0.1, mock_content=mock)
        return self._parse(str(resp.get("content") or ""))

    def _parse(self, text: str) -> Dict[str, Any]:
        text = (text or "").strip()
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        m = _JSON_OBJ.search(text)
        if not m:
            raise ValueError("not JSON")
        obj = json.loads(m.group(0))
        if not isinstance(obj, dict):
            raise ValueError("not object")
        return obj

    def _normalize(self, raw: Dict[str, Any], remaining: int) -> Dict[str, Any]:
        typ = raw.get("type")
        if typ == "answer":
            return {
                "type": "answer",
                "answer": str(raw.get("answer") or "finish_localization"),
                "reason": str(raw.get("reason") or ""),
                "task_updates": raw.get("task_updates") or [],
            }
        if typ == "tool":
            tool = str(raw.get("tool") or "")
            if tool not in self.tools.descriptions():
                raise ToolArgumentError(f"unknown tool {tool}")
            if remaining <= 1:
                raise ValueError("last step requires answer, not tool")
            return {
                "type": "tool",
                "tool": tool,
                "arguments": dict(raw.get("arguments") or {}),
            }
        raise ValueError("type must be tool or answer")
