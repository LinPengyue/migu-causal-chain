"""chain4 拆条流水线：几何分段复用 chain2，窗级分类用 chain4_agent。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from causal_chain2.event_io import events_for_output
from causal_chain2.llm_classify import ClassifyResult
from causal_chain2.segmentation_geom import GeoSegment, segment_anchor_geom, segment_sliding_geom
from causal_chain2.timeline_highlights import (
    ScoredSegment,
    dedupe_same_template_iou,
    geom_to_dict,
    passes_margin,
    post_score_candidate_nms,
    scored_to_clip_dict,
    scored_to_dict,
    slice_events,
    sliding_supplements,
)
from causal_chain2.timeline_io import load_timeline_json

from causal_chain6.io.eval_record import EvalRecord
from causal_chain6.llm.agent import AgentV4Trace, classify_record_v4
from causal_chain6.schema.templates import CHAIN4_TEMPLATES, template_label_zh


def _events_to_eval_record(
    events: List[Dict[str, Any]],
    *,
    annotation_id: str,
    match_id: str,
) -> EvalRecord:
    return EvalRecord(
        annotation_id=annotation_id,
        match_id=match_id,
        gold_template_id="",
        gold_category="",
        gold_label_zh="",
        gold_category_zh="",
        events_raw=list(events),
        events_normalized=list(events),
        events_extracted=list(events),
    )


def _result_to_scored(seg: GeoSegment, result: ClassifyResult) -> ScoredSegment:
    tid = result.chain_template_id
    return ScoredSegment(
        t0_ms=seg.t0_ms,
        t1_ms=seg.t1_ms,
        i0=seg.i0,
        i1=seg.i1,
        event_types=list(seg.types),
        source=seg.source,
        pred_chain_template_id=tid,
        pred_chain_label_zh=template_label_zh(tid),
        prob_top1=float(result.confidence),
        prob_top2=float(result.prob_top2),
        margin=float(result.margin),
        probs=dict(result.probs),
    )


def score_segment_chain4(
    events: List[Dict[str, Any]],
    seg: GeoSegment,
    *,
    profile: Dict[str, Any],
    model=None,
    processor=None,
    device: str = "cuda",
    max_new_tokens: int = 512,
    max_events: Optional[int],
    match_id: str = "strip",
) -> ScoredSegment:
    """单窗：切事件 → causal_chain6.classify_record_v4。"""
    evs = slice_events(events, seg, max_events=max_events)
    for i, e in enumerate(evs):
        e.setdefault("order", i)
        e.setdefault("event_id", e.get("event_id") or f"{match_id}_e{i:04d}")
    rec = _events_to_eval_record(
        evs,
        annotation_id=f"seg_{seg.i0}_{seg.i1}",
        match_id=match_id,
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
    # 保证 category 来自 chain4 模板表
    if result.chain_template_id in CHAIN4_TEMPLATES:
        result.chain_category = CHAIN4_TEMPLATES[result.chain_template_id]["category"]
    return _result_to_scored(seg, result)


def finalize_strip_selection(
    *,
    anchor_scored: List[ScoredSegment],
    slide_scored: List[ScoredSegment],
    min_margin: float,
    min_prob_top1: float,
    iou_dedupe_thresh: float,
    iou_recall_thresh: float,
    use_sliding_recall: bool,
    template_whitelist: Optional[List[str]],
    sliding_post_nms: str = "off",
) -> List[ScoredSegment]:
    """从已打分 segment 池选出 final clips（anchor + sliding supplement + dedupe）。"""
    post_nms = (sliding_post_nms or "off").strip().lower()
    if post_nms not in ("off", "on"):
        raise ValueError(f"unsupported sliding_post_nms={sliding_post_nms!r}; use off|on")

    anchor_filtered = [
        s for s in anchor_scored if passes_margin(s, min_margin, min_prob_top1)
    ]
    if template_whitelist:
        allow = set(template_whitelist)
        anchor_filtered = [
            s for s in anchor_filtered if s.pred_chain_template_id in allow
        ]
    anchor_selected = dedupe_same_template_iou(anchor_filtered, iou_dedupe_thresh)

    sliding_selected: List[ScoredSegment] = []
    if use_sliding_recall:
        slide_filtered = [
            s for s in slide_scored if passes_margin(s, min_margin, min_prob_top1)
        ]
        if template_whitelist:
            allow = set(template_whitelist)
            slide_filtered = [
                s for s in slide_filtered if s.pred_chain_template_id in allow
            ]
        slide_supp = sliding_supplements(
            anchor_selected, slide_filtered, iou_recall_thresh=iou_recall_thresh
        )
        sliding_selected = dedupe_same_template_iou(slide_supp, iou_dedupe_thresh)

    combined = dedupe_same_template_iou(
        anchor_selected + sliding_selected, iou_dedupe_thresh
    )
    if post_nms == "on":
        from causal_chain6.schema.templates import CHAIN4_TEMPLATES

        cat_lookup = {
            tid: str((meta or {}).get("category") or "")
            for tid, meta in CHAIN4_TEMPLATES.items()
        }
        combined = post_score_candidate_nms(
            combined,
            cat_lookup=cat_lookup,
            iou_thresh=0.65,
            event_jaccard_thresh=0.60,
            score_eps=0.08,
        )
    return combined


def run_strip_highlights_events(
    *,
    events: List[Dict[str, Any]],
    match_id: str = "strip",
    profile: Dict[str, Any],
    model=None,
    processor=None,
    device: str = "cuda",
    max_new_tokens: int = 512,
    pre_ms: int,
    post_ms: int,
    window_ms: int,
    step_ms: int,
    min_margin: float,
    min_prob_top1: float,
    iou_dedupe_thresh: float,
    iou_recall_thresh: float,
    max_events: Optional[int],
    use_sliding_recall: bool,
    template_whitelist: Optional[List[str]],
    input_file: str = "",
    sliding_merge_mode: str = "legacy",
    sliding_post_nms: str = "off",
) -> Dict[str, Any]:
    """几何发现 + 窗级分类；输入为已加载的事件列表（供 prefix replay 使用）。"""
    events = list(events or [])
    # 分类侧：有模型则开 hybrid，否则纯规则（与 classify CLI 一致）
    profile = dict(profile)
    llm_cfg = dict(profile.get("llm") or {})
    if model is not None and processor is not None:
        llm_cfg["enabled"] = True
    else:
        llm_cfg["enabled"] = False
    profile["llm"] = llm_cfg
    merge_mode = (sliding_merge_mode or "legacy").strip().lower()
    post_nms = (sliding_post_nms or "off").strip().lower()
    if post_nms not in ("off", "on"):
        raise ValueError(f"unsupported sliding_post_nms={sliding_post_nms!r}; use off|on")

    if not events:
        return {
            "input_file": input_file,
            "event_count": 0,
            "config": {
                "backend": "chain4_agent",
                "profile": profile.get("name"),
                "llm_enabled": bool(llm_cfg.get("enabled")),
            },
            "stats": {
                "anchor_geom": 0,
                "anchor_scored": 0,
                "anchor_selected": 0,
                "sliding_geom": 0,
                "sliding_scored": 0,
                "sliding_selected": 0,
                "final_clips": 0,
            },
            "anchor_geom": [],
            "anchor_scored": [],
            "sliding_geom": [],
            "sliding_scored": [],
            "clips": [],
        }

    anchor_geom = segment_anchor_geom(events, pre_ms=pre_ms, post_ms=post_ms)
    anchor_geom_out = [geom_to_dict(g, f"a{i:02d}_geom") for i, g in enumerate(anchor_geom)]

    anchor_scored: List[ScoredSegment] = []
    anchor_scored_out: List[Dict[str, Any]] = []
    for i, g in enumerate(anchor_geom):
        pid = f"a{i:02d}"
        sc = score_segment_chain4(
            events,
            g,
            profile=profile,
            model=model,
            processor=processor,
            device=device,
            max_new_tokens=max_new_tokens,
            max_events=max_events,
            match_id=match_id,
        )
        anchor_scored.append(sc)
        anchor_scored_out.append(
            scored_to_dict(
                sc,
                pid,
                passes_margin=passes_margin(sc, min_margin, min_prob_top1),
            )
        )

    anchor_sel_ids = set()
    sliding_selected: List[ScoredSegment] = []
    slide_geom_out: List[Dict[str, Any]] = []
    slide_scored_out: List[Dict[str, Any]] = []
    slide_scored: List[ScoredSegment] = []
    if use_sliding_recall:
        slide_geom = segment_sliding_geom(
            events,
            window_ms=window_ms,
            step_ms=step_ms,
            merge_mode=merge_mode,
        )
        slide_geom_out = [
            geom_to_dict(g, f"s{i:02d}_geom") for i, g in enumerate(slide_geom)
        ]
        for i, g in enumerate(slide_geom):
            pid = f"s{i:02d}"
            sc = score_segment_chain4(
                events,
                g,
                profile=profile,
                model=model,
                processor=processor,
                device=device,
                max_new_tokens=max_new_tokens,
                max_events=max_events,
                match_id=match_id,
            )
            slide_scored.append(sc)
            slide_scored_out.append(
                scored_to_dict(
                    sc,
                    pid,
                    passes_margin=passes_margin(sc, min_margin, min_prob_top1),
                )
            )

    combined = finalize_strip_selection(
        anchor_scored=anchor_scored,
        slide_scored=slide_scored,
        min_margin=min_margin,
        min_prob_top1=min_prob_top1,
        iou_dedupe_thresh=iou_dedupe_thresh,
        iou_recall_thresh=iou_recall_thresh,
        use_sliding_recall=use_sliding_recall,
        template_whitelist=template_whitelist,
        sliding_post_nms=post_nms,
    )
    n_before_nms = len(combined)

    anchor_selected = dedupe_same_template_iou(
        [s for s in anchor_scored if passes_margin(s, min_margin, min_prob_top1)],
        iou_dedupe_thresh,
    )
    if template_whitelist:
        allow = set(template_whitelist)
        anchor_selected = [
            s for s in anchor_selected if s.pred_chain_template_id in allow
        ]
    anchor_sel_ids = {
        (s.t0_ms, s.t1_ms, s.pred_chain_template_id) for s in anchor_selected
    }
    for d in anchor_scored_out:
        key = (d["t0_ms"], d["t1_ms"], d["pred_chain_template_id"])
        d["in_anchor_selected"] = key in anchor_sel_ids

    if use_sliding_recall:
        slide_filtered = [
            s for s in slide_scored if passes_margin(s, min_margin, min_prob_top1)
        ]
        if template_whitelist:
            allow = set(template_whitelist)
            slide_filtered = [
                s for s in slide_filtered if s.pred_chain_template_id in allow
            ]
        slide_supp = sliding_supplements(
            anchor_selected, slide_filtered, iou_recall_thresh=iou_recall_thresh
        )
        sliding_selected = dedupe_same_template_iou(slide_supp, iou_dedupe_thresh)
        slide_sel_ids = {
            (s.t0_ms, s.t1_ms, s.pred_chain_template_id) for s in sliding_selected
        }
        for d in slide_scored_out:
            key = (d["t0_ms"], d["t1_ms"], d["pred_chain_template_id"])
            d["in_sliding_selected"] = key in slide_sel_ids
    final_keys = {(s.t0_ms, s.t1_ms, s.pred_chain_template_id) for s in combined}
    for d in anchor_scored_out + slide_scored_out:
        key = (d["t0_ms"], d["t1_ms"], d["pred_chain_template_id"])
        d["in_final_clips"] = key in final_keys

    clip_dicts = []
    for i, s in enumerate(combined):
        clip_dicts.append(scored_to_clip_dict(s, f"clip{i:02d}", events=events))

    return {
        "input_file": input_file,
        "event_count": len(events),
        "config": {
            "backend": "chain4_agent",
            "profile": profile.get("name"),
            "robust_classify": profile.get("robust_classify"),
            "pre_ms": pre_ms,
            "post_ms": post_ms,
            "window_ms": window_ms,
            "step_ms": step_ms,
            "sliding_merge_mode": merge_mode,
            "sliding_post_nms": post_nms,
            "min_margin": min_margin,
            "min_prob_top1": min_prob_top1,
            "iou_dedupe_thresh": iou_dedupe_thresh,
            "iou_recall_thresh": iou_recall_thresh,
            "max_events": max_events,
            "use_sliding_recall": use_sliding_recall,
            "template_whitelist": template_whitelist,
            "llm_enabled": bool(llm_cfg.get("enabled")),
        },
        "stats": {
            "anchor_geom": len(anchor_geom),
            "anchor_scored": len(anchor_scored),
            "anchor_selected": len(anchor_selected),
            "sliding_geom": len(slide_geom_out),
            "sliding_scored": len(slide_scored_out),
            "sliding_selected": len(sliding_selected),
            "final_clips_before_nms": n_before_nms,
            "final_clips": len(combined),
        },
        "anchor_geom": anchor_geom_out,
        "anchor_scored": anchor_scored_out,
        "sliding_geom": slide_geom_out,
        "sliding_scored": slide_scored_out,
        "clips": clip_dicts,
    }


def run_strip_highlights(
    *,
    timeline_path: Path,
    profile: Dict[str, Any],
    model=None,
    processor=None,
    device: str = "cuda",
    max_new_tokens: int = 512,
    pre_ms: int,
    post_ms: int,
    window_ms: int,
    step_ms: int,
    min_margin: float,
    min_prob_top1: float,
    iou_dedupe_thresh: float,
    iou_recall_thresh: float,
    max_events: Optional[int],
    use_sliding_recall: bool,
    template_whitelist: Optional[List[str]],
    sliding_merge_mode: str = "legacy",
    sliding_post_nms: str = "off",
) -> Dict[str, Any]:
    """几何发现（chain2）+ 窗级分类（chain4_agent / robust）。"""
    events = load_timeline_json(timeline_path)
    return run_strip_highlights_events(
        events=events,
        match_id=timeline_path.stem,
        profile=profile,
        model=model,
        processor=processor,
        device=device,
        max_new_tokens=max_new_tokens,
        pre_ms=pre_ms,
        post_ms=post_ms,
        window_ms=window_ms,
        step_ms=step_ms,
        min_margin=min_margin,
        min_prob_top1=min_prob_top1,
        iou_dedupe_thresh=iou_dedupe_thresh,
        iou_recall_thresh=iou_recall_thresh,
        max_events=max_events,
        use_sliding_recall=use_sliding_recall,
        template_whitelist=template_whitelist,
        input_file=str(timeline_path.resolve()),
        sliding_merge_mode=sliding_merge_mode,
        sliding_post_nms=sliding_post_nms,
    )
