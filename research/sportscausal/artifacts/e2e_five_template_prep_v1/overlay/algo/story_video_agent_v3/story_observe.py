"""Layered story observation: global / paragraph / local.

Honest about observation method: ordered multi-frame sampling is NOT
"watched full video" unless a video-native provider is used.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from story_video_agent.frames import FrameBudget, FrameBudgetExhausted, FrameStore
from story_video_agent.media import probe_video

from .story_timeline import build_story_timeline, story_time_to_media


def _even_times(start: float, end: float, count: int) -> List[float]:
    if count <= 1:
        return [0.5 * (start + end)]
    if end <= start:
        return [float(start)]
    return [start + (end - start) * i / (count - 1) for i in range(count)]


def _extract_ordered(
    store: FrameStore,
    times: Sequence[float],
    *,
    gap_id: str,
) -> Dict[str, Any]:
    """Extract frames; FrameBudgetExhausted becomes a local soft failure (never abort Agent)."""
    frames: List[Dict[str, Any]] = []
    exhausted = False
    error: Optional[str] = None
    try:
        for t in times:
            rec = store.extract_at(float(t), gap_id=gap_id, tool="story_layered_observe")
            frames.append(rec.to_dict())
    except FrameBudgetExhausted as exc:
        exhausted = True
        error = f"FrameBudgetExhausted:{exc}"
    return {
        "frames": frames,
        "frame_count": len(frames),
        "frame_budget_exhausted": exhausted,
        "error": error,
        "ok": bool(frames) and not exhausted,
    }


def observe_layers(
    *,
    story_mp4: Path,
    source_mp4: Path,
    edl: Sequence[Mapping[str, Any]],
    work_dir: Path,
    diagnosis_issues: Optional[Sequence[Mapping[str, Any]]] = None,
    global_frame_count: int = 12,
    paragraph_frame_count: int = 6,
    local_frame_count: int = 4,
    skip_vlm: bool = True,
    vlm_fn: Optional[Any] = None,
) -> Dict[str, Any]:
    """Produce layered visual evidence with explicit method disclosure.

    Offline / skip_vlm: ffmpeg ordered frames only; semantic UNKNOWN.
    Does not claim full-video comprehension from sparse frames.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    timeline = build_story_timeline(edl)
    story_dur = float(timeline.get("story_duration_sec") or 0.0)
    layers: Dict[str, Any] = {
        "global": None,
        "paragraph": [],
        "local": [],
    }
    method_notes: List[str] = []

    # --- Global: ordered frames across the finished cut ---
    if story_mp4.is_file() and story_dur > 0:
        media = probe_video(story_mp4)
        store = FrameStore(
            media,
            out_dir=work_dir / "global_frames",
            budget=FrameBudget(max_frames=max(global_frame_count + 2, 16)),
        )
        # Prefer continuous short spans at open / mid / late rather than N fixed per segment.
        spans = [
            (0.0, min(story_dur, max(8.0, story_dur * 0.18))),
            (max(0.0, story_dur * 0.35), min(story_dur, story_dur * 0.55)),
            (max(0.0, story_dur * 0.72), story_dur),
        ]
        per = max(2, global_frame_count // len(spans))
        g_frames: List[Dict[str, Any]] = []
        g_times: List[float] = []
        g_errors: List[str] = []
        for i, (a, b) in enumerate(spans):
            ts = _even_times(a, b, per)
            g_times.extend(ts)
            pack = _extract_ordered(store, ts, gap_id=f"global_span_{i}")
            # Bind finished-cut frames to story timestamps and EDL identities.
            # FrameStore timestamps are decoder metadata, not the segment ID.
            for j, frame in enumerate(pack["frames"]):
                mapped = story_time_to_media(timeline, float(ts[j]))
                g_frames.append({
                    **frame,
                    "story_sec": round(float(ts[j]), 3),
                    "segment_id": mapped.get("segment_id") if mapped else None,
                    "sample_provenance": "global_finished_cut",
                })
            if pack.get("error"):
                g_errors.append(str(pack["error"]))
            if pack.get("frame_budget_exhausted"):
                break
        layers["global"] = {
            "scope": "finished_story_mp4",
            "story_duration_sec": story_dur,
            "sample_spans_story_sec": [{"start": a, "end": b} for a, b in spans],
            "sample_times_story_sec": [round(t, 3) for t in g_times],
            "frame_count": len(g_frames),
            "frames": g_frames,
            "frame_budget_exhausted": bool(g_errors),
            "errors": g_errors or None,
            "observation_method": "ordered_multi_frame_spans",
            "claims_full_video_watch": False,
            "note": (
                "Global layer samples open/mid/late contiguous spans of the finished cut; "
                "not equivalent to watching every frame. FrameBudgetExhausted is soft-fail."
            ),
        }
        method_notes.append("global_ordered_multi_frame_spans")
    else:
        layers["global"] = {
            "scope": "finished_story_mp4",
            "ok": False,
            "error": "story_mp4_missing_or_zero_duration",
            "claims_full_video_watch": False,
        }

    # --- Paragraph: focus spans tied to needs_video_verify / arc categories ---
    # Prefer Critic needs_video_verify + narrative stages (buildup/turn/post-climax/ending).
    # Do not blanket-increase frame counts; target uncertain spans only.
    focus_cats = {
        "buildup", "transition", "ending", "opening", "arc_coverage",
        "narrative_order", "narrative_causality", "turn", "climax",
    }
    focus_issues = [
        i
        for i in (diagnosis_issues or [])
        if str(i.get("evidence_sufficiency") or "") == "needs_video_verify"
        or str(i.get("category") or "") in focus_cats
    ]
    # Ensure post-climax / ending coverage when climax exists on timeline.
    has_ending_focus = any(
        str(i.get("category") or "") in ("ending", "climax") for i in focus_issues
    )
    if story_dur > 0 and not has_ending_focus:
        focus_issues.append(
            {
                "issue_id": "targeted_post_climax_tail",
                "story_time_range": [max(0.0, story_dur * 0.78), story_dur],
                "category": "ending",
                "evidence_sufficiency": "needs_video_verify",
            }
        )
    if not focus_issues and story_dur > 0:
        focus_issues = [
            {
                "issue_id": "paragraph_opening_span",
                "story_time_range": [0.0, min(story_dur, max(6.0, story_dur * 0.18))],
                "category": "opening",
            },
            {
                "issue_id": "paragraph_development_span",
                "story_time_range": [story_dur * 0.28, story_dur * 0.55],
                "category": "buildup",
            },
            {
                "issue_id": "paragraph_turn_climax_span",
                "story_time_range": [story_dur * 0.55, story_dur * 0.82],
                "category": "climax",
            },
            {
                "issue_id": "paragraph_ending_span",
                "story_time_range": [story_dur * 0.82, story_dur],
                "category": "ending",
            },
        ]

    if story_mp4.is_file():
        media = probe_video(story_mp4)
        pstore = FrameStore(
            media,
            out_dir=work_dir / "paragraph_frames",
            budget=FrameBudget(max_frames=max(paragraph_frame_count * 4, 24)),
        )
        for iss in focus_issues[:6]:
            rng = list(iss.get("story_time_range") or [0.0, story_dur])
            a, b = float(rng[0]), float(rng[1] if len(rng) > 1 else rng[0] + 1.0)
            a = max(0.0, a)
            b = min(story_dur, max(a + 0.5, b))
            ts = _even_times(a, b, paragraph_frame_count)
            pack = _extract_ordered(
                pstore, ts, gap_id=f"para_{iss.get('issue_id') or 'x'}"
            )
            layers["paragraph"].append(
                {
                    "issue_id": iss.get("issue_id"),
                    "category": iss.get("category"),
                    "story_time_range": [a, b],
                    "sample_times_story_sec": [round(t, 3) for t in ts],
                    "frame_count": pack["frame_count"],
                    "frames": [
                        {
                            **frame,
                            "story_sec": round(float(ts[j]), 3),
                            "segment_id": (
                                story_time_to_media(timeline, float(ts[j])) or {}
                            ).get("segment_id"),
                            "sample_provenance": "paragraph_finished_cut",
                        }
                        for j, frame in enumerate(pack["frames"])
                    ],
                    "frame_budget_exhausted": pack.get("frame_budget_exhausted"),
                    "error": pack.get("error"),
                    "observation_method": "ordered_multi_frame_paragraph",
                    "claims_full_video_watch": False,
                }
            )
            if pack.get("frame_budget_exhausted"):
                break
        method_notes.append("paragraph_ordered_frames")

    # --- Local: source PTS around media windows for flagged / goal segments ---
    if source_mp4.is_file():
        smedia = probe_video(source_mp4)
        lstore = FrameStore(
            smedia,
            out_dir=work_dir / "local_frames",
            budget=FrameBudget(max_frames=max(local_frame_count * 6, 24)),
        )
        targets = []
        for iss in (diagnosis_issues or [])[:8]:
            for sid in iss.get("segment_ids") or []:
                targets.append(str(sid))
        # Always include goal anchors for local integrity check
        for seg in timeline.get("segments") or []:
            if "goal_action" in str(seg.get("role") or ""):
                targets.append(str(seg["segment_id"]))
        seen = set()
        for sid in targets:
            if sid in seen:
                continue
            seen.add(sid)
            seg = next(
                (s for s in (timeline.get("segments") or []) if s.get("segment_id") == sid),
                None,
            )
            if not seg or not seg.get("has_media_window"):
                continue
            mi, mo = float(seg["media_in"]), float(seg["media_out"])
            # Prefer a short continuous window at cut boundaries + mid
            ts = [
                mi + 0.3,
                0.5 * (mi + mo),
                max(mi + 0.3, mo - 0.3),
            ][:local_frame_count]
            pack = _extract_ordered(lstore, ts, gap_id=f"local_{sid}")
            layers["local"].append(
                {
                    "segment_id": sid,
                    "role": seg.get("role"),
                    "media_window": [mi, mo],
                    "story_time_range": [seg.get("story_in"), seg.get("story_out")],
                    "sample_times_media_sec": [round(t, 3) for t in ts],
                    "frame_count": pack["frame_count"],
                    "frames": pack["frames"],
                    "frame_budget_exhausted": pack.get("frame_budget_exhausted"),
                    "error": pack.get("error"),
                    "observation_method": "ordered_boundary_and_mid_frames",
                    "claims_full_video_watch": False,
                }
            )
            if pack.get("frame_budget_exhausted"):
                break
        method_notes.append("local_source_boundary_frames")

    semantic_provider_used = False
    vlm_results: List[Dict[str, Any]] = []
    if not skip_vlm and callable(vlm_fn):
        # Caller supplies authorized VLM; we still record sampled scope honestly.
        semantic_provider_used = True
        payload = {
            "layers": {
                "global_times": (layers.get("global") or {}).get("sample_times_story_sec"),
                "paragraph_count": len(layers.get("paragraph") or []),
                "local_count": len(layers.get("local") or []),
            },
            "timeline": timeline,
            "note": "Provider receives ordered frames / clip refs; scope is recorded below.",
        }
        try:
            vlm_results.append(vlm_fn(payload))
        except Exception as exc:  # noqa: BLE001 — surface honestly
            vlm_results.append({"ok": False, "error": str(exc)})
            semantic_provider_used = False

    out = {
        "schema": "v3a_layered_story_observe_v1",
        "fixture_or_offline": bool(skip_vlm) or not semantic_provider_used,
        "semantic_provider_used": semantic_provider_used,
        "observation_methods": method_notes,
        "claims_full_video_watch": False,
        "disclaimer": (
            "Observation uses time-ordered multi-frame sampling and/or short spans. "
            "Unless a video-native provider ingested continuous footage, this is not "
            "full-video watching. Do not equate sparse frames with complete story comprehension."
        ),
        "layers": layers,
        "vlm_results": vlm_results,
        "derived_issues": [],  # semantic promotion reserved for authorized VLM path
        "story_to_media_map_sample": [
            story_time_to_media(timeline, t)
            for t in _even_times(0.0, max(story_dur, 0.1), 5)
            if story_dur > 0
        ],
    }
    (work_dir / "layered_observe.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return out
