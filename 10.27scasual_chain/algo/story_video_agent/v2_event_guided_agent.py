"""Event-Guided planner: DeepSeek uses event times as anchors; invents story structure."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from story_video_agent.api_provider import ApiProvider
from story_video_agent.tools import ToolArgumentError
from story_video_agent.v2_phase_c1_toolbox import V2PhaseC1Toolbox

_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)

PLANNER_SYSTEM = """You are Story Video Agent V2 Event-Guided mode.
Inputs you MAY use: raw football event detections (id/type/times/scoreboard/live-replay)
AND Qwen video observations from tools. You MUST NOT assume pre-labeled story roles or
causal chains — none are provided.

Target story TYPE to evaluate: T01 (comeback / reverse a deficit by EITHER side).
If one side trails then later leads (e.g. 0-1 → 1-1 → 2-1), that IS a T01 story_candidate —
do NOT reject because the final margin is large or the leading team looks "dominant".

Return one JSON object:
- Tool: {"type":"tool","tool":"<name>","arguments":{"start":..,"end":..,"task_id":"..."}}
- Finish: {"type":"answer","answer":"<story_candidate|partial_story|no_comeback|unresolved>",
  "reason":"...",
  "beats":{"setup":{"event_ids":[],"media_start":null,"media_end":null,"note":""},
           "turning":{...},"climax":{...},"resolution":{...}},
  "relations":[{"from_event_id":"...","to_event_id":"...","kind":"temporal|causal|narrative","note":""}]}

Tools (Qwen verifies real video): coarse_search, refine_window, dense_action_inspect,
read_scoreboard_window, verify_live_replay.

Rules:
1. Event times are SEARCH ANCHORS only — Score_Recognition board state ≠ proven goal action.
2. Prefer verifying LIVE windows slightly BEFORE scoreboard jumps for shot/net action.
3. Invent temporal/causal/narrative relations yourself; do not copy annotation schemas.
4. Never invent timestamps outside observed event windows / tool results.
5. One tool call per turn; compact JSON; no chain-of-thought.
6. Finish with story_candidate only if deficit→level→lead is supported by score anchors
   AND at least some action verification exists; else partial_story / unresolved.
"""


class V2EventGuidedAgent:
    def __init__(
        self,
        *,
        duration: float,
        tools: V2PhaseC1Toolbox,
        api: ApiProvider,
        use_llm_planner: bool = True,
        planner_temperature: float = 0.1,
    ) -> None:
        self.duration = float(duration)
        self.tools = tools
        self.api = api
        self.use_llm_planner = bool(use_llm_planner)
        self.planner_temperature = float(planner_temperature)
        self.decision_attempts: List[Dict[str, Any]] = []
        self.argument_error: Optional[Dict[str, Any]] = None
        self.planner_mode_log: List[str] = []
        self._pending_anchor_idx = 0

    def decide(self, memory: Any, step: int, max_steps: int) -> Dict[str, Any]:
        self.decision_attempts = []
        self.argument_error = None
        remaining = max_steps - step
        rule = self._rule_policy(memory, remaining)
        # Spend Qwen budget on anchor verification via rule policy; call DeepSeek
        # for autonomous beat/relation synthesis when anchors are done or last steps.
        want_llm = bool(self.use_llm_planner) and (
            remaining <= 2 or str(rule.get("type")) == "answer"
        )
        for attempt in range(2):
            raw = rule
            parse_mode = "rule_policy"
            if want_llm:
                try:
                    llm = self._propose_llm(memory, remaining, step=step, max_steps=max_steps)
                    if isinstance(llm, dict) and "type" in llm:
                        # On last step force answer; otherwise accept tool or answer
                        if remaining <= 1 and llm.get("type") != "answer":
                            self.planner_mode_log.append("llm_non_terminal_ignored")
                        else:
                            raw = llm
                            parse_mode = "llm_api"
                            self.planner_mode_log.append(
                                "llm_terminal" if remaining <= 2 else "llm"
                            )
                    else:
                        self.planner_mode_log.append("llm_fallback_rule")
                except Exception:  # noqa: BLE001
                    self.planner_mode_log.append("llm_error_fallback_rule")
                    raw = rule
            else:
                self.planner_mode_log.append("rule_verify")

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
                if remaining <= 1:
                    terminal = self._terminal_from_memory(memory, reason="last_step_fallback")
                    record.update(status="accepted_terminal_fallback", decision=terminal)
                    return terminal
                if attempt:
                    if isinstance(exc, ToolArgumentError):
                        self.argument_error = {
                            "error": "ToolArgumentError",
                            "message": str(exc),
                        }
                        return self._terminal_from_memory(
                            memory, reason=f"repair_exhausted:{exc}"
                        )
                    raise ValueError("invalid_decision: " + str(exc)) from exc
                continue
        raise ValueError("invalid_decision: exhausted")

    def _verify_anchors(self, memory: Any) -> List[Dict[str, Any]]:
        """Anchors needing video check: initial deficit board + each score_change."""
        facts = memory.facts_for_planner(remaining=99)
        out: List[Dict[str, Any]] = []
        for a in facts.get("score_anchors") or []:
            if a.get("kind") in ("initial_score", "score_change"):
                out.append(a)
        return out

    def _score_changes(self, memory: Any) -> List[Dict[str, Any]]:
        return [a for a in self._verify_anchors(memory) if a.get("kind") == "score_change"]

    def _rule_policy(self, memory: Any, remaining: int) -> Dict[str, Any]:
        if remaining <= 1:
            return self._terminal_from_memory(memory, reason="budget_or_last_step")

        anchors = self._verify_anchors(memory)
        verified_ids = {
            str(v.get("task_id") or "")
            for v in memory.verifications
            if v.get("task_id")
        }
        # Walk anchors: dense inspect → live/replay. Replay-tagged boards look further back.
        for i, a in enumerate(anchors):
            tid = f"anchor_{i}_{a.get('event_id')}"
            t = float(a["event_time_sec"])
            et = str(a.get("event_type") or "")
            weak_type = et not in {"Goal", "Shot", "Save"}
            if a.get("is_replay") or weak_type:
                lookback = 120.0
            elif a.get("kind") == "initial_score":
                lookback = 100.0
            else:
                lookback = 40.0
            dense_id = tid + "_dense"
            replay_id = tid + "_live"
            if dense_id not in verified_ids:
                # Score_Recognition often lags live goals — center well before board event
                mid = max(0.0, t - min(70.0, lookback * 0.65))
                start = max(0.0, mid - 5.0)
                end = min(self.duration, start + 10.0)
                if end - start < 1.0:
                    end = min(self.duration, start + 2.0)
                return {
                    "type": "tool",
                    "tool": "dense_action_inspect",
                    "arguments": {
                        "start": round(start, 2),
                        "end": round(end, 2),
                        "task_id": dense_id,
                    },
                }
            if replay_id not in verified_ids:
                start = max(0.0, t - lookback)
                # Cap to verify_live_replay max (~16s) — use a slice near expected live action
                start = max(0.0, t - min(lookback, 14.0))
                end = min(self.duration, start + 12.0)
                return {
                    "type": "tool",
                    "tool": "verify_live_replay",
                    "arguments": {
                        "start": round(start, 2),
                        "end": round(end, 2),
                        "task_id": replay_id,
                    },
                }

        if anchors and len(memory.verifications) < 2:
            a = anchors[0]
            t = float(a["event_time_sec"])
            return {
                "type": "tool",
                "tool": "coarse_search",
                "arguments": {
                    "start": round(max(0.0, t - 40.0), 2),
                    "end": round(min(self.duration, t + 20.0), 2),
                    "task_id": "fallback_coarse",
                },
            }
        return self._terminal_from_memory(memory, reason="anchors_verified")

    def finish_from_memory(self, memory: Any, *, reason: str) -> Dict[str, Any]:
        """Public terminal synthesis used by runner on budget exhaustion."""
        return self._terminal_from_memory(memory, reason=reason)

    def _terminal_from_memory(self, memory: Any, *, reason: str) -> Dict[str, Any]:
        anchors = self._verify_anchors(memory)
        changes = [a for a in anchors if a.get("kind") == "score_change"]
        pairs = []
        for a in memory.event_digest.get("score_anchors") or []:
            if a.get("kind") == "initial_score" and a.get("score_pair"):
                pairs.append(tuple(a["score_pair"]))
            if a.get("kind") == "score_change" and a.get("score_after"):
                pairs.append(tuple(a["score_after"]))
        status = "unresolved"
        if len(changes) >= 1 and pairs:
            status = "partial_story"
            first, later = pairs[0], pairs[-1]
            if first[0] < first[1] and later[0] > later[1]:
                status = "story_candidate"
            elif first[1] < first[0] and later[1] > later[0]:
                status = "story_candidate"
        if memory.verifications and status == "unresolved" and changes:
            status = "partial_story"

        beats = {
            "setup": {"event_ids": [], "note": "inferred_from_score_anchors"},
            "turning": {"event_ids": [], "note": ""},
            "climax": {"event_ids": [], "note": ""},
            "resolution": {"event_ids": [], "note": ""},
        }
        relations: List[Dict[str, Any]] = []
        # Prefer initial deficit event as setup; else first change
        setup_src = next((a for a in anchors if a.get("kind") == "initial_score"), None)
        if setup_src is None and changes:
            setup_src = changes[0]
        if setup_src:
            beats["setup"]["event_ids"] = [setup_src.get("event_id")]
            beats["setup"]["media_start"] = max(0.0, float(setup_src["event_time_sec"]) - 40)
            beats["setup"]["media_end"] = float(setup_src["event_time_sec"])
        if changes:
            beats["turning"]["event_ids"] = [changes[0].get("event_id")]
            beats["turning"]["media_start"] = max(0.0, float(changes[0]["event_time_sec"]) - 20)
            beats["turning"]["media_end"] = float(changes[0]["event_time_sec"])
            if setup_src:
                relations.append(
                    {
                        "from_event_id": setup_src.get("event_id"),
                        "to_event_id": changes[0].get("event_id"),
                        "kind": "temporal",
                        "note": "deficit_then_level_or_next_change",
                    }
                )
                relations.append(
                    {
                        "from_event_id": setup_src.get("event_id"),
                        "to_event_id": changes[0].get("event_id"),
                        "kind": "narrative",
                        "note": "inferred_setup_to_turning",
                    }
                )
            if len(changes) >= 2:
                beats["climax"]["event_ids"] = [changes[1].get("event_id")]
                beats["climax"]["media_start"] = max(
                    0.0, float(changes[1]["event_time_sec"]) - 20
                )
                beats["climax"]["media_end"] = float(changes[1]["event_time_sec"])
                relations.append(
                    {
                        "from_event_id": changes[0].get("event_id"),
                        "to_event_id": changes[1].get("event_id"),
                        "kind": "causal",
                        "note": "inferred_momentum_after_level_or_prior_goal",
                    }
                )
            beats["resolution"]["event_ids"] = [changes[-1].get("event_id")]
            beats["resolution"]["media_start"] = max(
                0.0, float(changes[-1]["event_time_sec"]) - 15
            )
            beats["resolution"]["media_end"] = float(changes[-1]["event_time_sec"])

        return {
            "type": "answer",
            "answer": status,
            "reason": reason,
            "beats": beats,
            "relations": relations,
        }

    def _propose_llm(
        self, memory: Any, remaining: int, *, step: int, max_steps: int
    ) -> Optional[Dict[str, Any]]:
        facts = memory.facts_for_planner(remaining=remaining)
        user = {
            "step": step,
            "max_steps": max_steps,
            "remaining": remaining,
            "tools": self.tools.descriptions(),
            "facts": facts,
            "instruction": (
                "Verify goal-like actions near score anchors with tools, then finish "
                "with autonomously inferred beats/relations. No annotated causal input."
            ),
        }
        mock = json.dumps(self._rule_policy(memory, remaining), ensure_ascii=False)
        raw = self.api.chat(
            role="planner",
            messages=[
                {"role": "system", "content": PLANNER_SYSTEM},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
            ],
            temperature=self.planner_temperature,
            mock_content=mock,
        )
        text = str((raw or {}).get("content") or "")
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        m = _JSON_OBJ.search(text)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None

    def _normalize(self, raw: Dict[str, Any], remaining: int) -> Dict[str, Any]:
        if not isinstance(raw, dict) or "type" not in raw:
            raise ValueError("decision must be object with type")
        t = raw["type"]
        if t == "tool":
            if remaining <= 1:
                raise ValueError("last step must answer, not tool")
            name = raw.get("tool")
            if name not in self.tools.descriptions():
                raise ValueError(f"unknown tool {name}")
            return {
                "type": "tool",
                "tool": name,
                "arguments": raw.get("arguments") or {},
            }
        if t == "answer":
            ans = str(raw.get("answer") or "unresolved")
            allowed = {
                "story_candidate",
                "partial_story",
                "no_comeback",
                "unresolved",
                "finish_localization",
            }
            if ans == "finish_localization":
                ans = "unresolved"
            if ans not in allowed:
                ans = "unresolved"
            return {
                "type": "answer",
                "answer": ans,
                "reason": str(raw.get("reason") or ""),
                "beats": raw.get("beats") if isinstance(raw.get("beats"), dict) else {},
                "relations": raw.get("relations")
                if isinstance(raw.get("relations"), list)
                else [],
            }
        raise ValueError(f"bad type {t}")
