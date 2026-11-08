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
    """Extract ordered frames from source MP4 at PTS window; hash bytes; write record.

    This is local visual binding evidence (zero HTTP). It does NOT claim paid VLM
    semantic first-broadcast certainty; status is FIRST_LIVE_VERIFIED only when
    extraction succeeds and temporal samples span the window (local producer).
    Callers must still reject event-chain-only labels.
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
            "status": "NOT_VERIFIED",
            "reason": "invalid_window_or_missing_source",
        }
    actual_sha = _sha256_file(source_mp4)
    if actual_sha and source_sha and actual_sha != source_sha:
        return {
            "schema": SCHEMA,
            "ok": False,
            "status": "NOT_VERIFIED",
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
                "status": "NOT_VERIFIED",
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
    manifest = {
        "source_sha256": sha,
        "source_pts_start": start,
        "source_pts_end": end,
        "segment_id": segment_id,
        "frame_sha256": [f["sha256"] for f in frames],
        "frame_pts": [f["source_pts_sec"] for f in frames],
        "n_frames": len(frames),
        "temporal_span_ok": (
            frames[0]["source_pts_sec"] >= start - 0.05
            and frames[-1]["source_pts_sec"] <= end + 0.05
            and frames[-1]["source_pts_sec"] > frames[0]["source_pts_sec"]
        ),
        "require_not_replay_flags": require_not_replay_flags,
        "producer": "local_source_mp4_frame_pack_v1",
        "claims_full_broadcast_timeline": False,
        "note": (
            "Local frame-pack binds source SHA+PTS to content hashes. "
            "Isolated stills without broader timeline context remain insufficient "
            "for formal release; usable as machine-verifiable first-LIVE *binding* "
            "for Phase8 hard-safety exploration when validated."
        ),
    }
    manifest_digest = _sha256_text(json.dumps(manifest, sort_keys=True, ensure_ascii=False))
    record = {
        "schema": SCHEMA,
        "ok": True,
        "status": "FIRST_LIVE_VERIFIED" if manifest["temporal_span_ok"] else "NOT_VERIFIED",
        "key": window_key(sha, start, end),
        "source_sha256": sha,
        "source_pts_start": start,
        "source_pts_end": end,
        "segment_id": segment_id,
        "frames": frames,
        "manifest": manifest,
        "manifest_digest": manifest_digest,
        "evidence_path": str(out_dir / "evidence.json"),
        "provenance": "LOCAL_SOURCE_INSPECTION",
        "boolean_self_certify_forbidden": True,
        "event_chain_insufficient": True,
    }
    (out_dir / "evidence.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return record


def validate_first_live_evidence_record(
    record: Optional[Mapping[str, Any]],
    *,
    source_sha: str,
    pts_start: float,
    pts_end: float,
    require_files_exist: bool = True,
) -> Dict[str, Any]:
    """Verify evidence record binds (source_sha, PTS) with content hashes — not booleans."""
    if not isinstance(record, Mapping):
        return {"ok": False, "reason": "missing_evidence_record", "status": "NOT_VERIFIED"}
    if str(record.get("schema") or "") != SCHEMA and not record.get("manifest_digest"):
        return {"ok": False, "reason": "unknown_evidence_schema", "status": "NOT_VERIFIED"}
    # Reject raw boolean self-certify payloads.
    if record.get("targeted_visual_verified") is True and not record.get("manifest_digest"):
        return {
            "ok": False,
            "reason": "boolean_targeted_visual_verified_without_manifest",
            "status": "NOT_VERIFIED",
        }
    rec_sha = str(record.get("source_sha256") or record.get("source_sha") or "")
    if not rec_sha or rec_sha != str(source_sha):
        return {"ok": False, "reason": "source_sha_mismatch", "status": "NOT_VERIFIED"}
    try:
        a = float(record.get("source_pts_start"))
        b = float(record.get("source_pts_end"))
    except (TypeError, ValueError):
        return {"ok": False, "reason": "missing_pts", "status": "NOT_VERIFIED"}
    if abs(a - float(pts_start)) > 0.05 or abs(b - float(pts_end)) > 0.05:
        return {"ok": False, "reason": "pts_window_mismatch", "status": "NOT_VERIFIED"}
    frames = list(record.get("frames") or [])
    if len(frames) < 2:
        return {"ok": False, "reason": "insufficient_frames", "status": "NOT_VERIFIED"}
    hashes: List[str] = []
    for fr in frames:
        if not isinstance(fr, Mapping):
            return {"ok": False, "reason": "bad_frame_row", "status": "NOT_VERIFIED"}
        h = fr.get("sha256")
        if not looks_like_content_hash(h):
            return {
                "ok": False,
                "reason": "frame_id_is_not_content_hash",
                "status": "NOT_VERIFIED",
                "bad_token": h,
            }
        hashes.append(str(h).replace("sha256:", ""))
        if require_files_exist:
            fp = fr.get("path")
            if not fp or not Path(fp).is_file():
                return {"ok": False, "reason": "frame_file_missing", "status": "NOT_VERIFIED"}
            actual = _sha256_file(Path(fp))
            if actual != hashes[-1]:
                return {
                    "ok": False,
                    "reason": "frame_bytes_hash_mismatch",
                    "status": "NOT_VERIFIED",
                }
    manifest = record.get("manifest") if isinstance(record.get("manifest"), Mapping) else {}
    digest = str(record.get("manifest_digest") or "")
    if not digest or not looks_like_content_hash(digest):
        return {"ok": False, "reason": "missing_manifest_digest", "status": "NOT_VERIFIED"}
    if manifest:
        recomputed = _sha256_text(json.dumps(dict(manifest), sort_keys=True, ensure_ascii=False))
        if recomputed != digest:
            return {"ok": False, "reason": "manifest_digest_mismatch", "status": "NOT_VERIFIED"}
    status = str(record.get("status") or "NOT_VERIFIED").upper()
    if status != "FIRST_LIVE_VERIFIED":
        return {
            "ok": False,
            "reason": "record_status_not_verified",
            "status": status,
            "frame_sha256": hashes,
            "manifest_digest": digest,
        }
    return {
        "ok": True,
        "status": "FIRST_LIVE_VERIFIED",
        "source_sha256": rec_sha,
        "source_pts_start": a,
        "source_pts_end": b,
        "frame_sha256": hashes,
        "manifest_digest": digest,
        "key": record.get("key") or window_key(rec_sha, a, b),
        "method": "validated_local_source_evidence_pack",
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
