"""Round 2.3 candidate EDL from full story graph selections."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence


def build_r23_candidate_edl(
    *,
    story_graph: Dict[str, Any],
    max_seg_sec: float = 28.0,
    min_seg_sec: float = 4.0,
) -> Dict[str, Any]:
    beats = story_graph.get("beats") or {}
    order = ["setup", "buildup", "turning", "climax", "resolution"]
    segments: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []
    seen = set()
    narr = 0

    # Optional open title card
    segments.append(
        {
            "segment_id": "title_open",
            "beat": "setup",
            "role": "title_card",
            "narrative_order": narr,
            "media_in": None,
            "media_out": None,
            "duration_sec": 2.5,
            "time_status": "title_card",
            "render_eligibility": "placeholder_title",
            "title_text": "Comeback Story Candidate (Internal)",
            "event_ids": [],
            "source_node_ids": [],
            "time_provenance": {"source": "generated_title", "human_confirmed": False},
            "render_ready": False,
        }
    )
    narr += 1

    for beat in order:
        b = beats.get(beat) or {}
        for m in b.get("members") or []:
            nid = m.get("node_id")
            if not nid or nid in seen:
                continue
            seen.add(nid)
            tin, tout = m.get("media_in"), m.get("media_out")
            if tin is None or tout is None:
                segments.append(
                    {
                        "segment_id": f"missing_{nid}",
                        "beat": beat,
                        "role": "missing_clip",
                        "narrative_order": narr,
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
                narr += 1
                continue
            a, b_ = float(tin), float(tout)
            if b_ - a > max_seg_sec:
                b_ = a + max_seg_sec
            if b_ - a < min_seg_sec:
                mid = 0.5 * (a + b_)
                a, b_ = mid - min_seg_sec / 2, mid + min_seg_sec / 2
            seg = {
                "segment_id": f"edl_{narr:02d}_{beat}_{nid}",
                "beat": beat,
                "role": "goal" if nid.startswith("ke_") else "strip_context",
                "narrative_order": narr,
                "edl_index": narr,
                "media_in": round(max(0.0, a), 3),
                "media_out": round(b_, 3),
                "duration_sec": round(b_ - max(0.0, a), 3),
                "time_status": m.get("time_status") or "candidate",
                "render_eligibility": m.get("render_eligibility") or "candidate",
                "source_node_ids": [nid],
                "event_ids": [nid],
                "why": m.get("why"),
                "time_provenance": m.get("time_provenance")
                or {"source": "story_graph", "human_confirmed": False},
                "blocking_reasons": [],
                "render_ready": False,
            }
            segments.append(seg)
            narr += 1

    # Closing title (appended after chronological reorder of cuttable clips)
    title_close = {
        "segment_id": "title_close",
        "beat": "resolution",
        "role": "title_card",
        "narrative_order": narr,
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

    # Keep title cards as bookends; order playable clips by media time to avoid
    # beat-bucket jumps (buildup strip after later climax goal). Beat labels stay.
    open_segs = [s for s in segments if s.get("segment_id") == "title_open"]
    missing = [s for s in segments if s.get("role") == "missing_clip"]
    playable = [s for s in segments if s.get("media_in") is not None]
    playable.sort(key=lambda s: float(s.get("media_in") or 0))
    segments = open_segs + playable + missing + [title_close]
    for i, s in enumerate(segments):
        s["narrative_order"] = i
        if s.get("edl_index") is not None or s.get("media_in") is not None:
            s["edl_index"] = i
        if s.get("segment_id", "").startswith("edl_"):
            beat = s.get("beat") or "x"
            nid = (s.get("source_node_ids") or ["node"])[0]
            s["segment_id"] = f"edl_{i:02d}_{beat}_{nid}"

    # Overlap checks among cuttable segs
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
        "schema": "v2_strip_r2_3_candidate_edl_v1",
        "n_segments": len(segments),
        "n_goal_segments": n_goal,
        "n_non_goal_strip_segments": n_strip,
        "segments": segments,
        # video_renderer preview expects candidate_edl list OR plan.candidate_edl
        "candidate_edl": [
            {
                **s,
                "segment_id": s["segment_id"],
                "narrative_order": s["narrative_order"],
            }
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
            "blocking_issues": [x for x in issues if x.get("issue") == "non_positive_duration"],
        },
        "note": "Full-match story EDL; includes predicted strip context; render_ready=false",
        "render_ready": False,
    }


def edl_to_render_plan(edl: Dict[str, Any], *, qc: bool) -> Dict[str, Any]:
    """Build preview plan for video_renderer.render_story_video."""
    rows = []
    for s in edl.get("segments") or []:
        row = {
            "segment_id": s.get("segment_id"),
            "beat": s.get("beat"),
            "role": s.get("role"),
            "narrative_order": s.get("narrative_order"),
            "edl_index": s.get("edl_index") or s.get("narrative_order"),
            "media_in": s.get("media_in"),
            "media_out": s.get("media_out"),
            "event_ids": s.get("event_ids") or s.get("source_node_ids") or [],
            "time_status": s.get("time_status"),
            "time_provenance": s.get("time_provenance") or {},
            "render_eligibility": s.get("render_eligibility") or "candidate",
            "blocking_reasons": s.get("blocking_reasons") or [],
        }
        if s.get("render_eligibility") == "placeholder_title":
            row["render_eligibility"] = "blocked"  # force placeholder card path
            row["time_status"] = "unavailable"
            row["title_text"] = s.get("title_text")
        if s.get("render_eligibility") == "blocked":
            row["render_eligibility"] = "blocked"
            row["time_status"] = "unavailable"
        rows.append(row)
    return {
        "schema": "v2_r23_render_plan_v1",
        "story_tier": "candidate",
        "render_ready": False,
        "candidate_edl": rows,
        "qc_overlays": qc,
        "diagnostics": {"from": "r2_3_edl"},
    }
