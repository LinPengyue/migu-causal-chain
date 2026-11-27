"""One capped real-vision contextual review: BEFORE → CANDIDATE → AFTER.

No direct payment is made by this module. It is invoked only by the existing
authorized, bounded ApiProvider supplied from run_story_e2e. Offline calls are
not made. Ordered still frames are *not* equivalent to watching full video.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from .first_live_window_evidence import window_key
from .story_narrative_fit import (
    SCHEMA, context_for_candidate, validate_narrative_fit_review,
    _sha_file,
)


def run_vlm_narrative_triplet_review(
    api: Any,
    *,
    source_mp4: Path,
    source_sha: str,
    candidate: Mapping[str, Any],
    edl: Sequence[Mapping[str, Any]],
    out_dir: Path,
) -> Dict[str, Any]:
    """Video-context review with 2 source-PTS frames per role (6 total).

    A structured, source-bound model judgment is a *candidate prior*, not
    established improvement. The dual-video Verifier and human preview remain
    the independent authority on the edited cut.
    """
    ctx = context_for_candidate(candidate, edl)
    before, after, cand = ctx["before"], ctx["after"], ctx["candidate"]
    if not before or not after:
        return {"ok": False, "error": "missing_adjacent_triplet_context"}
    if not Path(source_mp4).is_file():
        return {"ok": False, "error": "source_mp4_missing"}
    try:
        from story_video_agent.frames import FrameBudget, FrameStore
        from story_video_agent.media import probe_video
        media = probe_video(Path(source_mp4))
        store = FrameStore(
            media, out_dir=out_dir / "source_frames",
            budget=FrameBudget(max_frames=6),
        )
        refs = []
        bindings = []
        paths = []
        ids = []
        for role, win in (("before", before), ("candidate", cand), ("after", after)):
            start = float(win["source_pts_start"])
            end = float(win["source_pts_end"])
            if end-start < 0.3:
                return {"ok": False, "error": f"too_short_{role}_window"}
            # Two distinct observation points, not a generic mid-frame shot.
            for idx, frac in enumerate((0.3, 0.7)):
                target = start + (end-start)*frac
                fr = store.extract_at(
                    target, gap_id=f"narrative_fit_{role}",
                    tool="narrative_fit_triplet",
                )
                if fr.actual_media_sec is None or fr.pts_status != "pts":
                    return {"ok": False, "error": "decoder_pts_missing", "role": role}
                actual = float(fr.actual_media_sec)
                if not start-0.05 <= actual <= end+0.05:
                    return {
                        "ok": False, "error": "decoded_pts_outside_role_window",
                        "role": role, "actual_pts": actual,
                    }
                path = Path(fr.path)
                fid = f"{role}_{idx}_{fr.frame_id}"
                ids.append(fid)
                paths.append(path)
                refs.append({
                    "role": role, "frame_id": fid,
                    "source_pts_sec": actual,
                    "path": str(path),
                    "sha256": _sha_file(path),
                })
                bindings.append({
                    "frame_id": fid,
                    "requested_media_sec": float(fr.requested_media_sec),
                    "actual_media_sec": actual,
                    "pts_status": fr.pts_status,
                })
        out_dir.mkdir(parents=True, exist_ok=True)
        store.write_manifest(out_dir / "frame_extraction_manifest.json")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"frame_extract:{type(exc).__name__}:{exc}"}

    prompt = (
        "You are evaluating whether an inserted scene IMPROVES an edited football "
        "story, not whether it is a highlight. Observe the six ORDERED source frames: "
        "two BEFORE, two CANDIDATE, two AFTER. These are stills, NOT native video; "
        "motion and exact causal connection may be uncertain. The three sections "
        "are different moments in the match. A large source-time skip is normal. "
        "Never infer a causal bridge solely from event heat, shot count or proximity. "
        "The candidate must supply SPECIFIC new story information required to "
        "understand the change between adjacent beats; thematic similarity alone "
        "is not enough. Prefer REJECT_INSERT if redundant or distracting; "
        "UNCERTAIN when frames cannot resolve story fit. "
        "Return one short JSON object: "
        "{verdict: SUPPORTS_INSERT|REJECT_INSERT|UNCERTAIN, "
        "story_function: string, before_to_candidate: string, "
        "candidate_to_after: string, new_story_information: string, "
        "baseline_comparison: string, missing_information_addressed: string|null, "
        "falsifiable_gain: string|null, evidence_frame_ids: [string], "
        "confidence: number}. "
        "For SUPPORTS_INSERT, cite at least one supplied frame_id from EACH "
        "of before/candidate/after and give concrete, non-generic explanations "
        "of how the candidate changes audience understanding. Never cite unseen frames. "
        "The decision is only a PRIOR for full candidate rendering and independent verification. "
        f"ISSUE_ID:{candidate.get('issue_id')} "
        f"MISSING_INFORMATION:{candidate.get('missing_narrative_info')} "
        f"BEFORE_ROLE:{before.get('role')} AFTER_ROLE:{after.get('role')} "
        f"FRAMES:{json.dumps(bindings, ensure_ascii=False)}"
    )
    try:
        from .story_paid_eval import _parse_model_json_lenient
        raw = api.vision_json(
            prompt=prompt,
            frame_paths=paths,
            frame_ids=ids,
            mock_obj={"verdict": "UNCERTAIN", "evidence_frame_ids": []},
            frame_bindings=bindings,
        )
        mode = str(raw.get("provider_mode") or "")
        if mode not in ("real", "openai_compatible"):
            return {"ok": False, "error": "no_real_vision_provider", "provider_mode": mode}
        parsed = _parse_model_json_lenient(str(raw.get("content") or ""))
        if not isinstance(parsed, Mapping):
            return {"ok": False, "error": "invalid_review_json"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"vlm_review:{type(exc).__name__}:{exc}"}

    narrative = {
        k: parsed.get(k) for k in (
            "story_function", "before_to_candidate", "candidate_to_after",
            "new_story_information", "baseline_comparison",
            "missing_information_addressed", "falsifiable_gain",
            "evidence_frame_ids",
        )
    }
    record = {
        "schema": SCHEMA,
        "source_sha256": str(source_sha),
        "source_pts_start": cand.get("source_pts_start"),
        "source_pts_end": cand.get("source_pts_end"),
        "issue_id": candidate.get("issue_id"),
        "before_segment_id": before.get("segment_id"),
        "after_segment_id": after.get("segment_id"),
        "before_pts_start": before["source_pts_start"],
        "before_pts_end": before["source_pts_end"],
        "after_pts_start": after["source_pts_start"],
        "after_pts_end": after["source_pts_end"],
        "review_method": "vlm_ordered_triplet_frames",
        "verdict": str(parsed.get("verdict") or "UNCERTAIN").upper(),
        "frame_refs": refs,
        "narrative_review": narrative,
        "observation_method": "six_ordered_source_frames_not_full_video",
    }
    validation = validate_narrative_fit_review(
        record, candidate=candidate, source_sha=source_sha, edl=edl,
        require_files_exist=True,
    )
    report = {
        "ok": validation.get("binding_valid") is True,
        "validation": validation,
        "review": record,
        "provider_mode": mode,
        "source_sha256": source_sha,
        "source_review_key": window_key(
            str(source_sha), float(cand["source_pts_start"]),
            float(cand["source_pts_end"]),
        ),
        "usage": raw.get("usage"),
        "est_cost_usd": raw.get("est_cost_usd"),
        "finish_reason": raw.get("finish_reason"),
        "claims_full_video_watch": False,
        "note": "Video-fit hypothesis only; not a measured quality improvement.",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "narrative_fit_review.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report
