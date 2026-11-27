"""P6: export V1 story goal_action clips + context and write audit manifests.

No paid API. Does not invent live_verified from injection alone.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .first_live_localize import cut_accurate_clip, extract_frame_accurate
from .pipeline import dump


def _safe_name(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)


def export_goal_bundle(
    *,
    video: Path,
    match_tag: str,
    goals: Sequence[Dict[str, Any]],
    out_dir: Path,
    context_pad_before: float = 20.0,
    context_pad_after: float = 35.0,
    frame_step: float = 1.0,
) -> Dict[str, Any]:
    dest = Path(out_dir)
    dest.mkdir(parents=True, exist_ok=True)
    clips_dir = dest / "goal_action_clips"
    ctx_dir = dest / "context_clips"
    frames_dir = dest / "audit_frames"
    clips_dir.mkdir(exist_ok=True)
    ctx_dir.mkdir(exist_ok=True)
    frames_dir.mkdir(exist_ok=True)

    rows = []
    concat_list = []
    for i, g in enumerate(goals):
        role = str(g["role"])
        mi, mo = float(g["media_in"]), float(g["media_out"])
        action = g.get("goal_action_sec")
        conf = g.get("score_confirmation_sec")
        stem = f"{i:02d}_{_safe_name(role)}_{int(mi)}_{int(mo)}"
        clip = cut_accurate_clip(
            video=video, media_in=mi, media_out=mo,
            out_mp4=clips_dir / f"{stem}.mp4",
        )
        ctx_in = max(0.0, mi - context_pad_before)
        ctx_out = mo + context_pad_after
        if conf is not None:
            ctx_out = max(ctx_out, float(conf) + 5.0)
        ctx = cut_accurate_clip(
            video=video, media_in=ctx_in, media_out=ctx_out,
            out_mp4=ctx_dir / f"{stem}_context.mp4",
        )
        # Dense frames across action clip + a few into post window
        fdir = frames_dir / stem
        fdir.mkdir(exist_ok=True)
        frames = []
        t = mi
        idx = 0
        while t <= mo + 1e-6:
            fp = fdir / f"f_{idx:03d}_{int(t*1000)}.jpg"
            fr = extract_frame_accurate(video, t, fp)
            frames.append({"media_sec": round(t, 3), "path": fr.get("path"), "ok": fr.get("ok")})
            t += frame_step
            idx += 1
        # also sample near confirmation if available and outside clip
        if conf is not None and float(conf) > mo + 1.0:
            for extra in (float(conf) - 2.0, float(conf), float(conf) + 2.0):
                if extra <= 0:
                    continue
                fp = fdir / f"confirm_{int(extra*1000)}.jpg"
                fr = extract_frame_accurate(video, extra, fp)
                frames.append({
                    "media_sec": round(extra, 3), "path": fr.get("path"), "ok": fr.get("ok"),
                    "kind": "score_confirm_probe",
                })
        row = {
            "index": i,
            "match_tag": match_tag,
            "role": role,
            "beat": g.get("beat"),
            "score_before": g.get("score_before"),
            "score_after": g.get("score_after"),
            "goal_action_sec": action,
            "score_confirmation_sec": conf,
            "edl_media_in": mi,
            "edl_media_out": mo,
            "clip": clip,
            "context_clip": ctx,
            "context_media_in": ctx_in,
            "context_media_out": ctx_out,
            "audit_frames": frames,
            # Must be filled by visual audit — NOT from injection
            "live_status": "live_status_unknown",
            "replay_risk": "unknown",
            "contains_goal_process": None,
            "mostly_celebration_only": None,
            "scoreboard_ok": None,
            "team_side_ok": None,
            "timing_bias": None,
            "recommended_trim": None,
            "edl_eligible": False,
            "notes": [],
        }
        rows.append(row)
        if clip.get("ok") and clip.get("path"):
            concat_list.append(Path(clip["path"]))

    # Unverified story preview concat (labeled)
    preview_path = dest / f"{match_tag}_story_goal_preview_UNVERIFIED.mp4"
    preview_meta = {"ok": False, "path": str(preview_path), "warning": "UNVERIFIED_NOT_FINAL"}
    if concat_list:
        lst = dest / "concat_list.txt"
        lst.write_text("".join(f"file '{p}'\n" for p in concat_list), encoding="utf-8")
        # re-encode for concat safety
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-movflags", "+faststart", str(preview_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        preview_meta = {
            "ok": proc.returncode == 0,
            "path": str(preview_path),
            "warning": "UNVERIFIED_NOT_FINAL_NO_REPLAY_QC",
            "stderr_tail": (proc.stderr or "")[-500:],
        }

    manifest = {
        "schema": "v3_p6_goal_video_export_v1",
        "match_tag": match_tag,
        "video": str(video),
        "n_goals": len(rows),
        "goals": rows,
        "preview": preview_meta,
        "render_ready": False,
        "note": "live_status defaults to live_status_unknown until visual audit",
    }
    dump(dest / "export_manifest.json", manifest)
    return manifest


def deep_probe_window(
    *,
    video: Path,
    out_dir: Path,
    media_in: float,
    media_out: float,
    step: float = 2.0,
    label: str = "probe",
) -> List[Dict[str, Any]]:
    dest = Path(out_dir)
    dest.mkdir(parents=True, exist_ok=True)
    rows = []
    t = float(media_in)
    i = 0
    while t <= float(media_out) + 1e-6:
        fp = dest / f"{label}_{i:03d}_{int(t*1000)}.jpg"
        fr = extract_frame_accurate(video, t, fp)
        rows.append({"media_sec": round(t, 3), "path": fr.get("path"), "ok": fr.get("ok")})
        t += step
        i += 1
    dump(dest / f"{label}_manifest.json", rows)
    return rows
