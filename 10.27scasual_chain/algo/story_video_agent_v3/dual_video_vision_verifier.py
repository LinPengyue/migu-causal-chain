"""Dual-video vision Verifier — real frames via ApiProvider.vision_json.

Text/EDL/ffprobe-only paths must NOT authorize semantic ACCEPT.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

from story_video_agent.api_provider import ApiCallError, ApiConfigError, ApiProvider
from story_video_agent.frames import FrameBudget, FrameBudgetExhausted, FrameStore
from story_video_agent.media import probe_video

from .fresh_e2e_cli import edl_diff
from .story_paid_eval import SYSTEM_VERIFIER, _parse_model_json_lenient
from .story_timeline import (
    aligned_narrative_sample_plan,
    build_story_timeline,
    story_time_to_media,
)

# Keep vision payload small under paid caps (one HTTP call).
MAX_PAIRS = 4
MAX_FRAMES_TOTAL = 8


def _changed_segment_ids(edl_delta: Mapping[str, Any]) -> List[str]:
    ids: List[str] = []
    for sid in edl_delta.get("added_segment_ids") or []:
        ids.append(str(sid))
    for sid in edl_delta.get("removed_segment_ids") or []:
        ids.append(str(sid))
    for ch in edl_delta.get("changed_segments") or []:
        if isinstance(ch, dict) and ch.get("segment_id"):
            ids.append(str(ch["segment_id"]))
    # unique preserve order
    out: List[str] = []
    for x in ids:
        if x not in out:
            out.append(x)
    return out


def extract_aligned_dual_frames(
    *,
    baseline_mp4: Path,
    candidate_mp4: Path,
    baseline_edl: Sequence[Mapping[str, Any]],
    candidate_edl: Sequence[Mapping[str, Any]],
    work_dir: Path,
    max_pairs: int = MAX_PAIRS,
) -> Dict[str, Any]:
    """Sample comparable narrative positions from both finished cuts."""
    work_dir.mkdir(parents=True, exist_ok=True)
    if not baseline_mp4.is_file() or not candidate_mp4.is_file():
        return {
            "ok": False,
            "error": "missing_baseline_or_candidate_mp4",
            "frames": [],
            "sent_frame_ids": [],
            "pairs": [],
        }
    base_tl = build_story_timeline(baseline_edl)
    cand_tl = build_story_timeline(candidate_edl)
    delta = edl_diff([dict(r) for r in baseline_edl], [dict(r) for r in candidate_edl])
    plan = aligned_narrative_sample_plan(
        base_tl,
        cand_tl,
        changed_segment_ids=_changed_segment_ids(delta),
        max_slots=max_pairs,
    )
    if not plan:
        return {
            "ok": False,
            "error": "no_aligned_narrative_slots",
            "frames": [],
            "sent_frame_ids": [],
            "pairs": [],
            "baseline_timeline": base_tl,
            "candidate_timeline": cand_tl,
        }

    b_store = FrameStore(
        probe_video(baseline_mp4),
        out_dir=work_dir / "baseline_frames",
        budget=FrameBudget(max_frames=MAX_FRAMES_TOTAL),
    )
    c_store = FrameStore(
        probe_video(candidate_mp4),
        out_dir=work_dir / "candidate_frames",
        budget=FrameBudget(max_frames=MAX_FRAMES_TOTAL),
    )

    frames: List[Dict[str, Any]] = []
    pairs: List[Dict[str, Any]] = []
    sent_ids: List[str] = []

    def _pull(store: FrameStore, story_sec: float, tl: Mapping[str, Any], *, video_tag: str, slot: str, idx: int):
        mapped = story_time_to_media(tl, story_sec) or {}
        # Story playback time on the finished cut == sample time on story_mp4.
        sample_t = float(story_sec)
        dur = float(tl.get("story_duration_sec") or 0.0)
        sample_t = min(max(0.05, sample_t), max(0.05, dur - 0.05) if dur > 0.1 else sample_t)
        fid = f"{video_tag}_{slot}_{idx}"
        try:
            rec = store.extract_at(sample_t, gap_id=f"dual_{video_tag}", tool="dual_video_verifier")
            d = rec.to_dict()
        except FrameBudgetExhausted as exc:
            return {
                "ok": False,
                "error": f"FrameBudgetExhausted:{exc}",
                "frame_id": fid,
                "video_tag": video_tag,
            }
        d["frame_id"] = fid
        d["video_tag"] = video_tag
        d["narrative_slot"] = slot
        d["story_sec"] = round(sample_t, 3)
        d["source_media_sec"] = mapped.get("media_sec")
        d["segment_id"] = mapped.get("segment_id")
        d["role"] = mapped.get("role")
        d["is_placeholder_story_region"] = bool(mapped.get("is_placeholder"))
        d["path"] = d.get("path")
        return {"ok": True, "frame": d}

    for i, slot in enumerate(plan[:max_pairs]):
        ns = str(slot.get("narrative_slot") or f"slot_{i}")
        b = _pull(
            b_store,
            float(slot["baseline_story_sec"]),
            base_tl,
            video_tag="baseline",
            slot=ns,
            idx=i,
        )
        c = _pull(
            c_store,
            float(slot["candidate_story_sec"]),
            cand_tl,
            video_tag="candidate",
            slot=ns,
            idx=i,
        )
        pair = {
            "narrative_slot": ns,
            "reason": slot.get("reason"),
            "baseline": b,
            "candidate": c,
        }
        pairs.append(pair)
        if b.get("ok") and b.get("frame"):
            frames.append(b["frame"])
            sent_ids.append(str(b["frame"]["frame_id"]))
        if c.get("ok") and c.get("frame"):
            frames.append(c["frame"])
            sent_ids.append(str(c["frame"]["frame_id"]))

    usable = [f for f in frames if f.get("path") and Path(f["path"]).is_file()]
    return {
        "ok": len(usable) >= 4 and any(f.get("video_tag") == "baseline" for f in usable)
        and any(f.get("video_tag") == "candidate" for f in usable),
        "frames": usable,
        "all_extracted": frames,
        "sent_frame_ids": [str(f["frame_id"]) for f in usable],
        "pairs": pairs,
        "sample_plan": plan,
        "baseline_timeline": base_tl,
        "candidate_timeline": cand_tl,
        "edl_delta": delta,
        "claims_full_video_watch": False,
        "observation_method": "aligned_narrative_dual_frame_pairs",
        "note": (
            "Frames are story-slot aligned (opening/development/turn/climax/ending/"
            "edit boundaries), not absolute-second twins. Sparse frames ≠ full watch."
        ),
    }


def _collect_cited_frame_ids(validated: Mapping[str, Any]) -> Set[str]:
    cited: Set[str] = set()

    def _walk_refs(refs: Any) -> None:
        if not isinstance(refs, list):
            return
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            for key in ("frame_id", "id", "ref"):
                v = ref.get(key)
                if v is None:
                    continue
                s = str(v)
                if s.startswith("baseline_") or s.startswith("candidate_") or "frame" in s.lower():
                    cited.add(s)
                # also accept exact sent ids later via intersection
                cited.add(s)

    for item in validated.get("evidence_of_improvement") or []:
        if isinstance(item, dict):
            _walk_refs(item.get("evidence_refs"))
    dims = validated.get("dimensions") or {}
    if isinstance(dims, dict):
        for d in dims.values():
            if isinstance(d, dict):
                _walk_refs(d.get("evidence_refs"))
    return cited


def validate_visual_verifier_payload(
    validated: Mapping[str, Any],
    *,
    sent_frame_ids: Sequence[str],
) -> Dict[str, Any]:
    """Fail-closed: improved claims require citations to frames actually sent."""
    sent = {str(x) for x in sent_frame_ids}
    out = dict(validated)
    reasons: List[str] = []
    delta = str(out.get("quality_delta_vs_baseline") or "").strip().lower()
    cited = _collect_cited_frame_ids(out)
    cited_sent = {c for c in cited if c in sent}

    if not sent:
        reasons.append("no_frames_sent")
        out["quality_delta_vs_baseline"] = "NOT_EVALUATED"
        out["accept_candidate"] = False
        out["semantic_status"] = "NOT_EVALUATED"
        return {
            "ok_for_semantic_accept": False,
            "semantic_verification_status": "NOT_EVALUATED",
            "validated": out,
            "reasons": reasons,
            "cited_sent_frame_ids": sorted(cited_sent),
            "sent_frame_ids": sorted(sent),
        }

    if delta in ("improved", "better"):
        eoi = out.get("evidence_of_improvement") or []
        if not eoi:
            reasons.append("improved_without_evidence_of_improvement")
            out["quality_delta_vs_baseline"] = "NOT_EVALUATED"
            out["accept_candidate"] = False
        elif not cited_sent:
            reasons.append("improved_evidence_refs_not_in_sent_frames")
            out["quality_delta_vs_baseline"] = "NOT_EVALUATED"
            out["accept_candidate"] = False
            reasons.append("refuse_text_only_or_unknown_frame_citations")
        else:
            # Require at least one baseline and one candidate citation when claiming improve.
            has_b = any(c.startswith("baseline_") for c in cited_sent)
            has_c = any(c.startswith("candidate_") for c in cited_sent)
            if not (has_b and has_c):
                reasons.append("improved_requires_both_baseline_and_candidate_frame_citations")
                out["quality_delta_vs_baseline"] = "NOT_EVALUATED"
                out["accept_candidate"] = False

    # Dimensions claiming improved without video frame refs → force NOT_EVALUATED
    dims = out.get("dimensions") if isinstance(out.get("dimensions"), dict) else {}
    fixed_dims: Dict[str, Any] = {}
    for name, d in dims.items():
        if not isinstance(d, dict):
            continue
        dd = dict(d)
        if str(dd.get("status") or "").lower() == "improved":
            refs = dd.get("evidence_refs") or []
            ok_refs = False
            for ref in refs:
                if isinstance(ref, dict):
                    tok = str(ref.get("frame_id") or ref.get("ref") or ref.get("id") or "")
                    if tok in sent:
                        ok_refs = True
                        break
            if not ok_refs:
                dd["status"] = "NOT_EVALUATED"
                dd["score"] = None
                reasons.append(f"dim_{name}_improved_without_sent_frame_refs")
        fixed_dims[name] = dd
    out["dimensions"] = fixed_dims

    hard = list(out.get("hard_vetoes") or [])
    accept = bool(out.get("accept_candidate")) and not hard
    if str(out.get("quality_delta_vs_baseline") or "").lower() not in ("improved", "better"):
        accept = False
        if out.get("accept_candidate"):
            reasons.append("refuse_accept_without_validated_improved_delta")
        out["accept_candidate"] = False

    if accept and not cited_sent:
        accept = False
        out["accept_candidate"] = False
        reasons.append("refuse_accept_without_sent_visual_citations")

    semantic = "PASSED" if accept else (
        "FAILED" if hard else "NOT_EVALUATED"
    )
    if accept:
        semantic = "PASSED"
    elif hard:
        semantic = "FAILED"
    else:
        semantic = "NOT_EVALUATED"
        out.setdefault("quality_delta_vs_baseline", "NOT_EVALUATED")

    out["semantic_status"] = semantic
    return {
        "ok_for_semantic_accept": bool(accept) and semantic == "PASSED",
        "semantic_verification_status": semantic,
        "validated": out,
        "reasons": reasons,
        "cited_sent_frame_ids": sorted(cited_sent),
        "sent_frame_ids": sorted(sent),
    }


def run_dual_video_vision_verifier(
    api: ApiProvider,
    *,
    baseline_mp4: Path,
    candidate_mp4: Path,
    baseline_edl: Sequence[Mapping[str, Any]],
    candidate_edl: Sequence[Mapping[str, Any]],
    work_dir: Path,
    audit_dir: Path,
    max_pairs: int = MAX_PAIRS,
) -> Dict[str, Any]:
    """Vision-backed dual cut comparison. No frames → NOT_EVALUATED (never text ACCEPT)."""
    audit_dir.mkdir(parents=True, exist_ok=True)
    pack = extract_aligned_dual_frames(
        baseline_mp4=baseline_mp4,
        candidate_mp4=candidate_mp4,
        baseline_edl=baseline_edl,
        candidate_edl=candidate_edl,
        work_dir=work_dir,
        max_pairs=max_pairs,
    )
    (audit_dir / "dual_frame_pack.json").write_text(
        json.dumps(
            {
                k: pack.get(k)
                for k in (
                    "ok", "error", "sent_frame_ids", "pairs", "sample_plan",
                    "claims_full_video_watch", "observation_method", "note", "edl_delta",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if not pack.get("ok"):
        return {
            "ok": False,
            "provider_mode": "skipped_insufficient_frames",
            "error": pack.get("error") or "insufficient_aligned_frames",
            "validated": {
                "hard_vetoes": [],
                "dimensions": {},
                "evidence_of_improvement": [],
                "quality_delta_vs_baseline": "NOT_EVALUATED",
                "accept_candidate": False,
                "semantic_status": "NOT_EVALUATED",
            },
            "ok_for_semantic_accept": False,
            "semantic_verification_status": "NOT_EVALUATED",
            "sent_frame_ids": pack.get("sent_frame_ids") or [],
            "frame_pack": pack,
            "reasons": ["insufficient_visual_evidence"],
        }

    frames = list(pack["frames"])
    paths = [Path(f["path"]) for f in frames]
    fids = [str(f["frame_id"]) for f in frames]
    bindings = []
    for f in frames:
        bindings.append({
            "frame_id": f["frame_id"],
            "requested_media_sec": f.get("story_sec"),
            "actual_media_sec": f.get("actual_media_sec") or f.get("story_sec"),
            "pts_status": f.get("pts_status") or "story_playback",
            "video_tag": f.get("video_tag"),
            "narrative_slot": f.get("narrative_slot"),
            "segment_id": f.get("segment_id"),
            "source_media_sec": f.get("source_media_sec"),
        })

    meta_lines = []
    for f in frames:
        meta_lines.append(
            f"{f['frame_id']}: video={f.get('video_tag')} slot={f.get('narrative_slot')} "
            f"story_sec={f.get('story_sec')} source_pts={f.get('source_media_sec')} "
            f"segment_id={f.get('segment_id')} role={f.get('role')}"
        )
    from .truncated_response_recovery import SHORT_PER_REVISION_JSON_SCHEMA

    prompt = (
        f"{SYSTEM_VERIFIER}\n"
        "Compare BASELINE vs CANDIDATE using ONLY provided frames (NOT full-video watch).\n"
        "Prefer SHORT structured output to avoid truncation. "
        f"Primary schema: {SHORT_PER_REVISION_JSON_SCHEMA}\n"
        "For each revision, judge whether the ORIGINAL diagnosed issue was solved; "
        "BETTER aesthetics alone is insufficient. If a fix introduces a new defect, "
        "set introduced_new_defect=true (must not ACCEPT).\n"
        "Also include compact top-level: hard_vetoes, quality_delta_vs_baseline, "
        "accept_candidate=false unless original issues resolved AND no new defects AND "
        "evidence_refs cite sent baseline_* and candidate_* frames.\n"
        "BETTER does not auto-ACCEPT. Cite only FRAME_MANIFEST ids.\n"
        f"FRAME_MANIFEST:\n" + "\n".join(meta_lines) + "\n"
    )
    mock = {
        "hard_vetoes": [],
        "dimensions": {},
        "evidence_of_improvement": [],
        "quality_delta_vs_baseline": "NOT_EVALUATED",
        "accept_candidate": False,
        "reasons": ["mock"],
    }
    try:
        raw = api.vision_json(
            prompt=prompt,
            frame_paths=paths,
            frame_ids=fids,
            mock_obj=mock,
            frame_bindings=bindings,
        )
    except (ApiConfigError, ApiCallError) as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}:{exc}",
            "provider_mode": "degraded",
            "validated": {
                "hard_vetoes": [],
                "dimensions": {},
                "evidence_of_improvement": [],
                "quality_delta_vs_baseline": "NOT_EVALUATED",
                "accept_candidate": False,
                "semantic_status": "NOT_EVALUATED",
            },
            "ok_for_semantic_accept": False,
            "semantic_verification_status": "NOT_EVALUATED",
            "sent_frame_ids": fids,
            "frame_pack": pack,
            "reasons": ["vision_api_failed"],
        }

    content = str(raw.get("content") or "")
    parsed = None
    parse_error = None
    try:
        parsed = _parse_model_json_lenient(content)
    except Exception as exc:  # noqa: BLE001
        parse_error = f"parse:{type(exc).__name__}:{exc}"

    from .truncated_response_recovery import recover_per_revision_judgments

    recovery = recover_per_revision_judgments(
        content,
        sent_frame_ids=fids,
        finish_reason=raw.get("finish_reason"),
        parse_error=parse_error,
    )
    (audit_dir / "dual_vision_verifier_raw.json").write_text(
        json.dumps(
            {
                "raw_excerpt": content[:8000],
                "parsed": parsed,
                "parse_error": parse_error,
                "usage": raw.get("usage"),
                "sent_frame_ids": fids,
                "finish_reason": raw.get("finish_reason"),
                "truncated_recovery": {
                    k: recovery.get(k)
                    for k in (
                        "status_tags",
                        "n_valid_recovered",
                        "n_rejected",
                        "extraction",
                        "raw_response_sha256",
                    )
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (audit_dir / "truncated_recovery.json").write_text(
        json.dumps(recovery, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    mode = str(raw.get("provider_mode") or "")
    if mode == "openai_compatible":
        mode = "real"

    # If full parse failed, rebuild a fail-closed payload that still preserves
    # recovered per-revision judgments (never invent ACCEPT/IMPROVED).
    if parse_error or not parsed:
        recovered = list(recovery.get("recovered") or [])
        parsed = {
            "hard_vetoes": [],
            "dimensions": {},
            "evidence_of_improvement": [],
            "quality_delta_vs_baseline": "NOT_EVALUATED",
            "accept_candidate": False,
            "semantic_status": "NOT_EVALUATED",
            "per_revision_judgments": [r.get("judgment") for r in recovered if r.get("judgment")],
            "recovery_status_tags": recovery.get("status_tags") or [],
            "reasons": ["parse_failed_or_truncated", "BETTER_not_auto_ACCEPT"],
        }
        # Still fail-closed for ACCEPT even if some items recovered as BETTER.
        gate = validate_visual_verifier_payload(parsed, sent_frame_ids=fids)
        return {
            "ok": mode == "real" and bool(recovered),
            "provider_mode": mode,
            "error": parse_error or "empty_parsed",
            "validated": gate["validated"],
            "ok_for_semantic_accept": False,
            "semantic_verification_status": "NOT_EVALUATED",
            "sent_frame_ids": fids,
            "cited_sent_frame_ids": gate.get("cited_sent_frame_ids"),
            "frame_pack": pack,
            "est_cost_usd": raw.get("est_cost_usd"),
            "usage": raw.get("usage"),
            "reasons": list(gate.get("reasons") or []) + ["truncated_recovery_fail_closed_accept"],
            "vision_backed": bool(fids),
            "truncated_recovery": recovery,
            "per_revision_judgments_recovered": recovered,
        }

    gate = validate_visual_verifier_payload(parsed, sent_frame_ids=fids)
    # Attach any extra recovered per-revision rows for case binding.
    if recovery.get("recovered") and not parsed.get("per_revision_judgments"):
        parsed = dict(gate["validated"])
        parsed["per_revision_judgments"] = [
            r.get("judgment") for r in recovery["recovered"] if r.get("judgment")
        ]
    return {
        "ok": mode == "real",
        "provider_mode": mode,
        "validated": gate["validated"],
        "ok_for_semantic_accept": gate["ok_for_semantic_accept"],
        "semantic_verification_status": gate["semantic_verification_status"],
        "sent_frame_ids": fids,
        "cited_sent_frame_ids": gate.get("cited_sent_frame_ids"),
        "frame_pack": pack,
        "est_cost_usd": raw.get("est_cost_usd"),
        "usage": raw.get("usage"),
        "reasons": gate.get("reasons") or [],
        "vision_backed": True,
        "truncated_recovery": recovery,
        "per_revision_judgments_recovered": recovery.get("recovered") or [],
    }


def text_only_verifier_forbidden_result() -> Dict[str, Any]:
    """Explicit reject path when caller attempts text/EDL-only verification."""
    return {
        "ok": False,
        "provider_mode": "text_only_forbidden",
        "error": "text_or_edl_only_verifier_forbidden",
        "validated": {
            "hard_vetoes": [],
            "dimensions": {},
            "evidence_of_improvement": [],
            "quality_delta_vs_baseline": "NOT_EVALUATED",
            "accept_candidate": False,
            "semantic_status": "NOT_EVALUATED",
        },
        "ok_for_semantic_accept": False,
        "semantic_verification_status": "NOT_EVALUATED",
        "sent_frame_ids": [],
        "reasons": ["text_only_verifier_cannot_authorize_accept"],
        "vision_backed": False,
    }
