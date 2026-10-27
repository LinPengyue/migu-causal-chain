"""Agent 决策循环：Video-RSI Initial Harness 形态；规则策略，不调 LLM。"""

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
        self._probed = False
        self._skip: Set[str] = set()
        self._sample_queue: List[str] = []
        self._sampled_done: Set[str] = set()

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
                gap_id = None
                if isinstance(raw, dict):
                    tool = raw.get("tool")
                    if tool in ("register_evidence_task", "sample_next_evidence"):
                        gap_id = str((raw.get("arguments") or {}).get("gap_id") or "")
                if gap_id:
                    self._skip.add(gap_id)
                    if gap_id in self._sample_queue:
                        self._sample_queue = [g for g in self._sample_queue if g != gap_id]
                    self._sampled_done.add(gap_id)
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

        if self.tools.media_only and not self._probed:
            return {"type": "tool", "tool": "probe_video_media", "arguments": {}}

        if not self._listed:
            return {"type": "tool", "tool": "list_story_gaps", "arguments": {}}

        pending = self._registerable_gaps()
        if pending:
            gap = pending[0]
            return {
                "type": "tool",
                "tool": "register_evidence_task",
                "arguments": {"gap_id": str(gap["gap_id"])},
            }

        if self.tools.media_only:
            while self._sample_queue:
                gap_id = self._sample_queue[0]
                if gap_id in self._sampled_done or gap_id in self._skip:
                    self._sample_queue.pop(0)
                    continue
                store = self.tools.frame_store
                if store is not None and store.budget.remaining <= 0:
                    return {
                        "type": "answer",
                        "answer": "finish_evidence_plan",
                        "reason": "frame_budget_exhausted",
                    }
                return {
                    "type": "tool",
                    "tool": "sample_next_evidence",
                    "arguments": {"gap_id": gap_id},
                }

        return {"type": "tool", "tool": "finish_evidence_plan", "arguments": {}}

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

    def mark_probed(self) -> None:
        self._probed = True

    def mark_registered(self, gap_id: str) -> None:
        self._registered.add(gap_id)
        if self.tools.media_only and gap_id not in self._sample_queue:
            self._sample_queue.append(gap_id)

    def _finish_sample(self, gap_id: str) -> None:
        self._sampled_done.add(gap_id)
        if self._sample_queue and self._sample_queue[0] == gap_id:
            self._sample_queue.pop(0)

    def mark_sample_result(self, gap_id: str, observation: Dict[str, Any]) -> None:
        if observation.get("stopped") or observation.get("reason") in (
            "gap_coarse_quota",
            "no_more_intervals",
        ):
            self._finish_sample(gap_id)
            return
        gap = None
        for row in self.item.get("gaps") or []:
            if str(row.get("gap_id")) == gap_id:
                gap = row
                break
        seed_n = len((gap or {}).get("seed_windows") or [])
        seed_done = self.tools._gap_seed_cursor.get(gap_id, 0)
        if seed_done < seed_n:
            return
        # 有 seed：只跟 seed，不扫完全部 search_intervals；无 seed：本步已做一层 coarse
        self._finish_sample(gap_id)

    def skipped_gap_ids(self) -> Set[str]:
        return set(self._skip)
