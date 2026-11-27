"""V2 Phase A DeepSeek Story Planner (Video-RSI style decide loop)."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from story_video_agent.api_provider import ApiProvider
from story_video_agent.tools import ToolArgumentError
from story_video_agent.v2_rsi_toolbox import V2RSIToolbox

_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)

PLANNER_SYSTEM = """You are the Story Video Agent V2 planner for football T01 comeback evidence.
You do NOT answer multiple-choice questions. You gather video evidence for a comeback story.

Rules:
- Return exactly one JSON object per turn.
- Tool action: {"type":"tool","tool":"<name>","arguments":{...}}
- Finish: {"type":"answer","answer":"finish_evidence","reason":"...","hypothesis":{...}}
- Never invent media timestamps; only use times from prior tool observations or proposed windows.
- Do not treat chronological frame order as proven causality.
- Prefer: overview → scan_interval → inspect_interval / read_scoreboard_window.
- Avoid repeating nearly identical windows already in checked_intervals.
- If budget/remaining_steps is low, finish with unresolved notes rather than guessing goals.
- Observations from Qwen are NOT fact verification.
"""


class V2PhaseAAgent:
    def __init__(
        self,
        *,
        duration: float,
        tools: V2RSIToolbox,
        api: ApiProvider,
        use_llm_planner: bool = True,
        task_brief: str = "",
    ) -> None:
        self.duration = float(duration)
        self.tools = tools
        self.api = api
        self.use_llm_planner = bool(use_llm_planner)
        self.task_brief = task_brief or (
            "Find visible scoreboard scores and any live goal/celebration cues "
            "relevant to a possible comeback (T01). Mark uncertainties."
        )
        self.decision_attempts: List[Dict[str, Any]] = []
        self.argument_error: Optional[Dict[str, Any]] = None
        self.planner_mode_log: List[str] = []

    def decide(self, memory: Any, step: int, max_steps: int) -> Dict[str, Any]:
        self.decision_attempts = []
        self.argument_error = None
        remaining = max_steps - step
        rule = self._rule_policy(memory, remaining)
        for attempt in range(2):
            raw = rule
            parse_mode = "rule_policy"
            if self.use_llm_planner and remaining > 1:
                try:
                    llm = self._propose_llm(memory, remaining, step=step, max_steps=max_steps)
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
                semantic = isinstance(exc, ToolArgumentError)
                record.update(
                    status="rejected",
                    error_kind="tool_arguments" if semantic else "response_format",
                    error=str(exc),
                )
                if attempt:
                    if semantic:
                        self.argument_error = {
                            "error": "ToolArgumentError",
                            "message": str(exc),
                            "stage": "pre_dispatch",
                            "repair_exhausted": True,
                        }
                        return {
                            "type": "answer",
                            "answer": "finish_evidence",
                            "reason": f"repair_exhausted:{exc}",
                        }
                    raise ValueError("invalid_decision: " + str(exc)) from exc
                continue
        raise ValueError("invalid_decision: exhausted")

    def _rule_policy(self, memory: Any, remaining: int) -> Dict[str, Any]:
        facts = memory.planner_facts() if hasattr(memory, "planner_facts") else {}
        n_obs = int(facts.get("n_observations") or 0)
        if remaining <= 1:
            return {
                "type": "answer",
                "answer": "finish_evidence",
                "reason": "budget_or_last_step",
                "hypothesis": {"story_type": "T01_comeback", "status": "unresolved_or_partial"},
            }
        if n_obs == 0:
            return {"type": "tool", "tool": "overview", "arguments": {}}
        # Prefer unscanned mid windows for short clips
        checked = facts.get("checked_intervals") or []
        covered = sum(float(i["end"]) - float(i["start"]) for i in checked) if checked else 0.0
        if covered < self.duration * 0.5 and self.duration > 20:
            # second half scan
            start = max(0.0, self.duration * 0.35)
            end = min(self.duration, start + min(20.0, self.duration / 2))
            if end - start > 8:
                return {
                    "type": "tool",
                    "tool": "scan_interval",
                    "arguments": {"start": round(start, 2), "end": round(end, 2)},
                }
        # local inspect near last observation end
        if checked:
            last = checked[-1]
            mid = 0.5 * (float(last["start"]) + float(last["end"]))
            s = max(0.0, mid - 4.0)
            e = min(self.duration, mid + 4.0)
            if e - s >= 1.0:
                return {
                    "type": "tool",
                    "tool": "inspect_interval",
                    "arguments": {"start": round(s, 2), "end": round(e, 2)},
                }
        return {
            "type": "answer",
            "answer": "finish_evidence",
            "reason": "rule_policy_complete",
            "hypothesis": {"story_type": "T01_comeback", "status": "partial"},
        }

    def _propose_llm(
        self, memory: Any, remaining: int, *, step: int, max_steps: int
    ) -> Dict[str, Any]:
        payload = {
            "task": self.task_brief,
            "duration_sec": self.duration,
            "tools": self.tools.descriptions(),
            "memory": memory.planner_facts(),
            "step": step,
            "remaining_steps": remaining,
            "max_steps": max_steps,
            "frame_budget_remaining": self.tools.store.budget.remaining,
        }
        messages = [
            {"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        mock = json.dumps(self._rule_policy(memory, remaining), ensure_ascii=False)
        resp = self.api.chat(role="planner", messages=messages, temperature=0.1, mock_content=mock)
        text = str(resp.get("content") or "")
        return self._parse_json_decision(text)

    def _parse_json_decision(self, text: str) -> Dict[str, Any]:
        text = (text or "").strip()
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        m = _JSON_OBJ.search(text)
        if not m:
            raise ValueError("planner response is not JSON")
        obj = json.loads(m.group(0))
        if not isinstance(obj, dict):
            raise ValueError("planner JSON is not an object")
        return obj

    def _normalize(self, raw: Dict[str, Any], remaining: int) -> Dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError("decision must be object")
        typ = raw.get("type")
        if typ == "answer":
            if remaining > 1 and not raw.get("reason"):
                raise ValueError("answer requires reason")
            return {
                "type": "answer",
                "answer": str(raw.get("answer") or "finish_evidence"),
                "reason": str(raw.get("reason") or ""),
                "hypothesis": raw.get("hypothesis") or {},
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
