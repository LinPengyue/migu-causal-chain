"""Source observations for a Planner-selected story trial."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Mapping

from story_video_agent.frames import FrameBudget, FrameStore
from story_video_agent.media import probe_video

from .story_evidence_search import _live_credibility, event_media_span
from .story_narrative_fit import _sha_file
from .story_timeline import _num
from .story_first_poc_cli import parse_model_json, write_json
from .story_paid_eval import _call_audit_from_raw


# The previous relation and before/candidate/after review is archived at
# ba38ef7 (this file). The shared narrative-fit implementation remains available
# in story_narrative_fit.py and story_narrative_fit_vlm.py.


def story_first_event_context(trial, source_events):
    """Build a compact source timeline and identify independently annotated events."""
    windows = trial["windows"]
    selected = {event["event_id"]: event for event in trial["events"]}
    # Keep all events in the candidate windows and the nearest two on either
    # side of each window, even where the event timeline is sparse.
    timed = []
    for event in source_events:
        eid = str(event.get("event_id") or "")
        span = event_media_span(event)
        if eid and span and all(math.isfinite(t) for t in span):
            timed.append((span[1], eid, event))
    timed.sort(key=lambda row: (row[0], row[1]))
    nearby = set()
    for w in windows:
        start, end = w["source_pts_start"], w["source_pts_end"]
        nearby.update(eid for pts, eid, _ in timed if start <= pts <= end)
        nearby.update(eid for _, eid, _ in [row for row in timed if row[0] < start][-2:])
        nearby.update(eid for _, eid, _ in [row for row in timed if row[0] > end][:2])
    occurrences = {}
    for pts, eid, _ in timed:
        if eid in selected:
            occurrences.setdefault(eid, []).append(pts)

    rows, annotated_ids = [], set()
    for pts, eid, event in timed:
        if eid not in nearby and eid not in selected:
            continue
        enrichment = event.get("enrichment")
        provenance = enrichment.get("provenance") if isinstance(enrichment, Mapping) else None
        quality = event.get("annotation_quality")
        confidence = quality.get("annotator_confidence") if isinstance(quality, Mapping) else None
        if provenance == "independent_atomic_annotation":
            annotation_source = provenance
        elif provenance == "causal_atom_fill":
            annotation_source = provenance
        elif isinstance(quality, Mapping) and (conf := _num(confidence)) is not None and 0 < conf <= 1:
            annotation_source = "annotated_delivery_event"
        else:
            annotation_source = "source_event"
        candidate = selected.get(eid)
        if (candidate and annotation_source != "source_event" and len(occurrences[eid]) == 1
                and abs(pts - candidate["source_pts_sec"]) <= 0.05
                and str(event.get("event_type") or event.get("event_type_zh") or "").casefold()
                == str(candidate.get("event_type") or "").casefold()):
            annotated_ids.add(eid)
        attrs = event.get("attributes")
        rows.append({
            "event_id": eid,
            "source_pts_sec": pts,
            "event_type": event.get("event_type") or event.get("event_type_zh"),
            "label": event.get("comment_label"),
            "notes": str(event.get("notes") or "")[:240],
            "attributes": {
                key: attrs[key] for key in ("Attacker", "Defender", "Defensive_Action", "Team")
                if isinstance(attrs, Mapping) and key in attrs
            },
            "broadcast_phase": _live_credibility(event)["broadcast_phase"],
            "annotation_source": annotation_source,
            "annotator_confidence": confidence,
        })
    return rows, annotated_ids


def _story_review_frames(trial, source_mp4, out_dir):
    media = probe_video(source_mp4)
    store = FrameStore(media, out_dir=out_dir / "source_frames",
                       budget=FrameBudget(max_frames=2 * len(trial["windows"]) + len(trial["events"])))
    event_pts = {row["event_id"]: row["source_pts_sec"] for row in trial["events"]}
    refs = {}
    for window in trial["windows"]:
        wid = window["candidate_id"]
        start, end = window["source_pts_start"], window["source_pts_end"]
        times = {start + fraction * (end - start): [] for fraction in (0.3, 0.7)}
        for eid in window["event_ids"]:
            times.setdefault(event_pts[eid], []).append(eid)
        for target, event_ids in sorted(times.items()):
            frame = store.extract_at(
                target, gap_id=f"{wid}:candidate", tool="story_first_source_review",
            )
            pts = frame.actual_media_sec
            if (frame.pts_status != "pts" or pts is None
                    or not start - 0.05 <= pts <= end + 0.05):
                raise ValueError("decoded_pts_outside_review_window:" + wid)
            fid = f"f{len(refs) + 1}"
            refs[fid] = {
                "role": "candidate", "frame_id": fid, "window_id": wid,
                "event_ids": event_ids, "source_pts_sec": pts,
                "path": str(frame.path), "sha256": _sha_file(Path(frame.path)),
                "requested_media_sec": frame.requested_media_sec,
                "actual_media_sec": pts, "pts_status": "pts",
            }
    store.write_manifest(out_dir / "frame_extraction_manifest.json")
    return refs


def _assess_observations(trial, parsed, refs):
    observations, feedback = [], []
    rows = parsed.get("events")
    rows = rows if isinstance(rows, list) else []
    for event in trial["events"]:
        eid = event["event_id"]
        matches = [row for row in rows if isinstance(row, Mapping) and row.get("event_id") == eid]
        row = matches[0] if len(matches) == 1 else {}
        cited = row.get("frame_ids")
        bound = isinstance(cited, list) and all(isinstance(f, str) and f in refs for f in cited)
        reason = str(row.get("reason") or "").strip()[:600]
        status = row.get("status")
        event_bound = bound and any(eid in refs[f]["event_ids"] for f in cited)
        if not event_bound or not reason or status not in ("SUPPORTED", "CONTRADICTED", "UNCERTAIN"):
            status = "UNCERTAIN"
            reason = "missing_bound_visual_support"
        result = {"event_id": eid, "status": status, "reason": reason,
                  "frame_ids": cited if bound else []}
        observations.append(result)
        if status != "SUPPORTED":
            feedback.append({**result, "event_ids": [eid]})
    return observations, feedback


def observe_story_first_trial(api, *, trial, source_mp4, source_sha, out_dir,
                              source_event_context=(), teams=None):
    out_dir.mkdir(parents=True, exist_ok=True)
    if api is None:
        return {"feedback": [{"status": "AWAITING_VIDEO_REVIEW",
                              "reason": "no_approved_video_call_available"}],
                "event_observations": []}
    try:
        refs = _story_review_frames(trial, source_mp4, out_dir)
    except (OSError, ValueError, RuntimeError) as exc:
        return {"feedback": [{"status": "SOURCE_FOOTAGE_UNAVAILABLE",
                              "reason": f"{type(exc).__name__}:{exc}"}],
                "event_observations": []}
    try:
        context = {
            "events": trial["events"],
            "source_event_context": list(source_event_context),
            "teams": teams or {},
            "windows": [
                {k: w.get(k) for k in ("candidate_id", "source_pts_start", "source_pts_end",
                                      "event_ids", "existing_segment_id")}
                for w in trial["windows"]
            ],
            "frame_refs": [
                {k: ref[k] for k in ("frame_id", "role", "window_id", "event_ids", "source_pts_sec")}
                for ref in refs.values()
            ],
        }
        prompt = (
            "Verify the listed events from source-bound stills in original time order. "
            "Use the surrounding source event timeline, including human annotations, "
            "for event facts and timing. Report what the sampled frames support or "
            "clearly contradict. Cite candidate frames bound to each selected event. "
            "Use UNCERTAIN if the sampled frames do not show the action or attribution "
            "clearly. Do not infer team numbers from kit color without a supplied mapping. "
            "If an event is visible only as a replay "
            "or slow-motion shot, mark it CONTRADICTED. First-live certification requires "
            "separate evidence. Return one compact JSON object with one row per event. "
            "Use short frame IDs and one brief, factual reason. "
            "{events:[{event_id,status:SUPPORTED|CONTRADICTED|UNCERTAIN,reason,frame_ids}]}\n"
            + json.dumps(context, ensure_ascii=False, separators=(",", ":"))
        )
        write_json(out_dir / "review_input.json", {
            "source_sha256": source_sha, "prompt": prompt, "frame_refs": list(refs.values()),
        })
        raw = api.vision_json(
            prompt=prompt, frame_paths=[Path(r["path"]) for r in refs.values()],
            frame_ids=list(refs), frame_bindings=list(refs.values()),
            mock_obj={"events": []},
        )
        content = str(raw.get("content") or "")
        (out_dir / "review_response.txt").write_text(content, encoding="utf-8")
        write_json(out_dir / "review_usage.json", _call_audit_from_raw(raw))
        if raw.get("provider_mode") not in ("real", "openai_compatible") or (
            str(raw.get("finish_reason") or "").lower() in ("length", "content_filter")
        ):
            raise ValueError("video_review_not_real_or_truncated")
        parsed = parse_model_json(content)
    except Exception as exc:
        return {"feedback": [{"status": "AWAITING_VIDEO_REVIEW",
                              "reason": f"{type(exc).__name__}:{exc}"}],
                "event_observations": []}
    observations, feedback = _assess_observations(trial, parsed, refs)
    write_json(out_dir / "event_observations.json", observations)
    return {"feedback": feedback, "event_observations": observations}
