"""Missing Goal Detector — score_recognition trajectory vs Goal events / strips.

No gold times, no V1 roles, no match-specific hardcoding.
score_confirmation_time is board observation time, NOT action time.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from story_video_agent.v2_event_adapter import score_transition_anchors

GOAL_TYPES = {"Goal", "goal", "Header_goal", "header_goal", "Own_goal", "own_goal"}


def _is_goal_event(e: Dict[str, Any]) -> bool:
    et = str(e.get("event_type") or "")
    eid = str(e.get("event_type_id") or "").lower()
    return et in GOAL_TYPES or et.lower() in GOAL_TYPES or "goal" in eid


def _pair(v: Any) -> Optional[Tuple[int, int]]:
    if v is None:
        return None
    if isinstance(v, (list, tuple)) and len(v) == 2:
        return int(v[0]), int(v[1])
    return None


def _goals_added(before: Tuple[int, int], after: Tuple[int, int]) -> int:
    return max(0, (after[0] + after[1]) - (before[0] + before[1]))


def _strip_covers_goalish(chain: Dict[str, Any]) -> bool:
    cat = str(chain.get("predicted_category") or chain.get("chain_category") or "")
    last = str(chain.get("last_event") or "")
    first = str(chain.get("first_event") or "")
    tid = str(chain.get("predicted_template_id") or chain.get("template_id") or "")
    if cat == "outcome":
        return True
    if last == "goal" or first == "goal":
        return True
    if "goal" in tid.lower() and "goal_line" not in tid.lower():
        return True
    return False


def build_score_trajectory(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Stable score path from whitelisted score_pair observations."""
    timed = [
        e
        for e in events
        if e.get("score_pair") and e.get("event_time_sec") is not None
    ]
    timed.sort(key=lambda e: float(e["event_time_sec"]))
    points: List[Dict[str, Any]] = []
    prev = None
    for e in timed:
        pair = _pair(e["score_pair"])
        if pair is None:
            continue
        if prev is None or pair != prev:
            points.append(
                {
                    "score": list(pair),
                    "event_id": e["event_id"],
                    "event_time_sec": float(e["event_time_sec"]),
                    "media_start_sec": e.get("media_start_sec"),
                    "media_end_sec": e.get("media_end_sec"),
                    "event_type": e.get("event_type"),
                    "is_replay": e.get("is_replay"),
                    "is_change": prev is not None and pair != prev,
                }
            )
            prev = pair
    anchors = score_transition_anchors(list(events))
    return {
        "schema": "v2_score_trajectory_v1",
        "n_observations_with_score": len(timed),
        "n_unique_states": len(points),
        "points": points,
        "anchors": anchors,
        "note": "Score_Recognition is board state, not proven goal action time",
    }


def _nearby_goal_events(
    events: Sequence[Dict[str, Any]],
    *,
    t0: float,
    t1: float,
) -> List[Dict[str, Any]]:
    out = []
    for e in events:
        if not _is_goal_event(e):
            continue
        t = e.get("event_time_sec")
        if t is None:
            continue
        tf = float(t)
        if t0 - 5.0 <= tf <= t1 + 30.0:
            out.append(e)
    return out


def _nearby_strips(
    strips: Sequence[Dict[str, Any]],
    *,
    center_sec: float,
    pad_sec: float,
) -> List[str]:
    ids: List[str] = []
    for c in strips:
        t0 = c.get("t0_sec")
        t1 = c.get("t1_sec")
        if t0 is None or t1 is None:
            continue
        mid = 0.5 * (float(t0) + float(t1))
        if abs(mid - center_sec) <= pad_sec or (
            float(t0) - pad_sec <= center_sec <= float(t1) + pad_sec
        ):
            if _strip_covers_goalish(c):
                ids.append(str(c.get("strip_chain_id") or c.get("clip_id")))
    return ids


def _candidate_event_ids(
    events: Sequence[Dict[str, Any]],
    *,
    t0: float,
    t1: float,
) -> List[str]:
    prefer = {"Goal", "Shot", "Save", "Corner_kick", "Pass", "Kick_off"}
    nearby = []
    for e in events:
        t = e.get("event_time_sec")
        if t is None:
            continue
        tf = float(t)
        if t0 <= tf <= t1:
            nearby.append(e)
    nearby.sort(
        key=lambda e: (
            0 if e.get("event_type") in prefer else 1,
            abs(float(e["event_time_sec"]) - t1),
        )
    )
    return [str(e["event_id"]) for e in nearby[:12]]


def _search_region(
    *,
    prev_t: Optional[float],
    confirm_t: float,
    duration_hint: Optional[float] = None,
    initial_deficit: bool = False,
) -> Dict[str, Any]:
    """Adaptive coarse-to-fine search region from score times only (no fixed 90/150)."""
    if initial_deficit:
        # No proven 0:0 observation — search before confirmation, do not invent exact time.
        end = float(confirm_t)
        # Use half the confirmation time as a soft horizon, capped generically.
        span = min(max(end * 0.5, 60.0), 600.0)
        start = max(0.0, end - span)
        phases = []
        n = 3 if (end - start) > 180 else 2
        step = (end - start) / n
        for i in range(n):
            phases.append(
                {
                    "phase": f"coarse_{i}",
                    "start_sec": round(start + i * step, 3),
                    "end_sec": round(start + (i + 1) * step, 3),
                }
            )
        return {
            "search_start_sec": round(start, 3),
            "search_end_sec": round(end, 3),
            "basis": "before_first_nonzero_score_no_00_observed",
            "phases": phases,
            "invented_exact_action_time": False,
        }

    start = float(prev_t) if prev_t is not None else max(0.0, float(confirm_t) - 180.0)
    end = float(confirm_t)
    if end <= start:
        start = max(0.0, end - 120.0)
    gap = end - start
    # Split gap into adaptive phases; denser near confirmation.
    if gap <= 90:
        phases = [
            {"phase": "full_gap", "start_sec": round(start, 3), "end_sec": round(end, 3)},
            {
                "phase": "near_confirm",
                "start_sec": round(max(start, end - max(20.0, gap * 0.35)), 3),
                "end_sec": round(end, 3),
            },
        ]
    else:
        thirds = gap / 3.0
        phases = [
            {
                "phase": "early_third",
                "start_sec": round(start, 3),
                "end_sec": round(start + thirds, 3),
            },
            {
                "phase": "mid_third",
                "start_sec": round(start + thirds, 3),
                "end_sec": round(start + 2 * thirds, 3),
            },
            {
                "phase": "late_third_near_confirm",
                "start_sec": round(start + 2 * thirds, 3),
                "end_sec": round(end, 3),
            },
            {
                "phase": "refine_tail",
                "start_sec": round(max(start, end - min(45.0, gap * 0.25)), 3),
                "end_sec": round(end, 3),
            },
        ]
    return {
        "search_start_sec": round(start, 3),
        "search_end_sec": round(end, 3),
        "gap_sec": round(gap, 3),
        "basis": "between_prev_score_obs_and_confirmation",
        "phases": phases,
        "invented_exact_action_time": False,
        "duration_hint": duration_hint,
    }


def detect_missing_goals(
    *,
    events: Sequence[Dict[str, Any]],
    predicted_strips: Optional[Sequence[Dict[str, Any]]] = None,
    match_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Emit missing_goal_candidate rows for uncovered score increases."""
    strips = list(predicted_strips or [])
    traj = build_score_trajectory(events)
    points = traj["points"]
    candidates: List[Dict[str, Any]] = []
    covered: List[Dict[str, Any]] = []

    # Initial deficit: first observed score is already non-zero without 0:0.
    if points:
        first = points[0]
        fs = tuple(first["score"])
        if fs != (0, 0) and (fs[0] + fs[1]) >= 1:
            goals = _nearby_goal_events(
                events, t0=0.0, t1=float(first["event_time_sec"])
            )
            nearby_strips = _nearby_strips(
                strips, center_sec=float(first["event_time_sec"]), pad_sec=120.0
            )
            # Only count strips that end before/near confirmation as covering.
            covered_by_strip = bool(nearby_strips)
            if goals or covered_by_strip:
                covered.append(
                    {
                        "kind": "initial_nonzero_score",
                        "score_after": list(fs),
                        "score_confirmation_time": first["event_time_sec"],
                        "covering_goal_event_ids": [g["event_id"] for g in goals],
                        "covering_strip_ids": nearby_strips,
                    }
                )
            else:
                region = _search_region(
                    prev_t=None,
                    confirm_t=float(first["event_time_sec"]),
                    initial_deficit=True,
                )
                candidates.append(
                    {
                        "schema": "v2_missing_goal_candidate_v1",
                        "candidate_id": "mg_initial_deficit_0",
                        "kind": "initial_deficit_pending",
                        "score_before": None,
                        "score_after": list(fs),
                        "score_confirmation_time": float(first["event_time_sec"]),
                        "previous_score_observation_time": None,
                        "confirmation_event_id": first["event_id"],
                        "candidate_event_ids": _candidate_event_ids(
                            events, t0=region["search_start_sec"], t1=region["search_end_sec"]
                        ),
                        "nearby_predicted_strip_ids": nearby_strips,
                        "search_region": region,
                        "search_status": "pending_video",
                        "note": (
                            "First scoreboard observation is already non-zero; "
                            "no explicit 0:0 observation — do not invent exact action time"
                        ),
                        "verification_status": "unresolved",
                        "render_ready": False,
                    }
                )

    # Transitions between consecutive unique score states
    for i in range(1, len(points)):
        prev_p, cur_p = points[i - 1], points[i]
        before = tuple(prev_p["score"])
        after = tuple(cur_p["score"])
        added = _goals_added(before, after)
        if added <= 0:
            continue
        # Replay-tagged confirmation: still a candidate, but flag for careful verify.
        t_prev = float(prev_p["event_time_sec"])
        t_conf = float(cur_p["event_time_sec"])
        goals = _nearby_goal_events(events, t0=t_prev, t1=t_conf)
        nearby_goalish_strips = _nearby_strips(strips, center_sec=t_conf, pad_sec=90.0)
        # Also check strips whose window overlaps (t_prev, t_conf]
        for c in strips:
            if not _strip_covers_goalish(c):
                continue
            t0, t1 = c.get("t0_sec"), c.get("t1_sec")
            if t0 is None or t1 is None:
                continue
            if float(t1) < t_prev - 5 or float(t0) > t_conf + 30:
                continue
            sid = str(c.get("strip_chain_id") or c.get("clip_id"))
            if sid not in nearby_goalish_strips:
                nearby_goalish_strips.append(sid)

        if goals:
            covered.append(
                {
                    "kind": "score_change_covered_by_goal_event",
                    "score_before": list(before),
                    "score_after": list(after),
                    "score_confirmation_time": t_conf,
                    "previous_score_observation_time": t_prev,
                    "covering_goal_event_ids": [g["event_id"] for g in goals],
                    "covering_strip_ids": nearby_goalish_strips,
                }
            )
            continue
        if nearby_goalish_strips:
            covered.append(
                {
                    "kind": "score_change_covered_by_predicted_strip",
                    "score_before": list(before),
                    "score_after": list(after),
                    "score_confirmation_time": t_conf,
                    "previous_score_observation_time": t_prev,
                    "covering_goal_event_ids": [],
                    "covering_strip_ids": nearby_goalish_strips,
                    "note": "Strip is predicted only — still unverified action",
                }
            )
            # Still emit a soft candidate so video can confirm action time;
            # mark as strip_hypothesis_present.
            region = _search_region(prev_t=t_prev, confirm_t=t_conf)
            candidates.append(
                {
                    "schema": "v2_missing_goal_candidate_v1",
                    "candidate_id": f"mg_trans_{i}_strip_hyp",
                    "kind": "score_change_strip_hypothesis",
                    "score_before": list(before),
                    "score_after": list(after),
                    "score_confirmation_time": t_conf,
                    "previous_score_observation_time": t_prev,
                    "confirmation_event_id": cur_p["event_id"],
                    "confirmation_is_replay": cur_p.get("is_replay"),
                    "candidate_event_ids": _candidate_event_ids(
                        events, t0=region["search_start_sec"], t1=region["search_end_sec"]
                    ),
                    "nearby_predicted_strip_ids": nearby_goalish_strips,
                    "search_region": region,
                    "search_status": "pending_video_confirm_strip",
                    "goals_added": added,
                    "verification_status": "unresolved",
                    "render_ready": False,
                }
            )
            continue

        region = _search_region(prev_t=t_prev, confirm_t=t_conf)
        candidates.append(
            {
                "schema": "v2_missing_goal_candidate_v1",
                "candidate_id": f"mg_trans_{i}",
                "kind": "score_change_missing_goal",
                "score_before": list(before),
                "score_after": list(after),
                "score_confirmation_time": t_conf,
                "previous_score_observation_time": t_prev,
                "confirmation_event_id": cur_p["event_id"],
                "confirmation_is_replay": cur_p.get("is_replay"),
                "candidate_event_ids": _candidate_event_ids(
                    events, t0=region["search_start_sec"], t1=region["search_end_sec"]
                ),
                "nearby_predicted_strip_ids": nearby_goalish_strips,
                "search_region": region,
                "search_status": "pending_video",
                "goals_added": added,
                "verification_status": "unresolved",
                "render_ready": False,
            }
        )

    return {
        "schema": "v2_missing_goal_detector_v1",
        "match_id": match_id,
        "trajectory": traj,
        "missing_goal_candidates": candidates,
        "covered_transitions": covered,
        "n_missing": len(candidates),
        "n_covered": len(covered),
        "forbidden_inputs": [
            "*_causal.json",
            "strip_gold.json",
            "V1 goal times",
            "match-specific hardcoded times",
        ],
        "render_ready": False,
    }
