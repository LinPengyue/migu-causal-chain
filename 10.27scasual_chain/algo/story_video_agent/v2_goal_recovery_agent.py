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

        # Sticky: once any window shows score_after, live action is earlier.
        last_scores = cand.get("last_score_pairs") or []
        score_after = cand.get("score_after")
        score_before = cand.get("score_before")
        after_t = tuple(score_after) if score_after else None
        before_t = tuple(score_before) if score_before else None
        board_already_after = bool(cand.get("board_after_seen"))
        if not board_already_after and after_t and last_scores:
            board_already_after = any(tuple(s) == after_t for s in last_scores)
        last_still_after = bool(after_t and any(tuple(s) == after_t for s in last_scores))
        last_has_before = bool(before_t and any(tuple(s) == before_t for s in last_scores))
        streak = int(cand.get("same_window_streak") or 0)

        def _region_start() -> float:
            rs = None
            for ph in phases:
                try:
                    rs = (
                        float(ph["start_sec"])
                        if rs is None
                        else min(rs, float(ph["start_sec"]))
                    )
                except (TypeError, ValueError, KeyError):
                    continue
            if rs is None:
                rs = float(cand.get("previous_score_observation_time") or 0.0)
            return rs

        def _walk_earlier(end_cap: float, reason: str) -> Dict[str, Any]:
            chunk = 75.0
            end = float(end_cap)
            start = end - chunk
            rs = _region_start()
            if end <= rs + 8.0:
                return {
                    "type": "tool",
                    "tool": "mark_unresolved",
                    "arguments": {
                        "candidate_id": cid,
                        "why": "earlier_than_scoreboard_exhausted_without_shot_net",
                    },
                    "reason": "rule_earlier_exhaust",
                }
            start = max(rs, start)
            end = max(start + 8.0, end)
            return {
                "type": "tool",
                "tool": "refine",
                "arguments": {
                    "candidate_id": cid,
                    "start": start,
                    "end": end,
                    "purpose": "dense" if (end - start) <= 45 else "coarse",
                },
                "reason": reason,
            }

        shot = cand.get("last_shot_action") or {}
        result = cand.get("last_goal_result") or {}

        # One densify around a bound shot even if the coarse window OCR'd score_after
        # (scoreboard often updates a few seconds after the action).
        if (
            shot.get("media_sec") is not None
            and not cand.get("last_has_net")
            and not cand.get("tried_dense_around_shot")
            and streak < 2
        ):
            t = float(shot["media_sec"])
            return {
                "type": "tool",
                "tool": "refine",
                "arguments": {
                    "candidate_id": cid,
                    "start": max(0.0, t - 5.0),
                    "end": t + 7.0,
                    "purpose": "dense",
                },
                "reason": "rule_dense_around_shot_frame",
            }
        # Bound net without shot → densify just before result frame.
        if (
            result.get("media_sec") is not None
            and not shot.get("media_sec")
            and not cand.get("tried_dense_around_result")
            and streak < 2
        ):
            t = float(result["media_sec"])
            return {
                "type": "tool",
                "tool": "refine",
                "arguments": {
                    "candidate_id": cid,
                    "start": max(0.0, t - 8.0),
                    "end": t + 4.0,
                    "purpose": "dense",
                },
                "reason": "rule_dense_around_result_frame",
            }

        # Still seeing score_after after densify attempts → walk further back.
        if board_already_after and last_still_after and cand.get("last_window"):
            return _walk_earlier(
                float(cand["last_window"]["start"]),
                "rule_search_earlier_than_scoreboard_after",
            )

        # Partial candidate densify (once); avoid identical-window loops.
        if last_grade == "goal_candidate" and cand.get("last_window") and streak < 2:
            w = cand["last_window"]
            # If we already saw score_before here, densify the late edge (transition).
            mid = 0.5 * (float(w["start"]) + float(w["end"]))
            if last_has_before or float(w["end"]) - float(w["start"]) > 20.0:
                mid = float(w["start"]) + 0.72 * (float(w["end"]) - float(w["start"]))
            return {
                "type": "tool",
                "tool": "refine",
                "arguments": {
                    "candidate_id": cid,
                    "start": max(float(w["start"]), mid - 8.0),
                    "end": min(float(w["end"]), mid + 8.0),
                    "purpose": "dense",
                },
                "reason": "rule_refine_partial",
            }

        if board_already_after and cand.get("last_window"):
            # Streak exhausted or scoreboard-only earlier hit → step back again.
            return _walk_earlier(
                float(cand["last_window"]["start"]),
                "rule_search_earlier_than_scoreboard_after",
            )
        if board_already_after:
            baw = cand.get("board_after_window") or {}
            end_cap = float(
                baw.get("start")
                or cand.get("score_confirmation_time")
                or 0.0
            )
            return _walk_earlier(end_cap, "rule_search_earlier_than_scoreboard_after")
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
