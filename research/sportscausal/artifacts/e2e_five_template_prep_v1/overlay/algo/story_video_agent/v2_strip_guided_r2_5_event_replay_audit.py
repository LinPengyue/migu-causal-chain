"""Audit original events.json replay/live fields against an EDL media span set."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _media_span(ev: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    mt = ev.get("media_time") or {}
    s, e = mt.get("start_time_sec"), mt.get("end_time_sec")
    if s is None or e is None:
        return None
    return float(s), float(e)


def _overlap(a0: float, a1: float, b0: float, b1: float) -> bool:
    return max(a0, b0) < min(a1, b1)


def audit_event_replay_fields(
    *,
    events_path: Path,
    edl_spans: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Count video_context / is_replay / broadcast_phase / is_slow_motion and EDL coverage.

    Does not invent labels: missing fields are recorded as missing, never defaulted to false.
    """
    events_path = Path(events_path)
    doc = json.loads(events_path.read_text(encoding="utf-8"))
    events: List[Dict[str, Any]] = list(doc.get("events") or [])

    n = len(events)
    has_vc = 0
    is_replay_c: Counter = Counter()
    bp_c: Counter = Counter()
    sm_c: Counter = Counter()
    replay_of_present = 0
    replay_events: List[Dict[str, Any]] = []

    for ev in events:
        vc = ev.get("video_context")
        if not isinstance(vc, dict):
            is_replay_c["<no_video_context>"] += 1
            bp_c["<no_video_context>"] += 1
            sm_c["<no_video_context>"] += 1
            continue
        has_vc += 1
        if "is_replay" not in vc:
            is_replay_c["<missing>"] += 1
        else:
            v = vc.get("is_replay")
            key = "null" if v is None else str(bool(v))
            is_replay_c[key] += 1
            if v is True:
                span = _media_span(ev)
                replay_events.append(
                    {
                        "event_id": ev.get("event_id"),
                        "event_type": ev.get("event_type"),
                        "start_time_sec": None if span is None else span[0],
                        "end_time_sec": None if span is None else span[1],
                        "broadcast_phase": vc.get("broadcast_phase"),
                        "is_slow_motion": vc.get("is_slow_motion"),
                        "replay_of_event_id": vc.get("replay_of_event_id"),
                    }
                )
        if "broadcast_phase" not in vc:
            bp_c["<missing>"] += 1
        else:
            bp_c[str(vc.get("broadcast_phase"))] += 1
        if "is_slow_motion" not in vc:
            sm_c["<missing>"] += 1
        else:
            v = vc.get("is_slow_motion")
            sm_c["null" if v is None else str(bool(v))] += 1
        if "replay_of_event_id" in vc:
            replay_of_present += 1

    span_coverage: List[Dict[str, Any]] = []
    for sp in edl_spans:
        a = sp.get("media_in")
        b = sp.get("media_out")
        if a is None or b is None:
            continue
        a_f, b_f = float(a), float(b)
        hits: List[Dict[str, Any]] = []
        for ev in events:
            span = _media_span(ev)
            if span is None:
                continue
            if not _overlap(a_f, b_f, span[0], span[1]):
                continue
            vc = ev.get("video_context") if isinstance(ev.get("video_context"), dict) else {}
            hits.append(
                {
                    "event_id": ev.get("event_id"),
                    "event_type": ev.get("event_type"),
                    "start_time_sec": span[0],
                    "end_time_sec": span[1],
                    "broadcast_phase": vc.get("broadcast_phase") if "broadcast_phase" in vc else "<missing>",
                    "is_replay": vc.get("is_replay") if "is_replay" in vc else "<missing>",
                    "is_slow_motion": vc.get("is_slow_motion") if "is_slow_motion" in vc else "<missing>",
                }
            )
        n_replay = sum(1 for h in hits if h.get("is_replay") is True)
        n_live = sum(1 for h in hits if h.get("broadcast_phase") == "LIVE" and h.get("is_replay") is False)
        span_coverage.append(
            {
                "segment_id": sp.get("segment_id") or sp.get("node_id") or sp.get("key_event_id"),
                "role": sp.get("role"),
                "media_in": a_f,
                "media_out": b_f,
                "n_overlapping_events": len(hits),
                "n_overlapping_replay": n_replay,
                "n_overlapping_live_labeled": n_live,
                "coverage_status": (
                    "covered"
                    if hits
                    else "uncovered_no_event_in_span"
                ),
                "overlapping_events": hits,
            }
        )

    uncovered = [s for s in span_coverage if s["coverage_status"] != "covered"]
    usable = has_vc == n and is_replay_c.get("True", 0) + is_replay_c.get("False", 0) == n
    incomplete_notes: List[str] = []
    if has_vc < n:
        incomplete_notes.append("some_events_missing_video_context")
    if is_replay_c.get("<missing>", 0) or is_replay_c.get("null", 0):
        incomplete_notes.append("is_replay_incomplete")
    if sm_c.get("True", 0) == 0 and sm_c.get("False", 0) == n:
        incomplete_notes.append(
            "is_slow_motion_all_false_may_be_underlabeled — do not treat as proof of no slow-mo"
        )
    if uncovered:
        incomplete_notes.append(
            f"{len(uncovered)}_edl_spans_have_no_overlapping_events — cannot rely on event labels alone"
        )

    return {
        "schema": "v2_r25_event_replay_field_audit_v1",
        "events_path": str(events_path),
        "n_events": n,
        "video_context_present": has_vc,
        "video_context_coverage_ratio": round(has_vc / n, 4) if n else None,
        "is_replay_counts": dict(is_replay_c),
        "broadcast_phase_counts": dict(bp_c),
        "is_slow_motion_counts": dict(sm_c),
        "replay_of_event_id_field_present_on": replay_of_present,
        "n_replay_true_events": len(replay_events),
        "replay_events": replay_events,
        "edl_span_coverage": span_coverage,
        "n_edl_spans_uncovered": len(uncovered),
        "labels_usable_for_candidate_audit": usable and len(uncovered) == 0,
        "labels_partially_usable": usable and len(uncovered) > 0,
        "incomplete_notes": incomplete_notes,
        "policy": (
            "When event labels overlap a candidate span, feed them into broadcast timeline. "
            "When uncovered or incomplete, do NOT default is_replay=false; require video observation."
        ),
        "render_ready": False,
    }


def event_labels_overlapping(
    audit: Dict[str, Any], media_in: float, media_out: float
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in audit.get("replay_events") or []:
        s, e = row.get("start_time_sec"), row.get("end_time_sec")
        if s is None or e is None:
            continue
        if _overlap(media_in, media_out, float(s), float(e)):
            out.append({**row, "label": "replay"})
    return out
