"""chain4_agent 分类 + 可选叙事生成。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from causal_chain2.llm_qwen import generate_text

from causal_chain8.io.eval_record import EvalRecord
from causal_chain8.llm.agent import AgentV4Trace, classify_record_v4
from causal_chain8.llm.constants import SYSTEM_AGENT_V4
from causal_chain8.rules.rank import global_rule_shortlist

from causal_chain8.discover import ChainCandidate
from causal_chain8.extract_chain import build_chain_from_window, narrative_from_chain
from causal_chain8.highlight_schema import HighlightChain


def _events_with_order(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for i, e in enumerate(events):
        d = dict(e)
        d.setdefault("order", i)
        d.setdefault("event_id", d.get("event_id") or f"e{i:04d}")
        out.append(d)
    return out


def classify_candidate_chain4(
    model,
    processor,
    events: List[Dict[str, Any]],
    candidate: ChainCandidate,
    *,
    profile: Dict[str, Any],
    device: str,
    max_new_tokens: int = 512,
    match_id: str = "match",
) -> Tuple[str, float, float, bool, AgentV4Trace]:
    sub = _events_with_order(events[candidate.i0 : candidate.i1 + 1])
    types = [e["type"] for e in sub]
    rec = EvalRecord(
        annotation_id=candidate.candidate_id,
        match_id=match_id,
        gold_template_id="",
        gold_category="",
        gold_label_zh="",
        gold_category_zh="",
        events_raw=list(sub),
        events_normalized=list(sub),
        events_extracted=list(sub),
    )
    tr = AgentV4Trace()
    result = classify_record_v4(
        rec,
        profile=profile,
        model=model,
        processor=processor,
        device=device,
        max_new_tokens=max_new_tokens,
        trace=tr,
    )
    tid = result.chain_template_id
    conf = float(result.confidence)
    margin = float(result.margin)

    # 窗内已有进球/吹掉时，禁止落成中柱链；改用规则 shortlist 中第一个合理模板
    critical = {"goal", "header_goal", "disallowed_goal", "penalty", "red_card"}
    has_crit = any(t in critical for t in types)
    if has_crit and tid == "shot_post_bar_chain":
        ranked = global_rule_shortlist(types, profile=profile, top_k=5)
        for r in ranked:
            alt = r["chain_template_id"]
            if alt != "shot_post_bar_chain":
                tid = alt
                conf = float(r.get("critic_score", conf))
                margin = max(margin, 0.15)
                tr.rationale = (tr.rationale or "") + "|override_post_bar_for_critical"
                break

    fast = tr.mode in ("rule_only", "rule_fast")
    return tid, conf, margin, fast, tr


def hint_templates_from_rules(
    events: List[Dict[str, Any]],
    candidates: List[ChainCandidate],
    *,
    profile: Dict[str, Any],
) -> Dict[int, str]:
    hints: Dict[int, str] = {}
    for cand in candidates:
        types = [e["type"] for e in events[cand.i0 : cand.i1 + 1]]
        ranked = global_rule_shortlist(types, profile=profile, top_k=1)
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
    types = " → ".join(e.type for e in chain.events)
    prompt = f"""## 任务
为以下足球因果链写一句中文集锦解说（15～30字），不要 JSON，不要引号。

链类型：{chain.chain_label_zh}（{chain.chain_template_id}）
事件序列：{types}

只输出解说文本。"""
    text = generate_text(
        model,
        processor,
        SYSTEM_AGENT_V4,
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
    profile: Optional[Dict[str, Any]] = None,
    model=None,
    processor=None,
    device: str = "cuda",
    use_llm_narrative: bool = True,
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
        profile=profile,
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
