#!/usr/bin/env python3
"""独立导出：每场比赛拆条因果链（不改现有评测脚本）。

默认离线评测同源（逻辑完整率 82.15%）：
  每条 strip_gold 已切好的 clip.events → causal_chain6 strip → pred

--mode online：在线评测同源（约 71.62%）：
  gold_events 流 → OnlineStripEngine feed/advance → one-to-one

--mode timeline：整场时间线自切（交付探测，不对齐正式数字）。

用法（在 8.31causal_chain 根目录）：

  export PYTHONPATH="$PWD/algo:$PWD/eval"
  python eval/dump_strip_chains.py
  python eval/dump_strip_chains.py --mode online
  python eval/dump_strip_chains.py --mode timeline
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "algo"))
sys.path.insert(0, str(ROOT / "eval"))

from causal_chain6.schema.templates import CHAIN4_TEMPLATES  # noqa: E402
from eval_common import (  # noqa: E402
    REPORTS,
    ROOT as _ROOT,
    clip_events_for_gold,
    gold_events_stream,
    load_index,
    load_strip_gold,
    load_timeline_events,
    make_match_pbar,
)
from metrics import check_pair  # noqa: E402
from run_stream_strip import online_replay  # noqa: E402
from stream_metrics import score_stream_match  # noqa: E402
from strip_adapter import AlgoStripAdapter, OnlineStripAdapter  # noqa: E402


def _enrich_pred(pred: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(pred)
    tid = str(d.get("template_id") or d.get("pred_chain_template_id") or "")
    if not d.get("chain_category") and tid in CHAIN4_TEMPLATES:
        d["chain_category"] = CHAIN4_TEMPLATES[tid]["category"]
    return d


def _category_counts(clips: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for c in clips:
        cat = str(c.get("chain_category") or "unknown") or "unknown"
        counts[cat] = counts.get(cat, 0) + 1
    return counts


def _pick_best_pred(gold: Dict[str, Any], preds: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """与 score_oracle_upper 一致：优先 strict，再比 IoU。"""
    from metrics import time_iou

    best = None
    best_flags = None
    best_iou = -1.0
    g_norm = {
        "chain_category": gold.get("chain_category") or gold.get("category") or "",
        "first_event": gold.get("first_event") or gold.get("first") or "",
        "last_event": gold.get("last_event") or gold.get("last") or "",
        "t0_ms": gold.get("t0_ms"),
        "t1_ms": gold.get("t1_ms"),
        "anchor_t_ms": gold.get("anchor_t_ms"),
    }
    for p in preds:
        flags = check_pair(g_norm, p)
        iou = time_iou(
            int(g_norm["t0_ms"] or 0),
            int(g_norm["t1_ms"] or 0),
            int(p.get("t0_ms") or 0),
            int(p.get("t1_ms") or 0),
        )
        if flags["strict"] or (best_flags is None and flags.get("a_time")):
            if flags["strict"] and (best_flags is None or not best_flags.get("strict")):
                best, best_flags, best_iou = p, flags, iou
            elif flags["strict"] and iou > best_iou:
                best, best_flags, best_iou = p, flags, iou
            elif best_flags is None:
                best, best_flags, best_iou = p, flags, iou
        elif best_flags is None and iou > best_iou:
            best, best_flags, best_iou = p, flags, iou
    return best


def _dump_gold_clips(
    *,
    adapter: AlgoStripAdapter,
    golds: List[Dict[str, Any]],
    timeline: List[Dict[str, Any]],
    event_source: str,
    match_id: str,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """与 eval_offline_strip 同源：每条 gold clip → strip。"""
    chains: List[Dict[str, Any]] = []
    n_strict = 0
    n_scorable = 0
    n_empty = 0
    for gi, g in enumerate(golds):
        clip = clip_events_for_gold(g, timeline, event_source=event_source)
        if not clip:
            n_empty += 1
            chains.append(
                {
                    "clip_id": f"clip{gi:02d}",
                    "annotation_id": g.get("annotation_id"),
                    "ok": False,
                    "reason": "empty_clip",
                    "gold": {
                        "chain_category": g.get("chain_category") or g.get("category"),
                        "first_event": g.get("first_event"),
                        "last_event": g.get("last_event"),
                        "t0_ms": g.get("t0_ms"),
                        "t1_ms": g.get("t1_ms"),
                    },
                }
            )
            continue
        preds = [_enrich_pred(p) for p in adapter.predict(clip, match_id=f"{match_id}_g{gi}")]
        n_scorable += 1
        best = _pick_best_pred(g, preds) if preds else None
        g_norm = {
            "chain_category": g.get("chain_category") or g.get("category") or "",
            "first_event": g.get("first_event") or "",
            "last_event": g.get("last_event") or "",
            "t0_ms": g.get("t0_ms"),
            "t1_ms": g.get("t1_ms"),
            "anchor_t_ms": g.get("anchor_t_ms"),
        }
        flags = check_pair(g_norm, best) if best else {
            "a_time": False,
            "b_category": False,
            "c_first": False,
            "d_last": False,
            "strict": False,
        }
        if flags.get("strict"):
            n_strict += 1
        entry: Dict[str, Any] = {
            "clip_id": f"clip{gi:02d}",
            "annotation_id": g.get("annotation_id"),
            "ok": True,
            "strict_match": bool(flags.get("strict")),
            "flags": flags,
            "gold": {
                "chain_category": g_norm["chain_category"],
                "first_event": g_norm["first_event"],
                "last_event": g_norm["last_event"],
                "t0_ms": g_norm["t0_ms"],
                "t1_ms": g_norm["t1_ms"],
            },
            "pred": best,
            "n_preds_on_clip": len(preds),
            "all_preds": preds,
        }
        # 顶层也摊平 pred，方便直接当算法输出读
        if best:
            entry.update(
                {
                    "chain_category": best.get("chain_category"),
                    "first_event": best.get("first_event"),
                    "last_event": best.get("last_event"),
                    "t0_ms": best.get("t0_ms"),
                    "t1_ms": best.get("t1_ms"),
                    "template_id": best.get("template_id"),
                    "events": best.get("events"),
                    "event_ids": best.get("event_ids"),
                    "event_keys": best.get("event_keys"),
                }
            )
        chains.append(entry)

    stats = {
        "n_gold": len(golds),
        "n_scorable": n_scorable,
        "n_empty_clip": n_empty,
        "strict_matched": n_strict,
        "logic_complete_rate": round(100.0 * n_strict / n_scorable, 2) if n_scorable else None,
    }
    return chains, stats


def _dump_timeline(
    *,
    adapter: AlgoStripAdapter,
    events: List[Dict[str, Any]],
    match_id: str,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    preds = [_enrich_pred(p) for p in adapter.predict(events, match_id=match_id)]
    chains = []
    for i, p in enumerate(preds):
        d = dict(p)
        d["clip_id"] = f"clip{i:02d}"
        chains.append(d)
    stats = {"n_pred": len(chains), "final_clips": len(chains)}
    return chains, stats


def _dump_online(
    *,
    adapter: OnlineStripAdapter,
    golds: List[Dict[str, Any]],
    stream_events: List[Dict[str, Any]],
    match_id: str,
    prefix_stride: int,
    min_prefix: int,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """与 eval_online_strip 同源：流式 replay + bipartite one-to-one。"""
    timeline_preds = online_replay(
        stream_events,
        adapter,
        match_id=match_id,
        stride=prefix_stride,
        min_prefix=min_prefix,
    )
    sm = score_stream_match(golds, timeline_preds, require_strict=True)
    chains: List[Dict[str, Any]] = []
    for gi, (g, row) in enumerate(zip(golds, sm.get("gold_rows") or [])):
        pred = row.get("pred")
        flags = row.get("flags") or {}
        entry: Dict[str, Any] = {
            "clip_id": f"clip{gi:02d}",
            "annotation_id": g.get("annotation_id") or row.get("annotation_id"),
            "ok": True,
            "strict_match": bool(flags.get("strict")),
            "matched": bool(row.get("matched")),
            "latency_ms": row.get("latency_ms"),
            "track_id": row.get("track_id"),
            "t_ready": row.get("t_ready"),
            "flags": flags,
            "gold": {
                "chain_category": g.get("chain_category") or g.get("category"),
                "first_event": g.get("first_event"),
                "last_event": g.get("last_event"),
                "t0_ms": g.get("t0_ms"),
                "t1_ms": g.get("t1_ms"),
            },
            "pred": pred,
        }
        if pred:
            entry.update(
                {
                    "chain_category": pred.get("category") or pred.get("chain_category"),
                    "first_event": pred.get("first") or pred.get("first_event"),
                    "last_event": pred.get("last") or pred.get("last_event"),
                    "t0_ms": pred.get("t0_ms"),
                    "t1_ms": pred.get("t1_ms"),
                    "emit_t_ms": pred.get("emit_t_ms"),
                }
            )
        chains.append(entry)

    n_gold = int(sm.get("n_gold") or 0)
    n_strict = int(sm.get("strict_complete") or 0)
    stats = {
        "n_gold": n_gold,
        "n_scorable": n_gold,
        "strict_matched": n_strict,
        "logic_complete_rate": round(100.0 * n_strict / n_gold, 2) if n_gold else None,
        "precision_hits": sm.get("precision_hits"),
        "n_tracks": sm.get("n_tracks") or sm.get("n_emit_deduped"),
        "recall_matched": sm.get("recall_matched"),
        "n_stream_events": len(stream_events),
        "n_prefix_snapshots": len(timeline_preds),
    }
    return chains, stats


def main(argv: List[str] | None = None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="Dump per-match strip causal chains")
    ap.add_argument("--limit-matches", type=int, default=0, help="0=全部场次")
    ap.add_argument("--profile", default="production")
    ap.add_argument(
        "--mode",
        choices=["gold_clips", "online", "timeline"],
        default="gold_clips",
        help="gold_clips=离线评测(82%)；online=在线评测(71%)；timeline=整场自切",
    )
    ap.add_argument(
        "--event-source",
        choices=["gold_events", "timeline"],
        default="gold_events",
        help="gold_clips / online 的事件源（默认 gold_events）",
    )
    ap.add_argument("--prefix-stride", type=int, default=1, help="online 模式")
    ap.add_argument("--min-prefix", type=int, default=2, help="online 模式")
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="默认按 mode：strip_dump / strip_dump_online / strip_dump_timeline",
    )
    ap.add_argument("--use-llm", action="store_true", default=False)
    ap.add_argument("--model-path", type=str, default="/data2/lpy1/Qwen2.5-VL")
    ap.add_argument("--device", default="cuda")
    args = ap.parse_args(argv)

    model = processor = None
    if args.use_llm:
        from causal_chain2.llm_qwen import load_qwen

        print(f"loading Qwen from {args.model_path} on {args.device} ...", flush=True)
        model, processor = load_qwen(args.model_path, args.device)

    device = args.device if args.use_llm else "cpu"
    offline_adapter = AlgoStripAdapter(
        profile_name=args.profile,
        model=model,
        processor=processor,
        device=device,
        use_llm=bool(args.use_llm),
        use_sliding_recall=True,
    )
    online_adapter = OnlineStripAdapter(
        profile_name=args.profile,
        model=model,
        processor=processor,
        device=device,
        use_llm=bool(args.use_llm),
        use_sliding_recall=True,
    )

    out_defaults = {
        "gold_clips": REPORTS / "strip_dump",
        "online": REPORTS / "strip_dump_online",
        "timeline": REPORTS / "strip_dump_timeline",
    }
    if args.out_dir is None:
        args.out_dir = out_defaults[args.mode]
    out_dir = args.out_dir if args.out_dir.is_absolute() else _ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    matches = load_index()["matches"]
    if args.limit_matches > 0:
        matches = matches[: args.limit_matches]

    manifest: List[Dict[str, Any]] = []
    n_strict_all = 0
    n_scorable_all = 0
    pbar = make_match_pbar("Dump Strip Chains", len(matches))
    try:
        for mi, meta in enumerate(matches):
            mdir = _ROOT / meta["dir"]
            safe = str(meta.get("safe_id") or f"m{mi}")
            mid = str(meta.get("match_id") or safe)
            golds = load_strip_gold(mdir)
            timeline = load_timeline_events(mdir)
            adapter_name = "AlgoStripAdapter"

            if args.mode == "gold_clips":
                if not golds:
                    manifest.append(
                        {"safe_id": safe, "ok": False, "reason": "no_strip_gold", "n_chains": 0}
                    )
                    pbar.update(1)
                    continue
                chains, stats = _dump_gold_clips(
                    adapter=offline_adapter,
                    golds=golds,
                    timeline=timeline,
                    event_source=args.event_source,
                    match_id=safe,
                )
                n_strict_all += int(stats.get("strict_matched") or 0)
                n_scorable_all += int(stats.get("n_scorable") or 0)
                pipeline = f"gold_clip({args.event_source})→causal_chain6.strip"
                aligned = "eval/eval_offline_strip.py --event-source " + args.event_source
            elif args.mode == "online":
                if not golds:
                    manifest.append(
                        {"safe_id": safe, "ok": False, "reason": "no_strip_gold", "n_chains": 0}
                    )
                    pbar.update(1)
                    continue
                if args.event_source == "gold_events":
                    stream = gold_events_stream(golds)
                else:
                    stream = timeline
                if not stream:
                    manifest.append(
                        {"safe_id": safe, "ok": False, "reason": "empty_stream", "n_chains": 0}
                    )
                    pbar.update(1)
                    continue
                chains, stats = _dump_online(
                    adapter=online_adapter,
                    golds=golds,
                    stream_events=stream,
                    match_id=safe,
                    prefix_stride=args.prefix_stride,
                    min_prefix=args.min_prefix,
                )
                n_strict_all += int(stats.get("strict_matched") or 0)
                n_scorable_all += int(stats.get("n_scorable") or 0)
                adapter_name = "OnlineStripAdapter"
                pipeline = f"stream({args.event_source})→OnlineStripEngine→one-to-one"
                aligned = (
                    "eval/eval_online_strip.py --stream-source " + args.event_source
                )
            else:
                if not timeline:
                    manifest.append(
                        {"safe_id": safe, "ok": False, "reason": "empty_timeline", "n_chains": 0}
                    )
                    pbar.update(1)
                    continue
                chains, stats = _dump_timeline(
                    adapter=offline_adapter, events=timeline, match_id=safe
                )
                pipeline = "full_timeline→causal_chain6.strip"
                aligned = "delivery discovery (not eval rate)"

            cat_counts = _category_counts(
                [c for c in chains if c.get("chain_category")]
            )
            payload = {
                "match_id": mid,
                "safe_id": safe,
                "mode": args.mode,
                "n_chains": len(chains),
                "category_counts": cat_counts,
                "chains": chains,
                "config": {
                    "backend": "dump_strip_chains",
                    "algo": "causal_chain6",
                    "adapter": adapter_name,
                    "mode": args.mode,
                    "event_source": (
                        args.event_source if args.mode in ("gold_clips", "online") else None
                    ),
                    "prefix_stride": args.prefix_stride if args.mode == "online" else None,
                    "min_prefix": args.min_prefix if args.mode == "online" else None,
                    "profile": args.profile,
                    "use_llm": bool(args.use_llm),
                    "pipeline": pipeline,
                    "aligned_with": aligned,
                },
                "stats": stats,
            }
            out_path = out_dir / f"{safe[:60]}.json"
            out_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            manifest.append(
                {
                    "safe_id": safe,
                    "match_id": mid,
                    "ok": True,
                    "path": str(out_path.relative_to(_ROOT)),
                    "n_chains": len(chains),
                    "category_counts": cat_counts,
                    "stats": stats,
                }
            )
            if args.mode in ("gold_clips", "online"):
                pbar.set_postfix_str(
                    f"strict={stats.get('strict_matched')}/{stats.get('n_scorable')} "
                    f"logic={stats.get('logic_complete_rate')}%"
                )
            else:
                pbar.set_postfix_str(f"chains={len(chains)}")
            pbar.update(1)
    finally:
        pbar.close()

    n_ok = sum(1 for m in manifest if m.get("ok"))
    summary: Dict[str, Any] = {
        "n_matches": len(matches),
        "n_ok": n_ok,
        "n_fail": len(matches) - n_ok,
        "mode": args.mode,
        "event_source": (
            args.event_source if args.mode in ("gold_clips", "online") else None
        ),
        "out_dir": str(out_dir),
        "use_llm": bool(args.use_llm),
        "algo": "causal_chain6",
        "matches": manifest,
    }
    if args.mode in ("gold_clips", "online") and n_scorable_all:
        summary["strict_matched"] = n_strict_all
        summary["n_scorable"] = n_scorable_all
        summary["logic_complete_rate"] = round(100.0 * n_strict_all / n_scorable_all, 2)
    man_path = out_dir / "_manifest.json"
    man_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                k: summary[k]
                for k in summary
                if k
                in (
                    "n_matches",
                    "n_ok",
                    "mode",
                    "event_source",
                    "strict_matched",
                    "n_scorable",
                    "logic_complete_rate",
                    "out_dir",
                )
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    print(f"wrote {man_path}", flush=True)
    return summary


if __name__ == "__main__":
    main()
