"""chain4 规则排序（业务骨架 soft_match）。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from causal_chain8.rules.robust import (
    apply_robust_scores,
    robust_enabled,
    scoring_view,
)
from causal_chain8.schema.rules import RulesContext
from causal_chain8.schema.templates import (
    ALL_TEMPLATE_IDS,
    CHAIN4_TEMPLATES,
    get_chain_templates,
    templates_in_category,
)


def _rules_ctx(profile: Dict[str, Any]) -> RulesContext:
    return RulesContext.from_profile(profile)


def _match_types(event_types: List[str], profile: Optional[Dict[str, Any]]) -> List[str]:
    if robust_enabled(profile):
        return scoring_view(event_types, profile)
    return list(event_types)


def find_canonical_matches(
    event_types: List[str],
    ctx: RulesContext,
    *,
    candidate_ids: Optional[List[str]] = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    cands = candidate_ids or list(ALL_TEMPLATE_IDS)
    scored: List[tuple[float, str, str]] = []
    for tid in cands:
        s = ctx.soft_match_score(tid, event_types)
        if s <= 0:
            continue
        best_seq = ""
        for seq in ctx.canonical_sequences.get(tid, [])[:3]:
            best_seq = " → ".join(seq)
            break
        scored.append((s, tid, best_seq))
    scored.sort(reverse=True)
    out: List[Dict[str, Any]] = []
    for score, tid, seq in scored[:top_k]:
        out.append(
            {
                "chain_template_id": tid,
                "match_score": round(score, 4),
                "best_canonical": seq,
                "transitions_ok": ctx.consecutive_pairs_allowed(tid, event_types)
                if len(event_types) >= 2
                else True,
            }
        )
    return out


def filter_by_transitions(
    event_types: List[str],
    ctx: RulesContext,
    candidate_ids: Optional[List[str]] = None,
) -> List[str]:
    cands = candidate_ids or list(ALL_TEMPLATE_IDS)
    if len(event_types) < 2:
        return list(cands)
    return [tid for tid in cands if ctx.consecutive_pairs_allowed(tid, event_types)]


def rank_candidates_rule(
    event_types: List[str],
    candidate_ids: List[str],
    ctx: RulesContext,
    llm_scores: Optional[Dict[str, float]] = None,
    *,
    profile: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    view = _match_types(event_types, profile)
    ranked: List[Dict[str, Any]] = []
    for tid in candidate_ids:
        soft = ctx.soft_match_score(tid, view)
        llm_s = float((llm_scores or {}).get(tid, soft))
        check = ctx.check_transitions(tid, view)
        bonus = 0.0
        if check["exact_canonical_match"]:
            bonus += 0.25
        if check["allowed"]:
            bonus += 0.1
        else:
            bonus -= 0.1
        if check.get("length_ok"):
            bonus += 0.05
        ranked.append(
            {
                "chain_template_id": tid,
                "llm_score": round(llm_s, 4),
                "critic_score": round(0.35 * llm_s + 0.65 * soft + bonus, 4),
                "soft_score": round(soft, 4),
                "transitions_ok": check["allowed"],
                "exact_canonical": check["exact_canonical_match"],
                "illegal_pairs": check["illegal_pairs"],
                "length_ok": check.get("length_ok", True),
            }
        )
    ranked.sort(key=lambda x: -x["critic_score"])
    return apply_robust_scores(ranked, event_types, profile=profile)


def global_rule_shortlist(
    event_types: List[str],
    *,
    profile: Dict[str, Any],
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    ctx = _rules_ctx(profile)
    view = _match_types(event_types, profile)
    best = ctx.best_template(view, top_k=max(top_k * 3, 15))
    if best:
        best = apply_robust_scores(best, event_types, profile=profile)
        return best[:top_k]
    # fallback
    return rank_candidates_rule(
        event_types, list(ALL_TEMPLATE_IDS), ctx, profile=profile
    )[:top_k]


def rule_top1(event_types: List[str], *, profile: Dict[str, Any]) -> str:
    ranked = global_rule_shortlist(event_types, profile=profile, top_k=1)
    return ranked[0]["chain_template_id"] if ranked else "outcome_other"


def infer_category_from_events(event_types: List[str]) -> str:
    if not event_types:
        return "outcome"
    end = event_types[-1]
    if end == "disallowed_goal":
        return "correction"
    if "var" in event_types and end in ("disallowed_goal", "free_kick", "offside", "penalty"):
        return "correction"
    if end == "own_goal" or "own_goal" in event_types:
        return "special"
    if end in ("goal", "header_goal", "red_card", "second_yellow_red") or "penalty" in event_types:
        return "outcome"
    if end == "keeper_save" or "goal_line_clearance" in event_types:
        return "danger"
    if end in ("shot", "corner", "cross") and "goal" not in event_types and "own_goal" not in event_types:
        return "danger"
    return "special"


def format_tool_context_v4(
    event_types: List[str],
    category: str,
    ctx: RulesContext,
    *,
    global_ranked: Optional[List[Dict[str, Any]]] = None,
) -> str:
    in_cat = templates_in_category(category)
    templates = get_chain_templates()
    lines = [
        f"## Tool：大类 `{category}` 内模版（共 {len(in_cat)}）",
        "## Tool：业务骨架 soft 排序（chain4）",
    ]
    ranked = global_ranked or ctx.best_template(event_types, top_k=5)
    for i, r in enumerate(ranked, 1):
        tid = r["chain_template_id"]
        zh = templates.get(tid, {}).get("label_zh", tid)
        mx = templates.get(tid, {}).get("max_len", "?")
        flag = "✓" if r.get("transitions_ok", True) else "✗"
        lines.append(
            f"{i}. `{tid}` score={r.get('critic_score', r.get('soft_score'))} "
            f"{flag} max_len={mx} | {zh}"
        )
    lines.append("\n## 长度建议")
    for tid in in_cat[:8]:
        meta = templates.get(tid, {})
        lines.append(
            f"- `{tid}`: {meta.get('label_zh')} 长度 {meta.get('min_len')}-{meta.get('max_len')}；"
            f"{meta.get('description', '')}"
        )
    return "\n".join(lines)
