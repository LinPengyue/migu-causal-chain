"""CANONICAL 对齐：LCS / 后缀 / relaxed 前缀。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from causal_chain6.schema.rules import RulesContext


@dataclass
class AlignmentCandidate:
    template_id: str
    pattern: List[str]
    indices: List[int]
    coverage: float
    exact: bool
    suffix_match: bool


def lcs_alignment(seq: List[str], pattern: List[str]) -> List[int]:
    indices: List[int] = []
    j = 0
    for i, t in enumerate(seq):
        if j < len(pattern) and t == pattern[j]:
            indices.append(i)
            j += 1
    if j < len(pattern):
        return []
    return indices


def suffix_indices(seq: List[str], pattern: List[str]) -> Optional[List[int]]:
    n = len(pattern)
    if len(seq) < n:
        return None
    start = len(seq) - n
    if seq[start:] == pattern:
        return list(range(start, len(seq)))
    return None


def _prefix_types_for(ctx: RulesContext, template_id: str) -> Set[str]:
    ov = ctx.overlays.get(template_id) or {}
    return set(ov.get("prefix_allowed") or [])


def align_template_in_window(
    types: List[str],
    template_id: str,
    ctx: RulesContext,
    *,
    local_offset: int = 0,
) -> List[AlignmentCandidate]:
    out: List[AlignmentCandidate] = []
    seqs = ctx.canonical_sequences.get(template_id, [])
    prefix_allowed = _prefix_types_for(ctx, template_id)

    for pat in seqs:
        if not pat:
            continue
        idx = suffix_indices(types, pat)
        suffix = True
        if idx is None:
            idx = lcs_alignment(types, pat)
            suffix = False
        if not idx:
            continue
        coverage = len(idx) / len(pat)
        exact = types == pat or (suffix and coverage >= 1.0)
        if suffix and len(idx) < len(types):
            prefix = types[: idx[0]]
            if prefix_allowed and prefix and not all(p in prefix_allowed for p in prefix):
                if ctx.mode != "relaxed_prefix":
                    coverage *= 0.85
        global_idx = [local_offset + i for i in idx]
        out.append(
            AlignmentCandidate(
                template_id=template_id,
                pattern=list(pat),
                indices=global_idx,
                coverage=coverage,
                exact=exact,
                suffix_match=suffix,
            )
        )
    return out


def align_all_templates(
    types: List[str],
    ctx: RulesContext,
    *,
    local_offset: int = 0,
    template_ids: Optional[List[str]] = None,
) -> List[AlignmentCandidate]:
    from causal_chain6.schema.templates import ALL_TEMPLATE_IDS

    cands = template_ids or list(ALL_TEMPLATE_IDS)
    all_c: List[AlignmentCandidate] = []
    for tid in cands:
        all_c.extend(align_template_in_window(types, tid, ctx, local_offset=local_offset))
    return all_c
