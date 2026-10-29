"""DeepSeek (or rule) planner for missing-goal video search — no gold times."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from story_video_agent.api_provider import ApiProvider

SYSTEM = """You plan VIDEO SEARCH for missing football goals.
You receive missing_goal_candidates built ONLY from scoreboard changes + raw events + predicted strips.
Rules:
1. score_confirmation_time is NOT the action time.
2. Propose coarse-to-fine windows INSIDE each candidate search_region / phases.
3. Prefer late phases near confirmation first, then earlier phases if needed.
4. Never invent absolute timestamps outside the provided search_region.
5. Never use known gold goal times or story roles.
6. After an observation, decide: refine | shift_phase | mark_unresolved | propose_inferred_goal.
7. propose_inferred_goal ONLY if observation reports verified_action with shot+net frame evidence and not pure replay.
Output ONE JSON object:
{"type":"tool","tool":"observe_phase"|"refine"|"mark_unresolved"|"finish",
 "arguments":{...},"reason":"..."}
observe_phase args: candidate_id, phase_index (int), purpose: coarse|dense|live_replay|scoreboard
refine args: candidate_id, start, end, purpose
mark_unresolved args: candidate_id, why
finish args: {}
"""


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


class V2GoalRecoveryAgent:
    def __init__(
        self,
        *,
        api: ApiProvider,
        use_llm_planner: bool = True,
    ) -> None:
        self.api = api
        self.use_llm_planner = use_llm_planner
        self.planner_mode_log: List[str] = []
        self.decision_attempts = 0

    def decide(self, state: Dict[str, Any], step: int, max_steps: int) -> Dict[str, Any]:
        self.decision_attempts = 0
        if step >= max_steps - 1:
            return {"type": "tool", "tool": "finish", "arguments": {}, "reason": "last_step"}
        if self.use_llm_planner:
            try:
                decision = self._llm_decide(state, step, max_steps)
                if decision:
                    self.planner_mode_log.append("llm")
                    return decision
            except Exception as exc:  # noqa: BLE001
                self.planner_mode_log.append(f"llm_fail:{type(exc).__name__}")
        self.planner_mode_log.append("rule")
        return self._rule_decide(state, step, max_steps)

    def _llm_decide(self, state: Dict[str, Any], step: int, max_steps: int) -> Optional[Dict[str, Any]]:
        self.decision_attempts += 1
        user = json.dumps(
            {
                "step": step,
                "max_steps": max_steps,
                "open_candidates": state.get("open_candidates"),
                "recent_observations": state.get("recent_observations"),
                "frames_remaining": state.get("frames_remaining"),
                "rules": [
                    "Do not invent times outside search_region",
                    "Celebration or scoreboard alone is insufficient",
                ],
            },
            ensure_ascii=False,
        )
        resp = self.api.chat(
            role="planner",
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user},
            ],
        )
        text = ""
        if isinstance(resp, dict):
            text = str(resp.get("content") or resp.get("text") or "")
        else:
            text = str(resp or "")
        obj = _extract_json(text)
        if not obj or obj.get("type") != "tool":
            return None
        tool = str(obj.get("tool") or "")
        if tool not in {"observe_phase", "refine", "mark_unresolved", "finish"}:
            return None
        return {
            "type": "tool",
            "tool": tool,
            "arguments": obj.get("arguments") or {},
            "reason": str(obj.get("reason") or "llm"),
        }

    def _rule_decide(self, state: Dict[str, Any], step: int, max_steps: int) -> Dict[str, Any]:
        """Deterministic coarse→fine without match-specific times."""
        opens: List[Dict[str, Any]] = list(state.get("open_candidates") or [])
        if not opens:
            return {"type": "tool", "tool": "finish", "arguments": {}, "reason": "no_open"}
        # Prefer candidates with zero observations, then those needing refine.
        opens.sort(
            key=lambda c: (
                int(c.get("n_observations") or 0),
                0 if c.get("kind") == "score_change_missing_goal" else 1,
                -float(c.get("score_confirmation_time") or 0),
            )
        )
        cand = opens[0]
        cid = cand["candidate_id"]
        phases = list((cand.get("search_region") or {}).get("phases") or [])
        n_obs = int(cand.get("n_observations") or 0)
        last_grade = cand.get("last_grade")

        if last_grade == "goal_candidate" and cand.get("last_window"):
            w = cand["last_window"]
            mid = 0.5 * (float(w["start"]) + float(w["end"]))
            return {
                "type": "tool",
                "tool": "refine",
                "arguments": {
                    "candidate_id": cid,
                    "start": max(float(w["start"]), mid - 6.0),
                    "end": min(float(w["end"]), mid + 6.0),
                    "purpose": "dense",
                },
                "reason": "rule_refine_partial",
            }
        if n_obs >= max(3, len(phases)):
            return {
                "type": "tool",
                "tool": "mark_unresolved",
                "arguments": {"candidate_id": cid, "why": "phases_exhausted_without_verified_action"},
                "reason": "rule_exhaust",
            }
        # Start from last phase (near confirmation), then earlier.
        if phases:
            idx = max(0, len(phases) - 1 - n_obs)
            purpose = "coarse" if n_obs == 0 else ("dense" if n_obs >= 1 else "coarse")
            return {
                "type": "tool",
                "tool": "observe_phase",
                "arguments": {
                    "candidate_id": cid,
                    "phase_index": idx,
                    "purpose": purpose if purpose != "dense" or n_obs == 0 else "coarse",
                },
                "reason": "rule_phase_from_end",
            }
        return {
            "type": "tool",
            "tool": "mark_unresolved",
            "arguments": {"candidate_id": cid, "why": "no_phases"},
            "reason": "rule_no_phases",
        }
