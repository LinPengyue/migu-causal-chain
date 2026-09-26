"""仅几何分段（无模版打分），供 timeline_highlights + GNN 重打分。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

ANCHOR_TYPES = frozenset(
    {
        "goal",
        "disallowed_goal",
        "var",
        "red_card",
        "penalty",
    }
)


@dataclass
class GeoSegment:
    t0_ms: int
    t1_ms: int
    i0: int
    i1: int
    types: List[str]
    source: str  # "anchor" | "sliding"
    anchor_i: int | None = None


def segment_anchor_geom(
    events: List[Dict[str, Any]],
    *,
    pre_ms: int = 120_000,
    post_ms: int = 60_000,
    min_events: int = 2,
) -> List[GeoSegment]:
    out: List[GeoSegment] = []
    seen: set[Tuple[int, int]] = set()
    n = len(events)
    if n == 0:
        return out
    times = [int(e["t_ms"]) for e in events]
    types = [e["type"] for e in events]

    for i, e in enumerate(events):
        if e["type"] not in ANCHOR_TYPES:
            continue
        t = int(e["t_ms"])
        t0, t1 = t - pre_ms, t + post_ms
        i0 = next((k for k in range(n) if times[k] >= t0), 0)
        i1 = next((k for k in range(n - 1, -1, -1) if times[k] <= t1), n - 1)
        if i1 < i0 or i1 - i0 + 1 < min_events:
            continue
        key = (i0, i1)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            GeoSegment(
                t0_ms=times[i0],
                t1_ms=times[i1],
                i0=i0,
                i1=i1,
                types=types[i0 : i1 + 1],
                source="anchor",
                anchor_i=i,
            )
        )
    return out


def segment_sliding_geom(
    events: List[Dict[str, Any]],
    *,
    window_ms: int = 180_000,
    step_ms: int = 90_000,
    min_events: int = 2,
    merge_mode: str = "legacy",
) -> List[GeoSegment]:
    """滑窗几何提案。

    merge_mode:
      - legacy: 连续 overlap 的 raw windows 合并成更长 segment（原行为）
      - none:   每个 raw window 独立保留，交给后续 score/filter/dedupe
    """
    if not events:
        return []
    mode = (merge_mode or "legacy").strip().lower()
    if mode not in ("legacy", "none"):
        raise ValueError(f"unsupported sliding merge_mode={merge_mode!r}; use legacy|none")

    t_min = int(events[0]["t_ms"])
    t_max = int(events[-1]["t_ms"])
    times = [int(e["t_ms"]) for e in events]
    types = [e["type"] for e in events]
    raw: List[GeoSegment] = []
    start = t_min
    while start <= t_max:
        end = start + window_ms
        i0 = next((k for k in range(len(events)) if times[k] >= start), 0)
        i1 = next(
            (k for k in range(len(events) - 1, -1, -1) if times[k] <= end),
            len(events) - 1,
        )
        if i1 >= i0 and i1 - i0 + 1 >= min_events:
            raw.append(
                GeoSegment(
                    t0_ms=times[i0],
                    t1_ms=times[i1],
                    i0=i0,
                    i1=i1,
                    types=types[i0 : i1 + 1],
                    source="sliding",
                    anchor_i=None,
                )
            )
        start += step_ms

    if not raw:
        return []
    if mode == "none":
        return raw

    merged: List[GeoSegment] = [raw[0]]
    for s in raw[1:]:
        prev = merged[-1]
        overlap = not (s.t0_ms > prev.t1_ms or s.t1_ms < prev.t0_ms)
        if overlap:
            i0 = min(prev.i0, s.i0)
            i1 = max(prev.i1, s.i1)
            merged[-1] = GeoSegment(
                t0_ms=times[i0],
                t1_ms=times[i1],
                i0=i0,
                i1=i1,
                types=types[i0 : i1 + 1],
                source="sliding",
                anchor_i=None,
            )
        else:
            merged.append(s)
    return merged
