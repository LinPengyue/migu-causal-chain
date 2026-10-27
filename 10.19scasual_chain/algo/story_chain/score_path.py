"""从交付事件的 score_recognition 抽出稳定比分轨迹。

只承认一侧加 1 且在随后窗口里站住的变化。记分牌闪回、时钟样式和缺省比分都不补。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

Score = Tuple[int, int]
_SCORE_RE = re.compile(r"\s*(\d+)\s*[:：]\s*(\d+)\s*")
_MAX_SIDE = 9
_CONFIRM_SEC = 90.0
_MIN_HITS = 2


@dataclass
class ScoreNode:
    t_sec: float
    score: Score
    opening: bool = False
    delta_side: Optional[str] = None
    carrier_event_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "t_sec": round(self.t_sec, 3),
            "score": f"{self.score[0]}:{self.score[1]}",
            "opening": self.opening,
            "delta_side": self.delta_side,
            "carrier_event_id": self.carrier_event_id,
        }


@dataclass
class ScoredEvent:
    t_sec: float
    score: Score
    event_id: str
    event_type_zh: str
    raw: Dict[str, Any] = field(repr=False)


def parse_score(value: Any) -> Optional[Score]:
    if not isinstance(value, str):
        return None
    matched = _SCORE_RE.fullmatch(value)
    if not matched:
        return None
    left, right = int(matched.group(1)), int(matched.group(2))
    if left > _MAX_SIDE or right > _MAX_SIDE:
        return None
    return left, right


def event_time_sec(event: Dict[str, Any]) -> float:
    media = event.get("media_time") or {}
    raw = media.get("event_time_sec")
    if raw is None:
        raw = media.get("start_time_sec") or 0
    return float(raw)


def is_replay(event: Dict[str, Any]) -> bool:
    return bool((event.get("video_context") or {}).get("is_replay"))


def _plus_one(prev: Score, nxt: Score) -> Optional[str]:
    d_left = nxt[0] - prev[0]
    d_right = nxt[1] - prev[1]
    if d_left + d_right != 1:
        return None
    if d_left == 1 and d_right == 0:
        return "left"
    if d_right == 1 and d_left == 0:
        return "right"
    return None


def live_scored_events(events: Sequence[Dict[str, Any]]) -> List[ScoredEvent]:
    rows: List[ScoredEvent] = []
    for event in events:
        if is_replay(event):
            continue
        score = parse_score((event.get("scores") or {}).get("score_recognition"))
        if score is None:
            continue
        rows.append(
            ScoredEvent(
                t_sec=event_time_sec(event),
                score=score,
                event_id=str(event.get("event_id") or ""),
                event_type_zh=str(event.get("event_type_zh") or ""),
                raw=event,
            )
        )
    rows.sort(key=lambda row: (row.t_sec, row.event_id))
    return rows


def _confirmed(points: Sequence[ScoredEvent], index: int, prev: Score, nxt: Score) -> bool:
    t0 = points[index].t_sec
    window = [row for row in points if t0 <= row.t_sec <= t0 + _CONFIRM_SEC]
    if len(window) < _MIN_HITS:
        return False
    hits = sum(1 for row in window if row.score == nxt)
    prev_hits = sum(1 for row in window if row.score == prev)
    if hits < _MIN_HITS or hits <= prev_hits:
        return False
    top = max(sum(1 for row in window if row.score == score) for score in {row.score for row in window})
    return hits == top


def build_score_path(events: Sequence[Dict[str, Any]]) -> List[ScoreNode]:
    """返回已提交比分。第一节点是开场比分，不一定对应进球。"""
    points = live_scored_events(events)
    if not points:
        return []

    zero_at = next((row.t_sec for row in points if row.score == (0, 0)), None)
    if zero_at is not None:
        points = [row for row in points if row.t_sec >= zero_at - 1e-6]
        start_score: Score = (0, 0)
        start_t = zero_at
        start_event = next(row.event_id for row in points if row.score == (0, 0))
    else:
        start_score = points[0].score
        start_t = points[0].t_sec
        start_event = points[0].event_id

    path = [
        ScoreNode(
            t_sec=start_t,
            score=start_score,
            opening=True,
            carrier_event_id=start_event,
        )
    ]
    for index, row in enumerate(points):
        prev = path[-1]
        if row.t_sec < prev.t_sec:
            continue
        side = _plus_one(prev.score, row.score)
        if side is None:
            continue
        if not _confirmed(points, index, prev.score, row.score):
            continue
        path.append(
            ScoreNode(
                t_sec=row.t_sec,
                score=row.score,
                opening=False,
                delta_side=side,
                carrier_event_id=row.event_id,
            )
        )
    return path


def _side_margin(score: Score, side: str) -> int:
    if side == "left":
        return score[0] - score[1]
    return score[1] - score[0]


def _leader(score: Score) -> Optional[str]:
    if score[0] > score[1]:
        return "left"
    if score[1] > score[0]:
        return "right"
    return None


def find_comeback_arc(path: Sequence[ScoreNode], *, max_extra_goals: int = 2) -> Optional[Dict[str, Any]]:
    """主角是终场领先、且轨迹上曾经落后的那一侧。取最后一次翻盘。"""
    if len(path) < 2:
        return None
    protagonist = _leader(path[-1].score)
    if protagonist is None:
        return None
    last_behind: Optional[int] = None
    for index, node in enumerate(path):
        if _side_margin(node.score, protagonist) < 0:
            last_behind = index
    if last_behind is None:
        return None

    equalizer: Optional[ScoreNode] = None
    go_ahead: Optional[ScoreNode] = None
    for node in path[last_behind + 1 :]:
        margin = _side_margin(node.score, protagonist)
        if equalizer is None and margin == 0:
            equalizer = node
        elif equalizer is not None and go_ahead is None and margin > 0:
            go_ahead = node
            break
    if equalizer is None or go_ahead is None:
        return None

    spell_start = last_behind
    while spell_start > 0 and _side_margin(path[spell_start - 1].score, protagonist) < 0:
        spell_start -= 1
    extras = [
        node
        for node in path
        if node.t_sec > go_ahead.t_sec and node.delta_side == protagonist
    ][:max_extra_goals]
    return {
        "protagonist_side": protagonist,
        "spell": list(path[spell_start : last_behind + 1]),
        "equalizer": equalizer,
        "go_ahead": go_ahead,
        "extras": extras,
    }
