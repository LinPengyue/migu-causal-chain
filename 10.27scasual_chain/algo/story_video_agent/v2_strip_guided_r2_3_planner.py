"""Global Story Planner — DeepSeek selects narrative structure; rule fallback if LLM fails."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence

from story_video_agent.api_provider import ApiProvider
from story_video_agent.v2_event_guided_relation import review_relations
from story_video_agent.v2_strip_guided_r2_3_memory import V2R23StoryMemory

_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)

SYSTEM = """You are Story Video Agent V2 Round 2.3 Global Story Planner for football.
You build a FULL-MATCH narrative (often T01 comeback) from:
- score path
- video-verified key goals
- algorithm-predicted strip causal chains (NOT gold)
- optional Qwen video checks

Return ONE JSON object per turn:
A) Tool: {"type":"tool","tool": TOOL, "arguments":{...}, "reason":"..."}
   TOOLS:
   - select_node: {"node_id":"ke_...|strip_...","beat":"setup|buildup|turning|climax|resolution","why":"..."}
   - exclude_node: {"node_id":"...","why":"..."}
   - propose_relation: {"source_node_id":"...","target_node_id":"...","relation_type":"temporal|narrative|causal|correction","explanation":"...","supporting_event_ids":[],"supporting_strip_ids":[],"supporting_evidence_ids":[]}
   - request_video_check: {"node_id":"strip_...","start":sec,"end":sec,"purpose":"coarse|dense|live_replay","why":"..."}
   - finish_story: {"discovery_status":"story_candidate|partial_story|unresolved","reason":"..."}
B) Do NOT select all strips. Prefer 1–3 non-goal buildup/danger strips that support the comeback arc.
C) Causal relations REQUIRE supporting_evidence_ids; score-order alone → temporal or narrative only.
D) Never invent media times. Never claim unverified Goals are verified.
E) One tool/finish per turn; compact JSON.
"""


def summarize_strips_for_planner(
    chains: Sequence[Dict[str, Any]],
    *,
    key_event_times: Sequence[float],
    max_n: int = 24,
) -> List[Dict[str, Any]]:
    """Rank strips by narrative usefulness near verified goals / danger-outcome."""
    scored = []
    for c in chains:
        t0 = float(c.get("t0_sec") or 0)
        t1 = float(c.get("t1_sec") or 0)
        cat = str(c.get("predicted_category") or c.get("chain_category") or "")
        last = str(c.get("last_event") or "")
        first = str(c.get("first_event") or "")
        near = min((abs(0.5 * (t0 + t1) - kt) for kt in key_event_times), default=1e9) if key_event_times else 1e9
        # Prefer danger/outcome near goals; also buildup windows BEFORE equalizer/go-ahead
        bonus = 0
        if cat == "outcome" or last == "goal":
            bonus -= 40
        if cat == "danger":
            bonus -= 25
        if cat == "correction":
            bonus -= 10
        # penalize very long / far strips
        score = near / 60.0 + bonus + max(0.0, (t1 - t0) - 90) / 30.0
        scored.append((score, c))
    scored.sort(key=lambda x: x[0])
    out = []
    for _, c in scored[:max_n]:
        out.append(
            {
                "node_id": f"strip_{(c.get('strip_chain_id') or c.get('clip_id'))}",
                "strip_chain_id": c.get("strip_chain_id") or c.get("clip_id"),
                "t0_sec": c.get("t0_sec"),
                "t1_sec": c.get("t1_sec"),
                "category": c.get("predicted_category") or c.get("chain_category"),
                "template": c.get("predicted_template_id") or c.get("template_id"),
                "first_event": c.get("first_event"),
                "last_event": c.get("last_event"),
                "event_sequence": (c.get("event_sequence") or [])[:8],
                "provenance": "algo_predicted_strip",
                "verification_status": "predicted",
            }
        )
    return out


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


class V2R23StoryPlanner:
    def __init__(self, *, api: ApiProvider, use_llm: bool = True) -> None:
        self.api = api
        self.use_llm = bool(use_llm)
        self.planner_mode_log: List[str] = []

    def decide(self, memory: V2R23StoryMemory, step: int, max_steps: int) -> Dict[str, Any]:
        remaining = max_steps - step
        rule = self._rule_decide(memory, remaining)
        if self.use_llm and remaining > 1:
            llm = self._llm_decide(memory, step, max_steps)
            if llm:
                self.planner_mode_log.append("llm")
                return llm
            self.planner_mode_log.append("llm_fallback_rule")
        else:
            self.planner_mode_log.append("rule")
        return rule

    def _llm_decide(self, memory: V2R23StoryMemory, step: int, max_steps: int) -> Optional[Dict[str, Any]]:
        user = json.dumps(
            {
                "step": step,
                "max_steps": max_steps,
                "state": memory.planner_view(),
                "instruction": "Select next tool or finish_story. Prefer selecting a buildup strip if none selected yet.",
            },
            ensure_ascii=False,
        )
        try:
            resp = self.api.chat(
                role="planner",
                messages=[
                    {"role": "system", "content": SYSTEM},
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
        if not obj or obj.get("type") not in {"tool", "answer"}:
            return None
        if obj.get("type") == "answer":
            return {
                "type": "tool",
                "tool": "finish_story",
                "arguments": {
                    "discovery_status": obj.get("answer") or obj.get("discovery_status") or "partial_story",
                    "reason": obj.get("reason") or "llm_answer",
                },
                "reason": "llm_answer",
            }
        tool = str(obj.get("tool") or "")
        if tool not in {
            "select_node",
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

    def _rule_decide(self, memory: V2R23StoryMemory, remaining: int) -> Dict[str, Any]:
        """Deterministic T01-oriented selection without hardcoding match times."""
        if remaining <= 1:
            return {
                "type": "tool",
                "tool": "finish_story",
                "arguments": {
                    "discovery_status": "story_candidate" if len(memory.selected_node_ids) >= 3 else "partial_story",
                    "reason": "last_step",
                },
                "reason": "rule_last_step",
            }

        # Ensure all verified key goals selected into beats
        for ke in memory.key_events:
            nid = ke["key_event_id"]
            if nid in memory.selected_node_ids or nid in memory.excluded_node_ids:
                continue
            beat = self._beat_for_key_event(ke, memory.key_events)
            return {
                "type": "tool",
                "tool": "select_node",
                "arguments": {
                    "node_id": nid,
                    "beat": beat,
                    "why": f"video-verified goal for score {ke.get('score_before')}->{ke.get('score_after')}",
                },
                "reason": "rule_select_verified_goal",
            }

        # Add temporal relations between consecutive selected goals
        goal_ids = [k["key_event_id"] for k in memory.key_events if k["key_event_id"] in memory.selected_node_ids]
        existing = {(r.get("source_node_id"), r.get("target_node_id"), r.get("relation_type")) for r in memory.relations}
        for i in range(len(goal_ids) - 1):
            key = (goal_ids[i], goal_ids[i + 1], "temporal")
            if key not in existing:
                return {
                    "type": "tool",
                    "tool": "propose_relation",
                    "arguments": {
                        "source_node_id": goal_ids[i],
                        "target_node_id": goal_ids[i + 1],
                        "relation_type": "temporal",
                        "explanation": "Verified goals ordered by media time",
                        "supporting_event_ids": [],
                        "supporting_strip_ids": [],
                        "supporting_evidence_ids": [],
                    },
                    "reason": "rule_temporal_goals",
                }

        # Narrative deficit→lead once
        if len(goal_ids) >= 2:
            narr = (goal_ids[0], goal_ids[-1], "narrative")
            if narr not in existing:
                return {
                    "type": "tool",
                    "tool": "propose_relation",
                    "arguments": {
                        "source_node_id": goal_ids[0],
                        "target_node_id": goal_ids[-1],
                        "relation_type": "narrative",
                        "explanation": "Comeback arc: opening deficit to later lead (narrative, not causal proof)",
                        "supporting_event_ids": [k.get("inferred_event_id") for k in memory.key_events],
                        "supporting_strip_ids": [],
                        "supporting_evidence_ids": [],
                    },
                    "reason": "rule_narrative_comeback",
                }

        # Select up to 4 non-goal strips across deficit/buildup/turning windows
        selected_strips = [n for n in memory.selected_node_ids if n.startswith("strip_")]
        if len(selected_strips) < 4:
            eq_t = None
            for k in memory.key_events:
                sb, sa = k.get("score_before"), k.get("score_after")
                if sb and sa and tuple(sb) == (0, 1) and tuple(sa) == (1, 1):
                    eq_t = float(k.get("media_time_sec") or 0)
                    break
            for s in memory.strip_summaries:
                nid = s["node_id"]
                if nid in memory.selected_node_ids or nid in memory.excluded_node_ids:
                    continue
                if s.get("last_event") == "goal":
                    # already covered by verified goal nodes — exclude duplicate strip goal endpoint
                    return {
                        "type": "tool",
                        "tool": "exclude_node",
                        "arguments": {
                            "node_id": nid,
                            "why": "goal-endpoint strip redundant with verified goal node",
                        },
                        "reason": "rule_exclude_redundant_goal_strip",
                    }
                t0 = float(s.get("t0_sec") or 0)
                t1 = float(s.get("t1_sec") or 0)
                cat = str(s.get("category") or "")
                # buildup: before equalizer, danger/special attack
                if eq_t and t1 < eq_t and cat in {"danger", "special", "outcome"}:
                    return {
                        "type": "tool",
                        "tool": "select_node",
                        "arguments": {
                            "node_id": nid,
                            "beat": "buildup",
                            "why": f"predicted {cat} strip before equalizer supports deficit-period pressure ({s.get('first_event')}→{s.get('last_event')})",
                        },
                        "reason": "rule_select_buildup_strip",
                    }
                # after equalizer before go-ahead as turning support
                go_t = None
                for k in memory.key_events:
                    sb, sa = k.get("score_before"), k.get("score_after")
                    if sb and sa and tuple(sb) == (1, 1) and tuple(sa) == (2, 1):
                        go_t = float(k.get("media_time_sec") or 0)
                        break
                if eq_t and go_t and eq_t < t0 < go_t and cat == "danger":
                    return {
                        "type": "tool",
                        "tool": "select_node",
                        "arguments": {
                            "node_id": nid,
                            "beat": "turning",
                            "why": "danger strip between equalizer and go-ahead",
                        },
                        "reason": "rule_select_turning_strip",
                    }
                # Pre-goal context strips near later verified goals (predicted only)
                for k in memory.key_events[2:]:
                    kt = float(k.get("media_time_sec") or 0)
                    if kt <= 0:
                        continue
                    if cat in {"danger", "outcome", "special"} and (kt - 180.0) <= t1 <= kt + 15.0:
                        beat = self._beat_for_key_event(k, memory.key_events)
                        if beat == "setup":
                            beat = "buildup"
                        return {
                            "type": "tool",
                            "tool": "select_node",
                            "arguments": {
                                "node_id": nid,
                                "beat": "buildup" if beat in {"turning", "climax"} else beat,
                                "why": (
                                    f"predicted {cat} strip near verified goal "
                                    f"{k.get('score_before')}->{k.get('score_after')} "
                                    f"({s.get('first_event')}→{s.get('last_event')})"
                                ),
                            },
                            "reason": "rule_select_near_goal_strip",
                        }

        # Link selected buildup strip → equalizer narratively
        strip_sel = [n for n in memory.selected_node_ids if n.startswith("strip_")]
        if strip_sel and goal_ids:
            # find equalizer goal id
            eq_id = None
            for k in memory.key_events:
                sa = tuple(k.get("score_after") or ())
                if sa == (1, 1):
                    eq_id = k["key_event_id"]
                    break
            if eq_id:
                key = (strip_sel[0], eq_id, "narrative")
                if key not in existing:
                    return {
                        "type": "tool",
                        "tool": "propose_relation",
                        "arguments": {
                            "source_node_id": strip_sel[0],
                            "target_node_id": eq_id,
                            "relation_type": "narrative",
                            "explanation": "Buildup pressure strip precedes equalizer in comeback narrative",
                            "supporting_strip_ids": [strip_sel[0].replace("strip_", "", 1)],
                            "supporting_event_ids": [],
                            "supporting_evidence_ids": [],
                        },
                        "reason": "rule_narrative_buildup_to_equalizer",
                    }

        return {
            "type": "tool",
            "tool": "finish_story",
            "arguments": {
                "discovery_status": "story_candidate" if len(memory.selected_node_ids) >= 4 else "partial_story",
                "reason": "rule_structure_complete",
            },
            "reason": "rule_finish",
        }

    @staticmethod
    def _beat_for_key_event(ke: Dict[str, Any], all_kes: Sequence[Dict[str, Any]]) -> str:
        """Map verified goals to beats by score role (not index padding into buildup)."""
        idx = next((i for i, x in enumerate(all_kes) if x.get("key_event_id") == ke.get("key_event_id")), 0)
        n = len(all_kes)
        sb = ke.get("score_before")
        sa = tuple(ke.get("score_after") or ())
        # Opening deficit / first conceded
        if idx == 0 or sb is None:
            return "setup"
        # Equalizer: home side catches up to 1-1 (or any first equalize after deficit)
        if sb and sa and int(sa[0]) == int(sa[1]) and int(sa[0]) >= 1:
            return "turning"
        # Last verified goal closes the story
        if idx == n - 1 and n >= 3:
            return "resolution"
        # First lead after being behind → climax; later lead extensions stay climax
        if sb and sa and int(sa[0]) > int(sa[1]) and int(sb[0]) <= int(sb[1]):
            return "climax"
        if sb and sa and int(sa[0]) > int(sb[0]):
            return "climax"
        return "climax"


def apply_planner_decision(memory: V2R23StoryMemory, decision: Dict[str, Any]) -> Dict[str, Any]:
    """Mutate memory according to planner tool decision; return observation."""
    tool = decision.get("tool")
    args = decision.get("arguments") or {}
    memory.tool_log.append({"decision": decision})
    if tool == "select_node":
        nid = str(args.get("node_id") or "")
        beat = str(args.get("beat") or "buildup")
        why = str(args.get("why") or "")
        if nid and nid not in memory.selected_node_ids:
            memory.selected_node_ids.append(nid)
            memory.selection_reasons[nid] = why
            if beat in memory.beat_assignments and nid not in memory.beat_assignments[beat]:
                memory.beat_assignments[beat].append(nid)
        return {"selected": nid, "beat": beat, "why": why}
    if tool == "exclude_node":
        nid = str(args.get("node_id") or "")
        why = str(args.get("why") or "")
        if nid and nid not in memory.excluded_node_ids:
            memory.excluded_node_ids.append(nid)
            memory.exclusion_reasons[nid] = why
        return {"excluded": nid, "why": why}
    if tool == "propose_relation":
        rel = {
            "source_node_id": args.get("source_node_id"),
            "target_node_id": args.get("target_node_id"),
            "relation_type": args.get("relation_type") or "temporal",
            "explanation": args.get("explanation") or "",
            "supporting_event_ids": list(args.get("supporting_event_ids") or []),
            "supporting_strip_ids": list(args.get("supporting_strip_ids") or []),
            "supporting_evidence_ids": list(args.get("supporting_evidence_ids") or []),
            "provenance": "planner",
            "verification_status": "proposed",
        }
        memory.relations.append(rel)
        return {"relation_added": rel}
    if tool == "request_video_check":
        req = {
            "node_id": args.get("node_id"),
            "start": args.get("start"),
            "end": args.get("end"),
            "purpose": args.get("purpose") or "coarse",
            "why": args.get("why") or "",
        }
        memory.pending_video_checks.append(req)
        return {"queued_video_check": req}
    if tool == "finish_story":
        memory.discovery_status = str(args.get("discovery_status") or "partial_story")
        return {"finished": True, "discovery_status": memory.discovery_status, "reason": args.get("reason")}
    return {"error": f"unknown_tool:{tool}"}


def finalize_relations(memory: V2R23StoryMemory) -> Dict[str, Any]:
    rel_in = [
        {
            "from_event_id": r.get("source_node_id"),
            "to_event_id": r.get("target_node_id"),
            "relation_type": r.get("relation_type"),
            "explanation": r.get("explanation"),
            "supporting_evidence_ids": r.get("supporting_evidence_ids") or [],
            "verification_status": r.get("verification_status"),
        }
        for r in memory.relations
    ]
    verified = {k["key_event_id"] for k in memory.key_events}
    reviewed = review_relations(rel_in, evidence_ids=set(), verified_event_ids=verified)
    out = []
    for r, src in zip(reviewed.get("relations") or [], memory.relations):
        out.append(
            {
                "source_node_id": r.get("from_event_id"),
                "target_node_id": r.get("to_event_id"),
                "relation_type": r.get("relation_type"),
                "explanation": r.get("explanation"),
                "supporting_event_ids": src.get("supporting_event_ids") or [],
                "supporting_strip_ids": src.get("supporting_strip_ids") or [],
                "supporting_evidence_ids": r.get("supporting_evidence_ids") or [],
                "provenance": src.get("provenance"),
                "verification_status": r.get("verification_status"),
                "review_reasons": r.get("review_reasons"),
            }
        )
    return {
        "schema": "v2_r23_story_relations_v1",
        "relations": out,
        "review": {
            "n_accepted": reviewed.get("n_accepted"),
            "n_downgraded": reviewed.get("n_downgraded"),
            "n_rejected": reviewed.get("n_rejected"),
        },
        "render_ready": False,
    }
