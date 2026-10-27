"""窗内事件对齐 chain4 canonical，并扩展为更长核心链。"""

from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

from causal_chain8.schema.rules import RulesContext
from causal_chain8.schema.skeletons import canonical_sequences_map
from causal_chain8.schema.templates import CHAIN4_TEMPLATES, template_label_zh

from causal_chain8.highlight_schema import ChainEdge, ChainEvent, HighlightChain

# 扩展核心链时优先保留的事件
_KEEP_TYPES: Set[str] = {
    "pass",
    "dribble_past",
    "dribble_breakthrough",
    "successful_tackle",
    "assist",
    "interception",
    "possession_lost",
    "cross",
    "aerial_won",
    "corner",
    "throw_in",
    "free_kick",
    "foul",
    "shot",
    "header_shot",
    "keeper_save",
    "goal_line_clearance",
    "goal",
    "header_goal",
    "penalty",
    "var",
    "offside",
    "disallowed_goal",
    "red_card",
    "controversy",
}


def _lcs_alignment(seq: List[str], pattern: List[str]) -> List[int]:
    indices: List[int] = []
    j = 0
    for i, t in enumerate(seq):
        if j < len(pattern) and t == pattern[j]:
            indices.append(i)
            j += 1
    if j < len(pattern):
        return []
    return indices


def _best_canonical_alignment(
    event_types: List[str], template_id: str
) -> Tuple[List[str], List[int], float]:
    best_pat: List[str] = []
    best_idx: List[int] = []
    best_score = -1.0
    for pat in canonical_sequences_map().get(template_id, []):
        idx = _lcs_alignment(event_types, pat)
        if not idx:
            continue
        score = len(idx) / len(pat)
        if event_types == pat:
            score = 1.0
        if score > best_score:
            best_score = score
            best_pat = pat
            best_idx = idx
    return best_pat, best_idx, best_score


def _role_for_event(etype: str, pos: int, total: int) -> str:
    if etype in ("goal", "own_goal", "header_goal", "disallowed_goal"):
        return "outcome"
    if etype in ("red_card", "second_yellow_red"):
        return "outcome"
    if etype in ("var", "controversy", "offside"):
        return "correction"
    if etype in ("penalty", "corner", "free_kick", "throw_in"):
        return "set_piece"
    if etype in ("shot", "header_shot"):
        return "shot"
    if etype == "keeper_save":
        return "save"
    if etype == "goal_line_clearance":
        return "clearance"
    if pos == 0:
        return "build_up"
    if pos == total - 1:
        return "outcome"
    return "build_up"


def _expand_core_indices(
    event_types: List[str],
    align_idx: List[int],
    *,
    max_core: int = 8,
    pad: int = 3,
) -> List[int]:
    """在 canonical 对齐两端扩展有意义事件，形成更长核心链。"""
    if not align_idx:
        # 无对齐：取窗内 keep 类型，最多 max_core，偏末端
        keep = [i for i, t in enumerate(event_types) if t in _KEEP_TYPES]
        if not keep:
            return list(range(min(len(event_types), max_core)))
        if len(keep) <= max_core:
            return keep
        return keep[-max_core:]

    lo, hi = min(align_idx), max(align_idx)
    selected: Set[int] = set(align_idx)

    # 向左扩展
    left = lo - 1
    added = 0
    while left >= 0 and added < pad and len(selected) < max_core:
        if event_types[left] in _KEEP_TYPES:
            selected.add(left)
            added += 1
        left -= 1

    # 向右扩展
    right = hi + 1
    added = 0
    while right < len(event_types) and added < pad and len(selected) < max_core:
        if event_types[right] in _KEEP_TYPES:
            selected.add(right)
            added += 1
        right += 1

    # 中间空洞：对齐区间内全部 keep 事件纳入
    for i in range(lo, hi + 1):
        if event_types[i] in _KEEP_TYPES:
            selected.add(i)

    ordered = sorted(selected)
    if len(ordered) <= max_core:
        return ordered
    # 超长时保留末端（更靠近终局）
    return ordered[-max_core:]


def build_chain_from_window(
    *,
    clip_id: str,
    template_id: str,
    events_window: List[Dict[str, Any]],
    i0: int,
    anchor_i: int,
    anchor_type: str,
    confidence: float = 0.0,
    margin: float = 0.0,
    fast_path: bool = False,
    profile: Dict[str, Any] | None = None,
    max_core_events: int = 8,
) -> HighlightChain:
    types = [e["type"] for e in events_window]
    meta = CHAIN4_TEMPLATES.get(template_id, {})
    pat, align_idx, align_score = _best_canonical_alignment(types, template_id)

    core_idx = _expand_core_indices(
        types, align_idx, max_core=max_core_events, pad=3
    )
    aligned_set = set(align_idx or [])
    core_set = set(core_idx)

    chain_events: List[ChainEvent] = []
    for order, local_i in enumerate(core_idx):
        ev = events_window[local_i]
        chain_events.append(
            ChainEvent(
                order=order,
                type=ev["type"],
                t_ms=int(ev["t_ms"]),
                event_id=str(ev.get("event_id", "")),
                role=_role_for_event(ev["type"], order, len(core_idx)),
                global_index=i0 + local_i,
            )
        )

    context_events: List[ChainEvent] = []
    for local_i, ev in enumerate(events_window):
        if local_i in core_set:
            continue
        context_events.append(
            ChainEvent(
                order=local_i,
                type=ev["type"],
                t_ms=int(ev["t_ms"]),
                event_id=str(ev.get("event_id", "")),
                role="context",
                global_index=i0 + local_i,
            )
        )

    edges: List[ChainEdge] = []
    for a, b in zip(range(len(chain_events) - 1), range(1, len(chain_events))):
        edges.append(ChainEdge(src=a, dst=b, rel="temporal_next"))
        edges.append(ChainEdge(src=a, dst=b, rel="causal_leads_to"))

    ctx = RulesContext.from_profile(profile)
    check = ctx.check_transitions(template_id, [e.type for e in chain_events])
    t0 = chain_events[0].t_ms if chain_events else int(events_window[0]["t_ms"])
    t1 = chain_events[-1].t_ms if chain_events else int(events_window[-1]["t_ms"])
    local_anchor = max(0, min(anchor_i - i0, len(events_window) - 1))

    return HighlightChain(
        clip_id=clip_id,
        chain_template_id=template_id,
        chain_label_zh=template_label_zh(template_id) or meta.get("label_zh", template_id),
        chain_category=str(meta.get("category", "special")),
        t0_ms=t0,
        t1_ms=t1,
        anchor_type=anchor_type,
        anchor_t_ms=int(events_window[local_anchor]["t_ms"]),
        events=chain_events,
        context_events=context_events,
        edges=edges,
        confidence=confidence,
        margin=margin,
        fast_path=fast_path,
        validation={
            "canonical_pattern": " → ".join(pat) if pat else "",
            "align_score": round(align_score if align_idx else 0.3, 4),
            "core_expanded": True,
            "core_size": len(chain_events),
            "align_size": len(align_idx or []),
            "exact_canonical": check.get("exact_canonical_match", False),
            "transitions_ok": check.get("allowed", False),
            "illegal_pairs": check.get("illegal_pairs", []),
            "rules_backend": "causal_chain8",
            "aligned_in_core": sorted(aligned_set & core_set),
        },
    )


def narrative_from_chain(chain: HighlightChain) -> str:
    types = " → ".join(e.type for e in chain.events)
    if chain.validation.get("exact_canonical"):
        return f"{chain.chain_label_zh}：{types}"
    return f"{chain.chain_label_zh}（{types}）"
