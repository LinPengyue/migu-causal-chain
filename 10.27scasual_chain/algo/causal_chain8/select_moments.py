"""层 A：通用集锦选片（PDF T0/T1/T2 规则，不可被因果链分数覆盖）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

# --- 分级 ---
T0_GOAL = frozenset({"goal", "header_goal", "own_goal"})
T0_RED = frozenset({"red_card", "second_yellow_red"})
T1_SHOT = frozenset({"shot", "header_shot"})
T1_SAVE = frozenset({"keeper_save"})
T1_FK = frozenset({"free_kick"})
T2_TYPES = frozenset(
    {
        "header_shot",  # 进攻头球（与射门头球重叠时按邻域过滤）
        "dribble_breakthrough",
        "dribble_past",
        "successful_tackle",
        "interception",
        "corner",
    }
)

# 短窗（ms）——全局常量，不按场次调参
WINDOW_MS = {
    "T0": (12_000, 4_000),
    "T1": (8_000, 5_000),
    "T2": (6_000, 4_000),
}

HALF_MS_DEFAULT = 45 * 60 * 1000
SLOT_MS = 15 * 60 * 1000
MERGE_GAP_MS = 2_000
T1_NEAR_DUP_MS = 5_000

# T0 数量 → 推荐补 T1 数（规则三）
T0_TO_T1_FILL = {1: 5, 2: 4, 3: 3, 4: 2, 5: 1}


@dataclass
class HighlightMoment:
    tier: str
    event_type: str
    event_i: int
    t_ms: int
    t0_ms: int
    t1_ms: int
    reason: str = ""
    half: int = 1  # 1 or 2
    slot: int = 0  # 0..2 within half

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier,
            "event_type": self.event_type,
            "event_i": self.event_i,
            "t_ms": self.t_ms,
            "t0_ms": self.t0_ms,
            "t1_ms": self.t1_ms,
            "reason": self.reason,
            "half": self.half,
            "slot": self.slot,
        }


def _times(events: Sequence[Dict[str, Any]]) -> List[int]:
    return [int(e["t_ms"]) for e in events]


def _half_and_slot(t_ms: int, half_ms: int) -> Tuple[int, int]:
    if t_ms < half_ms:
        half = 1
        slot = min(2, max(0, t_ms // SLOT_MS))
    else:
        half = 2
        rel = t_ms - half_ms
        slot = min(2, max(0, rel // SLOT_MS))
    return half, int(slot)


def _window_for(tier: str, t_ms: int, t_min: int, t_max: int) -> Tuple[int, int]:
    pre, post = WINDOW_MS.get(tier, (8_000, 5_000))
    return max(t_min, t_ms - pre), min(t_max, t_ms + post)


def _events_in_range(
    events: Sequence[Dict[str, Any]],
    times: Sequence[int],
    t0: int,
    t1: int,
) -> List[Tuple[int, Dict[str, Any]]]:
    out = []
    for i, t in enumerate(times):
        if t0 <= t <= t1:
            out.append((i, events[i]))
    return out


def _is_penalty_goal(
    events: Sequence[Dict[str, Any]],
    times: Sequence[int],
    i: int,
) -> bool:
    """点球后短窗内进球 → 视为 T0 点球进球。"""
    if events[i]["type"] != "penalty":
        return False
    t = times[i]
    for j in range(i, min(i + 8, len(events))):
        if times[j] - t > 20_000:
            break
        if events[j]["type"] in T0_GOAL:
            return True
    return False


def collect_t0(
    events: Sequence[Dict[str, Any]],
    times: Sequence[int],
    half_ms: int,
    t_min: int,
    t_max: int,
) -> List[HighlightMoment]:
    moments: List[HighlightMoment] = []
    seen_t: Set[int] = set()
    for i, e in enumerate(events):
        typ = e["type"]
        t = times[i]
        tier_type = None
        reason = ""
        if typ in T0_GOAL:
            tier_type, reason = typ, "t0_goal"
        elif typ in T0_RED:
            tier_type, reason = typ, "t0_red"
        elif typ == "penalty" and _is_penalty_goal(events, times, i):
            tier_type, reason = "penalty", "t0_penalty_goal"
        if not tier_type:
            continue
        # 同一毫秒多个 goal 只留一条
        if t in seen_t and tier_type in T0_GOAL:
            continue
        seen_t.add(t)
        half, slot = _half_and_slot(t, half_ms)
        t0, t1 = _window_for("T0", t, t_min, t_max)
        moments.append(
            HighlightMoment(
                tier="T0",
                event_type=tier_type,
                event_i=i,
                t_ms=t,
                t0_ms=t0,
                t1_ms=t1,
                reason=reason,
                half=half,
                slot=slot,
            )
        )
    moments.sort(key=lambda m: m.t_ms)
    return moments


def _has_type_after(
    events: Sequence[Dict[str, Any]],
    times: Sequence[int],
    i: int,
    types: Set[str],
    max_ms: int,
) -> bool:
    t = times[i]
    for j in range(i + 1, len(events)):
        dt = times[j] - t
        if dt > max_ms:
            break
        if events[j]["type"] in types:
            return True
    return False


def _has_type_before(
    events: Sequence[Dict[str, Any]],
    times: Sequence[int],
    i: int,
    types: Set[str],
    max_ms: int,
) -> bool:
    t = times[i]
    for j in range(i - 1, -1, -1):
        dt = t - times[j]
        if dt > max_ms:
            break
        if events[j]["type"] in types:
            return True
    return False


def is_valuable_t1(
    events: Sequence[Dict[str, Any]],
    times: Sequence[int],
    i: int,
) -> Tuple[bool, str]:
    typ = events[i]["type"]
    if typ in T1_SAVE:
        # 前 3s 射门，且后为角球/再射门；或扑后同队控球/传球
        if _has_type_before(events, times, i, set(T1_SHOT), 3_000):
            if _has_type_after(events, times, i, set(T1_SHOT) | {"corner"}, 8_000):
                return True, "save_after_shot_then_threat"
            if _has_type_after(events, times, i, {"pass", "ball_possession"}, 8_000):
                return True, "save_then_possession"
        return False, ""
    if typ in T1_SHOT:
        if _has_type_after(events, times, i, set(T1_SAVE) | {"corner"}, 10_000):
            return True, "shot_then_save_or_corner"
        return False, ""
    if typ in T1_FK:
        if _has_type_after(events, times, i, set(T1_SHOT), 10_000):
            return True, "fk_then_shot"
        if _has_type_after(events, times, i, set(T1_SAVE) | {"corner"}, 12_000):
            return True, "fk_then_save_or_corner"
        return False, ""
    return False, ""


def is_valuable_t2(
    events: Sequence[Dict[str, Any]],
    times: Sequence[int],
    i: int,
) -> Tuple[bool, str]:
    typ = events[i]["type"]
    if typ in ("dribble_breakthrough", "dribble_past"):
        if _has_type_after(
            events, times, i, set(T1_SHOT) | set(T1_FK) | {"corner"}, 10_000
        ):
            return True, "dribble_then_threat"
        return False, ""
    if typ in ("successful_tackle", "interception", "corner"):
        if _has_type_after(
            events, times, i, set(T1_SHOT) | set(T1_FK) | set(T1_SAVE), 10_000
        ):
            return True, f"{typ}_then_threat"
        return False, ""
    if typ == "header_shot":
        # 进攻头球：后紧跟扑救/角球
        if _has_type_after(events, times, i, set(T1_SAVE) | {"corner"}, 8_000):
            return True, "header_then_save_or_corner"
        return False, ""
    return False, ""


def collect_valuable_t1(
    events: Sequence[Dict[str, Any]],
    times: Sequence[int],
    half_ms: int,
    t_min: int,
    t_max: int,
    *,
    exclude_t_ms: Optional[Set[int]] = None,
) -> List[HighlightMoment]:
    exclude_t_ms = exclude_t_ms or set()
    out: List[HighlightMoment] = []
    for i, e in enumerate(events):
        if e["type"] not in (T1_SHOT | T1_SAVE | T1_FK):
            continue
        t = times[i]
        if t in exclude_t_ms:
            continue
        ok, reason = is_valuable_t1(events, times, i)
        if not ok:
            continue
        half, slot = _half_and_slot(t, half_ms)
        t0, t1 = _window_for("T1", t, t_min, t_max)
        out.append(
            HighlightMoment(
                tier="T1",
                event_type=e["type"],
                event_i=i,
                t_ms=t,
                t0_ms=t0,
                t1_ms=t1,
                reason=reason,
                half=half,
                slot=slot,
            )
        )
    out.sort(key=lambda m: m.t_ms)
    return out


def collect_valuable_t2(
    events: Sequence[Dict[str, Any]],
    times: Sequence[int],
    half_ms: int,
    t_min: int,
    t_max: int,
    *,
    exclude_t_ms: Optional[Set[int]] = None,
) -> List[HighlightMoment]:
    exclude_t_ms = exclude_t_ms or set()
    out: List[HighlightMoment] = []
    for i, e in enumerate(events):
        if e["type"] not in T2_TYPES:
            continue
        # header_shot 已可能作为 T1 射门；T2 头球走同样邻域
        t = times[i]
        if t in exclude_t_ms:
            continue
        ok, reason = is_valuable_t2(events, times, i)
        if not ok:
            continue
        half, slot = _half_and_slot(t, half_ms)
        t0, t1 = _window_for("T2", t, t_min, t_max)
        out.append(
            HighlightMoment(
                tier="T2",
                event_type=e["type"],
                event_i=i,
                t_ms=t,
                t0_ms=t0,
                t1_ms=t1,
                reason=reason,
                half=half,
                slot=slot,
            )
        )
    out.sort(key=lambda m: m.t_ms)
    return out


_T1_WEIGHT = {"shot": 3, "header_shot": 3, "keeper_save": 2, "free_kick": 1}
_T2_WEIGHT = {
    "header_shot": 5,
    "dribble_breakthrough": 4,
    "dribble_past": 4,
    "interception": 3,
    "successful_tackle": 2,
    "corner": 1,
}


def _weight(m: HighlightMoment) -> int:
    if m.tier == "T1":
        return _T1_WEIGHT.get(m.event_type, 0)
    if m.tier == "T2":
        return _T2_WEIGHT.get(m.event_type, 0)
    return 10


def _slot_center(half: int, slot: int, half_ms: int) -> int:
    base = 0 if half == 1 else half_ms
    return base + slot * SLOT_MS + SLOT_MS // 2


def pick_per_slot(
    candidates: List[HighlightMoment],
    half_ms: int,
    *,
    per_half: int = 3,
) -> List[HighlightMoment]:
    """每半场最多 per_half 个：每个 15 分钟槽选 1 个最接近槽中点的高权重事件。"""
    picked: List[HighlightMoment] = []
    for half in (1, 2):
        half_cands = [m for m in candidates if m.half == half]
        slot_picks: List[HighlightMoment] = []
        for slot in range(3):
            pool = [m for m in half_cands if m.slot == slot]
            if not pool:
                continue
            center = _slot_center(half, slot, half_ms)
            pool.sort(key=lambda m: (-_weight(m), abs(m.t_ms - center)))
            slot_picks.append(pool[0])
        # 不足则从该半场其他槽补
        if len(slot_picks) < per_half:
            used = {id(m) for m in slot_picks}
            rest = [m for m in half_cands if id(m) not in used]
            rest.sort(key=lambda m: (-_weight(m), m.t_ms))
            for m in rest:
                if len(slot_picks) >= per_half:
                    break
                slot_picks.append(m)
        picked.extend(slot_picks[:per_half])
    picked.sort(key=lambda m: m.t_ms)
    return picked


def dedupe_near(moments: List[HighlightMoment], gap_ms: int = T1_NEAR_DUP_MS) -> List[HighlightMoment]:
    """时间间隔过近只留 1 个（优先更高权重，同权优先射门）。"""
    if not moments:
        return []
    ordered = sorted(moments, key=lambda m: m.t_ms)
    kept: List[HighlightMoment] = [ordered[0]]
    for m in ordered[1:]:
        prev = kept[-1]
        if m.t_ms - prev.t_ms < gap_ms:
            # 替换或跳过
            if _weight(m) > _weight(prev):
                kept[-1] = m
            elif _weight(m) == _weight(prev) and m.event_type in T1_SHOT and prev.event_type not in T1_SHOT:
                kept[-1] = m
            continue
        kept.append(m)
    return kept


def merge_overlapping(moments: List[HighlightMoment], gap_ms: int = MERGE_GAP_MS) -> List[HighlightMoment]:
    """相邻重叠或间隔 < gap → 合并区间（保留更高 tier / 更早锚点信息）。"""
    if not moments:
        return []
    tier_rank = {"T0": 3, "T1": 2, "T2": 1}
    ordered = sorted(moments, key=lambda m: m.t0_ms)
    out: List[HighlightMoment] = []
    cur = ordered[0]
    for m in ordered[1:]:
        if m.t0_ms <= cur.t1_ms + gap_ms:
            # merge
            prefer = m if tier_rank.get(m.tier, 0) > tier_rank.get(cur.tier, 0) else cur
            if tier_rank.get(m.tier, 0) == tier_rank.get(cur.tier, 0):
                prefer = cur if cur.t_ms <= m.t_ms else m
            cur = HighlightMoment(
                tier=prefer.tier,
                event_type=prefer.event_type,
                event_i=prefer.event_i,
                t_ms=prefer.t_ms,
                t0_ms=min(cur.t0_ms, m.t0_ms),
                t1_ms=max(cur.t1_ms, m.t1_ms),
                reason=prefer.reason + "|merged",
                half=prefer.half,
                slot=prefer.slot,
            )
        else:
            out.append(cur)
            cur = m
    out.append(cur)
    return out


def _t0_type_flags(t0: List[HighlightMoment]) -> Tuple[bool, bool, bool]:
    has_goal = any(m.event_type in T0_GOAL for m in t0)
    has_pen = any(m.reason == "t0_penalty_goal" or m.event_type == "penalty" for m in t0)
    has_red = any(m.event_type in T0_RED for m in t0)
    return has_goal, has_pen, has_red


def _fill_t1_for_t0_count(
    t0: List[HighlightMoment],
    t1_pool: List[HighlightMoment],
    half_ms: int,
) -> List[HighlightMoment]:
    """规则三：T0 全收，按数量与半场分布补 T1。"""
    n = len(t0)
    if n <= 0:
        return []
    if n >= 6:
        return list(t0)

    t0_h1 = [m for m in t0 if m.half == 1]
    t0_h2 = [m for m in t0 if m.half == 2]
    n1, n2 = len(t0_h1), len(t0_h2)

    # 每半场目标段数（尽量 3+3=6）
    need1, need2 = 0, 0
    if n == 1:
        if n1 == 1:
            need1, need2 = 2, 3
        else:
            need1, need2 = 3, 2
    elif n == 2:
        if n1 == 2:
            need1, need2 = 1, 3
        elif n2 == 2:
            need1, need2 = 3, 1
        else:
            need1, need2 = 2, 2
    elif n == 3:
        if n1 == 3:
            need1, need2 = 0, 3
        elif n2 == 3:
            need1, need2 = 3, 0
        elif n1 == 2:
            need1, need2 = 1, 2
        else:
            need1, need2 = 2, 1
    elif n == 4:
        if n1 >= 3:
            need1, need2 = 0, 2
        elif n2 >= 3:
            need1, need2 = 2, 0
        elif n1 == 2 and n2 == 2:
            need1, need2 = 1, 1
        elif n1 == 3:
            need1, need2 = 0, 2
        elif n2 == 1:
            need1, need2 = 0, 2  # 3+1 → 只有 1 个 T0 的半场补 2
            if n1 == 3:
                need1, need2 = 0, 2
        if n1 == 3 and n2 == 1:
            need1, need2 = 0, 2
        elif n1 == 1 and n2 == 3:
            need1, need2 = 2, 0
    elif n == 5:
        # 仅当极端集中才补 1 个 T1
        if n1 == 5:
            need1, need2 = 0, 1
        elif n2 == 5:
            need1, need2 = 1, 0
        else:
            need1, need2 = 0, 0

    def pick_half(half: int, already: int, need_extra: int) -> List[HighlightMoment]:
        if need_extra <= 0:
            return []
        pool = [m for m in t1_pool if m.half == half]
        # 避开 T0 过近
        t0_times = {m.t_ms for m in t0}
        pool = [m for m in pool if all(abs(m.t_ms - t) >= T1_NEAR_DUP_MS for t in t0_times)]
        # 优先填空白槽
        occupied_slots = {m.slot for m in t0 if m.half == half}
        by_slot: Dict[int, List[HighlightMoment]] = {0: [], 1: [], 2: []}
        for m in pool:
            by_slot.setdefault(m.slot, []).append(m)
        chosen: List[HighlightMoment] = []
        # 先补空槽
        for slot in range(3):
            if len(chosen) >= need_extra:
                break
            if slot in occupied_slots and already + len([x for x in t0 if x.half == half and x.slot == slot]) >= 1:
                # 槽已有 T0 仍可补，但后置
                continue
            cands = by_slot.get(slot) or []
            if not cands:
                continue
            center = _slot_center(half, slot, half_ms)
            cands.sort(key=lambda m: (-_weight(m), abs(m.t_ms - center)))
            chosen.append(cands[0])
        # 再任意补足
        used = {id(m) for m in chosen}
        rest = [m for m in pool if id(m) not in used]
        rest.sort(key=lambda m: (-_weight(m), m.t_ms))
        for m in rest:
            if len(chosen) >= need_extra:
                break
            chosen.append(m)
        return chosen[:need_extra]

    extra = pick_half(1, n1, need1) + pick_half(2, n2, need2)
    return sorted(t0 + extra, key=lambda m: m.t_ms)


def select_moments(
    events: Sequence[Dict[str, Any]],
    *,
    half_ms: Optional[int] = None,
) -> Tuple[List[HighlightMoment], Dict[str, Any]]:
    """PDF 规则选片。返回 (moments, debug_stats)。"""
    if not events:
        return [], {"n_events": 0}

    times = _times(events)
    t_min, t_max = times[0], times[-1]
    if half_ms is None:
        # 有足够时长用 45min，否则对半分
        half_ms = HALF_MS_DEFAULT if t_max >= HALF_MS_DEFAULT else max(t_max // 2, 1)

    t0 = collect_t0(events, times, half_ms, t_min, t_max)
    t0_times = {m.t_ms for m in t0}
    t1_all = collect_valuable_t1(
        events, times, half_ms, t_min, t_max, exclude_t_ms=t0_times
    )
    t2_all = collect_valuable_t2(
        events, times, half_ms, t_min, t_max, exclude_t_ms=t0_times
    )

    has_goal, has_pen, has_red = _t0_type_flags(t0)
    rule = ""
    selected: List[HighlightMoment] = []

    # 规则一：三类 T0 都有 → 只收 T0
    if has_goal and has_pen and has_red:
        rule = "rule1_t0_only_all_three"
        selected = list(t0)
    elif len(t0) == 0:
        # 规则二：只用 T1
        rule = "rule2_t1_only"
        selected = pick_per_slot(t1_all, half_ms, per_half=3)
        selected = dedupe_near(selected, T1_NEAR_DUP_MS)
        # 规则四：T1 太少用 T2 补
        if len(selected) < 4:
            rule = "rule4_t1_plus_t2"
            need = 6 - len(selected)
            used = {m.t_ms for m in selected}
            t2_pool = [m for m in t2_all if m.t_ms not in used]
            t2_picked = pick_per_slot(t2_pool, half_ms, per_half=3)
            t2_picked = dedupe_near(t2_picked, T1_NEAR_DUP_MS)
            for m in t2_picked:
                if len(selected) >= 6:
                    break
                if all(abs(m.t_ms - s.t_ms) >= T1_NEAR_DUP_MS for s in selected):
                    selected.append(m)
            selected.sort(key=lambda m: m.t_ms)
    elif 1 <= len(t0) <= 5:
        rule = f"rule3_t0_{len(t0)}_fill_t1"
        selected = _fill_t1_for_t0_count(t0, t1_all, half_ms)
        selected = dedupe_near(selected, T1_NEAR_DUP_MS)
        # 确保所有 T0 仍在
        have = {m.t_ms for m in selected if m.tier == "T0"}
        for m in t0:
            if m.t_ms not in have:
                selected.append(m)
        selected.sort(key=lambda m: m.t_ms)
    else:
        rule = "rule_t0_many"
        selected = list(t0)

    selected = merge_overlapping(selected, MERGE_GAP_MS)
    selected.sort(key=lambda m: m.t_ms)

    stats = {
        "rule": rule,
        "half_ms": half_ms,
        "n_t0": len(t0),
        "n_t1_pool": len(t1_all),
        "n_t2_pool": len(t2_all),
        "n_selected": len(selected),
        "n_t0_selected": sum(1 for m in selected if m.tier == "T0"),
        "n_t1_selected": sum(1 for m in selected if m.tier == "T1"),
        "n_t2_selected": sum(1 for m in selected if m.tier == "T2"),
        "has_goal": has_goal,
        "has_penalty_goal": has_pen,
        "has_red": has_red,
    }
    return selected, stats


def moment_to_index_window(
    events: Sequence[Dict[str, Any]],
    moment: HighlightMoment,
) -> Tuple[int, int, int]:
    """返回 (anchor_i, i0, i1)。"""
    times = _times(events)
    i0 = next((k for k in range(len(times)) if times[k] >= moment.t0_ms), 0)
    i1 = next(
        (k for k in range(len(times) - 1, -1, -1) if times[k] <= moment.t1_ms),
        len(times) - 1,
    )
    if i1 < i0:
        i0, i1 = i1, i0
    anchor_i = moment.event_i
    if not (i0 <= anchor_i <= i1):
        # 锚点落到窗外时取窗内最接近
        anchor_i = min(range(i0, i1 + 1), key=lambda k: abs(times[k] - moment.t_ms))
    return anchor_i, i0, i1
