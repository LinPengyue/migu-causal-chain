"""在原始比赛时间序列上判断有没有逆风翻盘，不生成故事链。

两层结论（产品约定，2026-10-20）：
- story：比分翻盘，且时间序列里有铺垫 + 蓄力，可出完整故事链
- candidate：比分已走出落后→扳平→反超，但缺铺垫/蓄力（如克罗地亚开场即落后），
  仍属逆风翻盘剧本候选，标 candidate，不升为正式故事
- none：连比分翻盘都不成立
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from story_chain.score_path import ScoreNode, build_score_path, event_time_sec, find_comeback_arc, is_replay

_CRISIS_TYPES = frozenset({"扑救", "门线救险"})
_ATTEMPT_TYPES = frozenset({"射门", "任意球", "角球"})
_MIN_ATTEMPTS = 2
_MAX_CRISIS = 3
_MAX_ATTEMPTS = 3

TIER_NONE = "none"
TIER_CANDIDATE = "candidate"
TIER_STORY = "story"


@dataclass
class Recognition:
    present: bool
    reason: str
    tier: str = TIER_NONE
    protagonist_side: Optional[str] = None
    beats: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def is_candidate(self) -> bool:
        return self.tier == TIER_CANDIDATE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "present": self.present,
            "tier": self.tier,
            "is_candidate": self.is_candidate,
            "reason": self.reason,
            "protagonist_side": self.protagonist_side,
            "beats": self.beats,
        }


def _live(events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = [event for event in events if not is_replay(event)]
    rows.sort(key=lambda event: (event_time_sec(event), str(event.get("event_id") or "")))
    return rows


def _ids_between(
    events: Sequence[Dict[str, Any]],
    types: frozenset,
    t0: float,
    t1: float,
    *,
    skip_ids: Sequence[str] = (),
) -> List[str]:
    skipped = set(skip_ids)
    found: List[str] = []
    for event in events:
        event_id = str(event.get("event_id") or "")
        if event_id in skipped:
            continue
        if event.get("event_type_zh") not in types:
            continue
        t_sec = event_time_sec(event)
        if t0 <= t_sec < t1:
            found.append(event_id)
    return found


def _sample_even(event_ids: Sequence[str], limit: int) -> List[str]:
    rows = list(event_ids)
    if len(rows) <= limit:
        return rows
    if limit <= 1:
        return [rows[len(rows) // 2]]
    picked: List[str] = []
    seen = set()
    for slot in range(limit):
        index = round(slot * (len(rows) - 1) / (limit - 1))
        if index in seen:
            continue
        seen.add(index)
        picked.append(rows[index])
    return picked


def _core_beats(arc: Dict[str, Any]) -> Dict[str, List[str]]:
    equalizer: ScoreNode = arc["equalizer"]
    go_ahead: ScoreNode = arc["go_ahead"]
    beats = {
        "铺垫": [],
        "蓄力": [],
        "转折": [equalizer.carrier_event_id] if equalizer.carrier_event_id else [],
        "高潮": [go_ahead.carrier_event_id] if go_ahead.carrier_event_id else [],
    }
    for node in arc["extras"]:
        if node.carrier_event_id and node.carrier_event_id not in beats["高潮"]:
            beats["高潮"].append(node.carrier_event_id)
    return beats


def _candidate(
    reason: str,
    protagonist: Optional[str],
    beats: Optional[Dict[str, List[str]]] = None,
) -> Recognition:
    return Recognition(
        present=False,
        reason=reason,
        tier=TIER_CANDIDATE,
        protagonist_side=protagonist,
        beats=beats or {},
    )


def recognize_comeback(events: Sequence[Dict[str, Any]]) -> Recognition:
    """只看全量事件。比分翻盘是候选门槛；铺垫+蓄力齐才升为正式故事。"""
    path = build_score_path(events)
    if not path:
        return Recognition(False, "no_score", TIER_NONE)
    arc = find_comeback_arc(path)
    if arc is None:
        return Recognition(False, "no_comeback", TIER_NONE)

    live = _live(events)
    spell: List[ScoreNode] = arc["spell"]
    equalizer: ScoreNode = arc["equalizer"]
    go_ahead: ScoreNode = arc["go_ahead"]
    t_behind = spell[0].t_sec
    protagonist = arc["protagonist_side"]
    beats = _core_beats(arc)
    if not beats["转折"] or not beats["高潮"]:
        return Recognition(False, "no_score_step_event", TIER_NONE, protagonist, beats)
    if not (equalizer.t_sec < go_ahead.t_sec):
        return Recognition(False, "beats_out_of_order", TIER_NONE, protagonist, beats)

    # 失球铺垫：对手造成落后的记分节点（含开场即 0:n 的 opening 节点）。
    # 旧逻辑跳过 opening，导致「开场即落后」场次永远 missing_setup、不展开对手进球。
    concede_ids: List[str] = []
    for node in spell:
        if (not node.opening) and node.delta_side == protagonist:
            continue
        if node.carrier_event_id:
            concede_ids.append(node.carrier_event_id)
    crisis_ids = _ids_between(live, _CRISIS_TYPES, t_behind, equalizer.t_sec)
    setup_ids = concede_ids + [event_id for event_id in crisis_ids if event_id not in concede_ids]
    if not setup_ids:
        return _candidate("missing_setup", protagonist, beats)

    occupied = [equalizer.carrier_event_id or "", go_ahead.carrier_event_id or ""]
    attempt_ids = _ids_between(
        live,
        _ATTEMPT_TYPES,
        t_behind,
        go_ahead.t_sec,
        skip_ids=occupied,
    )
    beats["铺垫"] = concede_ids + _sample_even(
        [event_id for event_id in crisis_ids if event_id not in concede_ids],
        _MAX_CRISIS,
    )
    if len(attempt_ids) < _MIN_ATTEMPTS:
        beats["蓄力"] = list(attempt_ids)
        return _candidate("missing_buildup", protagonist, beats)

    setup_times = [event_time_sec(event) for event in live if str(event.get("event_id")) in set(setup_ids)]
    attempt_times = [event_time_sec(event) for event in live if str(event.get("event_id")) in set(attempt_ids)]
    if not setup_times or min(setup_times) >= equalizer.t_sec:
        return _candidate("setup_not_before_equalizer", protagonist, beats)
    if not attempt_times or min(attempt_times) >= go_ahead.t_sec:
        beats["蓄力"] = list(attempt_ids)
        return _candidate("buildup_not_before_go_ahead", protagonist, beats)

    beats["蓄力"] = _sample_even(attempt_ids, _MAX_ATTEMPTS)
    return Recognition(True, "", TIER_STORY, protagonist, beats)
