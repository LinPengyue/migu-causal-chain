"""主流程：层 A PDF 选片 → 层 B 因果链分类/抽取 → 短窗 reel。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from causal_chain2.llm_qwen import load_qwen

from causal_chain8.assemble_reel import assemble_reel, time_iou
from causal_chain8.config import load_profile
from causal_chain8.discover import ChainCandidate
from causal_chain8.highlight_io import load_timeline_document, write_reel_json
from causal_chain8.highlight_schema import HighlightChain, HighlightReel
from causal_chain8.refine import build_refined_chain, classify_candidate_chain4
from causal_chain8.select_moments import moment_to_index_window, select_moments


def _match_ground_truth(
    chains: List[HighlightChain],
    ground_truth: List[Dict[str, Any]],
    *,
    iou_thresh: float = 0.4,
) -> Dict[str, Any]:
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


def _moment_to_candidate(
    events: List[Dict[str, Any]],
    moment,
    *,
    idx: int,
) -> ChainCandidate:
    anchor_i, i0, i1 = moment_to_index_window(events, moment)
    types = [e["type"] for e in events[i0 : i1 + 1]]
    return ChainCandidate(
        candidate_id=f"m{idx:02d}_{moment.tier}_{moment.event_type}",
        anchor_i=anchor_i,
        anchor_type=str(events[anchor_i]["type"]),
        anchor_t_ms=int(events[anchor_i]["t_ms"]),
        i0=i0,
        i1=i1,
        t0_ms=int(events[i0]["t_ms"]),
        t1_ms=int(events[i1]["t_ms"]),
        event_types=types,
        hint_template_id="",
    )


def run_build_highlights(
    *,
    timeline_path: Path,
    model_path: str,
    profile_name: str = "production",
    device: str = "cuda",
    max_new_tokens: int = 512,
    ambiguous_margin: float = 0.12,
    half_ms: Optional[int] = None,
    max_clips: Optional[int] = None,
    max_total_duration_ms: Optional[int] = None,
    use_llm_narrative: bool = True,
    skip_llm: bool = False,
    model=None,
    processor=None,
) -> HighlightReel:
    profile = load_profile(profile_name)
    profile = dict(profile)
    profile.setdefault("llm", {})
    profile["llm"] = dict(profile["llm"])
    profile["llm"]["enabled"] = not skip_llm
    profile["llm"]["ambiguous_margin"] = ambiguous_margin

    events, meta = load_timeline_document(timeline_path)
    match_id = str(meta.get("match_id", timeline_path.stem))
    ground_truth = meta.get("ground_truth_chains")

    # --- 层 A：PDF 选片（唯一决定谁进集锦）---
    moments, select_stats = select_moments(events, half_ms=half_ms)

    if not skip_llm and (model is None or processor is None):
        model, processor = load_qwen(model_path, device)
    if skip_llm:
        model = processor = None

    # --- 层 B：仅对已选 moment 做因果链 ---
    built: List[HighlightChain] = []
    fast_n = 0
    for i, moment in enumerate(moments):
        cand = _moment_to_candidate(events, moment, idx=i)
        tid, conf, margin, fast_path, _tr = classify_candidate_chain4(
            model,
            processor,
            events,
            cand,
            profile=profile,
            device=device,
            max_new_tokens=max_new_tokens,
            match_id=match_id,
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
            profile=profile,
            model=model,
            processor=processor,
            device=device,
            use_llm_narrative=use_llm_narrative and not skip_llm,
        )
        # 强制短窗为选片窗（抽取可能再裁核心，但 clip 时间用 PDF 窗）
        chain.t0_ms = moment.t0_ms
        chain.t1_ms = moment.t1_ms
        chain.validation = dict(chain.validation or {})
        chain.validation["selection"] = moment.to_dict()
        built.append(chain)

    final = assemble_reel(
        built,
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
            "backend": "chain8_select_then_chain",
            "architecture": "A_select_moments → B_causal_chain",
            "profile": profile.get("name", profile_name),
            "robust_classify": profile.get("robust_classify"),
            "model_path": model_path,
            "device": device,
            "ambiguous_margin": ambiguous_margin,
            "half_ms": select_stats.get("half_ms"),
            "use_llm_narrative": use_llm_narrative and not skip_llm,
            "skip_llm": skip_llm,
            "max_clips": max_clips,
            "max_total_duration_ms": max_total_duration_ms,
        },
        stats={
            "moments_selected": len(moments),
            "chains_built": len(built),
            "clips_final": len(final),
            "fast_path": fast_n,
            "llm_path": len(moments) - fast_n,
            "select": select_stats,
            "moments": [m.to_dict() for m in moments],
            **gt_eval,
        },
        ground_truth=ground_truth,
    )
    return reel


def main() -> None:
    import argparse
    import json

    ap = argparse.ArgumentParser(
        description="causal_chain8：PDF 选片(A) → 因果链(B) → 集锦 reel"
    )
    ap.add_argument("--timeline-json", type=Path, required=True)
    ap.add_argument("--model-path", type=str, default="")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--profile", type=str, default="production")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--max-new-tokens", type=int, default=512)
    ap.add_argument("--agent-margin", type=float, default=0.12)
    ap.add_argument("--half-ms", type=int, default=0, help="半场时长 ms，0=自动")
    ap.add_argument("--max-clips", type=int, default=0)
    ap.add_argument("--max-total-duration-ms", type=int, default=0)
    ap.add_argument("--no-llm-narrative", action="store_true")
    ap.add_argument(
        "--rule-only",
        action="store_true",
        help="不加载 VLM，仅规则分类（选片层仍完整执行）",
    )
    ap.add_argument("--select-only", action="store_true", help="只跑选片，写 moments JSON")
    ap.add_argument("--viz-dir", type=Path, default=None)
    args = ap.parse_args()

    if args.select_only:
        events, meta = load_timeline_document(args.timeline_json)
        half = args.half_ms if args.half_ms > 0 else None
        moments, stats = select_moments(events, half_ms=half)
        payload = {
            "match_id": meta.get("match_id", args.timeline_json.stem),
            "stats": stats,
            "moments": [m.to_dict() for m in moments],
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        print(f"wrote {len(moments)} moments -> {args.out}")
        return

    skip_llm = bool(args.rule_only) or not str(args.model_path).strip()
    if not skip_llm and not args.model_path:
        raise SystemExit("需要 --model-path，或加 --rule-only / --select-only")

    reel = run_build_highlights(
        timeline_path=args.timeline_json,
        model_path=args.model_path or "",
        profile_name=args.profile,
        device=args.device,
        max_new_tokens=args.max_new_tokens,
        ambiguous_margin=args.agent_margin,
        half_ms=args.half_ms if args.half_ms > 0 else None,
        max_clips=args.max_clips if args.max_clips > 0 else None,
        max_total_duration_ms=(
            args.max_total_duration_ms if args.max_total_duration_ms > 0 else None
        ),
        use_llm_narrative=not args.no_llm_narrative,
        skip_llm=skip_llm,
    )

    write_reel_json(args.out, reel.to_dict())
    print(json.dumps(reel.stats.get("select", {}), ensure_ascii=False, indent=2))
    print(json.dumps({k: reel.stats[k] for k in ("moments_selected", "clips_final", "fast_path")}, ensure_ascii=False))
    print(f"wrote {len(reel.clips)} clips -> {args.out}")

    if args.viz_dir:
        from causal_chain8.viz import render_reel_visualizations

        events, _ = load_timeline_document(args.timeline_json)
        paths = render_reel_visualizations(reel.to_dict(), events, args.viz_dir)
        print(f"visualizations ({len(paths)} files) -> {args.viz_dir}")


if __name__ == "__main__":
    main()
