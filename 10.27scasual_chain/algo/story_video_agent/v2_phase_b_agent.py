"""Phase B DeepSeek story discovery planner (hierarchical long-video search)."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from story_video_agent.api_provider import ApiProvider
from story_video_agent.tools import ToolArgumentError
from story_video_agent.v2_phase_b_toolbox import V2PhaseBToolbox

_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)

PLANNER_SYSTEM = """You are Story Video Agent V2 Phase B — football story discovery planner.
Target story TYPE to evaluate: T01 (comeback / reverse a deficit). You are NOT told whether
this match actually contains a comeback. Decide from VIDEO TOOL OBSERVATIONS only.

Return exactly one JSON object:
- Tool: {"type":"tool","tool":"<name>","arguments":{...}}
- Finish: {"type":"answer","answer":"<story_candidate|partial_story|no_comeback|unresolved>",
           "reason":"...","hypothesis":{...}}

Rules:
1. Never invent media timestamps; only propose windows or cite observed times.
2. Sparse overview/partition samples do NOT mean the interval was fully watched.
3. Prefer hierarchy: global_overview → partition_scan on untouched partitions →
   localize_event / read_scoreboard_window → verify_evidence.
4. Avoid re-scanning nearly identical windows already in search_history.
5. Do not equate time order with proven causality.
6. Qwen observations are not fact verification.
7. Finish with no_comeback ONLY if coverage is adequate AND scoreboard/result evidence
   consistently shows no deficit→equalizer→lead pattern; otherwise prefer unresolved
   or partial_story when evidence is incomplete.
8. Keep JSON compact. Do not narrate chain-of-thought in the JSON.
"""


class V2PhaseBAgent:
    def __init__(
        self,
        *,
        duration: float,
        tools: V2PhaseBToolbox,
        api: ApiProvider,
        use_llm_planner: bool = True,
        task_brief: str = "",
        planner_temperature: float = 0.1,
    ) -> None:
        self.duration = float(duration)
        self.tools = tools
        self.api = api
        self.use_llm_planner = bool(use_llm_planner)
        self.planner_temperature = float(planner_temperature)
        self.task_brief = task_brief or (
            "Determine whether a T01-style comeback story is supported by visible "
            "video evidence. Identify deficit / equalizer / go-ahead candidates if any. "
            "Leave unknowns as unresolved. Do not assume a comeback exists."
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
            # Last step: still allow LLM to emit a terminal answer (tools forbidden by normalize).
            if self.use_llm_planner:
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
                # Last-step tool proposals → synthesize terminal answer from evidence.
                if remaining <= 1 and "last step requires answer" in str(exc):
                    terminal = self._rule_policy(memory, remaining)
                    record.update(status="accepted_terminal_fallback", decision=terminal)
                    return terminal
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
                            "answer": "unresolved",
                            "reason": f"repair_exhausted:{exc}",
                            "hypothesis": {"discovery_status": "unresolved"},
                        }
                    raise ValueError("invalid_decision: " + str(exc)) from exc
                continue
        raise ValueError("invalid_decision: exhausted")

    def _rule_policy(self, memory: Any, remaining: int) -> Dict[str, Any]:
        facts = memory.planner_facts() if hasattr(memory, "planner_facts") else {}
        n_obs = int(facts.get("n_observations") or 0)
        if remaining <= 1:
            # Prefer evidence-backed terminal status over blank unresolved.
            blob = json.dumps(facts.get("evidence_items_deduped") or [], ensure_ascii=False).lower()
            notes = " ".join(
                str(o.get("notes_head") or "") for o in (facts.get("recent_observations") or [])
            ).lower()
            text = blob + " " + notes
            has_deficit = ("0 - 1" in text) or ("0-1" in text) or ("trailing" in text) or ("落后" in text)
            has_level = ("1 - 1" in text) or ("1-1" in text) or ("equaliz" in text) or ("扳平" in text)
            has_lead = ("2 - 1" in text) or ("2-1" in text) or ("comeback" in text) or ("反超" in text)
            if has_deficit and has_level and has_lead:
                ans = "story_candidate"
            elif has_deficit or has_level or has_lead:
                ans = "partial_story"
            else:
                ans = "unresolved"
            return {
                "type": "answer",
                "answer": ans,
                "reason": "budget_or_last_step_from_evidence",
                "hypothesis": {
                    "discovery_status": ans,
                    "status": ans,
                    "evidence_cues": {
                        "deficit_like": has_deficit,
                        "level_like": has_level,
                        "lead_like": has_lead,
                    },
                },
            }
        if n_obs == 0:
            return {"type": "tool", "tool": "global_overview", "arguments": {}}
        untouched = facts.get("untouched_partitions_sample") or []
        if untouched and self.duration > 120:
            p = untouched[0]
            start, end = float(p["start"]), float(p["end"])
            # shrink to partition_scan limits if needed
            if end - start > 900:
                end = start + 900
            if end - start > 60:
                return {
                    "type": "tool",
                    "tool": "partition_scan",
                    "arguments": {"start": round(start, 2), "end": round(end, 2)},
                }
        # scoreboard verify near last observation mid
        checked = [
            o
            for o in (facts.get("recent_observations") or [])
            if o.get("media_start_sec") is not None
        ]
        if checked:
            last = checked[-1]
            mid = 0.5 * (float(last["media_start_sec"]) + float(last["media_end_sec"]))
            s = max(0.0, mid - 8.0)
            e = min(self.duration, mid + 8.0)
            if e - s >= 1.0:
                return {
                    "type": "tool",
                    "tool": "read_scoreboard_window",
                    "arguments": {"start": round(s, 2), "end": round(e, 2)},
                }
        return {
            "type": "answer",
            "answer": "partial_story" if n_obs else "unresolved",
            "reason": "rule_policy_complete",
            "hypothesis": {"discovery_status": "partial_story" if n_obs else "unresolved"},
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
            "response_hint": (
                "Prefer compact tool JSON. On finish set answer to one of "
                "story_candidate|partial_story|no_comeback|unresolved."
            ),
        }
        messages = [
            {"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        mock = json.dumps(self._rule_policy(memory, remaining), ensure_ascii=False)
        resp = self.api.chat(
            role="planner",
            messages=messages,
            temperature=self.planner_temperature,
            mock_content=mock,
        )
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
            ans = str(raw.get("answer") or "unresolved")
            allowed = {
                "story_candidate",
                "partial_story",
                "no_comeback",
                "unresolved",
                "finish_evidence",
            }
            if ans not in allowed:
                ans = "unresolved"
            if ans == "finish_evidence":
                ans = "partial_story"
            hyp = dict(raw.get("hypothesis") or {})
            hyp.setdefault("discovery_status", ans)
            return {
                "type": "answer",
                "answer": ans,
                "reason": str(raw.get("reason") or ""),
                "hypothesis": hyp,
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
