"""Hybrid LLM 分类 + 可选叙事生成。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from causal_chain2.agent_classify import AgentTrace, classify_events_agent
from causal_chain2.agent_tools import global_rule_shortlist
from causal_chain2.llm_qwen import generate_text
from causal_chain2.prompts_agent import SYSTEM_AGENT

from causal_chain3.discover import ChainCandidate
from causal_chain3.extract_chain import build_chain_from_window, narrative_from_chain
from causal_chain3.schema import HighlightChain


def _events_with_order(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for i, e in enumerate(events):
        d = dict(e)
        d.setdefault("order", i)
        out.append(d)
    return out


def classify_candidate_hybrid(
    model,
    processor,
    events: List[Dict[str, Any]],
    candidate: ChainCandidate,
    *,
    device: str,
    max_new_tokens: int = 512,
    ambiguous_margin: float = 0.12,
) -> Tuple[str, float, float, bool, AgentTrace]:
    """对候选窗做 hybrid 分类，返回 template_id, confidence, margin, fast_path, trace。"""
    sub = _events_with_order(events[candidate.i0 : candidate.i1 + 1])
    tr = AgentTrace()
    result = classify_events_agent(
        model,
        processor,
        sub,
        device=device,
        max_new_tokens=max_new_tokens,
        trace=tr,
        ambiguous_margin=ambiguous_margin,
    )
    return (
        result.chain_template_id,
        result.confidence,
        result.margin,
        tr.fast_path,
        tr,
    )


def hint_templates_from_rules(
    events: List[Dict[str, Any]], candidates: List[ChainCandidate]
) -> Dict[int, str]:
    """第一轮规则 top1 作为 discover 扩展 hint（可选第二遍 discover）。"""
    hints: Dict[int, str] = {}
    for cand in candidates:
        types = [e["type"] for e in events[cand.i0 : cand.i1 + 1]]
        ranked = global_rule_shortlist(types, top_k=1)
        if ranked:
            hints[cand.anchor_i] = ranked[0]["chain_template_id"]
    return hints


def refine_chain_narrative_llm(
    model,
    processor,
    chain: HighlightChain,
    *,
    device: str,
    max_new_tokens: int = 128,
) -> str:
    """LLM 生成集锦解说一句话。"""
    types = " → ".join(e.type for e in chain.events)
    prompt = f"""## 任务
为以下足球因果链写一句中文集锦解说（15～30字），不要 JSON，不要引号。

链类型：{chain.chain_label_zh}（{chain.chain_template_id}）
事件序列：{types}

只输出解说文本。"""
    text = generate_text(
        model,
        processor,
        SYSTEM_AGENT,
        prompt,
        device,
        max_new_tokens=max_new_tokens,
        do_sample=False,
    )
    return text.strip().split("\n")[0][:80]


def build_refined_chain(
    *,
    clip_id: str,
    events: List[Dict[str, Any]],
    candidate: ChainCandidate,
    template_id: str,
    confidence: float,
    margin: float,
    fast_path: bool,
    model=None,
    processor=None,
    device: str = "cuda",
    use_llm_narrative: bool = True,
    max_new_tokens: int = 512,
) -> HighlightChain:
    window = events[candidate.i0 : candidate.i1 + 1]
    chain = build_chain_from_window(
        clip_id=clip_id,
        template_id=template_id,
        events_window=window,
        i0=candidate.i0,
        anchor_i=candidate.anchor_i,
        anchor_type=candidate.anchor_type,
        confidence=confidence,
        margin=margin,
        fast_path=fast_path,
    )
    if use_llm_narrative and model is not None and processor is not None:
        try:
            chain.narrative_zh = refine_chain_narrative_llm(
                model,
                processor,
                chain,
                device=device,
                max_new_tokens=128,
            )
        except Exception:
            chain.narrative_zh = narrative_from_chain(chain)
    else:
        chain.narrative_zh = narrative_from_chain(chain)
    return chain
