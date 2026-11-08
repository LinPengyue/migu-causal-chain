"""EDL structural safety checks shared by the unified story E2E main chain.

These are *safety* gates (not story-quality judgments). Failures must block
candidate render / formal accept.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence


def _num(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def active_media_rows(edl: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for r in edl:
        if not isinstance(r, Mapping):
            continue
        if r.get("include_in_cut", True) is False:
            continue
        mi, mo = _num(r.get("media_in")), _num(r.get("media_out"))
        if mi is None or mo is None:
            continue
        if mo <= mi:
            continue
        rows.append(dict(r))
    return rows


def check_source_pts_monotonic(
    edl: Sequence[Mapping[str, Any]],
    *,
    epsilon: float = 1e-3,
) -> Dict[str, Any]:
    """Return ok=False when adjacent media cuts reverse source PTS order."""
    rows = active_media_rows(edl)
    breaks: List[Dict[str, Any]] = []
    for a, b in zip(rows, rows[1:]):
        a_out = _num(a.get("media_out"))
        b_in = _num(b.get("media_in"))
        if a_out is None or b_in is None:
            continue
        if float(b_in) + epsilon < float(a_out):
            breaks.append(
                {
                    "prev_segment_id": a.get("segment_id"),
                    "prev_media_out": a_out,
                    "next_segment_id": b.get("segment_id"),
                    "next_media_in": b_in,
                    "delta_sec": float(b_in) - float(a_out),
                }
            )
    return {
        "schema": "v3a_edl_source_pts_monotonic_v1",
        "ok": len(breaks) == 0,
        "n_media_rows": len(rows),
        "breaks": breaks,
        "gate": "safety",
        "note": "Monotonic source PTS is a safety constraint, not a quality score.",
    }


def classify_revision_status(
    *,
    edl_changed: bool,
    applied_bound: bool,
    candidate_rendered: bool,
    candidate_accepted: bool,
    vision_backed: bool,
    semantic_passed: bool,
    quality_delta: Optional[str] = None,
    safety_ok: bool = True,
) -> Dict[str, Any]:
    """Distinguish APPLIED / VERIFIED / IMPROVED (never conflate)."""
    applied = bool(edl_changed and applied_bound and safety_ok)
    verified = bool(
        applied
        and candidate_rendered
        and candidate_accepted
        and vision_backed
        and semantic_passed
        and safety_ok
    )
    q = str(quality_delta or "").lower()
    improved = bool(verified and q in ("improved", "better"))
    return {
        "schema": "v3a_revision_status_v1",
        "APPLIED": applied,
        "VERIFIED": verified,
        "IMPROVED": improved,
        "safety_ok": bool(safety_ok),
        "edl_changed": bool(edl_changed),
        "candidate_rendered": bool(candidate_rendered),
        "candidate_accepted": bool(candidate_accepted),
        "vision_backed": bool(vision_backed),
        "semantic_passed": bool(semantic_passed),
        "quality_delta": quality_delta,
        "note": (
            "APPLIED=EDL mutated under safety; VERIFIED=accepted with vision; "
            "IMPROVED=verified plus quality_delta improved. Fixture gate wiring "
            "must not be reported as real story-quality IMPROVED."
        ),
    }
