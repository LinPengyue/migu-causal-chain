"""Event-Guided planner Round 2 — DeepSeek mid-loop candidate search (agent mode)."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from story_video_agent.api_provider import ApiProvider
from story_video_agent.tools import ToolArgumentError
from story_video_agent.v2_phase_c1_toolbox import V2PhaseC1Toolbox

_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)

PLANNER_SYSTEM = """You are Story Video Agent V2 Event-Guided AGENT mode.
You search for live GOAL ACTIONS using a candidate event board + Qwen video tools.
No causal.json, story roles, or pre-made story graph are provided.

Target: T01 comeback (either side trails then later leads) if evidence supports it.

Return ONE JSON object per turn:
A) Meta/board tool (no video):
 {"type":"tool","tool":"list_candidates"|"list_anchors"|"select_candidate"|"reject_candidate"|"shift_search"|"confirm_localization",
  "arguments":{...}}
B) Video tool (Qwen):
 {"type":"tool","tool":"observe_window",
  "arguments":{"start":0,"end":10,"candidate_event_id":"event_xxx","purpose":"dense|coarse|live_replay|scoreboard"}}
C) Finish:
 {"type":"answer","answer":"story_candidate|partial_story|no_comeback|unresolved","reason":"...",
  "beats":{...},
  "relations":[{"from_event_id":"...","to_event_id":"...","relation_type":"temporal|causal|narrative",
    "supporting_evidence_ids":["ev_..."],"explanation":"...","verification_status":"proposed"}]}

Rules:
1. YOU choose which candidate and which media window — do not blindly use fixed offsets.
2. If observation is celebration/scoreboard-only or midfield, OR scoreboard already shows the NEW score without a live shot/net, shift_search earlier with a LARGE delta (-40 to -90). Prefer virtual_*early150* probes when Score_Recognition lags.
3. confirm_localization ONLY when the latest observe_window for that candidate has
   shooting_action_evidence=true AND goal_result_evidence=true. If confirm is denied,
   you MUST observe_window or shift_search — never spam confirm_localization.
4. causal edges MUST include supporting_evidence_ids from real observations; never claim equalizer caused go-ahead from order alone.
5. One tool/answer per turn; compact JSON.
"""

META_TOOLS = {
    "list_candidates",
    "list_anchors",
    "select_candidate",
    "reject_candidate",
    "shift_search",
    "confirm_localization",
}
VIDEO_PURPOSES = {"dense", "coarse", "live_replay", "scoreboard"}


class V2EventGuidedAgent:
    def __init__(
        self,
        *,
        duration: float,
        tools: V2PhaseC1Toolbox,
        api: ApiProvider,
        planner_mode: str = "agent",
        use_llm_planner: bool = True,
        planner_temperature: float = 0.1,
    ) -> None:
        self.duration = float(duration)
        self.tools = tools
        self.api = api
        self.planner_mode = planner_mode  # agent | rule
        self.use_llm_planner = bool(use_llm_planner) and planner_mode == "agent"
        self.planner_temperature = float(planner_temperature)
        self.decision_attempts: List[Dict[str, Any]] = []
        self.argument_error: Optional[Dict[str, Any]] = None
        self.planner_mode_log: List[str] = []

    def decide(self, memory: Any, step: int, max_steps: int) -> Dict[str, Any]:
        self.decision_attempts = []
        self.argument_error = None
        remaining = max_steps - step
        rule = self._rule_policy(memory, remaining)

        # Anti-loop: if planner spammed denied confirms, force rule recovery.
        recent = memory.autonomous_decisions[-4:]
        confirm_spam = (
            len(recent) >= 3
            and all(r.get("tool") == "confirm_localization" for r in recent[-3:])
        )
        want_llm = bool(self.use_llm_planner) and not confirm_spam
        if confirm_spam:
            self.planner_mode_log.append("rule_recover_confirm_spam")
        # Agent mode: LLM on every step except force terminal on last step still via LLM
        for attempt in range(2):
            raw = rule
            parse_mode = "rule_policy"
            if want_llm:
                try:
                    llm = self._propose_llm(memory, remaining, step=step, max_steps=max_steps)
                    if isinstance(llm, dict) and "type" in llm:
                        if remaining <= 1 and llm.get("type") != "answer":
                            # force finish synthesis via LLM retry content or rule terminal
                            raw = self._terminal_from_memory(memory, reason="last_step_force_answer")
                            parse_mode = "rule_terminal_forced"
                            self.planner_mode_log.append("llm_non_terminal_forced_rule")
                        else:
                            raw = llm
                            parse_mode = "llm_api"
                            self.planner_mode_log.append("llm_mid" if remaining > 1 else "llm_terminal")
                    else:
                        self.planner_mode_log.append("llm_fallback_rule")
                except Exception:  # noqa: BLE001
                    self.planner_mode_log.append("llm_error_fallback_rule")
                    raw = rule
            else:
                self.planner_mode_log.append("rule_baseline")

            record: Dict[str, Any] = {
                "attempt": attempt,
                "raw_response": raw,
                "parse_mode": parse_mode,
                "rule_fallback": rule,
            }
            self.decision_attempts.append(record)
            try:
                decision = self._normalize(raw, remaining)
                record.update(status="accepted", decision=decision)
                memory.log_autonomy(
                    {
                        "step": step,
                        "parse_mode": parse_mode,
                        "decision_type": decision.get("type"),
                        "tool": decision.get("tool"),
                        "used_llm": parse_mode == "llm_api",
                    }
                )
                return decision
            except (ValueError, TypeError, ToolArgumentError) as exc:
                record.update(status="rejected", error=str(exc))
                if remaining <= 1:
                    terminal = self._terminal_from_memory(memory, reason="last_step_fallback")
                    record.update(status="accepted_terminal_fallback", decision=terminal)
                    return terminal
                if attempt:
                    self.argument_error = {"error": type(exc).__name__, "message": str(exc)}
                    return self._terminal_from_memory(memory, reason=f"repair_exhausted:{exc}")
                continue
        raise ValueError("invalid_decision: exhausted")

    def finish_from_memory(self, memory: Any, *, reason: str) -> Dict[str, Any]:
        return self._terminal_from_memory(memory, reason=reason)

    # --- rule baseline (Event-Rule / recovery) ---
    def _rule_policy(self, memory: Any, remaining: int) -> Dict[str, Any]:
        if remaining <= 1:
            return self._terminal_from_memory(memory, reason="budget_or_last_step")

        board = memory.board
        # Prefer open/observing candidates near score changes, search earlier.
        # CRITICAL: after shift_search must observe — never shift in a loop.
        cands = board.list_candidates()

        def _priority(c: Dict[str, Any]) -> tuple:
            et = str(c.get("event_type") or "")
            # early150 probes and Goal/Shot first
            if et == "score_lag_probe" and "early150" in str(c.get("candidate_event_id")):
                return (0, float(c.get("event_time_sec") or 0))
            if et in {"Goal", "Shot"}:
                return (1, float(c.get("event_time_sec") or 0))
            if et == "score_lag_probe":
                return (2, float(c.get("event_time_sec") or 0))
            return (3, float(c.get("event_time_sec") or 0))

        cands = sorted(cands, key=_priority)
        for c in cands:
            if c["status"] in ("localized", "rejected"):
                continue
            eid = c["candidate_event_id"]
            full = board.get(eid) or {}
            n_obs = int(c.get("n_observations") or 0)
            attempts = int(full.get("search_attempts") or 0)
            center = float(c.get("search_center_sec") or c.get("event_time_sec") or 0)
            pending = bool(full.get("pending_observe_after_shift"))

            def _observe(cen: float) -> Dict[str, Any]:
                start = max(0.0, cen - 5.0)
                end = min(self.duration, start + 10.0)
                return {
                    "type": "tool",
                    "tool": "observe_window",
                    "arguments": {
                        "start": round(start, 2),
                        "end": round(end, 2),
                        "candidate_event_id": eid,
                        "purpose": "dense",
                    },
                }

            if n_obs == 0 or pending:
                return _observe(center)
            if attempts >= 5 and c["status"] != "localized":
                return {
                    "type": "tool",
                    "tool": "reject_candidate",
                    "arguments": {
                        "candidate_event_id": eid,
                        "reason": "rule_exhausted_no_frame_bound_action",
                    },
                }
            # After an observation without localization: shift once, next turn observes.
            return {
                "type": "tool",
                "tool": "shift_search",
                "arguments": {"candidate_event_id": eid, "delta_sec": -60.0},
            }
        return self._terminal_from_memory(memory, reason="rule_candidates_exhausted")

    def _terminal_from_memory(self, memory: Any, *, reason: str) -> Dict[str, Any]:
        anchors = memory.board.list_anchors()
        changes = [a for a in anchors if a.get("kind") == "score_change"]
        pairs = []
        for a in anchors:
            if a.get("kind") == "initial_score" and a.get("score_pair"):
                pairs.append(tuple(a["score_pair"]))
            if a.get("kind") == "score_change" and a.get("score_after"):
                pairs.append(tuple(a["score_after"]))
        status = "unresolved"
        if len(pairs) >= 2:
            first, later = pairs[0], pairs[-1]
            if (first[0] < first[1] and later[0] > later[1]) or (
                first[1] < first[0] and later[1] > later[0]
            ):
                status = "story_candidate" if memory.evidence_records or memory.verifications else "partial_story"
            else:
                status = "partial_story"

        localized = memory.board.localized()
        beats = {
            "setup": {"event_ids": [], "note": "inferred"},
            "turning": {"event_ids": [], "note": ""},
            "climax": {"event_ids": [], "note": ""},
            "resolution": {"event_ids": [], "note": ""},
        }
        if anchors:
            setup = next((a for a in anchors if a.get("kind") == "initial_score"), None)
            if setup:
                beats["setup"]["event_ids"] = [setup.get("event_id")]
        if changes:
            beats["turning"]["event_ids"] = [changes[0].get("event_id")]
            if len(changes) >= 2:
                beats["climax"]["event_ids"] = [changes[1].get("event_id")]
            beats["resolution"]["event_ids"] = [changes[-1].get("event_id")]

        # Relations: temporal only in rule fallback — NEVER auto-causal
        relations: List[Dict[str, Any]] = []
        loc_ids = [c["candidate_event_id"] for c in localized]
        evid_ids = [e.get("candidate_event_id") for e in memory.evidence_records]
        chain = loc_ids or [c.get("event_id") for c in changes]
        for i in range(len(chain) - 1):
            relations.append(
                {
                    "from_event_id": chain[i],
                    "to_event_id": chain[i + 1],
                    "relation_type": "temporal",
                    "supporting_evidence_ids": [x for x in evid_ids if x][:2],
                    "explanation": "time-ordered score or localized events",
                    "verification_status": "proposed",
                }
            )
            # narrative optional weak link
            relations.append(
                {
                    "from_event_id": chain[i],
                    "to_event_id": chain[i + 1],
                    "relation_type": "narrative",
                    "supporting_evidence_ids": [],
                    "explanation": "same T01 score-path narrative (not causal proof)",
                    "verification_status": "proposed",
                }
            )

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
            "meta_tools": sorted(META_TOOLS),
            "video_tool": {
                "name": "observe_window",
                "purposes": sorted(VIDEO_PURPOSES),
                "maps_to": {
                    "dense": "dense_action_inspect",
                    "coarse": "coarse_search",
                    "live_replay": "verify_live_replay",
                    "scoreboard": "read_scoreboard_window",
                },
            },
            "facts": facts,
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
            name = str(raw.get("tool") or "")
            args = raw.get("arguments") or {}
            if not isinstance(args, dict):
                raise ToolArgumentError("arguments must be object")
            if name in META_TOOLS:
                return {"type": "tool", "tool": name, "arguments": args}
            if name == "observe_window":
                return {"type": "tool", "tool": name, "arguments": args}
            # legacy C1 tool names → wrap as observe_window
            if name in {
                "coarse_search",
                "refine_window",
                "dense_action_inspect",
                "read_scoreboard_window",
                "verify_live_replay",
            }:
                purpose = {
                    "coarse_search": "coarse",
                    "refine_window": "dense",
                    "dense_action_inspect": "dense",
                    "read_scoreboard_window": "scoreboard",
                    "verify_live_replay": "live_replay",
                }[name]
                return {
                    "type": "tool",
                    "tool": "observe_window",
                    "arguments": {
                        "start": args.get("start"),
                        "end": args.get("end"),
                        "candidate_event_id": args.get("candidate_event_id")
                        or args.get("task_id")
                        or "unknown",
                        "purpose": purpose,
                    },
                }
            raise ValueError(f"unknown tool {name}")
        if t == "answer":
            ans = str(raw.get("answer") or "unresolved")
            allowed = {
                "story_candidate",
                "partial_story",
                "no_comeback",
                "unresolved",
            }
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
