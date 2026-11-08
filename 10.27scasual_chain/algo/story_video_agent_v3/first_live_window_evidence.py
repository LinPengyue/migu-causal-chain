"""Authoritative per-window first-LIVE evidence (source SHA + precise PTS).

Zero-HTTP local path: extract frames/clip from source MP4, hash bytes, write a
validated evidence record. Event-chain LIVE labels and raw booleans are never
sufficient to certify FIRST_LIVE_VERIFIED.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

SCHEMA = "v3a_first_live_window_evidence_v1"
TIMELINE_REVIEW_SCHEMA = "v3a_broadcast_timeline_review_v1"

# Evidence tiers (do not collapse).
BINDING_FRAME_BOUND_VALID = "FRAME_BOUND_VALID"
BINDING_INVALID = "BINDING_INVALID"
FIRST_LIVE_VERIFIED = "FIRST_LIVE_VERIFIED"
REPLAY_CONFIRMED = "REPLAY_CONFIRMED"
FIRST_LIVE_UNKNOWN = "UNKNOWN"
FIRST_LIVE_NOT_VERIFIED = "NOT_VERIFIED"


def _sha256_file(path: Path) -> Optional[str]:
    p = Path(path)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def window_key(source_sha: str, start: float, end: float) -> str:
    return f"{source_sha}|{float(start):.3f}:{float(end):.3f}"


def looks_like_content_hash(token: Any) -> bool:
    """True only for hex digests (frame *content*), not frame_ids like baseline_a."""
    if token is None:
        return False
    s = str(token).strip().lower()
    if s.startswith("sha256:"):
        s = s[7:]
    if len(s) not in (64, 40):  # sha256 or sha1
        return False
    return all(c in "0123456789abcdef" for c in s)


def edl_media_windows(edl: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Active cut rows with concrete source PTS."""
    out: List[Dict[str, Any]] = []
    for row in edl or []:
        if not isinstance(row, Mapping):
            continue
        if row.get("include_in_cut", True) is False:
            continue
        mi, mo = row.get("media_in"), row.get("media_out")
        try:
            a, b = float(mi), float(mo)
        except (TypeError, ValueError):
            continue
        if b <= a:
            continue
        out.append(
            {
                "segment_id": row.get("segment_id"),
                "source_pts_start": a,
                "source_pts_end": b,
                "role": row.get("role"),
                "is_replay": bool(row.get("is_replay")),
                "evidence_status": row.get("evidence_status"),
                "first_live_status": row.get("first_live_status"),
            }
        )
    return out


def diff_new_source_windows(
    parent_edl: Sequence[Mapping[str, Any]],
    candidate_edl: Sequence[Mapping[str, Any]],
    *,
    source_sha: Optional[str] = None,
    iou_match: float = 0.92,
) -> List[Dict[str, Any]]:
    """New source windows introduced by candidate vs parent (EDL diff, not apply_report).

    A window is new unless an ancestor row matches the same PTS span (high IoU).
    """
    sha = str(source_sha or "").strip() or "MISSING_SOURCE_SHA"
    parent = edl_media_windows(parent_edl)
    cand = edl_media_windows(candidate_edl)

    def _iou(a0: float, a1: float, b0: float, b1: float) -> float:
        lo, hi = max(a0, b0), min(a1, b1)
        inter = max(0.0, hi - lo)
        union = max(a1, b1) - min(a0, b0)
        return inter / union if union > 1e-9 else 0.0

    new_rows: List[Dict[str, Any]] = []
    for c in cand:
        matched = False
        for p in parent:
            if _iou(
                float(c["source_pts_start"]),
                float(c["source_pts_end"]),
                float(p["source_pts_start"]),
                float(p["source_pts_end"]),
            ) >= iou_match:
                matched = True
                break
        if matched:
            continue
        start = float(c["source_pts_start"])
        end = float(c["source_pts_end"])
        new_rows.append(
            {
                **c,
                "source_sha": sha,
                "key": window_key(sha, start, end),
                "origin": "edl_diff",
            }
        )
    return new_rows


def build_local_first_live_evidence_pack(
    *,
    source_mp4: Path,
    source_sha: str,
    pts_start: float,
    pts_end: float,
    out_dir: Path,
    segment_id: Optional[str] = None,
    n_frames: int = 3,
    require_not_replay_flags: bool = True,
) -> Dict[str, Any]:
    """Extract ordered frames; hash bytes; write a *binding* record only.

    Successful extraction + hash integrity ⇒ FRAME_BOUND_VALID.
    Never emits FIRST_LIVE_VERIFIED — that requires a distinct broadcast-timeline
    review artifact (see build_broadcast_timeline_review).
    """
    from .first_live_localize import extract_frame_accurate

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    source_mp4 = Path(source_mp4)
    start = float(pts_start)
    end = float(pts_end)
    if end <= start or not source_mp4.is_file():
        return {
            "schema": SCHEMA,
            "ok": False,
            "binding_status": BINDING_INVALID,
            "status": BINDING_INVALID,
            "first_live_status": FIRST_LIVE_NOT_VERIFIED,
            "reason": "invalid_window_or_missing_source",
        }
    actual_sha = _sha256_file(source_mp4)
    if actual_sha and source_sha and actual_sha != source_sha:
        return {
            "schema": SCHEMA,
            "ok": False,
            "binding_status": BINDING_INVALID,
            "status": BINDING_INVALID,
            "first_live_status": FIRST_LIVE_NOT_VERIFIED,
            "reason": "source_sha_mismatch",
            "expected_source_sha": source_sha,
            "actual_source_sha": actual_sha,
        }
    sha = source_sha or actual_sha or "MISSING_SOURCE_SHA"
    samples = []
    n = max(2, min(5, int(n_frames)))
    for i in range(n):
        t = start + (end - start) * (0.15 + 0.7 * i / max(1, n - 1))
        samples.append(round(t, 3))
    frames: List[Dict[str, Any]] = []
    frame_dir = out_dir / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    for i, t in enumerate(samples):
        fp = frame_dir / f"t{t:.3f}_{i}.jpg"
        meta = extract_frame_accurate(source_mp4, t, fp)
        if not meta.get("ok") or not meta.get("sha256"):
            return {
                "schema": SCHEMA,
                "ok": False,
                "binding_status": BINDING_INVALID,
                "status": BINDING_INVALID,
                "first_live_status": FIRST_LIVE_NOT_VERIFIED,
                "reason": f"frame_extract_failed@{t}",
                "frames": frames,
            }
        frames.append(
            {
                "frame_id": f"src_{sha[:8]}_{i}",
                "source_pts_sec": t,
                "path": str(fp),
                "sha256": meta["sha256"],
                "accurate_decode": True,
            }
        )
    unique_hashes = {f["sha256"] for f in frames}
    temporal_span_ok = (
        frames[0]["source_pts_sec"] >= start - 0.05
        and frames[-1]["source_pts_sec"] <= end + 0.05
        and frames[-1]["source_pts_sec"] > frames[0]["source_pts_sec"]
    )
    binding_ok = bool(temporal_span_ok)
    manifest = {
        "source_sha256": sha,
        "source_pts_start": start,
        "source_pts_end": end,
        "segment_id": segment_id,
        "frame_sha256": [f["sha256"] for f in frames],
        "frame_pts": [f["source_pts_sec"] for f in frames],
        "n_frames": len(frames),
        "n_unique_frame_hashes": len(unique_hashes),
        "identical_frame_hashes": len(unique_hashes) == 1,
        "temporal_span_ok": temporal_span_ok,
        "require_not_replay_flags": require_not_replay_flags,
        "producer": "local_source_mp4_frame_pack_v1",
        "claims_full_broadcast_timeline": False,
        "evidence_tier": "frame_binding_only",
        "note": (
            "FRAME_BOUND_VALID = source SHA + PTS + image-byte hashes only. "
            "Identical still hashes or sparse frames are NOT first-broadcast proof. "
            "FIRST_LIVE_VERIFIED requires a distinct broadcast_timeline_review."
        ),
    }
    manifest_digest = _sha256_text(json.dumps(manifest, sort_keys=True, ensure_ascii=False))
    record = {
        "schema": SCHEMA,
        "ok": binding_ok,
        "binding_status": BINDING_FRAME_BOUND_VALID if binding_ok else BINDING_INVALID,
        # Legacy "status" mirrors binding only — never FIRST_LIVE_VERIFIED here.
        "status": BINDING_FRAME_BOUND_VALID if binding_ok else BINDING_INVALID,
        "first_live_status": FIRST_LIVE_NOT_VERIFIED,
        "first_live_verified": False,
        "key": window_key(sha, start, end),
        "source_sha256": sha,
        "source_pts_start": start,
        "source_pts_end": end,
        "segment_id": segment_id,
        "frames": frames,
        "manifest": manifest,
        "manifest_digest": manifest_digest,
        "evidence_path": str(out_dir / "evidence.json"),
        "provenance": "LOCAL_SOURCE_FRAME_BINDING",
        "boolean_self_certify_forbidden": True,
        "event_chain_insufficient": True,
        "frame_pack_cannot_certify_first_live": True,
    }
    (out_dir / "evidence.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return record


def validate_frame_binding(
    record: Optional[Mapping[str, Any]],
    *,
    source_sha: str,
    pts_start: float,
    pts_end: float,
    require_files_exist: bool = True,
) -> Dict[str, Any]:
    """Validate source-SHA + PTS + frame-byte binding only (not first-broadcast)."""
    if not isinstance(record, Mapping):
        return {
            "binding_valid": False,
            "first_live_verified": False,
            "reason": "missing_evidence_record",
            "binding_status": BINDING_INVALID,
            "first_live_status": FIRST_LIVE_NOT_VERIFIED,
        }
    if record.get("targeted_visual_verified") is True and not record.get("manifest_digest"):
        return {
            "binding_valid": False,
            "first_live_verified": False,
            "reason": "boolean_targeted_visual_verified_without_manifest",
            "binding_status": BINDING_INVALID,
            "first_live_status": FIRST_LIVE_NOT_VERIFIED,
        }
    if str(record.get("schema") or "") not in (SCHEMA, "") and not record.get("manifest_digest"):
        return {
            "binding_valid": False,
            "first_live_verified": False,
            "reason": "unknown_evidence_schema",
            "binding_status": BINDING_INVALID,
            "first_live_status": FIRST_LIVE_NOT_VERIFIED,
        }
    rec_sha = str(record.get("source_sha256") or record.get("source_sha") or "")
    if not rec_sha or rec_sha != str(source_sha):
        return {
            "binding_valid": False,
            "first_live_verified": False,
            "reason": "source_sha_mismatch",
            "binding_status": BINDING_INVALID,
            "first_live_status": FIRST_LIVE_NOT_VERIFIED,
        }
    try:
        a = float(record.get("source_pts_start"))
        b = float(record.get("source_pts_end"))
    except (TypeError, ValueError):
        return {
            "binding_valid": False,
            "first_live_verified": False,
            "reason": "missing_pts",
            "binding_status": BINDING_INVALID,
            "first_live_status": FIRST_LIVE_NOT_VERIFIED,
        }
    if abs(a - float(pts_start)) > 0.05 or abs(b - float(pts_end)) > 0.05:
        return {
            "binding_valid": False,
            "first_live_verified": False,
            "reason": "pts_window_mismatch",
            "binding_status": BINDING_INVALID,
            "first_live_status": FIRST_LIVE_NOT_VERIFIED,
        }
    frames = list(record.get("frames") or [])
    if len(frames) < 2:
        return {
            "binding_valid": False,
            "first_live_verified": False,
            "reason": "insufficient_frames",
            "binding_status": BINDING_INVALID,
            "first_live_status": FIRST_LIVE_NOT_VERIFIED,
        }
    hashes: List[str] = []
    for fr in frames:
        if not isinstance(fr, Mapping):
            return {
                "binding_valid": False,
                "first_live_verified": False,
                "reason": "bad_frame_row",
                "binding_status": BINDING_INVALID,
                "first_live_status": FIRST_LIVE_NOT_VERIFIED,
            }
        h = fr.get("sha256")
        if not looks_like_content_hash(h):
            return {
                "binding_valid": False,
                "first_live_verified": False,
                "reason": "frame_id_is_not_content_hash",
                "binding_status": BINDING_INVALID,
                "first_live_status": FIRST_LIVE_NOT_VERIFIED,
                "bad_token": h,
            }
        hashes.append(str(h).replace("sha256:", ""))
        if require_files_exist:
            fp = fr.get("path")
            # Allow pack-relative paths resolved against evidence_path parent.
            if fp and not Path(fp).is_file():
                evid = record.get("evidence_path")
                if evid:
                    cand = Path(evid).parent / fp
                    if cand.is_file():
                        fp = str(cand)
            if not fp or not Path(fp).is_file():
                return {
                    "binding_valid": False,
                    "first_live_verified": False,
                    "reason": "frame_file_missing",
                    "binding_status": BINDING_INVALID,
                    "first_live_status": FIRST_LIVE_NOT_VERIFIED,
                }
            actual = _sha256_file(Path(fp))
            if actual != hashes[-1]:
                return {
                    "binding_valid": False,
                    "first_live_verified": False,
                    "reason": "frame_bytes_hash_mismatch",
                    "binding_status": BINDING_INVALID,
                    "first_live_status": FIRST_LIVE_NOT_VERIFIED,
                }
    manifest = record.get("manifest") if isinstance(record.get("manifest"), Mapping) else {}
    digest = str(record.get("manifest_digest") or "")
    if not digest or not looks_like_content_hash(digest):
        return {
            "binding_valid": False,
            "first_live_verified": False,
            "reason": "missing_manifest_digest",
            "binding_status": BINDING_INVALID,
            "first_live_status": FIRST_LIVE_NOT_VERIFIED,
        }
    if manifest:
        recomputed = _sha256_text(json.dumps(dict(manifest), sort_keys=True, ensure_ascii=False))
        if recomputed != digest:
            return {
                "binding_valid": False,
                "first_live_verified": False,
                "reason": "manifest_digest_mismatch",
                "binding_status": BINDING_INVALID,
                "first_live_status": FIRST_LIVE_NOT_VERIFIED,
            }
    return {
        "binding_valid": True,
        "first_live_verified": False,
        "reason": None,
        "binding_status": BINDING_FRAME_BOUND_VALID,
        "first_live_status": FIRST_LIVE_NOT_VERIFIED,
        "source_sha256": rec_sha,
        "source_pts_start": a,
        "source_pts_end": b,
        "frame_sha256": hashes,
        "n_unique_frame_hashes": len(set(hashes)),
        "identical_frame_hashes": len(set(hashes)) == 1,
        "manifest_digest": digest,
        "key": record.get("key") or window_key(rec_sha, a, b),
        "method": "frame_binding_validated",
        "note": (
            "Binding PASS is not first-broadcast LIVE. "
            "Identical JPG hashes are not semantic first-occurrence proof."
        ),
    }


def build_broadcast_timeline_review(
    *,
    source_sha: str,
    pts_start: float,
    pts_end: float,
    out_dir: Optional[Path] = None,
    source_mp4: Optional[Path] = None,
    events: Optional[Sequence[Mapping[str, Any]]] = None,
    context_pad_sec: float = 8.0,
    explicit_review: Optional[Mapping[str, Any]] = None,
    binding_record: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Independent first-broadcast / replay review over continuous source context.

    Outcomes: FIRST_LIVE_VERIFIED | REPLAY_CONFIRMED | UNKNOWN.
    Sparse frame packs and VLM text claims alone never self-certify verified.
    Explicit human/algorithm review is accepted only when evidence-backed and
    bound to the same source SHA + PTS.
    """
    start = float(pts_start)
    end = float(pts_end)
    sha = str(source_sha)
    ctx_lo = max(0.0, start - float(context_pad_sec))
    ctx_hi = end + float(context_pad_sec)
    rationale: List[str] = []
    outcome = FIRST_LIVE_UNKNOWN
    method = "insufficient_timeline_context"
    evidence_refs: List[Dict[str, Any]] = []

    # 1) Event-chain continuous context: replay overlaps / REPLAY phase in pad window.
    replay_hits: List[Dict[str, Any]] = []
    live_hits: List[Dict[str, Any]] = []
    for ev in events or []:
        if not isinstance(ev, Mapping):
            continue
        mt = ev.get("media_time") if isinstance(ev.get("media_time"), Mapping) else {}
        vc = ev.get("video_context") if isinstance(ev.get("video_context"), Mapping) else {}
        try:
            e0 = float(mt.get("start_time_sec", mt.get("event_time_sec")))
            e1 = float(mt.get("end_time_sec", e0 + 1.0))
        except (TypeError, ValueError):
            continue
        if e1 < ctx_lo or e0 > ctx_hi:
            continue
        is_rep = bool(vc.get("is_replay") or vc.get("is_slow_motion")) or str(
            vc.get("broadcast_phase") or ""
        ).upper() in ("REPLAY", "SLOWMO", "SLOW_MOTION")
        row = {
            "event_id": ev.get("event_id"),
            "start": e0,
            "end": e1,
            "broadcast_phase": vc.get("broadcast_phase"),
            "is_replay": is_rep,
        }
        if is_rep and not (e1 < start or e0 > end):
            replay_hits.append(row)
        elif not is_rep and not (e1 < start or e0 > end):
            live_hits.append(row)

    if replay_hits:
        outcome = REPLAY_CONFIRMED
        method = "continuous_context_event_replay_overlap"
        rationale.append("window_overlaps_replay_or_slowmo_in_source_timeline")
        evidence_refs.extend(replay_hits)

    # 2) Explicit authenticated review (human or offline algorithm) — must bind SHA+PTS.
    if explicit_review and isinstance(explicit_review, Mapping):
        rev_sha = str(explicit_review.get("source_sha256") or explicit_review.get("source_sha") or "")
        try:
            ra = float(explicit_review.get("source_pts_start", start))
            rb = float(explicit_review.get("source_pts_end", end))
        except (TypeError, ValueError):
            ra, rb = start, end
        sha_ok = rev_sha == sha
        pts_ok = abs(ra - start) <= 0.05 and abs(rb - end) <= 0.05
        evid_ok = bool(
            explicit_review.get("evidence_refs")
            or explicit_review.get("clip_sha256")
            or explicit_review.get("frame_sha256")
            or explicit_review.get("rationale")
        )
        label = str(
            explicit_review.get("outcome")
            or explicit_review.get("conclusion_label")
            or ""
        ).upper()
        # Map legacy labels
        if label in ("VERIFIED_FIRST_LIVE", "FIRST_LIVE_VERIFIED"):
            label = FIRST_LIVE_VERIFIED
        elif label in ("REPLAY", "REPLAY_DETECTED", "REPLAY_CONFIRMED"):
            label = REPLAY_CONFIRMED
        elif label in ("UNRESOLVED", "UNKNOWN", ""):
            label = FIRST_LIVE_UNKNOWN
        if sha_ok and pts_ok and evid_ok and label in (
            FIRST_LIVE_VERIFIED,
            REPLAY_CONFIRMED,
            FIRST_LIVE_UNKNOWN,
        ):
            # Never accept FIRST_LIVE_VERIFIED from a claim that only cites the
            # local frame-pack (self-certify).
            cites_only_pack = bool(explicit_review.get("cites_frame_pack_only"))
            if label == FIRST_LIVE_VERIFIED and cites_only_pack:
                outcome = FIRST_LIVE_UNKNOWN
                method = "explicit_review_rejected_frame_pack_self_certify"
                rationale.append("first_live_claim_based_only_on_frame_pack_rejected")
            else:
                outcome = label
                method = str(
                    explicit_review.get("method") or "explicit_authenticated_timeline_review"
                )
                rationale.append(str(explicit_review.get("rationale") or "explicit_review"))
                evidence_refs.append(
                    {
                        "kind": "explicit_review",
                        "reviewer": explicit_review.get("reviewer")
                        or explicit_review.get("algorithm"),
                        "provenance": explicit_review.get("provenance"),
                    }
                )
        elif not (sha_ok and pts_ok):
            rationale.append("explicit_review_sha_or_pts_mismatch_ignored")

    # 3) Sparse isolated binding frames ⇒ remain UNKNOWN (even if binding valid).
    if outcome == FIRST_LIVE_UNKNOWN:
        if binding_record and validate_frame_binding(
            binding_record,
            source_sha=sha,
            pts_start=start,
            pts_end=end,
            require_files_exist=False,
        ).get("binding_valid"):
            rationale.append("frame_binding_present_but_no_first_broadcast_proof")
            method = method if method != "insufficient_timeline_context" else (
                "binding_only_no_timeline_proof"
            )
        if not evidence_refs and not replay_hits and not explicit_review:
            rationale.append("no_continuous_timeline_or_authenticated_review")

    # Optional continuous clip hash for auditability (zero HTTP ffmpeg).
    clip_meta: Dict[str, Any] = {}
    if source_mp4 is not None and Path(source_mp4).is_file() and out_dir is not None:
        try:
            from .first_live_localize import cut_accurate_clip

            out_dir = Path(out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            clip_path = out_dir / "context_clip.mp4"
            clip_meta = cut_accurate_clip(
                video=Path(source_mp4),
                media_in=ctx_lo,
                media_out=ctx_hi,
                out_mp4=clip_path,
                max_dur=min(40.0, ctx_hi - ctx_lo + 0.1),
            )
            if clip_meta.get("ok") and clip_meta.get("sha256"):
                evidence_refs.append(
                    {
                        "kind": "continuous_context_clip",
                        "path": str(clip_path),
                        "sha256": clip_meta["sha256"],
                        "media_in": ctx_lo,
                        "media_out": min(ctx_hi, float(clip_meta.get("media_out") or ctx_hi)),
                    }
                )
        except Exception as exc:  # noqa: BLE001
            clip_meta = {"ok": False, "error": f"{type(exc).__name__}:{exc}"}

    review = {
        "schema": TIMELINE_REVIEW_SCHEMA,
        "source_sha256": sha,
        "source_pts_start": start,
        "source_pts_end": end,
        "context_window": {"start": ctx_lo, "end": ctx_hi},
        "outcome": outcome,
        "first_live_status": outcome if outcome != FIRST_LIVE_UNKNOWN else FIRST_LIVE_NOT_VERIFIED,
        "method": method,
        "rationale": rationale,
        "evidence_refs": evidence_refs,
        "replay_hits": replay_hits,
        "live_hits_in_window": live_hits,
        "clip": clip_meta,
        "provenance": "ZERO_HTTP_BROADCAST_TIMELINE_REVIEW",
        "frame_pack_insufficient_alone": True,
        "note": (
            "FIRST_LIVE_VERIFIED only via authenticated timeline review bound to "
            "source SHA+PTS with continuous context evidence. Otherwise UNKNOWN; "
            "replay overlap ⇒ REPLAY_CONFIRMED."
        ),
    }
    if out_dir is not None:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / "broadcast_timeline_review.json").write_text(
            json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return review


def validate_first_live_evidence_record(
    record: Optional[Mapping[str, Any]],
    *,
    source_sha: str,
    pts_start: float,
    pts_end: float,
    require_files_exist: bool = True,
    timeline_review: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Composite validation: binding vs first-broadcast are independent.

    Returns binding_valid / first_live_verified separately. ``ok`` is True only
    when first_live is independently verified (not merely frame-bound).
    """
    binding = validate_frame_binding(
        record,
        source_sha=source_sha,
        pts_start=pts_start,
        pts_end=pts_end,
        require_files_exist=require_files_exist,
    )
    review = timeline_review
    if review is None and isinstance(record, Mapping):
        review = record.get("broadcast_timeline_review")
    first_live_status = FIRST_LIVE_NOT_VERIFIED
    first_live_verified = False
    replay_confirmed = False
    review_method = None
    if isinstance(review, Mapping) and str(review.get("schema") or "") == TIMELINE_REVIEW_SCHEMA:
        # Review must bind same SHA + PTS.
        if (
            str(review.get("source_sha256") or "") == str(source_sha)
            and abs(float(review.get("source_pts_start", pts_start)) - float(pts_start)) <= 0.05
            and abs(float(review.get("source_pts_end", pts_end)) - float(pts_end)) <= 0.05
        ):
            outcome = str(review.get("outcome") or FIRST_LIVE_UNKNOWN).upper()
            review_method = review.get("method")
            if outcome == REPLAY_CONFIRMED:
                first_live_status = REPLAY_CONFIRMED
                replay_confirmed = True
            elif outcome == FIRST_LIVE_VERIFIED:
                first_live_status = FIRST_LIVE_VERIFIED
                first_live_verified = True
            else:
                first_live_status = FIRST_LIVE_NOT_VERIFIED
        else:
            review_method = "timeline_review_sha_pts_mismatch"
    # Legacy: never treat record.status==FIRST_LIVE_VERIFIED from frame pack as verified.
    legacy_status = str((record or {}).get("status") or "").upper() if record else ""
    if legacy_status == FIRST_LIVE_VERIFIED and not first_live_verified:
        # Frame-pack mislabel — demote.
        pass

    return {
        "ok": bool(first_live_verified and binding.get("binding_valid")),
        "binding_valid": bool(binding.get("binding_valid")),
        "binding_status": binding.get("binding_status") or BINDING_INVALID,
        "first_live_verified": first_live_verified,
        "first_live_status": first_live_status,
        "replay_confirmed": replay_confirmed,
        "status": (
            FIRST_LIVE_VERIFIED
            if first_live_verified
            else (
                REPLAY_CONFIRMED
                if replay_confirmed
                else (binding.get("binding_status") or BINDING_INVALID)
            )
        ),
        "reason": binding.get("reason"),
        "source_sha256": binding.get("source_sha256"),
        "source_pts_start": binding.get("source_pts_start"),
        "source_pts_end": binding.get("source_pts_end"),
        "frame_sha256": binding.get("frame_sha256"),
        "manifest_digest": binding.get("manifest_digest"),
        "key": binding.get("key"),
        "method": (
            review_method
            if first_live_verified or replay_confirmed
            else binding.get("method") or "frame_binding_only"
        ),
        "note": (
            "Hard-safety PASS requires first_live_verified on every new window. "
            "FRAME_BOUND_VALID alone ⇒ safety UNKNOWN."
        ),
    }


def load_evidence_store(path: Optional[Path]) -> Dict[str, Any]:
    """Load a directory or JSON map of window_key → evidence records."""
    if path is None:
        return {"schema": "v3a_first_live_evidence_store_v1", "by_key": {}}
    p = Path(path)
    by_key: Dict[str, Any] = {}
    if p.is_file():
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("by_key"), dict):
            by_key = dict(raw["by_key"])
        elif isinstance(raw, dict) and raw.get("key"):
            by_key[str(raw["key"])] = raw
    elif p.is_dir():
        for child in sorted(p.rglob("evidence.json")):
            try:
                rec = json.loads(child.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if isinstance(rec, dict) and rec.get("key"):
                by_key[str(rec["key"])] = rec
    return {"schema": "v3a_first_live_evidence_store_v1", "by_key": by_key, "root": str(p)}
