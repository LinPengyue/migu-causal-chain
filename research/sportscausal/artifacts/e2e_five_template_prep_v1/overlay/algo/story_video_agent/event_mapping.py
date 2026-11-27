"""Phase 3A.1：事件 ID 溯源与安全关联。

不得仅凭字符串相等关联 score_path.carrier_event_id 与 story.events。
关联须校验时间、类型、回放状态与来源；失败 → unresolved_mapping。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

# ID 来源命名空间（诊断用，不暗示可自动合并）
ID_NAMESPACES = frozenset(
    {
        "score_path_carrier",
        "t01_story_event",
        "delivery_event",
        "causal_chain",
        "visual_gap",
        "unknown",
    }
)

_GOAL_TYPES = frozenset({"进球", "乌龙球", "头球破门", "goal", "own_goal", "header_goal", "Goal"})
_ASSIST_TYPES = frozenset({"助攻", "assist", "Assist"})
# carrier 与 score 时间允许偏差（秒）；回放通常远大于此
# 记分牌相对 live 进球常滞后；过窄会漏掉反超等关键动作（机制参数，非场次特例）
DEFAULT_TIME_SLACK_SEC = 180.0


def event_namespace(event: Dict[str, Any]) -> str:
    src = str(event.get("source") or "")
    if src == "causal_chain":
        return "causal_chain"
    if src == "delivery_event":
        return "delivery_event"
    if event.get("event_id"):
        return "t01_story_event"
    return "unknown"


def event_t_sec(event: Dict[str, Any]) -> Optional[float]:
    if event.get("t_ms") is not None:
        try:
            return float(event["t_ms"]) / 1000.0
        except (TypeError, ValueError):
            return None
    if event.get("t_sec") is not None:
        try:
            return float(event["t_sec"])
        except (TypeError, ValueError):
            return None
    return None


def index_story_events(story: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for ev in story.get("events") or []:
        if not isinstance(ev, dict) or not ev.get("event_id"):
            continue
        eid = str(ev["event_id"])
        # 碰撞：同 ID 出现多次 → 标记，不静默覆盖
        if eid in out:
            out[eid] = {
                **out[eid],
                "_id_collision": True,
                "_collision_count": int(out[eid].get("_collision_count") or 1) + 1,
            }
        else:
            row = dict(ev)
            row["_namespace"] = event_namespace(ev)
            row["_id_collision"] = False
            out[eid] = row
    return out


def merge_causal_live_goals(
    events: Dict[str, Dict[str, Any]],
    causal: Optional[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """把交付因果链中的 live 进球并入索引。

    T01 story.events 常只保留主角扳平/反超进球，丢失造成落后的对手进球；
    score_path.carrier 又可能指向记分牌旁的非进球交付事件（同 ID 冲突）。
    因果链进球用 ``causal:<annotation_id>:<event_id>`` 命名，避免覆盖交付 ID。
    """
    if not causal:
        return events
    out = dict(events)
    for chain in causal.get("causal_chains") or []:
        if not isinstance(chain, dict):
            continue
        if chain.get("is_replay"):
            continue
        ann = str(chain.get("annotation_id") or "ann")
        for ev in chain.get("events") or []:
            if not isinstance(ev, dict):
                continue
            if ev.get("type") not in _GOAL_TYPES and ev.get("type_en") not in _GOAL_TYPES:
                continue
            if ev.get("is_replay"):
                continue
            raw_id = str(ev.get("event_id") or "")
            if not raw_id:
                continue
            eid = f"causal:{ann}:{raw_id}"
            if eid in out:
                continue
            row = dict(ev)
            row["event_id"] = eid
            row["source"] = "causal_chain"
            row["source_annotation_id"] = ann
            row["story_role"] = row.get("story_role") or "铺垫"
            row["_namespace"] = "causal_chain"
            row["_id_collision"] = False
            row["_causal_raw_event_id"] = raw_id
            out[eid] = row
    return out


def _type_compatible_for_score_carrier(
    event_type: str, *, score_delta_side: Optional[str]
) -> bool:
    """记分牌 carrier 期望进球类；助攻/传球等不兼容。"""
    t = (event_type or "").strip()
    if t in _GOAL_TYPES:
        return True
    # 明确不兼容
    if t in _ASSIST_TYPES or t in ("传球", "角球", "犯规", "pass", "corner"):
        return False
    # 未知类型：不自动兼容
    return False


def link_score_carrier(
    *,
    carrier_event_id: Optional[str],
    score_node: Dict[str, Any],
    events: Dict[str, Dict[str, Any]],
    time_slack_sec: float = DEFAULT_TIME_SLACK_SEC,
    require_live: bool = False,
) -> Dict[str, Any]:
    """尝试将 score_path.carrier_event_id 关联到 T01 story.events。"""
    score_t = float(score_node.get("t_sec") or -1)
    score = score_node.get("score")
    delta = score_node.get("delta_side")
    cid = str(carrier_event_id or "").strip()
    base = {
        "carrier_event_id": cid or None,
        "score_t_sec": score_t,
        "score": score,
        "delta_side": delta,
        "status": "unresolved_mapping",
        "linked_event_id": None,
        "reasons": [],
        "checks": {},
    }
    if not cid:
        base["reasons"].append("empty_carrier_id")
        return base
    ev = events.get(cid)
    if ev is None:
        base["reasons"].append("carrier_id_not_in_story_events")
        base["checks"]["id_string_match"] = False
        return base
    # 字符串命中 ≠ 语义关联；继续校验
    base["checks"]["id_string_match"] = True
    if ev.get("_id_collision"):
        base["reasons"].append("event_id_collision")
        return base

    t = event_t_sec(ev)
    base["checks"]["event_t_sec"] = t
    base["checks"]["event_type"] = ev.get("type")
    base["checks"]["is_replay"] = bool(ev.get("is_replay"))
    base["checks"]["namespace"] = ev.get("_namespace")
    base["checks"]["score_context"] = ev.get("score_context")

    if t is None:
        base["reasons"].append("event_missing_time")
        return base
    dt = abs(t - score_t)
    base["checks"]["abs_dt_sec"] = round(dt, 3)
    if dt > time_slack_sec:
        base["reasons"].append(
            f"time_mismatch: event@{t:.3f}s vs score@{score_t:.3f}s dt={dt:.3f}s>{time_slack_sec}"
        )

    if not _type_compatible_for_score_carrier(str(ev.get("type") or ""), score_delta_side=delta):
        base["reasons"].append(f"type_incompatible:{ev.get('type')}")

    if require_live and ev.get("is_replay"):
        base["reasons"].append("replay_not_allowed_for_required_live")
    elif ev.get("is_replay") and dt > 30.0:
        # 回放且时间远离记分牌 → 禁止当作该比分节点动作
        base["reasons"].append("replay_far_from_scoreboard")

    # score_context 若存在且与节点比分矛盾矛盾
    ctx = ev.get("score_context")
    if ctx and score and str(ctx) != str(score):
        base["reasons"].append(f"score_context_mismatch:{ctx}!={score}")

    if base["reasons"]:
        return base

    base["status"] = "linked"
    base["linked_event_id"] = cid
    base["linked_event"] = {
        "event_id": cid,
        "type": ev.get("type"),
        "t_sec": t,
        "is_replay": bool(ev.get("is_replay")),
        "namespace": ev.get("_namespace"),
        "story_role": ev.get("story_role"),
    }
    return base


def find_live_goal_candidates(
    events: Dict[str, Dict[str, Any]],
    *,
    score_t: float,
    role_hint: Optional[str] = None,
    slack_before: float = DEFAULT_TIME_SLACK_SEC,
    slack_after: float = 30.0,
) -> List[Dict[str, Any]]:
    """在比分确认锚点附近寻找 live 进球动作候选（score_path 本身不是进球时间）。"""
    cands: List[Dict[str, Any]] = []
    for eid, ev in events.items():
        if ev.get("type") not in _GOAL_TYPES:
            continue
        if ev.get("is_replay"):
            continue
        if ev.get("_id_collision"):
            continue
        t = event_t_sec(ev)
        if t is None:
            continue
        if not (score_t - slack_before <= t <= score_t + slack_after):
            continue
        dt = t - score_t
        # 进球通常不晚于记分牌太多
        weight = abs(dt)
        if role_hint and ev.get("story_role") and ev.get("story_role") != role_hint:
            weight += 40.0
        cands.append(
            {
                "event_id": eid,
                "t_sec": t,
                "type": ev.get("type"),
                "is_replay": False,
                "shot_kind": "live",
                "story_role": ev.get("story_role"),
                "namespace": ev.get("_namespace"),
                "dt_to_score_sec": round(dt, 3),
                "confidence": round(max(0.0, 1.0 - weight / max(slack_before, 1.0)), 3),
                "selection_reason": "live_goal_near_scoreboard_anchor",
            }
        )
    cands.sort(key=lambda c: (-c["confidence"], abs(c["dt_to_score_sec"])))
    return cands


def find_replay_supplements(
    events: Dict[str, Dict[str, Any]],
    *,
    linked_live_event_id: Optional[str],
    score_t: Optional[float] = None,
    role_hint: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """回放补充：必须能指向关联的真实比赛事件或明确 unresolved。"""
    out: List[Dict[str, Any]] = []
    live = events.get(str(linked_live_event_id or ""))
    live_t = event_t_sec(live) if live else None
    for eid, ev in events.items():
        if not ev.get("is_replay"):
            continue
        if ev.get("type") not in _GOAL_TYPES and ev.get("type") not in _ASSIST_TYPES:
            continue
        t = event_t_sec(ev)
        linked_to = None
        status = "unresolved_mapping"
        reasons: List[str] = []
        if linked_live_event_id and live_t is not None and t is not None:
            # 回放通常在 live 之后
            if 0 <= (t - live_t) <= 900:
                linked_to = linked_live_event_id
                status = "linked_to_live"
            else:
                reasons.append("replay_not_near_live_event")
        elif score_t is not None and t is not None and abs(t - score_t) <= 900:
            reasons.append("replay_near_score_but_no_live_link")
        else:
            reasons.append("no_live_anchor")
        if role_hint and ev.get("story_role") and ev.get("story_role") != role_hint:
            reasons.append(f"role_hint_mismatch:{ev.get('story_role')}")
        out.append(
            {
                "event_id": eid,
                "t_sec": t,
                "type": ev.get("type"),
                "shot_kind": "replay_supplement",
                "is_replay": True,
                "link_status": status,
                "linked_live_event_id": linked_to,
                "reasons": reasons,
                "confidence": 0.4 if status == "linked_to_live" else 0.1,
            }
        )
    return out


def provenance_ref(
    *,
    namespace: str,
    ref_id: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    row = {"namespace": namespace if namespace in ID_NAMESPACES else "unknown", "id": ref_id}
    if extra:
        row.update(extra)
    return row
