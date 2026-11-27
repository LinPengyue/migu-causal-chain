"""Candidate EDL from verified goal story nodes — render_ready stays false."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


def build_candidate_edl(
    *,
    story_graph: Dict[str, Any],
    pad_pre_sec: float = 1.5,
    pad_post_sec: float = 2.5,
    min_seg_sec: float = 3.0,
    max_seg_sec: float = 18.0,
) -> Dict[str, Any]:
    nodes = list(story_graph.get("nodes") or [])
    beats = story_graph.get("beats") or {}
    segments: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []

    # Prefer beat order for narrative completeness
    beat_order = ["setup", "buildup", "turning", "climax", "resolution"]
    seen_nodes = set()
    ordered_nodes: List[Dict[str, Any]] = []
    for bname in beat_order:
        b = beats.get(bname) or {}
        for nid in b.get("story_node_ids") or []:
            if nid in seen_nodes:
                continue
            node = next((n for n in nodes if n.get("node_id") == nid), None)
            if node:
                ordered_nodes.append(node)
                seen_nodes.add(nid)
    for n in nodes:
        if n.get("node_id") not in seen_nodes:
            ordered_nodes.append(n)

    for i, n in enumerate(ordered_nodes):
        ew = n.get("edit_window") or {}
        t0 = float(ew.get("media_in") or (float(n["media_time_sec"]) - pad_pre_sec))
        t1 = float(ew.get("media_out") or (float(n["media_time_sec"]) + pad_post_sec))
        # Expand short windows slightly; clamp long ones
        if t1 - t0 < min_seg_sec:
            mid = 0.5 * (t0 + t1)
            t0 = mid - min_seg_sec / 2
            t1 = mid + min_seg_sec / 2
        if t1 - t0 > max_seg_sec:
            # Keep action-centered: prefer shot→result span
            shot_t = (n.get("shot_action") or {}).get("media_sec")
            res_t = (n.get("goal_result") or {}).get("media_sec") or n.get("media_time_sec")
            if shot_t is not None and res_t is not None:
                t0 = float(shot_t) - pad_pre_sec
                t1 = float(res_t) + pad_post_sec
            if t1 - t0 > max_seg_sec:
                t1 = t0 + max_seg_sec

        seg = {
            "seg_id": f"edl_{i+1:02d}_{n.get('role_in_t01')}",
            "role": n.get("role_in_t01"),
            "story_node_id": n.get("node_id"),
            "inferred_event_id": n.get("inferred_event_id"),
            "media_in": round(max(0.0, t0), 3),
            "media_out": round(t1, 3),
            "duration_sec": round(t1 - max(0.0, t0), 3),
            "shot_action_media_sec": (n.get("shot_action") or {}).get("media_sec"),
            "goal_result_media_sec": (n.get("goal_result") or {}).get("media_sec"),
            "live_or_replay": n.get("live_or_replay"),
            "linked_strip_chain_id": n.get("linked_strip_chain_id"),
            "verification_status": n.get("verification_status"),
            "time_provenance": {
                "source": "video_verified_edit_window",
                "human_confirmed": False,
            },
            "render_ready": False,
        }
        segments.append(seg)

    # Conflict / duplicate checks
    for i in range(len(segments)):
        a = segments[i]
        if a["media_out"] <= a["media_in"]:
            issues.append({"seg_id": a["seg_id"], "issue": "non_positive_duration"})
        if a.get("live_or_replay") == "replay":
            issues.append({"seg_id": a["seg_id"], "issue": "segment_marked_replay"})
        for j in range(i + 1, len(segments)):
            b = segments[j]
            # overlap
            if a["media_in"] < b["media_out"] and b["media_in"] < a["media_out"]:
                overlap = min(a["media_out"], b["media_out"]) - max(a["media_in"], b["media_in"])
                if overlap > 0.5:
                    issues.append(
                        {
                            "seg_ids": [a["seg_id"], b["seg_id"]],
                            "issue": "temporal_overlap",
                            "overlap_sec": round(overlap, 3),
                        }
                    )
            # near-duplicate centers
            ca = 0.5 * (a["media_in"] + a["media_out"])
            cb = 0.5 * (b["media_in"] + b["media_out"])
            if abs(ca - cb) < 3.0:
                issues.append(
                    {
                        "seg_ids": [a["seg_id"], b["seg_id"]],
                        "issue": "near_duplicate_centers",
                        "delta_sec": round(abs(ca - cb), 3),
                    }
                )

    # Narrative completeness: need deficit + at least one later goal for T01
    roles = {s.get("role") for s in segments}
    completeness = {
        "has_opening_deficit": "opening_deficit" in roles,
        "has_equalizer_or_turning": bool(roles & {"equalizer", "go_ahead", "climax_lead"}),
        "n_segments": len(segments),
        "ok": len(segments) >= 2 and "opening_deficit" in roles,
    }

    gates = {
        "independent_review_passed": False,
        "delivery_gate_passed": False,
        "render_ready": False,
        "blocking_issues": [x for x in issues if x.get("issue") in {"non_positive_duration", "segment_marked_replay"}],
        "warnings": [x for x in issues if x.get("issue") not in {"non_positive_duration", "segment_marked_replay"}],
    }

    return {
        "schema": "v2_strip_r2_2_candidate_edl_v1",
        "n_segments": len(segments),
        "segments": segments,
        "narrative_completeness": completeness,
        "boundary_checks": issues,
        "gates": gates,
        "note": "Internal candidate EDL only; render_ready=false until independent review",
        "render_ready": False,
    }
