"""chain4 hybrid agent（规则 + 可选 LLM / VLM）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from causal_chain2.llm_classify import ClassifyResult, _empty_probs, _normalize_probs
from causal_chain2.llm_json import extract_json_object
from causal_chain2.llm_qwen import generate_text

from causal_chain4.io.eval_record import EvalRecord
from causal_chain4.llm.constants import SYSTEM_AGENT_V4
from causal_chain4.llm.prompts import prompt_classifier_v4
from causal_chain4.llm.vlm_clip import VlmClipResult, analyze_clip_optional
from causal_chain4.rules.rank import (
    format_tool_context_v4,
    global_rule_shortlist,
    rank_candidates_rule,
)
from causal_chain4.schema.rules import RulesContext
from causal_chain4.schema.templates import ALL_TEMPLATE_IDS, CHAIN4_TEMPLATES

_FALLBACK = "outcome_other"
_OTHER_FAMILY = {
    "outcome_other",
    "individual_breakthrough_goal",
    "team_buildup_goal",
    "corner_coop_goal",
}


@dataclass
class AgentV4Trace:
    global_ranked: List[Dict[str, Any]] = field(default_factory=list)
    classifier_candidates: List[Dict[str, Any]] = field(default_factory=list)
    vlm: Optional[VlmClipResult] = None
    mode: str = "rule_only"
    rationale: str = ""


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


def _result(tid: str, score: float, category: str, *, rationale: str) -> ClassifyResult:
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
        parse_ok=True,
    )


def classify_record_v4(
    rec: EvalRecord,
    *,
    profile: Dict[str, Any],
    model=None,
    processor=None,
    device: str = "cuda",
    max_new_tokens: int = 512,
    video_root: Optional[str] = None,
    trace: Optional[AgentV4Trace] = None,
) -> ClassifyResult:
    tr = trace if trace is not None else AgentV4Trace()
    events = rec.events_core or rec.events_normalized
    types = [str(e.get("type", "")) for e in events]
    if not types:
        probs = _empty_probs()
        probs[_FALLBACK] = 1.0
        return ClassifyResult(
            chain_template_id=_FALLBACK,
            chain_category="outcome",
            confidence=0.05,
            margin=0.05,
            probs=probs,
            rationale="empty_events",
            parse_ok=False,
        )

    ctx = RulesContext.from_profile(profile)
    global_ranked = global_rule_shortlist(types, profile=profile, top_k=5)
    tr.global_ranked = global_ranked

    llm_cfg = profile.get("llm") or {}
    vlm_cfg = profile.get("vlm") or {}
    margin_th = float(llm_cfg.get("ambiguous_margin", 0.12))

    if global_ranked and len(global_ranked) >= 2:
        rule_margin = global_ranked[0]["critic_score"] - global_ranked[1]["critic_score"]
    elif global_ranked:
        rule_margin = 1.0
    else:
        rule_margin = 0.0

    use_llm = bool(llm_cfg.get("enabled")) and model is not None and processor is not None
    use_vlm = bool(vlm_cfg.get("enabled")) and model is not None and processor is not None

    if not use_llm and not use_vlm:
        tr.mode = "rule_only"
        best = global_ranked[0]
        tid = best["chain_template_id"]
        tr.rationale = f"rule_only margin={rule_margin:.3f}"
        return _result(tid, best["critic_score"], CHAIN4_TEMPLATES[tid]["category"], rationale=tr.rationale)

    shortlist = [r["chain_template_id"] for r in global_ranked[:5]] or [_FALLBACK]
    category = CHAIN4_TEMPLATES.get(shortlist[0], {}).get("category", "outcome")

    vlm_tid: Optional[str] = None
    if use_vlm and rule_margin < margin_th:
        tr.vlm = analyze_clip_optional(
            rec,
            model=model,
            processor=processor,
            device=device,
            video_root=video_root,
            rule_top3=shortlist[:3],
            max_frames=int(vlm_cfg.get("max_frames", 3)),
            max_new_tokens=max_new_tokens,
        )
        if tr.vlm and tr.vlm.suggested_template_id in ALL_TEMPLATE_IDS:
            vlm_tid = tr.vlm.suggested_template_id

    if use_llm and rule_margin < margin_th:
        tr.mode = "hybrid_llm"
        tool_ctx = format_tool_context_v4(types, category, ctx, global_ranked=global_ranked)
        raw = generate_text(
            model,
            processor,
            SYSTEM_AGENT_V4,
            prompt_classifier_v4(rec, events, category, tool_ctx),
            device,
            max_new_tokens=max_new_tokens,
            do_sample=False,
        )
        candidates = _parse_top3(raw, shortlist)
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
        merged = rank_candidates_rule(types, shortlist, ctx, llm_scores)
        tid = merged[0]["chain_template_id"]
        if vlm_tid:
            tr.mode = "hybrid_llm_vlm"
            for r in merged:
                if r["chain_template_id"] == vlm_tid:
                    r["critic_score"] += 0.08
            merged.sort(key=lambda x: -x["critic_score"])
            tid = merged[0]["chain_template_id"]
        tr.rationale = f"hybrid margin={rule_margin:.3f}"
        return _result(tid, merged[0]["critic_score"], CHAIN4_TEMPLATES[tid]["category"], rationale=tr.rationale)

    tr.mode = "rule_fast" if not use_vlm else "rule_vlm_skip"
    best = global_ranked[0]
    tid = vlm_tid or best["chain_template_id"]
    score = best["critic_score"]
    if vlm_tid and vlm_tid != best["chain_template_id"]:
        score = best["critic_score"] + 0.05
    tr.rationale = f"fast_path margin={rule_margin:.3f}"
    return _result(tid, score, CHAIN4_TEMPLATES[tid]["category"], rationale=tr.rationale)
