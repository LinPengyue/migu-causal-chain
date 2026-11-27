"""抽取候选打分。"""

from __future__ import annotations

from typing import List

from causal_chain6.extract.align import AlignmentCandidate
from causal_chain6.schema.rules import RulesContext


def score_alignment(
    cand: AlignmentCandidate,
    event_types: List[str],
    ctx: RulesContext,
) -> float:
    """对齐全局 event 索引上的子序列打分。"""
    idx = cand.indices
    if not idx:
        return 0.0
    sub = [event_types[i] for i in idx if 0 <= i < len(event_types)]
    if not sub:
        return 0.0

    score = cand.coverage
    if cand.exact:
        score += 0.35
    elif cand.suffix_match:
        score += 0.15

    check = ctx.check_transitions(cand.template_id, sub)
    if check["allowed"]:
        score += 0.15
    else:
        score -= 0.35

    if check["exact_canonical_match"]:
        score += 0.1

    # 偏好更短、更贴近 canonical 长度
    extra = len(sub) - len(cand.pattern)
    if extra > 0:
        score -= min(0.25, 0.04 * extra)

    return max(0.0, min(1.5, score))


def rank_alignments(
    candidates: List[AlignmentCandidate],
    event_types: List[str],
    ctx: RulesContext,
    *,
    top_k: int = 5,
) -> List[tuple[float, AlignmentCandidate]]:
    scored = [(score_alignment(c, event_types, ctx), c) for c in candidates]
    scored.sort(key=lambda x: -x[0])
    return scored[:top_k]
