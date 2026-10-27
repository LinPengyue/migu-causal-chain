"""Agent：规则策略 + 可选远程 LLM Planner（失败降级规则）。"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Set

from story_video_agent.api_provider import ApiProvider
from story_video_agent.frames import gap_priority, prioritize_gap_ids
from story_video_agent.tools import ToolArgumentError, ToolBox

_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)

PLANNER_SYSTEM = (
    "You are the Story Video Agent planner for football comeback evidence. "
    "Choose exactly one next action as JSON: "
    '{"type":"tool","tool":"<name>","arguments":{...}} '
    'or {"type":"answer","answer":"finish_evidence_plan","reason":"..."}. '
    "Use only listed tools. Never invent media timestamps; tools bind times. "
    "VLM observations are not fact verification. Prefer high-priority climax gaps."
)


class Agent:
    def __init__(
        self,
        item: Dict[str, Any],
        tools: ToolBox,
        *,
        api: Optional[ApiProvider] = None,
        use_llm_planner: bool = False,
    ) -> None:
        self.item = item
        self.tools = tools
        self.api = api
        self.use_llm_planner = bool(use_llm_planner) and api is not None
        self.decision_attempts: List[Dict[str, Any]] = []
        self.argument_error: Optional[Dict[str, Any]] = None
        self._registered: Set[str] = set()
        self._listed = False
        self._probed = False
        self._skip: Set[str] = set()
        self._sample_queue: List[str] = []
        self._sampled_done: Set[str] = set()
        self._observe_queue: List[str] = []
        self._observed_done: Set[str] = set()
        self._task_frames: Dict[str, List[str]] = {}
        self.planner_mode_log: List[str] = []

    def decide(self, memory: Any, step: int, max_steps: int) -> Dict[str, Any]:
        self.decision_attempts = []
        self.argument_error = None
        remaining = max_steps - step
        for attempt in range(2):
            rule_raw = self._propose_rule(remaining)
            raw = rule_raw
            parse_mode = "rule_policy"
            if self.use_llm_planner and remaining > 1 and self.api is not None:
                try:
                    llm_raw = self._propose_llm(memory, remaining, fallback=rule_raw)
                    if isinstance(llm_raw, dict) and "type" in llm_raw:
                        raw = llm_raw
                        parse_mode = "llm_api"
                        self.planner_mode_log.append("llm")
                    else:
                        self.planner_mode_log.append("llm_fallback_rule")
                except Exception:  # noqa: BLE001
                    self.planner_mode_log.append("llm_error_fallback_rule")
                    raw = rule_raw
            else:
                self.planner_mode_log.append("rule")

            record: Dict[str, Any] = {
                "attempt": attempt,
                "raw_response": raw,
                "parse_mode": parse_mode,
                "rule_fallback": rule_raw,
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
                    if tool in (
                        "register_evidence_task",
                        "sample_next_evidence",
                        "inspect_visual_evidence",
                    ):
                        gap_id = str((raw.get("arguments") or {}).get("gap_id") or "")
                if gap_id:
                    self._skip.add(gap_id)
                    self._sample_queue = [g for g in self._sample_queue if g != gap_id]
                    self._observe_queue = [g for g in self._observe_queue if g != gap_id]
                    self._sampled_done.add(gap_id)
                    self._observed_done.add(gap_id)
                continue
        raise ValueError("invalid_decision: exhausted decision attempts")

    def _propose_llm(
        self, memory: Any, remaining: int, *, fallback: Dict[str, Any]
    ) -> Dict[str, Any]:
        assert self.api is not None
        tools = self.tools.descriptions()
        stages = getattr(memory, "gap_stages", {}) or {}
        evidence_n = len(getattr(memory, "visual_evidence", []) or [])
        user = {
            "remaining_steps": remaining,
            "match_id": self.item.get("match_id"),
            "story_tier": self.item.get("story_tier"),
            "focus_gap_ids": sorted(self.tools.focus_gap_ids) if self.tools.focus_gap_ids else [],
            "gaps": [
                {
                    "gap_id": g.get("gap_id"),
                    "kind": g.get("kind"),
                    "priority": gap_priority(str(g.get("gap_id"))),
                    "anchor_status": g.get("anchor_status"),
                    "tool_hint": g.get("tool_hint"),
                }
                for g in (self.item.get("gaps") or [])
            ],
            "registered": sorted(self._registered),
            "sample_queue": list(self._sample_queue),
            "observe_queue": list(self._observe_queue),
            "task_frames": {k: v[:8] for k, v in self._task_frames.items()},
            "memory_stages": stages,
            "visual_evidence_count": evidence_n,
            "tools": tools,
            "hint_rule_decision": fallback,
        }
        result = self.api.plan_decision(
            system_prompt=PLANNER_SYSTEM,
            user_prompt=json.dumps(user, ensure_ascii=False),
            mock_decision=fallback,
        )
        content = str(result.get("content") or "")
        try:
            obj = json.loads(content)
        except json.JSONDecodeError:
            m = _JSON_OBJ.search(content)
            if not m:
                return fallback
            obj = json.loads(m.group(0))
        if not isinstance(obj, dict) or "type" not in obj:
            return fallback
        return obj

    def _registerable_gaps(self) -> List[Dict[str, Any]]:
        rows = []
        for gap in self.item.get("gaps") or []:
            gap_id = str(gap.get("gap_id") or "")
            if not gap_id or gap_id in self._registered or gap_id in self._skip:
                continue
            if not gap.get("registerable", True):
                continue
            if self.tools.focus_gap_ids and gap_id not in self.tools.focus_gap_ids:
                continue
            rows.append(gap)
        rows.sort(key=lambda g: (gap_priority(str(g.get("gap_id"))), str(g.get("gap_id"))))
        return rows

    def _propose_rule(self, remaining: int) -> Dict[str, Any]:
        if remaining <= 1:
            return {
                "type": "answer",
                "answer": "finish_evidence_plan",
                "reason": "last_step",
            }

        needs_media = self.tools.media_only or self.tools.perception
        if needs_media and not self._probed:
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

        if needs_media:
            while self._sample_queue:
                gap_id = self._sample_queue[0]
                if gap_id in self._sampled_done or gap_id in self._skip:
                    self._sample_queue.pop(0)
                    continue
                store = self.tools.frame_store
                if store is not None and store.budget.remaining_for(gap_id) <= 0:
                    self._sampled_done.add(gap_id)
                    self._sample_queue.pop(0)
                    if store.budget.remaining <= 0:
                        break
                    continue
                return {
                    "type": "tool",
                    "tool": "sample_next_evidence",
                    "arguments": {"gap_id": gap_id},
                }

            if self.tools.perception:
                while self._observe_queue:
                    gap_id = self._observe_queue[0]
                    if gap_id in self._observed_done or gap_id in self._skip:
                        self._observe_queue.pop(0)
                        continue
                    frames = self._task_frames.get(gap_id) or []
                    if not frames:
                        self._observed_done.add(gap_id)
                        self._observe_queue.pop(0)
                        continue
                    return {
                        "type": "tool",
                        "tool": "inspect_visual_evidence",
                        "arguments": {"gap_id": gap_id, "frame_ids": frames},
                    }

            if needs_media and self.tools.frame_store is not None:
                if self.tools.frame_store.budget.remaining <= 0 and self._sample_queue:
                    return {
                        "type": "answer",
                        "answer": "finish_evidence_plan",
                        "reason": "frame_budget_exhausted",
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
        needs_media = self.tools.media_only or self.tools.perception
        if needs_media and gap_id not in self._sample_queue:
            self._sample_queue.append(gap_id)
            self._sample_queue = prioritize_gap_ids(self._sample_queue)

    def _finish_sample(self, gap_id: str) -> None:
        self._sampled_done.add(gap_id)
        if self._sample_queue and self._sample_queue[0] == gap_id:
            self._sample_queue.pop(0)
        if self.tools.perception and gap_id not in self._observe_queue:
            if self._task_frames.get(gap_id):
                self._observe_queue.append(gap_id)

    def mark_sample_result(self, gap_id: str, observation: Dict[str, Any]) -> None:
        frames = observation.get("frames") or []
        ids = [str(f.get("frame_id")) for f in frames if f.get("frame_id")]
        if ids:
            self._task_frames.setdefault(gap_id, []).extend(ids)
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
        self._finish_sample(gap_id)

    def mark_observe_result(self, gap_id: str, observation: Dict[str, Any]) -> None:
        self._observed_done.add(gap_id)
        if self._observe_queue and self._observe_queue[0] == gap_id:
            self._observe_queue.pop(0)

    def skipped_gap_ids(self) -> Set[str]:
        return set(self._skip)
