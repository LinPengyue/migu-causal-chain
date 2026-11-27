"""Zero-HTTP full-cut baseline/candidate comparison.

Measures EDL structure and duration cost; does NOT claim semantic improvement.
Actual story gain needs independently grounded dual-video observations.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence


def _included(rows: Sequence[Mapping[str, Any]]) -> list:
    out = []
    for r in rows:
        if not isinstance(r, Mapping) or not r.get("include_in_cut", True):
            continue
        try:
            start, end = float(r["media_in"]), float(r["media_out"])
        except (KeyError, ValueError, TypeError):
            continue
        if end > start:
            out.append((str(r.get("segment_id") or ""), start, end, str(r.get("role") or "")))
    return out


def compare_fullcut_edls(
    baseline: Sequence[Mapping[str, Any]],
    candidate: Sequence[Mapping[str, Any]],
    *,
    fullcut_review: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """A measured cost report and deliberately fail-closed story quality state.

    A structured review with independent source binding is future work; callers
    MUST NOT treat untrusted text labels as quality proof.
    """
    a, b = _included(baseline), _included(candidate)
    da = sum(end-start for _, start, end, _ in a)
    db = sum(end-start for _, start, end, _ in b)
    baseline_keys = {(sid, st, en, role) for sid, st, en, role in a}
    candidate_keys = {(sid, st, en, role) for sid, st, en, role in b}
    added = [dict(segment_id=sid, source_pts=[st, en], role=role, duration_sec=round(en-st, 3))
             for sid, st, en, role in b if (sid, st, en, role) not in baseline_keys]
    removed = [dict(segment_id=sid, source_pts=[st, en], role=role, duration_sec=round(en-st, 3))
               for sid, st, en, role in a if (sid, st, en, role) not in candidate_keys]
    delta = db-da
    return {
        "schema": "v3a_fullcut_baseline_candidate_delta_v1",
        "baseline_duration_sec": round(da, 3),
        "candidate_duration_sec": round(db, 3),
        "duration_delta_sec": round(delta, 3),
        "duration_ratio": round(db/da, 4) if da else None,
        "added_source_segments": added,
        "removed_source_segments": removed,
        "has_edit": a != b,
        "duration_cost_observed": delta > 0,
        "duration_is_not_story_quality": True,
        "story_information_gain": "UNVERIFIED",
        "story_coherence_gain": "UNVERIFIED",
        "pacing_gain": "UNVERIFIED",
        "fullcut_semantic_review": "NOT_AUTHENTICATED",
        "untrusted_external_review_ignored": bool(fullcut_review),
        "candidate_better_than_baseline": "UNVERIFIED",
        "authorizes_promote_best": False,
        "required_next_evidence": (
            "Independent matched full-cut visual/audio review comparing the "
            "same story before/after; source and candidate MP4 SHA binding, "
            "actual observed missing-information resolution, pacing and "
            "redundancy; source-first-live and goal-safety remain separate."
        ),
    }
