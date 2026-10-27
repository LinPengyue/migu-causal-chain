"""协议字段 ↔ 算法字段适配。咪咕固定映射只维护这一份。

时间语义（已确认）：
- 外部 eventTime / callback start·end：媒体时间轴秒（可小数），原点=输入视频/直播会话起点
- 内部算法：始终毫秒 t_ms / t0_ms / t1_ms
- 仅在本 adapter 转换，不改 causal_chain 算法
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger("api.adapters")

from api.event_type_map import (  # noqa: E402 — 唯一 provisional 表
    PROVISIONAL_EVENT_TYPE_MAP,
    UNMAPPED_EVENT_TYPE,
)

# 剩余 PROTOCOL_BLOCKER：正式 eventTypeId 字典（见 event_type_map.py）

# 媒体时间轴（非足球比赛时钟）
TIME_MODE = "media_timeline"
EXTERNAL_TIME_UNIT = "seconds"
INTERNAL_TIME_UNIT = "milliseconds"


@dataclass
class AdapterConfig:
    # 外部协议固定为媒体时间秒
    event_time_unit: str = "s"
    callback_time_mode: str = "chain_window"
    emit_highlight_type5: bool = True
    reject_out_of_order: bool = True
    enable_deadline_timer: bool = True
    media_ms_per_wall_second: float = 1000.0
    deadline_timer_min_wall_s: float = 0.02
    deadline_timer_max_wall_s: float = 120.0
    # 未知 eventTypeId：reject=拒绝 sync；unmapped=写入哨兵类型并告警（默认）
    unknown_event_type_policy: str = "unmapped"  # "unmapped" | "reject"


DEFAULT_ADAPTER_CONFIG = AdapterConfig()

CATEGORY_TO_HIGHLIGHT_TYPE: Dict[str, int] = {
    "outcome": 1,
    "correction": 2,
    "danger": 3,
    "special": 4,
}

# 咪咕固定 chainType 1~18（禁止按 enum 顺序自动生成）
MIGU_CHAIN_TYPE_MAP: Dict[str, int] = {
    "corner_cross_goal": 1,
    "rebound_follow_up_goal": 2,
    "turnover_counter_goal": 3,
    "penalty_scored_chain": 4,
    "red_card_decision_chain": 5,
    "goal_disallowed_chain": 6,
    "var_penalty_cancelled_chain": 7,
    "var_overturn_chain": 8,
    "shot_save_chain": 9,
    "shot_post_bar_chain": 10,
    "second_phase_after_frame_chain": 11,
    "goal_line_extreme_save_chain": 12,
    "throw_in_build_up_chain": 13,
    "own_goal_causal_chain": 14,
    "keeper_spill_danger_chain": 15,
    "deflection_goal_chain": 16,
    "quick_restart_set_piece_chain": 17,
    "outcome_other": 18,
    # 新增 outcome 细分类 → 18（不是 19）
    "individual_breakthrough_goal": 18,
    "team_buildup_goal": 18,
    "corner_coop_goal": 18,
}

CHAIN_TEMPLATE_TO_TYPE: Dict[str, int] = MIGU_CHAIN_TYPE_MAP

# highlightType=5 专用：集锦组合链（非算法模板，不进 MIGU_CHAIN_TYPE_MAP）
MIGU_REEL_CHAIN_TYPE = 19
MIGU_REEL_CHAIN_NAME = "集锦组合链"


def event_time_to_ms(event_time: Any, cfg: AdapterConfig = DEFAULT_ADAPTER_CONFIG) -> int:
    """外部媒体时间秒 → 内部 ms。用 Decimal 避免浮点误差（如 108.351→108351）。"""
    del cfg  # 外部协议已固定为秒
    d = Decimal(str(event_time))
    return int((d * Decimal(1000)).to_integral_value(rounding=ROUND_HALF_UP))


def ms_to_media_seconds(t_ms: int) -> float:
    """内部 ms → 外部媒体时间秒。"""
    d = (Decimal(int(t_ms)) / Decimal(1000)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    # 干净整数秒用 x.0
    if d == d.to_integral_value():
        return float(d.to_integral_value())
    return float(d)


def map_event_type(
    event_type_id: Optional[str],
    event_name: Optional[str],
) -> str:
    """兼容旧调用；无上下文时同样禁止把未知串冒充为已知事件。"""
    typ, _mapped = resolve_event_type(event_type_id, event_name)
    return typ


def resolve_event_type(
    event_type_id: Optional[str],
    event_name: Optional[str],
) -> Tuple[str, bool]:
    """查 provisional 表。返回 (internal_type, mapped_ok)。

    mapped_ok=False 时 type 恒为 UNMAPPED_EVENT_TYPE，绝不把未知 id 当已知事件。
    """
    for raw in (event_type_id, event_name):
        if raw is None:
            continue
        s = str(raw).strip()
        if not s:
            continue
        if s in PROVISIONAL_EVENT_TYPE_MAP:
            return PROVISIONAL_EVENT_TYPE_MAP[s], True
        key = s.lower().replace(" ", "_")
        if key in PROVISIONAL_EVENT_TYPE_MAP:
            return PROVISIONAL_EVENT_TYPE_MAP[key], True
    return UNMAPPED_EVENT_TYPE, False


def map_event_type_with_context(
    event_type_id: Optional[str],
    event_name: Optional[str],
    *,
    task_id: str = "",
    match_id: str = "",
    clip_id: str = "",
    cfg: AdapterConfig = DEFAULT_ADAPTER_CONFIG,
) -> Tuple[str, bool]:
    """带联调上下文的映射。返回 (type, ok)。ok=False 且 policy=reject 时由调用方拒收。"""
    typ, ok = resolve_event_type(event_type_id, event_name)
    if ok:
        return typ, True
    logger.warning(
        "unknown eventTypeId mapping REJECTED_AS_KNOWN taskId=%s matchId=%s clipId=%s "
        "eventTypeId=%r eventName=%r → fallback=%r policy=%s "
        "(PROTOCOL_BLOCKER: formal eventTypeId dict)",
        task_id,
        match_id,
        clip_id,
        event_type_id,
        event_name,
        UNMAPPED_EVENT_TYPE,
        cfg.unknown_event_type_policy,
    )
    if cfg.unknown_event_type_policy == "reject":
        return UNMAPPED_EVENT_TYPE, False
    return UNMAPPED_EVENT_TYPE, True  # accept as unmapped sentinel


def category_to_highlight_type(category: str) -> int:
    return CATEGORY_TO_HIGHLIGHT_TYPE.get(str(category or "").strip().lower(), 1)


def template_to_chain_type(template_id: str) -> int:
    tid = str(template_id or "").strip()
    if tid in MIGU_CHAIN_TYPE_MAP:
        return MIGU_CHAIN_TYPE_MAP[tid]
    logger.warning("template_id %r not in migu map; fallback chainType=18", tid)
    return 18


def build_highlight_time(
    *,
    chain_t0_ms: int,
    chain_t1_ms: int,
    event_t_ms: Optional[int] = None,
    cfg: AdapterConfig = DEFAULT_ADAPTER_CONFIG,
) -> Tuple[float, float]:
    """内部 ms → callback start/end（媒体时间秒）。"""
    if cfg.callback_time_mode == "event_ms" and event_t_ms is not None:
        start = end = ms_to_media_seconds(int(event_t_ms))
    else:
        start = ms_to_media_seconds(int(chain_t0_ms))
        end = ms_to_media_seconds(int(chain_t1_ms))
    logger.info(
        "start/end semantic=%s unit=%s start=%s end=%s",
        TIME_MODE,
        EXTERNAL_TIME_UNIT,
        start,
        end,
    )
    return start, end


def clip_to_algo_event(
    clip: Dict[str, Any],
    *,
    cfg: AdapterConfig = DEFAULT_ADAPTER_CONFIG,
    order: int = 0,
    task_id: str = "",
    match_id: str = "",
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """clip → 算法事件。返回 (event, error_message)。error 非空表示应拒绝 sync。"""
    clip_id = str(clip["clipId"])
    typ, ok = map_event_type_with_context(
        clip.get("eventTypeId"),
        clip.get("eventName"),
        task_id=task_id,
        match_id=match_id,
        clip_id=clip_id,
        cfg=cfg,
    )
    if not ok and cfg.unknown_event_type_policy == "reject":
        return None, (
            f"unknown eventTypeId/eventName rejected: "
            f"eventTypeId={clip.get('eventTypeId')!r} eventName={clip.get('eventName')!r}"
        )
    ev: Dict[str, Any] = {
        "event_id": clip_id,
        "type": typ,
        "t_ms": event_time_to_ms(clip["eventTime"], cfg),
        "order": int(order),
        "migu_clip_id": clip_id,
        "migu_video_path": clip.get("videoPath"),
        "migu_event_name": clip.get("eventName"),
        "migu_event_type_id": clip.get("eventTypeId"),
        "migu_score": clip.get("score"),
        "migu_type_unmapped": typ == UNMAPPED_EVENT_TYPE,
    }
    return ev, None


def _lookup_category(template_id: str, category: str = "") -> str:
    cat = str(category or "").strip()
    if cat:
        return cat
    try:
        from causal_chain6.schema.templates import CHAIN4_TEMPLATES

        return str((CHAIN4_TEMPLATES.get(template_id) or {}).get("category") or "")
    except Exception:  # noqa: BLE001
        return ""


def _chain_event_ids(chain: Any) -> List[str]:
    evs = getattr(chain, "events", None) or (chain.get("events") if isinstance(chain, dict) else []) or []
    out: List[str] = []
    for e in evs:
        if isinstance(e, dict):
            eid = e.get("event_id") or e.get("migu_clip_id")
        else:
            eid = getattr(e, "event_id", None)
        if eid:
            out.append(str(eid))
    return out


def _chain_window(chain: Any) -> Tuple[int, int]:
    if isinstance(chain, dict):
        return int(chain.get("t0_ms") or 0), int(chain.get("t1_ms") or 0)
    return int(getattr(chain, "t0_ms", 0) or 0), int(getattr(chain, "t1_ms", 0) or 0)


def _chain_category(chain: Any) -> str:
    if isinstance(chain, dict):
        tid = str(chain.get("pred_chain_template_id") or chain.get("chain_template_id") or "")
        return _lookup_category(tid, str(chain.get("chain_category") or ""))
    return str(getattr(chain, "chain_category", "") or "")


def _chain_template(chain: Any) -> str:
    if isinstance(chain, dict):
        return str(
            chain.get("pred_chain_template_id")
            or chain.get("chain_template_id")
            or chain.get("template_id")
            or ""
        )
    return str(getattr(chain, "chain_template_id", "") or "")


def resolve_business_clip_ids(
    chain: Any,
    *,
    known_clip_ids: Sequence[str],
    events: Sequence[Dict[str, Any]],
) -> List[str]:
    known = set(str(x) for x in known_clip_ids)
    from_chain = [eid for eid in _chain_event_ids(chain) if eid in known]
    if from_chain:
        seen: Set[str] = set()
        out: List[str] = []
        for x in from_chain:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out
    t0, t1 = _chain_window(chain)
    out = []
    seen = set()
    for ev in events:
        eid = str(ev.get("event_id") or "")
        if eid not in known or eid in seen:
            continue
        if t0 <= int(ev.get("t_ms") or 0) <= t1:
            seen.add(eid)
            out.append(eid)
    return out


def strip_result_id(clip: Dict[str, Any], *, known_clip_ids: Sequence[str]) -> str:
    tid = _chain_template(clip)
    t0, t1 = _chain_window(clip)
    known = set(str(x) for x in known_clip_ids)
    eids = [e for e in _chain_event_ids(clip) if e in known]
    return f"{t0}:{t1}:{tid}:{','.join(eids)}"


def strip_clip_to_callback_body(
    *,
    task_id: str,
    match_id: str,
    clip: Dict[str, Any],
    known_clip_ids: Sequence[str],
    events: Sequence[Dict[str, Any]],
    cfg: AdapterConfig = DEFAULT_ADAPTER_CONFIG,
) -> Dict[str, Any]:
    t0, t1 = _chain_window(clip)
    clip_ids = resolve_business_clip_ids(clip, known_clip_ids=known_clip_ids, events=events)
    highlights: List[Dict[str, Any]] = []
    for cid in clip_ids:
        ev = next((e for e in events if str(e.get("event_id")) == cid), None)
        start, end = build_highlight_time(
            chain_t0_ms=t0,
            chain_t1_ms=t1,
            event_t_ms=int(ev["t_ms"]) if ev else None,
            cfg=cfg,
        )
        highlights.append({"clipId": cid, "start": start, "end": end})
    return {
        "taskId": task_id,
        "matchId": match_id,
        "highlightType": category_to_highlight_type(_chain_category(clip)),
        "chainType": template_to_chain_type(_chain_template(clip)),
        "highlights": highlights,
    }


def select_new_strip_callbacks(
    preds: Sequence[Dict[str, Any]],
    *,
    task_id: str,
    match_id: str,
    known_clip_ids: Sequence[str],
    events: Sequence[Dict[str, Any]],
    emitted_result_ids: Set[str],
    cfg: AdapterConfig = DEFAULT_ADAPTER_CONFIG,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    bodies: List[Dict[str, Any]] = []
    new_ids: List[str] = []
    for p in preds or []:
        if not isinstance(p, dict):
            continue
        rid = strip_result_id(p, known_clip_ids=known_clip_ids)
        if rid in emitted_result_ids:
            continue
        body = strip_clip_to_callback_body(
            task_id=task_id,
            match_id=match_id,
            clip=p,
            known_clip_ids=known_clip_ids,
            events=events,
            cfg=cfg,
        )
        new_ids.append(rid)
        if body.get("highlights"):
            bodies.append(body)
    return bodies, new_ids


def post_match_type5_body(
    *,
    task_id: str,
    match_id: str,
    reel_clips: Sequence[Any],
    known_clip_ids: Sequence[str],
    events: Sequence[Dict[str, Any]],
    cfg: AdapterConfig = DEFAULT_ADAPTER_CONFIG,
) -> Optional[Dict[str, Any]]:
    """赛后集锦：highlightType=5 / chainType=19（集锦组合链）。"""
    if not cfg.emit_highlight_type5:
        return None

    highlights: List[Dict[str, Any]] = []
    # 按 reel 播放顺序展开（不跨段全局去重，保持顺序）
    for chain in reel_clips or []:
        t0, t1 = _chain_window(chain)
        start, end = build_highlight_time(chain_t0_ms=t0, chain_t1_ms=t1, cfg=cfg)
        for cid in resolve_business_clip_ids(
            chain, known_clip_ids=known_clip_ids, events=events
        ):
            highlights.append({"clipId": cid, "start": start, "end": end})

    return {
        "taskId": task_id,
        "matchId": match_id,
        "highlightType": 5,
        "chainType": int(MIGU_REEL_CHAIN_TYPE),
        "highlights": highlights,
    }
