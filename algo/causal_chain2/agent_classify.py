"""方案 C：Planner → Tool → Classifier → Critic → Final（默认规则主导混合模式）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from causal_chain2.a3_schema import A3Record, events_for_graph
from causal_chain2.agent_tools import (
    event_types_from_events,
    format_global_shortlist_context,
    format_tool_context,
    global_rule_shortlist,
    infer_category_from_events,
    rank_candidates_rule,
    tool_check_transitions,
    tool_filter_by_transitions,
    tool_find_canonical_matches,
)
from causal_chain2.chain_schema import ALL_TEMPLATE_IDS, CHAIN_TEMPLATES
from causal_chain2.llm_classify import ClassifyResult, _empty_probs, _normalize_probs, label_zh
from causal_chain2.llm_json import extract_json_object
from causal_chain2.llm_qwen import generate_text
from causal_chain2.prompts_agent import (
    SYSTEM_AGENT,
    prompt_classifier_top3,
    prompt_critic,
    prompt_final,
    prompt_planner,
)
from causal_chain2.prompts_classify import CATEGORIES, templates_in_category

_FALLBACK = "outcome_other"


@dataclass
class AgentTrace:
    chain_category: str = ""
    planner_rationale: str = ""
    tool_context: str = ""
    global_ranked: List[Dict[str, Any]] = field(default_factory=list)
    classifier_candidates: List[Dict[str, Any]] = field(default_factory=list)
    critic_ranked: List[Dict[str, Any]] = field(default_factory=list)
    rule_ranked: List[Dict[str, Any]] = field(default_factory=list)
    final_raw: str = ""
    steps_ok: bool = True
    fast_path: bool = False
    mode: str = "hybrid"


def _parse_planner(text: str) -> tuple[str, str, bool]:
    obj = extract_json_object(text)
    if not obj:
        return "outcome", "parse_fail", False
    cat = str(obj.get("chain_category", "outcome")).strip()
    if cat not in CATEGORIES:
        cat = "outcome"
    return cat, str(obj.get("rationale", "")), True


def _parse_top3(text: str, allowed: List[str]) -> List[Dict[str, Any]]:
    obj = extract_json_object(text)
    allow = set(allowed)
    out: List[Dict[str, Any]] = []
    if not obj:
        return out
    items = obj.get("candidates") or obj.get("top3") or []
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        tid = str(it.get("chain_template_id", "")).strip()
        if tid not in allow:
            continue
        try:
            conf = float(it.get("confidence", 0.0))
        except (TypeError, ValueError):
            conf = 0.0
        out.append(
            {
                "chain_template_id": tid,
                "confidence": max(0.0, min(1.0, conf)),
                "rationale": str(it.get("rationale", "")),
            }
        )
    out.sort(key=lambda x: -x["confidence"])
    return out[:3]


def _parse_critic(text: str) -> List[Dict[str, Any]]:
    obj = extract_json_object(text)
    if not obj:
        return []
    items = obj.get("ranked") or []
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        tid = str(it.get("chain_template_id", "")).strip()
        if tid not in ALL_TEMPLATE_IDS:
            continue
        try:
            conf = float(it.get("confidence", 0.0))
        except (TypeError, ValueError):
            conf = 0.0
        out.append(
            {
                "chain_template_id": tid,
                "confidence": max(0.0, min(1.0, conf)),
                "accept": bool(it.get("accept", True)),
                "rationale": str(it.get("rationale", "")),
            }
        )
    return out[:3]


def _parse_final(text: str) -> tuple[str, float, Dict[str, float], str, bool]:
    obj = extract_json_object(text)
    if not obj:
        probs = _empty_probs()
        probs[_FALLBACK] = 1.0
        return _FALLBACK, 0.05, probs, "parse_fail", False
    tid = str(obj.get("chain_template_id", _FALLBACK)).strip()
    if tid not in ALL_TEMPLATE_IDS:
        tid = _FALLBACK
    try:
        p1 = float(obj.get("confidence", 0.5))
    except (TypeError, ValueError):
        p1 = 0.5
    p1 = max(0.0, min(1.0, p1))
    scores = {tid: p1}
    alts = obj.get("alternatives") or []
    if isinstance(alts, list):
        for a in alts[:2]:
            if isinstance(a, dict):
                aid = str(a.get("chain_template_id", "")).strip()
                if aid in ALL_TEMPLATE_IDS and aid != tid:
                    try:
                        scores[aid] = float(a.get("confidence", 0.0))
                    except (TypeError, ValueError):
                        pass
    probs = _normalize_probs(scores)
    p1n = probs.get(tid, p1)
    return tid, p1n, probs, str(obj.get("rationale", "")), True


def _result_from_rule(
    tid: str,
    score: float,
    category: str,
    *,
    rationale: str,
    parse_ok: bool = True,
    category_rationale: str = "",
    fast_path: bool = False,
) -> ClassifyResult:
    probs = _normalize_probs({tid: score})
    others = sorted((v for k, v in probs.items() if k != tid), reverse=True)
    p2 = others[0] if others else 0.0
    return ClassifyResult(
        chain_template_id=tid,
        chain_category=category,
        confidence=score,
        prob_top2=p2,
        margin=score - p2,
        probs=probs,
        rationale=rationale,
        parse_ok=parse_ok,
        category_rationale=category_rationale,
    )


def _rule_margin(ranked: List[Dict[str, Any]]) -> float:
    if not ranked:
        return 0.0
    if len(ranked) == 1:
        return 1.0
    return float(ranked[0]["critic_score"]) - float(ranked[1]["critic_score"])


def _merge_llm_rule_scores(
    event_types: List[str],
    shortlist: List[str],
    llm_scores: Dict[str, float],
    global_ranked: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """LLM top-3 分与全库规则分加权合并。"""
    rule_map = {r["chain_template_id"]: r["critic_score"] for r in global_ranked}
    merged: Dict[str, float] = {}
    for tid in shortlist:
        llm_s = llm_scores.get(tid, 0.0)
        rule_s = rule_map.get(tid, 0.0)
        merged[tid] = 0.35 * llm_s + 0.65 * rule_s
    return rank_candidates_rule(event_types, shortlist, merged)


def classify_events_agent_hybrid(
    model,
    processor,
    events: List[Dict[str, Any]],
    *,
    device: str,
    max_new_tokens: int = 512,
    trace: Optional[AgentTrace] = None,
    ambiguous_margin: float = 0.12,
) -> ClassifyResult:
    """规则主导：全库 Tool 排序 → 高置信直达 → 否则 LLM 仅在 top-5 内消歧。"""
    tr = trace if trace is not None else AgentTrace()
    tr.mode = "hybrid"
    types = event_types_from_events(events)
    if not types:
        probs = _empty_probs()
        probs[_FALLBACK] = 1.0
        return ClassifyResult(
            chain_template_id=_FALLBACK,
            chain_category="outcome",
            confidence=0.05,
            margin=0.05,
            probs=probs,
            parse_ok=False,
            rationale="empty_events",
        )

    global_ranked = global_rule_shortlist(types, top_k=5)
    tr.global_ranked = global_ranked
    category = (
        CHAIN_TEMPLATES[global_ranked[0]["chain_template_id"]]["category"]
        if global_ranked
        else infer_category_from_events(types)
    )
    tr.chain_category = category
    tr.planner_rationale = f"rule_category:{infer_category_from_events(types)}"

    margin = _rule_margin(global_ranked)
    if global_ranked and margin >= ambiguous_margin:
        best = global_ranked[0]
        tr.fast_path = True
        tr.rule_ranked = global_ranked
        return _result_from_rule(
            best["chain_template_id"],
            best["critic_score"],
            CHAIN_TEMPLATES[best["chain_template_id"]]["category"],
            rationale=f"rule_fast_path margin={margin:.3f}",
            category_rationale=tr.planner_rationale,
            fast_path=True,
        )

    shortlist = [r["chain_template_id"] for r in global_ranked[:5]]
    if not shortlist:
        trans = tool_filter_by_transitions(types)
        shortlist = trans[:5] if trans else [_FALLBACK]

    tr.tool_context = format_global_shortlist_context(types, global_ranked)
    cat_for_prompt = CHAIN_TEMPLATES[shortlist[0]]["category"]
    cls_raw = generate_text(
        model,
        processor,
        SYSTEM_AGENT,
        prompt_classifier_top3(
            events,
            cat_for_prompt,
            format_tool_context(types, cat_for_prompt, extra_ranked=global_ranked),
        ),
        device,
        max_new_tokens=max_new_tokens,
        do_sample=False,
    )
    candidates = _parse_top3(cls_raw, shortlist)
    if len(candidates) < 1:
        for r in global_ranked[:3]:
            candidates.append(
                {
                    "chain_template_id": r["chain_template_id"],
                    "confidence": r["critic_score"],
                    "rationale": "rule_fill",
                }
            )
    tr.classifier_candidates = candidates

    llm_scores = {c["chain_template_id"]: c["confidence"] for c in candidates}
    for tid in shortlist:
        llm_scores.setdefault(tid, 0.0)
    tr.rule_ranked = _merge_llm_rule_scores(types, shortlist, llm_scores, global_ranked)

    if tr.rule_ranked:
        best = tr.rule_ranked[0]
        tid = best["chain_template_id"]
        return _result_from_rule(
            tid,
            best["critic_score"],
            CHAIN_TEMPLATES[tid]["category"],
            rationale=f"hybrid_merge margin={margin:.3f}",
            category_rationale=tr.planner_rationale,
        )

    tid, conf, rationale = _FALLBACK, 0.1, "hybrid_empty"
    return _result_from_rule(tid, conf, category, rationale=rationale, parse_ok=False)


def classify_events_agent_full_llm(
    model,
    processor,
    events: List[Dict[str, Any]],
    *,
    device: str,
    max_new_tokens: int = 512,
    trace: Optional[AgentTrace] = None,
    skip_critic_llm: bool = False,
) -> ClassifyResult:
    """原 5 步全 LLM 路径（易因 Planner 锁大类而偏低，仅作对照）。"""
    tr = trace if trace is not None else AgentTrace()
    tr.mode = "full_llm"
    types = event_types_from_events(events)
    if not types:
        return classify_events_agent_hybrid(
            model, processor, events, device=device, max_new_tokens=max_new_tokens, trace=tr
        )

    plan_raw = generate_text(
        model,
        processor,
        SYSTEM_AGENT,
        prompt_planner(events),
        device,
        max_new_tokens=min(256, max_new_tokens),
        do_sample=False,
    )
    category, plan_rationale, plan_ok = _parse_planner(plan_raw)
    tr.chain_category = category
    tr.planner_rationale = plan_rationale
    tr.global_ranked = global_rule_shortlist(types, top_k=5)

    in_cat = templates_in_category(category)
    tr.tool_context = format_tool_context(
        types, category, extra_ranked=tr.global_ranked
    )

    cls_raw = generate_text(
        model,
        processor,
        SYSTEM_AGENT,
        prompt_classifier_top3(events, category, tr.tool_context),
        device,
        max_new_tokens=max_new_tokens,
        do_sample=False,
    )
    candidates = _parse_top3(cls_raw, in_cat)
    seen = {c["chain_template_id"] for c in candidates}
    for r in tr.global_ranked:
        tid = r["chain_template_id"]
        if tid in in_cat and tid not in seen and len(candidates) < 3:
            candidates.append(
                {
                    "chain_template_id": tid,
                    "confidence": r["critic_score"],
                    "rationale": "global_fill",
                }
            )
            seen.add(tid)
    tr.classifier_candidates = candidates

    llm_scores = {c["chain_template_id"]: c["confidence"] for c in candidates}
    tool_checks = [tool_check_transitions(c["chain_template_id"], types) for c in candidates]
    tr.rule_ranked = rank_candidates_rule(
        types, [c["chain_template_id"] for c in candidates], llm_scores
    )

    if skip_critic_llm:
        ranked = [
            {
                "chain_template_id": r["chain_template_id"],
                "confidence": r["critic_score"],
                "accept": r["transitions_ok"],
                "rationale": "rule_critic",
            }
            for r in tr.rule_ranked
        ]
    else:
        critic_raw = generate_text(
            model,
            processor,
            SYSTEM_AGENT,
            prompt_critic(events, candidates, tool_checks),
            device,
            max_new_tokens=min(384, max_new_tokens),
            do_sample=False,
        )
        ranked = _parse_critic(critic_raw) or [
            {
                "chain_template_id": r["chain_template_id"],
                "confidence": r["critic_score"],
                "accept": r["transitions_ok"],
                "rationale": "rule_critic_fallback",
            }
            for r in tr.rule_ranked
        ]
    tr.critic_ranked = ranked

    if tr.rule_ranked and tr.rule_ranked[0]["transitions_ok"]:
        best = tr.rule_ranked[0]
        return _result_from_rule(
            best["chain_template_id"],
            best["critic_score"],
            CHAIN_TEMPLATES[best["chain_template_id"]]["category"],
            rationale="full_llm_rule_final",
            parse_ok=plan_ok,
            category_rationale=plan_rationale,
        )

    final_pool = [r for r in ranked if r.get("accept", True)] or ranked
    final_raw = generate_text(
        model,
        processor,
        SYSTEM_AGENT,
        prompt_final(events, final_pool),
        device,
        max_new_tokens=min(256, max_new_tokens),
        do_sample=False,
    )
    tr.final_raw = final_raw
    tid, p1, probs, rationale, fin_ok = _parse_final(final_raw)
    if not fin_ok:
        best = tr.rule_ranked[0] if tr.rule_ranked else None
        if best:
            return _result_from_rule(
                best["chain_template_id"],
                best["critic_score"],
                CHAIN_TEMPLATES[best["chain_template_id"]]["category"],
                rationale="full_llm_fallback",
                parse_ok=False,
                category_rationale=plan_rationale,
            )
    others = sorted((v for k, v in probs.items() if k != tid), reverse=True)
    p2 = others[0] if others else 0.0
    return ClassifyResult(
        chain_template_id=tid,
        chain_category=CHAIN_TEMPLATES.get(tid, {}).get("category", category),
        confidence=p1,
        prob_top2=p2,
        margin=p1 - p2,
        probs=probs,
        rationale=rationale,
        parse_ok=plan_ok and fin_ok,
        category_rationale=plan_rationale,
    )


def classify_events_agent(
    model,
    processor,
    events: List[Dict[str, Any]],
    *,
    device: str,
    max_new_tokens: int = 512,
    trace: Optional[AgentTrace] = None,
    skip_critic_llm: bool = False,
    full_llm: bool = False,
    ambiguous_margin: float = 0.12,
) -> ClassifyResult:
    if full_llm:
        return classify_events_agent_full_llm(
            model,
            processor,
            events,
            device=device,
            max_new_tokens=max_new_tokens,
            trace=trace,
            skip_critic_llm=skip_critic_llm,
        )
    return classify_events_agent_hybrid(
        model,
        processor,
        events,
        device=device,
        max_new_tokens=max_new_tokens,
        trace=trace,
        ambiguous_margin=ambiguous_margin,
    )


def classify_record_agent(
    model,
    processor,
    rec: A3Record,
    *,
    device: str,
    max_new_tokens: int = 512,
    trace: Optional[AgentTrace] = None,
    skip_critic_llm: bool = False,
    full_llm: bool = False,
    ambiguous_margin: float = 0.12,
) -> ClassifyResult:
    return classify_events_agent(
        model,
        processor,
        events_for_graph(rec),
        device=device,
        max_new_tokens=max_new_tokens,
        trace=trace,
        skip_critic_llm=skip_critic_llm,
        full_llm=full_llm,
        ambiguous_margin=ambiguous_margin,
    )
