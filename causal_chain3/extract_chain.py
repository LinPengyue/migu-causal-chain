"""窗内事件对齐 canonical 骨架，构建链节点与边。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from causal_chain2.agent_tools import tool_check_transitions
from causal_chain2.chain_rules import CANONICAL_SEQUENCES
from causal_chain2.chain_schema import CHAIN_TEMPLATES

from causal_chain3.schema import ChainEdge, ChainEvent, HighlightChain


def _lcs_alignment(seq: List[str], pattern: List[str]) -> List[int]:
    """在 seq 中按顺序匹配 pattern，返回 pattern 各位置在 seq 中的索引。"""
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
    """返回最佳 canonical 模式及其在窗内的索引对齐。"""
    best_pat: List[str] = []
    best_idx: List[int] = []
    best_score = -1.0
    for pat in CANONICAL_SEQUENCES.get(template_id, []):
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


def _role_for_event(etype: str, template_id: str, pos: int, total: int) -> str:
    if etype in ("goal", "header_goal", "disallowed_goal"):
        return "outcome"
    if etype in ("red_card", "second_yellow_red"):
        return "outcome"
    if etype in ("var", "controversy", "offside", "free_kick"):
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
) -> HighlightChain:
    """从候选窗构建 HighlightChain（对齐 canonical 子序列）。"""
    types = [e["type"] for e in events_window]
    meta = CHAIN_TEMPLATES.get(template_id, {})
    pat, align_idx, align_score = _best_canonical_alignment(types, template_id)

    chain_events: List[ChainEvent] = []
    context_events: List[ChainEvent] = []
    aligned_global: set[int] = set()

    if align_idx:
        for order, local_i in enumerate(align_idx):
            ev = events_window[local_i]
            global_i = i0 + local_i
            aligned_global.add(local_i)
            chain_events.append(
                ChainEvent(
                    order=order,
                    type=ev["type"],
                    t_ms=int(ev["t_ms"]),
                    event_id=str(ev.get("event_id", "")),
                    role=_role_for_event(
                        ev["type"], template_id, order, len(align_idx)
                    ),
                    global_index=global_i,
                )
            )
    else:
        # 对齐失败：保留全窗作为链事件
        for order, ev in enumerate(events_window):
            chain_events.append(
                ChainEvent(
                    order=order,
                    type=ev["type"],
                    t_ms=int(ev["t_ms"]),
                    event_id=str(ev.get("event_id", "")),
                    role=_role_for_event(
                        ev["type"], template_id, order, len(events_window)
                    ),
                    global_index=i0 + order,
                )
            )
        align_score = 0.3

    for local_i, ev in enumerate(events_window):
        if local_i in aligned_global:
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

    check = tool_check_transitions(template_id, [e.type for e in chain_events])
    t0 = chain_events[0].t_ms if chain_events else int(events_window[0]["t_ms"])
    t1 = chain_events[-1].t_ms if chain_events else int(events_window[-1]["t_ms"])

    return HighlightChain(
        clip_id=clip_id,
        chain_template_id=template_id,
        chain_label_zh=meta.get("label_zh", template_id),
        chain_category=meta.get("category", "special"),
        t0_ms=t0,
        t1_ms=t1,
        anchor_type=anchor_type,
        anchor_t_ms=int(events_window[anchor_i - i0]["t_ms"]),
        events=chain_events,
        context_events=context_events,
        edges=edges,
        confidence=confidence,
        margin=margin,
        fast_path=fast_path,
        validation={
            "canonical_pattern": " → ".join(pat) if pat else "",
            "align_score": round(align_score, 4),
            "exact_canonical": check.get("exact_canonical_match", False),
            "transitions_ok": check.get("allowed", False),
            "illegal_pairs": check.get("illegal_pairs", []),
        },
    )


def narrative_from_chain(chain: HighlightChain) -> str:
    """规则生成一句话叙事（无 LLM）。"""
    types = " → ".join(e.type for e in chain.events)
    if chain.validation.get("exact_canonical"):
        return f"{chain.chain_label_zh}：{types}"
    return f"{chain.chain_label_zh}（{types}）"
