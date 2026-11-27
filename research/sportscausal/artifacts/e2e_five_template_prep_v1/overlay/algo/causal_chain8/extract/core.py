"""因果链事件抽取主入口：长序列 → 规范子序列。"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from causal_chain2.event_io import ensure_event_ids

from causal_chain8.extract.anchors import detect_anchor_windows
from causal_chain8.extract.align import align_all_templates
from causal_chain8.extract.refine_llm import refine_extraction_llm
from causal_chain8.io.extraction_result import ExtractionResult
from causal_chain8.extract.score import rank_alignments
from causal_chain8.schema.rules import RulesContext


def _slice_events(events: List[Dict[str, Any]], indices: List[int], *, prefix: str) -> List[Dict[str, Any]]:
    out = []
    for j, i in enumerate(indices):
        ev = copy.deepcopy(events[i])
        ev["order"] = j
        out.append(ev)
    return ensure_event_ids(out, prefix=prefix)


def extract_causal_events(
    events: List[Dict[str, Any]],
    *,
    profile: Dict[str, Any],
    template_hint: Optional[str] = None,
    prefix: str = "ext",
    model=None,
    processor=None,
    device: str = "cuda",
) -> ExtractionResult:
    if not events:
        return ExtractionResult(method="empty")

    ctx = RulesContext.from_profile(profile)
    types = [str(e.get("type", "")) for e in events]
    extract_cfg = profile.get("extract") or {}
    max_window = int(extract_cfg.get("max_window", 12))
    use_llm = bool(extract_cfg.get("llm_refine")) and model is not None

    all_ranked: List[tuple[float, Any]] = []
    windows = detect_anchor_windows(types, max_window=max_window)

    template_filter: Optional[List[str]] = None
    if template_hint:
        template_filter = [template_hint]

    for win in windows:
        sub_types = types[win.start : win.end]
        cands = align_all_templates(
            sub_types,
            ctx,
            local_offset=win.start,
            template_ids=template_filter,
        )
        ranked = rank_alignments(cands, types, ctx, top_k=5)
        all_ranked.extend(ranked)

    if not all_ranked and template_hint:
        cands = align_all_templates(types, ctx, template_ids=[template_hint])
        all_ranked = rank_alignments(cands, types, ctx, top_k=5)

    if not all_ranked:
        indices = list(range(len(events)))
        sub = _slice_events(events, indices, prefix=prefix)
        return ExtractionResult(
            events_extracted=sub,
            extracted_indices=indices,
            method="fallback_full",
            score=0.1,
        )

    all_ranked.sort(key=lambda x: -x[0])
    best_score, best = all_ranked[0]
    margin = best_score - all_ranked[1][0] if len(all_ranked) > 1 else 1.0

    indices = list(best.indices)
    method = "canonical_align"

    if use_llm and margin < float(extract_cfg.get("llm_margin", 0.15)):
        refined = refine_extraction_llm(
            events,
            all_ranked[:5],
            model=model,
            processor=processor,
            device=device,
        )
        if refined:
            indices = refined
            method = "llm_refine"

    extracted = _slice_events(events, indices, prefix=prefix)
    sub_types = [str(e.get("type", "")) for e in extracted]
    check = ctx.check_transitions(best.template_id, sub_types)

    return ExtractionResult(
        events_extracted=extracted,
        extracted_indices=indices,
        template_hint=best.template_id,
        canonical_pattern=list(best.pattern),
        method=method,
        score=best_score,
        transitions_ok=check["allowed"],
        exact_canonical=check["exact_canonical_match"],
        candidate_templates=[c.template_id for _, c in all_ranked[:5]],
        margin=margin,
    )
