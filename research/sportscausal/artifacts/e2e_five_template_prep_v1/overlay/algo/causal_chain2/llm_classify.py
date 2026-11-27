"""方案 A（增强）：两阶段 LLM 闭集分类 + 可选单阶段。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from causal_chain2.a3_schema import A3Record, events_for_graph
from causal_chain2.chain_schema import ALL_TEMPLATE_IDS, CHAIN_TEMPLATES
from causal_chain2.llm_json import extract_json_object
from causal_chain2.llm_qwen import generate_text
from causal_chain2.prompts_classify import (
    CATEGORIES,
    SYSTEM_PROMPT_CLASSIFY,
    templates_in_category,
    user_prompt_category,
    user_prompt_classify_single_stage,
    user_prompt_template,
)

_FALLBACK_ID = "outcome_other"


@dataclass
class ClassifyResult:
    chain_template_id: str
    chain_category: str = ""
    confidence: float = 0.0
    prob_top2: float = 0.0
    margin: float = 0.0
    probs: Dict[str, float] = field(default_factory=dict)
    rationale: str = ""
    parse_ok: bool = True
    category_rationale: str = ""


def _empty_probs() -> Dict[str, float]:
    return {tid: 0.0 for tid in ALL_TEMPLATE_IDS}


def _normalize_probs(scores: Dict[str, float]) -> Dict[str, float]:
    out = _empty_probs()
    for tid, v in scores.items():
        if tid in out:
            out[tid] = max(0.0, float(v))
    total = sum(out.values())
    if total <= 0:
        out[_FALLBACK_ID] = 1.0
        return out
    return {tid: v / total for tid, v in out.items()}


def _parse_template_response(
    text: str,
    *,
    allowed: List[str] | None = None,
) -> Tuple[str, float, float, Dict[str, float], str, bool]:
    obj = extract_json_object(text)
    if not obj or not isinstance(obj, dict):
        probs = _empty_probs()
        probs[_FALLBACK_ID] = 1.0
        return _FALLBACK_ID, 0.05, 0.0, probs, "parse_fail", False

    tid = str(obj.get("chain_template_id", "")).strip()
    allow = set(allowed or ALL_TEMPLATE_IDS)
    if tid not in allow:
        tid = allowed[0] if allowed else _FALLBACK_ID

    try:
        p1 = float(obj.get("confidence", 0.5))
    except (TypeError, ValueError):
        p1 = 0.5
    p1 = max(0.0, min(1.0, p1))

    alt_scores: Dict[str, float] = {}
    alts = obj.get("alternatives") or []
    if isinstance(alts, list):
        for item in alts[:2]:
            if not isinstance(item, dict):
                continue
            aid = str(item.get("chain_template_id", "")).strip()
            if aid not in allow or aid == tid:
                continue
            try:
                alt_scores[aid] = max(0.0, min(1.0, float(item.get("confidence", 0.0))))
            except (TypeError, ValueError):
                continue

    raw_scores = {tid: p1, **alt_scores}
    probs = _normalize_probs(raw_scores)
    p1n = probs.get(tid, p1)
    others = sorted((v for k, v in probs.items() if k != tid), reverse=True)
    p2 = others[0] if others else 0.0
    rationale = str(obj.get("rationale", "")).strip()
    return tid, p1n, p2, probs, rationale, True


def _parse_category_response(text: str) -> Tuple[str, float, str, bool]:
    obj = extract_json_object(text)
    if not obj or not isinstance(obj, dict):
        return "outcome", 0.05, "parse_fail", False
    cat = str(obj.get("chain_category", "")).strip()
    if cat not in CATEGORIES:
        cat = "outcome"
    try:
        conf = float(obj.get("confidence", 0.5))
    except (TypeError, ValueError):
        conf = 0.5
    conf = max(0.0, min(1.0, conf))
    rationale = str(obj.get("rationale", "")).strip()
    return cat, conf, rationale, True


def classify_events_two_stage(
    model,
    processor,
    events: List[Dict[str, Any]],
    *,
    device: str,
    max_new_tokens: int = 512,
) -> ClassifyResult:
    if len(events) < 1:
        probs = _empty_probs()
        probs[_FALLBACK_ID] = 1.0
        return ClassifyResult(
            chain_template_id=_FALLBACK_ID,
            chain_category="outcome",
            confidence=0.05,
            prob_top2=0.0,
            margin=0.05,
            probs=probs,
            rationale="empty_events",
            parse_ok=False,
        )

    cat_raw = generate_text(
        model,
        processor,
        SYSTEM_PROMPT_CLASSIFY,
        user_prompt_category(events),
        device,
        max_new_tokens=min(max_new_tokens, 256),
        do_sample=False,
    )
    category, _cat_conf, cat_rationale, cat_ok = _parse_category_response(cat_raw)
    allowed = templates_in_category(category)
    if not allowed:
        allowed = list(ALL_TEMPLATE_IDS)

    tmpl_raw = generate_text(
        model,
        processor,
        SYSTEM_PROMPT_CLASSIFY,
        user_prompt_template(events, category),
        device,
        max_new_tokens=max_new_tokens,
        do_sample=False,
    )
    tid, p1, p2, probs, rationale, tmpl_ok = _parse_template_response(
        tmpl_raw, allowed=allowed
    )
    if CHAIN_TEMPLATES.get(tid, {}).get("category") != category and allowed:
        tid = allowed[0]
        probs = _normalize_probs({tid: p1})

    return ClassifyResult(
        chain_template_id=tid,
        chain_category=category,
        confidence=p1,
        prob_top2=p2,
        margin=p1 - p2,
        probs=probs,
        rationale=rationale,
        parse_ok=cat_ok and tmpl_ok,
        category_rationale=cat_rationale,
    )


def classify_events_single_stage(
    model,
    processor,
    events: List[Dict[str, Any]],
    *,
    device: str,
    max_new_tokens: int = 512,
) -> ClassifyResult:
    if len(events) < 1:
        probs = _empty_probs()
        probs[_FALLBACK_ID] = 1.0
        return ClassifyResult(
            chain_template_id=_FALLBACK_ID,
            chain_category="outcome",
            confidence=0.05,
            prob_top2=0.0,
            margin=0.05,
            probs=probs,
            rationale="empty_events",
            parse_ok=False,
        )

    raw = generate_text(
        model,
        processor,
        SYSTEM_PROMPT_CLASSIFY,
        user_prompt_classify_single_stage(events),
        device,
        max_new_tokens=max_new_tokens,
        do_sample=False,
    )
    tid, p1, p2, probs, rationale, ok = _parse_template_response(raw)
    cat = CHAIN_TEMPLATES.get(tid, {}).get("category", "")
    return ClassifyResult(
        chain_template_id=tid,
        chain_category=cat,
        confidence=p1,
        prob_top2=p2,
        margin=p1 - p2,
        probs=probs,
        rationale=rationale,
        parse_ok=ok,
    )


def classify_events(
    model,
    processor,
    events: List[Dict[str, Any]],
    *,
    device: str,
    max_new_tokens: int = 512,
    two_stage: bool = True,
) -> ClassifyResult:
    if two_stage:
        return classify_events_two_stage(
            model, processor, events, device=device, max_new_tokens=max_new_tokens
        )
    return classify_events_single_stage(
        model, processor, events, device=device, max_new_tokens=max_new_tokens
    )


def classify_record(
    model,
    processor,
    rec: A3Record,
    *,
    device: str,
    max_new_tokens: int = 512,
    two_stage: bool = True,
) -> ClassifyResult:
    return classify_events(
        model,
        processor,
        events_for_graph(rec),
        device=device,
        max_new_tokens=max_new_tokens,
        two_stage=two_stage,
    )


def label_zh(template_id: str) -> str:
    return CHAIN_TEMPLATES.get(template_id, {}).get("label_zh", template_id)
