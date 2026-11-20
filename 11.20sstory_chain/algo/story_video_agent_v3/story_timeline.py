"""Story playback timeline ↔ source media PTS mapping (match-agnostic)."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


def _num(x: Any) -> Optional[float]:
    try:
        if x is None or isinstance(x, bool):
            return None
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def edl_rows(obj: Any) -> List[Dict[str, Any]]:
    if isinstance(obj, list):
        return [r for r in obj if isinstance(r, dict)]
    if isinstance(obj, Mapping):
        for k in ("segments", "edl", "rows", "candidate_edl"):
            v = obj.get(k)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
    return []


def active_cut_rows(edl: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in edl:
        if not isinstance(r, dict):
            continue
        if r.get("include_in_cut", True) is False:
            continue
        out.append(dict(r))
    return out


DEFAULT_PLACEHOLDER_SEC = 2.5


def placeholder_duration_sec(row: Mapping[str, Any]) -> float:
    """Match phase5_delivery.render_dual_delivery placeholder timing."""
    v = _num(row.get("placeholder_sec"))
    if v is not None and v > 0:
        return float(v)
    return float(DEFAULT_PLACEHOLDER_SEC)


def build_story_timeline(edl: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Map included EDL rows onto contiguous story playback time.

    Title/placeholder rows with null media windows use explicit placeholder_sec
    (renderer default 2.5s) so story↔MP4 alignment includes non-media cards.
    """
    rows = active_cut_rows(edl)
    timeline: List[Dict[str, Any]] = []
    t = 0.0
    media_sum = 0.0
    placeholder_sum = 0.0
    for i, row in enumerate(rows):
        mi, mo = _num(row.get("media_in")), _num(row.get("media_out"))
        has_media = mi is not None and mo is not None and mo > mi
        if has_media:
            dur = float(mo - mi)
            media_sum += dur
        else:
            dur = placeholder_duration_sec(row)
            placeholder_sum += dur
        entry = {
            "index": i,
            "segment_id": str(row.get("segment_id") or f"seg_{i}"),
            "role": str(row.get("role") or ""),
            "beat": row.get("beat"),
            "story_in": round(t, 3),
            "story_out": round(t + dur, 3),
            "duration_sec": round(dur, 3),
            "media_in": mi,
            "media_out": mo,
            "has_media_window": has_media,
            "is_placeholder": not has_media,
            "placeholder_sec": None if has_media else round(dur, 3),
            "is_replay": row.get("is_replay"),
            "first_live_status": row.get("first_live_status"),
            "shot_kind": row.get("shot_kind"),
        }
        timeline.append(entry)
        t += dur
    return {
        "schema": "v3a_story_timeline_v1",
        "story_duration_sec": round(t, 3),
        "media_duration_sec": round(media_sum, 3),
        "placeholder_duration_sec": round(placeholder_sum, 3),
        "segment_count": len(timeline),
        "media_segment_count": sum(1 for x in timeline if x["has_media_window"]),
        "placeholder_segment_count": sum(1 for x in timeline if x["is_placeholder"]),
        "segments": timeline,
        "note": (
            "story_duration_sec includes placeholder title cards using placeholder_sec "
            "(or renderer default 2.5s). Compare MP4 duration to story_duration_sec, "
            "not media_duration_sec alone."
        ),
    }


def story_time_to_media(
    timeline: Mapping[str, Any],
    story_sec: float,
) -> Optional[Dict[str, Any]]:
    """Locate source media PTS (or placeholder) for a story playback time."""
    segments = timeline.get("segments") or []
    for index, seg in enumerate(segments):
        si, so = float(seg["story_in"]), float(seg["story_out"])
        # A cut seam belongs to the following segment, not the previous one.
        # Half-open intervals prevent claiming frames from the wrong shot.
        final_end = index == len(segments) - 1 and story_sec == so
        if story_sec < si or (story_sec >= so and not final_end):
            continue
        if seg.get("has_media_window"):
            frac = 0.0 if so <= si else (story_sec - si) / (so - si)
            media = float(seg["media_in"]) + frac * (
                float(seg["media_out"]) - float(seg["media_in"])
            )
            return {
                "segment_id": seg["segment_id"],
                "role": seg["role"],
                "story_sec": round(float(story_sec), 3),
                "media_sec": round(media, 3),
                "is_placeholder": False,
                "segment": seg,
            }
        return {
            "segment_id": seg["segment_id"],
            "role": seg["role"],
            "story_sec": round(float(story_sec), 3),
            "media_sec": None,
            "is_placeholder": True,
            "segment": seg,
        }
    return None


def narrative_slot_for_role(role: str) -> str:
    r = str(role or "").lower()
    if "title" in r and ("wrap" in r or "close" in r or "ending" in r):
        return "ending"
    if "wrap" in r or "ending" in r or "close" in r or "aftermath" in r:
        return "ending"
    if "go_ahead" in r or "winner" in r or "climax" in r:
        return "climax"
    if "equalizer" in r:
        return "turn"
    if "buildup" in r or "deficit" in r or "setup" in r or "background" in r:
        return "development"
    if "opponent_opening" in r or "opening" in r or ("title" in r and "open" in r):
        return "opening"
    if "goal_action" in r:
        return "climax"
    return "other"


def aligned_narrative_sample_plan(
    baseline_timeline: Mapping[str, Any],
    candidate_timeline: Mapping[str, Any],
    *,
    changed_segment_ids: Optional[Sequence[str]] = None,
    max_slots: int = 4,
) -> List[Dict[str, Any]]:
    """Plan comparable narrative slots across two cuts (not absolute-second twins).

    Each slot picks a relative position inside matching role-family segments so
    baseline/candidate frames are story-aligned even when durations differ.
    """
    changed = {str(x) for x in (changed_segment_ids or [])}
    preferred = ["opening", "development", "turn", "climax", "ending"]
    slots: List[Dict[str, Any]] = []

    def _first_seg(tl: Mapping[str, Any], slot: str) -> Optional[Dict[str, Any]]:
        for seg in tl.get("segments") or []:
            if narrative_slot_for_role(str(seg.get("role") or "")) == slot:
                return seg
        return None

    for slot in preferred:
        if len(slots) >= max_slots:
            break
        bseg = _first_seg(baseline_timeline, slot)
        cseg = _first_seg(candidate_timeline, slot)
        if not bseg or not cseg:
            continue
        # Midpoint of each segment → comparable narrative position within slot.
        b_t = 0.5 * (float(bseg["story_in"]) + float(bseg["story_out"]))
        c_t = 0.5 * (float(cseg["story_in"]) + float(cseg["story_out"]))
        slots.append({
            "narrative_slot": slot,
            "baseline_story_sec": round(b_t, 3),
            "candidate_story_sec": round(c_t, 3),
            "baseline_segment_id": bseg["segment_id"],
            "candidate_segment_id": cseg["segment_id"],
            "reason": "role_family_midpoint",
        })

    # Prioritize edit boundaries from changed segments.
    for sid in list(changed)[:2]:
        if len(slots) >= max_slots + 2:
            break
        for label, tl in (("baseline", baseline_timeline), ("candidate", candidate_timeline)):
            seg = next(
                (s for s in (tl.get("segments") or []) if s.get("segment_id") == sid),
                None,
            )
            if not seg:
                continue
            # Boundary just inside the segment start.
            t = float(seg["story_in"]) + min(0.4, max(0.1, float(seg["duration_sec"]) * 0.15))
            other_tl = candidate_timeline if label == "baseline" else baseline_timeline
            # Map by narrative slot, not absolute time.
            slot = narrative_slot_for_role(str(seg.get("role") or ""))
            other = _first_seg(other_tl, slot) or seg
            other_t = float(other["story_in"]) + min(
                0.4, max(0.1, float(other.get("duration_sec") or 0.5) * 0.15)
            )
            slots.append({
                "narrative_slot": f"edit_boundary:{slot}",
                "baseline_story_sec": round(t if label == "baseline" else other_t, 3),
                "candidate_story_sec": round(other_t if label == "baseline" else t, 3),
                "baseline_segment_id": sid if label == "baseline" else other.get("segment_id"),
                "candidate_segment_id": other.get("segment_id") if label == "baseline" else sid,
                "reason": "changed_segment_boundary",
                "changed_segment_id": sid,
            })
            break

    # Deduplicate near-identical baseline times
    uniq: List[Dict[str, Any]] = []
    seen_b: List[float] = []
    for s in slots:
        bt = float(s["baseline_story_sec"])
        if any(abs(bt - x) < 0.35 for x in seen_b):
            continue
        seen_b.append(bt)
        uniq.append(s)
    return uniq[: max(2, max_slots + 2)]


def media_window_to_story(
    timeline: Mapping[str, Any],
    media_in: float,
    media_out: float,
) -> Optional[Dict[str, Any]]:
    """Best-effort invert: find timeline segment covering media midpoint."""
    mid = 0.5 * (float(media_in) + float(media_out))
    for seg in timeline.get("segments") or []:
        if not seg.get("has_media_window"):
            continue
        mi, mo = float(seg["media_in"]), float(seg["media_out"])
        if mi - 1e-3 <= mid <= mo + 1e-3:
            return {
                "segment_id": seg["segment_id"],
                "story_in": seg["story_in"],
                "story_out": seg["story_out"],
                "media_in": mi,
                "media_out": mo,
            }
    return None


def protected_goal_segment_ids(edl: Sequence[Mapping[str, Any]]) -> List[str]:
    """Goal-action cuts are default protect-anchors unless evidence overturns."""
    ids: List[str] = []
    for r in active_cut_rows(edl):
        role = str(r.get("role") or "")
        if "goal_action" in role:
            sid = str(r.get("segment_id") or "")
            if sid:
                ids.append(sid)
    return ids


def narrative_beat_coverage(timeline: Mapping[str, Any]) -> Dict[str, Any]:
    """Describe which narrative roles appear on the story timeline (structure only)."""
    roles = [str(s.get("role") or "") for s in (timeline.get("segments") or [])]
    flags = {
        "has_title_open": any("title" in r and "wrap" not in r for r in roles),
        "has_opponent_opening": any("opponent_opening" in r for r in roles),
        "has_deficit_or_setup": any(
            "deficit" in r or "setup" in r or "buildup" in r for r in roles
        ),
        "has_equalizer": any("equalizer_goal" in r for r in roles),
        "has_go_ahead": any("go_ahead_goal" in r for r in roles),
        "has_wrap_or_close": any("wrap" in r or "close" in r or "ending" in r for r in roles),
        "roles": roles,
    }
    return flags
