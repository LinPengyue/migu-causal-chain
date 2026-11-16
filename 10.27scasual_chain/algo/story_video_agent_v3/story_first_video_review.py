"""Source observations for a Planner-selected story trial."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from story_video_agent.frames import FrameBudget, FrameStore
from story_video_agent.media import probe_video

from .story_narrative_fit import SCHEMA, _sha_file, context_for_candidate
from .story_first_poc_cli import parse_model_json, write_json
from .story_paid_eval import _call_audit_from_raw


def _story_review_frames(trial, edl, source_mp4, out_dir):
    media = probe_video(source_mp4)
    store = FrameStore(media, out_dir=out_dir / "source_frames",
                       budget=FrameBudget(max_frames=6 * len(trial["windows"]) + len(trial["events"])))
    event_pts = {row["event_id"]: row["source_pts_sec"] for row in trial["events"]}
    refs, contexts = {}, {}
    for window in trial["windows"]:
        wid = window["candidate_id"]
        roles = {"candidate": window}
        if not window.get("existing_segment_id"):
            context = context_for_candidate(window, edl)
            if not context["before"] or not context["after"]:
                raise ValueError("missing_adjacent_triplet_context:" + wid)
            roles = {role: (window if role == "candidate" else context[role])
                     for role in ("before", "candidate", "after")}
            contexts[wid] = context
        for role, span in roles.items():
            start, end = span["source_pts_start"], span["source_pts_end"]
            times = {start + fraction * (end - start): [] for fraction in (0.3, 0.7)}
            if role == "candidate":
                for eid in window["event_ids"]:
                    times.setdefault(event_pts[eid], []).append(eid)
            for idx, (target, event_ids) in enumerate(sorted(times.items())):
                frame = store.extract_at(
                    target, gap_id=f"{wid}:{role}",
                    tool="story_first_source_review",
                )
                pts = frame.actual_media_sec
                if (frame.pts_status != "pts" or pts is None
                        or not start - 0.05 <= pts <= end + 0.05):
                    raise ValueError("decoded_pts_outside_review_window:" + wid)
                fid = f"{wid}:{role}:{idx}"
                refs[fid] = {
                    "role": role, "frame_id": fid, "window_id": wid,
                    "event_ids": event_ids,
                    "source_pts_sec": pts, "path": str(frame.path),
                    "sha256": _sha_file(Path(frame.path)),
                    "requested_media_sec": frame.requested_media_sec,
                    "actual_media_sec": pts, "pts_status": "pts",
                }
    store.write_manifest(out_dir / "frame_extraction_manifest.json")
    return refs, contexts


def _assess_observations(trial, parsed, refs):
    feedback = []
    for key, id_key, expected in (
        ("events", "event_id", {e["event_id"]: {e["event_id"]} for e in trial["events"]}),
        ("relations", "relation_id", {
            r["relation_id"]: {r["source_event_id"], r["target_event_id"]}
            for r in trial["relations"]
        }),
    ):
        rows = parsed.get(key)
        rows = rows if isinstance(rows, list) else []
        for ident, required in expected.items():
            matches = [row for row in rows if isinstance(row, Mapping) and row.get(id_key) == ident]
            row = matches[0] if len(matches) == 1 else {}
            cited = row.get("frame_ids")
            evidence = set()
            if isinstance(cited, list) and all(isinstance(f, str) and f in refs for f in cited):
                evidence = {eid for f in cited for eid in refs[f]["event_ids"]}
            reason = str(row.get("reason") or "").strip()
            if row.get("status") != "SUPPORTED" or not required <= evidence or not reason:
                feedback.append({
                    id_key: ident, "event_ids": sorted(required),
                    "status": row.get("status") if row.get("status") in (
                        "CONTRADICTED", "UNCERTAIN",
                    ) else "UNCERTAIN",
                    "reason": (reason or "missing_bound_visual_support")[:600],
                })
    return feedback


def observe_story_first_trial(api, *, trial, edl, source_mp4, source_sha, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    if api is None:
        return {"feedback": [{"status": "AWAITING_VIDEO_REVIEW",
                              "reason": "no_approved_video_call_available"}],
                "fit_records": {}}
    try:
        refs, contexts = _story_review_frames(trial, edl, source_mp4, out_dir)
        context = {
            "trial": trial,
            "frame_refs": [{k: v for k, v in ref.items() if k not in ("path", "sha256")}
                           for ref in refs.values()],
        }
        prompt = (
            "Review this proposed story from ordered, source-bound still frames. "
            "Check each event and each proposed relation separately. Cite the supplied "
            "candidate frames for that event or both relation endpoints. If the evidence is "
            "ambiguous, specify what the next observation must resolve. Chronology and action "
            "similarity alone do not establish a causal relation. Judge the selected events "
            "and stated trial purpose. Other details in the original proposal are context "
            "and may have been explicitly dropped. Opposing teams may act, "
            "but the attribution must be accurate. If motion, attribution or the relation "
            "cannot be determined, return UNCERTAIN. Do not certify first live; flag visible "
            "replay/slow motion as CONTRADICTED. For each new window also assess BEFORE, "
            "CANDIDATE, AFTER in the current cut and name the specific story information it "
            "contributes. The trial may combine more than one clip. Return compact JSON "
            "with events:[{event_id,status:SUPPORTED|CONTRADICTED|UNCERTAIN,reason,frame_ids}], "
            "relations:[{relation_id,status,reason,frame_ids}], "
            "fit:[{window_id,verdict:SUPPORTS_INSERT|REJECT_INSERT|UNCERTAIN,story_function,"
            "before_to_candidate,candidate_to_after,new_story_information,baseline_comparison,"
            "missing_information_addressed,falsifiable_gain,evidence_frame_ids}]. "
            "Cite all three roles for each fit result.\n" + json.dumps(context, ensure_ascii=False)
        )
        write_json(out_dir / "review_input.json", {
            "source_sha256": source_sha, "prompt": prompt, "frame_refs": list(refs.values()),
        })
        raw = api.vision_json(
            prompt=prompt, frame_paths=[Path(r["path"]) for r in refs.values()],
            frame_ids=list(refs), frame_bindings=list(refs.values()),
            mock_obj={"events": [], "relations": [], "fit": []},
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
                "fit_records": {}}
    feedback = _assess_observations(trial, parsed, refs)
    fit_records = {}
    fit_rows = parsed.get("fit")
    for review in fit_rows if isinstance(fit_rows, list) else []:
        if not isinstance(review, Mapping):
            continue
        wid = str(review.get("window_id") or "")
        if wid not in contexts:
            continue
        ctx = contexts[wid]
        fit_records[wid] = {
            "schema": SCHEMA, "source_sha256": source_sha, "issue_id": ctx["issue_id"],
            "source_pts_start": ctx["candidate"]["source_pts_start"],
            "source_pts_end": ctx["candidate"]["source_pts_end"],
            **{f"{r}_segment_id": ctx[r]["segment_id"] for r in ("before", "after")},
            **{f"{r}_pts_{k}": ctx[r][f"source_pts_{k}"]
               for r in ("before", "after") for k in ("start", "end")},
            "review_method": "vlm_ordered_triplet_frames",
            "verdict": review.get("verdict"),
            "frame_refs": [r for r in refs.values() if r["window_id"] == wid],
            "narrative_review": dict(review),
        }
    return {"feedback": feedback, "fit_records": fit_records}
