"""干扰事件形态（C）：从交付链抽取可插入的噪声类型，不复制专项集序列。"""

from __future__ import annotations

from typing import Iterable, List, Sequence, Set

INTERFERENCE_EVENTS: Set[str] = {
    "substitution",
    "injury_time",
    "yellow_card",
    "controversy",
}

# 可插入的噪声（必须在交付里真实出现过才用于合成）
SYNTH_INSERTABLE = ("substitution", "yellow_card", "injury_time")


def has_interference(types: Sequence[str]) -> bool:
    s = set(types)
    return bool(s & INTERFERENCE_EVENTS)


def inject_interference(
    types: Sequence[str],
    noise: str,
    *,
    at: str = "mid",
) -> List[str]:
    """在干净主链中插入一种噪声，生成形态增强序列。"""
    seq = [str(t) for t in types if t]
    if not seq or noise not in SYNTH_INSERTABLE:
        return seq
    if at == "after_first" and len(seq) >= 2:
        i = 1
    elif at == "before_last" and len(seq) >= 2:
        i = len(seq) - 1
    else:
        i = max(1, len(seq) // 2)
    out = list(seq)
    out.insert(i, noise)
    return out


def observed_interference(pool: Iterable[Sequence[str]]) -> Set[str]:
    seen: Set[str] = set()
    for types in pool:
        seen |= set(types) & set(SYNTH_INSERTABLE)
    return seen
