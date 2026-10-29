"""Round 2.4 EDL — distinguish source_media_order vs narrative_order."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def build_r24_candidate_edl(
    *,
    story_graph: Dict[str, Any],
    playout_policy: str = "prefer_match_timeline",
    max_seg_sec: float = 22.0,
    min_seg_sec: float = 5.0,
    goal_pre_pad_sec: float = 8.0,
    goal_post_pad_sec: float = 3.0,
) -> Dict[str, Any]:
    """Build candidate EDL.

    - source_media_order: ascending by media_in (match timeline)
    - narrative_order: story playback order
      * prefer_match_timeline (default for T01): same as source_media_order among playable clips
      * planner_narrative: beat bucket order from Story Graph without force-sort by media time
    """
    beats = story_graph.get("beats") or {}
    beat_order = ["setup", "buildup", "turning", "climax", "resolution"]
    issues: List[Dict[str, Any]] = []
    seen = set()
    playable: List[Dict[str, Any]] = []

    title_open = {
        "segment_id": "title_open",
        "beat": "setup",
        "role": "title_card",
        "media_in": None,
        "media_out": None,
        "duration_sec": 2.5,
        "time_status": "title_card",
        "render_eligibility": "placeholder_title",
        "title_text": "Comeback Story R2.4 Candidate (Internal)",
        "event_ids": [],
        "source_node_ids": [],
        "time_provenance": {"source": "generated_title", "human_confirmed": False},
        "render_ready": False,
    }
    title_close = {
        "segment_id": "title_close",
        "beat": "resolution",
        "role": "title_card",
        "media_in": None,
        "media_out": None,
        "duration_sec": 2.0,
        "time_status": "title_card",
        "render_eligibility": "placeholder_title",
        "title_text": "End — render_ready=false",
        "event_ids": [],
        "source_node_ids": [],
        "time_provenance": {"source": "generated_title", "human_confirmed": False},
        "render_ready": False,
    }

    for beat in beat_order:
        for m in (beats.get(beat) or {}).get("members") or []:
            nid = m.get("node_id")
            if not nid or nid in seen:
                continue
            seen.add(nid)
            tin, tout = m.get("media_in"), m.get("media_out")
            if tin is None or tout is None:
                playable.append(
                    {
                        "segment_id": f"missing_{nid}",
                        "beat": beat,
                        "role": "missing_clip",
                        "media_in": None,
                        "media_out": None,
                        "time_status": "unavailable",
                        "render_eligibility": "blocked",
                        "blocking_reasons": ["missing_time_window"],
                        "source_node_ids": [nid],
                        "event_ids": [],
                        "title_text": f"镜头待定位: {nid}",
                        "why": m.get("why"),
                        "render_ready": False,
                    }
                )
                continue
            a, b = float(tin), float(tout)
            is_goal = str(nid).startswith("ke_")
            if is_goal:
                # Prefer verified shot/result span already in graph; clamp length
                if b - a > max_seg_sec + goal_pre_pad_sec:
                    # keep end, trim start
                    a = max(a, b - (max_seg_sec + 2.0))
            else:
                if b - a > max_seg_sec:
                    b = a + max_seg_sec
            if b - a < min_seg_sec:
                mid = 0.5 * (a + b)
                a, b = mid - min_seg_sec / 2, mid + min_seg_sec / 2
            playable.append(
                {
                    "segment_id": f"seg_{nid}",
                    "beat": beat,
                    "role": "goal" if is_goal else "strip_context",
                    "media_in": round(max(0.0, a), 3),
                    "media_out": round(b, 3),
                    "duration_sec": round(b - max(0.0, a), 3),
                    "time_status": m.get("time_status") or "candidate",
                    "render_eligibility": m.get("render_eligibility") or "candidate",
                    "source_node_ids": [nid],
                    "event_ids": [nid],
                    "why": m.get("why"),
                    "time_provenance": m.get("time_provenance")
                    or {"source": "story_graph", "human_confirmed": False},
                    "blocking_reasons": [],
                    "planner_beat_rank": beat_order.index(beat),
                    "render_ready": False,
                }
            )

    # source_media_order among timed clips
    timed = [s for s in playable if s.get("media_in") is not None]
    timed_by_media = sorted(timed, key=lambda s: float(s["media_in"]))
    for i, s in enumerate(timed_by_media):
        s["source_media_order"] = i

    missing = [s for s in playable if s.get("media_in") is None]

    if playout_policy == "planner_narrative":
        # Keep beat-bucket insertion order (already collected in beat_order)
        narr_body = [s for s in playable if s.get("media_in") is not None]
    else:
        # T01 default: match timeline playback (does NOT erase beat labels)
        narr_body = list(timed_by_media)

    segments: List[Dict[str, Any]] = [title_open] + narr_body + missing + [title_close]
    for i, s in enumerate(segments):
        s["narrative_order"] = i
        s["edl_index"] = i
        if s.get("segment_id", "").startswith("seg_") or s.get("role") in {"goal", "strip_context"}:
            beat = s.get("beat") or "x"
            nid = (s.get("source_node_ids") or ["node"])[0]
            s["segment_id"] = f"edl_{i:02d}_{beat}_{nid}"

    # Overlaps on playback order
    cuttable = [s for s in segments if s.get("media_in") is not None]
    for i in range(len(cuttable)):
        for j in range(i + 1, len(cuttable)):
            a, b = cuttable[i], cuttable[j]
            ov = min(a["media_out"], b["media_out"]) - max(a["media_in"], b["media_in"])
            if ov > 1.0:
                issues.append(
                    {
                        "issue": "temporal_overlap",
                        "seg_ids": [a["segment_id"], b["segment_id"]],
                        "overlap_sec": round(ov, 3),
                    }
                )

    n_goal = sum(1 for s in segments if s.get("role") == "goal")
    n_strip = sum(1 for s in segments if s.get("role") == "strip_context")
    return {
        "schema": "v2_strip_r2_4_candidate_edl_v1",
        "playout_policy": playout_policy,
        "n_segments": len(segments),
        "n_goal_segments": n_goal,
        "n_non_goal_strip_segments": n_strip,
        "segments": segments,
        "candidate_edl": [
            {**s, "segment_id": s["segment_id"], "narrative_order": s["narrative_order"]}
            for s in segments
            if s.get("media_in") is not None
            or s.get("render_eligibility") in {"blocked", "placeholder_title"}
        ],
        "boundary_checks": issues,
        "gates": {
            "independent_review_passed": False,
            "delivery_gate_passed": False,
            "render_ready": False,
            "has_non_goal_context": n_strip > 0,
            "ordering": {
                "source_media_order_defined": True,
                "narrative_order_defined": True,
                "playout_policy": playout_policy,
            },
        },
        "note": "R2.4 EDL separates source_media_order from narrative_order; render_ready=false",
        "render_ready": False,
    }
