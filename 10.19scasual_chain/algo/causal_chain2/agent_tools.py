"""智能体 Tool：模板定义、合法转移、CANONICAL 匹配（无 LLM）。"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from causal_chain2.chain_rules import (
    CANONICAL_SEQUENCES,
    consecutive_pairs_allowed,
    sequence_matches_template,
)
from causal_chain2.chain_schema import ALL_TEMPLATE_IDS, CHAIN_TEMPLATES, EVENT_TYPES
from causal_chain2.prompts_classify import templates_in_category


def event_types_from_events(events: List[Dict[str, Any]]) -> List[str]:
    return [str(e.get("type", "")) for e in events]


def tool_get_template_def(template_id: str) -> Dict[str, Any]:
    meta = CHAIN_TEMPLATES.get(template_id, {})
    seqs = CANONICAL_SEQUENCES.get(template_id, [])
    return {
        "chain_template_id": template_id,
        "chain_category": meta.get("category", ""),
        "label_zh": meta.get("label_zh", template_id),
        "description": meta.get("description", ""),
        "canonical_sequences": [" → ".join(s) for s in seqs],
    }


def tool_list_templates_by_category(category: str) -> List[Dict[str, Any]]:
    return [tool_get_template_def(tid) for tid in templates_in_category(category)]


def tool_check_transitions(template_id: str, event_types: List[str]) -> Dict[str, Any]:
    if len(event_types) < 2:
        return {
            "chain_template_id": template_id,
            "allowed": len(event_types) <= 1,
            "illegal_pairs": [],
            "exact_canonical_match": sequence_matches_template(template_id, event_types),
        }
    ok = consecutive_pairs_allowed(template_id, event_types)
    illegal: List[str] = []
    if template_id in CANONICAL_SEQUENCES:
        from causal_chain2.chain_rules import ALLOWED_TRANSITIONS

        allowed = ALLOWED_TRANSITIONS.get(template_id, set())
        for a, b in zip(event_types, event_types[1:]):
            if (a, b) not in allowed:
                illegal.append(f"{a}→{b}")
    return {
        "chain_template_id": template_id,
        "allowed": ok,
        "illegal_pairs": illegal,
        "exact_canonical_match": sequence_matches_template(template_id, event_types),
    }


def _prefix_match_score(seq: List[str], event_types: List[str]) -> float:
    """event_types 是否为 seq 的前缀或等于 seq。"""
    if not event_types:
        return 0.0
    if event_types == seq:
        return 1.0
    if len(event_types) <= len(seq) and seq[: len(event_types)] == event_types:
        return 0.7 + 0.3 * (len(event_types) / len(seq))
    # 最长公共前缀比例
    common = 0
    for a, b in zip(event_types, seq):
        if a == b:
            common += 1
        else:
            break
    if common == 0:
        return 0.0
    return 0.4 * common / max(len(event_types), len(seq))


def tool_find_canonical_matches(
    event_types: List[str],
    *,
    candidate_ids: List[str] | None = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    cands = candidate_ids or list(ALL_TEMPLATE_IDS)
    scored: List[Tuple[float, str, str]] = []
    for tid in cands:
        best = 0.0
        best_seq = ""
        for seq in CANONICAL_SEQUENCES.get(tid, []):
            s = _prefix_match_score(seq, event_types)
            if sequence_matches_template(tid, event_types):
                s = 1.0
            if s > best:
                best = s
                best_seq = " → ".join(seq)
        if best > 0:
            scored.append((best, tid, best_seq))
    scored.sort(reverse=True)
    out: List[Dict[str, Any]] = []
    for score, tid, seq in scored[:top_k]:
        out.append(
            {
                "chain_template_id": tid,
                "match_score": round(score, 4),
                "best_canonical": seq,
                "transitions_ok": consecutive_pairs_allowed(tid, event_types)
                if len(event_types) >= 2
                else True,
            }
        )
    return out


def tool_filter_by_transitions(
    event_types: List[str],
    candidate_ids: List[str] | None = None,
) -> List[str]:
    cands = candidate_ids or list(ALL_TEMPLATE_IDS)
    if len(event_types) < 2:
        return list(cands)
    return [tid for tid in cands if consecutive_pairs_allowed(tid, event_types)]


def infer_category_from_events(event_types: List[str]) -> str:
    """规则推断 chain_category（Planner 失败或对照用）。"""
    if not event_types:
        return "outcome"
    end = event_types[-1]
    if end == "disallowed_goal":
        return "correction"
    if "var" in event_types:
        if end in ("disallowed_goal", "free_kick", "offside", "penalty"):
            return "correction"
    if end in ("goal", "red_card", "second_yellow_red") or "penalty" in event_types:
        return "outcome"
    if end == "keeper_save" or "goal_line_clearance" in event_types:
        return "danger"
    if end in ("shot", "corner", "cross") and "goal" not in event_types:
        return "danger"
    return "special"


def _canon_base_scores(event_types: List[str], candidate_ids: List[str]) -> Dict[str, float]:
    scores: Dict[str, float] = {}
    for tid in candidate_ids:
        canon = tool_find_canonical_matches(event_types, candidate_ids=[tid], top_k=1)
        scores[tid] = float(canon[0]["match_score"]) if canon else 0.1
    return scores


def global_rule_shortlist(
    event_types: List[str],
    *,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """全库 Tool 排序（不受 Planner 大类限制）。"""
    trans = tool_filter_by_transitions(event_types)
    if not trans:
        trans = list(ALL_TEMPLATE_IDS)
    scores = _canon_base_scores(event_types, trans)
    return rank_candidates_rule(event_types, trans, scores)[:top_k]


def format_global_shortlist_context(
    event_types: List[str],
    ranked: List[Dict[str, Any]],
) -> str:
    lines = [
        "## Tool：全库规则排序 top（含 CANONICAL + 转移校验）",
    ]
    for i, r in enumerate(ranked, 1):
        tid = r["chain_template_id"]
        d = tool_get_template_def(tid)
        flag = "✓" if r["transitions_ok"] else "✗"
        ex = "精确匹配" if r.get("exact_canonical") else ""
        lines.append(
            f"{i}. `{tid}` critic={r['critic_score']} {flag} {ex} | "
            f"{d['label_zh']}"
        )
    return "\n".join(lines)


def format_tool_context(
    event_types: List[str],
    category: str,
    *,
    extra_ranked: List[Dict[str, Any]] | None = None,
) -> str:
    """汇总 Tool 输出，注入 Classifier / Critic prompt。"""
    in_cat = templates_in_category(category)
    trans_ok = tool_filter_by_transitions(event_types, in_cat)
    canonical = tool_find_canonical_matches(event_types, candidate_ids=in_cat, top_k=5)
    lines = [
        f"## Tool：大类 `{category}` 内模板（共 {len(in_cat)}）",
        f"## Tool：相邻转移合法候选（{len(trans_ok)}）",
        ", ".join(f"`{t}`" for t in trans_ok) if trans_ok else "（无，可能序列过短或非法）",
        "",
        "## Tool：CANONICAL 相似样例（top）",
    ]
    if extra_ranked:
        lines.append(format_global_shortlist_context(event_types, extra_ranked))
        lines.append("")
    if canonical:
        for item in canonical:
            flag = "✓转移" if item["transitions_ok"] else "✗转移"
            lines.append(
                f"- `{item['chain_template_id']}` score={item['match_score']} "
                f"{flag} | {item['best_canonical']}"
            )
    else:
        lines.append("- （无显著匹配）")
    lines.append("\n## Tool：各类定义摘要")
    for tid in in_cat[:12]:
        d = tool_get_template_def(tid)
        lines.append(f"- `{tid}`: {d['label_zh']} — {d['description']}")
    if len(in_cat) > 12:
        lines.append(f"- …共 {len(in_cat)} 个")
    return "\n".join(lines)


def rank_candidates_rule(
    event_types: List[str],
    candidate_ids: List[str],
    llm_scores: Dict[str, float] | None = None,
) -> List[Dict[str, Any]]:
    """Critic 规则打分：LLM 分 + 转移合法 + CANONICAL 匹配。"""
    if llm_scores is None:
        llm_scores = _canon_base_scores(event_types, candidate_ids)
    ranked: List[Dict[str, Any]] = []
    for tid in candidate_ids:
        if tid not in llm_scores:
            llm_scores[tid] = 0.1
        check = tool_check_transitions(tid, event_types)
        canon = tool_find_canonical_matches(event_types, candidate_ids=[tid], top_k=1)
        canon_score = canon[0]["match_score"] if canon else 0.0
        base = float(llm_scores[tid])
        bonus = 0.0
        if check["exact_canonical_match"]:
            bonus += 0.35
        elif canon_score >= 0.7:
            bonus += 0.2
        if check["allowed"]:
            bonus += 0.15
        else:
            bonus -= 0.45
        ranked.append(
            {
                "chain_template_id": tid,
                "llm_score": round(base, 4),
                "critic_score": round(base + bonus, 4),
                "transitions_ok": check["allowed"],
                "exact_canonical": check["exact_canonical_match"],
                "illegal_pairs": check["illegal_pairs"],
            }
        )
    ranked.sort(key=lambda x: -x["critic_score"])
    return ranked
