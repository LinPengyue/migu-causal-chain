"""Observation-only search for NEW information before an existing turning-point action.

This is an optional supplement to broad event ranking. It NEVER confirms
narrative usefulness, FIRST_LIVE, or an edit; no hard-coded match/goal PTS.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from .story_evidence_search import (
    _ACTION_HINTS, _live_credibility, _scores, _type_relevance, event_media_span,
)
from .story_timeline import _num, active_cut_rows


def propose_turning_point_context(
    *,
    edl: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    issue_ids: Optional[Sequence[str]] = None,
    lookback_sec: float = 180.0,
    max_candidates: int = 6,
) -> Dict[str, Any]:
    """Return unverified search priors drawn from the source near story turns.

    Search is generated only for real turning-point roles already present
    in the EDL and directly preceded by a non-goal buildup. It is not
    tied to a specific match, period, score, or event label.
    """
    rows = active_cut_rows(edl)
    targets: List[Dict[str, Any]] = []
    issue_set = {str(x) for x in (issue_ids or [])}
    if not 30.0 <= lookback_sec <= 600.0 or not 1 <= max_candidates <= 20:
        raise ValueError("lookback_sec/max_candidates outside bounded research range")
    occupied = []
    for row in rows:
        a, b = _num(row.get("media_in")), _num(row.get("media_out"))
        if a is not None and b is not None and b > a:
            occupied.append((a, b))
    for index, turn in enumerate(rows):
        role = str(turn.get("role") or "").lower()
        if not any(x in role for x in ("equalizer_goal_action", "turn_goal_action", "comeback_goal_action")):
            continue
        if index < 1:
            continue
        before = rows[index - 1]
        before_role = str(before.get("role") or "").lower()
        if "goal" in before_role or not any(x in before_role for x in ("buildup", "pressure", "setup", "development")):
            continue
        turn_start = _num(turn.get("media_in"))
        before_end = _num(before.get("media_out"))
        if turn_start is None or before_end is None or turn_start <= before_end:
            continue
        # Concentrate on the actual turn neighborhood, not the entire half-hour+
        # source gap that dominated the older heat-score shortlist.
        hi = max(0.0, turn_start - 2.0)
        lo = max(before_end + 1.0, hi - lookback_sec)
        if hi - lo < 8.0:
            continue
        candidates = []
        for event in events:
            span = event_media_span(event)
            if span is None:
                continue
            start, mid, end = span
            if not lo <= mid <= hi:
                continue
            if start < lo or end > hi or end <= start or end - start > 25:
                continue
            live = _live_credibility(event)
            if not live["live_ok"]:
                continue
            # These are unverified; metadata marked LIVE is not broadcast proof.
            if any(end > a and start < b for a, b in occupied):
                continue
            scores = _scores(event)
            relevance = _type_relevance(event, _ACTION_HINTS)
            # Near-turn ranking is intentionally distinct from global heat-only
            # ranking. Relevance/recency are just retrieval priors, not story fit.
            proximity = (mid - lo) / max(hi - lo, 1.0)
            quality_prior = (
                2.0 * proximity + 0.4 * relevance
                + 0.12 * float(scores.get("overall_score") or 0.0)
                + 0.12 * float(scores.get("criticality_score") or 0.0)
            )
            candidates.append({
                "event_id": event.get("event_id"),
                "event_type": event.get("event_type"),
                "source_pts_start": round(start, 3),
                "source_pts_end": round(end, 3),
                "event_t_sec": round(mid, 3),
                "rank_prior": round(quality_prior, 3),
                "live_metadata": live,
                "evidence_tier": "EVENT_PTS_UNVERIFIED",
                "narrative_fit": "NOT_OBSERVED",
                "first_live_status": "UNRESOLVED",
                "why_search": "Potentially informative source footage near an existing story turn; not evidence of needed insertion",
            })
        candidates.sort(key=lambda c: (-c["rank_prior"], c["source_pts_start"]))
        # Avoid duplicate time-overlapping probes, but keep a healthy shortlist.
        selected = []
        for c in candidates:
            start, end = c["source_pts_start"], c["source_pts_end"]
            if any(end > x["source_pts_start"] and start < x["source_pts_end"] for x in selected):
                continue
            selected.append(c)
            if len(selected) >= max_candidates:
                break
        # A non-event-based observation window is still useful if detector
        # coverage is weak. It is NOT a candidate for EDL insertion.
        fallback_mid = 0.5 * (lo + hi)
        targets.append({
            "turn_segment_id": str(turn.get("segment_id") or ""),
            "before_segment_id": str(before.get("segment_id") or ""),
            "related_critic_issue_ids": sorted(x for x in issue_set
                if str(before.get("segment_id") or "") in x
                and str(turn.get("segment_id") or "") in x),
            "source_search_interval": [round(lo, 3), round(hi, 3)],
            "ranked_event_probes": selected,
            "event_count_in_window": len(candidates),
            "fallback_observation_interval": [
                round(max(lo, fallback_mid - 8), 3),
                round(min(hi, fallback_mid + 8), 3),
            ],
            "candidate_action_authorized": False,
            "requires_video_semantics": True,
            "requires_first_live_before_insert": True,
        })
    return {
        "schema": "v3a_proactive_turning_point_search_v1",
        "mode": "OBSERVATION_ONLY",
        "max_candidates_per_turn": max_candidates,
        "lookback_sec": lookback_sec,
        "targets": targets,
        "no_edl_write": True,
        "first_live_certified": False,
        "story_quality_improved": False,
        "note": "Search around turn from real EDL PTS. Candidate event/video semantics and first-live remain unknown. Human causal atoms are DEV-only when supplied upstream.",
    }
