"""逆风翻盘故事链：比分轨迹定主线，拆条链提供事件序列。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from story_chain.recognize import Recognition, recognize_comeback
from story_chain.score_path import ScoreNode, build_score_path, event_time_sec, find_comeback_arc, is_replay

GOAL_TYPES = frozenset({"进球", "乌龙球", "头球破门"})
DANGER_TERMINALS = frozenset({"扑救", "门线救险", "射门"})
_GOAL_MATCH_BEFORE = 90.0
_GOAL_MATCH_AFTER = 15.0
_CHAIN_EVENT_SLACK = 8.0

_ZH_TO_EN = {
    "进球": "goal",
    "乌龙球": "own_goal",
    "头球破门": "header_goal",
    "点球": "penalty",
    "射门": "shot",
    "任意球": "free_kick",
    "扑救": "keeper_save",
    "门线救险": "goal_line_clearance",
    "角球": "corner",
    "换人": "substitution",
    "比赛结束": "match_end",
    "犯规/被犯规": "foul",
    "争顶成功": "aerial_won",
    "传球": "pass",
    "过人": "dribble_past",
    "助攻": "assist",
    "界外球": "throw_in",
    "控球": "possession",
    "防守动作": "defensive_action",
    "吃牌": "card",
    "VAR": "var",
}


def _fmt(score: Tuple[int, int]) -> str:
    return f"{score[0]}:{score[1]}"


def _chain_terminal(chain: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    events = chain.get("events") or []
    if not events:
        return None
    return events[-1]


def _terminal_sec(chain: Dict[str, Any]) -> Optional[float]:
    terminal = _chain_terminal(chain)
    if not terminal or terminal.get("t_ms") is None:
        return None
    return float(terminal["t_ms"]) / 1000.0


def _match_goal_chain(
    step_t: float,
    chains: Sequence[Dict[str, Any]],
    used: set,
) -> Optional[Dict[str, Any]]:
    candidates: List[Tuple[float, bool, Dict[str, Any]]] = []
    for chain in chains:
        identity = id(chain)
        if identity in used:
            continue
        terminal = _chain_terminal(chain)
        if terminal is None or terminal.get("type") not in GOAL_TYPES:
            continue
        terminal_t = _terminal_sec(chain)
        if terminal_t is None:
            continue
        if step_t - _GOAL_MATCH_BEFORE <= terminal_t <= step_t + _GOAL_MATCH_AFTER:
            candidates.append((abs(terminal_t - step_t), bool(chain.get("is_replay")), chain))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]


def _delivery_by_id(events: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(event.get("event_id")): event for event in events if event.get("event_id")}


def _score_of_node(node: ScoreNode) -> str:
    return _fmt(node.score)


def _trim_chain_events(events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """同一条链里进球或扑救之后的重复镜头不再写入故事序列。"""
    if not events:
        return []
    terminal = events[-1].get("type")
    stop = GOAL_TYPES | DANGER_TERMINALS
    if terminal not in stop:
        return list(events)
    kept: List[Dict[str, Any]] = []
    for event in events:
        kept.append(event)
        if event.get("type") == terminal:
            break
    return kept


def _emit_chain_events(chain: Dict[str, Any], role: str, score: str) -> List[Dict[str, Any]]:
    subtype = chain.get("causal_chain_subtype") or ""
    annotation_id = chain.get("annotation_id") or ""
    replay = bool(chain.get("is_replay"))
    rows: List[Dict[str, Any]] = []
    for event in _trim_chain_events(chain.get("events") or []):
        rows.append(
            {
                "event_id": event.get("event_id"),
                "type": event.get("type"),
                "type_en": event.get("type_en") or _ZH_TO_EN.get(str(event.get("type") or ""), ""),
                "t_ms": event.get("t_ms"),
                "bz_id": event.get("bz_id"),
                "story_role": role,
                "source": "causal_chain",
                "source_annotation_id": annotation_id,
                "source_order": event.get("order"),
                "source_chain_category": chain.get("chain_category") or "",
                "source_chain_subtype": subtype,
                "is_replay": replay,
                "score_context": score,
            }
        )
    return rows


def _emit_delivery_event(event: Dict[str, Any], role: str, score: str) -> Dict[str, Any]:
    zh = str(event.get("event_type_zh") or "")
    return {
        "event_id": event.get("event_id"),
        "type": zh,
        "type_en": _ZH_TO_EN.get(zh, str(event.get("event_type") or "")),
        "t_ms": round(event_time_sec(event) * 1000.0, 1),
        "bz_id": event.get("bz_id"),
        "story_role": role,
        "source": "delivery_event",
        "source_annotation_id": "",
        "source_order": None,
        "source_chain_category": "",
        "source_chain_subtype": "",
        "is_replay": is_replay(event),
        "score_context": score,
    }


def _near_chain(event_row: Dict[str, Any], chain_rows: Sequence[Dict[str, Any]]) -> bool:
    t_ms = event_row.get("t_ms")
    if t_ms is None:
        return False
    zh = event_row.get("type")
    for row in chain_rows:
        if row.get("source") != "causal_chain":
            continue
        other = row.get("t_ms")
        if other is None:
            continue
        if row.get("type") == zh and abs(float(other) - float(t_ms)) <= _CHAIN_EVENT_SLACK * 1000:
            return True
    return False


def _step_events(
    node: ScoreNode,
    role: str,
    events: Sequence[Dict[str, Any]],
    chains: Sequence[Dict[str, Any]],
    used: set,
    by_id: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    chain = _match_goal_chain(node.t_sec, chains, used)
    score = _score_of_node(node)
    if chain is not None:
        used.add(id(chain))
        return _emit_chain_events(chain, role, score)
    carrier = by_id.get(node.carrier_event_id or "")
    if carrier is None:
        return []
    return [_emit_delivery_event(carrier, role, score)]


def _finish_event(events: Sequence[Dict[str, Any]], after_t: float) -> Optional[Dict[str, Any]]:
    """只收最后一粒故事进球之后的终场哨，避免半场结束插进高潮。"""
    candidates = []
    for event in events:
        if is_replay(event):
            continue
        if event.get("event_type_zh") != "比赛结束":
            continue
        if event_time_sec(event) >= after_t:
            candidates.append(event)
    if not candidates:
        return None
    candidates.sort(key=event_time_sec)
    return _emit_delivery_event(candidates[-1], "收尾", "")


def _base_result(
    match: Dict[str, Any],
    causal: Dict[str, Any],
    path: Sequence[ScoreNode],
    recognition: Optional[Recognition],
    *,
    reason: str,
) -> Dict[str, Any]:
    return {
        "schema_version": "story-t01-1",
        "match_id": match.get("match_id") or causal.get("match_id") or "",
        "video_name": causal.get("video_name") or "",
        "has_story": False,
        "is_candidate": False,
        "story_tier": "none",
        "story_template_id": "",
        "chain_category": "",
        "causal_chain_subtype": "",
        "story_label_zh": "无故事",
        "no_story_reason": reason,
        "protagonist_side": recognition.protagonist_side if recognition else None,
        "score_path": [node.to_dict() for node in path],
        "recognition": recognition.to_dict()
        if recognition
        else {
            "present": False,
            "tier": "none",
            "is_candidate": False,
            "reason": reason,
            "protagonist_side": None,
            "beats": {},
        },
        "events": [],
    }


def _empty_story(
    match: Dict[str, Any],
    causal: Dict[str, Any],
    reason: str,
    path: Sequence[ScoreNode],
    recognition: Optional[Recognition] = None,
) -> Dict[str, Any]:
    return _base_result(match, causal, path, recognition, reason=reason)


def _score_at(path: Sequence[ScoreNode], t_sec: float) -> str:
    active = path[0].score if path else (0, 0)
    for node in path:
        if node.t_sec <= t_sec:
            active = node.score
    return _fmt(active)


def _match_danger_chain(t_sec: float, chains: Sequence[Dict[str, Any]], used: set) -> Optional[Dict[str, Any]]:
    candidates: List[Tuple[float, Dict[str, Any]]] = []
    for chain in chains:
        if id(chain) in used or chain.get("chain_category") != "险情链":
            continue
        terminal = _chain_terminal(chain)
        if terminal is None or terminal.get("type") not in DANGER_TERMINALS:
            continue
        terminal_t = _terminal_sec(chain)
        if terminal_t is None:
            continue
        if t_sec - _GOAL_MATCH_BEFORE <= terminal_t <= t_sec + _GOAL_MATCH_AFTER:
            candidates.append((abs(terminal_t - t_sec), chain))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _emit_recognized(
    events: Sequence[Dict[str, Any]],
    chains: Sequence[Dict[str, Any]],
    recognition: Recognition,
    path: Sequence[ScoreNode],
    by_id: Dict[str, Dict[str, Any]],
    used: set,
) -> List[Dict[str, Any]]:
    """故事链只展开识别阶段点名的事件，不再另选一套片段。"""
    picked: List[Tuple[float, str, Dict[str, Any]]] = []
    for role in ("铺垫", "蓄力", "转折", "高潮"):
        for event_id in recognition.beats.get(role) or []:
            event = by_id.get(event_id)
            if event is None:
                continue
            picked.append((event_time_sec(event), role, event))
    picked.sort(key=lambda item: (item[0], item[1], str(item[2].get("event_id") or "")))

    rows: List[Dict[str, Any]] = []
    for t_sec, role, event in picked:
        score = _score_at(path, t_sec)
        zh = event.get("event_type_zh")
        if role in ("转折", "高潮") or (role == "铺垫" and zh not in _CRISIS_ZH):
            node = ScoreNode(
                t_sec=t_sec,
                score=tuple(int(part) for part in score.split(":")),  # type: ignore[arg-type]
                carrier_event_id=str(event.get("event_id") or ""),
            )
            rows.extend(_step_events(node, role, events, chains, used, by_id))
            continue
        if role == "铺垫":
            chain = _match_danger_chain(t_sec, chains, used)
            if chain is not None:
                used.add(id(chain))
                rows.extend(_emit_chain_events(chain, role, score))
                continue
        drafted = _emit_delivery_event(event, role, score)
        if not _near_chain(drafted, rows):
            rows.append(drafted)
    return rows


_CRISIS_ZH = frozenset({"扑救", "门线救险"})


def _pack_story(
    match_meta: Dict[str, Any],
    causal_meta: Dict[str, Any],
    path: Sequence[ScoreNode],
    recognition: Recognition,
    rows: List[Dict[str, Any]],
    *,
    strict: bool,
) -> Dict[str, Any]:
    out = _base_result(
        match_meta,
        causal_meta,
        path,
        recognition,
        reason="" if strict else recognition.reason,
    )
    out["has_story"] = strict
    out["is_candidate"] = not strict
    out["story_tier"] = "story" if strict else "candidate"
    out["story_template_id"] = "T01_comeback"
    out["chain_category"] = "故事链"
    out["causal_chain_subtype"] = "逆风翻盘"
    out["story_label_zh"] = "逆风翻盘" if strict else "逆风翻盘候选"
    out["protagonist_side"] = recognition.protagonist_side
    out["events"] = rows
    return out


def build_comeback_story(
    events: Sequence[Dict[str, Any]],
    chains: Sequence[Dict[str, Any]],
    *,
    match_meta: Optional[Dict[str, Any]] = None,
    causal_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    match_meta = match_meta or {}
    causal_meta = causal_meta or {}
    path = build_score_path(events)
    recognition = recognize_comeback(events)
    if recognition.tier == "none":
        return _empty_story(match_meta, causal_meta, recognition.reason, path, recognition)

    arc = find_comeback_arc(path)
    if arc is None:
        return _empty_story(match_meta, causal_meta, "no_comeback", path, recognition)

    by_id = _delivery_by_id(events)
    used: set = set()
    rows = _emit_recognized(events, chains, recognition, path, by_id, used)

    last_goal_t = arc["extras"][-1].t_sec if arc["extras"] else arc["go_ahead"].t_sec
    finish = _finish_event(events, last_goal_t)
    if finish is not None:
        finish["score_context"] = _fmt(path[-1].score)
        rows.append(finish)

    rows.sort(key=lambda row: (float(row["t_ms"] or 0), str(row.get("event_id") or "")))
    for order, row in enumerate(rows):
        row["order"] = order

    if not any(row["story_role"] == "转折" for row in rows) or not any(row["story_role"] == "高潮" for row in rows):
        return _empty_story(match_meta, causal_meta, "no_score_step_event", path, recognition)

    return _pack_story(
        match_meta,
        causal_meta,
        path,
        recognition,
        rows,
        strict=recognition.present,
    )


def build_match_story(delivery: Dict[str, Any], causal: Dict[str, Any]) -> Dict[str, Any]:
    return build_comeback_story(
        delivery.get("events") or [],
        causal.get("causal_chains") or [],
        match_meta=delivery,
        causal_meta=causal,
    )
