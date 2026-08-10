"""从长事件链抽取核心骨架，便于规则/VLM 分类。"""

from __future__ import annotations

import copy
from typing import List, Optional

from causal_chain2.event_io import ensure_event_ids


def _slice_events(events: List[dict], indices: List[int]) -> List[dict]:
    out = []
    for j, i in enumerate(indices):
        ev = copy.deepcopy(events[i])
        ev["order"] = j
        out.append(ev)
    return out


def _find_suffix(events: List[dict], types: List[str], suffix: List[str]) -> Optional[List[int]]:
    if len(suffix) > len(types):
        return None
    n = len(suffix)
    for start in range(len(types) - n, -1, -1):
        if types[start : start + n] == suffix:
            return list(range(start, start + n))
    return None


def _find_from_marker(events: List[dict], types: List[str], marker: str) -> Optional[List[int]]:
    if marker not in types:
        return None
    start = types.index(marker)
    return list(range(start, len(types)))


def extract_minimal_core(
    events: List[dict],
    *,
    gold_template_id: Optional[str] = None,
    prefix: str = "core",
) -> List[dict]:
    if len(events) <= 4:
        return copy.deepcopy(events)

    types = [str(e.get("type", "")) for e in events]

    if gold_template_id == "shot_save_chain" or (
        "keeper_save" in types and "shot" in types
    ):
        idx = _find_suffix(events, types, ["shot", "keeper_save"])
        if idx:
            i0 = max(0, idx[0] - 2)
            return ensure_event_ids(_slice_events(events, list(range(i0, idx[-1] + 1))), prefix=prefix)

    if gold_template_id == "goal_line_extreme_save_chain" or "goal_line_clearance" in types:
        idx = _find_suffix(events, types, ["shot", "goal_line_clearance"])
        if idx:
            return ensure_event_ids(_slice_events(events, idx), prefix=prefix)

    if gold_template_id == "throw_in_build_up_chain" or "throw_in" in types:
        idx = _find_from_marker(events, types, "throw_in")
        if idx:
            trimmed = idx[:]
            for terminal in ("goal", "foul", "shot", "keeper_save"):
                if terminal in types[idx[0] :]:
                    end = types.index(terminal, idx[0]) + 1
                    trimmed = list(range(idx[0], end))
                    break
            return ensure_event_ids(_slice_events(events, trimmed), prefix=prefix)

    if "goal" in types:
        goal_i = len(types) - 1 - types[::-1].index("goal")
        start = max(0, goal_i - 4)
        if "successful_tackle" in types[start : goal_i + 1] or "interception" in types[start : goal_i + 1]:
            start = max(0, goal_i - 5)
        return ensure_event_ids(_slice_events(events, list(range(start, goal_i + 1))), prefix=prefix)

    if "keeper_save" in types:
        idx = _find_suffix(events, types, ["shot", "keeper_save"])
        if idx:
            return ensure_event_ids(_slice_events(events, idx), prefix=prefix)

    return copy.deepcopy(events)
