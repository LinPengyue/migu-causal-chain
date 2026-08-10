"""整场时间线拆条（对齐 causal_chain2.timeline_highlights）。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

from causal_chain4.config import load_profile


def build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="causal_chain4 拆条：时间线 → 锚点/滑窗分段 → 分类 → 集锦片段"
    )
    ap.add_argument("--timeline-json", type=Path, required=True)
    ap.add_argument("--profile", type=str, default="production")
    ap.add_argument("--backend", choices=["agent", "llm", "gnn"], default=None)
    ap.add_argument("--model-path", type=str, default=None)
    ap.add_argument("--ckpt", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--max-new-tokens", type=int, default=512)
    ap.add_argument("--agent-full-llm", action="store_true")
    ap.add_argument("--agent-margin", type=float, default=None)
    ap.add_argument("--single-stage", action="store_true")
    ap.add_argument("--pre-ms", type=int, default=None)
    ap.add_argument("--post-ms", type=int, default=None)
    ap.add_argument("--window-ms", type=int, default=None)
    ap.add_argument("--step-ms", type=int, default=None)
    ap.add_argument("--min-margin", type=float, default=None)
    ap.add_argument("--min-prob-top1", type=float, default=0.0)
    ap.add_argument("--iou-dedupe", type=float, default=None)
    ap.add_argument("--iou-recall", type=float, default=None)
    ap.add_argument("--max-events", type=int, default=None)
    ap.add_argument("--optional-max-skip", type=int, default=2)
    ap.add_argument("--no-sliding-recall", action="store_true")
    ap.add_argument("--templates", type=str, default=None)
    ap.add_argument("--viz-dir", type=Path, default=None)
    return ap


def main(argv: list[str] | None = None) -> None:
    ap = build_argparser()
    args = ap.parse_args(argv)

    profile = load_profile(args.profile)
    strip_cfg = profile.get("strip") or {}

    from causal_chain2.timeline_highlights import SegmentScorer, load_gnn, run_timeline_highlights
    from causal_chain2.timeline_io import load_timeline_json

    dev = torch.device(args.device)
    backend = args.backend or str(strip_cfg.get("backend", "agent"))

    if backend in ("llm", "agent"):
        if not args.model_path:
            raise SystemExit(f"--backend {backend} 需要 --model-path")
        from causal_chain2.llm_qwen import load_qwen

        llm_model, llm_processor = load_qwen(args.model_path, args.device)
        agent_margin = args.agent_margin
        if agent_margin is None:
            agent_margin = float(strip_cfg.get("agent_margin", 0.12))
        scorer = SegmentScorer(
            backend=backend,
            device=dev,
            llm_model=llm_model,
            llm_processor=llm_processor,
            max_new_tokens=args.max_new_tokens,
            two_stage=not args.single_stage,
            full_llm=args.agent_full_llm,
            ambiguous_margin=agent_margin,
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

    pre_ms = args.pre_ms if args.pre_ms is not None else int(strip_cfg.get("pre_ms", 120_000))
    post_ms = args.post_ms if args.post_ms is not None else int(strip_cfg.get("post_ms", 60_000))
    window_ms = args.window_ms if args.window_ms is not None else int(strip_cfg.get("window_ms", 180_000))
    step_ms = args.step_ms if args.step_ms is not None else int(strip_cfg.get("step_ms", 90_000))
    min_margin = args.min_margin if args.min_margin is not None else float(strip_cfg.get("min_margin", 0.08))
    iou_dedupe = args.iou_dedupe if args.iou_dedupe is not None else float(strip_cfg.get("iou_dedupe", 0.5))
    iou_recall = args.iou_recall if args.iou_recall is not None else float(strip_cfg.get("iou_recall", 0.45))
    max_events = args.max_events if args.max_events is not None else int(strip_cfg.get("max_events", 12))

    result = run_timeline_highlights(
        timeline_path=args.timeline_json,
        scorer=scorer,
        pre_ms=pre_ms,
        post_ms=post_ms,
        window_ms=window_ms,
        step_ms=step_ms,
        min_margin=min_margin,
        min_prob_top1=args.min_prob_top1,
        iou_dedupe_thresh=iou_dedupe,
        iou_recall_thresh=iou_recall,
        max_events=max_events if max_events > 0 else None,
        use_sliding_recall=not args.no_sliding_recall,
        template_whitelist=whitelist,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["stats"], ensure_ascii=False, indent=2))
    print(f"profile={profile.get('name')}  wrote {len(result['clips'])} clips -> {args.out}")

    if args.viz_dir:
        from causal_chain2.timeline_highlights_viz import render_visualizations

        events = load_timeline_json(args.timeline_json)
        paths = render_visualizations(result, events, args.viz_dir)
        print(f"visualizations ({len(paths)} files) -> {args.viz_dir}")


if __name__ == "__main__":
    main()
