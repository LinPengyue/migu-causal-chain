"""Phase 3B：人工审核辅助 — 截图 / contact sheet / review_manifest / 导入桩。

导入未校验数据不得直接提升 render_ready。
明确区分 source_media_order 与 narrative_order。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from story_video_agent.internal_verification import GRANTED_BY, sanitize_plan_trust
from story_video_agent.media import MediaInfo, probe_video
from story_video_agent.video_renderer import RenderError, _require_ffmpeg

PathLike = Union[str, Path]


def _run(cmd: List[str], *, label: str) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=120)
    if proc.returncode != 0:
        raise RenderError(f"{label} failed: {(proc.stderr or '')[-300:]}")


def extract_review_stills(
    video_path: PathLike,
    media_in: float,
    media_out: float,
    out_dir: PathLike,
    *,
    stem: str,
) -> Dict[str, str]:
    """为片段提取起点 / 中点 / 终点截图。"""
    ffmpeg = _require_ffmpeg()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    a, b = float(media_in), float(media_out)
    mid = (a + b) / 2.0
    end = max(a, b - 0.05)
    paths = {
        "start": out_dir / f"{stem}_start.jpg",
        "mid": out_dir / f"{stem}_mid.jpg",
        "end": out_dir / f"{stem}_end.jpg",
    }
    for key, t, path in (
        ("start", a, paths["start"]),
        ("mid", mid, paths["mid"]),
        ("end", end, paths["end"]),
    ):
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{t:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(path),
        ]
        _run(cmd, label=f"still:{stem}:{key}")
    return {k: str(v) for k, v in paths.items()}


def build_contact_sheet(
    still_paths: Sequence[PathLike],
    out_path: PathLike,
    *,
    tile_w: int = 320,
    tile_h: int = 180,
    cols: int = 3,
) -> str:
    """用 ffmpeg tile 生成 contact sheet。"""
    ffmpeg = _require_ffmpeg()
    paths = [Path(p) for p in still_paths if Path(p).is_file()]
    if not paths:
        raise RenderError("no stills for contact sheet")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = len(paths)
    rows = (n + cols - 1) // cols
    # pad to cols*rows with black if needed
    inputs: List[str] = []
    filter_parts: List[str] = []
    for i, p in enumerate(paths):
        inputs += ["-i", str(p)]
        filter_parts.append(
            f"[{i}:v]scale={tile_w}:{tile_h}:force_original_aspect_ratio=decrease,"
            f"pad={tile_w}:{tile_h}:(ow-iw)/2:(oh-ih)/2,setsar=1[v{i}]"
        )
    # black pads
    lavfi_needed = cols * rows - n
    for j in range(lavfi_needed):
        idx = n + j
        inputs += [
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={tile_w}x{tile_h}:d=0.04",
        ]
        filter_parts.append(f"[{idx}:v]format=yuv420p,setsar=1[v{idx}]")
    layout_inputs = "".join(f"[v{i}]" for i in range(cols * rows))
    filter_parts.append(
        f"{layout_inputs}xstack=inputs={cols * rows}:layout="
        + "|".join(
            f"{(i % cols) * tile_w}_{(i // cols) * tile_h}"
            for i in range(cols * rows)
        )
        + "[out]"
    )
    cmd = (
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
        + inputs
        + ["-filter_complex", ";".join(filter_parts), "-map", "[out]", str(out_path)]
    )
    _run(cmd, label="contact_sheet")
    return str(out_path.resolve())


def build_review_manifest(
    plan: Dict[str, Any],
    video_path: PathLike,
    out_dir: PathLike,
    *,
    max_segments: Optional[int] = None,
) -> Dict[str, Any]:
    """生成 review_manifest.json + 每段三帧 + contact sheet。"""
    media = probe_video(video_path)
    plan = sanitize_plan_trust(plan)
    out_dir = Path(out_dir)
    stills_dir = out_dir / "stills"
    stills_dir.mkdir(parents=True, exist_ok=True)

    rows = list(plan.get("candidate_edl") or [])
    if not rows:
        rows = [
            {
                "segment_id": s.get("segment_id"),
                "beat": s.get("beat"),
                "role": s.get("role"),
                "media_in": s.get("media_in"),
                "media_out": s.get("media_out"),
                "time_status": s.get("time_status"),
                "time_provenance": s.get("time_provenance"),
                "render_eligibility": s.get("render_eligibility"),
                "blocking_reasons": s.get("blocking_reasons"),
                "event_ids": s.get("event_ids"),
                "narrative_order": s.get("narrative_order"),
                "source_media_order": s.get("source_media_order"),
                "shot_kind": s.get("shot_kind"),
            }
            for s in (plan.get("segments") or [])
        ]
    rows = sorted(
        rows, key=lambda r: (r.get("narrative_order") or 0, r.get("edl_index") or 0)
    )
    if max_segments is not None:
        rows = rows[: int(max_segments)]

    entries: List[Dict[str, Any]] = []
    all_stills: List[str] = []

    for i, row in enumerate(rows):
        sid = str(row.get("segment_id") or f"seg_{i}")
        tin, tout = row.get("media_in"), row.get("media_out")
        needs_human = True
        blocking = list(row.get("blocking_reasons") or [])
        stills: Dict[str, Any] = {}
        cuttable = (
            tin is not None
            and tout is not None
            and row.get("render_eligibility") != "blocked"
            and row.get("time_status")
            not in ("pending_localization", "pending_review", "unavailable")
        )
        if cuttable:
            try:
                a, b = float(tin), float(tout)
                if 0 <= a < b <= float(media.duration_sec) + 1e-3:
                    stills = extract_review_stills(
                        media.path, a, b, stills_dir, stem=f"{i:03d}_{sid}"
                    )
                    all_stills.extend(stills.values())
                else:
                    blocking.append("out_of_media_bounds_for_stills")
            except (TypeError, ValueError, RenderError) as exc:
                blocking.append(f"still_extract_failed:{exc}")
        else:
            blocking.append(blocking and blocking[0] or "not_cuttable_for_stills")

        # 内部未授予 → 始终需要人工确认
        prov = row.get("time_provenance") or {}
        internally_granted = prov.get("granted_by") == GRANTED_BY and bool(
            prov.get("pipeline_verified")
        )
        if internally_granted:
            needs_human = False

        entries.append(
            {
                "segment_id": sid,
                "beat": row.get("beat"),
                "role": row.get("role"),
                "shot_kind": row.get("shot_kind"),
                "media_in": tin,
                "media_out": tout,
                "source_media_order": row.get("source_media_order"),
                "narrative_order": row.get("narrative_order"),
                "time_status": row.get("time_status"),
                "time_source": (prov.get("source") if isinstance(prov, dict) else None),
                "render_eligibility": row.get("render_eligibility"),
                "event_ids": list(row.get("event_ids") or []),
                "stills": stills,
                "blocking_reasons": sorted(set(str(x) for x in blocking)),
                "needs_human_confirmation": needs_human,
                "internally_granted": internally_granted,
                "order_note": {
                    "narrative_order": row.get("narrative_order"),
                    "source_media_order": row.get("source_media_order"),
                    "distinction": (
                        "narrative_order=故事线剪辑顺序; "
                        "source_media_order=原片时间轴位置"
                    ),
                },
            }
        )

    contact = None
    if all_stills:
        contact = build_contact_sheet(
            all_stills, out_dir / "contact_sheet.jpg", cols=3
        )

    manifest = {
        "schema": "story-review-manifest-3b",
        "source_video": media.to_dict(),
        "match_id": plan.get("match_id"),
        "story_tier": plan.get("story_tier"),
        "render_ready": False,  # 审核产出本身不授予
        "n_segments": len(entries),
        "segments": entries,
        "contact_sheet": contact,
        "notes": [
            "stills/contact sheet 仅供人工审核",
            "import_review_decisions 不得直接将片段升为 render_ready",
            "source_media_order ≠ narrative_order",
        ],
    }
    man_path = out_dir / "review_manifest.json"
    man_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["path"] = str(man_path.resolve())
    return manifest


def import_review_decisions(
    plan: Dict[str, Any],
    decisions: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """结构化导入人工审核结果（桩）。

    允许写入 review_notes / human_confirmed 标记；
    **禁止** 仅凭导入将 render_eligibility 提升为 render_ready，
    也禁止写入 granted_by=internal_verification_pipeline。
    """
    plan = sanitize_plan_trust(plan)
    by_id = {s.get("segment_id"): s for s in (plan.get("segments") or [])}
    applied: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    for dec in decisions:
        sid = dec.get("segment_id")
        seg = by_id.get(sid)
        if not seg:
            rejected.append({"segment_id": sid, "reason": "unknown_segment"})
            continue
        # 拒绝直接提权
        if dec.get("render_eligibility") == "render_ready" or dec.get(
            "grant_render_ready"
        ):
            rejected.append(
                {
                    "segment_id": sid,
                    "reason": "import_cannot_grant_render_ready",
                    "hint": "must run internal_verification.apply_internal_verification",
                }
            )
            # 仍可记录人工意见，但不提权
        notes = dict(seg.get("review_notes") or {})
        notes["human_confirmed"] = bool(dec.get("human_confirmed"))
        notes["reviewer"] = dec.get("reviewer") or "unknown"
        notes["comment"] = dec.get("comment") or ""
        notes["decision_time_status"] = dec.get("time_status")
        if dec.get("adjusted_media_in") is not None:
            notes["proposed_media_in"] = dec.get("adjusted_media_in")
        if dec.get("adjusted_media_out") is not None:
            notes["proposed_media_out"] = dec.get("adjusted_media_out")
        # 提议时间写入 notes，不直接覆盖 media_in（避免未核验时间进入成片）
        seg["review_notes"] = notes
        if dec.get("reject"):
            seg["render_eligibility"] = "blocked"
            br = list(seg.get("blocking_reasons") or [])
            br.append("human_rejected")
            seg["blocking_reasons"] = sorted(set(br))
        applied.append({"segment_id": sid, "notes_keys": list(notes.keys())})

    plan.setdefault("diagnostics", {})
    plan["diagnostics"]["review_import"] = {
        "applied": applied,
        "rejected_elevations": rejected,
        "render_ready_unchanged": True,
        "note": "import never sets granted_by or render_ready",
    }
    # 强制保持非 render_ready（导入路径）
    plan["render_ready"] = False
    plan["render_ready_edl"] = []
    return plan
