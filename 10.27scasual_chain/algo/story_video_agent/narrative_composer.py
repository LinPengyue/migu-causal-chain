"""Phase 3A.1：Narrative Composer — 事件溯源安全的可剪辑故事线。

- score_path 只作比分确认锚点，不是进球动作时间
- carrier_event_id 须经 link_score_carrier 校验
- candidate_edl vs render_ready_edl；关键进球门禁
- 回放仅作补充且须 linked_live_event_id
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from story_video_agent.api_provider import ApiProvider
from story_video_agent.event_mapping import (
    find_live_goal_candidates,
    find_replay_supplements,
    index_story_events,
    link_score_carrier,
    provenance_ref,
)
from story_video_agent.state import _comeback_score_steps
from story_video_agent.story_output_schema import (
    ALGORITHM_ID,
    BEATS,
    SCHEMA_VERSION,
    build_candidate_edl,
    build_render_ready_edl,
    empty_plan,
    render_narrative_report,
    validate_compose_plan,
    validate_render_ready,
)
from story_video_agent.story_verifier import (
    check_narration_grounding,
    classify_visual_evidence,
    verify_story,
)

_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)

PAD_BEFORE = 4.0
PAD_AFTER = 8.0


def _find_score_milestones(
    story: Dict[str, Any], side: str
) -> Dict[str, Optional[Dict[str, Any]]]:
    """与 Phase 2A `_comeback_score_steps` 对齐：最后一次落后弧上的扳平/反超。"""
    steps = _comeback_score_steps(story)
    # 兼容旧键名
    return {
        "behind": steps.get("behind_start"),
        "behind_start": steps.get("behind_start"),
        "equalizer": steps.get("equalizer"),
        "go_ahead": steps.get("go_ahead"),
    }


def _team_names(story: Dict[str, Any], causal: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if causal:
        return {
            "left": str(causal.get("team_1_name") or ""),
            "right": str(causal.get("team_2_name") or ""),
        }
    name = str(story.get("match_id") or story.get("video_name") or "")
    for sep in ("vs", "VS", "对"):
        if sep in name:
            left, right = name.split(sep, 1)
            return {"left": left.strip(), "right": right.replace(".mp4", "").strip()}
    return {"left": "", "right": ""}


def _window_from_t(
    t: Optional[float],
    *,
    status: str,
    pad_before: float = PAD_BEFORE,
    pad_after: float = PAD_AFTER,
) -> Dict[str, Any]:
    if t is None:
        return {
            "media_in": None,
            "media_out": None,
            "time_status": "pending_localization",
            "precise_claim": False,
        }
    return {
        "media_in": round(max(0.0, float(t) - pad_before), 3),
        "media_out": round(float(t) + pad_after, 3),
        "time_status": status,
        "precise_claim": False,
    }


def _mk_seg(
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
    selection_reason: str,
    source_refs: Sequence[Dict[str, Any]],
    confidence: float,
    time_provenance: Dict[str, Any],
    render_eligibility: str,
    blocking_reasons: Sequence[str],
    linked_live_event_id: Optional[str] = None,
    narrative_order: Optional[int] = None,
    source_media_order: Optional[float] = None,
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
        "linked_live_event_id": linked_live_event_id,
        "narration": narration,
        "precise_claim": False,
        "selection_reason": selection_reason,
        "source_refs": list(source_refs),
        "confidence": float(confidence),
        "time_provenance": dict(time_provenance),
        "render_eligibility": render_eligibility,
        "blocking_reasons": list(blocking_reasons),
        "narrative_order": narrative_order,
        "source_media_order": source_media_order
        if source_media_order is not None
        else (float(media_in) if media_in is not None else None),
        "verification_status": "draft",
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


def _attach_visual(
    vis: Dict[str, Dict[str, Any]],
    gap_ids: Sequence[str],
    *,
    add_ref,
    missing: List[str],
) -> Tuple[List[str], List[Dict[str, Any]], bool]:
    """返回 frame_ids, refs, has_pipeline_verified_vlm。"""
    frames: List[str] = []
    refs: List[Dict[str, Any]] = []
    pipeline_ok = False
    for gid in gap_ids:
        if gid not in vis:
            continue
        cl = vis[gid]["_classified"]
        ref = add_ref(
            {
                "kind": cl["kind"],
                "used_as_fact": bool(cl.get("used_as_fact")),
                "pipeline_verified": bool(cl.get("pipeline_verified")),
                "gap_id": gid,
                "frame_ids": cl.get("frame_ids") or [],
                "provider_mode": cl.get("provider_mode"),
            }
        )
        refs.append(ref)
        if cl["kind"] == "mock":
            missing.append(f"{gid}_mock_only")
        elif cl["kind"] == "verified" and cl.get("pipeline_verified"):
            frames.extend(cl.get("frame_ids") or [])
            pipeline_ok = True
        elif cl["kind"] == "vlm_observation" and cl.get("normalized_ok"):
            frames.extend(cl.get("frame_ids") or [])
            # 观察 ≠ 可成片核实
        else:
            missing.append(f"{gid}_unresolved")
    return frames, refs, pipeline_ok


def compose_story_plan(
    story: Dict[str, Any],
    *,
    visual_evidence: Optional[Sequence[Dict[str, Any]]] = None,
    causal: Optional[Dict[str, Any]] = None,
    use_llm: bool = False,
    api: Optional[ApiProvider] = None,
) -> Dict[str, Any]:
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
        "schema": SCHEMA_VERSION,
        "llm_used": False,
        "mock_not_factual": True,
        "milestones_source": "state._comeback_score_steps",
    }

    if tier == "none":
        plan["verification_status"] = "blocked_none"
        plan["blocking_reasons"] = ["tier_none_no_comeback"]
        plan["narration"]["summary"] = (
            f"T01 判定为 none（{story.get('no_story_reason') or (story.get('recognition') or {}).get('reason') or 'no_comeback'}）；"
            "不生成翻盘故事编排。"
        )
        plan["missing_evidence"] = ["no_comeback_story"]
        plan["structure_ok"] = True
        plan["render_ready"] = False
        ok, problems = validate_compose_plan(plan)
        plan["diagnostics"]["structure_ok"] = ok
        plan["diagnostics"]["structure_problems"] = problems
        return plan

    events = index_story_events(story)
    vis = _visual_index(visual_evidence)
    milestones = _find_score_milestones(story, str(side or "left"))
    missing: List[str] = []
    blocking: List[str] = []
    mappings: List[Dict[str, Any]] = []
    segments: List[Dict[str, Any]] = []
    evidence_refs_global: List[Dict[str, Any]] = []
    all_event_ids: List[str] = []

    def add_ref(ref: Dict[str, Any]) -> Dict[str, Any]:
        evidence_refs_global.append(ref)
        return ref

    # ---------- 铺垫：落后比分确认（scoreboard anchor，非进球）----------
    behind = milestones.get("behind") or milestones.get("behind_start")
    if behind:
        carrier = str(behind.get("carrier_event_id") or "")
        link = link_score_carrier(
            carrier_event_id=carrier,
            score_node=behind,
            events=events,
            require_live=False,
        )
        mappings.append({"context": "behind_score", **link})
        win = _window_from_t(float(behind["t_sec"]), status="score_path_only")
        refs = [
            add_ref(
                {
                    "kind": "rule_fact",
                    "used_as_fact": True,
                    "source": "score_path",
                    "score": behind.get("score"),
                    "t_sec": behind.get("t_sec"),
                    "note": "scoreboard_anchor_not_goal_action",
                }
            )
        ]
        src_refs = [
            provenance_ref(
                namespace="score_path_carrier",
                ref_id=carrier or f"score@{behind.get('t_sec')}",
                extra={"link_status": link["status"]},
            )
        ]
        # 禁止把错误关联的回放写进 event_ids
        event_ids: List[str] = []
        block = ["score_path_only_not_render_ready", "setup_is_scoreboard_anchor_not_goal"]
        if link["status"] == "linked" and link.get("linked_event_id"):
            event_ids = [link["linked_event_id"]]
            all_event_ids.append(link["linked_event_id"])
            refs.append(
                add_ref(
                    {
                        "kind": "rule_fact",
                        "used_as_fact": True,
                        "source": "validated_carrier_link",
                        "event_id": link["linked_event_id"],
                    }
                )
            )
        else:
            missing.append(f"behind_carrier_unresolved:{carrier or 'empty'}")
            if link.get("reasons"):
                block.append("unresolved_mapping:" + ",".join(link["reasons"][:3]))
            refs.append(
                add_ref(
                    {
                        "kind": "unresolved_mapping",
                        "used_as_fact": False,
                        "carrier_event_id": carrier,
                        "reasons": link.get("reasons"),
                    }
                )
            )
        # 绝不自动挂未校验回放补充到铺垫
        segments.append(
            _mk_seg(
                segment_id="seg_setup_deficit",
                beat="铺垫",
                role="deficit_scoreboard_anchor",
                event_ids=event_ids,
                frame_ids=[],
                evidence_refs=refs,
                media_in=win["media_in"],
                media_out=win["media_out"],
                time_status="score_path_only",
                shot_kind="scoreboard_anchor",
                is_replay=False,
                narration=f"比分确认落后 {behind.get('score')} @ {behind.get('t_sec')}s（非进球动作时间）。",
                selection_reason="last_comeback_arc_behind_start_score_path",
                source_refs=src_refs,
                confidence=0.9,
                time_provenance={
                    "source": "score_path",
                    "t_sec": behind.get("t_sec"),
                    "pipeline_verified": False,
                },
                render_eligibility="candidate_only",
                blocking_reasons=block,
            )
        )
    else:
        missing.append("missing_setup_deficit_score_node")
        blocking.append("missing_behind_score_node")

    setup_frames, setup_refs, _ = _attach_visual(
        vis, ["missing_setup_visual"], add_ref=add_ref, missing=missing
    )
    if setup_frames and segments and segments[0]["segment_id"] == "seg_setup_deficit":
        segments[0]["frame_ids"] = setup_frames
        segments[0]["evidence_refs"].extend(setup_refs)
        segments[0]["narration"] += " 附视觉观察（非已核实事实，除非 pipeline_verified）。"

    # ---------- 蓄力：live，落在 behind→equalizer 之间 ----------
    eq_node = milestones.get("equalizer")
    eq_t = float(eq_node["t_sec"]) if eq_node else None
    behind_t = float(behind["t_sec"]) if behind else None
    buildup_ids = list(
        ((story.get("recognition") or {}).get("beats") or {}).get("蓄力") or []
    )
    if not buildup_ids:
        buildup_ids = [
            eid
            for eid, e in events.items()
            if e.get("story_role") == "蓄力" and not e.get("is_replay")
        ]
    live_buildup = 0
    for eid in buildup_ids:
        ev = events.get(str(eid))
        if ev is None:
            missing.append(f"buildup_event_missing:{eid}")
            continue
        if ev.get("is_replay") or ev.get("_id_collision"):
            continue
        t = None
        if ev.get("t_ms") is not None:
            t = float(ev["t_ms"]) / 1000.0
        if t is not None and eq_t is not None and t >= eq_t - 1e-6:
            continue
        if t is not None and behind_t is not None and t + 1e-6 < behind_t:
            continue
        win = _window_from_t(t, status="event_ms" if t is not None else "pending_localization")
        segments.append(
            _mk_seg(
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
                narration=f"蓄力动作 {ev.get('type')}（live，event_ms 未校准成片）。",
                selection_reason="live_buildup_between_behind_and_equalizer",
                source_refs=[
                    provenance_ref(namespace=str(ev.get("_namespace") or "t01_story_event"), ref_id=str(eid))
                ],
                confidence=0.55,
                time_provenance={
                    "source": "event_ms",
                    "t_sec": t,
                    "pipeline_verified": False,
                },
                render_eligibility="candidate_only",
                blocking_reasons=["unverified_event_ms"],
            )
        )
        all_event_ids.append(str(eid))
        live_buildup += 1
    if live_buildup == 0:
        missing.append("missing_live_buildup")

    # ---------- 转折 / 高潮：比分锚点 + 进球动作候选 ----------
    def add_goal_beat(
        *,
        beat: str,
        role_prefix: str,
        score_node: Optional[Dict[str, Any]],
        role_hint: str,
        vis_gaps: Sequence[str],
    ) -> Optional[str]:
        """返回 linked live goal event_id（若有）。"""
        if not score_node:
            missing.append(f"missing_{role_prefix}_score_node")
            blocking.append(f"missing_{role_prefix}_score_node")
            return None
        score_t = float(score_node["t_sec"])
        carrier = str(score_node.get("carrier_event_id") or "")
        link = link_score_carrier(
            carrier_event_id=carrier,
            score_node=score_node,
            events=events,
            require_live=True,
        )
        mappings.append({"context": f"{role_prefix}_score", **link})
        # 比分确认锚点（不可成片）
        win_sb = _window_from_t(score_t, status="score_path_only")
        sb_refs = [
            add_ref(
                {
                    "kind": "rule_fact",
                    "used_as_fact": True,
                    "source": "score_path",
                    "score": score_node.get("score"),
                    "t_sec": score_t,
                    "note": "scoreboard_confirm_only",
                }
            )
        ]
        if link["status"] != "linked":
            sb_refs.append(
                add_ref(
                    {
                        "kind": "unresolved_mapping",
                        "used_as_fact": False,
                        "carrier_event_id": carrier,
                        "reasons": link.get("reasons"),
                    }
                )
            )
            missing.append(f"{role_prefix}_carrier_unresolved:{carrier or 'empty'}")
        segments.append(
            _mk_seg(
                segment_id=f"seg_{role_prefix}_scoreboard",
                beat=beat,
                role=f"{role_prefix}_scoreboard_anchor",
                event_ids=[link["linked_event_id"]]
                if link.get("linked_event_id")
                else [],
                frame_ids=[],
                evidence_refs=sb_refs,
                media_in=win_sb["media_in"],
                media_out=win_sb["media_out"],
                time_status="score_path_only",
                shot_kind="scoreboard_anchor",
                is_replay=False,
                narration=f"{role_prefix} 比分确认 {score_node.get('score')} @ {score_t}s（非进球剪辑点）。",
                selection_reason="score_path_board_anchor",
                source_refs=[
                    provenance_ref(
                        namespace="score_path_carrier",
                        ref_id=carrier or f"score@{score_t}",
                        extra={"link_status": link["status"]},
                    )
                ],
                confidence=0.85,
                time_provenance={
                    "source": "score_path",
                    "t_sec": score_t,
                    "pipeline_verified": False,
                },
                render_eligibility="candidate_only",
                blocking_reasons=["score_path_only_not_render_ready"],
            )
        )

        # 进球动作：优先 live 候选，而非 carrier 字符串
        cands = find_live_goal_candidates(
            events, score_t=score_t, role_hint=role_hint
        )
        live_id = None
        if cands:
            best = cands[0]
            live_id = best["event_id"]
            win_g = _window_from_t(best["t_sec"], status="linked_event_ms")
            v_frames, v_refs, pipe_vlm = _attach_visual(
                vis, vis_gaps, add_ref=add_ref, missing=missing
            )
            # 外部 JSON 不得授予 render_ready；仅 internal_verification 可提升
            elig = "candidate_only"
            blocks = ["awaiting_internal_media_verification"]
            conf = float(best["confidence"])
            if pipe_vlm:
                conf = min(1.0, conf + 0.1)
            time_prov = {
                "source": "linked_live_goal_event",
                "t_sec": best["t_sec"],
                "score_anchor_t_sec": score_t,
                "pipeline_verified": False,
                "granted_by": None,
            }
            segments.append(
                _mk_seg(
                    segment_id=f"seg_{role_prefix}_goal_action",
                    beat=beat,
                    role=f"{role_prefix}_goal_action",
                    event_ids=[live_id],
                    frame_ids=v_frames,
                    evidence_refs=[
                        add_ref(
                            {
                                "kind": "rule_fact",
                                "used_as_fact": True,
                                "source": "live_goal_candidate",
                                "event_id": live_id,
                                "dt_to_score_sec": best.get("dt_to_score_sec"),
                            }
                        )
                    ]
                    + v_refs,
                    media_in=win_g["media_in"],
                    media_out=win_g["media_out"],
                    time_status="linked_event_ms",
                    shot_kind="live",
                    is_replay=False,
                    narration=f"{role_prefix} 进球动作候选 {live_id} @ {best['t_sec']}s（相对记分牌 Δ={best.get('dt_to_score_sec')}s）。",
                    selection_reason=best.get("selection_reason") or "live_goal_near_scoreboard",
                    source_refs=[
                        provenance_ref(
                            namespace="t01_story_event",
                            ref_id=live_id,
                            extra={"shot_kind": "live"},
                        )
                    ],
                    confidence=conf,
                    time_provenance=time_prov,
                    render_eligibility=elig,
                    blocking_reasons=blocks,
                )
            )
            all_event_ids.append(live_id)

            # 回放补充：仅 linked_to_live
            for rep in find_replay_supplements(
                events, linked_live_event_id=live_id, score_t=score_t, role_hint=role_hint
            ):
                if rep.get("link_status") != "linked_to_live":
                    mappings.append(
                        {
                            "context": f"{role_prefix}_replay",
                            "status": "unresolved_mapping",
                            "event_id": rep.get("event_id"),
                            "reasons": rep.get("reasons"),
                        }
                    )
                    continue
                tw = _window_from_t(rep.get("t_sec"), status="event_ms")
                segments.append(
                    _mk_seg(
                        segment_id=f"seg_{role_prefix}_replay_{rep['event_id']}",
                        beat=beat,
                        role=f"{role_prefix}_replay_supplement",
                        event_ids=[rep["event_id"]],
                        frame_ids=[],
                        evidence_refs=[
                            add_ref(
                                {
                                    "kind": "rule_fact",
                                    "used_as_fact": True,
                                    "source": "replay_linked_to_live",
                                    "event_id": rep["event_id"],
                                    "linked_live_event_id": live_id,
                                }
                            )
                        ],
                        media_in=tw["media_in"],
                        media_out=tw["media_out"],
                        time_status="event_ms",
                        shot_kind="replay_supplement",
                        is_replay=True,
                        linked_live_event_id=live_id,
                        narration=f"回放补充（关联 live {live_id}；默认不成片）。",
                        selection_reason="replay_supplement_linked_to_live_goal",
                        source_refs=[
                            provenance_ref(
                                namespace="t01_story_event",
                                ref_id=rep["event_id"],
                                extra={"linked_live_event_id": live_id},
                            )
                        ],
                        confidence=float(rep.get("confidence") or 0.4),
                        time_provenance={
                            "source": "replay_event_ms",
                            "t_sec": rep.get("t_sec"),
                            "pipeline_verified": False,
                        },
                        render_eligibility="candidate_only",
                        blocking_reasons=[
                            "replay_not_auto_render",
                            "unverified_event_ms",
                        ],
                    )
                )
        else:
            missing.append(f"missing_live_goal_action:{role_prefix}")
            blocking.append(f"missing_trusted_goal_action:{role_prefix}")
            segments.append(
                _mk_seg(
                    segment_id=f"seg_{role_prefix}_goal_pending",
                    beat=beat,
                    role=f"{role_prefix}_goal_action",
                    event_ids=[],
                    frame_ids=[],
                    evidence_refs=[],
                    media_in=None,
                    media_out=None,
                    time_status="pending_localization",
                    shot_kind="unknown",
                    is_replay=False,
                    narration=f"{role_prefix} 缺少可信 live 进球动作窗口；记分牌时间不可冒充进球。",
                    selection_reason="no_live_goal_candidate_near_scoreboard",
                    source_refs=[
                        provenance_ref(
                            namespace="score_path_carrier",
                            ref_id=carrier or f"score@{score_t}",
                        )
                    ],
                    confidence=0.0,
                    time_provenance={
                        "source": "none",
                        "score_anchor_t_sec": score_t,
                        "pipeline_verified": False,
                    },
                    render_eligibility="blocked",
                    blocking_reasons=[f"missing_trusted_goal_action:{role_prefix}"],
                )
            )
        return live_id

    add_goal_beat(
        beat="转折",
        role_prefix="equalizer",
        score_node=milestones.get("equalizer"),
        role_hint="转折",
        vis_gaps=(
            "verify_equalizer_goal_action",
            "locate_equalizer_goal_action",
            "verify_equalizer_scoreboard",
        ),
    )
    add_goal_beat(
        beat="高潮",
        role_prefix="go_ahead",
        score_node=milestones.get("go_ahead"),
        role_hint="高潮",
        vis_gaps=(
            "verify_go_ahead_goal_action",
            "locate_go_ahead_goal_action",
            "verify_go_ahead_scoreboard",
        ),
    )

    # ---------- 收尾 ----------
    ending = [
        e
        for e in events.values()
        if e.get("story_role") == "收尾" or e.get("type") in ("比赛结束", "全场结束")
    ]
    if ending:
        ev = ending[0]
        eid = str(ev["event_id"])
        t = float(ev["t_ms"]) / 1000.0 if ev.get("t_ms") is not None else None
        win = _window_from_t(t, status="event_ms" if t is not None else "pending_localization")
        frames, refs, _ = _attach_visual(
            vis, ["post_climax_reaction"], add_ref=add_ref, missing=missing
        )
        segments.append(
            _mk_seg(
                segment_id="seg_ending",
                beat="收尾",
                role="ending",
                event_ids=[eid],
                frame_ids=frames,
                evidence_refs=[
                    add_ref(
                        {
                            "kind": "rule_fact",
                            "used_as_fact": True,
                            "source": "event",
                            "event_id": eid,
                        }
                    )
                ]
                + refs,
                media_in=win["media_in"],
                media_out=win["media_out"],
                time_status=win["time_status"],
                shot_kind="replay_supplement" if ev.get("is_replay") else "live",
                is_replay=bool(ev.get("is_replay")),
                narration="收尾/终场（未校准默认不成片）。",
                selection_reason="ending_event",
                source_refs=[
                    provenance_ref(
                        namespace=str(ev.get("_namespace") or "t01_story_event"), ref_id=eid
                    )
                ],
                confidence=0.5,
                time_provenance={
                    "source": "event_ms",
                    "t_sec": t,
                    "pipeline_verified": False,
                },
                render_eligibility="candidate_only",
                blocking_reasons=["unverified_event_ms"],
            )
        )
        all_event_ids.append(eid)
    else:
        missing.append("missing_ending_event")
        segments.append(
            _mk_seg(
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
                selection_reason="missing_ending",
                source_refs=[],
                confidence=0.0,
                time_provenance={"source": "none", "pipeline_verified": False},
                render_eligibility="blocked",
                blocking_reasons=["missing_ending_event"],
            )
        )

    # narrative_order：按 beat，同 beat 内按媒体时间（进球动作早于记分牌确认）
    def sort_key(s: Dict[str, Any]) -> Tuple:
        beat_i = BEATS.index(s["beat"]) if s["beat"] in BEATS else 99
        role = str(s.get("role") or "")
        role_rank = 1
        if "goal_action" in role and "pending" not in role:
            role_rank = 0
        elif "scoreboard" in role:
            role_rank = 1
        elif "replay" in role:
            role_rank = 2
        elif "pending" in role:
            role_rank = 3
        t = s.get("source_media_order")
        t_key = float(t) if t is not None else 1e18
        return (beat_i, t_key, role_rank, s.get("segment_id") or "")

    segments.sort(key=sort_key)
    for i, seg in enumerate(segments):
        seg["narrative_order"] = i + 1

    proto = plan["protagonist"].get("team_name") or f"side={side}"
    by_beat = {b: "" for b in BEATS}
    for b in BEATS:
        parts = [s["narration"] for s in segments if s["beat"] == b and s.get("narration")]
        by_beat[b] = " ".join(parts)
    summary = {
        "story": f"{proto} 逆风翻盘草稿方案（3A.1）：比分锚点与进球动作分离；默认不可直接成片。",
        "candidate": f"{proto} 翻盘候选不完整；见 missing_evidence / blocking_reasons。",
    }[tier if tier in ("story", "candidate") else "candidate"]

    plan["segments"] = segments
    plan["evidence_refs"] = evidence_refs_global
    plan["event_ids"] = sorted(set(all_event_ids))
    plan["event_mappings"] = mappings
    plan["missing_evidence"] = missing
    plan["narration"] = {"summary": summary, "by_beat": by_beat}
    plan["candidate_edl"] = build_candidate_edl(segments)
    plan["render_ready_edl"] = build_render_ready_edl(segments)
    plan["edl"] = plan["candidate_edl"]

    # 关键进球门禁
    ready_roles = {
        s.get("role")
        for s in segments
        if s.get("render_eligibility") == "render_ready"
    }
    if "equalizer_goal_action" not in ready_roles:
        blocking.append("equalizer_goal_action_not_render_ready")
    if "go_ahead_goal_action" not in ready_roles:
        blocking.append("go_ahead_goal_action_not_render_ready")
    plan["blocking_reasons"] = sorted(set(blocking))

    render_ok, render_problems = validate_render_ready(plan)
    plan["render_ready"] = bool(render_ok)
    plan["diagnostics"]["render_problems"] = render_problems

    hard_conflict_types = {
        "score_path_time_regression",
        "score_path_illegal_transition",
        "story_tier_without_comeback_arc",
        "mock_used_as_fact",
        "delta_side_mismatch",
        "forged_verified_flag",
    }
    hard = [
        c
        for c in (verification.get("conflicts") or [])
        if c.get("type") in hard_conflict_types
    ]
    if hard:
        plan["verification_status"] = "conflicts_present"
    elif not plan["render_ready"]:
        plan["verification_status"] = "not_render_ready"
    elif tier == "candidate" or missing:
        plan["verification_status"] = "partial"
    else:
        plan["verification_status"] = "structure_ok"

    if use_llm and api is not None:
        plan = _enrich_narration_llm(plan, api=api)
        plan["diagnostics"]["llm_used"] = True
        narr_issues = check_narration_grounding(plan)
        plan["diagnostics"]["narration_grounding"] = narr_issues
        if narr_issues.get("ungrounded"):
            plan["blocking_reasons"] = sorted(
                set(plan["blocking_reasons"]) | {"llm_narration_ungrounded_claims"}
            )
            # 回滚到规则叙事摘要标记
            plan["narration"]["summary"] = (
                (plan["narration"].get("summary") or "")
                + " [LLM claims stripped/flagged: ungrounded]"
            )

    ok, problems = validate_compose_plan(plan)
    plan["structure_ok"] = ok
    plan["diagnostics"]["structure_ok"] = ok
    plan["diagnostics"]["structure_problems"] = problems
    return plan


def _enrich_narration_llm(plan: Dict[str, Any], *, api: ApiProvider) -> Dict[str, Any]:
    system = (
        "You narrate a football comeback edit plan. "
        "Return JSON {summary:str, by_beat:{铺垫,蓄力,转折,高潮,收尾}, "
        "segment_notes:{segment_id:str}}. "
        "Do not invent scores, timestamps, or event ids beyond the provided evidence. "
        "Do not claim mock evidence is verified."
    )
    user = {
        "match_id": plan.get("match_id"),
        "tier": plan.get("story_tier"),
        "allowed_scores": [
            r.get("score")
            for r in (plan.get("evidence_refs") or [])
            if r.get("kind") == "rule_fact" and r.get("score")
        ],
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
        if raw.get("provider_mode") in ("degraded",) and api.require_real:
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
    from story_video_agent.internal_verification import strip_external_trust_flags

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
    # 外部信任字段一律剥离
    vis = strip_external_trust_flags(vis)
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
