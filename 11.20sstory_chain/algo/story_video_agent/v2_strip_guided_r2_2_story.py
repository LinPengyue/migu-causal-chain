"""Full-match T01 Story Beats / Graph from unified verified Goals + strip B."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from story_video_agent.v2_event_guided_relation import review_relations


def _goal_time(g: Dict[str, Any]) -> float:
    return float(
        (g.get("goal_result") or {}).get("media_sec")
        or (g.get("media_time") or {}).get("event_time_sec")
        or 0.0
    )


def _score_path(goals: Sequence[Dict[str, Any]], anchors: Sequence[Dict[str, Any]]) -> List[Tuple]:
    pairs: List[Tuple] = []
    for a in anchors:
        if a.get("kind") == "initial_score" and a.get("score_pair"):
            pairs.append(tuple(a["score_pair"]))
        if a.get("kind") == "score_change" and a.get("score_after"):
            pairs.append(tuple(a["score_after"]))
    if not pairs:
        for g in sorted(goals, key=_goal_time):
            st = g.get("related_score_transition") or {}
            if st.get("score_before") is not None:
                pairs.append(tuple(st["score_before"]))
            if st.get("score_after") is not None:
                pairs.append(tuple(st["score_after"]))
    # dedupe consecutive
    out: List[Tuple] = []
    for p in pairs:
        if not out or out[-1] != p:
            out.append(p)
    return out


def _find_chain_near(
    chains: Sequence[Dict[str, Any]],
    t_sec: float,
    *,
    prefer_goal: bool = True,
) -> Optional[Dict[str, Any]]:
    t_ms = t_sec * 1000.0
    best = None
    best_d = 1e18
    for c in chains:
        t0, t1 = float(c.get("t0_ms") or 0), float(c.get("t1_ms") or 0)
        mid = 0.5 * (t0 + t1)
        d = abs(mid - t_ms)
        if t0 - 30_000 <= t_ms <= t1 + 30_000:
            d = min(d, abs(t_ms - mid) * 0.5)
        bonus = 0.0
        cat = c.get("predicted_category") or c.get("chain_category")
        if prefer_goal and (c.get("last_event") == "goal" or cat == "outcome"):
            bonus = -50_000
        if d + bonus < best_d:
            best_d = d + bonus
            best = c
    return best


def build_story_nodes(
    *,
    verified_goals: Sequence[Dict[str, Any]],
    strip_b_chains: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """One Story Node per video-verified Goal (independent of outcome classify)."""
    nodes = []
    for i, g in enumerate(sorted(verified_goals, key=_goal_time)):
        t = _goal_time(g)
        chain = _find_chain_near(strip_b_chains, t, prefer_goal=True)
        st = g.get("related_score_transition") or {}
        cat = None
        tpl = None
        if chain:
            cat = chain.get("predicted_category") or chain.get("chain_category")
            tpl = chain.get("predicted_template_id") or chain.get("template_id")
        nodes.append(
            {
                "node_id": f"sn_goal_{i+1}_{g.get('inferred_event_id')}",
                "node_type": "goal_action",
                "role_in_t01": _role_for_index(i, len(verified_goals)),
                "inferred_event_id": g.get("inferred_event_id") or g.get("event_id"),
                "media_time_sec": t,
                "shot_action": g.get("shot_action"),
                "goal_result": g.get("goal_result"),
                "edit_window": g.get("edit_window"),
                "score_before": st.get("score_before"),
                "score_after": st.get("score_after"),
                "score_confirmation_time": st.get("score_confirmation_time"),
                "live_or_replay": (
                    "live"
                    if (g.get("video_context") or {}).get("broadcast_phase") == "LIVE"
                    or (g.get("live_or_replay") == "live")
                    else ("replay" if (g.get("video_context") or {}).get("is_replay") else "unknown")
                ),
                "verification_status": g.get("verification_status"),
                "linked_strip_chain_id": (chain or {}).get("strip_chain_id") or (chain or {}).get("clip_id"),
                "linked_strip_template": tpl,
                "linked_strip_category": cat,
                "outcome_chain_ok": bool(
                    chain
                    and (
                        cat == "outcome"
                        or chain.get("last_event") == "goal"
                    )
                ),
                "as_independent_key_node": True,
                "provenance": "video_agent_inferred+strip_map",
                "render_ready": False,
            }
        )
    return nodes


def _role_for_index(i: int, n: int) -> str:
    if i == 0:
        return "opening_deficit"
    if i == n - 1 and n >= 3:
        return "climax_lead"
    if i == 1:
        return "equalizer"
    if i == 2:
        return "go_ahead"
    return f"goal_{i+1}"


def build_t01_story_graph(
    *,
    verified_goals: Sequence[Dict[str, Any]],
    strip_b_bundle: Dict[str, Any],
    event_digest: Dict[str, Any],
    evidence_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    chains = strip_b_bundle.get("chains") or []
    anchors = event_digest.get("score_anchors") or []
    nodes = build_story_nodes(verified_goals=verified_goals, strip_b_chains=chains)
    path = _score_path(verified_goals, anchors)

    # Beats aligned to verified goal nodes (not random strip priority)
    beat_map = {
        "setup": None,
        "buildup": None,
        "turning": None,
        "climax": None,
        "resolution": None,
    }
    if nodes:
        beat_map["setup"] = nodes[0]
        if len(nodes) >= 2:
            beat_map["turning"] = nodes[1]
        if len(nodes) >= 3:
            beat_map["buildup"] = nodes[1]
            beat_map["climax"] = nodes[2]
        if len(nodes) >= 4:
            beat_map["climax"] = nodes[-2]
            beat_map["resolution"] = nodes[-1]
        elif len(nodes) >= 3:
            beat_map["resolution"] = nodes[-1]
        elif len(nodes) == 2:
            beat_map["climax"] = nodes[-1]
            beat_map["resolution"] = nodes[-1]
        else:
            beat_map["climax"] = nodes[0]

    def _beat_payload(node: Optional[Dict[str, Any]], note: str) -> Dict[str, Any]:
        if not node:
            return {
                "story_node_ids": [],
                "strip_chain_ids": [],
                "event_ids": [],
                "media_in": None,
                "media_out": None,
                "note": note,
                "provenance": "unresolved",
            }
        ew = node.get("edit_window") or {}
        return {
            "story_node_ids": [node["node_id"]],
            "strip_chain_ids": [node["linked_strip_chain_id"]] if node.get("linked_strip_chain_id") else [],
            "event_ids": [node["inferred_event_id"]],
            "media_in": ew.get("media_in") or (float(node["media_time_sec"]) - 2.0),
            "media_out": ew.get("media_out") or (float(node["media_time_sec"]) + 3.0),
            "shot_action": node.get("shot_action"),
            "goal_result": node.get("goal_result"),
            "note": note,
            "provenance": "video_verified_goal_node",
        }

    beats = {
        "setup": _beat_payload(beat_map["setup"], "opening deficit / first goal"),
        "buildup": _beat_payload(beat_map["buildup"], "buildup after deficit"),
        "turning": _beat_payload(beat_map["turning"], "equalizer / turning point"),
        "climax": _beat_payload(beat_map["climax"], "go-ahead / climax"),
        "resolution": _beat_payload(beat_map["resolution"], "lead consolidation"),
    }

    relations: List[Dict[str, Any]] = []
    # Temporal along goal nodes
    for i in range(len(nodes) - 1):
        a, b = nodes[i], nodes[i + 1]
        relations.append(
            {
                "from_event_id": a["inferred_event_id"],
                "to_event_id": b["inferred_event_id"],
                "relation_type": "temporal",
                "explanation": "Ordered by verified goal_result media times",
                "supporting_evidence_ids": list(evidence_ids or [])[:4],
                "verification_status": "rule_temporal",
            }
        )
    # Narrative deficit→lead if score path flips
    flipped = False
    if len(path) >= 2:
        first, later = path[0], path[-1]
        flipped = (first[0] < first[1] and later[0] > later[1]) or (
            first[1] < first[0] and later[1] > later[0]
        )
    if flipped and len(nodes) >= 2:
        relations.append(
            {
                "from_event_id": nodes[0]["inferred_event_id"],
                "to_event_id": nodes[-1]["inferred_event_id"],
                "relation_type": "narrative",
                "explanation": "T01 score path deficit→lead (narrative, not causal proof)",
                "supporting_evidence_ids": list(evidence_ids or [])[:8],
                "verification_status": "score_path_narrative",
            }
        )
    # No fabricated causal edges from score order
    reviewed = review_relations(
        relations,
        evidence_ids=set(evidence_ids or []),
        verified_event_ids={n["inferred_event_id"] for n in nodes},
    )

    discovery = "story_candidate" if flipped and len(nodes) >= 2 else (
        "partial_story" if nodes else "unresolved"
    )

    return {
        "schema": "v2_strip_r2_2_story_graph_v1",
        "story_type": "T01_comeback",
        "discovery_status": discovery,
        "score_path": path,
        "n_verified_goal_nodes": len(nodes),
        "nodes": nodes,
        "beats": beats,
        "relations": reviewed.get("relations") or [],
        "relation_review": {
            "n_accepted": reviewed.get("n_accepted"),
            "n_downgraded": reviewed.get("n_downgraded"),
            "n_rejected": reviewed.get("n_rejected"),
            "policy": reviewed.get("policy"),
        },
        "provenance_note": (
            "temporal=verified goal times; narrative=score_path; "
            "causal never invented from score order alone; "
            "nodes retained even without outcome strip classify"
        ),
        "render_ready": False,
    }
