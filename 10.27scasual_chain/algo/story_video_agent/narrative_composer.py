"""Phase 3A：Narrative Composer — T01 五段故事线编排（规则基线 + 可选 LLM 润色）。

- story：完整候选编排
- candidate：不完整方案 + missing_evidence
- none：不强行生成翻盘故事
- 回放仅作 replay_supplement，不驱动 live 主时序
- mock 视觉证据不得 used_as_fact
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from story_video_agent.api_provider import ApiProvider
from story_video_agent.story_output_schema import (
    ALGORITHM_ID,
    BEATS,
    SCHEMA_VERSION,
    TEMPLATE_ID,
    empty_plan,
    render_narrative_report,
    segments_to_edl,
    validate_compose_plan,
)
from story_video_agent.story_verifier import classify_visual_evidence, verify_story

_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)

PAD_BEFORE = 4.0
PAD_AFTER = 8.0
DEFAULT_DUR = 10.0


def _events_by_id(story: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(e["event_id"]): e
        for e in (story.get("events") or [])
        if isinstance(e, dict) and e.get("event_id")
    }


def _parse_score(score: str) -> Optional[Tuple[int, int]]:
    if not isinstance(score, str) or ":" not in score:
        return None
    a, b = score.split(":", 1)
    try:
        return int(a), int(b)
    except ValueError:
        return None


def _team_names(story: Dict[str, Any], causal: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if causal:
        return {
            "left": str(causal.get("team_1_name") or ""),
            "right": str(causal.get("team_2_name") or ""),
        }
    # fallback parse video_name / match_id "AvsB"
    name = str(story.get("match_id") or story.get("video_name") or "")
    for sep in ("vs", "VS", "对"):
        if sep in name:
            left, right = name.split(sep, 1)
            return {"left": left.strip(), "right": right.replace(".mp4", "").strip()}
    return {"left": "", "right": ""}


def _find_score_milestones(
    story: Dict[str, Any], side: str
) -> Dict[str, Optional[Dict[str, Any]]]:
    """定位落后确认、扳平、反超节点（相对主角）。"""
    nodes = [n for n in (story.get("score_path") or []) if isinstance(n, dict)]
    behind = equalizer = go_ahead = None
    prev_margin = None
    for node in nodes:
        pair = _parse_score(str(node.get("score") or ""))
        if not pair:
            continue
        margin = pair[0] - pair[1] if side == "left" else pair[1] - pair[0]
        if margin < 0 and behind is None:
            behind = node
        if prev_margin is not None:
            if prev_margin < 0 <= margin and equalizer is None:
                equalizer = node
            if prev_margin <= 0 < margin and go_ahead is None:
                # 从平或负到正
                if prev_margin == 0 and margin > 0:
                    go_ahead = node
                elif prev_margin < 0 and margin > 0:
                    go_ahead = node
        prev_margin = margin
    # 若 equalizer 后下一分即超车，go_ahead 可能等于下一节点
    if equalizer and go_ahead is None:
        eq_t = float(equalizer.get("t_sec") or 0)
        for node in nodes:
            t = float(node.get("t_sec") or 0)
            if t <= eq_t:
                continue
            pair = _parse_score(str(node.get("score") or ""))
            if not pair:
                continue
            margin = pair[0] - pair[1] if side == "left" else pair[1] - pair[0]
            if margin > 0:
                go_ahead = node
                break
    return {"behind": behind, "equalizer": equalizer, "go_ahead": go_ahead}


def _window_from_t(
    t: Optional[float], *, status: str, pad_before: float = PAD_BEFORE, pad_after: float = PAD_AFTER
) -> Dict[str, Any]:
    if t is None:
        return {
            "media_in": None,
            "media_out": None,
            "time_status": "pending_localization",
            "precise_claim": False,
        }
    start = max(0.0, float(t) - pad_before)
    end = float(t) + pad_after
    return {
        "media_in": round(start, 3),
        "media_out": round(end, 3),
        "time_status": status,
        "precise_claim": False,
    }


def _seg(
    *,
    segment_id: str,
    beat: str,
    role: str,
    event_ids: Sequence[str],
    frame_ids: Sequence[str],
    evidence_refs: Sequence[Dict[str, Any]],
    media_in: Any,
    media_out: Any,
    time_status: str,
    shot_kind: str,
    is_replay: bool,
    narration: str,
    verification_status: str = "draft",
) -> Dict[str, Any]:
    return {
        "segment_id": segment_id,
        "beat": beat,
        "role": role,
        "event_ids": list(event_ids),
        "frame_ids": list(frame_ids),
        "evidence_refs": list(evidence_refs),
        "media_in": media_in,
        "media_out": media_out,
        "time_status": time_status,
        "shot_kind": shot_kind,
        "is_replay": bool(is_replay),
        "verification_status": verification_status,
        "narration": narration,
        "precise_claim": False,
    }


def _visual_index(
    visual_evidence: Sequence[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for ev in visual_evidence:
        if not isinstance(ev, dict):
            continue
        classified = classify_visual_evidence(ev)
        gid = str(ev.get("gap_id") or classified.get("gap_id") or "")
        if gid:
            out[gid] = {**ev, "_classified": classified}
    return out


def compose_story_plan(
    story: Dict[str, Any],
    *,
    visual_evidence: Optional[Sequence[Dict[str, Any]]] = None,
    causal: Optional[Dict[str, Any]] = None,
    use_llm: bool = False,
    api: Optional[ApiProvider] = None,
) -> Dict[str, Any]:
    """规则基线编排；可选 LLM 仅润色 narration（须再校验）。"""
    visual_evidence = list(visual_evidence or [])
    verification = verify_story(story, visual_evidence=visual_evidence, causal=causal)
    tier = str(
        story.get("story_tier")
        or (story.get("recognition") or {}).get("tier")
        or "none"
    )
    match_id = str(story.get("match_id") or "")
    plan = empty_plan(match_id=match_id, story_tier=tier)
    teams = _team_names(story, causal)
    side = story.get("protagonist_side") or (story.get("recognition") or {}).get(
        "protagonist_side"
    )
    plan["protagonist"] = {
        "side": side,
        "team_name": teams.get(str(side) or "", "") if side else "",
        "teams": teams,
    }
    plan["diagnostics"] = {
        "verification": verification,
        "composer": ALGORITHM_ID,
        "llm_used": False,
        "mock_not_factual": True,
    }

    if tier == "none":
        plan["verification_status"] = "blocked_none"
        plan["narration"]["summary"] = (
            f"T01 判定为 none（{story.get('no_story_reason') or (story.get('recognition') or {}).get('reason') or 'no_comeback'}）；"
            "不生成翻盘故事编排。"
        )
        plan["missing_evidence"] = ["no_comeback_story"]
        plan["edl"] = []
        ok, problems = validate_compose_plan(plan)
        plan["diagnostics"]["structure_ok"] = ok
        plan["diagnostics"]["structure_problems"] = problems
        return plan

    events = _events_by_id(story)
    vis = _visual_index(visual_evidence)
    milestones = _find_score_milestones(story, str(side or "left"))
    missing: List[str] = []
    segments: List[Dict[str, Any]] = []
    evidence_refs_global: List[Dict[str, Any]] = []
    all_event_ids: List[str] = []

    def add_ref(ref: Dict[str, Any]) -> Dict[str, Any]:
        evidence_refs_global.append(ref)
        return ref

    # ---- 铺垫：落后局面（score behind）；live 优先，回放仅补充 ----
    behind = milestones["behind"]
    if behind:
        carrier = str(behind.get("carrier_event_id") or "")
        ev = events.get(carrier)
        is_replay = bool(ev.get("is_replay")) if ev else False
        win = _window_from_t(float(behind["t_sec"]), status="score_path_only")
        refs = [
            add_ref(
                {
                    "kind": "rule_fact",
                    "used_as_fact": True,
                    "source": "score_path",
                    "score": behind.get("score"),
                    "t_sec": behind.get("t_sec"),
                }
            )
        ]
        shot = "replay_supplement" if is_replay else "live"
        if is_replay:
            # 主片段仍用 score_path 时间作为 live 叙事锚，事件回放另标
            shot = "live"
            is_replay = False
        seg = _seg(
            segment_id="seg_setup_deficit",
            beat="铺垫",
            role="deficit_context",
            event_ids=[carrier] if carrier else [],
            frame_ids=[],
            evidence_refs=refs,
            media_in=win["media_in"],
            media_out=win["media_out"],
            time_status=win["time_status"],
            shot_kind=shot,
            is_replay=False,
            narration=f"主角落后比分 {behind.get('score')}（score_path 规则事实）。",
        )
        segments.append(seg)
        if carrier:
            all_event_ids.append(carrier)
        # 若存在回放事件作补充
        if ev and ev.get("is_replay"):
            tw = _window_from_t(
                float(ev["t_ms"]) / 1000.0 if ev.get("t_ms") is not None else None,
                status="event_ms",
            )
            segments.append(
                _seg(
                    segment_id="seg_setup_replay_supp",
                    beat="铺垫",
                    role="deficit_replay_supplement",
                    event_ids=[carrier],
                    frame_ids=[],
                    evidence_refs=[
                        add_ref(
                            {
                                "kind": "rule_fact",
                                "used_as_fact": True,
                                "source": "event_replay_flag",
                                "event_id": carrier,
                            }
                        )
                    ],
                    media_in=tw["media_in"],
                    media_out=tw["media_out"],
                    time_status=tw["time_status"],
                    shot_kind="replay_supplement",
                    is_replay=True,
                    narration="叙事补充回放（非真实比赛主时序）。",
                )
            )
    else:
        missing.append("missing_setup_deficit_score_node")

    # 视觉 setup（mock 不得当事实）
    setup_vis = vis.get("missing_setup_visual")
    if setup_vis:
        cl = setup_vis["_classified"]
        ref = add_ref(
            {
                "kind": cl["kind"],
                "used_as_fact": False,
                "gap_id": "missing_setup_visual",
                "frame_ids": cl.get("frame_ids") or [],
                "provider_mode": cl.get("provider_mode"),
            }
        )
        if cl["kind"] == "mock":
            missing.append("setup_visual_mock_only_not_factual")
        elif cl["kind"] == "vlm_observation" and cl.get("normalized_ok"):
            # 挂到铺垫段 frame_ids，但不升格为 verified
            for seg in segments:
                if seg["segment_id"] == "seg_setup_deficit":
                    seg["frame_ids"] = list(cl.get("frame_ids") or [])
                    seg["evidence_refs"].append(ref)
                    seg["narration"] += " 附 VLM 观察（非已核实事实）。"
                    break
        else:
            missing.append("setup_visual_unresolved")

    # ---- 蓄力：live 非回放；且须落在扳平之前（避免打乱主时序）----
    buildup_ids = list(
        ((story.get("recognition") or {}).get("beats") or {}).get("蓄力") or []
    )
    if not buildup_ids:
        buildup_ids = [
            eid
            for eid, e in events.items()
            if e.get("story_role") == "蓄力" and not e.get("is_replay")
        ]
    eq_t_limit = None
    if milestones["equalizer"] is not None:
        eq_t_limit = float(milestones["equalizer"].get("t_sec") or 0)
    behind_t = (
        float(milestones["behind"].get("t_sec") or 0)
        if milestones["behind"] is not None
        else None
    )
    live_buildup = 0
    for eid in buildup_ids:
        ev = events.get(str(eid))
        if ev is None:
            missing.append(f"buildup_event_missing:{eid}")
            segments.append(
                _seg(
                    segment_id=f"seg_buildup_missing_{eid}",
                    beat="蓄力",
                    role="buildup_pending",
                    event_ids=[str(eid)],
                    frame_ids=[],
                    evidence_refs=[],
                    media_in=None,
                    media_out=None,
                    time_status="pending_localization",
                    shot_kind="unknown",
                    is_replay=False,
                    narration=f"蓄力事件 {eid} 缺失，待定位。",
                )
            )
            continue
        if ev.get("is_replay"):
            # 回放不进入蓄力主线
            continue
        t = float(ev["t_ms"]) / 1000.0 if ev.get("t_ms") is not None else None
        if t is not None and eq_t_limit is not None and t >= eq_t_limit - 1e-6:
            # 扳平后的“蓄力”标注不纳入蓄力主线，避免时序回退
            continue
        if t is not None and behind_t is not None and t + 1e-6 < behind_t:
            # 落后确认前的动作更偏铺垫上下文，跳过以免无关硬塞
            continue
        win = _window_from_t(t, status="event_ms" if t is not None else "pending_localization")
        segments.append(
            _seg(
                segment_id=f"seg_buildup_{eid}",
                beat="蓄力",
                role="buildup_action",
                event_ids=[str(eid)],
                frame_ids=[],
                evidence_refs=[
                    add_ref(
                        {
                            "kind": "rule_fact",
                            "used_as_fact": True,
                            "source": "event",
                            "event_id": eid,
                            "type": ev.get("type"),
                        }
                    )
                ],
                media_in=win["media_in"],
                media_out=win["media_out"],
                time_status=win["time_status"],
                shot_kind="live",
                is_replay=False,
                narration=f"蓄力动作 {ev.get('type')}（live）。",
            )
        )
        all_event_ids.append(str(eid))
        live_buildup += 1
    if live_buildup == 0:
        missing.append("missing_live_buildup")

    # ---- 转折：扳平 ----
    eq = milestones["equalizer"]
    if eq:
        carrier = str(eq.get("carrier_event_id") or "")
        ev = events.get(carrier)
        win = _window_from_t(float(eq["t_sec"]), status="score_path_only")
        frame_ids: List[str] = []
        refs = [
            add_ref(
                {
                    "kind": "rule_fact",
                    "used_as_fact": True,
                    "source": "score_path_equalizer",
                    "score": eq.get("score"),
                    "t_sec": eq.get("t_sec"),
                }
            )
        ]
        for gid in (
            "verify_equalizer_goal_action",
            "verify_equalizer_scoreboard",
            "locate_equalizer_goal_action",
        ):
            if gid in vis:
                cl = vis[gid]["_classified"]
                refs.append(
                    add_ref(
                        {
                            "kind": cl["kind"],
                            "used_as_fact": False,
                            "gap_id": gid,
                            "frame_ids": cl.get("frame_ids") or [],
                            "provider_mode": cl.get("provider_mode"),
                        }
                    )
                )
                if cl["kind"] == "mock":
                    missing.append(f"{gid}_mock_only")
                elif cl.get("normalized_ok") and cl["kind"] == "vlm_observation":
                    frame_ids.extend(cl.get("frame_ids") or [])
        # 进球动作事件若缺失 → pending_review
        time_status = win["time_status"]
        if carrier and carrier not in events:
            missing.append(f"equalizer_goal_event_missing:{carrier}")
            time_status = "pending_review"
        segments.append(
            _seg(
                segment_id="seg_equalizer",
                beat="转折",
                role="equalizer",
                event_ids=[carrier] if carrier else [],
                frame_ids=frame_ids,
                evidence_refs=refs,
                media_in=win["media_in"],
                media_out=win["media_out"],
                time_status=time_status,
                shot_kind="live",
                is_replay=False,
                narration=f"扳平至 {eq.get('score')}（score_path）。",
            )
        )
        if carrier:
            all_event_ids.append(carrier)
        if ev and ev.get("is_replay"):
            tw = _window_from_t(
                float(ev["t_ms"]) / 1000.0 if ev.get("t_ms") is not None else None,
                status="event_ms",
            )
            segments.append(
                _seg(
                    segment_id="seg_equalizer_replay_supp",
                    beat="转折",
                    role="equalizer_replay_supplement",
                    event_ids=[carrier],
                    frame_ids=[],
                    evidence_refs=[
                        add_ref(
                            {
                                "kind": "rule_fact",
                                "used_as_fact": True,
                                "source": "event_replay_flag",
                                "event_id": carrier,
                            }
                        )
                    ],
                    media_in=tw["media_in"],
                    media_out=tw["media_out"],
                    time_status=tw["time_status"],
                    shot_kind="replay_supplement",
                    is_replay=True,
                    narration="扳平相关回放补充镜头（非主时序）。",
                )
            )
    else:
        missing.append("missing_equalizer_score_node")

    # ---- 高潮：反超 + 后续 ----
    ga = milestones["go_ahead"]
    if ga:
        carrier = str(ga.get("carrier_event_id") or "")
        win = _window_from_t(float(ga["t_sec"]), status="score_path_only")
        frame_ids = []
        refs = [
            add_ref(
                {
                    "kind": "rule_fact",
                    "used_as_fact": True,
                    "source": "score_path_go_ahead",
                    "score": ga.get("score"),
                    "t_sec": ga.get("t_sec"),
                }
            )
        ]
        for gid in (
            "verify_go_ahead_goal_action",
            "verify_go_ahead_scoreboard",
            "locate_go_ahead_goal_action",
        ):
            if gid in vis:
                cl = vis[gid]["_classified"]
                refs.append(
                    add_ref(
                        {
                            "kind": cl["kind"],
                            "used_as_fact": False,
                            "gap_id": gid,
                            "frame_ids": cl.get("frame_ids") or [],
                            "provider_mode": cl.get("provider_mode"),
                        }
                    )
                )
                if cl["kind"] == "mock":
                    missing.append(f"{gid}_mock_only")
                elif cl.get("normalized_ok") and cl["kind"] == "vlm_observation":
                    frame_ids.extend(cl.get("frame_ids") or [])
        if carrier and carrier not in events:
            missing.append(f"go_ahead_goal_event_missing:{carrier}")
        segments.append(
            _seg(
                segment_id="seg_go_ahead",
                beat="高潮",
                role="go_ahead",
                event_ids=[carrier] if carrier else [],
                frame_ids=frame_ids,
                evidence_refs=refs,
                media_in=win["media_in"],
                media_out=win["media_out"],
                time_status=win["time_status"]
                if carrier in events or not carrier
                else "pending_review",
                shot_kind="live",
                is_replay=False,
                narration=f"反超至 {ga.get('score')}（score_path）。",
            )
        )
        if carrier:
            all_event_ids.append(carrier)
    else:
        missing.append("missing_go_ahead_score_node")

    # 额外高潮 live 射门/进球（recognition），过滤回放与无关
    for eid in ((story.get("recognition") or {}).get("beats") or {}).get("高潮") or []:
        if str(eid) in all_event_ids:
            continue
        ev = events.get(str(eid))
        if ev is None:
            missing.append(f"climax_event_missing:{eid}")
            continue
        if ev.get("is_replay"):
            tw = _window_from_t(
                float(ev["t_ms"]) / 1000.0 if ev.get("t_ms") is not None else None,
                status="event_ms",
            )
            segments.append(
                _seg(
                    segment_id=f"seg_climax_replay_{eid}",
                    beat="高潮",
                    role="climax_replay_supplement",
                    event_ids=[str(eid)],
                    frame_ids=[],
                    evidence_refs=[
                        add_ref(
                            {
                                "kind": "rule_fact",
                                "used_as_fact": True,
                                "source": "event_replay_flag",
                                "event_id": eid,
                            }
                        )
                    ],
                    media_in=tw["media_in"],
                    media_out=tw["media_out"],
                    time_status=tw["time_status"],
                    shot_kind="replay_supplement",
                    is_replay=True,
                    narration="高潮回放补充。",
                )
            )
            continue
        # 避免无关：仅保留进球/射门类
        if ev.get("type") not in ("进球", "射门", "头球破门", "乌龙球", "Goal", "Shot"):
            continue
        t = float(ev["t_ms"]) / 1000.0 if ev.get("t_ms") is not None else None
        win = _window_from_t(t, status="event_ms" if t is not None else "pending_localization")
        segments.append(
            _seg(
                segment_id=f"seg_climax_{eid}",
                beat="高潮",
                role="climax_action",
                event_ids=[str(eid)],
                frame_ids=[],
                evidence_refs=[
                    add_ref(
                        {
                            "kind": "rule_fact",
                            "used_as_fact": True,
                            "source": "event",
                            "event_id": eid,
                        }
                    )
                ],
                media_in=win["media_in"],
                media_out=win["media_out"],
                time_status=win["time_status"],
                shot_kind="live",
                is_replay=False,
                narration=f"高潮动作 {ev.get('type')}。",
            )
        )
        all_event_ids.append(str(eid))

    # ---- 收尾：比赛结束或反应 ----
    ending = [
        e
        for e in events.values()
        if e.get("story_role") == "收尾" or e.get("type") in ("比赛结束", "全场结束")
    ]
    reaction = vis.get("post_climax_reaction")
    if ending:
        ev = ending[0]
        eid = str(ev["event_id"])
        t = float(ev["t_ms"]) / 1000.0 if ev.get("t_ms") is not None else None
        win = _window_from_t(t, status="event_ms" if t is not None else "pending_localization")
        frames = []
        refs = [
            add_ref(
                {
                    "kind": "rule_fact",
                    "used_as_fact": True,
                    "source": "event",
                    "event_id": eid,
                }
            )
        ]
        if reaction:
            cl = reaction["_classified"]
            refs.append(
                add_ref(
                    {
                        "kind": cl["kind"],
                        "used_as_fact": False,
                        "gap_id": "post_climax_reaction",
                        "frame_ids": cl.get("frame_ids") or [],
                    }
                )
            )
            if cl["kind"] == "mock":
                missing.append("post_climax_reaction_mock_only")
            elif cl.get("normalized_ok") and cl["kind"] == "vlm_observation":
                frames = list(cl.get("frame_ids") or [])
        segments.append(
            _seg(
                segment_id="seg_ending",
                beat="收尾",
                role="ending",
                event_ids=[eid],
                frame_ids=frames,
                evidence_refs=refs,
                media_in=win["media_in"],
                media_out=win["media_out"],
                time_status=win["time_status"],
                shot_kind="replay_supplement" if ev.get("is_replay") else "live",
                is_replay=bool(ev.get("is_replay")),
                narration="收尾/终场。",
            )
        )
        all_event_ids.append(eid)
    else:
        missing.append("missing_ending_event")
        segments.append(
            _seg(
                segment_id="seg_ending_pending",
                beat="收尾",
                role="ending_pending",
                event_ids=[],
                frame_ids=[],
                evidence_refs=[],
                media_in=None,
                media_out=None,
                time_status="pending_localization",
                shot_kind="unknown",
                is_replay=False,
                narration="收尾镜头待定位。",
            )
        )

    # 排序：live 主线按 media_in；replay_supplement 跟在同 beat 后
    def sort_key(s: Dict[str, Any]) -> Tuple:
        beat_i = BEATS.index(s["beat"]) if s["beat"] in BEATS else 99
        is_rep = 1 if s.get("shot_kind") == "replay_supplement" else 0
        t = s.get("media_in")
        t_key = float(t) if t is not None else 1e18
        return (beat_i, is_rep, t_key, s.get("segment_id") or "")

    segments.sort(key=sort_key)

    # narration 规则基线
    proto = plan["protagonist"].get("team_name") or f"side={side}"
    by_beat = {b: "" for b in BEATS}
    for b in BEATS:
        parts = [s["narration"] for s in segments if s["beat"] == b and s.get("narration")]
        by_beat[b] = " ".join(parts)
    summary = {
        "story": f"{proto} 逆风翻盘候选剪辑方案（规则基线）：落后→蓄力→扳平→反超→收尾。",
        "candidate": f"{proto} 翻盘候选不完整方案；缺口见 missing_evidence。",
    }[tier if tier in ("story", "candidate") else "candidate"]

    plan["segments"] = segments
    plan["evidence_refs"] = evidence_refs_global
    plan["event_ids"] = sorted(set(all_event_ids))
    plan["missing_evidence"] = missing
    plan["narration"] = {"summary": summary, "by_beat": by_beat}
    plan["edl"] = segments_to_edl(segments)

    hard_conflict_types = {
        "score_path_time_regression",
        "score_path_illegal_transition",
        "story_tier_without_comeback_arc",
        "mock_used_as_fact",
        "delta_side_mismatch",
    }
    hard = [
        c
        for c in (verification.get("conflicts") or [])
        if c.get("type") in hard_conflict_types
    ]
    if hard:
        plan["verification_status"] = "conflicts_present"
    elif tier == "candidate" or missing or verification.get("conflicts"):
        # recognition 缺事件/回放主证据等记入 partial，不阻断候选方案
        plan["verification_status"] = "partial"
    else:
        plan["verification_status"] = "structure_ok"

    if use_llm and api is not None:
        plan = _enrich_narration_llm(plan, api=api)
        plan["diagnostics"]["llm_used"] = True

    ok, problems = validate_compose_plan(plan)
    plan["diagnostics"]["structure_ok"] = ok
    plan["diagnostics"]["structure_problems"] = problems
    if not ok and plan["verification_status"] == "structure_ok":
        plan["verification_status"] = "draft"
    return plan


def _enrich_narration_llm(plan: Dict[str, Any], *, api: ApiProvider) -> Dict[str, Any]:
    """LLM 仅生成 narration / 衔接建议；必须通过校验，失败则保留规则文本。"""
    system = (
        "You narrate a football comeback edit plan. "
        "Return JSON {summary:str, by_beat:{铺垫,蓄力,转折,高潮,收尾}, "
        "segment_notes:{segment_id:str}}. "
        "Do not invent timestamps or event ids. Do not claim mock evidence is verified."
    )
    user = {
        "match_id": plan.get("match_id"),
        "tier": plan.get("story_tier"),
        "segments": [
            {
                "segment_id": s.get("segment_id"),
                "beat": s.get("beat"),
                "role": s.get("role"),
                "shot_kind": s.get("shot_kind"),
                "event_ids": s.get("event_ids"),
                "time_status": s.get("time_status"),
                "rule_narration": s.get("narration"),
            }
            for s in plan.get("segments") or []
        ],
        "missing_evidence": plan.get("missing_evidence"),
    }
    fallback = {
        "summary": (plan.get("narration") or {}).get("summary"),
        "by_beat": (plan.get("narration") or {}).get("by_beat"),
        "segment_notes": {},
    }
    try:
        raw = api.chat(
            role="planner",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
            ],
            mock_content=json.dumps(fallback, ensure_ascii=False),
            allow_degraded_fallback=True,
        )
        if raw.get("provider_mode") in ("degraded", "mock") and api.require_real:
            return plan
        content = str(raw.get("content") or "")
        try:
            obj = json.loads(content)
        except json.JSONDecodeError:
            m = _JSON_OBJ.search(content)
            obj = json.loads(m.group(0)) if m else None
        if not isinstance(obj, dict):
            return plan
        narr = dict(plan.get("narration") or {})
        if isinstance(obj.get("summary"), str) and obj["summary"].strip():
            narr["summary"] = obj["summary"].strip()
        by = dict(narr.get("by_beat") or {})
        for beat, text in (obj.get("by_beat") or {}).items():
            if beat in BEATS and isinstance(text, str) and text.strip():
                by[beat] = text.strip()
        narr["by_beat"] = by
        notes = obj.get("segment_notes") or {}
        if isinstance(notes, dict):
            for seg in plan.get("segments") or []:
                sid = seg.get("segment_id")
                if sid in notes and isinstance(notes[sid], str) and notes[sid].strip():
                    seg["narration"] = notes[sid].strip()
        plan["narration"] = narr
        # 衔接建议不写入伪时间
        plan["diagnostics"]["llm_provider_mode"] = raw.get("provider_mode")
    except Exception as exc:  # noqa: BLE001
        plan["diagnostics"]["llm_error"] = str(exc)[:200]
    return plan


def compose_from_paths(
    story_path: str,
    *,
    causal_path: Optional[str] = None,
    visual_evidence: Optional[Sequence[Dict[str, Any]]] = None,
    visual_evidence_path: Optional[str] = None,
    use_llm: bool = False,
    api: Optional[ApiProvider] = None,
    out_json: Optional[str] = None,
    out_report: Optional[str] = None,
) -> Dict[str, Any]:
    story = json.loads(Path(story_path).read_text(encoding="utf-8"))
    causal = None
    if causal_path and Path(causal_path).is_file():
        causal = json.loads(Path(causal_path).read_text(encoding="utf-8"))
    vis = list(visual_evidence or [])
    if visual_evidence_path and Path(visual_evidence_path).is_file():
        loaded = json.loads(Path(visual_evidence_path).read_text(encoding="utf-8"))
        if isinstance(loaded, list):
            vis.extend(loaded)
        elif isinstance(loaded, dict) and isinstance(loaded.get("visual_evidence"), list):
            vis.extend(loaded["visual_evidence"])
    plan = compose_story_plan(
        story,
        visual_evidence=vis,
        causal=causal,
        use_llm=use_llm,
        api=api,
    )
    if out_json:
        Path(out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(out_json).write_text(
            json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if out_report:
        Path(out_report).parent.mkdir(parents=True, exist_ok=True)
        Path(out_report).write_text(render_narrative_report(plan), encoding="utf-8")
    return plan
