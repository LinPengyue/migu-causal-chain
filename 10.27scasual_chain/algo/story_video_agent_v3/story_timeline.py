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


def build_story_timeline(edl: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Map included EDL rows onto contiguous story playback time.

    Title/placeholder rows with null media windows are kept as zero-duration
    (or tagged placeholder) so segment_id order is preserved for diagnosis.
    """
    rows = active_cut_rows(edl)
    timeline: List[Dict[str, Any]] = []
    t = 0.0
    for i, row in enumerate(rows):
        mi, mo = _num(row.get("media_in")), _num(row.get("media_out"))
        has_media = mi is not None and mo is not None and mo > mi
        dur = float(mo - mi) if has_media else 0.0
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
            "is_replay": row.get("is_replay"),
            "first_live_status": row.get("first_live_status"),
            "shot_kind": row.get("shot_kind"),
        }
        timeline.append(entry)
        t += dur
    return {
        "schema": "v3a_story_timeline_v1",
        "story_duration_sec": round(t, 3),
        "segment_count": len(timeline),
        "media_segment_count": sum(1 for x in timeline if x["has_media_window"]),
        "segments": timeline,
    }


def story_time_to_media(
    timeline: Mapping[str, Any],
    story_sec: float,
) -> Optional[Dict[str, Any]]:
    """Locate source media PTS for a story playback time."""
    for seg in timeline.get("segments") or []:
        if not seg.get("has_media_window"):
            continue
        si, so = float(seg["story_in"]), float(seg["story_out"])
        if si - 1e-6 <= story_sec <= so + 1e-6:
            frac = 0.0 if so <= si else (story_sec - si) / (so - si)
            media = float(seg["media_in"]) + frac * (
                float(seg["media_out"]) - float(seg["media_in"])
            )
            return {
                "segment_id": seg["segment_id"],
                "role": seg["role"],
                "story_sec": round(float(story_sec), 3),
                "media_sec": round(media, 3),
                "segment": seg,
            }
    return None


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
