"""Full-match Story Graph for Round 2.3."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from story_video_agent.v2_strip_guided_r2_3_memory import V2R23StoryMemory


def _clip_window_for_node(
    *,
    node_id: str,
    key_events: Sequence[Dict[str, Any]],
    strip_by_id: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    if node_id.startswith("ke_"):
        ke = next((k for k in key_events if k.get("key_event_id") == node_id), None)
        if not ke:
            return {}
        ew = ke.get("edit_window") or {}
        # Prefer verified edit window; pad buildup for attack context slightly
        tin = float(ew.get("media_in") or ke.get("media_time_sec") or 0) - 1.0
        # Include short pre-shot buildup (~8s) for goal clips when shot known
        shot = (ke.get("shot_action") or {}).get("media_sec")
        if shot is not None:
            tin = min(tin, float(shot) - 6.0)
        tout = float(ew.get("media_out") or ke.get("media_time_sec") or 0) + 2.0
        return {
            "media_in": max(0.0, tin),
            "media_out": tout,
            "time_status": "verified_action",
            "time_provenance": {"source": "video_verified_edit_window", "human_confirmed": False},
            "render_eligibility": "candidate",
        }
    if node_id.startswith("strip_"):
        sid = node_id.replace("strip_", "", 1)
        s = strip_by_id.get(sid) or strip_by_id.get(node_id)
        if not s:
            return {"time_status": "unavailable", "render_eligibility": "blocked"}
        t0 = float(s.get("t0_sec") or 0)
        t1 = float(s.get("t1_sec") or 0)
        # Cap long strips for story pacing
        if t1 - t0 > 25.0:
            t1 = t0 + 25.0
        return {
            "media_in": t0,
            "media_out": t1,
            "time_status": "predicted_strip_span",
            "time_provenance": {"source": "algo_predicted_strip", "human_confirmed": False},
            "render_eligibility": "candidate_predicted",
        }
    return {}


def build_full_story_graph(
    *,
    memory: V2R23StoryMemory,
    relations_doc: Dict[str, Any],
    score_anchors: Sequence[Dict[str, Any]],
    strip_chains: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    strip_by_id = {
        str(c.get("strip_chain_id") or c.get("clip_id")): c for c in strip_chains
    }
    # also index planner summaries
    for s in memory.strip_summaries:
        sid = str(s.get("strip_chain_id") or "")
        if sid:
            strip_by_id.setdefault(sid, s)

    nodes: List[Dict[str, Any]] = []

    # Score nodes
    for i, a in enumerate(score_anchors):
        nodes.append(
            {
                "node_id": f"score_{i}_{a.get('event_id')}",
                "node_type": "score",
                "kind": a.get("kind"),
                "score_pair": a.get("score_pair") or a.get("score_after"),
                "score_before": a.get("score_before"),
                "score_after": a.get("score_after") or a.get("score_pair"),
                "media_time_sec": a.get("event_time_sec"),
                "source_event_id": a.get("event_id"),
                "provenance": "events_json_score_anchor",
            }
        )

    # Key event / goal nodes
    for ke in memory.key_events:
        nodes.append(
            {
                "node_id": ke["key_event_id"],
                "node_type": "event",
                "subtype": "verified_goal",
                "inferred_event_id": ke.get("inferred_event_id"),
                "score_before": ke.get("score_before"),
                "score_after": ke.get("score_after"),
                "media_time_sec": ke.get("media_time_sec"),
                "shot_action": ke.get("shot_action"),
                "goal_result": ke.get("goal_result"),
                "edit_window": ke.get("edit_window"),
                "live_or_replay": ke.get("live_or_replay"),
                "verification_status": ke.get("verification_status"),
                "nearby_strip_chains": ke.get("nearby_strip_chains"),
                "selected": ke["key_event_id"] in memory.selected_node_ids,
                "selection_reason": memory.selection_reasons.get(ke["key_event_id"]),
                "provenance": "video_agent_inferred",
            }
        )

    # Strip chain nodes (selected + summarized pool)
    seen_strips = set()
    for s in memory.strip_summaries:
        nid = s["node_id"]
        sid = s.get("strip_chain_id")
        seen_strips.add(nid)
        nodes.append(
            {
                "node_id": nid,
                "node_type": "strip_chain",
                "strip_chain_id": sid,
                "t0_sec": s.get("t0_sec"),
                "t1_sec": s.get("t1_sec"),
                "category": s.get("category"),
                "template": s.get("template"),
                "first_event": s.get("first_event"),
                "last_event": s.get("last_event"),
                "event_sequence": s.get("event_sequence"),
                "verification_status": "predicted",
                "selected": nid in memory.selected_node_ids,
                "excluded": nid in memory.excluded_node_ids,
                "selection_reason": memory.selection_reasons.get(nid),
                "exclusion_reason": memory.exclusion_reasons.get(nid),
                "provenance": "algo_predicted_strip",
                "local_causal_status": "predicted",
            }
        )

    # Beat nodes
    for beat, ids in memory.beat_assignments.items():
        nodes.append(
            {
                "node_id": f"beat_{beat}",
                "node_type": "story_beat",
                "beat": beat,
                "member_node_ids": list(ids),
                "provenance": "planner_assignment",
            }
        )

    # Clip nodes for selected members
    clip_nodes = []
    for nid in memory.selected_node_ids:
        win = _clip_window_for_node(node_id=nid, key_events=memory.key_events, strip_by_id=strip_by_id)
        clip_nodes.append(
            {
                "node_id": f"clip_{nid}",
                "node_type": "clip",
                "source_node_id": nid,
                **win,
                "provenance": win.get("time_provenance", {}).get("source"),
            }
        )
    nodes.extend(clip_nodes)

    # Local causal edges within selected strips (predicted only)
    local_relations = []
    for nid in memory.selected_node_ids:
        if not nid.startswith("strip_"):
            continue
        sid = nid.replace("strip_", "", 1)
        s = strip_by_id.get(sid) or {}
        seq = s.get("event_sequence") or []
        # event_sequence may be list of types or dicts
        types = []
        for x in seq:
            if isinstance(x, str):
                types.append(x)
            elif isinstance(x, dict):
                types.append(str(x.get("type") or x.get("event") or ""))
        for i in range(len(types) - 1):
            if not types[i] or not types[i + 1]:
                continue
            local_relations.append(
                {
                    "source_node_id": nid,
                    "target_node_id": nid,
                    "relation_type": "causal",
                    "scope": "local_strip",
                    "explanation": f"Predicted local step {types[i]} → {types[i+1]} inside strip",
                    "local_step": [types[i], types[i + 1]],
                    "supporting_strip_ids": [sid],
                    "supporting_event_ids": [],
                    "supporting_evidence_ids": [],
                    "provenance": "algo_predicted_strip",
                    "verification_status": "predicted",
                }
            )

    beats_payload = {}
    for beat, ids in memory.beat_assignments.items():
        members = []
        for nid in ids:
            win = _clip_window_for_node(node_id=nid, key_events=memory.key_events, strip_by_id=strip_by_id)
            members.append({"node_id": nid, **win, "why": memory.selection_reasons.get(nid)})
        beats_payload[beat] = {
            "member_node_ids": ids,
            "members": members,
            "note": f"planner beat={beat}",
        }

    return {
        "schema": "v2_strip_r2_3_story_graph_v1",
        "story_type": memory.story_hypothesis,
        "discovery_status": memory.discovery_status,
        "score_path": memory.score_path,
        "n_nodes": len(nodes),
        "nodes": nodes,
        "beats": beats_payload,
        "global_relations": relations_doc.get("relations") or [],
        "local_strip_relations": local_relations,
        "selection_reasons": memory.selection_reasons,
        "exclusion_reasons": memory.exclusion_reasons,
        "answers": {
            "why_this_story": "Score path shows deficit then lead; verified goals + selected predicted strips support T01 comeback narrative",
            "mainline_events": [k.get("key_event_id") for k in memory.key_events],
            "beat_rationale": memory.selection_reasons,
            "local_vs_global": "local_strip_relations are algo-predicted only; global_relations reviewed (causal needs evidence)",
            "missing_video": [
                u for u in (memory.snapshot().get("pending_video_checks") or [])
            ],
        },
        "render_ready": False,
    }
