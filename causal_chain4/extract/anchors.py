"""锚点检测：从长序列定位因果链候选窗口。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Set, Tuple


@dataclass
class AnchorWindow:
    start: int
    end: int
    anchor_type: str
    anchor_index: int


_TERMINAL_TYPES: Set[str] = {
    "goal",
    "header_goal",
    "disallowed_goal",
    "keeper_save",
    "goal_line_clearance",
    "red_card",
    "second_yellow_red",
    "penalty",
    "foul",
    "shot",
    "corner",
    "throw_in",
    "var",
}


def detect_anchor_windows(types: List[str], *, max_window: int = 12) -> List[AnchorWindow]:
    """返回若干 [start, end) 候选窗（含 end-1）。"""
    n = len(types)
    if n == 0:
        return []
    if n <= max_window:
        return [AnchorWindow(0, n, types[-1], n - 1)]

    windows: List[AnchorWindow] = []
    seen: Set[Tuple[int, int]] = set()

    def add(start: int, end: int, anchor_type: str, anchor_i: int) -> None:
        start = max(0, start)
        end = min(n, end)
        if end <= start:
            return
        if end - start > max_window:
            start = end - max_window
        key = (start, end)
        if key in seen:
            return
        seen.add(key)
        windows.append(AnchorWindow(start, end, anchor_type, anchor_i))

    for i, t in enumerate(types):
        if t not in _TERMINAL_TYPES:
            continue
        if t == "goal":
            start = i
            for j in range(i, -1, -1):
                if types[j] in ("successful_tackle", "interception", "possession_lost", "corner", "throw_in", "free_kick"):
                    start = j
                    break
                if i - j >= 6:
                    start = max(0, i - 5)
                    break
            add(start, i + 1, t, i)
        elif t == "keeper_save":
            start = max(0, i - 5)
            for j in range(i, -1, -1):
                if types[j] == "shot":
                    start = max(0, j - 2)
                    break
            add(start, i + 1, t, i)
        elif t == "goal_line_clearance":
            start = max(0, i - 3)
            add(start, i + 1, t, i)
        elif t in ("disallowed_goal", "var"):
            start = max(0, i - 6)
            add(start, min(n, i + 2), t, i)
        elif t == "throw_in":
            end = i + 1
            for terminal in ("goal", "foul", "shot", "keeper_save"):
                if terminal in types[i:]:
                    end = types.index(terminal, i) + 1
                    break
            add(i, end, t, i)
        elif t == "corner":
            end = i + 1
            if "goal" in types[i:]:
                end = types.index("goal", i) + 1
            elif "keeper_save" in types[i:]:
                end = types.index("keeper_save", i) + 1
            else:
                end = min(n, i + 6)
            add(max(0, i - 1), end, t, i)
        elif t == "shot" and "goal" not in types[i:]:
            add(max(0, i - 4), min(n, i + 2), t, i)

    if not windows:
        windows.append(AnchorWindow(0, n, types[-1], n - 1))
    return windows
