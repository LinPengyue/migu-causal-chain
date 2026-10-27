"""Agent 决策循环：Video-RSI Initial Harness 形态；Phase 1.5 规则策略，不调 LLM。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from story_video_agent.tools import ToolArgumentError, ToolBox


class Agent:
    def __init__(self, item: Dict[str, Any], tools: ToolBox) -> None:
        self.item = item
        self.tools = tools
        self.decision_attempts: List[Dict[str, Any]] = []
        self.argument_error: Optional[Dict[str, Any]] = None
        self._registered: Set[str] = set()
        self._listed = False
        self._skip: Set[str] = set()

    def decide(self, memory: Any, step: int, max_steps: int) -> Dict[str, Any]:
        self.decision_attempts = []
        self.argument_error = None
        remaining = max_steps - step
        for attempt in range(2):
            raw = self._propose(remaining)
            record: Dict[str, Any] = {
                "attempt": attempt,
                "raw_response": raw,
                "parse_mode": "rule_policy",
            }
            self.decision_attempts.append(record)
            try:
                decision = self._normalize_decision(raw, remaining)
                record["proposed_decision"] = decision
                if decision["type"] == "tool":
                    decision = dict(
                        decision,
                        arguments=self.tools.normalize_arguments(
                            decision["tool"], decision.get("arguments", {})
                        ),
                    )
                record.update(status="accepted", decision=decision)
                return decision
            except (ValueError, TypeError) as exc:
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
                            "answer": "finish_evidence_plan",
                            "reason": f"repair_exhausted:{exc}",
                        }
                    raise ValueError("invalid_decision: " + str(exc)) from exc
                # 跳过导致参数失败的 gap，下一轮换任务
                gap_id = None
                if isinstance(raw, dict) and raw.get("tool") == "register_evidence_task":
                    gap_id = str((raw.get("arguments") or {}).get("gap_id") or "")
                if gap_id:
                    self._skip.add(gap_id)
                continue
        raise ValueError("invalid_decision: exhausted decision attempts")

    def _registerable_gaps(self) -> List[Dict[str, Any]]:
        rows = []
        for gap in self.item.get("gaps") or []:
            gap_id = str(gap.get("gap_id") or "")
            if not gap_id or gap_id in self._registered or gap_id in self._skip:
                continue
            if not gap.get("registerable", True):
                continue
            rows.append(gap)
        return rows

    def _propose(self, remaining: int) -> Dict[str, Any]:
        if remaining <= 1:
            return {
                "type": "answer",
                "answer": "finish_evidence_plan",
                "reason": "last_step",
            }
        if not self._listed:
            return {"type": "tool", "tool": "list_story_gaps", "arguments": {}}

        pending = self._registerable_gaps()
        if not pending:
            return {"type": "tool", "tool": "finish_evidence_plan", "arguments": {}}

        gap = pending[0]
        return {
            "type": "tool",
            "tool": "register_evidence_task",
            "arguments": {"gap_id": str(gap["gap_id"])},
        }

    def _normalize_decision(self, raw: Dict[str, Any], remaining: int) -> Dict[str, Any]:
        if not isinstance(raw, dict) or "type" not in raw:
            raise ValueError("decision must be an object with type")
        if remaining <= 1 and raw.get("type") != "answer":
            raise ValueError("last step requires a terminal answer; no tool action will execute")
        if raw["type"] == "answer":
            return {
                "type": "answer",
                "answer": str(raw.get("answer") or "finish_evidence_plan"),
                "reason": str(raw.get("reason") or ""),
            }
        if raw["type"] != "tool":
            raise ValueError("type must be tool or answer")
        tool = raw.get("tool")
        if not tool:
            raise ValueError("tool decision requires tool name")
        return {
            "type": "tool",
            "tool": str(tool),
            "arguments": dict(raw.get("arguments") or {}),
        }

    def mark_listed(self) -> None:
        self._listed = True

    def mark_registered(self, gap_id: str) -> None:
        self._registered.add(gap_id)

    def skipped_gap_ids(self) -> Set[str]:
        return set(self._skip)
