"""Optional video-first additive story opportunity search for V3-A.

This stage diagnoses *potential* montage ambiguity from the EDL, then retrieves
bounded, continuous windows from the ORIGINAL source immediately preceding the
next story action. It is NOT an event-heat retrieval and NEVER asserts story
quality, first-LIVE status, or permission to change an EDL.

All formulas operate on roles and timestamps, never match/goal hardcodes.
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .story_timeline import active_cut_rows, build_story_timeline

SCHEMA = "v3a_additive_story_opportunity_v1"
PREGOAL_CONTEXT_SEC = 150.0
MAX_CANDIDATES = 4
WINDOW_SEC = 12.0
SOURCE_READ_BUDGET_SEC = 48.0
_MIN_CAUSAL_GAP_SEC = 180.0


def _number(x: Any) -> Optional[float]:
    if isinstance(x, bool) or x is None:
        return None
    try:
        v = float(x)
    except (ValueError, TypeError, OverflowError):
        return None
    return v if math.isfinite(v) else None


def _is_buildup(role: str) -> bool:
    role = str(role or "").lower()
    return any(x in role for x in ("buildup", "pressure", "setup", "development"))


def _is_goal_action(role: str) -> bool:
    return "goal_action" in str(role or "").lower()


def _unoccupied_windows(
    *,
    lower: float,
    upper: float,
    occupied: Sequence[tuple[float, float]],
    n: int,
    duration: float,
) -> List[Dict[str, float]]:
    """Evenly probe recent pre-goal source time; never optimize for event heat."""
    if upper - lower < duration * 1.5:
        return []
    out = []
    # Stratify the prior interval, with a near-action window. Distinct
    # evidence is vital; 4 overlapping 12-s clips do not cover 48 s.
    for frac in (0.18, 0.43, 0.68, 0.93):
        if len(out) >= n:
            break
        center = lower + frac * (upper - lower)
        a = max(lower, min(upper - duration, center - duration / 2))
        b = a + duration
        if any(b > lo and a < hi for lo, hi in occupied):
            continue
        if any(b > x["media_in"] and a < x["media_out"] for x in out):
            continue
        out.append({"media_in": round(a, 3), "media_out": round(b, 3)})
    return out


def discover_additive_opportunities(
    edl: Sequence[Mapping[str, Any]],
    *,
    source_sha256: str,
    max_opportunities: int = 1,
    lookback_sec: float = PREGOAL_CONTEXT_SEC,
    max_candidates: int = MAX_CANDIDATES,
    window_sec: float = WINDOW_SEC,
) -> Dict[str, Any]:
    """Detect one *question* near a misleading buildup→distant-action seam.

    The implication is narrative, not physical causation: distant source PTS
    between adjacent edit shots is NEVER proof that the story is defective.
    Source windows are search hypotheses and unverified broadcast footage.
    """
    if not source_sha256 or len(source_sha256) != 64 or any(
        c not in "0123456789abcdefABCDEF" for c in source_sha256
    ):
        raise ValueError("source_sha256_required")
    if not (1 <= max_opportunities <= 3 and 1 <= max_candidates <= 4):
        raise ValueError("invalid_search_budget")
    if not (30 <= lookback_sec <= 300 and 4 <= window_sec <= 15):
        raise ValueError("invalid_temporal_budget")
    rows = active_cut_rows(edl)
    occupied = [
        (float(a), float(b))
        for r in rows
        for a, b in [(_number(r.get("media_in")), _number(r.get("media_out")))]
        if a is not None and b is not None and b > a
    ]
    opportunities = []
    for idx in range(1, len(rows)):
        previous, action = rows[idx - 1], rows[idx]
        prev_role, action_role = str(previous.get("role") or ""), str(action.get("role") or "")
        if not (_is_buildup(prev_role) and _is_goal_action(action_role)):
            continue
        prev_out, goal_in = _number(previous.get("media_out")), _number(action.get("media_in"))
        if prev_out is None or goal_in is None:
            continue
        gap = goal_in - prev_out
        if gap < _MIN_CAUSAL_GAP_SEC:
            continue
        lower = max(0.0, prev_out + 1.0, goal_in - lookback_sec)
        upper = goal_in - 4.0
        wins = _unoccupied_windows(
            lower=lower, upper=upper, occupied=occupied,
            n=max_candidates, duration=window_sec,
        )
        if not wins:
            continue
        timeline = build_story_timeline(rows)
        before_tl = next((s for s in timeline["segments"]
                          if s["segment_id"] == previous.get("segment_id")), None)
        seam = float(before_tl["story_out"]) if before_tl else None
        issue_id = f"additive_transition_{previous.get('segment_id')}_to_{action.get('segment_id')}"
        opportunities.append({
            "opportunity_id": issue_id,
            "category": "additive_narrative_opportunity",
            "target_narrative_function": "pre_goal_state_change_or_buildup",
            "before_segment_id": str(previous.get("segment_id")),
            "after_segment_id": str(action.get("segment_id")),
            "before_role": prev_role,
            "after_role": action_role,
            "before_pts_end": round(prev_out, 3),
            "after_pts_start": round(goal_in, 3),
            "source_gap_sec": round(gap, 3),
            "story_seam_sec": round(seam, 3) if seam is not None else None,
            "observed_structural_fact": "adjacent_edited_shots_from_distant_source_times",
            "story_question": (
                "Does the adjacent buildup shot falsely imply it directly caused "
                "the later goal? Is specific unshown game-state or emotional "
                "information actually needed before the goal, or is the cut coherent?"
            ),
            "required_new_information": (
                "If, and only if, video establishes a meaningful deficiency, identify "
                "a concrete pre-action state change or escalating pressure not already "
                "shown by the baseline; mere temporal closeness is not enough."
            ),
            "hypothesis_status": "OPPORTUNITY_UNVERIFIED",
            "story_defect_confirmed": False,
            "source_video_windows": [
                {**w, "origin": "stratified_pre_action_video_probe",
                 "semantics_verified": False, "first_live_verified": False,
                 "edl_insert_authorized": False}
                for w in wins
            ],
            "requires_first_live_evidence_before_insert": True,
            "baseline_goal_anchors_protected": True,
        })
        if len(opportunities) >= max_opportunities:
            break
    return {
        "schema": SCHEMA,
        "source_sha256": source_sha256.lower(),
        "opportunities": opportunities,
        "source_window_count": sum(len(x["source_video_windows"]) for x in opportunities),
        "max_total_source_read_sec": SOURCE_READ_BUDGET_SEC,
        "event_metadata_used_for_video_ranking": False,
        "paid_http_calls": 0,
        "edl_mutation_authorized": False,
        "first_live_verified": False,
        "semantic_repair_confirmed": False,
        "note": (
            "Opportunity discovery is only a search prior. Continuous source "
            "video must be watched/semantically reviewed before any narrative "
            "claim. New source must separately satisfy FIRST_LIVE before EDL insertion."
        ),
    }


def _sha_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(part)
    return hasher.hexdigest()


def _export_clip(video: Path, start: float, end: float, out: Path) -> Dict[str, Any]:
    if start < 0 or end - start < .5:
        return {"ok": False, "error": "invalid_clip_bounds"}
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-i", str(video), "-t", f"{end-start:.3f}",
        "-map", "0:v:0", "-map", "0:a?", "-vf", "scale=960:-2",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "25",
        "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", "-y",
        str(out),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=100)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}"}
    ok = result.returncode == 0 and out.is_file() and out.stat().st_size > 4096
    return {
        "ok": ok, "path": str(out) if ok else None,
        "sha256": _sha_file(out) if ok else None,
        "error": None if ok else result.stderr[-800:],
        "requested_source_pts": [round(start, 3), round(end, 3)],
        "semantic_status": "NOT_REVIEWED",
    }


def build_opportunity_video_pack(
    *,
    opportunities: Mapping[str, Any],
    source_mp4: Path,
    story_mp4: Path,
    edl: Sequence[Mapping[str, Any]],
    out_dir: Path,
    max_source_read_sec: float = SOURCE_READ_BUDGET_SEC,
) -> Dict[str, Any]:
    """Materialize readable continuous clips. Never edits a narrative EDL."""
    if out_dir.exists():
        raise FileExistsError("refuse_overwrite_existing_video_pack")
    if not source_mp4.is_file() or not story_mp4.is_file():
        raise FileNotFoundError("source_or_finished_story_mp4_missing")
    expected_sha = str(opportunities.get("source_sha256") or "")
    if _sha_file(source_mp4) != expected_sha:
        raise ValueError("source_sha256_mismatch")
    out_dir.mkdir(parents=True)
    total_read = 0.0
    review_items = []
    for i, opportunity in enumerate(opportunities.get("opportunities") or [], 1):
        if not isinstance(opportunity, Mapping):
            continue
        seam = _number(opportunity.get("story_seam_sec"))
        item = {
            "opportunity_id": opportunity.get("opportunity_id"),
            "story_defect_confirmed": False,
            "first_live_verified": False,
            "candidate_semantic_status": "NOT_REVIEWED",
            "finished_story_context": None,
            "source_context_clips": [],
        }
        if seam is not None:
            tl = build_story_timeline(edl)
            story_end = float(tl["story_duration_sec"])
            # Include the FULL following goal action (often ~22s): an 8s
            # after-seam snippet can miss shot/net and falsely assess semantics.
            lo, hi = max(0.0, seam - 8.0), min(story_end, seam + 24.0)
            if hi - lo >= .5:
                item["finished_story_context"] = _export_clip(
                    story_mp4, lo, hi, out_dir / f"{i:02d}_story_seam.mp4",
                )
        for j, window in enumerate(opportunity.get("source_video_windows") or [], 1):
            if not isinstance(window, Mapping):
                continue
            a, b = _number(window.get("media_in")), _number(window.get("media_out"))
            if a is None or b is None or b <= a:
                continue
            if total_read + (b-a) > max_source_read_sec + 1e-6:
                break
            total_read += b-a
            exported = _export_clip(
                source_mp4, a, b, out_dir / f"{i:02d}_source_probe_{j:02d}.mp4",
            )
            item["source_context_clips"].append({
                "media_in": a, "media_out": b,
                "source": "ORIGINAL_MATCH_VIDEO",
                "event_heat_based": False,
                "first_live_verified": False,
                "semantic_fit_verified": False,
                "export": exported,
            })
        review_items.append(item)
    report = {
        "schema": "v3a_additive_story_opportunity_video_pack_v1",
        "source_sha256": expected_sha,
        "story_mp4_sha256": _sha_file(story_mp4),
        "actual_requested_source_read_sec": round(total_read, 3),
        "paid_http_calls": 0,
        "edl_modified": False,
        "release_authorized": False,
        "video_pack_only": True,
        "required_review_questions": [
            "What exactly is absent from the existing story seam?",
            "Does the candidate show a relevant new state change, rather than generic attack footage?",
            "Does the candidate improve continuity over the baseline when viewed in context?",
            "Is the source original first-broadcast live, not replay or slow motion?",
            "Does insertion preserve the three protected goal actions and source chronology?",
        ],
        "review_items": review_items,
    }
    (out_dir / "opportunity_video_manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return report
