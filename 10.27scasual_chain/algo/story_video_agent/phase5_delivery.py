"""Phase 5 delivery: Story Plan → summary / graph / dual candidate MP4s.

Same cut timeline for story_clean.mp4 and story_qc.mp4.
No match-specific goal times. Optional glitch ranges only via explicit profile.
render_ready stays false; both variants are candidate_only.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from story_video_agent.media import probe_video
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

LOUDNORM_I = -16.0
LOUDNORM_TP = -1.5
LOUDNORM_LRA = 11.0

# Roles included in the single full-story cut (not dual narrative lengths)
_CUT_ROLE_HINTS = (
    "opponent_opening_goal_action",
    "equalizer_goal_action",
    "go_ahead_goal_action",
    "lead_extend_",
    "buildup",
    "ending",
)
_SKIP_SHOT_KINDS = {"replay_supplement", "unknown"}
_MAX_BUILDUP_CLIPS = 3
_MAX_SCOREBOARD_SEC = 3.5


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _window_covers(a: float, b: float, t: float, *, pad_before: float = 0.0, pad_after: float = 0.0) -> bool:
    return (a + pad_before) <= t <= (b - pad_after)


def apply_glitch_avoidance(
    media_in: float,
    media_out: float,
    ranges: Sequence[Tuple[float, float, str]],
    *,
    must_cover: Optional[float] = None,
    min_pad_before_anchor: float = 0.3,
    min_pad_after_anchor: float = 2.5,
    rebuild_pad_before: float = 8.0,
    rebuild_pad_after: float = 10.0,
) -> Tuple[float, float, List[Dict[str, Any]], Optional[str]]:
    """Shift window off glitch spans while preserving optional goal anchor.

    Returns ``(media_in, media_out, notes, integrity_failure)``.
    If ``must_cover`` is set and no clean window can still contain the anchor
    (with minimum pads), ``integrity_failure`` explains why — caller must not
    treat the clip as a complete goal action.
    """
    notes: List[Dict[str, Any]] = []
    a, b = float(media_in), float(media_out)
    ranges = list(ranges or [])

    def _avoid(a0: float, b0: float) -> Tuple[float, float]:
        aa, bb = a0, b0
        for ga, gb, lab in ranges:
            if bb <= ga or aa >= gb:
                continue
            if must_cover is not None:
                # Anchor inside glitch → cannot salvage this span
                if ga - 1e-6 <= must_cover <= gb + 1e-6:
                    notes.append(
                        {
                            "label": lab,
                            "action": "anchor_in_glitch",
                            "must_cover": must_cover,
                            "glitch": [ga, gb],
                        }
                    )
                    continue
                # Prefer the side that keeps the anchor
                if must_cover >= gb:
                    notes.append({"label": lab, "action": "raise_in_keep_anchor", "from": aa, "to": gb})
                    aa = max(aa, gb)
                elif must_cover <= ga:
                    notes.append({"label": lab, "action": "lower_out_keep_anchor", "from": bb, "to": ga})
                    bb = min(bb, ga)
                else:
                    # Should not happen if anchor not in glitch
                    notes.append({"label": lab, "action": "ambiguous_overlap", "glitch": [ga, gb]})
            else:
                # No anchor: prefer shorter trim
                if aa < gb <= bb and (gb - aa) <= (bb - ga):
                    notes.append({"label": lab, "action": "raise_in", "from": aa, "to": gb})
                    aa = gb
                elif aa < ga < bb:
                    notes.append({"label": lab, "action": "lower_out", "from": bb, "to": ga})
                    bb = ga
            if bb - aa < 0.5 and must_cover is None:
                notes.append({"label": lab, "action": "jump_past", "to": gb + 0.2})
                aa = gb + 0.2
                bb = max(bb, aa + 2.0)
        return aa, bb

    a, b = _avoid(a, b)

    if must_cover is not None:
        ok = (
            b - a >= (min_pad_before_anchor + min_pad_after_anchor)
            and _window_covers(
                a, b, must_cover, pad_before=0.0, pad_after=0.0
            )
            and must_cover - a >= min_pad_before_anchor - 1e-6
            and b - must_cover >= min_pad_after_anchor - 1e-6
        )
        # Also ensure no glitch remains overlapping window
        still_glitch = any(not (b <= ga or a >= gb) for ga, gb, _ in ranges)
        if (not ok) or still_glitch:
            # Rebuild tight window around anchor then re-avoid
            a2 = max(0.0, must_cover - rebuild_pad_before)
            b2 = must_cover + rebuild_pad_after
            notes.append(
                {
                    "action": "rebuild_around_anchor",
                    "must_cover": must_cover,
                    "from": [a, b],
                    "to": [a2, b2],
                }
            )
            a, b = _avoid(a2, b2)
            still_glitch = any(not (b <= ga or a >= gb) for ga, gb, _ in ranges)
            covers = _window_covers(a, b, must_cover)
            pads_ok = (
                covers
                and (must_cover - a) >= min_pad_before_anchor - 1e-6
                and (b - must_cover) >= min_pad_after_anchor - 1e-6
            )
            if still_glitch or not pads_ok:
                reason = "glitch_conflicts_with_goal_anchor"
                if any(
                    ga - 1e-6 <= must_cover <= gb + 1e-6 for ga, gb, _ in ranges
                ):
                    reason = "goal_anchor_inside_glitch"
                elif not covers:
                    reason = "goal_anchor_outside_clean_window"
                return round(a, 3), round(b, 3), notes, reason

    return round(a, 3), round(b, 3), notes, None


def select_delivery_rows(
    plan: Dict[str, Any],
    *,
    glitch_ranges: Optional[Sequence[Tuple[float, float, str]]] = None,
) -> List[Dict[str, Any]]:
    """One full story cut from Story Plan segments / candidate_edl."""
    segs = list(plan.get("segments") or [])
    if not segs:
        segs = list(plan.get("candidate_edl") or [])
    segs = sorted(
        segs,
        key=lambda s: (s.get("narrative_order") or 0, s.get("segment_id") or ""),
    )
    glitch_ranges = list(glitch_ranges or [])
    rows: List[Dict[str, Any]] = []
    buildup_n = 0
    has_goal_for_prefix: Dict[str, bool] = {}

    for seg in segs:
        role = str(seg.get("role") or "")
        shot = str(seg.get("shot_kind") or "")
        if shot in _SKIP_SHOT_KINDS:
            continue
        if seg.get("render_eligibility") == "blocked" and seg.get("media_in") is None:
            continue
        if "pending" in role:
            continue

        # Prefer live goal actions; keep short scoreboard only if no action for same prefix
        if "goal_action" in role and "pending" not in role:
            prefix = role.replace("_goal_action", "")
            has_goal_for_prefix[prefix] = True
        if "scoreboard" in role:
            # 无对应完整进球动作的扩大比分牌：留给 ending_final_scoreboard，避免重复且不伪装进球
            if role.startswith("lead_extend_") and "scoreboard" in role:
                prefix = role.split("_scoreboard")[0]
                if not has_goal_for_prefix.get(prefix):
                    continue
            tin = _safe_float(seg.get("media_in"))
            tout = _safe_float(seg.get("media_out"))
            if tin is not None and tout is not None and (tout - tin) > _MAX_SCOREBOARD_SEC:
                seg = dict(seg)
                seg["media_out"] = round(tin + _MAX_SCOREBOARD_SEC, 3)
                prov = dict(seg.get("time_provenance") or {})
                prov["shortened_scoreboard"] = True
                seg["time_provenance"] = prov

        if "buildup" in role or role.startswith("buildup"):
            buildup_n += 1
            if buildup_n > _MAX_BUILDUP_CLIPS:
                continue

        # 终场：优先终场比分确认；拒绝未过门禁的远处 match_end
        if role in ("ending", "ending_match_end") and (
            "ending_match_end_rejected" in str(seg.get("blocking_reasons") or [])
            or str(seg.get("selection_reason") or "") == "ending_event"
        ):
            # legacy/unverified match_end cut — do not ship (may be other-match feed)
            continue
        if role == "ending_pending":
            continue

        tin = _safe_float(seg.get("media_in"))
        tout = _safe_float(seg.get("media_out"))
        notes: List[Dict[str, Any]] = []
        integrity_fail: Optional[str] = None
        prov = dict(seg.get("time_provenance") or {})
        is_goal_action = (
            "goal_action" in role
            and "pending" not in role
            and "scoreboard" not in role
        )
        # 仅有比分牌不得标为完整进球动作
        if "scoreboard" in role:
            prov["not_a_goal_action"] = True
        must_cover: Optional[float] = None
        if is_goal_action:
            must_cover = _safe_float(prov.get("t_sec"))
            if must_cover is None and tin is not None and tout is not None:
                # fallback: mid-window is weak; prefer original center of action pad
                must_cover = round((tin + tout) / 2.0, 3)
                prov["anchor_fallback"] = "mid_window_untrusted"
        if tin is not None and tout is not None and glitch_ranges:
            tin, tout, notes, integrity_fail = apply_glitch_avoidance(
                tin,
                tout,
                glitch_ranges,
                must_cover=must_cover if is_goal_action else None,
            )
        elif tin is not None and tout is not None and is_goal_action and must_cover is not None:
            if not _window_covers(tin, tout, must_cover):
                integrity_fail = "goal_anchor_outside_window"

        blocks = list(seg.get("blocking_reasons") or []) + [
            "phase5_candidate_delivery",
            "semantic_unverified",
        ]
        goal_complete = True
        if is_goal_action and integrity_fail:
            goal_complete = False
            blocks.append(f"goal_integrity_failed:{integrity_fail}")
            blocks.append("needs_alternate_live_goal_search")
            # Do not ship incomplete attack-only clip as a complete goal action
            # Keep in EDL as补证 marker with times for QC, but flag explicitly
            role = f"{role}_incomplete" if not role.endswith("_incomplete") else role
            notes.append(
                {
                    "action": "demote_incomplete_goal",
                    "reason": integrity_fail,
                    "must_cover": must_cover,
                }
            )

        # Post-check: complete goals must still cover anchor after any trim
        if is_goal_action and goal_complete and must_cover is not None and tin is not None and tout is not None:
            if not _window_covers(tin, tout, must_cover):
                goal_complete = False
                integrity_fail = "goal_anchor_outside_final_window"
                blocks.append(f"goal_integrity_failed:{integrity_fail}")
                role = f"{role}_incomplete" if not role.endswith("_incomplete") else role

        row = {
            "edl_index": len(rows) + 1,
            "segment_id": seg.get("segment_id"),
            "beat": seg.get("beat"),
            "role": role,
            "shot_kind": shot,
            "is_replay": bool(seg.get("is_replay")),
            "media_in": tin,
            "media_out": tout,
            "time_status": seg.get("time_status"),
            "time_provenance": prov,
            "event_ids": list(seg.get("event_ids") or []),
            "frame_ids": list(seg.get("frame_ids") or []),
            "linked_live_event_id": seg.get("linked_live_event_id"),
            "narrative_order": seg.get("narrative_order"),
            "source_media_order": seg.get("source_media_order"),
            "render_eligibility": "candidate_only",
            "blocking_reasons": blocks,
            "confidence": seg.get("confidence"),
            "selection_reason": seg.get("selection_reason"),
            "narration": seg.get("narration") or "",
            "include_in_cut": True,
            "glitch_avoidance": notes,
            "goal_anchor_t_sec": must_cover if is_goal_action else None,
            "goal_action_complete": goal_complete if is_goal_action else None,
            "integrity_failure": integrity_fail,
            "evidence_refs": list(seg.get("evidence_refs") or []),
            "source_refs": list(seg.get("source_refs") or []),
        }
        if tin is None or tout is None:
            # skip untimed unless title
            if shot != "title_card":
                continue
        rows.append(row)
    return _dedupe_windows_prefer_ending(rows)


def _dedupe_windows_prefer_ending(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Same media window: keep ending_final_scoreboard over plain scoreboard."""
    by_win: Dict[Tuple[int, int], List[int]] = {}
    for i, r in enumerate(rows):
        tin, tout = _safe_float(r.get("media_in")), _safe_float(r.get("media_out"))
        if tin is None or tout is None:
            continue
        key = (int(round(tin * 100)), int(round(tout * 100)))
        by_win.setdefault(key, []).append(i)
    drop: set = set()
    for idxs in by_win.values():
        if len(idxs) < 2:
            continue
        roles = [(j, str(rows[j].get("role") or "")) for j in idxs]
        ending = [j for j, role in roles if role == "ending_final_scoreboard"]
        boards = [j for j, role in roles if "scoreboard" in role and role != "ending_final_scoreboard"]
        if ending and boards:
            drop.update(boards)
        elif len(boards) > 1:
            drop.update(boards[1:])
    out = [r for i, r in enumerate(rows) if i not in drop]
    for i, r in enumerate(out):
        r["edl_index"] = i + 1
        r["narrative_order"] = i + 1
    return out


def _score_label_from_plan(plan: Dict[str, Any], role: str) -> List[str]:
    """Business overlays from score_path / narration — no hardcoded match scores."""
    lines: List[str] = []
    beat = ""
    for seg in plan.get("segments") or []:
        if seg.get("role") == role:
            beat = str(seg.get("beat") or "")
            narr = str(seg.get("narration") or "")
            m = re.search(r"比分确认\s+(\d+:\d+)", narr)
            if m:
                lines.append(f"比分 {m.group(1)}")
            m2 = re.search(r"(\d+:\d+)", narr)
            if not lines and m2 and "scoreboard" in role:
                lines.append(f"比分 {m2.group(1)}")
            break
    if "opponent_opening" in role:
        lines = ["失球 · 落后开始"] + lines
    elif role.startswith("equalizer") and "goal" in role:
        lines = ["扳平"] + lines
    elif role.startswith("go_ahead") and "goal" in role:
        lines = ["反超"] + lines
    elif "lead_extend" in role and "goal" in role:
        lines = ["扩大优势"] + lines
    elif "buildup" in role:
        lines = ["蓄力"]
    elif role == "ending" or "ending" in role:
        lines = ["终场"]
    if beat and beat not in lines:
        lines = [beat] + lines
    return lines[:3]


def _clean_overlays(plan: Dict[str, Any], row: Dict[str, Any]) -> List[str]:
    """Business-facing: no tech banners on live footage.

    Title cards use placeholder_lines (clean). Gameplay: light narrative cue only.
    """
    role = str(row.get("role") or "")
    if row.get("shot_kind") == "title_card":
        return []
    # Soft beat cue only — no candidate_only / media timestamps / event ids
    labels = _score_label_from_plan(plan, role.replace("_incomplete", ""))
    return [x for x in labels if x and "candidate" not in x.lower()][:2]


def _qc_overlays(plan: Dict[str, Any], row: Dict[str, Any]) -> List[str]:
    a = row.get("media_in")
    b = row.get("media_out")
    eids = ",".join(str(x) for x in (row.get("event_ids") or [])[:3]) or "-"
    complete = row.get("goal_action_complete")
    anchor = row.get("goal_anchor_t_sec")
    lines = [
        "内部 QC · candidate_only · render_ready=false",
        f"{row.get('beat') or ''} | {row.get('role') or ''}",
        f"media {a}-{b} | {row.get('time_status')}",
        f"eid:{eids}",
    ]
    if anchor is not None:
        lines.append(f"anchor={anchor} complete={complete}")
    if row.get("integrity_failure"):
        lines.append(f"integrity:{row.get('integrity_failure')}")
    return lines


def render_dual_delivery(
    *,
    plan: Dict[str, Any],
    video: Path,
    out_dir: Path,
    delivery_edl: Sequence[Dict[str, Any]],
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    fps: int = DEFAULT_FPS,
) -> Dict[str, Any]:
    """Render story_clean.mp4 and story_qc.mp4 from the same EDL timeline."""
    ffmpeg = _require_ffmpeg()
    media = probe_video(video)
    has_audio = bool(media.audio_codec)
    out_dir.mkdir(parents=True, exist_ok=True)
    results: Dict[str, Any] = {}

    for variant, overlay_fn, name in (
        ("clean", _clean_overlays, "story_clean.mp4"),
        ("qc", _qc_overlays, "story_qc.mp4"),
    ):
        work = out_dir / f"_work_{variant}"
        clips_dir = work / "clips"
        clips_dir.mkdir(parents=True, exist_ok=True)
        clip_paths: List[Path] = []
        ffmpeg_log: List[Dict[str, Any]] = []
        seg_meta: List[Dict[str, Any]] = []

        for i, row in enumerate(delivery_edl):
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
            }
            tin, tout = row.get("media_in"), row.get("media_out")
            if tin is None or tout is None:
                if variant == "qc":
                    lines = list(
                        row.get("placeholder_lines_qc")
                        or row.get("placeholder_lines")
                        or ["标题", sid]
                    )
                else:
                    lines = list(row.get("placeholder_lines") or ["标题", sid])
                rec = _make_placeholder(
                    ffmpeg=ffmpeg,
                    out_path=clip_path,
                    duration=float(row.get("placeholder_sec") or 2.5),
                    width=width,
                    height=height,
                    fps=fps,
                    lines=lines,
                )
                ffmpeg_log.append(rec)
                meta["placeholder"] = True
            else:
                a, b = float(tin), float(tout)
                overlays = overlay_fn(plan, row)
                af = f"aresample={DEFAULT_AUDIO_RATE},dynaudnorm=f=150:g=15"
                try:
                    rec = _cut_segment(
                        ffmpeg=ffmpeg,
                        src=Path(media.path),
                        media_in=a,
                        media_out=b,
                        out_path=clip_path,
                        width=width,
                        height=height,
                        fps=fps,
                        has_audio=has_audio,
                        overlay_lines=overlays,
                        accurate_seek=True,
                        audio_filter=af,
                    )
                    ffmpeg_log.append(rec)
                    meta["cut"] = True
                except RenderError as exc:
                    meta["skip_reason"] = str(exc)
                    rec = _make_placeholder(
                        ffmpeg=ffmpeg,
                        out_path=clip_path,
                        duration=2.5,
                        width=width,
                        height=height,
                        fps=fps,
                        lines=["裁切失败", sid, str(exc)[:40]],
                    )
                    ffmpeg_log.append(rec)
                    meta["placeholder"] = True
            clip_paths.append(clip_path)
            seg_meta.append(meta)

        raw_mp4 = work / "concat_raw.mp4"
        ffmpeg_log.append(
            _concat_clips(ffmpeg=ffmpeg, clip_paths=clip_paths, out_mp4=raw_mp4)
        )
        out_mp4 = out_dir / name
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
        proc = subprocess.run(
            loud_cmd, capture_output=True, text=True, check=False, timeout=1200
        )
        ffmpeg_log.append(
            {
                "label": "loudnorm_master",
                "returncode": proc.returncode,
                "stderr_tail": (proc.stderr or "")[-300:],
            }
        )
        if proc.returncode != 0:
            raise RenderError(f"loudnorm failed ({variant}): {(proc.stderr or '')[-400:]}")
        info = probe_video(out_mp4)
        results[variant] = {
            "out_mp4": str(out_mp4),
            "duration_sec": info.duration_sec,
            "segments": seg_meta,
            "ffmpeg_log_n": len(ffmpeg_log),
        }
    return results


def build_story_title(plan: Dict[str, Any], story: Dict[str, Any]) -> str:
    proto = (plan.get("protagonist") or {}).get("team_name") or ""
    teams = (plan.get("protagonist") or {}).get("teams") or {}
    left = teams.get("left") or ""
    right = teams.get("right") or ""
    if proto and left and right:
        other = right if proto == left else left
        return f"{proto} 逆转 {other}"
    match_id = str(story.get("match_id") or plan.get("match_id") or "比赛")
    return f"T01 逆风翻盘 · {match_id}"


def _beat_plain_label(role: str) -> str:
    role = role.replace("_incomplete", "")
    if "opponent_opening" in role and "goal" in role:
        return "对手造成落后的进球动作"
    if "deficit" in role or ("scoreboard" in role and "铺垫" in role):
        return "落后比分确认"
    if "equalizer" in role and "goal" in role:
        return "扳平进球动作"
    if "equalizer" in role:
        return "扳平比分确认"
    if "go_ahead" in role and "goal" in role:
        return "反超进球动作"
    if "go_ahead" in role:
        return "反超比分确认"
    if "lead_extend" in role and "goal" in role:
        return "扩大优势进球动作"
    if "lead_extend" in role:
        return "扩大优势比分确认"
    if "buildup" in role:
        return "蓄力阶段相关进攻/事件"
    if "ending" in role:
        return "终场/收尾画面"
    if "title" in role:
        return "标题卡"
    return role


def build_story_summary_md(
    *,
    plan: Dict[str, Any],
    story: Dict[str, Any],
    delivery_edl: Sequence[Dict[str, Any]],
    title: str,
) -> str:
    """甲方可读正文 + 技术附录。不编造球员/战术/未证实因果。"""
    teams = (plan.get("protagonist") or {}).get("teams") or {}
    side = (plan.get("protagonist") or {}).get("side")
    proto = (plan.get("protagonist") or {}).get("team_name") or "主角队"
    other = ""
    if proto and teams:
        other = teams.get("right") if proto == teams.get("left") else teams.get("left")
        other = other or ""
    score_path = [n for n in (story.get("score_path") or []) if isinstance(n, dict)]

    # Score arc in plain language (from structured path only)
    score_plain = []
    for n in score_path:
        who = n.get("delta_side")
        who_name = teams.get(str(who)) if who else None
        if who_name:
            score_plain.append(f"{n.get('score')}（{who_name}取得进球后的比分确认）")
        else:
            score_plain.append(str(n.get("score")))

    goal_rows = [
        r
        for r in delivery_edl
        if "goal_action" in str(r.get("role") or "") and r.get("shot_kind") != "title_card"
    ]
    complete_goals = [r for r in goal_rows if r.get("goal_action_complete") is not False]
    incomplete_goals = [r for r in goal_rows if r.get("goal_action_complete") is False]
    missing = list(plan.get("missing_evidence") or [])

    # ~200–400字摘要：只用结构化事实
    left_n = teams.get("left") or "主队"
    right_n = teams.get("right") or "客队"
    # 最后一次落后弧（非整场所有进球默认全收）
    arc_note = ""
    has_open = any("opponent_opening" in str(r.get("role")) for r in delivery_edl)
    has_eq = any("equalizer_goal" in str(r.get("role")) for r in delivery_edl)
    has_ga = any("go_ahead_goal" in str(r.get("role")) for r in delivery_edl)
    if has_open and has_eq and has_ga:
        arc_note = (
            f"本摘要主线是{proto}在「最后一次落后」之后完成的扳平与反超"
            "（T01 最后一次落后弧），并不默认展开赛前所有历史进球过程。"
        )
    abstract = (
        f"本场为「逆风翻盘」类型故事。对阵双方为{left_n}与{right_n}，"
        f"系统认定的故事主角是{proto}"
        + (f"（对手为{other}）" if other else "")
        + "。"
        + arc_note
    )
    if score_plain:
        abstract += "比分确认轨迹为：" + " → ".join(score_plain) + "。"
        abstract += "上述时间为记分牌确认锚点，不等于进球动作发生时刻。"
    abstract += (
        "叙事按铺垫、蓄力、转折、高潮、收尾组织："
        "先交代造成（该弧内）落后的失球，再收录落后期间的相关进攻，"
        "随后是扳平与反超（及可能的扩大优势），最后以终场比分确认收束"
        "（远处「比赛结束」标注若不紧邻终场比分则不采用，以免误切其它转播）。"
    )
    abstract += (
        f"当前结构化收录了 {len(complete_goals)} 个判定为窗口完整的进球动作候选"
    )
    if incomplete_goals or missing:
        abstract += (
            f"，另有 {len(incomplete_goals)} 个进球动作因证据不足或花屏冲突降级为补证，"
            "摘要不将其表述为已核实进球。"
        )
    else:
        abstract += "。"
    abstract += "本文仅陈述算法已结构化的事实；未经验证的战术、球员动作与因果不作断言。"

    # Five beats in plain language
    beat_blocks: List[str] = []
    for beat in ("铺垫", "蓄力", "转折", "高潮", "收尾"):
        items = [r for r in delivery_edl if r.get("beat") == beat]
        if not items:
            beat_blocks.append(f"### {beat}\n本段暂无入选镜头，或证据不足未编排。")
            continue
        lines_b = [f"### {beat}"]
        for r in items:
            label = _beat_plain_label(str(r.get("role") or ""))
            tin, tout = r.get("media_in"), r.get("media_out")
            if tin is None:
                lines_b.append(f"- {label}（标题/说明卡）")
                continue
            status = "窗口完整候选" if r.get("goal_action_complete") is not False or "goal_action" not in str(r.get("role")) else "不完整·待补证"
            if "goal_action" in str(r.get("role") or ""):
                status = "进球动作候选·窗口完整" if r.get("goal_action_complete") is not False else "进球动作·不完整待补证"
            elif "scoreboard" in str(r.get("role") or ""):
                status = "比分确认（非进球动作）"
            lines_b.append(
                f"- {label}：原片约 {tin:.1f}–{tout:.1f} 秒；{status}。"
            )
        beat_blocks.append("\n".join(lines_b))

    # Relations in plain language
    rel_lines = [
        "- 叙事承接：各段按故事顺序衔接，**不代表**已证实战术因果。",
        "- 时间先后：有时间戳的镜头按原片时间排序。",
        "- 比分状态：score_path 相邻节点表示记分牌确认的比分变化。",
        "- 事件关联：进球镜头与事件表/因果链 live 进球的规则匹配；"
        "**不等于**独立语义核验通过，也**不等于**已证实攻防因果。",
    ]

    # Gaps
    gap_lines = []
    for r in incomplete_goals:
        gap_lines.append(
            f"- {_beat_plain_label(str(r.get('role')))}："
            f"完整性失败原因 `{r.get('integrity_failure')}`；"
            f"锚点 {r.get('goal_anchor_t_sec')}；需另搜可用直播镜头。"
        )
    for m in missing:
        gap_lines.append(f"- 缺失证据标记：{m}")
    if not gap_lines:
        gap_lines.append("- 当前无额外补证条目（仍整体为候选，未做独立语义签发）。")

    # Tech appendix table
    tech_rows = [
        "| 段 | 叙事位 | 角色 | 原片入点 | 原片出点 | 关联事件 | 时间状态 | 进球完整 | 核验 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in delivery_edl:
        tech_rows.append(
            f"| {r.get('segment_id')} | {r.get('beat')} | {r.get('role')} | "
            f"{r.get('media_in')} | {r.get('media_out')} | {r.get('event_ids')} | "
            f"{r.get('time_status')} | {r.get('goal_action_complete')} | "
            f"candidate_only / semantic_unverified |"
        )

    lines = [
        f"# {title}",
        "",
        "> 本稿为咪咕甲方可读的故事链内容摘要（候选审核）。"
        "非正式生产授权；画面语义尚未独立核验通过。",
        "",
        "## 比赛与故事类型",
        f"- 对阵：{left_n} vs {right_n}",
        f"- 故事类型：逆风翻盘（T01）",
        f"- 故事主角：{proto}",
        "",
        "## 故事标题",
        title,
        "",
        "## 故事摘要",
        abstract,
        "",
        "## 五段叙事过程",
        "\n\n".join(beat_blocks),
        "",
        "## 关键比分变化",
    ]
    if score_path:
        for n in score_path:
            lines.append(
                f"- 比分确认 **{n.get('score')}**（记分牌锚点约 {n.get('t_sec')} 秒；"
                f"非进球动作时刻）"
            )
    else:
        lines.append("- （无比分轨迹）")
    lines.extend(
        [
            "",
            "## 事件关系说明",
            "\n".join(rel_lines),
            "",
            "## 镜头来源与核验状态（概要）",
            "- 业务版与内部 QC 版共用同一剪辑时间轴（同一 EDL）。",
            "- 全部镜头为算法候选：`render_ready=false`，未授予正式成片。",
            "- 进球动作优先绑定事件表/因果链中的 live 进球时间；比分牌仅作确认，不替代进球。",
            f"- 完整进球动作候选 {len(complete_goals)} 个；不完整/补证 {len(incomplete_goals)} 个。",
            "",
            "## 不能确认的关键事实与缺失证据",
            "\n".join(gap_lines),
            "",
            "---",
            "",
            "## 技术附录",
            "",
            "以下字段供研发/算法复审，不作为甲方主读内容。完整图见 `story_graph.json`，"
            "剪辑表见 `candidate_edl.json`，方案见 `story_plan.json`。",
            "",
            f"- match_id: `{story.get('match_id') or plan.get('match_id')}`",
            f"- story_tier: `{plan.get('story_tier')}`",
            f"- protagonist_side: `{side}`",
            f"- blocking_reasons: `{plan.get('blocking_reasons')}`",
            "",
            "\n".join(tech_rows),
            "",
        ]
    )
    return "\n".join(lines)


def validate_story_graph(graph: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Ensure every edge endpoint exists; relation types are declared; no forged semantic pass."""
    problems: List[str] = []
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    ids = {str(n.get("id")) for n in nodes if n.get("id") is not None}
    if len(ids) != len([n for n in nodes if n.get("id") is not None]):
        problems.append("duplicate_node_id")
    allowed = set(graph.get("relation_types") or [])
    for i, e in enumerate(edges):
        s, t = str(e.get("source")), str(e.get("target"))
        if s not in ids:
            problems.append(f"edge[{i}].source_missing:{s}")
        if t not in ids:
            problems.append(f"edge[{i}].target_missing:{t}")
        rel = e.get("relation")
        if allowed and rel not in allowed:
            problems.append(f"edge[{i}].unknown_relation:{rel}")
        # Candidate associations must not claim semantic verification done
        if e.get("relation") == "event_association" and e.get("semantic_verified") is True:
            problems.append(f"edge[{i}].forged_semantic_verified")
        if e.get("relation") == "causal_verified" and not e.get("independent_verification"):
            problems.append(f"edge[{i}].causal_verified_without_independent_check")
    return (not problems), problems


def build_story_graph(
    *,
    plan: Dict[str, Any],
    story: Dict[str, Any],
    delivery_edl: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Typed nodes/edges; all endpoints exist; no conflation of relation kinds."""
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    id_set: set = set()

    def add_node(node: Dict[str, Any]) -> str:
        nid = str(node["id"])
        if nid in id_set:
            return nid
        id_set.add(nid)
        nodes.append(node)
        return nid

    seg_ids: List[str] = []
    for row in delivery_edl:
        nid = str(row.get("segment_id") or f"seg_{len(seg_ids)}")
        seg_ids.append(
            add_node(
                {
                    "id": nid,
                    "type": "story_segment",
                    "beat": row.get("beat"),
                    "role": row.get("role"),
                    "media_in": row.get("media_in"),
                    "media_out": row.get("media_out"),
                    "time_status": row.get("time_status"),
                    "shot_kind": row.get("shot_kind"),
                    "goal_action_complete": row.get("goal_action_complete"),
                }
            )
        )
        for eid in row.get("event_ids") or []:
            add_node(
                {
                    "id": f"event:{eid}",
                    "type": "event",
                    "event_id": eid,
                    "linked_from_segment": nid,
                }
            )

    # Narrative succession among segments only
    for i in range(len(seg_ids) - 1):
        edges.append(
            {
                "source": seg_ids[i],
                "target": seg_ids[i + 1],
                "relation": "narrative_succession",
                "evidence": "delivery_edl_order",
                "semantic_verified": False,
                "note": "剪辑叙事承接，非已证实因果",
            }
        )

    seg_by_id = {n["id"]: n for n in nodes if n.get("type") == "story_segment"}
    timed = [
        (sid, _safe_float(seg_by_id[sid].get("media_in")))
        for sid in seg_ids
        if _safe_float(seg_by_id.get(sid, {}).get("media_in")) is not None
    ]
    timed.sort(key=lambda x: x[1] or 0)
    for i in range(len(timed) - 1):
        edges.append(
            {
                "source": timed[i][0],
                "target": timed[i + 1][0],
                "relation": "temporal_before",
                "evidence": "media_in_order",
                "semantic_verified": False,
                "note": "原片时间先后（可核对时间戳）",
            }
        )

    sp = [n for n in (story.get("score_path") or []) if isinstance(n, dict)]
    score_ids: List[str] = []
    for i, node in enumerate(sp):
        sid = add_node(
            {
                "id": f"score:{i}:{node.get('score')}",
                "type": "score_state",
                "score": node.get("score"),
                "t_sec": node.get("t_sec"),
                "delta_side": node.get("delta_side"),
                "carrier_event_id": node.get("carrier_event_id"),
            }
        )
        score_ids.append(sid)
        if i > 0:
            edges.append(
                {
                    "source": score_ids[i - 1],
                    "target": sid,
                    "relation": "score_state_change",
                    "evidence": "score_path",
                    "semantic_verified": False,
                    "note": "比分状态变化（记分牌锚点）",
                }
            )

    # Event association (rule-matched); NOT causal_verified / NOT semantic pass
    for row in delivery_edl:
        sid = str(row.get("segment_id"))
        for eid in row.get("event_ids") or []:
            ev_nid = f"event:{eid}"
            if ev_nid not in id_set:
                add_node({"id": ev_nid, "type": "event", "event_id": eid})
            edges.append(
                {
                    "source": sid,
                    "target": ev_nid,
                    "relation": "event_association",
                    "evidence": "segment_event_ids",
                    "semantic_verified": False,
                    "note": "镜头–事件规则关联；未做独立语义核验",
                }
            )
        for ref in row.get("evidence_refs") or []:
            if not isinstance(ref, dict):
                continue
            src = str(ref.get("source") or "")
            if not ref.get("used_as_fact"):
                continue
            if src not in (
                "live_goal_candidate",
                "opponent_opening_live_goal",
                "replay_linked_to_live",
            ):
                continue
            eid = ref.get("event_id") or ref.get("linked_live_event_id")
            if not eid:
                continue
            ev_nid = f"event:{eid}"
            if ev_nid not in id_set:
                add_node({"id": ev_nid, "type": "event", "event_id": eid})
            # Avoid duplicate association edges
            if any(
                e.get("source") == sid
                and e.get("target") == ev_nid
                and e.get("relation") == "event_association"
                for e in edges
            ):
                continue
            edges.append(
                {
                    "source": sid,
                    "target": ev_nid,
                    "relation": "event_association",
                    "evidence": src,
                    "semantic_verified": False,
                    "note": "规则证据上的事件关联；非已证实战术因果，非语义签发",
                }
            )

    graph = {
        "schema": "phase5_1_story_graph_v2",
        "match_id": story.get("match_id") or plan.get("match_id"),
        "nodes": nodes,
        "edges": edges,
        "relation_types": [
            "event_association",
            "score_state_change",
            "temporal_before",
            "narrative_succession",
            # reserved: only when independent verification exists
            "causal_verified",
        ],
        "disclaimer": (
            "narrative_succession / temporal_before / score_state_change / event_association "
            "均不得解释为已完成的独立语义核验或战术因果证实；"
            "causal_verified 仅在具备 independent_verification 时使用（本阶段不自动产出）。"
        ),
    }
    ok, problems = validate_story_graph(graph)
    graph["structure_ok"] = ok
    graph["structure_problems"] = problems
    return graph


def load_glitch_profile(path: Optional[Path]) -> List[Tuple[float, float, str]]:
    if path is None:
        return []
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = data.get("ranges") if isinstance(data, dict) else data
    out: List[Tuple[float, float, str]] = []
    for r in rows or []:
        out.append(
            (
                float(r["media_in"] if isinstance(r, dict) else r[0]),
                float(r["media_out"] if isinstance(r, dict) else r[1]),
                str(r.get("label") if isinstance(r, dict) else (r[2] if len(r) > 2 else "glitch")),
            )
        )
    return out
