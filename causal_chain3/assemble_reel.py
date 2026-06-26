"""集锦排序、去重、时长预算。"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from causal_chain3.schema import HighlightChain

# 模板优先级（越大越靠前）
TEMPLATE_PRIORITY: Dict[str, int] = {
    "corner_cross_goal": 90,
    "rebound_follow_up_goal": 88,
    "turnover_counter_goal": 86,
    "penalty_scored_chain": 85,
    "deflection_goal_chain": 84,
    "outcome_other": 80,
    "goal_disallowed_chain": 82,
    "var_overturn_chain": 81,
    "var_penalty_cancelled_chain": 80,
    "red_card_decision_chain": 78,
    "goal_line_extreme_save_chain": 70,
    "keeper_spill_danger_chain": 65,
    "shot_save_chain": 60,
    "shot_post_bar_chain": 55,
    "second_phase_after_frame_chain": 50,
    "throw_in_build_up_chain": 45,
    "quick_restart_set_piece_chain": 45,
    "own_goal_causal_chain": 83,
}


def time_iou(a0: int, a1: int, b0: int, b1: int) -> float:
    inter = max(0, min(a1, b1) - max(a0, b0))
    union = max(a1, b1) - min(a0, b0)
    if union <= 0:
        return 0.0
    return inter / union


def _score(chain: HighlightChain) -> float:
    pri = TEMPLATE_PRIORITY.get(chain.chain_template_id, 40)
    return pri + chain.confidence * 10 + chain.margin * 5


def dedupe_chains(
    chains: List[HighlightChain],
    *,
    iou_thresh: float = 0.5,
) -> List[HighlightChain]:
    order = sorted(chains, key=lambda c: -_score(c))
    kept: List[HighlightChain] = []
    for c in order:
        drop = False
        for k in kept:
            if c.chain_template_id != k.chain_template_id:
                continue
            if time_iou(c.t0_ms, c.t1_ms, k.t0_ms, k.t1_ms) >= iou_thresh:
                drop = True
                break
        if not drop:
            kept.append(c)
    return kept


def assemble_reel(
    chains: List[HighlightChain],
    *,
    iou_dedupe_thresh: float = 0.5,
    min_margin: float = 0.0,
    min_confidence: float = 0.0,
    template_whitelist: Optional[Set[str]] = None,
    max_clips: Optional[int] = None,
    max_total_duration_ms: Optional[int] = None,
) -> List[HighlightChain]:
    filtered = [
        c
        for c in chains
        if c.margin >= min_margin and c.confidence >= min_confidence
    ]
    if template_whitelist:
        filtered = [c for c in filtered if c.chain_template_id in template_whitelist]

    deduped = dedupe_chains(filtered, iou_thresh=iou_dedupe_thresh)
    deduped.sort(key=lambda c: (c.t0_ms, -_score(c)))

    if max_clips is not None:
        deduped = deduped[:max_clips]

    if max_total_duration_ms is not None:
        out: List[HighlightChain] = []
        total = 0
        for c in sorted(deduped, key=lambda x: -_score(x)):
            dur = max(c.t1_ms - c.t0_ms, 0)
            if total + dur > max_total_duration_ms:
                continue
            out.append(c)
            total += dur
        out.sort(key=lambda c: c.t0_ms)
        return out

    return deduped
