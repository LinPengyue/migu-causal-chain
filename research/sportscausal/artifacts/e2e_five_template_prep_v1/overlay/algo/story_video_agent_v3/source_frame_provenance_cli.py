"""Read-only revalidation of archived REAL-model source JPGs.

Not an Agent, not an experiment, not a FIRST_LIVE detector. It only resolves
whether the original frame bytes cited in a real VLM log can be reproduced from
the exact source SHA / PTS using deployed extractors (q2 or FrameStore q3).
Never mutates an EDL or a historical file; costs zero HTTP calls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from .story_goal_video_repair import audit_source_frame_redecode

SCHEMA = "v3a_source_frame_provenance_audit_v1"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for buf in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(buf)
    return h.hexdigest()


def inspect_archived_real_goal_frames(
    *,
    source_mp4: Path,
    source_sha256: str,
    frame_manifest_path: Path,
    semantic_log_path: Path,
) -> Dict[str, Any]:
    """Inspect original provider input IDs, not newly sampled replacement JPGs."""
    manifest = json.loads(Path(frame_manifest_path).read_text(encoding="utf-8"))
    semantic = json.loads(Path(semantic_log_path).read_text(encoding="utf-8"))
    if not isinstance(manifest, Mapping) or not isinstance(semantic, Mapping):
        raise ValueError("manifest_and_semantic_log_must_be_json_objects")
    if semantic.get("provider_mode") != "real" or semantic.get("observation_only") is not True:
        raise ValueError("not_a_real_observation_only_model_log")
    inference = semantic.get("vlm_inference")
    if not isinstance(inference, Mapping):
        raise ValueError("missing_original_model_inference")
    shot_ids = [str(x) for x in (inference.get("shot_frame_ids") or [])]
    net_ids = [str(x) for x in (inference.get("net_frame_ids") or [])]
    if not shot_ids or not net_ids:
        raise ValueError("shot_and_net_model_citations_required")
    cited_ids = list(dict.fromkeys(shot_ids + net_ids))
    original_rows = list(manifest.get("frames") or [])
    by_id = {
        str(fr.get("frame_id")): fr for fr in original_rows
        if isinstance(fr, Mapping) and fr.get("frame_id")
    }
    if len(by_id) != len(original_rows):
        raise ValueError("ambiguous_or_malformed_original_frame_manifest")
    if any(fid not in by_id for fid in cited_ids):
        raise ValueError(
            "cited_model_frame_id_missing_from_original_manifest:"
            + ",".join(fid for fid in cited_ids if fid not in by_id)
        )
    bound_frames = []
    for fid in cited_ids:
        fr = by_id[fid]
        p = Path(str(fr.get("path") or ""))
        if not p.is_file():
            raise ValueError("original_model_input_jpg_missing:" + fid)
        if fr.get("actual_media_sec") is None or fr.get("requested_media_sec") is None:
            raise ValueError("original_frame_requested_or_actual_pts_missing:" + fid)
        bound_frames.append({
            "frame_id": fid,
            "path": str(p),
            "sha256": sha256_file(p),
            "source_pts_sec": float(fr["actual_media_sec"]),
            "requested_media_sec": float(fr["requested_media_sec"]),
        })
    verify = audit_source_frame_redecode(
        source_mp4=Path(source_mp4),
        source_sha=source_sha256,
        binding={"frames": bound_frames},
    )
    return {
        "schema": SCHEMA,
        "source_sha256": source_sha256,
        "semantic_log_sha256": sha256_file(Path(semantic_log_path)),
        "frame_manifest_sha256": sha256_file(Path(frame_manifest_path)),
        "semantic_provider_mode": "real",
        "source_model_input_ids": cited_ids,
        "n_original_model_frames": len(bound_frames),
        "source_frame_redecode": verify,
        "stage3_source_frame_binding_valid": bool(verify.get("ok")),
        "first_live_status": "NOT_VERIFIED",
        "first_live_verified": False,
        "edl_modified": False,
        "api_calls": 0,
        "historical_evidence_reused": True,
        "note": (
            "Passing source-frame identity does not establish first occurrence. "
            "Stage4 UNKNOWN remains binding until separate FIRST_LIVE evidence."
        ),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Zero-HTTP archived VLM frame provenance audit")
    ap.add_argument("--source-mp4", type=Path, required=True)
    ap.add_argument("--source-sha256", required=True)
    ap.add_argument("--frame-manifest", type=Path, required=True)
    ap.add_argument("--semantic-log", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    opts = ap.parse_args(argv)
    if opts.out.exists():
        ap.error("refuse_overwrite_previous_audit")
    if len(opts.source_sha256) != 64:
        ap.error("source_sha256_must_have_64_hex_chars")
    try:
        data = inspect_archived_real_goal_frames(
            source_mp4=opts.source_mp4,
            source_sha256=opts.source_sha256,
            frame_manifest_path=opts.frame_manifest,
            semantic_log_path=opts.semantic_log,
        )
        opts.out.parent.mkdir(parents=True, exist_ok=True)
        opts.out.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        ap.error(type(exc).__name__ + ":" + str(exc))
    print(json.dumps({
        "status": data["source_frame_redecode"]["status"],
        "all_cited_frames_match_source": data["stage3_source_frame_binding_valid"],
        "first_live_verified": False,
        "edl_modified": False,
        "report": str(opts.out),
    }, ensure_ascii=False))
    return 0 if data["stage3_source_frame_binding_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
