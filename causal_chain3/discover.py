"""锚点候选发现 + 模板感知时间窗扩展。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Set

from causal_chain2.chain_rules import CANONICAL_SEQUENCES
from causal_chain2.segmentation_geom import segment_anchor_geom

# 险情 / 推进类链的次级锚点（chain2 仅 goal/VAR/红牌/点球）
SECONDARY_ANCHOR_TYPES = frozenset(
    {"keeper_save", "goal_line_clearance", "throw_in"}
)


def _segment_type_anchor_geom(
    events: List[Dict[str, Any]],
    anchor_types: frozenset[str],
    *,
    pre_ms: int,
    post_ms: int,
    min_events: int,
) -> List[tuple[int, int, int]]:
    """返回 (anchor_i, i0, i1) 列表。"""
    n = len(events)
    if n == 0:
        return []
    times = [int(e["t_ms"]) for e in events]
    out: List[tuple[int, int, int]] = []
    seen: Set[tuple[int, int]] = set()
    for i, e in enumerate(events):
        if e["type"] not in anchor_types:
            continue
        t = times[i]
        i0 = next((k for k in range(n) if times[k] >= t - pre_ms), 0)
        i1 = next((k for k in range(n - 1, -1, -1) if times[k] <= t + post_ms), n - 1)
        if i1 < i0 or i1 - i0 + 1 < min_events:
            continue
        key = (i0, i1)
        if key in seen:
            continue
        seen.add(key)
        out.append((i, i0, i1))
    return out


def _segment_double_shot_anchor(
    events: List[Dict[str, Any]],
    *,
    pre_ms: int,
    post_ms: int,
    min_events: int,
) -> List[tuple[int, int, int]]:
    """连续两次 shot（中柱/横梁链）以第二次 shot 为锚。"""
    n = len(events)
    times = [int(e["t_ms"]) for e in events]
    out: List[tuple[int, int, int]] = []
    seen: Set[tuple[int, int]] = set()
    for i in range(1, n):
        if events[i - 1]["type"] != "shot" or events[i]["type"] != "shot":
            continue
        t = times[i]
        i0 = next((k for k in range(n) if times[k] >= t - pre_ms), 0)
        i1 = next((k for k in range(n - 1, -1, -1) if times[k] <= t + post_ms), n - 1)
        if i1 < i0 or i1 - i0 + 1 < min_events:
            continue
        key = (i0, i1)
        if key in seen:
            continue
        seen.add(key)
        out.append((i, i0, i1))
    return out


@dataclass
class ChainCandidate:
    """一条待抽取的因果链候选窗。"""

    candidate_id: str
    anchor_i: int
    anchor_type: str
    anchor_t_ms: int
    i0: int
    i1: int
    t0_ms: int
    t1_ms: int
    event_types: List[str]
    hint_template_id: str = ""


def _expand_indices_for_template(
    events: List[Dict[str, Any]],
    anchor_i: int,
    template_id: str,
    *,
    pre_ms: int,
    post_ms: int,
) -> tuple[int, int]:
    """根据 canonical 最长骨架向前/后扩展索引边界。"""
    n = len(events)
    times = [int(e["t_ms"]) for e in events]
    seqs = CANONICAL_SEQUENCES.get(template_id, [])
    max_len = max((len(s) for s in seqs), default=4)
    t_anchor = times[anchor_i]

    i0 = next((k for k in range(n) if times[k] >= t_anchor - pre_ms), 0)
    i1 = next((k for k in range(n - 1, -1, -1) if times[k] <= t_anchor + post_ms), n - 1)

    # 锚点前最多再留 max_len 个事件
    i0 = max(i0, max(0, anchor_i - max_len - 2))
    i1 = min(i1, min(n - 1, anchor_i + max_len + 2))
    return i0, i1


def discover_candidates(
    events: List[Dict[str, Any]],
    *,
    pre_ms: int = 120_000,
    post_ms: int = 90_000,
    min_events: int = 2,
    hint_templates: Dict[int, str] | None = None,
) -> List[ChainCandidate]:
    """
    以锚点事件触发候选窗；若提供 hint_templates（anchor_i→template_id）则做模板感知扩展。
    """
    hint_templates = hint_templates or {}
    geom = segment_anchor_geom(
        events, pre_ms=pre_ms, post_ms=post_ms, min_events=min_events
    )
    anchor_windows: List[tuple[int, int, int]] = []
    for g in geom:
        anchor_i = g.anchor_i if g.anchor_i is not None else g.i1
        anchor_windows.append((anchor_i, g.i0, g.i1))

    for anchor_i, i0, i1 in _segment_type_anchor_geom(
        events,
        SECONDARY_ANCHOR_TYPES,
        pre_ms=pre_ms,
        post_ms=post_ms,
        min_events=min_events,
    ):
        anchor_windows.append((anchor_i, i0, i1))

    for anchor_i, i0, i1 in _segment_double_shot_anchor(
        events, pre_ms=pre_ms, post_ms=post_ms, min_events=min_events
    ):
        anchor_windows.append((anchor_i, i0, i1))

    seen: Set[tuple[int, int, str]] = set()
    out: List[ChainCandidate] = []

    for idx, (anchor_i, g_i0, g_i1) in enumerate(anchor_windows):
        anchor_type = events[anchor_i]["type"]
        hint = hint_templates.get(anchor_i, "")

        if hint:
            i0, i1 = _expand_indices_for_template(
                events, anchor_i, hint, pre_ms=pre_ms, post_ms=post_ms
            )
        else:
            i0, i1 = g_i0, g_i1

        key = (i0, i1, anchor_type)
        if key in seen:
            continue
        seen.add(key)

        types = [e["type"] for e in events[i0 : i1 + 1]]
        out.append(
            ChainCandidate(
                candidate_id=f"cand{idx:02d}",
                anchor_i=anchor_i,
                anchor_type=anchor_type,
                anchor_t_ms=int(events[anchor_i]["t_ms"]),
                i0=i0,
                i1=i1,
                t0_ms=int(events[i0]["t_ms"]),
                t1_ms=int(events[i1]["t_ms"]),
                event_types=types,
                hint_template_id=hint,
            )
        )
    return out
