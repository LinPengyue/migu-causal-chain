"""层 B 之后：按时间排序已选片段（选片权在 select_moments，此处不做分数淘汰）。"""

from __future__ import annotations

from typing import List, Optional

from causal_chain8.highlight_schema import HighlightChain


def time_iou(a0: int, a1: int, b0: int, b1: int) -> float:
    inter = max(0, min(a1, b1) - max(a0, b0))
    union = max(a1, b1) - min(a0, b0)
    if union <= 0:
        return 0.0
    return inter / union


def assemble_reel(
    chains: List[HighlightChain],
    *,
    max_clips: Optional[int] = None,
    max_total_duration_ms: Optional[int] = None,
) -> List[HighlightChain]:
    """因果链已与选片 1:1 对应；仅按时间排序与可选预算裁剪。"""
    selected = sorted(chains, key=lambda c: c.t0_ms)
    if max_clips is not None and len(selected) > max_clips:
        # T0 优先保留（validation.selection.tier）
        def _tier_rank(c: HighlightChain) -> int:
            tier = (c.validation or {}).get("selection", {}).get("tier", "T2")
            return {"T0": 0, "T1": 1, "T2": 2}.get(tier, 3)

        ordered = sorted(selected, key=lambda c: (_tier_rank(c), c.t0_ms))
        selected = sorted(ordered[:max_clips], key=lambda c: c.t0_ms)

    if max_total_duration_ms is not None:
        out: List[HighlightChain] = []
        total = 0
        for c in selected:
            dur = max(c.t1_ms - c.t0_ms, 0)
            if out and total + dur > max_total_duration_ms:
                tier = (c.validation or {}).get("selection", {}).get("tier")
                if tier != "T0":
                    continue
            out.append(c)
            total += dur
        selected = out

    return selected
