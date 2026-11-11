"""Phase10-B Agent-inferred long-range narrative state, never Benchmark gold.

Builds a version/source-bound *hypothesis graph* from the working EDL and the
allowed V3-R story plan. It proposes bounded observation targets, consumes
validated semantic evidence metadata, and produces a concise Planner context.

Editorial adjacency is not match causation. Story roles are plan hints, not
human truth. No mutation, rendering, or paid API happens in this module.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Dict, Mapping, Optional, Sequence

from .story_timeline import build_story_timeline, narrative_slot_for_role

GRAPH_SCHEMA = "v3a_agent_inferred_narrative_graph_v1"
GRAPH_ROLE = "AGENT_INFERRED"
GOLD_SCHEMA = "migu_long_range_story_chain_v1"
BOUNDARY_SLOTS = frozenset({"opening", "development", "turn", "climax", "ending"})


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def _identifiers(row: Mapping[str, Any], singular: str, plural: str) -> list[str]:
    result: list[str] = []
    for v in (row.get(singular), row.get(plural)):
        if isinstance(v, str) and v.strip():
            result.append(v)
        elif isinstance(v, (tuple, list)):
            result.extend(x for x in v if isinstance(x, str) and x.strip())
    return list(dict.fromkeys(result))[:12]


def _reject_benchmark_gold(plan: Mapping[str, Any], edl: Sequence[Mapping[str, Any]]) -> None:
    """Defend the research protocol at the inference entrypoint."""
    for obj in [plan, *edl]:
        if not isinstance(obj, Mapping):
            continue
        if obj.get("data_role") == "BENCHMARK_GOLD" or obj.get("schema") == GOLD_SCHEMA:
            raise ValueError("Benchmark gold story chain cannot be used as an Agent input")


def _slot(seg: Mapping[str, Any]) -> str:
    return narrative_slot_for_role(str(seg.get("role") or ""))


def build_inferred_narrative_graph(
    *,
    edl: Sequence[Mapping[str, Any]],
    story_plan: Optional[Mapping[str, Any]] = None,
    source_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Infer only edit structure and review needs; never infer a goal fact.

    Source PTS windows are existing EDL claims and still need independent
    first-live/factual verification. No event/short-chain ground truth injected.
    """
    plan = story_plan or {}
    if not isinstance(plan, Mapping):
        raise ValueError("story_plan must be an object")
    if not isinstance(edl, (tuple, list)):
        raise ValueError("edl must be a list")
    _reject_benchmark_gold(plan, edl)
    timeline = build_story_timeline(edl)
    active = [r for r in edl if isinstance(r, Mapping) and r.get("include_in_cut", True) is not False]
    segments = list(timeline.get("segments") or [])
    ids = [str(s.get("segment_id") or "") for s in segments]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate active EDL segment_id in narrative graph")
    nodes: list[Dict[str, Any]] = []
    for s, row in zip(segments, active):
        media_window = (
            [s["media_in"], s["media_out"]]
            if s.get("has_media_window") else None
        )
        nodes.append({
            "node_id": "edl:" + str(s["segment_id"]),
            "segment_id": s["segment_id"],
            "role_hint": s.get("role"),
            "narrative_slot_hint": _slot(s),
            "story_time_range": [s["story_in"], s["story_out"]],
            "source_window": media_window,
            "event_ids": _identifiers(row, "event_id", "event_ids"),
            "short_chain_ids": _identifiers(row, "chain_id", "short_chain_ids"),
            "source_binding": "EDL_WINDOW_NOT_LIVE_VERIFIED" if media_window else "NON_MEDIA_CARD",
            "semantic_status": "UNOBSERVED_ROLE_HYPOTHESIS",
            "protected_goal_action_hint": "goal_action" in str(s.get("role") or ""),
        })
    edges: list[Dict[str, Any]] = []
    for a, b in zip(nodes, nodes[1:]):
        transition = (
            a["narrative_slot_hint"] in BOUNDARY_SLOTS
            and b["narrative_slot_hint"] in BOUNDARY_SLOTS
            and a["narrative_slot_hint"] != b["narrative_slot_hint"]
            and a["source_window"] is not None
            and b["source_window"] is not None
        )
        edges.append({
            "edge_id": "adj:" + _fingerprint([a["segment_id"], b["segment_id"]])[:16],
            "from_node": a["node_id"],
            "to_node": b["node_id"],
            "relation": "editorial_adjacency",
            "relation_status": "EDL_ORDER_ONLY",
            "narrative_transition_hypothesis": bool(transition),
            "narrative_evidence_status": "NOT_REVIEWED",
            "semantic_evidence": [],
            "is_match_causal_claim": False,
        })
    for key in ("story_goal", "narrative_goal", "theme", "title"):
        val = plan.get(key)
        if isinstance(val, str) and val.strip():
            story_goal = val[:240]
            break
    else:
        story_goal = None
    graph = {
        "schema": GRAPH_SCHEMA,
        "data_role": GRAPH_ROLE,
        "edl_sha256": _fingerprint(edl),
        "source_sha256": source_sha256,
        "story_plan_sha256": _fingerprint(plan),
        "story_goal_hint": story_goal,
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "unreviewed_narrative_transitions": sum(
                bool(e["narrative_transition_hypothesis"]) for e in edges
            ),
            "model_reviewed_transitions": 0,
        },
        "limitations": [
            "EDL adjacency/role annotations are not verified match causality or narrative quality.",
            "No Benchmark gold chain, annotated test EDL or human review is an Agent input.",
            "This graph alone never confirms a story defect or authorizes an edit.",
        ],
    }
    return graph


def graph_observation_targets(
    graph: Mapping[str, Any],
    *,
    max_targets: int = 2,
) -> list[Dict[str, Any]]:
    """Target transition boundaries by role, not by match-time jump length."""
    if graph.get("schema") != GRAPH_SCHEMA or graph.get("data_role") != GRAPH_ROLE:
        return []
    nodes = {n["node_id"]: n for n in graph.get("nodes") or [] if isinstance(n, dict)}
    scored = []
    for edge in graph.get("edges") or []:
        if not isinstance(edge, Mapping) or not edge.get("narrative_transition_hypothesis"):
            continue
        a, b = nodes.get(edge.get("from_node")), nodes.get(edge.get("to_node"))
        if not a or not b:
            continue
        lo = max(0.0, float(a["story_time_range"][1]) - 1.25)
        hi = float(b["story_time_range"][0]) + 1.25
        if not all(math.isfinite(v) for v in (lo, hi)) or hi <= lo:
            continue
        pair = (a["narrative_slot_hint"], b["narrative_slot_hint"])
        priority = 0 if pair in (
            ("development", "turn"), ("development", "climax"),
            ("turn", "climax"), ("climax", "ending"),
        ) else 1
        scored.append((priority, lo, {
            "issue_id": "graph_review_" + edge["edge_id"].replace(":", "_"),
            "category": "graph_transition_review_only",
            "story_time_range": [round(lo, 3), round(hi, 3)],
            "segment_ids": [a["segment_id"], b["segment_id"]],
            "evidence_sufficiency": "needs_video_verify",
            "diagnosis_status": "OBSERVATION_PRIORITY_NOT_STORY_DEFECT",
            "story_defect_confirmed": False,
            "note": "Observe role/state transition; source-time jump alone is NOT a defect.",
        }))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [v for _, _, v in scored[:max(0, max_targets)]]


def attach_validated_video_review(
    graph: Mapping[str, Any],
    *,
    observations: Mapping[str, Any],
    diagnosis_issues: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Attach bounded *model review claims*; do not promote narrative facts.

    Caller uses normalized evidence from vlm_semantic_evidence only when
    real provider and citation validation succeed. Previous graph immutable.
    """
    if graph.get("schema") != GRAPH_SCHEMA or graph.get("data_role") != GRAPH_ROLE:
        raise ValueError("not an AGENT_INFERRED narrative graph")
    out = json.loads(json.dumps(graph, ensure_ascii=False))
    if observations.get("fixture_or_offline") or not observations.get("semantic_provider_used"):
        return out
    issues = {
        str(i.get("issue_id")): i
        for i in diagnosis_issues if isinstance(i, Mapping) and i.get("issue_id")
    }
    evidence_list = observations.get("semantic_evidence") or []
    for item in evidence_list:
        if not isinstance(item, Mapping):
            continue
        issue = issues.get(str(item.get("issue_id") or ""))
        if not issue or item.get("citation_status") not in ("CITED_SENT_FRAMES", "VALID"):
            continue
        if item.get("claim_status") not in (
            "DEFECT_CONFIRMED", "FRAME_CITED", "SEMANTIC_HYPOTHESIS",
        ):
            continue
        affected = set(str(i) for i in issue.get("segment_ids") or [])
        for edge in out.get("edges") or []:
            nodes = {n["node_id"]: n for n in out.get("nodes") or []}
            a = nodes.get(edge.get("from_node"))
            b = nodes.get(edge.get("to_node"))
            if not a or not b or not (a["segment_id"] in affected or b["segment_id"] in affected):
                continue
            edge["narrative_evidence_status"] = "MODEL_REVIEWED_NOT_HUMAN_VERIFIED"
            edge["semantic_evidence"].append({
                "issue_id": item.get("issue_id"),
                "claim_status": item.get("claim_status"),
                "citation_status": item.get("citation_status"),
                "frame_refs": list(item.get("frame_refs") or [])[:6],
                "scope": (item.get("observation_scope") or {}).get("method")
                if isinstance(item.get("observation_scope"), Mapping) else None,
            })
    out["summary"]["model_reviewed_transitions"] = sum(
        1 for e in out.get("edges") or []
        if e.get("narrative_evidence_status") == "MODEL_REVIEWED_NOT_HUMAN_VERIFIED"
    )
    return out


def graph_planner_context(graph: Mapping[str, Any], *, max_nodes: int = 18) -> Dict[str, Any]:
    """Small inference-only prompt context (do not dump human benchmark labels)."""
    if graph.get("schema") != GRAPH_SCHEMA or graph.get("data_role") != GRAPH_ROLE:
        raise ValueError("Planner narrative graph provenance mismatch")
    nodes = [
        {
            "segment_id": n["segment_id"],
            "role_hint": n["role_hint"],
            "slot_hint_unverified": n["narrative_slot_hint"],
            "event_refs": n["event_ids"][:3],
            "short_chain_refs": n["short_chain_ids"][:3],
            "story_time_range": n["story_time_range"],
        }
        for n in (graph.get("nodes") or [])[:max_nodes]
    ]
    return {
        "data_role": GRAPH_ROLE,
        "story_goal_hint": graph.get("story_goal_hint"),
        "ordered_story_segments": nodes,
        "unreviewed_transition_count": (graph.get("summary") or {}).get(
            "unreviewed_narrative_transitions"
        ),
        "model_reviewed_transition_count": (graph.get("summary") or {}).get(
            "model_reviewed_transitions"
        ),
        "graph_edges_are_causal_facts": False,
        "instructions": (
            "Use only as inferred narrative state and observation priorities. "
            "Adjacency and role labels do not prove causal links, missing footage "
            "or edit necessity. Cite independently confirmed issues for mutations."
        ),
    }
