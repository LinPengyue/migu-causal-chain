"""Round 2.4 Story Planner — observation-aware DeepSeek loop."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from story_video_agent.api_provider import ApiProvider
from story_video_agent.v2_strip_guided_r2_3_planner import (
    V2R23StoryPlanner,
    apply_planner_decision,
    ensure_verified_goals_selected,
    finalize_relations,
    summarize_strips_for_planner,
)
from story_video_agent.v2_strip_guided_r2_4_memory import V2R24StoryMemory

_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)

SYSTEM_R24 = """You are Story Video Agent V2 Round 2.4 Global Story Planner.
Build a T01 comeback story using video-verified goals + algo-predicted strips + Qwen strip observations.

Return ONE JSON tool call per turn:
{"type":"tool","tool":TOOL,"arguments":{...},"reason":"..."}

TOOLS:
- select_node: {"node_id":"ke_|strip_...","beat":"setup|buildup|turning|climax|resolution","why":"..."}
  why MUST answer: related goal/phase, what info it adds, whether deletion hurts understanding.
- unselect_node: {"node_id":"...","why":"..."}  // revoke a prior selection using observation evidence
- exclude_node: {"node_id":"...","why":"..."}
- propose_relation: {"source_node_id","target_node_id","relation_type":"temporal|narrative|causal|correction",
  "explanation","supporting_event_ids":[],"supporting_strip_ids":[],"supporting_evidence_ids":[]}
  causal REQUIRES supporting_evidence_ids; never claim verified causal from score order alone.
- request_video_check: {"node_id":"strip_...","start":sec,"end":sec,"purpose":"coarse|dense","why":"..."}
- finish_story: {"discovery_status":"story_candidate|partial_story|unresolved","reason":"..."}

RULES:
1) Keep ALL video-verified ke_ goals.
2) Use strip_observations: if recommendation=drop/replace or supports_prior_why=false, unselect that strip.
3) Do NOT keep a fixed count of strips. Prefer 2–5 high-value non-goal strips after observation.
4) Never upgrade predicted strips to verified_action.
5) Prefer live attack context over replay/duplicate windows.
6) One tool per turn.
"""


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:  # noqa: BLE001
        m = _JSON_OBJ.search(text)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except Exception:  # noqa: BLE001
            return None


class V2R24StoryPlanner(V2R23StoryPlanner):
    def _llm_decide(self, memory: V2R24StoryMemory, step: int, max_steps: int) -> Optional[Dict[str, Any]]:  # type: ignore[override]
        user = json.dumps(
            {
                "step": step,
                "max_steps": max_steps,
                "state": memory.planner_view(),
                "instruction": (
                    "Act on strip_observations first if any pending drops. "
                    "Then refine selections. finish_story only when goals kept and observations addressed."
                ),
            },
            ensure_ascii=False,
        )
        try:
            resp = self.api.chat(
                role="planner",
                messages=[
                    {"role": "system", "content": SYSTEM_R24},
                    {"role": "user", "content": user},
                ],
            )
        except Exception as exc:  # noqa: BLE001
            self.planner_mode_log.append(f"llm_error:{exc}")
            return None
        text = ""
        if isinstance(resp, dict):
            text = str(resp.get("content") or resp.get("text") or "")
        obj = _extract_json(text)
        if not obj:
            return None
        if obj.get("type") == "answer":
            return {
                "type": "tool",
                "tool": "finish_story",
                "arguments": {
                    "discovery_status": obj.get("discovery_status") or "partial_story",
                    "reason": obj.get("reason") or "llm_answer",
                },
                "reason": "llm_answer",
            }
        tool = str(obj.get("tool") or "")
        if tool not in {
            "select_node",
            "unselect_node",
            "exclude_node",
            "propose_relation",
            "request_video_check",
            "finish_story",
        }:
            return None
        return {
            "type": "tool",
            "tool": tool,
            "arguments": obj.get("arguments") or {},
            "reason": str(obj.get("reason") or "llm"),
        }

    def _rule_decide(self, memory: V2R24StoryMemory, remaining: int) -> Dict[str, Any]:  # type: ignore[override]
        # Act on observations before finishing
        for nid, obs in memory.strip_observations.items():
            if nid not in memory.selected_node_ids:
                continue
            rec = obs.get("recommendation")
            if rec in {"drop", "replace"} or obs.get("supports_prior_why") is False:
                return {
                    "type": "tool",
                    "tool": "unselect_node",
                    "arguments": {
                        "node_id": nid,
                        "why": f"observation_{rec}:{obs.get('summary')}",
                    },
                    "reason": "rule_drop_on_observation",
                }
        # Pending selected strips without observation → request check
        for nid in memory.selected_node_ids:
            if not nid.startswith("strip_"):
                continue
            if nid in memory.strip_observations:
                continue
            meta = next((s for s in memory.strip_summaries if s.get("node_id") == nid), None)
            if not meta:
                continue
            return {
                "type": "tool",
                "tool": "request_video_check",
                "arguments": {
                    "node_id": nid,
                    "start": float(meta.get("t0_sec") or 0),
                    "end": min(float(meta.get("t0_sec") or 0) + 36.0, float(meta.get("t1_sec") or 0) or 1e9),
                    "purpose": "coarse",
                    "why": "missing_observation_for_selected_strip",
                },
                "reason": "rule_request_obs",
            }
        # Fall back to R2.3 rule path (goals + limited strips)
        return super()._rule_decide(memory, remaining)


def apply_r24_decision(memory: V2R24StoryMemory, decision: Dict[str, Any]) -> Dict[str, Any]:
    tool = decision.get("tool")
    args = decision.get("arguments") or {}
    if tool == "unselect_node":
        nid = str(args.get("node_id") or "")
        why = str(args.get("why") or "unselect")
        evid = None
        if nid in memory.strip_observations:
            evid = memory.strip_observations[nid].get("evidence_id")
        memory.tool_log.append({"decision": decision})
        memory.unselect_node(nid, why=why, evidence_id=evid)
        return {"unselected": nid, "why": why, "evidence_id": evid}
    if tool == "select_node":
        nid = str(args.get("node_id") or "")
        obs = apply_planner_decision(memory, decision)
        memory.selection_change_log.append(
            {
                "action": "select",
                "node_id": nid,
                "beat": args.get("beat"),
                "why": args.get("why"),
            }
        )
        return obs
    return apply_planner_decision(memory, decision)


def seed_from_r23(
    memory: V2R24StoryMemory,
    *,
    r23_selected: List[str],
    selection_reasons: Dict[str, str],
    beat_assignments: Optional[Dict[str, List[str]]] = None,
) -> None:
    memory.r23_selected_baseline = list(r23_selected)
    beats = beat_assignments or {}
    nid_to_beat = {}
    for b, members in beats.items():
        for nid in members:
            nid_to_beat[nid] = b
    for nid in r23_selected:
        if nid.startswith("ke_"):
            continue  # goals added via ensure
        beat = nid_to_beat.get(nid, "buildup")
        apply_r24_decision(
            memory,
            {
                "type": "tool",
                "tool": "select_node",
                "arguments": {
                    "node_id": nid,
                    "beat": beat,
                    "why": selection_reasons.get(nid) or "r23_baseline",
                },
                "reason": "seed_r23",
            },
        )


def apply_review_observations(memory: V2R24StoryMemory, review_doc: Dict[str, Any]) -> None:
    for rev in review_doc.get("reviews") or []:
        nid = rev.get("node_id")
        if not nid:
            continue
        memory.record_observation(rev)
        if rev.get("recommendation") in {"drop", "replace"} and nid in memory.selected_node_ids:
            memory.narrative_conflicts.append(
                {
                    "node_id": nid,
                    "conflict": "observation_vs_prior_selection",
                    "recommendation": rev.get("recommendation"),
                    "summary": rev.get("summary"),
                }
            )


__all__ = [
    "V2R24StoryPlanner",
    "SYSTEM_R24",
    "apply_r24_decision",
    "seed_from_r23",
    "apply_review_observations",
    "ensure_verified_goals_selected",
    "finalize_relations",
    "summarize_strips_for_planner",
]
