"""Read-only, match-agnostic source-bound audit of story-cut relevance.

A short, real broadcast shot can still be narratively irrelevant. This audit
maps viewer-reported playback times to source-bound EDL windows, including
adjacent windows when timing is uncertain. It NEVER infers video semantics,
changes an EDL, labels the target clip, or authorizes use of replay.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from .story_exploratory_cut import _protected
from .story_timeline import active_cut_rows, build_story_timeline, edl_rows, story_time_to_media

SCHEMA = "v3a_cut_relevance_audit_v1"


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def build_cut_relevance_inventory(
    edl: Sequence[Mapping[str, Any]],
    *,
    source_sha256: Optional[str] = None,
) -> dict[str, Any]:
    """Inventory ALL active clips, including safety-protected goal/score clips.

    Exploratory protection is a mutation constraint, NOT proof of story value.
    Source SHA is metadata supplied by caller, not re-hashed in this function.
    """
    timeline = build_story_timeline(edl)
    rows = active_cut_rows(edl)
    segments = []
    for seg, row in zip(timeline["segments"], rows):
        locked = _protected(row)
        segments.append({
            "segment_id": seg["segment_id"],
            "role": seg["role"],
            "story_in": seg["story_in"],
            "story_out": seg["story_out"],
            "media_in": seg["media_in"],
            "media_out": seg["media_out"],
            "shot_kind": seg["shot_kind"],
            "has_media_window": seg["has_media_window"],
            "exploratory_edit_protected": locked,
            "goal_action_complete": row.get("goal_action_complete") is True,
            "narrative_necessity": "UNVERIFIED",
            "semantic_video_verified": False,
        })
    return {
        "schema": SCHEMA,
        "source_sha256": source_sha256,
        "source_sha_verified_here": False,
        "story_duration_sec": timeline["story_duration_sec"],
        "segment_count": len(segments),
        "segments": segments,
        "notes": [
            "A protected score/title/goal row is not necessarily narratively useful in its entirety.",
            "No role string, event ID, PTS gap or human comment is a video-semantic verdict.",
            "Do not delete or trim goal action/first-live evidence without independent source-bound video review.",
        ],
    }


def audit_playback_observations(
    edl: Sequence[Mapping[str, Any]],
    playback_times_sec: Sequence[float],
    *,
    rendered_duration_sec: Optional[float] = None,
    observation_radius_sec: float = 0.5,
    source_sha256: Optional[str] = None,
) -> dict[str, Any]:
    """Resolve imprecise viewer timestamps to conservative source candidates.

    MP4-vs-EDL duration discrepancy may be accumulated anywhere in the render;
    it is NOT an exact global time offset. Conservatively widen each interval
    by the absolute discrepancy, and return *all* intersecting EDL segments.
    """
    inventory = build_cut_relevance_inventory(edl, source_sha256=source_sha256)
    story_duration = float(inventory["story_duration_sec"])
    rendered = _finite(rendered_duration_sec)
    if rendered_duration_sec is not None and rendered is None:
        raise ValueError("rendered_duration_sec must be finite")
    radius = _finite(observation_radius_sec)
    if radius is None or radius < 0:
        raise ValueError("observation_radius_sec must be finite and nonnegative")
    if rendered is not None and rendered <= 0:
        raise ValueError("rendered_duration_sec must be positive")
    delta = abs(rendered - story_duration) if rendered is not None else 0.0
    effective_radius = float(radius) + delta
    tl = build_story_timeline(edl)
    observations = []
    for raw_time in playback_times_sec:
        t = _finite(raw_time)
        if t is None or t < 0 or (rendered is not None and t > rendered):
            observations.append({
                "playback_sec": raw_time,
                "status": "INVALID_PLAYBACK_TIME",
                "candidate_segments": [],
            })
            continue
        # When no rendered duration is provided, the EDL end bounds still apply.
        if rendered is None and t > story_duration:
            observations.append({
                "playback_sec": t,
                "status": "OUTSIDE_EDL_DURATION",
                "candidate_segments": [],
            })
            continue
        lo, hi = max(0.0, t - effective_radius), t + effective_radius
        possible = []
        for seg in inventory["segments"]:
            if seg["story_in"] <= hi and seg["story_out"] >= lo:
                possible.append({
                    "segment_id": seg["segment_id"],
                    "role": seg["role"],
                    "story_interval": [seg["story_in"], seg["story_out"]],
                    "source_interval": [seg["media_in"], seg["media_out"]],
                    "exploratory_edit_protected": seg["exploratory_edit_protected"],
                    "goal_action_complete": seg["goal_action_complete"],
                    "semantic_video_verified": False,
                })
        nominal = story_time_to_media(tl, t) if t <= story_duration else None
        observations.append({
            "playback_sec": t,
            "status": "NEEDS_BOUNDARY_VIDEO_REVIEW" if len(possible) != 1
                else "NEEDS_SEGMENT_VIDEO_REVIEW",
            "nominal_segment_id": nominal.get("segment_id") if nominal else None,
            "candidate_segments": possible,
            "uncertainty_window_sec": [round(lo, 3), round(hi, 3)],
            "render_duration_discrepancy_sec": round(delta, 3),
            "semantic_event_relevance": "UNVERIFIED",
            "edit_authorized": False,
        })
    return {
        "schema": SCHEMA,
        "audit_type": "HUMAN_TIME_TO_SOURCE_CANDIDATES",
        "source_sha256": source_sha256,
        "source_sha_verified_here": False,
        "edl_duration_sec": story_duration,
        "rendered_duration_sec": rendered,
        "effective_uncertainty_radius_sec": round(effective_radius, 3),
        "observations": observations,
        "not_agent_runtime_input": True,
        "no_edl_mutation": True,
        "no_automatic_deletion": True,
        "next_step": "Inspect all candidate source windows and adjacent clips in the original video; classify narrative contribution with bound visual evidence.",
    }


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Read-only story playback/source relevance audit")
    p.add_argument("--edl", type=Path, required=True)
    p.add_argument("--time", type=float, action="append", required=True,
                   help="Viewer playback timestamp in seconds; repeat per observation")
    p.add_argument("--rendered-duration-sec", type=float)
    p.add_argument("--radius-sec", type=float, default=0.5)
    p.add_argument("--source-sha256")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    edl = edl_rows(json.loads(args.edl.read_text(encoding="utf-8")))
    if not edl:
        p.error("EDL must contain nonempty segment rows")
    report = audit_playback_observations(
        edl, args.time, rendered_duration_sec=args.rendered_duration_sec,
        observation_radius_sec=args.radius_sec, source_sha256=args.source_sha256,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
