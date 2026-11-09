"""Active source-footage search for story gaps (match-agnostic).

When Critic flags thin buildup / abrupt transitions / weak endings, search the
raw match event chain (and optional causal atoms) for LIVE candidate windows
with real source PTS — never invent timestamps or hard-code match clocks.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .story_timeline import _num, active_cut_rows, protected_goal_segment_ids

SCHEMA = "v3a_story_evidence_search_v1"

# Narrative-useful LIVE event families (English + common zh labels). Match-agnostic.
_ACTION_HINTS = (
    "shot", "save", "chance", "cross", "tackle", "dribble", "header", "block",
    "clearance", "corner", "free_kick", "freekick", "foul", "card", "offside",
    "aerial", "defensive", "attack", "pass", "possession", "throw", "interception",
    "射", "扑", "传", "角", "任意", "抢", "解围", "犯规", "头球", "突破", "机会",
)

_ENDING_HINTS = (
    "celebration", "shot", "save", "foul", "substitution", "aerial", "free_kick",
    "defensive", "pass", "possession", "庆祝", "换人", "犯规", "扑", "射",
)

_MAX_CANDIDATES_PER_ISSUE = 5
_MIN_SPAN = 3.0
_MAX_SPAN = 18.0
_DEFAULT_SPAN = 8.0


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_match_events(
    match_json: Optional[Path] = None,
    events_json: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Load event rows from match delivery JSON or enriched events file."""
    paths = [p for p in (events_json, match_json) if p is not None]
    for path in paths:
        if not path.is_file():
            continue
        raw = _load_json(path)
        if isinstance(raw, list):
            return [e for e in raw if isinstance(e, dict)]
        if isinstance(raw, Mapping):
            for key in ("events", "rows", "enriched_events"):
                rows = raw.get(key)
                if isinstance(rows, list):
                    return [e for e in rows if isinstance(e, dict)]
    return []


def event_media_span(event: Mapping[str, Any]) -> Optional[Tuple[float, float, float]]:
    """Return (start, event_t, end) in source media seconds, or None."""
    mt = event.get("media_time") if isinstance(event.get("media_time"), Mapping) else {}
    start = _num(mt.get("start_time_sec"))
    mid = _num(mt.get("event_time_sec"))
    end = _num(mt.get("end_time_sec"))
    if mid is None:
        mid = _num(event.get("media_pts")) or _num(event.get("pts_sec")) or _num(event.get("t_sec"))
    if start is None and mid is not None:
        start = mid - 2.0
    if end is None and mid is not None:
        end = mid + 4.0
    if mid is None or start is None or end is None:
        return None
    if end <= start:
        end = start + _DEFAULT_SPAN
    return float(start), float(mid), float(end)


def _live_credibility(event: Mapping[str, Any]) -> Dict[str, Any]:
    vc = event.get("video_context") if isinstance(event.get("video_context"), Mapping) else {}
    phase = str(vc.get("broadcast_phase") or "").upper()
    is_replay = vc.get("is_replay") in (True, "true", "True", 1)
    is_slow = vc.get("is_slow_motion") in (True, "true", "True", 1)
    live_ok = (phase == "LIVE" or phase == "") and not is_replay and not is_slow
    conf = 0.85 if phase == "LIVE" and live_ok else (0.45 if live_ok else 0.1)
    return {
        "live_ok": bool(live_ok),
        "broadcast_phase": phase or None,
        "is_replay": bool(is_replay),
        "is_slow_motion": bool(is_slow),
        "live_confidence": conf,
        "replay_of_event_id": vc.get("replay_of_event_id"),
    }


def _scores(event: Mapping[str, Any]) -> Dict[str, float]:
    sc = event.get("scores") if isinstance(event.get("scores"), Mapping) else {}
    out = {}
    for k in ("overall_score", "emotional_heat_score", "criticality_score"):
        v = _num(sc.get(k))
        if v is not None:
            out[k] = float(v)
    return out


def _type_relevance(event: Mapping[str, Any], hints: Sequence[str]) -> float:
    blob = " ".join(
        str(event.get(k) or "")
        for k in ("event_type", "event_type_zh", "comment_label")
    ).lower()
    hits = sum(1 for h in hints if h.lower() in blob)
    return float(min(3.0, hits))


def _clamp_span(start: float, end: float) -> Tuple[float, float]:
    if end - start < _MIN_SPAN:
        mid = 0.5 * (start + end)
        start, end = mid - _DEFAULT_SPAN / 2.0, mid + _DEFAULT_SPAN / 2.0
    if end - start > _MAX_SPAN:
        mid = 0.5 * (start + end)
        start, end = mid - _MAX_SPAN / 2.0, mid + _MAX_SPAN / 2.0
    return round(start, 3), round(end, 3)


def _goal_windows(edl: Sequence[Mapping[str, Any]]) -> List[Tuple[float, float, str]]:
    out: List[Tuple[float, float, str]] = []
    for r in active_cut_rows(edl):
        if "goal_action" not in str(r.get("role") or ""):
            continue
        mi, mo = _num(r.get("media_in")), _num(r.get("media_out"))
        if mi is None or mo is None or mo <= mi:
            continue
        out.append((float(mi), float(mo), str(r.get("segment_id") or "")))
    return out


def _overlaps_goal(start: float, end: float, goals: Sequence[Tuple[float, float, str]]) -> Optional[str]:
    for gi, go, sid in goals:
        if end > gi - 1.0 and start < go + 1.0:
            return sid
    return None


def _row_by_id(edl: Sequence[Mapping[str, Any]], sid: str) -> Optional[Dict[str, Any]]:
    for r in edl:
        if str(r.get("segment_id") or "") == sid:
            return dict(r)
    return None


def search_window_for_issue(
    issue: Mapping[str, Any],
    edl: Sequence[Mapping[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Derive a source-PTS search interval from issue + adjacent EDL rows."""
    cat = str(issue.get("category") or "")
    sids = [str(x) for x in (issue.get("segment_ids") or []) if x]
    goals = _goal_windows(edl)

    if cat in ("transition", "buildup"):
        if len(sids) >= 2:
            a = _row_by_id(edl, sids[0])
            b = _row_by_id(edl, sids[1])
        elif len(sids) == 1:
            # sparse bridge: search before the turn/target segment
            b = _row_by_id(edl, sids[0])
            a = None
            rows = active_cut_rows(edl)
            for i, r in enumerate(rows):
                if str(r.get("segment_id")) == sids[0] and i > 0:
                    a = dict(rows[i - 1])
                    break
        else:
            return None
        if not a or not b:
            return None
        a_out, b_in = _num(a.get("media_out")), _num(b.get("media_in"))
        if a_out is None or b_in is None or b_in - a_out < 8.0:
            return None
        return {
            "kind": "bridge_between_cuts",
            "lo": float(a_out) + 1.0,
            "hi": float(b_in) - 1.0,
            "insert_after_segment_id": str(a.get("segment_id")),
            "before_segment_id": str(b.get("segment_id")),
            "narrative_function": "supplement_buildup_or_transition_bridge",
            "role": "buildup_bridge_action",
            "hints": _ACTION_HINTS,
        }

    if cat == "ending":
        # Prefer window after last goal_action up to (and slightly past) first aftermath scoreboard.
        last_goal = None
        for r in active_cut_rows(edl):
            if "goal_action" in str(r.get("role") or ""):
                last_goal = r
        if last_goal is None:
            return None
        g_out = _num(last_goal.get("media_out"))
        if g_out is None:
            return None
        # Stay inside (goal_out, next_scoreboard_in) so inserts before the scoreboard
        # cannot reverse source PTS order relative to that neighbor.
        hi = float(g_out) + 90.0
        insert_before = None
        for r in active_cut_rows(edl):
            mi = _num(r.get("media_in"))
            role = str(r.get("role") or "")
            if mi is not None and mi >= g_out - 1e-6 and (
                "scoreboard" in role or "wrap" in role or "aftermath" in role
            ):
                # Clamp hi strictly before the following scoreboard/wrap cut.
                hi = min(hi, float(mi) - 0.5)
                insert_before = str(r.get("segment_id"))
                break
        if hi - (float(g_out) + 1.0) < 6.0:
            # No usable aftermath gap before scoreboard; widen by inserting after
            # the scoreboard instead (caller still uses insert_after last_goal only
            # when a gap exists — otherwise skip this ending search window).
            return None
        return {
            "kind": "post_climax_aftermath",
            "lo": float(g_out) + 1.0,
            "hi": float(hi),
            "insert_after_segment_id": str(last_goal.get("segment_id")),
            "before_segment_id": insert_before,
            "narrative_function": "extend_ending_closure",
            "role": "ending_closure_action",
            "hints": _ENDING_HINTS,
        }

    if cat in ("narrative_order", "redundancy", "replay_risk", "narrative_causality"):
        # Reorder/drop/replace — search may still propose replacements for dropped material.
        return {
            "kind": "structure_repair",
            "lo": None,
            "hi": None,
            "insert_after_segment_id": sids[0] if sids else None,
            "before_segment_id": None,
            "narrative_function": f"structure_repair:{cat}",
            "role": None,
            "hints": (),
            "structure_only": True,
            "segment_ids": sids,
        }

    return None


def _rank_events_in_window(
    events: Sequence[Mapping[str, Any]],
    *,
    lo: float,
    hi: float,
    hints: Sequence[str],
    goals: Sequence[Tuple[float, float, str]],
    occupied: Sequence[Tuple[float, float]],
    max_candidates: Optional[int] = _MAX_CANDIDATES_PER_ISSUE,
) -> List[Dict[str, Any]]:
    ranked: List[Dict[str, Any]] = []
    for ev in events:
        span = event_media_span(ev)
        if span is None:
            continue
        start0, mid, end0 = span
        if not (lo < mid < hi):
            continue
        live = _live_credibility(ev)
        if not live["live_ok"]:
            continue
        start, end = _clamp_span(start0, end0)
        # Keep candidate fully inside search window when possible.
        start = max(start, lo)
        end = min(end, hi)
        if end - start < _MIN_SPAN:
            continue
        if _overlaps_goal(start, end, goals):
            continue
        if any(end > a and start < b for a, b in occupied):
            continue
        sc = _scores(ev)
        rel = _type_relevance(ev, hints)
        score = (
            float(sc.get("overall_score") or 0.0)
            + float(sc.get("emotional_heat_score") or 0.0)
            + float(sc.get("criticality_score") or 0.0) * 0.5
            + rel
            + live["live_confidence"]
        )
        mid_c = (start + end) / 2.0
        gap = max(hi - lo, 1.0)
        # Prefer bridges that reduce the *larger residual* source jump (gap balance),
        # not merely proximity to the destination cut (that bias selected late-gap
        # heat events that still leave a huge early residual — real-run 3504s).
        residual_max = max(mid_c - lo, hi - mid_c)
        gap_balance = max(0.0, 1.0 - (residual_max / gap))
        # Stronger than single criticality half-point / end-proximity so event heat
        # near the destination cut cannot dominate a bridge that still leaves a
        # huge residual jump (real-run 3504 bias).
        score += gap_balance * 2.0
        # Mild preference for material nearer the later beat (destination), weaker
        # than gap_balance so heat+end-proximity cannot dominate alone.
        proximity_hi = 1.0 - abs(mid_c - hi) / gap
        score += max(0.0, proximity_hi) * 0.15
        # Large-gap risk: candidate still leaves >15min residual on either side.
        risks = _candidate_risks(ev, live, start, end, goals)
        if gap >= 900.0 and residual_max >= 900.0:
            risks.append("large_residual_source_jump")
            score -= 1.25
        ranked.append(
            {
                "candidate_id": f"cand_{ev.get('event_id') or f'{mid:.1f}'}_{int(start)}",
                "event_id": ev.get("event_id"),
                "event_type": ev.get("event_type"),
                "event_type_zh": ev.get("event_type_zh"),
                "source_pts_start": round(start, 3),
                "source_pts_end": round(end, 3),
                "event_t_sec": round(mid, 3),
                "live": live,
                "scores": sc,
                "type_relevance": rel,
                "confidence": round(min(0.99, score / 12.0), 3),
                "rank_score": round(score, 3),
                "gap_balance": round(gap_balance, 3),
                "residual_max_sec": round(residual_max, 3),
                "search_gap_sec": round(gap, 3),
                "risks": risks,
                "evidence_tier": EVIDENCE_TIER_EVENT_PTS,
                "story_defect_fit": {
                    "gap_balance": round(gap_balance, 3),
                    "residual_max_sec": round(residual_max, 3),
                    "proximity_to_destination": round(max(0.0, proximity_hi), 3),
                    "rationale": (
                        "Ranks by event scores + type hints + how evenly the candidate "
                        "splits the diagnosed source gap; does not prove causal story value."
                    ),
                },
            }
        )
    ranked.sort(key=lambda x: (-float(x["rank_score"]), float(x["source_pts_start"])))
    if max_candidates is None:
        # Exhaustive mode: preserve overlapping alternatives until the caller
        # checks first-broadcast evidence and prior feedback. Otherwise a
        # high-heat but unverified event can erase an attested nearby segment.
        return ranked
    # Legacy direct-call mode: dedup overlapping windows (keep highest score).
    kept: List[Dict[str, Any]] = []
    for c in ranked:
        s, e = float(c["source_pts_start"]), float(c["source_pts_end"])
        if any(e > float(k["source_pts_start"]) and s < float(k["source_pts_end"]) for k in kept):
            continue
        kept.append(c)
        # None means retrieve all non-overlapping evidence candidates.
        # The agent must validate evidence + filter prior failures BEFORE truncation.
        if max_candidates is not None and len(kept) >= max_candidates:
            break
    return kept


def _candidate_risks(
    event: Mapping[str, Any],
    live: Mapping[str, Any],
    start: float,
    end: float,
    goals: Sequence[Tuple[float, float, str]],
) -> List[str]:
    risks: List[str] = []
    if live.get("live_confidence", 0) < 0.7:
        risks.append("live_phase_uncertain")
    near = _overlaps_goal(start - 5.0, end + 5.0, goals)
    if near:
        risks.append(f"near_goal_window:{near}")
    et = str(event.get("event_type") or "").lower()
    if "goal" in et and "action" not in et:
        risks.append("goal_labeled_event_not_used_as_goal_action")
    if end - start > 15.0:
        risks.append("long_clip")
    return risks


# Explicit evidence tiers — never collapse event-chain LIVE into first-broadcast.
EVIDENCE_TIER_EVENT_PTS = "EVENT_PTS_CANDIDATE"
EVIDENCE_TIER_FIRST_LIVE = "FIRST_LIVE_VERIFIED"


def verify_search_candidate(
    candidate: Mapping[str, Any],
    *,
    edl: Sequence[Mapping[str, Any]],
    min_confidence: float = 0.25,
) -> Dict[str, Any]:
    """Event-chain PTS/LIVE gate only — NOT authenticated first-broadcast proof."""
    start = _num(candidate.get("source_pts_start"))
    end = _num(candidate.get("source_pts_end"))
    live = candidate.get("live") if isinstance(candidate.get("live"), Mapping) else {}
    reasons: List[str] = []
    if start is None or end is None or end - start < _MIN_SPAN:
        reasons.append("invalid_span")
    if not live.get("live_ok"):
        reasons.append("not_live")
    if live.get("is_replay") or live.get("is_slow_motion"):
        reasons.append("replay_or_slowmo")
    if float(candidate.get("confidence") or 0.0) < min_confidence:
        reasons.append("low_confidence")
    goals = _goal_windows(edl)
    hit = _overlaps_goal(float(start or 0), float(end or 0), goals) if start is not None else "no_span"
    if hit:
        reasons.append(f"overlaps_protected_goal:{hit}")
    ok = not reasons
    return {
        "ok": ok,
        "reasons": reasons,
        "verified_source_pts_start": start if ok else None,
        "verified_source_pts_end": end if ok else None,
        "method": "event_chain_live_credibility",
        "evidence_tier": EVIDENCE_TIER_EVENT_PTS,
        "note": (
            "EVENT_PTS_CANDIDATE = event metadata + LIVE label + source PTS. "
            "Not FIRST_LIVE_VERIFIED broadcast-timeline attestation."
        ),
    }


def _apply_feedback_to_candidates(
    verified: Sequence[Mapping[str, Any]],
    feedback_context: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Penalize same-context overlapping PTS; never permanently ban a window."""
    if not feedback_context:
        return {
            "verified_candidates": list(verified),
            "feedback_filtered_candidates": [],
            "feedback_filter_applied": False,
        }
    from .story_revision_feedback import should_penalize_candidate

    records = list(feedback_context.get("records") or [])
    if not records and feedback_context.get("summary"):
        # summary-only context: rebuild minimal memory from tried_revisions
        for t in (feedback_context.get("summary") or {}).get("tried_revisions") or []:
            if isinstance(t, dict):
                records.append(
                    {
                        "action": t.get("action"),
                        "source_pts": t.get("source_pts"),
                        "failure_class": t.get("failure_class") or "UNCERTAIN_OR_UNVERIFIED",
                        "issue_signature": t.get("issue_signature") or {"category": "transition"},
                        "evidence_token": t.get("evidence_token"),
                    }
                )
        # Also fold uncertain_or_unverified rows (carry full signatures).
        for t in (feedback_context.get("summary") or {}).get("uncertain_or_unverified") or []:
            if isinstance(t, dict) and t.get("source_pts"):
                records.append(dict(t))
    kept: List[Dict[str, Any]] = []
    filtered: List[Dict[str, Any]] = []
    for c in verified:
        if not isinstance(c, dict):
            continue
        sig = {
            # Prefer diagnosis category; story_role aliases handled in feedback.
            "category": c.get("category") or c.get("story_role") or "transition",
            "anchor_segment_ids": [
                x
                for x in (c.get("insert_after_segment_id"), c.get("before_segment_id"))
                if x
            ],
            "missing_narrative_info": c.get("missing_narrative_info"),
            "issue_id_raw": c.get("issue_id"),
        }
        # Never pass candidate_id as evidence_token — it would falsely unlock retries.
        tok = c.get("evidence_token")
        from .story_revision_feedback import is_observation_grade_evidence_token

        decision = should_penalize_candidate(
            records,
            issue_signature=sig,
            action="search_add",
            source_pts=[c.get("source_pts_start"), c.get("source_pts_end")],
            new_evidence_token=tok if is_observation_grade_evidence_token(tok) else None,
        )
        if decision.get("suppress"):
            filtered.append({**c, "feedback_skip": decision})
            continue
        # Novelty / alternate-function boost as ranking prior only
        row = dict(c)
        row["feedback_novelty_bonus"] = 0.15 if not filtered else 0.05
        kept.append(row)
    kept.sort(
        key=lambda r: (
            float(r.get("feedback_novelty_bonus") or 0.0)
            + float(r.get("rank_score") or r.get("score") or r.get("relevance") or 0.0)
        ),
        reverse=True,
    )
    return {
        "verified_candidates": kept,
        "feedback_filtered_candidates": filtered,
        "feedback_filter_applied": True,
        "feedback_store_n": len(records),
    }


def _annotate_first_live_tier(
    candidate: Dict[str, Any],
    *,
    evidence_store: Optional[Mapping[str, Any]],
    source_sha: Optional[str],
) -> Dict[str, Any]:
    """Attach first-live attestation status without promoting event LIVE labels."""
    row = dict(candidate)
    row.setdefault("evidence_tier", EVIDENCE_TIER_EVENT_PTS)
    row["first_live_status"] = "NOT_VERIFIED"
    row["first_live_available"] = False
    row["executable_safe_revision"] = False
    start = _num(row.get("source_pts_start"))
    end = _num(row.get("source_pts_end"))
    by_key = (evidence_store or {}).get("by_key") if isinstance(evidence_store, Mapping) else None
    if not source_sha or start is None or end is None or not isinstance(by_key, dict):
        row["reject_or_defer_reason"] = "event_pts_only_pending_first_live_attestation"
        return row
    from .first_live_window_evidence import (
        validate_first_live_evidence_record,
        window_key,
    )

    key = window_key(str(source_sha), float(start), float(end))
    pack = by_key.get(key)
    if not isinstance(pack, dict):
        row["reject_or_defer_reason"] = "no_first_live_evidence_pack_for_window"
        return row
    # The Search pre-apply gate must enforce the SAME source/frame/timeline proof
    # as the post-edit ledger. A string first_live_status is not certification.
    validation = validate_first_live_evidence_record(
        pack,
        source_sha=str(source_sha),
        pts_start=float(start),
        pts_end=float(end),
        require_files_exist=True,
    )
    row["first_live_key"] = key
    row["first_live_available"] = True
    row["first_live_validation"] = {
        k: validation.get(k)
        for k in ("ok", "binding_valid", "binding_status", "first_live_verified",
                  "replay_confirmed", "reason", "method", "manifest_digest")
    }
    if validation.get("replay_confirmed"):
        row["first_live_status"] = "REPLAY_CONFIRMED"
        row["reject_or_defer_reason"] = "replay_confirmed_by_timeline_review"
    elif (validation.get("ok") and validation.get("binding_valid")
          and validation.get("first_live_verified")):
        row["first_live_status"] = EVIDENCE_TIER_FIRST_LIVE
        row["evidence_tier"] = EVIDENCE_TIER_FIRST_LIVE
        row["executable_safe_revision"] = True
        row["reject_or_defer_reason"] = None
    else:
        # Keep an unbound positive review visible for diagnostics only; it is not
        # a certified first-broadcast segment and must never reach apply.
        row["first_live_status"] = "NOT_VERIFIED"
        row["review_claimed_first_live_status"] = validation.get("first_live_status")
        row["reject_or_defer_reason"] = (
            "first_live_evidence_validation_failed:"
            + str(validation.get("reason") or validation.get("method") or "incomplete")
        )
    return row


def build_candidate_selection_diagnostics(
    candidates: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Reviewer-readable ranked table (no match-specific hardcoding)."""
    rows: List[Dict[str, Any]] = []
    for i, c in enumerate(candidates or []):
        if not isinstance(c, dict):
            continue
        rows.append(
            {
                "rank": i + 1,
                "candidate_id": c.get("candidate_id"),
                "issue_id": c.get("issue_id"),
                "story_role": c.get("role"),
                "event_type": c.get("event_type"),
                "source_pts": [c.get("source_pts_start"), c.get("source_pts_end")],
                "rank_score": c.get("rank_score"),
                "gap_balance": c.get("gap_balance"),
                "residual_max_sec": c.get("residual_max_sec"),
                "evidence_tier": c.get("evidence_tier"),
                "first_live_status": c.get("first_live_status"),
                "first_live_available": c.get("first_live_available"),
                "first_live_validation": c.get("first_live_validation"),
                "executable_safe_revision": bool(c.get("executable_safe_revision")),
                "causal_transition_rationale": (c.get("story_defect_fit") or {}).get("rationale"),
                "reject_or_defer_reason": c.get("reject_or_defer_reason")
                or ((c.get("feedback_skip") or {}).get("reason")),
                "risks": list(c.get("risks") or []),
            }
        )
    return rows


def run_story_evidence_search(
    *,
    diagnosis: Mapping[str, Any],
    edl: Sequence[Mapping[str, Any]],
    match_json: Optional[Path] = None,
    events_json: Optional[Path] = None,
    max_issues: int = 4,
    already_searched_issue_ids: Optional[Sequence[str]] = None,
    feedback_context: Optional[Mapping[str, Any]] = None,
    first_live_evidence_store: Optional[Mapping[str, Any]] = None,
    narrative_fit_evidence_store: Optional[Mapping[str, Any]] = None,
    source_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Critic issues → search targets → ranked EVENT_PTS candidates with PTS.

    first_live_evidence_store annotates FIRST_LIVE_VERIFIED when available; event
    LIVE labels alone never make a candidate executable_safe_revision.
    feedback_context is optional (default None) for Phase 8; legacy callers unchanged.
    """
    from .story_narrative_fit import annotate_narrative_fit

    events = load_match_events(match_json=match_json, events_json=events_json)
    goals = _goal_windows(edl)
    occupied = [(g[0], g[1]) for g in goals]
    for r in active_cut_rows(edl):
        mi, mo = _num(r.get("media_in")), _num(r.get("media_out"))
        if mi is not None and mo is not None and mo > mi:
            occupied.append((float(mi), float(mo)))

    skip = set(already_searched_issue_ids or [])
    searchable_cats = {
        "transition", "buildup", "ending", "narrative_order",
        "redundancy", "replay_risk", "narrative_causality",
    }
    issues = [
        i for i in (diagnosis.get("issues") or [])
        if isinstance(i, dict)
        and str(i.get("category") or "") in searchable_cats
        and str(i.get("issue_id") or "") not in skip
    ]
    # Prefer needs_video_verify / major+ first.
    def _prio(iss: Mapping[str, Any]) -> Tuple[int, int]:
        sev = {"critical": 0, "major": 1, "minor": 2}.get(str(iss.get("severity")), 3)
        suf = 0 if iss.get("evidence_sufficiency") == "needs_video_verify" else 1
        return (suf, sev)

    issues = sorted(issues, key=_prio)[: max(1, max_issues)]

    targets: List[Dict[str, Any]] = []
    all_candidates: List[Dict[str, Any]] = []
    verified: List[Dict[str, Any]] = []
    verified_before_feedback: List[Dict[str, Any]] = []
    feedback_filtered: List[Dict[str, Any]] = []

    for iss in issues:
        win = search_window_for_issue(iss, edl)
        if win is None:
            targets.append(
                {
                    "issue_id": iss.get("issue_id"),
                    "category": iss.get("category"),
                    "status": "no_search_window",
                }
            )
            continue
        if win.get("structure_only"):
            targets.append(
                {
                    "issue_id": iss.get("issue_id"),
                    "category": iss.get("category"),
                    "status": "structure_repair_no_footage_search",
                    "search_window": win,
                    "candidates": [],
                }
            )
            continue
        lo, hi = float(win["lo"]), float(win["hi"])
        if hi - lo < 6.0:
            targets.append(
                {
                    "issue_id": iss.get("issue_id"),
                    "category": iss.get("category"),
                    "status": "search_window_too_small",
                    "search_window": win,
                }
            )
            continue
        # Retrieve broadly: the first five highest-heat events may ALL be
        # unauthenticated or previously rejected, hiding an actionable candidate
        # outside the raw score top five. Limit only after proof and feedback.
        cands = _rank_events_in_window(
            events,
            lo=lo,
            hi=hi,
            hints=list(win.get("hints") or _ACTION_HINTS),
            goals=goals,
            occupied=occupied,
            max_candidates=None,
        )
        enriched: List[Dict[str, Any]] = []
        local_eligible: List[Dict[str, Any]] = []
        for c in cands:
            row = {
                **c,
                "issue_id": iss.get("issue_id"),
                "category": iss.get("category"),
                "narrative_function": win.get("narrative_function"),
                "role": win.get("role"),
                "insert_after_segment_id": win.get("insert_after_segment_id"),
                "before_segment_id": win.get("before_segment_id"),
                "search_window": {"lo": lo, "hi": hi, "kind": win.get("kind")},
                "event_association": {
                    "event_id": c.get("event_id"),
                    "event_type": c.get("event_type"),
                },
                "visual_evidence": {
                    "kind": "event_chain_live_context",
                    "live": c.get("live"),
                    "note": "Event metadata candidate only; first broadcast needs source-video proof.",
                },
            }
            gate = verify_search_candidate(row, edl=edl)
            row["evidence_verification"] = gate
            enriched.append(row)
            all_candidates.append(row)
            if gate.get("ok"):
                first_live_row = _annotate_first_live_tier(
                    row,
                    evidence_store=first_live_evidence_store,
                    source_sha=source_sha256,
                )
                local_eligible.append(annotate_narrative_fit(
                    first_live_row,
                    source_sha=source_sha256,
                    edl=edl,
                    evidence_store=narrative_fit_evidence_store,
                ))
        # Feedback must see the *entire* candidate pool, not only raw top five.
        # This lets a lower-ranked verified alternative survive a failed high-heat
        # candidate without any hardcoded match or candidate IDs.
        verified_before_feedback.extend(local_eligible)
        filtered_here = _apply_feedback_to_candidates(local_eligible, feedback_context)
        feedback_filtered.extend(filtered_here.get("feedback_filtered_candidates") or [])
        # Narrative rejection from bound triplet review is a negative, not a
        # generic PTS ban. Unknown fit is proposal-only at the production gate.
        fit_filtered = [
            c for c in (filtered_here.get("verified_candidates") or [])
            if not c.get("narrative_fit_rejects_insert")
        ]
        ranked_safe_first = sorted(
            fit_filtered,
            key=lambda r: (
                1 if (r.get("executable_safe_revision") and
                      r.get("narrative_fit_supports_insert")) else 0,
                1 if r.get("executable_safe_revision") else 0,
                float(r.get("feedback_novelty_bonus") or 0.0)
                + float(r.get("rank_score") or 0.0),
            ),
            reverse=True,
        )
        selected_here = []
        for c in ranked_safe_first:
            start_c, end_c = float(c["source_pts_start"]), float(c["source_pts_end"])
            if any(end_c > a and start_c < b for a, b in occupied):
                continue
            selected_here.append(c)
            occupied.append((start_c, end_c))
            if len(selected_here) >= _MAX_CANDIDATES_PER_ISSUE:
                break
        verified.extend(selected_here)
        targets.append(
            {
                "issue_id": iss.get("issue_id"),
                "category": iss.get("category"),
                "status": "candidates_found" if enriched else "no_credible_candidates",
                "search_window": win,
                # Return the actionable shortlist, while retaining the complete
                # inspected pool and feedback-filtered rows in the top-level report.
                "candidates": selected_here,
                "n_candidates_considered": len(enriched),
                "n_event_candidates_eligible": len(local_eligible),
                "n_feedback_filtered": len(filtered_here.get("feedback_filtered_candidates") or []),
                "n_narrative_fit_rejected": sum(
                    1 for c in (filtered_here.get("verified_candidates") or [])
                    if c.get("narrative_fit_rejects_insert")
                ),
                "n_narrative_fit_supported": sum(
                    1 for c in selected_here if c.get("narrative_fit_supports_insert")
                ),
                "verified_count": len(selected_here),
                "n_first_live_executable": sum(
                    1 for c in selected_here if c.get("executable_safe_revision")
                ),
            }
        )

    verified_out = sorted(
        verified,
        key=lambda r: (
            1 if (r.get("executable_safe_revision") and
                  r.get("narrative_fit_supports_insert")) else 0,
            1 if r.get("executable_safe_revision") else 0,
            float(r.get("feedback_novelty_bonus") or 0.0)
            + float(r.get("rank_score") or 0.0),
        ),
        reverse=True,
    )
    executable = [c for c in verified_out if c.get("executable_safe_revision")]
    propose_only = [c for c in verified_out if not c.get("executable_safe_revision")]
    diagnostics = build_candidate_selection_diagnostics(verified_out)
    return {
        "schema": SCHEMA,
        "events_loaded": len(events),
        "match_json": str(match_json) if match_json else None,
        "events_json": str(events_json) if events_json else None,
        "protected_goal_segment_ids": protected_goal_segment_ids(edl),
        "targets": targets,
        "candidates": all_candidates,
        "verified_candidates": verified_out,
        "verified_candidates_before_feedback": verified_before_feedback,
        "feedback_filtered_candidates": feedback_filtered,
        "feedback_filter_applied": bool(feedback_context),
        "executable_first_live_candidates": executable,
        "narrative_fit_supported_candidates": [
            c for c in executable if c.get("narrative_fit_supports_insert")
        ],
        "narrative_fit_review_required_candidates": [
            c for c in verified_out if not c.get("narrative_fit_supports_insert")
        ],
        "propose_only_event_pts_candidates": propose_only,
        "selection_diagnostics": diagnostics,
        "search_success": bool(verified_out),
        "executable_search_success": bool(executable),
        "note": (
            "Search uses event-chain LIVE credibility and real media_time PTS "
            "(evidence_tier=EVENT_PTS_CANDIDATE). FIRST_LIVE_VERIFIED comes only from "
            "authenticated per-window broadcast-timeline attestation. "
            "Feedback context may suppress same-context overlaps without permanent PTS bans. "
            "Narrative fit requires distinct before/candidate/after video evidence; "
            "event heat and source-gap balance are NOT story quality proxies. "
            "No match-specific timestamps or fixed goal counts."
        ),
    }


def search_candidates_to_observations(
    search_report: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Convert FIRST_LIVE-executable search hits into apply observations.

    EVENT_PTS_CANDIDATE rows are intentionally excluded so apply cannot bind
    uncertified windows even if a stale search_add intent leaks through.
    """
    obs: List[Dict[str, Any]] = []
    pool = list(search_report.get("executable_first_live_candidates") or [])
    if not pool:
        pool = [
            c
            for c in (search_report.get("verified_candidates") or [])
            if isinstance(c, dict) and c.get("executable_safe_revision")
        ]
    for c in pool:
        if not isinstance(c, dict):
            continue
        gate = c.get("evidence_verification") or {}
        if not gate.get("ok"):
            continue
        start = float(c["source_pts_start"])
        end = float(c["source_pts_end"])
        mid = 0.5 * (start + end)
        req = f"search:{c.get('candidate_id')}"
        obs.append(
            {
                "ok": True,
                "request_id": req,
                "issue_id": c.get("issue_id"),
                "anchor_id": f"search:{c.get('candidate_id')}",
                "window": {"start": start, "end": end},
                "allowed_windows": [{"start": start, "end": end, "anchor_id": f"search:{c.get('candidate_id')}"}],
                "frames": [
                    {
                        "frame_id": f"{req}:f0",
                        "actual_media_sec": round(start + 0.5, 3),
                    },
                    {
                        "frame_id": f"{req}:f1",
                        "actual_media_sec": round(mid, 3),
                    },
                    {
                        "frame_id": f"{req}:f2",
                        "actual_media_sec": round(end - 0.5, 3),
                    },
                ],
                "vlm": {
                    "supports_bound_segment": True,
                    "live_or_replay": "live",
                    "candidate_goal_action_span": {"start": start, "end": end},
                    "search_verified": True,
                    "event_id": c.get("event_id"),
                },
                "search_candidate": c,
            }
        )
    return obs
