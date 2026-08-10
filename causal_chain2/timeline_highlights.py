"""
整场时间线 → 锚点/滑窗几何分段 → 窗级分类打分（LLM 或 GNN）→ margin 过滤 → 集锦片段列表。

设计要点（与用户需求对齐）：
- 分段只用几何 (t0/t1/i0/i1/types)，不用模版 pred_template；
- 集锦主选锚点窗；滑窗仅作召回补充（与已选锚点段时间 IoU 过高则丢弃）；
- 同模版 + 时间 IoU 高只保留最高 top1 概率的一条；
- 阈值用 margin = p_top1 - p_top2。
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import torch
import torch.nn.functional as F

from causal_chain2.chain_schema import CHAIN_TEMPLATES
from causal_chain2.graph_pack import TEMPLATE_TO_IX, pack_from_events_list
from causal_chain2.agent_classify import classify_events_agent
from causal_chain2.event_io import events_for_output
from causal_chain2.llm_classify import ClassifyResult, classify_events, label_zh
from causal_chain2.model import LiteGCN
from causal_chain2.segmentation_geom import GeoSegment, segment_anchor_geom, segment_sliding_geom
from causal_chain2.timeline_io import load_timeline_json

IX_TO_TEMPLATE: Dict[int, str] = {v: k for k, v in TEMPLATE_TO_IX.items()}


@dataclass
class SegmentScorer:
    backend: str  # "agent" | "llm" | "gnn"
    device: torch.device
    gnn_model: Optional[LiteGCN] = None
    llm_model: Any = None
    llm_processor: Any = None
    max_new_tokens: int = 512
    optional_max_skip: int = 2
    two_stage: bool = True
    skip_critic_llm: bool = False
    full_llm: bool = False
    ambiguous_margin: float = 0.12


@dataclass
class ScoredSegment:
    t0_ms: int
    t1_ms: int
    i0: int
    i1: int
    event_types: List[str]
    source: str
    pred_chain_template_id: str
    pred_chain_label_zh: str
    prob_top1: float
    prob_top2: float
    margin: float
    probs: Dict[str, float] = field(default_factory=dict)


def time_iou(a0: int, a1: int, b0: int, b1: int) -> float:
    inter = max(0, min(a1, b1) - max(a0, b0))
    union = max(a1, b1) - min(a0, b0)
    if union <= 0:
        return 0.0
    return inter / union


def slice_events(
    events: List[Dict[str, Any]],
    seg: GeoSegment,
    *,
    max_events: int | None,
) -> List[Dict[str, Any]]:
    """从时间线切出片段事件，补 order；过长时围绕锚点或区间中心截断。"""
    sub = [dict(events[k]) for k in range(seg.i0, seg.i1 + 1)]
    if max_events is None or len(sub) <= max_events:
        for i, e in enumerate(sub):
            e.setdefault("order", i)
        return sub

    if seg.anchor_i is not None and seg.i0 <= seg.anchor_i <= seg.i1:
        center = seg.anchor_i - seg.i0
    else:
        center = len(sub) // 2
    half = max_events // 2
    start = max(0, center - half)
    end = min(len(sub), start + max_events)
    start = max(0, end - max_events)
    trimmed = sub[start:end]
    for i, e in enumerate(trimmed):
        e["order"] = i
    return trimmed


def load_gnn(ckpt_path: Path, device: torch.device) -> LiteGCN:
    ck = torch.load(ckpt_path, map_location=device, weights_only=False)
    model = LiteGCN(
        int(ck["in_dim"]),
        int(ck["hidden"]),
        int(ck["num_classes"]),
    ).to(device)
    model.load_state_dict(ck["model"])
    model.eval()
    return model


def _classify_result_to_scored(seg: GeoSegment, result: ClassifyResult) -> ScoredSegment:
    tid = result.chain_template_id
    return ScoredSegment(
        t0_ms=seg.t0_ms,
        t1_ms=seg.t1_ms,
        i0=seg.i0,
        i1=seg.i1,
        event_types=seg.types,
        source=seg.source,
        pred_chain_template_id=tid,
        pred_chain_label_zh=label_zh(tid),
        prob_top1=result.confidence,
        prob_top2=result.prob_top2,
        margin=result.margin,
        probs=dict(result.probs),
    )


@torch.no_grad()
def score_segment_gnn(
    model: LiteGCN,
    events: List[Dict[str, Any]],
    seg: GeoSegment,
    device: torch.device,
    *,
    max_events: int | None,
    optional_max_skip: int,
) -> ScoredSegment:
    evs = slice_events(events, seg, max_events=max_events)
    x, edge_index = pack_from_events_list(
        evs, optional_max_skip=optional_max_skip, device=device
    )
    logits, _ = model(x, edge_index)
    probs = F.softmax(logits, dim=-1).squeeze(0)
    k = int(probs.numel())
    top2v, top2ix = torch.topk(probs, k=min(2, k))
    ix1 = int(top2ix[0].item())
    p1 = float(top2v[0].item())
    p2 = float(top2v[1].item()) if k >= 2 else 0.0
    tid = IX_TO_TEMPLATE[ix1]
    prob_map = {IX_TO_TEMPLATE[i]: float(probs[i].item()) for i in range(k)}
    return ScoredSegment(
        t0_ms=seg.t0_ms,
        t1_ms=seg.t1_ms,
        i0=seg.i0,
        i1=seg.i1,
        event_types=seg.types,
        source=seg.source,
        pred_chain_template_id=tid,
        pred_chain_label_zh=CHAIN_TEMPLATES.get(tid, {}).get("label_zh", tid),
        prob_top1=p1,
        prob_top2=p2,
        margin=p1 - p2,
        probs=prob_map,
    )


def score_segment(
    scorer: SegmentScorer,
    events: List[Dict[str, Any]],
    seg: GeoSegment,
    *,
    max_events: int | None,
) -> ScoredSegment:
    evs = slice_events(events, seg, max_events=max_events)
    if scorer.backend == "agent":
        result = classify_events_agent(
            scorer.llm_model,
            scorer.llm_processor,
            evs,
            device=str(scorer.device),
            max_new_tokens=scorer.max_new_tokens,
            skip_critic_llm=scorer.skip_critic_llm,
            full_llm=scorer.full_llm,
            ambiguous_margin=scorer.ambiguous_margin,
        )
        return _classify_result_to_scored(seg, result)
    if scorer.backend == "llm":
        result = classify_events(
            scorer.llm_model,
            scorer.llm_processor,
            evs,
            device=str(scorer.device),
            max_new_tokens=scorer.max_new_tokens,
            two_stage=scorer.two_stage,
        )
        return _classify_result_to_scored(seg, result)
    if scorer.gnn_model is None:
        raise ValueError("gnn backend requires gnn_model")
    return score_segment_gnn(
        scorer.gnn_model,
        events,
        seg,
        scorer.device,
        max_events=max_events,
        optional_max_skip=scorer.optional_max_skip,
    )


def passes_margin(seg: ScoredSegment, min_margin: float, min_prob_top1: float) -> bool:
    if seg.prob_top1 < min_prob_top1:
        return False
    return seg.margin >= min_margin


def dedupe_same_template_iou(
    segments: List[ScoredSegment],
    iou_thresh: float,
) -> List[ScoredSegment]:
    """同 pred_chain_template_id 且时间 IoU >= 阈值：只保留 prob_top1 最高的一条。"""
    if not segments:
        return []
    order = sorted(segments, key=lambda s: -s.prob_top1)
    kept: List[ScoredSegment] = []
    for s in order:
        drop = False
        for k in kept:
            if s.pred_chain_template_id != k.pred_chain_template_id:
                continue
            if time_iou(s.t0_ms, s.t1_ms, k.t0_ms, k.t1_ms) >= iou_thresh:
                drop = True
                break
        if not drop:
            kept.append(s)
    kept.sort(key=lambda s: s.t0_ms)
    return kept


def sliding_supplements(
    anchor_selected: List[ScoredSegment],
    sliding_scored: List[ScoredSegment],
    *,
    iou_recall_thresh: float,
) -> List[ScoredSegment]:
    """
    滑窗召回：已通过 margin 的滑窗段，若与任一已选锚点段时间 IoU 过高则丢弃。
    """
    out: List[ScoredSegment] = []
    for s in sliding_scored:
        dominated = False
        for a in anchor_selected:
            if time_iou(s.t0_ms, s.t1_ms, a.t0_ms, a.t1_ms) >= iou_recall_thresh:
                dominated = True
                break
        if not dominated:
            out.append(s)
    return out


def geom_to_dict(g: GeoSegment, proposal_id: str) -> Dict[str, Any]:
    return {
        "proposal_id": proposal_id,
        "t0_ms": g.t0_ms,
        "t1_ms": g.t1_ms,
        "i0": g.i0,
        "i1": g.i1,
        "event_types": g.types,
        "source": g.source,
        "anchor_i": g.anchor_i,
    }


def scored_to_dict(
    s: ScoredSegment,
    proposal_id: str,
    *,
    passes_margin: bool = False,
    in_anchor_selected: bool = False,
    in_sliding_selected: bool = False,
    in_final_clips: bool = False,
) -> Dict[str, Any]:
    return {
        "proposal_id": proposal_id,
        "t0_ms": s.t0_ms,
        "t1_ms": s.t1_ms,
        "i0": s.i0,
        "i1": s.i1,
        "event_types": s.event_types,
        "source": s.source,
        "anchor_i": None,
        "pred_chain_template_id": s.pred_chain_template_id,
        "pred_chain_label_zh": s.pred_chain_label_zh,
        "prob_top1": round(s.prob_top1, 6),
        "prob_top2": round(s.prob_top2, 6),
        "margin": round(s.margin, 6),
        "probs": {k: round(v, 6) for k, v in s.probs.items()},
        "passes_margin": passes_margin,
        "in_anchor_selected": in_anchor_selected,
        "in_sliding_selected": in_sliding_selected,
        "in_final_clips": in_final_clips,
    }


def scored_to_clip_dict(
    s: ScoredSegment,
    proposal_id: str = "",
    *,
    events: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    d = scored_to_dict(s, proposal_id or "clip")
    d["in_final_clips"] = True
    if events is not None:
        d["events"] = events_for_output(events[s.i0 : s.i1 + 1])
    return d


def run_timeline_highlights(
    *,
    timeline_path: Path,
    scorer: SegmentScorer,
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
) -> Dict[str, Any]:
    events = load_timeline_json(timeline_path)

    anchor_geom = segment_anchor_geom(
        events, pre_ms=pre_ms, post_ms=post_ms
    )
    anchor_geom_out = [
        geom_to_dict(g, f"a{i:02d}_geom") for i, g in enumerate(anchor_geom)
    ]

    anchor_scored: List[ScoredSegment] = []
    anchor_scored_out: List[Dict[str, Any]] = []
    for i, g in enumerate(anchor_geom):
        pid = f"a{i:02d}"
        sc = score_segment(
            scorer,
            events,
            g,
            max_events=max_events,
        )
        anchor_scored.append(sc)
        anchor_scored_out.append(
            scored_to_dict(
                sc,
                pid,
                passes_margin=passes_margin(sc, min_margin, min_prob_top1),
            )
        )

    anchor_filtered = [
        s for s in anchor_scored if passes_margin(s, min_margin, min_prob_top1)
    ]
    if template_whitelist:
        allow = set(template_whitelist)
        anchor_filtered = [
            s for s in anchor_filtered if s.pred_chain_template_id in allow
        ]

    anchor_selected = dedupe_same_template_iou(anchor_filtered, iou_dedupe_thresh)
    anchor_sel_ids = {
        (s.t0_ms, s.t1_ms, s.pred_chain_template_id) for s in anchor_selected
    }
    for d in anchor_scored_out:
        key = (d["t0_ms"], d["t1_ms"], d["pred_chain_template_id"])
        d["in_anchor_selected"] = key in anchor_sel_ids

    sliding_selected: List[ScoredSegment] = []
    slide_geom_out: List[Dict[str, Any]] = []
    slide_scored_out: List[Dict[str, Any]] = []
    if use_sliding_recall:
        slide_geom = segment_sliding_geom(
            events, window_ms=window_ms, step_ms=step_ms
        )
        slide_geom_out = [
            geom_to_dict(g, f"s{i:02d}_geom") for i, g in enumerate(slide_geom)
        ]
        slide_scored: List[ScoredSegment] = []
        for i, g in enumerate(slide_geom):
            pid = f"s{i:02d}"
            sc = score_segment(
                scorer,
                events,
                g,
                max_events=max_events,
            )
            slide_scored.append(sc)
            slide_scored_out.append(
                scored_to_dict(
                    sc,
                    pid,
                    passes_margin=passes_margin(sc, min_margin, min_prob_top1),
                )
            )
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

    combined = dedupe_same_template_iou(
        anchor_selected + sliding_selected, iou_dedupe_thresh
    )
    final_keys = {
        (s.t0_ms, s.t1_ms, s.pred_chain_template_id) for s in combined
    }
    for d in anchor_scored_out + slide_scored_out:
        key = (d["t0_ms"], d["t1_ms"], d["pred_chain_template_id"])
        d["in_final_clips"] = key in final_keys

    clip_dicts = []
    for i, s in enumerate(combined):
        clip_dicts.append(scored_to_clip_dict(s, f"clip{i:02d}", events=events))

    return {
        "input_file": str(timeline_path.resolve()),
        "event_count": len(events),
        "config": {
            "backend": scorer.backend,
            "two_stage": scorer.two_stage if scorer.backend == "llm" else None,
            "skip_critic_llm": scorer.skip_critic_llm if scorer.backend == "agent" else None,
            "pre_ms": pre_ms,
            "post_ms": post_ms,
            "window_ms": window_ms,
            "step_ms": step_ms,
            "min_margin": min_margin,
            "min_prob_top1": min_prob_top1,
            "iou_dedupe_thresh": iou_dedupe_thresh,
            "iou_recall_thresh": iou_recall_thresh,
            "max_events": max_events,
            "use_sliding_recall": use_sliding_recall,
            "template_whitelist": template_whitelist,
        },
        "stats": {
            "anchor_geom": len(anchor_geom),
            "anchor_scored": len(anchor_scored),
            "anchor_after_margin": len(anchor_filtered),
            "anchor_selected": len(anchor_selected),
            "sliding_geom": len(slide_geom_out),
            "sliding_scored": len(slide_scored_out),
            "sliding_selected": len(sliding_selected),
            "clips_final": len(combined),
        },
        "proposals": {
            "anchor_geom": anchor_geom_out,
            "anchor_scored": anchor_scored_out,
            "sliding_geom": slide_geom_out,
            "sliding_scored": slide_scored_out,
        },
        "clips": clip_dicts,
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="时间线 → 锚点分段 + 分类打分 + margin 集锦选段"
    )
    ap.add_argument("--timeline-json", type=Path, required=True)
    ap.add_argument(
        "--backend",
        choices=["agent", "llm", "gnn"],
        default="llm",
        help="agent=方案C（慢，离线精修）；llm=两阶段（默认）",
    )
    ap.add_argument(
        "--model-path",
        type=str,
        default=None,
        help="--backend llm/agent 时 Qwen2.5-VL 权重目录",
    )
    ap.add_argument(
        "--ckpt",
        type=Path,
        default=None,
        help="--backend gnn 时 LiteGCN checkpoint",
    )
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--max-new-tokens", type=int, default=512)
    ap.add_argument(
        "--agent-full-llm",
        action="store_true",
        help="agent 后端：旧版 5 步全 LLM（不推荐）",
    )
    ap.add_argument(
        "--agent-margin",
        type=float,
        default=0.12,
        help="agent hybrid：规则分差阈值",
    )
    ap.add_argument(
        "--single-stage",
        action="store_true",
        help="llm 后端：单阶段 18 类（默认两阶段）",
    )
    ap.add_argument("--pre-ms", type=int, default=120_000)
    ap.add_argument("--post-ms", type=int, default=60_000)
    ap.add_argument("--window-ms", type=int, default=180_000)
    ap.add_argument("--step-ms", type=int, default=90_000)
    ap.add_argument(
        "--min-margin",
        type=float,
        default=0.08,
        help="p_top1 - p_top2 下限，抑制塌缩到单一模版",
    )
    ap.add_argument(
        "--min-prob-top1",
        type=float,
        default=0.0,
        help="可选：top1 概率下限",
    )
    ap.add_argument(
        "--iou-dedupe",
        type=float,
        default=0.5,
        help="同模版时间 IoU 去重阈值",
    )
    ap.add_argument(
        "--iou-recall",
        type=float,
        default=0.45,
        help="滑窗补充时与已选锚点段时间 IoU 超过则丢弃",
    )
    ap.add_argument(
        "--max-events",
        type=int,
        default=12,
        help="打分前窗内最多保留事件数（围绕锚点或中心截断）",
    )
    ap.add_argument("--optional-max-skip", type=int, default=2, help="仅 gnn 后端")
    ap.add_argument(
        "--no-sliding-recall",
        action="store_true",
        help="关闭滑窗召回，仅锚点窗",
    )
    ap.add_argument(
        "--templates",
        type=str,
        default=None,
        help="逗号分隔 chain_template_id 白名单；默认不过滤",
    )
    ap.add_argument(
        "--viz-dir",
        type=Path,
        default=None,
        help="可选：输出可视化 PNG 目录（时间轴 + 每条 proposal 的分类概率图）",
    )
    args = ap.parse_args()

    dev = torch.device(args.device)
    if args.backend in ("llm", "agent"):
        if not args.model_path:
            raise SystemExit(f"--backend {args.backend} 需要 --model-path")
        from causal_chain2.llm_qwen import load_qwen

        llm_model, llm_processor = load_qwen(args.model_path, args.device)
        scorer = SegmentScorer(
            backend=args.backend,
            device=dev,
            llm_model=llm_model,
            llm_processor=llm_processor,
            max_new_tokens=args.max_new_tokens,
            two_stage=not args.single_stage,
            full_llm=args.agent_full_llm,
            ambiguous_margin=args.agent_margin,
        )
    else:
        if not args.ckpt:
            raise SystemExit("--backend gnn 需要 --ckpt")
        ckpt = args.ckpt.expanduser().resolve()
        if not ckpt.is_file():
            raise SystemExit(f"找不到 checkpoint: {ckpt}")
        scorer = SegmentScorer(
            backend="gnn",
            device=dev,
            gnn_model=load_gnn(ckpt, dev),
            optional_max_skip=args.optional_max_skip,
        )
    whitelist = None
    if args.templates and str(args.templates).strip():
        whitelist = [x.strip() for x in str(args.templates).split(",") if x.strip()]

    result = run_timeline_highlights(
        timeline_path=args.timeline_json,
        scorer=scorer,
        pre_ms=args.pre_ms,
        post_ms=args.post_ms,
        window_ms=args.window_ms,
        step_ms=args.step_ms,
        min_margin=args.min_margin,
        min_prob_top1=args.min_prob_top1,
        iou_dedupe_thresh=args.iou_dedupe,
        iou_recall_thresh=args.iou_recall,
        max_events=args.max_events if args.max_events > 0 else None,
        use_sliding_recall=not args.no_sliding_recall,
        template_whitelist=whitelist,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["stats"], ensure_ascii=False, indent=2))
    print(f"wrote {len(result['clips'])} clips -> {args.out}")

    if args.viz_dir:
        from causal_chain2.timeline_highlights_viz import render_visualizations

        events = load_timeline_json(args.timeline_json)
        paths = render_visualizations(result, events, args.viz_dir)
        print(f"visualizations ({len(paths)} files) -> {args.viz_dir}")


if __name__ == "__main__":
    main()
