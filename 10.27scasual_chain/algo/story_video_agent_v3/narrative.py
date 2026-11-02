"""V3-P2 narrative beat assembly for T01 last-deficit arcs.

Builds a V1-compatible story_view with explicit 铺垫/蓄力/转折/高潮/收尾
coverage. Goal beats may be narrative_placeholder (unresolved) without
fabricated goal_action times. Buildup must come from predicted strips ∩ raw LIVE.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from story_video_agent.v2_strip_reinfer import norm_type

from .pipeline import CRITICAL, SOURCE

# Editorial preference for 蓄力 (not causal claims — ranking only).
_BUILDUP_PRIORITY = (
    "shot", "射门", "header", "头球", "cross", "传中", "chance", "威胁",
    "save", "扑救", "dribble", "breakthrough", "突破", "key_pass", "关键传球",
)
_BUILDUP_LOW = (
    "throw_in", "掷界外球", "ball_possession", "控球", "pass", "传球",
    "foul", "犯规", "defensive_action", "防守",
)


def _score_list(raw: Any) -> Optional[List[int]]:
    if isinstance(raw, str) and ":" in raw:
        a, b = raw.split(":", 1)
        return [int(a), int(b)]
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        return [int(raw[0]), int(raw[1])]
    return None


def _buildup_rank(event_type: Optional[str]) -> int:
    t = norm_type(event_type or "")
    low_t = str(event_type or "").lower()
    for i, key in enumerate(_BUILDUP_PRIORITY):
        if key in t or key in low_t:
            return i
    for j, key in enumerate(_BUILDUP_LOW):
        if key in t or key in low_t:
            return 100 + j
    return 50


def select_editorial_buildup(
    predicted: Dict[str, Any],
    arc: Dict[str, Any],
    *,
    allowed_events: Sequence[Dict[str, Any]],
    max_n: int = 5,
) -> List[Dict[str, Any]]:
    """Rank LIVE predicted-strip events in deficit→equalizer for editorial 蓄力.

    Temporal co-occurrence only — never invents causal edges.
    """
    t0 = (arc.get("score_confirmation_sec") or {}).get("deficit")
    t1 = (arc.get("score_confirmation_sec") or {}).get("equalizer")
    if t0 is None or t1 is None:
        return []
    known = {str(e["event_id"]): e for e in allowed_events if e.get("event_id")}
    candidates: List[Dict[str, Any]] = []
    for chain in predicted.get("causal_chains") or []:
        label = str(chain.get("predicted_label") or "").lower()
        if any(w in label for w in ("进球", "破门", "入网", "goal")):
            continue
        start = float(chain["t0_ms"]) / 1000.0
        # Strictly after deficit board, strictly before equalizer board
        if not (float(t0) < start < float(t1) - 1.0):
            continue
        for e in chain.get("events") or []:
            eid = str(e.get("event_id") or "")
            if not eid or eid not in known:
                continue
            raw = known[eid]
            if raw.get("is_replay") is not False:
                continue
            if str(raw.get("broadcast_phase") or "").upper() != "LIVE":
                continue
            source_t = raw.get("event_time_sec")
            if source_t is None:
                continue
            t_ms = e.get("t_ms")
            if t_ms is None:
                t_ms = int(round(float(source_t) * 1000.0))
            if abs(float(t_ms) / 1000.0 - float(source_t)) > 5.0:
                continue
            if not (float(t0) < float(source_t) < float(t1) - 1.0):
                continue
            et = str(e.get("type") or raw.get("event_type") or "")
            if norm_type(et) != norm_type(raw.get("event_type")):
                continue
            candidates.append({
                "event_id": eid,
                "type": et,
                "t_ms": int(t_ms),
                "story_role": "蓄力",
                "source": "predicted_causal",
                "source_chain_id": chain.get("chain_id"),
                "prediction_source": SOURCE,
                "prediction_confidence": chain.get("confidence"),
                "verification_status": "unverified",
                "is_replay": False,
                "time_provenance": "unverified_predicted_event",
                "raw_broadcast_phase": "LIVE",
                "broadcast_phase_source": "raw_event_video_context",
                "temporal_consistency_checked": True,
                "editorial_rank": _buildup_rank(et),
                "causal_claim": False,
                "note": "Editorial candidate from predicted strip ∩ LIVE raw event; not a causal edge",
            })
    # Prefer higher editorial value, then spread chronologically among top pool
    candidates.sort(key=lambda x: (int(x["editorial_rank"]), float(x["t_ms"])))
    # Dedup by event_id keeping best rank
    uniq: Dict[str, Dict[str, Any]] = {}
    for c in candidates:
        prev = uniq.get(c["event_id"])
        if prev is None or int(c["editorial_rank"]) < int(prev["editorial_rank"]):
            uniq[c["event_id"]] = c
    ranked = sorted(uniq.values(), key=lambda x: (int(x["editorial_rank"]), float(x["t_ms"])))
    # Take a pool then chronologically diversify
    pool = ranked[: max(max_n * 3, max_n)]
    pool.sort(key=lambda x: float(x["t_ms"]))
    if len(pool) <= max_n:
        chosen = pool
    else:
        idx = [round(i * (len(pool) - 1) / (max_n - 1)) for i in range(max_n)]
        chosen = [pool[i] for i in idx]
    # Drop pure low-value if we still have higher-value alternatives in pool
    high = [c for c in chosen if int(c["editorial_rank"]) < 100]
    if len(high) >= max(2, max_n // 2):
        # refill from high-value chronologically if needed
        high_all = [c for c in pool if int(c["editorial_rank"]) < 100]
        if len(high_all) >= max_n:
            idx = [round(i * (len(high_all) - 1) / (max_n - 1)) for i in range(max_n)]
            chosen = [high_all[i] for i in idx]
    return sorted(chosen, key=lambda x: float(x["t_ms"]))


def _narrative_goal_placeholder(
    *,
    role: str,
    beat: str,
    score_before: Optional[List[int]],
    score_after: Optional[List[int]],
    score_confirmation_sec: Optional[float],
) -> Dict[str, Any]:
    return {
        "event_id": f"v3_narrative_placeholder_{role}",
        "type": "narrative_placeholder_goal",
        "story_role": beat,
        "critical_goal_role": role,
        "narrative_placeholder": True,
        "t_ms": None,
        "goal_action_sec": None,
        "media_in": None,
        "media_out": None,
        "score_before": score_before,
        "score_after": score_after,
        "score_confirmation_sec": score_confirmation_sec,
        "verification_status": "unresolved",
        "time_provenance": "scoreboard_confirmation_only_not_goal_action",
        "prediction_source": None,
        "source": "v3_narrative_placeholder",
        "is_replay": False,
        "note": "Story-role placeholder only; forbidden as verified goal action PTS",
        "render_ready": False,
    }


def _ending_placeholder(
    *,
    final_score: Optional[List[int]],
    final_score_t: Optional[float],
    go_ahead_t: Optional[float],
) -> Dict[str, Any]:
    return {
        "event_id": "v3_narrative_placeholder_ending",
        "type": "narrative_placeholder_final_score",
        "story_role": "收尾",
        "narrative_placeholder": True,
        "t_ms": int(round(float(final_score_t) * 1000.0)) if final_score_t is not None else None,
        "goal_action_sec": None,
        "final_score": final_score,
        "score_confirmation_sec": final_score_t,
        "full_time_verified": False,
        "whistle_verified": False,
        "verification_status": "unresolved",
        "time_provenance": "final_score_path_pending_visual_qc",
        "source": "v3_narrative_placeholder",
        "is_replay": False,
        "ending_policy": "conservative_score_wrap_not_whistle",
        "duplicate_of_go_ahead_board": bool(
            final_score_t is not None and go_ahead_t is not None
            and abs(float(final_score_t) - float(go_ahead_t)) <= 1.0
        ),
        "note": "Conservative ending: final-score narrative pending review; no fabricated full-time whistle",
        "render_ready": False,
    }


def build_t01_story_view(
    *,
    match_id: str,
    score_path: Sequence[Dict[str, Any]],
    arc_pack: Dict[str, Any],
    buildup: Sequence[Dict[str, Any]],
    opening_score_before: Optional[List[int]] = None,
) -> Dict[str, Any]:
    arc = arc_pack.get("selected_arc")
    if not arc:
        return {
            "schema_version": "v3_v1_story_view_v1",
            "match_id": match_id,
            "story_tier": "none",
            "is_candidate": False,
            "has_story": False,
            "protagonist_side": None,
            "recognition": {"tier": "none", "present": False,
                            "beats": {"铺垫": [], "蓄力": [], "转折": [], "高潮": [], "收尾": []}},
            "score_path": list(score_path),
            "events": [],
            "no_story_reason": arc_pack.get("status"),
            "render_ready": False,
        }
    side = arc.get("protagonist_side")
    anchors = arc.get("score_confirmation_sec") or {}
    deficit = list(arc.get("deficit_score") or [])
    equalizer = list(arc.get("equalizer_score") or [])
    go_ahead = list(arc.get("go_ahead_score") or [])

    placeholders = [
        _narrative_goal_placeholder(
            role="opening_deficit", beat="铺垫",
            score_before=opening_score_before, score_after=deficit,
            score_confirmation_sec=anchors.get("deficit"),
        ),
        _narrative_goal_placeholder(
            role="equalizer", beat="转折",
            score_before=deficit, score_after=equalizer,
            score_confirmation_sec=anchors.get("equalizer"),
        ),
        _narrative_goal_placeholder(
            role="go_ahead", beat="高潮",
            score_before=equalizer, score_after=go_ahead,
            score_confirmation_sec=anchors.get("go_ahead"),
        ),
    ]
    final_node = list(score_path)[-1] if score_path else None
    final_score = _score_list((final_node or {}).get("score"))
    final_t = (final_node or {}).get("t_sec")
    ending = _ending_placeholder(
        final_score=final_score,
        final_score_t=float(final_t) if final_t is not None else None,
        go_ahead_t=anchors.get("go_ahead"),
    )

    events: List[Dict[str, Any]] = list(placeholders) + list(buildup) + [ending]
    beats = {
        "铺垫": [placeholders[0]["event_id"]],
        "蓄力": [b["event_id"] for b in buildup],
        "转折": [placeholders[1]["event_id"]],
        "高潮": [placeholders[2]["event_id"]],
        "收尾": [ending["event_id"]],
    }
    return {
        "schema_version": "v3_v1_story_view_v1",
        "match_id": match_id,
        "story_tier": "candidate",
        "is_candidate": True,
        "has_story": True,
        "story_semantic_complete": True,  # role coverage; NOT evidence/render complete
        "protagonist_side": side,
        "protagonist_team_name": arc.get("protagonist_team_name"),
        "selected_arc_scores": {
            "deficit": deficit, "equalizer": equalizer, "go_ahead": go_ahead,
        },
        "recognition": {
            "tier": "candidate",
            "protagonist_side": side,
            "present": True,
            "beats": beats,
            "beat_status": {
                "铺垫": "narrative_placeholder_unresolved_goal",
                "蓄力": "predicted_strip_live_candidates",
                "转折": "narrative_placeholder_unresolved_goal",
                "高潮": "narrative_placeholder_unresolved_goal",
                "收尾": "conservative_final_score_pending_qc",
            },
        },
        "score_path": list(score_path),
        "events": events,
        "no_story_reason": None,
        "note": (
            "T01 last-deficit narrative assembled for V1 planner. "
            "Goal beats are unresolved placeholders; buildup is predicted∩LIVE only."
        ),
        "render_ready": False,
    }


def narrative_completeness_report(
    *,
    story: Dict[str, Any],
    plan: Dict[str, Any],
    edl: Sequence[Dict[str, Any]],
    predicted: Dict[str, Any],
    buildup: Sequence[Dict[str, Any]],
    tasks: Dict[str, Any],
) -> Dict[str, Any]:
    beats = ((story.get("recognition") or {}).get("beats") or {})
    role_coverage = {
        beat: {"n_ids": len(beats.get(beat) or []), "ids": list(beats.get(beat) or [])}
        for beat in ("铺垫", "蓄力", "转折", "高潮", "收尾")
    }
    plan_segs = plan.get("segments") or []
    plan_beats = sorted({str(s.get("beat")) for s in plan_segs if s.get("beat")})
    predicted_participating = {
        b.get("source_chain_id") for b in buildup if b.get("source_chain_id")
    }
    goal_slots = [x for x in edl if x.get("critical_goal_role")]
    editable = []
    blocked = []
    for row in edl:
        if row.get("include_in_cut") and row.get("media_in") is not None and row.get("media_out") is not None:
            if row.get("render_eligibility") not in {"blocked", "blocked_unresolved"} and not row.get("scoreboard_only"):
                editable.append(row.get("segment_id") or row.get("role"))
                continue
        if row.get("critical_goal_role") or row.get("media_in") is None:
            blocked.append({
                "id": row.get("segment_id") or row.get("role"),
                "reason": row.get("verification_status") or row.get("render_eligibility") or "no_media",
            })
        elif row.get("scoreboard_only") or "scoreboard" in str(row.get("role") or ""):
            blocked.append({
                "id": row.get("segment_id") or row.get("role"),
                "reason": "scoreboard_only_not_goal_action",
            })
        elif row.get("blocking_reasons") or row.get("render_eligibility") in {"blocked", "candidate_only"}:
            blocked.append({
                "id": row.get("segment_id") or row.get("role"),
                "reason": (row.get("blocking_reasons") or [row.get("render_eligibility")])[0]
                if isinstance(row.get("blocking_reasons"), list) and row.get("blocking_reasons")
                else row.get("render_eligibility") or "candidate_not_cuttable",
            })

    evidence_complete = all(
        t.get("status") == "resolved" or t.get("verification_status") == "verified_first_live"
        for t in (tasks.get("tasks") or [])
    )
    semantic_pass = all(role_coverage[b]["n_ids"] > 0 for b in role_coverage)
    structure_pass = bool(plan.get("structure_ok") or (plan.get("diagnostics") or {}).get("structure_ok")
                          or plan_segs)
    # predicted chain participation: must appear in plan buildup segments
    plan_buildup_eids = {
        eid
        for s in plan_segs if s.get("beat") == "蓄力"
        for eid in (s.get("event_ids") or [])
    }
    buildup_in_plan = [b["event_id"] for b in buildup if b["event_id"] in plan_buildup_eids]

    return {
        "schema": "v3_narrative_completeness_v1",
        "role_coverage": role_coverage,
        "role_coverage_complete": semantic_pass,
        "plan_beats_present": plan_beats,
        "predicted_chain_participation": {
            "n_predicted_chains": predicted.get("n_predicted_chains"),
            "n_buildup_candidates": len(buildup),
            "n_distinct_source_chains": len(predicted_participating),
            "source_chain_ids": sorted(predicted_participating),
            "buildup_event_ids_in_plan": buildup_in_plan,
            "predicted_strips_reach_v1_plan": len(buildup_in_plan) > 0,
        },
        "evidence_integrity": {
            "n_critical_tasks": len(tasks.get("tasks") or []),
            "n_unresolved_tasks": sum(
                1 for t in (tasks.get("tasks") or [])
                if t.get("status") == "unresolved" or t.get("verification_status") == "unresolved"
            ),
            "goal_placeholders": [
                {
                    "role": g.get("critical_goal_role"),
                    "media_in": g.get("media_in"),
                    "goal_action_sec": g.get("goal_action_sec"),
                    "score_confirmation_sec": g.get("score_confirmation_sec"),
                    "verification_status": g.get("verification_status"),
                }
                for g in goal_slots
            ],
            "evidence_complete": evidence_complete,
        },
        "cuttability": {
            "editable_segment_ids": editable,
            "blocked_or_pending": blocked,
            "any_critical_goal_cuttable": False,
            "render_ready": False,
        },
        "gates": {
            "graph_structure_pass": bool(structure_pass),
            "story_semantic_pass": bool(semantic_pass and len(buildup_in_plan) > 0),
            "critical_video_evidence_pass": False,
        },
        "verdict": (
            "narrative_roles_ready_evidence_pending"
            if semantic_pass and len(buildup_in_plan) > 0
            else "narrative_incomplete"
        ),
        "render_ready": False,
    }
