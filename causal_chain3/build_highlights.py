"""主流程：发现 → hybrid 精修建链 → 编排 reel。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from causal_chain2.llm_qwen import load_qwen

from causal_chain3.assemble_reel import assemble_reel, time_iou
from causal_chain3.discover import discover_candidates
from causal_chain3.io import load_timeline_document, write_reel_json
from causal_chain3.refine import build_refined_chain, classify_candidate_hybrid
from causal_chain3.schema import HighlightChain, HighlightReel


def _match_ground_truth(
    chains: List[HighlightChain],
    ground_truth: List[Dict[str, Any]],
    *,
    iou_thresh: float = 0.4,
) -> Dict[str, Any]:
    """与样例 ground_truth_chains 比对 template 命中率。"""
    if not ground_truth:
        return {}
    matched = 0
    details: List[Dict[str, Any]] = []
    used_pred: Set[str] = set()

    for gt in ground_truth:
        gt_tid = gt["chain_template_id"]
        gt_t0, gt_t1 = int(gt["t0_ms"]), int(gt["t1_ms"])
        best: Optional[HighlightChain] = None
        best_iou = 0.0
        for c in chains:
            if c.clip_id in used_pred:
                continue
            iou = time_iou(gt_t0, gt_t1, c.t0_ms, c.t1_ms)
            if iou >= iou_thresh and iou > best_iou:
                best_iou = iou
                best = c
        ok = best is not None and best.chain_template_id == gt_tid
        if ok:
            matched += 1
            if best:
                used_pred.add(best.clip_id)
        details.append(
            {
                "gt_clip_id": gt.get("clip_id", ""),
                "gt_template": gt_tid,
                "pred_template": best.chain_template_id if best else None,
                "time_iou": round(best_iou, 4),
                "correct": ok,
            }
        )
    n = len(ground_truth)
    return {
        "ground_truth_count": n,
        "matched_template": matched,
        "ground_truth_accuracy": round(matched / max(n, 1), 4),
        "details": details,
    }


def run_build_highlights(
    *,
    timeline_path: Path,
    model_path: str,
    device: str = "cuda",
    max_new_tokens: int = 512,
    ambiguous_margin: float = 0.12,
    pre_ms: int = 120_000,
    post_ms: int = 90_000,
    min_margin: float = 0.05,
    min_confidence: float = 0.0,
    iou_dedupe_thresh: float = 0.5,
    template_whitelist: Optional[List[str]] = None,
    max_clips: Optional[int] = None,
    max_total_duration_ms: Optional[int] = None,
    use_llm_narrative: bool = True,
    two_pass_discover: bool = True,
) -> HighlightReel:
    events, meta = load_timeline_document(timeline_path)
    match_id = str(meta.get("match_id", timeline_path.stem))
    ground_truth = meta.get("ground_truth_chains")

    model, processor = load_qwen(model_path, device)

    candidates = discover_candidates(
        events, pre_ms=pre_ms, post_ms=post_ms
    )

    # 第一遍规则 hint → 第二遍模板感知扩展（可选）
    if two_pass_discover and candidates:
        from causal_chain3.refine import hint_templates_from_rules

        hints = hint_templates_from_rules(events, candidates)
        candidates = discover_candidates(
            events, pre_ms=pre_ms, post_ms=post_ms, hint_templates=hints
        )

    built: List[HighlightChain] = []
    fast_n = 0
    for i, cand in enumerate(candidates):
        tid, conf, margin, fast_path, _tr = classify_candidate_hybrid(
            model,
            processor,
            events,
            cand,
            device=device,
            max_new_tokens=max_new_tokens,
            ambiguous_margin=ambiguous_margin,
        )
        if fast_path:
            fast_n += 1
        chain = build_refined_chain(
            clip_id=f"clip{i:02d}",
            events=events,
            candidate=cand,
            template_id=tid,
            confidence=conf,
            margin=margin,
            fast_path=fast_path,
            model=model,
            processor=processor,
            device=device,
            use_llm_narrative=use_llm_narrative,
        )
        built.append(chain)

    allow: Optional[Set[str]] = set(template_whitelist) if template_whitelist else None
    final = assemble_reel(
        built,
        iou_dedupe_thresh=iou_dedupe_thresh,
        min_margin=min_margin,
        min_confidence=min_confidence,
        template_whitelist=allow,
        max_clips=max_clips,
        max_total_duration_ms=max_total_duration_ms,
    )
    for j, c in enumerate(final):
        c.clip_id = f"clip{j:02d}"

    total_dur = sum(max(c.t1_ms - c.t0_ms, 0) for c in final)
    gt_eval = _match_ground_truth(final, ground_truth or [])

    reel = HighlightReel(
        match_id=match_id,
        input_file=str(timeline_path.resolve()),
        event_count=len(events),
        clips=final,
        ordering=[c.clip_id for c in final],
        total_duration_ms=total_dur,
        config={
            "backend": "agent_hybrid",
            "model_path": model_path,
            "device": device,
            "ambiguous_margin": ambiguous_margin,
            "pre_ms": pre_ms,
            "post_ms": post_ms,
            "min_margin": min_margin,
            "min_confidence": min_confidence,
            "iou_dedupe_thresh": iou_dedupe_thresh,
            "use_llm_narrative": use_llm_narrative,
            "two_pass_discover": two_pass_discover,
            "template_whitelist": template_whitelist,
            "max_clips": max_clips,
            "max_total_duration_ms": max_total_duration_ms,
        },
        stats={
            "candidates": len(candidates),
            "chains_built": len(built),
            "clips_final": len(final),
            "fast_path": fast_n,
            "llm_path": len(candidates) - fast_n,
            **gt_eval,
        },
        ground_truth=ground_truth,
    )
    return reel


def main() -> None:
    import argparse
    import json

    ap = argparse.ArgumentParser(
        description="causal_chain3：整场 timeline → 集锦因果链 reel（hybrid LLM）"
    )
    ap.add_argument("--timeline-json", type=Path, required=True)
    ap.add_argument("--model-path", type=str, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--max-new-tokens", type=int, default=512)
    ap.add_argument("--agent-margin", type=float, default=0.12)
    ap.add_argument("--pre-ms", type=int, default=120_000)
    ap.add_argument("--post-ms", type=int, default=90_000)
    ap.add_argument("--min-margin", type=float, default=0.05)
    ap.add_argument("--min-confidence", type=float, default=0.0)
    ap.add_argument("--iou-dedupe", type=float, default=0.5)
    ap.add_argument(
        "--templates",
        type=str,
        default=None,
        help="逗号分隔 chain_template_id 白名单",
    )
    ap.add_argument("--max-clips", type=int, default=0)
    ap.add_argument("--max-total-duration-ms", type=int, default=0)
    ap.add_argument(
        "--no-llm-narrative",
        action="store_true",
        help="叙事用规则模板，不调 LLM 写解说",
    )
    ap.add_argument(
        "--no-two-pass-discover",
        action="store_true",
        help="关闭规则 hint 第二遍 discover",
    )
    ap.add_argument("--viz-dir", type=Path, default=None)
    args = ap.parse_args()

    whitelist = None
    if args.templates and str(args.templates).strip():
        whitelist = [x.strip() for x in str(args.templates).split(",") if x.strip()]

    reel = run_build_highlights(
        timeline_path=args.timeline_json,
        model_path=args.model_path,
        device=args.device,
        max_new_tokens=args.max_new_tokens,
        ambiguous_margin=args.agent_margin,
        pre_ms=args.pre_ms,
        post_ms=args.post_ms,
        min_margin=args.min_margin,
        min_confidence=args.min_confidence,
        iou_dedupe_thresh=args.iou_dedupe,
        template_whitelist=whitelist,
        max_clips=args.max_clips if args.max_clips > 0 else None,
        max_total_duration_ms=(
            args.max_total_duration_ms if args.max_total_duration_ms > 0 else None
        ),
        use_llm_narrative=not args.no_llm_narrative,
        two_pass_discover=not args.no_two_pass_discover,
    )

    write_reel_json(args.out, reel.to_dict())
    print(json.dumps(reel.stats, ensure_ascii=False, indent=2))
    print(f"wrote {len(reel.clips)} clips -> {args.out}")

    if args.viz_dir:
        from causal_chain3.viz import render_reel_visualizations

        events, _ = load_timeline_document(args.timeline_json)
        paths = render_reel_visualizations(reel.to_dict(), events, args.viz_dir)
        print(f"visualizations ({len(paths)} files) -> {args.viz_dir}")


if __name__ == "__main__":
    main()
