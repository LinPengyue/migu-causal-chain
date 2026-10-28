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


def apply_glitch_avoidance(
    media_in: float,
    media_out: float,
    ranges: Sequence[Tuple[float, float, str]],
) -> Tuple[float, float, List[Dict[str, Any]]]:
    """Shift window endpoints off explicit glitch spans. No default ranges."""
    notes: List[Dict[str, Any]] = []
    a, b = float(media_in), float(media_out)
    for ga, gb, lab in ranges:
        if b <= ga or a >= gb:
            continue
        # Prefer keep action after glitch if overlap near start
        if a < gb <= b and (gb - a) < (b - ga):
            notes.append({"label": lab, "action": "raise_in", "from": a, "to": gb})
            a = gb
        elif a < ga < b:
            notes.append({"label": lab, "action": "lower_out", "from": b, "to": ga})
            b = ga
        if b - a < 0.5:
            # fallback: jump past glitch
            notes.append({"label": lab, "action": "jump_past", "to": gb + 0.2})
            a = gb + 0.2
            b = max(b, a + 2.0)
    return round(a, 3), round(b, 3), notes


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

        tin = _safe_float(seg.get("media_in"))
        tout = _safe_float(seg.get("media_out"))
        notes: List[Dict[str, Any]] = []
        if tin is not None and tout is not None and glitch_ranges:
            tin, tout, notes = apply_glitch_avoidance(tin, tout, glitch_ranges)

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
            "time_provenance": seg.get("time_provenance") or {},
            "event_ids": list(seg.get("event_ids") or []),
            "frame_ids": list(seg.get("frame_ids") or []),
            "linked_live_event_id": seg.get("linked_live_event_id"),
            "narrative_order": seg.get("narrative_order"),
            "source_media_order": seg.get("source_media_order"),
            "render_eligibility": "candidate_only",
            "blocking_reasons": list(seg.get("blocking_reasons") or [])
            + ["phase5_candidate_delivery", "semantic_unverified"],
            "confidence": seg.get("confidence"),
            "selection_reason": seg.get("selection_reason"),
            "narration": seg.get("narration") or "",
            "include_in_cut": True,
            "glitch_avoidance": notes,
            "evidence_refs": list(seg.get("evidence_refs") or []),
            "source_refs": list(seg.get("source_refs") or []),
        }
        if tin is None or tout is None:
            # skip untimed unless title
            if shot != "title_card":
                continue
        rows.append(row)
    return rows


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
    title = (plan.get("narration") or {}).get("title") or "T01 逆风翻盘"
    role = str(row.get("role") or "")
    lines = ["候选审核样片", str(title)[:40]]
    lines.extend(_score_label_from_plan(plan, role))
    return lines[:4]


def _qc_overlays(plan: Dict[str, Any], row: Dict[str, Any]) -> List[str]:
    a = row.get("media_in")
    b = row.get("media_out")
    eids = ",".join(str(x) for x in (row.get("event_ids") or [])[:3]) or "-"
    return [
        "内部 QC · candidate_only",
        f"{row.get('beat') or ''} | {row.get('role') or ''}",
        f"media {a}-{b} | {row.get('time_status')}",
        f"eid:{eids}",
        f"elig:{row.get('render_eligibility')}",
    ]


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


def build_story_summary_md(
    *,
    plan: Dict[str, Any],
    story: Dict[str, Any],
    delivery_edl: Sequence[Dict[str, Any]],
    title: str,
) -> str:
    teams = (plan.get("protagonist") or {}).get("teams") or {}
    side = (plan.get("protagonist") or {}).get("side")
    proto = (plan.get("protagonist") or {}).get("team_name") or f"side={side}"
    score_path = story.get("score_path") or []
    score_lines = []
    for n in score_path:
        if isinstance(n, dict):
            score_lines.append(
                f"- {n.get('score')} @ {n.get('t_sec')}s"
                f"（delta_side={n.get('delta_side')}）"
            )

    by_beat: Dict[str, List[str]] = {}
    for row in delivery_edl:
        beat = str(row.get("beat") or "?")
        by_beat.setdefault(beat, []).append(
            f"- **{row.get('role')}** | media "
            f"{row.get('media_in')}-{row.get('media_out')} | "
            f"events={row.get('event_ids')} | "
            f"{row.get('selection_reason')} | "
            f"status={row.get('time_status')} / {row.get('render_eligibility')}"
        )

    # Natural-language abstract from structured facts only
    milestones = []
    for row in delivery_edl:
        role = str(row.get("role") or "")
        if "goal_action" in role:
            milestones.append(f"{row.get('beat')}段纳入 {role}（事件 {row.get('event_ids')}）")
    abstract_parts = [
        f"本场由 T01 识别为逆风翻盘故事（tier={plan.get('story_tier')}），"
        f"主角为 {proto}（side={side}）。",
        f"球队：{teams.get('left') or '?'} vs {teams.get('right') or '?'}。",
    ]
    if score_path:
        first = score_path[0].get("score") if isinstance(score_path[0], dict) else "?"
        last = score_path[-1].get("score") if isinstance(score_path[-1], dict) else "?"
        abstract_parts.append(
            f"比分轨迹自 {first} 至终场相关节点 {last}（详见下表；记分牌时间为确认锚点，"
            f"不等于进球动作时刻）。"
        )
    abstract_parts.append(
        "叙事按铺垫→蓄力→转折→高潮→收尾组织；进球镜头优先关联因果/事件表中的 live 进球，"
        "回放不作独立主叙事。以下摘要仅陈述系统已结构化收录的事件与关系，"
        "未经验证的因果不作事实断言。"
    )
    if milestones:
        abstract_parts.append("关键动作收录：" + "；".join(milestones) + "。")
    abstract = "".join(abstract_parts)
    # keep ~200-400 Chinese chars where possible
    if len(abstract) < 180:
        abstract += (
            f"交付为候选审核样片（render_ready=false）；"
            f"共 {len(delivery_edl)} 个剪辑段，业务版与 QC 版共用同一 EDL。"
        )

    why_selected = []
    for row in delivery_edl:
        why_selected.append(
            f"- `{row.get('segment_id')}`：{row.get('selection_reason')} — {row.get('narration')}"
        )

    relations = []
    for row in delivery_edl:
        for ref in row.get("evidence_refs") or []:
            if isinstance(ref, dict) and ref.get("used_as_fact"):
                relations.append(
                    f"- 证据({ref.get('kind')}/{ref.get('source')}): "
                    f"{json.dumps(ref, ensure_ascii=False)[:200]}"
                )
    relations = relations[:40]

    beats_block = []
    for beat in ("铺垫", "蓄力", "转折", "高潮", "收尾"):
        items = by_beat.get(beat) or ["- （本场该段无入选镜头或证据不足）"]
        beats_block.append(f"### {beat}\n" + "\n".join(items))

    lines = [
        f"# 故事链内容摘要：{title}",
        "",
        "> 内部候选交付 · `render_ready=false` · 非正式生产授权",
        "",
        "## 1. 比赛信息与故事类型",
        f"- match_id: `{story.get('match_id') or plan.get('match_id')}`",
        f"- 故事类型: T01 逆风翻盘（tier=`{plan.get('story_tier')}`）",
        f"- 主角: {proto}（{side}）",
        f"- 球队: left={teams.get('left')} / right={teams.get('right')}",
        "",
        "## 2. 故事标题",
        f"**{title}**",
        "",
        "## 3. 故事摘要",
        abstract,
        "",
        "## 4. 五段叙事结构",
        "\n\n".join(beats_block),
        "",
        "## 5. 关键比分变化",
        "\n".join(score_lines) if score_lines else "- （无 score_path）",
        "",
        "## 6. 关键事件为何入选",
        "\n".join(why_selected) if why_selected else "- （无）",
        "",
        "## 7. 事件关系与证据（摘要）",
        "关系类型详见 `story_graph.json`（因果 / 比分状态 / 时间先后 / 叙事承接分边）。",
        "\n".join(relations) if relations else "- （无 used_as_fact 证据条目）",
        "",
        "## 8. 时间与核验",
        "| segment | beat | media_in | media_out | events | time_status | eligibility |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in delivery_edl:
        lines.append(
            f"| {row.get('segment_id')} | {row.get('beat')} | {row.get('media_in')} | "
            f"{row.get('media_out')} | {row.get('event_ids')} | {row.get('time_status')} | "
            f"{row.get('render_eligibility')} |"
        )
    lines.extend(
        [
            "",
            "## 门禁",
            f"- render_ready: `{plan.get('render_ready')}`",
            f"- blocking: {plan.get('blocking_reasons')}",
            f"- missing_evidence: {plan.get('missing_evidence')}",
            "",
        ]
    )
    return "\n".join(lines)


def build_story_graph(
    *,
    plan: Dict[str, Any],
    story: Dict[str, Any],
    delivery_edl: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Nodes + typed edges; do not conflate causal vs temporal vs narrative."""
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    node_ids: List[str] = []

    for row in delivery_edl:
        nid = str(row.get("segment_id") or f"n{len(nodes)}")
        node_ids.append(nid)
        nodes.append(
            {
                "id": nid,
                "type": "story_segment",
                "beat": row.get("beat"),
                "role": row.get("role"),
                "event_ids": row.get("event_ids"),
                "media_in": row.get("media_in"),
                "media_out": row.get("media_out"),
                "time_status": row.get("time_status"),
                "shot_kind": row.get("shot_kind"),
            }
        )

    # Narrative succession (not causal)
    for i in range(len(node_ids) - 1):
        edges.append(
            {
                "source": node_ids[i],
                "target": node_ids[i + 1],
                "relation": "narrative_succession",
                "evidence": "delivery_edl_order",
                "proven": False,
                "note": "剪辑叙事承接，非已证实因果",
            }
        )

    # Temporal order when both timed
    timed = [
        (nid, _safe_float(n["media_in"]))
        for nid, n in zip(node_ids, nodes)
        if _safe_float(n.get("media_in")) is not None
    ]
    timed.sort(key=lambda x: x[1] or 0)
    for i in range(len(timed) - 1):
        edges.append(
            {
                "source": timed[i][0],
                "target": timed[i + 1][0],
                "relation": "temporal_before",
                "evidence": "media_in_order",
                "proven": True,
            }
        )

    # Score-state edges from score_path
    sp = [n for n in (story.get("score_path") or []) if isinstance(n, dict)]
    for i, node in enumerate(sp):
        sid = f"score_{i}_{node.get('score')}"
        nodes.append(
            {
                "id": sid,
                "type": "score_state",
                "score": node.get("score"),
                "t_sec": node.get("t_sec"),
                "delta_side": node.get("delta_side"),
                "carrier_event_id": node.get("carrier_event_id"),
            }
        )
        if i > 0:
            prev = f"score_{i-1}_{sp[i-1].get('score')}"
            edges.append(
                {
                    "source": prev,
                    "target": sid,
                    "relation": "score_state_change",
                    "evidence": "score_path",
                    "proven": True,
                    "note": "比分状态变化（记分牌锚点）",
                }
            )

    # Evidenced causal only when composer marked used_as_fact causal/live link
    for row in delivery_edl:
        sid = str(row.get("segment_id"))
        for ref in row.get("evidence_refs") or []:
            if not isinstance(ref, dict):
                continue
            src = str(ref.get("source") or "")
            if ref.get("used_as_fact") and src in (
                "live_goal_candidate",
                "opponent_opening_live_goal",
                "replay_linked_to_live",
            ):
                edges.append(
                    {
                        "source": sid,
                        "target": str(ref.get("event_id") or ref.get("linked_live_event_id")),
                        "relation": "evidenced_association",
                        "evidence": src,
                        "proven": True,
                        "note": "事件关联有规则证据；不等于战术因果已证实",
                    }
                )

    return {
        "schema": "phase5_story_graph_v1",
        "match_id": story.get("match_id") or plan.get("match_id"),
        "nodes": nodes,
        "edges": edges,
        "relation_types": [
            "evidenced_association",
            "score_state_change",
            "temporal_before",
            "narrative_succession",
        ],
        "disclaimer": (
            "叙事承接与时间先后不得解释为已证实因果；"
            "仅 evidenced_association 且 used_as_fact 的边表示有规则证据的事件关联。"
        ),
    }


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
