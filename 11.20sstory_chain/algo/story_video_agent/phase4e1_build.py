"""Phase 4E.1: Croatia-only historical edit (glitch-avoid + packaging).

DEPRECATED for generic delivery. Phase 5 uses ``phase5_pipeline.py``.
This module is retained for Croatia regression reference only; the generic
entry must NOT import or auto-fallback to these hardcoded times/ranges.

No paid API. preview-only; render_ready stays false; candidate_only.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from story_video_agent.video_renderer import (
    DEFAULT_AUDIO_RATE,
    DEFAULT_FPS,
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    RenderError,
    _concat_clips,
    _cut_segment,
    _make_placeholder,
    _require_ffmpeg,
)
from story_video_agent.media import probe_video

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VIDEO = Path("/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4")
OUT_DIR = ROOT / "_local_render" / "phase4e1b"
REPORTS = ROOT / "reports"
REPORT_PREFIX = "phase4e1b"

# Internal preview loudness target (not migu formal delivery spec)
LOUDNORM_I = -16.0
LOUDNORM_TP = -1.5
LOUDNORM_LRA = 11.0

# Source bitstream glitch ranges (media seconds) confirmed by KF stream-copy + visual QC
SOURCE_GLITCH_RANGES = [
    (3603.6, 3604.8, "ga_board_2_1_green_mosaic"),
    (6315.8, 6316.7, "third_goal_approach_neon_band"),
    (7855.6, 7856.5, "fourth_board_green_band"),
]


def _row(
    *,
    idx: int,
    segment_id: str,
    beat: str,
    role: str,
    shot_kind: str,
    media_in: Optional[float],
    media_out: Optional[float],
    narration: str,
    selection_reason: str,
    time_status: str = "local_visual_candidate",
    provenance: Optional[Dict[str, Any]] = None,
    event_ids: Optional[List[str]] = None,
    confidence: float = 0.7,
    placeholder_lines: Optional[List[str]] = None,
    placeholder_sec: Optional[float] = None,
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "edl_index": idx,
        "segment_id": segment_id,
        "beat": beat,
        "role": role,
        "shot_kind": shot_kind,
        "is_replay": False,
        "media_in": media_in,
        "media_out": media_out,
        "time_status": time_status if media_in is not None else "placeholder_title",
        "time_provenance": provenance or {"source": "phase4e1_edit", "pipeline_verified": False},
        "event_ids": event_ids or [],
        "frame_ids": [],
        "linked_live_event_id": None,
        "narrative_order": idx,
        "source_media_order": media_in if media_in is not None else -1,
        "render_eligibility": "candidate_only",
        "blocking_reasons": [
            "semantic_unverified",
            "phase4e1_preview_only",
            "source_glitch_avoidance_applied",
        ],
        "confidence": confidence,
        "selection_reason": selection_reason,
        "narration": narration,
        "include_in_cut": False,
    }
    if placeholder_lines is not None:
        row["placeholder_lines"] = placeholder_lines
        row["placeholder_sec"] = float(placeholder_sec or 2.5)
    return row


def build_long_edl() -> List[Dict[str, Any]]:
    """Primary story cut: four goals, short boards, avoid source glitch spans."""
    i = 0
    rows: List[Dict[str, Any]] = []

    def add(**kw: Any) -> None:
        nonlocal i
        i += 1
        rows.append(_row(idx=i, **kw))

    add(
        segment_id="seg_title_open",
        beat="铺垫",
        role="story_title",
        shot_kind="title_card",
        media_in=None,
        media_out=None,
        narration="开场标题：落后到逆转",
        selection_reason="phase4e1_narrative_packaging",
        placeholder_sec=3.0,
        placeholder_lines=[
            "T01 克罗地亚逆转加拿大",
            "失球 0:1  →  终场 4:1",
            "内部审核样片 · candidate_only",
        ],
    )
    add(
        segment_id="seg_opponent_opening_goal_action",
        beat="铺垫",
        role="opponent_opening_goal_action",
        shot_kind="live",
        media_in=968.0,
        media_out=990.0,
        narration="加拿大先进球：传球→头球→入网≈981.5→庆祝（live；非 1079 记分牌）",
        selection_reason="phase4e1b_local_opening_goal",
        time_status="local_visual_candidate",
        provenance={
            "source": "local_frame_review",
            "causal_goal_event_id": "event_000004",
            "causal_goal_t_sec": 980.137,
            "ball_in_net_sec": 981.5,
            "header_contact_sec": 980.5,
            "is_replay": False,
            "broadcast_clock": "01:06-01:10",
            "avoided_scoreboard_proxy_t_sec": 1079.06,
            "pipeline_verified": False,
        },
        event_ids=["event_000004"],
        confidence=0.78,
    )
    add(
        segment_id="seg_setup_deficit",
        beat="铺垫",
        role="deficit_scoreboard_anchor",
        shot_kind="scoreboard_anchor",
        media_in=1078.06,
        media_out=1082.06,
        narration="0:1 比分确认（缩短≈4s；不替代失球动作）",
        selection_reason="phase4e1b_shorten_setup_after_opening_goal",
        time_status="score_path_only",
        provenance={"source": "score_path", "t_sec": 1079.06, "pipeline_verified": False},
        confidence=0.9,
    )
    add(
        segment_id="seg_title_buildup",
        beat="蓄力",
        role="story_title",
        shot_kind="title_card",
        media_in=None,
        media_out=None,
        narration="蓄力标题",
        selection_reason="phase4e1_narrative_packaging",
        placeholder_sec=2.0,
        placeholder_lines=["蓄力", "角球 → 禁区压迫"],
    )
    add(
        segment_id="seg_buildup_attack",
        beat="蓄力",
        role="buildup_attack",
        shot_kind="live",
        media_in=3038.0,
        media_out=3063.5,
        narration="蓄力完整尾段至扳平 abut（禁止 max_clip 截断）",
        selection_reason="phase4e_abut_fix_seam_retained",
        provenance={
            "source": "local_frame_review",
            "corner_sec": 3042.85,
            "abut_at": 3063.5,
            "pipeline_verified": False,
            "max_clip_sec": None,
        },
        event_ids=["event_000066", "event_000067"],
        confidence=0.65,
    )
    add(
        segment_id="seg_equalizer_goal_action",
        beat="转折",
        role="equalizer_goal_action",
        shot_kind="live",
        media_in=3063.5,
        media_out=3075.0,
        narration="1:1 扳平 live 入网≈3067",
        selection_reason="phase4c_local_localization_retained",
        provenance={"source": "local_frame_review", "ball_in_net_sec": 3067.0},
        event_ids=["event_000021"],
        confidence=0.72,
    )
    add(
        segment_id="seg_equalizer_scoreboard",
        beat="转折",
        role="equalizer_scoreboard_anchor",
        shot_kind="scoreboard_anchor",
        media_in=3145.0,
        media_out=3148.5,
        narration="1:1 比分确认（缩短≈3.5s）",
        selection_reason="phase4e1_shorten_scoreboard",
        time_status="score_path_only",
        provenance={"source": "score_path", "t_sec": 3145.98},
        confidence=0.85,
    )
    add(
        segment_id="seg_title_go_ahead",
        beat="高潮",
        role="story_title",
        shot_kind="title_card",
        media_in=None,
        media_out=None,
        narration="反超标题",
        selection_reason="phase4e1_narrative_packaging",
        placeholder_sec=2.0,
        placeholder_lines=["高潮 · 反超", "2:1"],
    )
    add(
        segment_id="seg_go_ahead_goal_action",
        beat="高潮",
        role="go_ahead_goal_action",
        shot_kind="live",
        media_in=3518.0,
        media_out=3532.0,
        narration="2:1 反超动作≈3525",
        selection_reason="phase4c_local_localization_retained",
        provenance={"source": "local_frame_review", "ball_in_net_sec": 3525.0},
        confidence=0.72,
    )
    add(
        segment_id="seg_go_ahead_scoreboard_closer",
        beat="高潮",
        role="go_ahead_scoreboard_anchor",
        shot_kind="scoreboard_anchor",
        media_in=3599.5,
        media_out=3603.0,
        narration="2:1 牌（避开源花屏≈3604；含 LIVAJA 底部条）",
        selection_reason="phase4e1_avoid_source_glitch_3604",
        time_status="score_path_only",
        provenance={
            "source": "score_path",
            "t_sec": 3600.0,
            "avoided_glitch": [3603.6, 3604.8],
            "clean_window": [3599.5, 3603.0],
        },
        confidence=0.8,
    )
    add(
        segment_id="seg_third_goal_action",
        beat="高潮",
        role="third_goal_action",
        shot_kind="live",
        media_in=6317.0,
        media_out=6328.0,
        narration="3:1 动作（避开源花屏≈6316；入网≈6318.5）",
        selection_reason="phase4e1_avoid_source_glitch_6316",
        provenance={
            "source": "local_frame_review",
            "ball_in_net_sec": 6318.5,
            "avoided_glitch": [6315.8, 6316.7],
            "phase4e_window_was": [6312.0, 6328.0],
        },
        confidence=0.7,
    )
    add(
        segment_id="seg_third_scoreboard",
        beat="高潮",
        role="third_scoreboard_anchor",
        shot_kind="scoreboard_anchor",
        media_in=6406.0,
        media_out=6409.5,
        narration="3:1 比分确认（缩短≈3.5s）",
        selection_reason="phase4e1_shorten_scoreboard",
        time_status="score_path_only",
        provenance={"source": "score_path", "t_sec": 6408.7},
        confidence=0.8,
    )
    add(
        segment_id="seg_fourth_goal_action",
        beat="高潮",
        role="fourth_goal_action",
        shot_kind="live",
        media_in=7742.0,
        media_out=7756.0,
        narration="4:1 动作≈7749",
        selection_reason="phase4e_local_search_4_1_retained",
        provenance={"source": "local_frame_review", "ball_in_net_sec": 7749.0},
        confidence=0.7,
    )
    add(
        segment_id="seg_fourth_scoreboard",
        beat="高潮",
        role="fourth_scoreboard_anchor",
        shot_kind="scoreboard_anchor",
        media_in=7857.0,
        media_out=7860.5,
        narration="4:1 牌（避开源花屏≈7856）",
        selection_reason="phase4e1_avoid_source_glitch_7856",
        time_status="score_path_only",
        provenance={
            "source": "score_path",
            "t_sec": 7858.37,
            "avoided_glitch": [7855.6, 7856.5],
            "clean_window": [7857.0, 7860.5],
        },
        confidence=0.8,
    )
    add(
        segment_id="seg_ending_full_time",
        beat="收尾",
        role="full_time_ending",
        shot_kind="scoreboard_anchor",
        media_in=7928.0,
        media_out=7942.0,
        narration="FULL TIME 4:1",
        selection_reason="phase4d_full_time_retained",
        time_status="score_path_only",
        provenance={"source": "score_path", "t_sec": 7935.0},
        confidence=0.85,
    )
    add(
        segment_id="seg_title_close",
        beat="收尾",
        role="story_title",
        shot_kind="title_card",
        media_in=None,
        media_out=None,
        narration="收束标题",
        selection_reason="phase4e1_narrative_packaging",
        placeholder_sec=2.5,
        placeholder_lines=["终场 4:1", "克罗地亚完成逆转", "candidate_only · 非正式成片"],
    )
    return rows


def build_short_edl() -> List[Dict[str, Any]]:
    """Short control: through 2:1 then bridge to FULL TIME (glitch-avoid boards)."""
    long_rows = {r["segment_id"]: r for r in build_long_edl()}
    keep = [
        "seg_title_open",
        "seg_opponent_opening_goal_action",
        "seg_setup_deficit",
        "seg_title_buildup",
        "seg_buildup_attack",
        "seg_equalizer_goal_action",
        "seg_equalizer_scoreboard",
        "seg_title_go_ahead",
        "seg_go_ahead_goal_action",
        "seg_go_ahead_scoreboard_closer",
    ]
    rows = []
    for sid in keep:
        r = dict(long_rows[sid])
        rows.append(r)
    # bridge
    rows.append(
        _row(
            idx=len(rows) + 1,
            segment_id="seg_text_bridge_2_to_4",
            beat="高潮",
            role="story_bridge",
            shot_kind="title_card",
            media_in=None,
            media_out=None,
            narration="短版文字桥：2:1 后至终场",
            selection_reason="phase4e1_short_bridge",
            placeholder_sec=4.0,
            placeholder_lines=["随后扩大比分", "3:1 → 4:1", "（短版略去过程，见长版）"],
        )
    )
    rows.append(dict(long_rows["seg_ending_full_time"]))
    rows.append(dict(long_rows["seg_title_close"]))
    for i, r in enumerate(rows, 1):
        r["edl_index"] = i
        r["narrative_order"] = i
    return rows


def build_plan(edl: List[Dict[str, Any]], *, variant: str) -> Dict[str, Any]:
    return {
        "schema": "story_video_agent.story_plan.v1",
        "story_id": "T01_comeback",
        "story_tier": "candidate",
        "match_id": "croatia_vs_canada_2022-11-28",
        "phase": "4E.1b",
        "variant": variant,
        "render_ready": False,
        "render_ready_edl": [],
        "candidate_edl": edl,
        "gates": {
            "candidate_only": True,
            "no_paid_api": True,
            "no_auto_semantic_grant": True,
            "review_ready": False,  # flipped after glitch QC pass
        },
        "notes": [
            "phase4e1: avoid source HEVC bitstream glitch spans; shorten boards; narrative titles; loudness",
            "phase4e1b: insert opponent opening goal action before 0:1 scoreboard (cause of deficit)",
            "goal action timestamps unchanged unless window trimmed to skip source corruption",
        ],
        "source_glitch_ranges": [
            {"media_in": a, "media_out": b, "label": lab}
            for a, b, lab in SOURCE_GLITCH_RANGES
        ],
        "loudness_target": {
            "I_LUFS": LOUDNORM_I,
            "TP_dBTP": LOUDNORM_TP,
            "LRA": LOUDNORM_LRA,
            "scope": "internal_web_preview_only",
        },
    }


def _score_overlay(role: str) -> List[str]:
    mapping = {
        "opponent_opening_goal_action": ["失球 → 0:1", "加拿大先进球"],
        "deficit_scoreboard_anchor": ["比分 0:1", "逆境确认"],
        "buildup_attack": ["蓄力中"],
        "equalizer_goal_action": ["扳平 → 1:1"],
        "equalizer_scoreboard_anchor": ["1:1"],
        "go_ahead_goal_action": ["反超 → 2:1"],
        "go_ahead_scoreboard_anchor": ["2:1"],
        "third_goal_action": ["扩大 → 3:1"],
        "third_scoreboard_anchor": ["3:1"],
        "fourth_goal_action": ["再下一城 → 4:1"],
        "fourth_scoreboard_anchor": ["4:1"],
        "full_time_ending": ["FULL TIME 4:1"],
    }
    return mapping.get(role, [])


def render_variant(
    *,
    plan: Dict[str, Any],
    video: Path,
    out_mp4: Path,
    work_dir: Path,
) -> Dict[str, Any]:
    ffmpeg = _require_ffmpeg()
    media = probe_video(video)
    has_audio = bool(media.audio_codec)
    work_dir.mkdir(parents=True, exist_ok=True)
    clips_dir = work_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    rows = list(plan.get("candidate_edl") or [])
    clip_paths: List[Path] = []
    ffmpeg_log: List[Dict[str, Any]] = []
    segments: List[Dict[str, Any]] = []

    for i, row in enumerate(rows):
        sid = str(row.get("segment_id") or f"seg_{i}")
        clip_path = clips_dir / f"{i:03d}_{sid}.mp4"
        meta: Dict[str, Any] = {
            "segment_id": sid,
            "beat": row.get("beat"),
            "role": row.get("role"),
            "media_in": row.get("media_in"),
            "media_out": row.get("media_out"),
            "cut": False,
            "placeholder": False,
            "clip_path": str(clip_path),
        }
        if row.get("shot_kind") == "title_card" or row.get("media_in") is None:
            lines = list(row.get("placeholder_lines") or ["标题卡", sid])
            dur = float(row.get("placeholder_sec") or 2.5)
            rec = _make_placeholder(
                ffmpeg=ffmpeg,
                out_path=clip_path,
                duration=dur,
                width=DEFAULT_WIDTH,
                height=DEFAULT_HEIGHT,
                fps=DEFAULT_FPS,
                lines=lines,
            )
            ffmpeg_log.append(rec)
            meta["placeholder"] = True
            meta["duration"] = dur
        else:
            a = float(row["media_in"])
            b = float(row["media_out"])
            # HARD: never truncate via max_clip_sec in 4E.1
            overlays = [
                "内部审核样片",
                f"{row.get('beat') or ''} | {sid}",
                f"media {a:.1f}-{b:.1f}s",
            ] + _score_overlay(str(row.get("role") or ""))
            # light per-clip gain toward target; final loudnorm on master
            af = f"aresample={DEFAULT_AUDIO_RATE},dynaudnorm=f=150:g=15"
            rec = _cut_segment(
                ffmpeg=ffmpeg,
                src=Path(media.path),
                media_in=a,
                media_out=b,
                out_path=clip_path,
                width=DEFAULT_WIDTH,
                height=DEFAULT_HEIGHT,
                fps=DEFAULT_FPS,
                has_audio=has_audio,
                overlay_lines=overlays,
                accurate_seek=True,
                audio_filter=af,
            )
            ffmpeg_log.append(rec)
            meta["cut"] = True
            meta["duration"] = b - a
        clip_paths.append(clip_path)
        segments.append(meta)

    raw_mp4 = work_dir / "concat_raw.mp4"
    concat_rec = _concat_clips(ffmpeg=ffmpeg, clip_paths=clip_paths, out_mp4=raw_mp4)
    ffmpeg_log.append(concat_rec)

    # Final loudness pass (internal preview target)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    loud_cmd = [
        ffmpeg,
        "-hide_banner",
        "-y",
        "-i",
        str(raw_mp4),
        "-af",
        f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-ar",
        str(DEFAULT_AUDIO_RATE),
        "-ac",
        "2",
        str(out_mp4),
    ]
    proc = subprocess.run(loud_cmd, capture_output=True, text=True, check=False, timeout=900)
    ffmpeg_log.append(
        {
            "label": "loudnorm_master",
            "returncode": proc.returncode,
            "stderr_tail": (proc.stderr or "")[-800:],
        }
    )
    if proc.returncode != 0:
        raise RenderError(f"loudnorm failed: {(proc.stderr or '')[-400:]}")

    info = probe_video(out_mp4)
    result = {
        "ok": True,
        "out_mp4": str(out_mp4),
        "duration_sec": info.duration_sec,
        "segments": segments,
        "ffmpeg_log": ffmpeg_log,
        "max_clip_sec": None,
        "loudness_target": plan.get("loudness_target"),
    }
    (work_dir / "render_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def measure_loudness(path: Path) -> Dict[str, Any]:
    ffmpeg = _require_ffmpeg()
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-i",
        str(path),
        "-af",
        "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=600)
    text = (proc.stderr or "") + (proc.stdout or "")
    # parse last JSON object
    start = text.rfind("{")
    end = text.rfind("}")
    parsed: Dict[str, Any] = {}
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            parsed = {"parse_error": True, "raw_tail": text[-500:]}
    return {"returncode": proc.returncode, "loudnorm": parsed}


def extract_still(src: Path, t: float, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{t:.3f}",
            "-i",
            str(src),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(out),
        ],
        check=True,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    video = Path(argv[0]) if argv else DEFAULT_VIDEO
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)

    variants = {
        "long_primary": build_long_edl(),
        "short_bridge": build_short_edl(),
    }
    manifests = {}
    for name, edl in variants.items():
        plan = build_plan(edl, variant=name)
        edl_path = OUT_DIR / f"edl_{name}.json"
        plan_path = OUT_DIR / f"plan_{name}.json"
        edl_path.write_text(json.dumps(edl, ensure_ascii=False, indent=2), encoding="utf-8")
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        # also mirror into reports (small JSON)
        (REPORTS / f"{REPORT_PREFIX}_edl_{name}.json").write_text(
            json.dumps(edl, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (REPORTS / f"{REPORT_PREFIX}_plan_{name}.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        out_mp4 = OUT_DIR / f"croatia_preview_{REPORT_PREFIX}_{name}.mp4"
        work = OUT_DIR / f"work_{name}"
        print(f"[phase4e1] rendering {name} …", flush=True)
        result = render_variant(plan=plan, video=video, out_mp4=out_mp4, work_dir=work)
        loud = measure_loudness(out_mp4)
        result["loudness_measured"] = loud
        (OUT_DIR / f"manifest_{name}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        manifests[name] = result
        print(
            f"[phase4e1] {name} duration={result['duration_sec']:.2f}s "
            f"loud={loud.get('loudnorm', {}).get('input_i')}",
            flush=True,
        )

    # Write QC stills for former glitch preview times mapped via new timeline
    stills = OUT_DIR / "qc_stills"
    stills.mkdir(exist_ok=True)
    long_mp4 = Path(manifests["long_primary"]["out_mp4"])
    # Map: build expected preview times from segments
    t = 0.0
    timeline = []
    for seg in manifests["long_primary"]["segments"]:
        d = float(seg.get("duration") or 0)
        timeline.append((t, t + d, seg["segment_id"], seg.get("media_in"), seg.get("media_out")))
        t += d
    (OUT_DIR / "timeline_long_primary.json").write_text(
        json.dumps(
            [
                {
                    "preview_in": a,
                    "preview_out": b,
                    "segment_id": sid,
                    "media_in": mi,
                    "media_out": mo,
                }
                for a, b, sid, mi, mo in timeline
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    # Sample midpoints of previously-glitchy roles
    for sid, label in [
        ("seg_go_ahead_scoreboard_closer", "ga_board"),
        ("seg_third_goal_action", "third_goal"),
        ("seg_fourth_scoreboard", "fourth_board"),
    ]:
        for a, b, s, mi, mo in timeline:
            if s == sid:
                mid = (a + b) / 2
                extract_still(long_mp4, mid, stills / f"long_{label}_preview_{mid:.1f}.jpg")
                # also 3 samples
                for frac, tag in [(0.2, "a"), (0.5, "b"), (0.8, "c")]:
                    extract_still(
                        long_mp4, a + (b - a) * frac, stills / f"long_{label}_{tag}.jpg"
                    )
                break

    summary = {
        "phase": "4E.1",
        "source_glitch_ranges": SOURCE_GLITCH_RANGES,
        "variants": {
            k: {
                "out_mp4": v["out_mp4"],
                "duration_sec": v["duration_sec"],
                "loudness": v.get("loudness_measured"),
            }
            for k, v in manifests.items()
        },
    }
    (OUT_DIR / "build_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
