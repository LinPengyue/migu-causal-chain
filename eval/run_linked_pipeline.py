#!/usr/bin/env python3
"""9.31 串联入口：上游 timeline → 拆条 + 集锦（按场输出）+ 逻辑完整率。

数据前提（build_datasets 已做好）：
  datasets/matches/<safe_id>/timeline.json   ← 无 causal 的交付事件（上游输入）
  datasets/matches/<safe_id>/strip_gold.json
  datasets/matches/<safe_id>/highlight_gold*.json  ← *_causal.json 标注

本脚本只做「穿起来 + 出结果 + 报完整率」；归因（上游 vs 因果链）后续再说。

用法（在 9.31causal_chain 根目录）：

  export PYTHONPATH="$PWD/algo:$PWD/eval"
  python eval/run_linked_pipeline.py --limit-matches 2
  python eval/run_linked_pipeline.py

输出：
  reports/linked_pipeline/<safe_id>/strip.json
  reports/linked_pipeline/<safe_id>/highlight.json
  reports/linked_pipeline/_summary.json
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

from causal_chain8.config import load_profile as load_c8_profile  # noqa: E402
from causal_chain8.highlight_io import write_reel_json  # noqa: E402
from eval_common import (  # noqa: E402
    REPORTS,
    ROOT as _ROOT,
    build_highlight_clips,
    clip_events_for_gold,
    highlight_clip_to_pred,
    highlight_logic_by_label_source,
    label_source_counts,
    load_highlight_gold,
    load_index,
    load_strip_gold,
    load_timeline_events,
    make_match_pbar,
    pct,
    should_drop_t2_for_gold,
)
from metrics import match_golds_to_preds, summarize  # noqa: E402
from strip_adapter import AlgoStripAdapter, OnlineStripAdapter  # noqa: E402
from run_stream_strip import online_replay  # noqa: E402
from stream_metrics import score_oracle_upper, score_stream_match  # noqa: E402
from eval_common import gold_events_stream  # noqa: E402


def _clip_to_dict(c: Any) -> Dict[str, Any]:
    if hasattr(c, "to_dict"):
        return c.to_dict()
    if isinstance(c, dict):
        return dict(c)
    return {
        "clip_id": str(getattr(c, "clip_id", "")),
        "t0_ms": int(getattr(c, "t0_ms", 0) or 0),
        "t1_ms": int(getattr(c, "t1_ms", 0) or 0),
        "chain_category": str(getattr(c, "chain_category", "") or ""),
        "chain_template_id": str(getattr(c, "chain_template_id", "") or ""),
    }


def _run_strip_module(
    adapter: AlgoStripAdapter,
    golds: List[Dict[str, Any]],
    timeline: List[Dict[str, Any]],
    *,
    event_source: str,
    match_id: str,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """与 offline_strip 同源：每条 gold clip → strip（模块完整率）。"""
    chains: List[Dict[str, Any]] = []
    golds_scored: List[Dict[str, Any]] = []
    preds_per: List[List[Dict[str, Any]]] = []
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
                }
            )
            continue
        preds = adapter.predict(clip, match_id=f"{match_id}_g{gi}")
        golds_scored.append(g)
        preds_per.append(preds)
        chains.append(
            {
                "clip_id": f"clip{gi:02d}",
                "annotation_id": g.get("annotation_id"),
                "ok": True,
                "gold": {
                    "chain_category": g.get("chain_category"),
                    "first_event": g.get("first_event"),
                    "last_event": g.get("last_event"),
                    "t0_ms": g.get("t0_ms"),
                    "t1_ms": g.get("t1_ms"),
                },
                "preds": preds,
            }
        )
    scored = (
        score_oracle_upper(golds_scored, preds_per)
        if golds_scored
        else {"n_gold": 0, "strict_complete": 0, "strict_rate": None}
    )
    stats = {
        "n_gold": int(scored.get("n_gold") or 0),
        "strict_matched": int(scored.get("strict_complete") or 0),
        "logic_complete_rate": scored.get("strict_rate"),
        "n_empty_clip": n_empty,
        "event_source": event_source,
        "protocol": "per_gold_clip_strip",
    }
    return chains, stats


def _run_strip_timeline(
    adapter: AlgoStripAdapter,
    events: List[Dict[str, Any]],
    golds: List[Dict[str, Any]],
    *,
    match_id: str,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """整场 timeline → strip，再与 strip_gold 一对一（串联形态）。"""
    preds = adapter.predict(events, match_id=match_id)
    chains = []
    for i, p in enumerate(preds):
        d = dict(p)
        d["clip_id"] = f"clip{i:02d}"
        chains.append(d)
    rows = match_golds_to_preds(golds, preds) if golds else []
    summ = summarize(rows) if rows else {"n": 0, "strict_complete": 0, "strict_rate": None}
    stats = {
        "n_gold": int(summ.get("n") or 0),
        "strict_matched": int(summ.get("strict_complete") or 0),
        "logic_complete_rate": summ.get("strict_rate"),
        "n_pred": len(preds),
        "precision": pct(int(summ.get("strict_complete") or 0), len(preds)),
        "protocol": "full_timeline_vs_strip_gold",
    }
    return chains, stats


def _run_strip_online(
    adapter: OnlineStripAdapter,
    golds: List[Dict[str, Any]],
    stream: List[Dict[str, Any]],
    *,
    match_id: str,
    prefix_stride: int,
    min_prefix: int,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    timeline_preds = online_replay(
        stream, adapter, match_id=match_id, stride=prefix_stride, min_prefix=min_prefix
    )
    sm = score_stream_match(golds, timeline_preds, require_strict=True)
    chains = list(sm.get("gold_rows") or [])
    n_gold = int(sm.get("n_gold") or 0)
    n_strict = int(sm.get("strict_complete") or 0)
    stats = {
        "n_gold": n_gold,
        "strict_matched": n_strict,
        "logic_complete_rate": round(100.0 * n_strict / n_gold, 2) if n_gold else None,
        "n_tracks": sm.get("n_tracks") or sm.get("n_emit_deduped"),
        "precision": pct(int(sm.get("precision_hits") or 0), int(sm.get("n_tracks") or sm.get("n_emit_deduped") or 0)),
        "protocol": "online_stream_vs_strip_gold",
    }
    return chains, stats


def _run_highlight(
    events: List[Dict[str, Any]],
    hl_gold: List[Dict[str, Any]],
    *,
    match_id: str,
    profile: Dict[str, Any],
    drop_t2: bool,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    clips, build_stats = build_highlight_clips(
        events, match_id=match_id, profile=profile, drop_t2=drop_t2
    )
    clip_dicts = [_clip_to_dict(c) for c in clips]
    preds = [highlight_clip_to_pred(c) for c in clips]
    rows = match_golds_to_preds(hl_gold, preds) if hl_gold else []
    summ = summarize(rows) if rows else {"n": 0, "strict_complete": 0, "strict_rate": None}
    by_src = highlight_logic_by_label_source(hl_gold, rows) if hl_gold and rows else {}
    ordering = [str(c.get("clip_id") or f"clip{i:02d}") for i, c in enumerate(clip_dicts)]
    total_dur = sum(
        max(int(c.get("t1_ms") or 0) - int(c.get("t0_ms") or 0), 0) for c in clip_dicts
    )
    payload = {
        "match_id": match_id,
        "reel": {
            "clips": clip_dicts,
            "ordering": ordering,
            "total_duration_ms": total_dur,
        },
        "build_stats": build_stats,
    }
    stats = {
        "n_gold": int(summ.get("n") or 0),
        "strict_matched": int(summ.get("strict_complete") or 0),
        "logic_complete_rate": summ.get("strict_rate"),
        "n_pred": len(preds),
        "precision": pct(int(summ.get("strict_complete") or 0), len(preds)),
        "by_label_source": by_src,
        "label_source_counts": label_source_counts(hl_gold),
        "drop_t2": drop_t2,
        "protocol": "select_moments→clips_vs_highlight_gold",
    }
    return payload, stats


def _acc_add(acc: Dict[str, int], stats: Dict[str, Any]) -> None:
    acc["n_gold"] = acc.get("n_gold", 0) + int(stats.get("n_gold") or 0)
    acc["strict"] = acc.get("strict", 0) + int(stats.get("strict_matched") or 0)
    acc["n_pred"] = acc.get("n_pred", 0) + int(stats.get("n_pred") or 0)


def _acc_rate(acc: Dict[str, int]) -> Optional[float]:
    return pct(acc.get("strict", 0), acc.get("n_gold", 0))


def main(argv: List[str] | None = None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="Linked strip+highlight per-match pipeline")
    ap.add_argument("--limit-matches", type=int, default=0)
    ap.add_argument("--profile", default="production")
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=REPORTS / "linked_pipeline",
    )
    ap.add_argument(
        "--strip-mode",
        choices=["module", "timeline", "online", "all"],
        default="all",
        help="module≈82%%口径；timeline=整场串联；online≈71%%；all=三种都跑",
    )
    ap.add_argument(
        "--module-event-source",
        choices=["gold_events", "timeline"],
        default="gold_events",
        help="module 模式 clip 事件源（默认 gold_events）",
    )
    ap.add_argument(
        "--online-stream-source",
        choices=["gold_events", "timeline"],
        default="gold_events",
    )
    ap.add_argument("--prefix-stride", type=int, default=1)
    ap.add_argument("--min-prefix", type=int, default=2)
    ap.add_argument("--keep-t2", action="store_true", help="集锦不自动 drop T2")
    args = ap.parse_args(argv)

    offline = AlgoStripAdapter(profile_name=args.profile, use_llm=False, use_sliding_recall=True)
    online = OnlineStripAdapter(profile_name=args.profile, use_llm=False, use_sliding_recall=True)
    hl_profile = dict(load_c8_profile(args.profile))
    hl_profile.setdefault("llm", {})
    hl_profile["llm"] = dict(hl_profile.get("llm") or {})
    hl_profile["llm"]["enabled"] = False

    out_dir = args.out_dir if args.out_dir.is_absolute() else _ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    matches = load_index()["matches"]
    if args.limit_matches > 0:
        matches = matches[: args.limit_matches]

    do_module = args.strip_mode in ("module", "all")
    do_timeline = args.strip_mode in ("timeline", "all")
    do_online = args.strip_mode in ("online", "all")

    acc_module: Dict[str, int] = {}
    acc_timeline: Dict[str, int] = {}
    acc_online: Dict[str, int] = {}
    acc_hl: Dict[str, int] = {}
    manifest: List[Dict[str, Any]] = []

    pbar = make_match_pbar("Linked Pipeline", len(matches))
    try:
        for mi, meta in enumerate(matches):
            mdir = _ROOT / meta["dir"]
            safe = str(meta.get("safe_id") or f"m{mi}")
            mid = str(meta.get("match_id") or safe)
            match_out = out_dir / safe[:60]
            match_out.mkdir(parents=True, exist_ok=True)

            timeline = load_timeline_events(mdir)
            golds = load_strip_gold(mdir)
            hl_gold, hl_src = load_highlight_gold(mdir)
            drop_t2 = (not args.keep_t2) and should_drop_t2_for_gold(hl_src, hl_gold)

            row: Dict[str, Any] = {
                "safe_id": safe,
                "match_id": mid,
                "path": str(match_out.relative_to(_ROOT)),
                "n_timeline_events": len(timeline),
                "n_strip_gold": len(golds),
                "n_highlight_gold": len(hl_gold),
            }

            strip_payload: Dict[str, Any] = {
                "match_id": mid,
                "safe_id": safe,
                "n_timeline_events": len(timeline),
                "modes": {},
            }

            if do_module and golds:
                chains, st = _run_strip_module(
                    offline,
                    golds,
                    timeline,
                    event_source=args.module_event_source,
                    match_id=safe,
                )
                strip_payload["modes"]["module"] = {"chains": chains, "stats": st}
                _acc_add(acc_module, st)
                row["strip_module"] = st

            if do_timeline and timeline:
                chains, st = _run_strip_timeline(
                    offline, timeline, golds, match_id=safe
                )
                strip_payload["modes"]["timeline"] = {"chains": chains, "stats": st}
                _acc_add(acc_timeline, st)
                row["strip_timeline"] = st

            if do_online and golds:
                if args.online_stream_source == "gold_events":
                    stream = gold_events_stream(golds)
                else:
                    stream = timeline
                if stream:
                    chains, st = _run_strip_online(
                        online,
                        golds,
                        stream,
                        match_id=safe,
                        prefix_stride=args.prefix_stride,
                        min_prefix=args.min_prefix,
                    )
                    strip_payload["modes"]["online"] = {"chains": chains, "stats": st}
                    _acc_add(acc_online, st)
                    row["strip_online"] = st

            strip_path = match_out / "strip.json"
            strip_path.write_text(
                json.dumps(strip_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            if timeline:
                hl_payload, hl_st = _run_highlight(
                    timeline,
                    hl_gold,
                    match_id=safe,
                    profile=hl_profile,
                    drop_t2=drop_t2,
                )
                hl_payload["safe_id"] = safe
                hl_payload["stats"] = hl_st
                hl_payload["config"] = {
                    "pipeline": "timeline→select_moments→clips",
                    "aligned_with": "eval/eval_offline_highlight.py",
                    "highlight_gold_source": hl_src,
                }
                write_reel_json(match_out / "highlight.json", hl_payload)
                _acc_add(acc_hl, hl_st)
                row["highlight"] = hl_st
            else:
                row["highlight"] = {"ok": False, "reason": "empty_timeline"}

            manifest.append(row)
            bits = []
            if "strip_module" in row:
                bits.append(f"mod={row['strip_module'].get('logic_complete_rate')}")
            if "highlight" in row and isinstance(row["highlight"], dict):
                bits.append(f"hl={row['highlight'].get('logic_complete_rate')}")
            pbar.set_postfix_str(" ".join(bits) or "-")
            pbar.update(1)
    finally:
        pbar.close()

    summary = {
        "n_matches": len(matches),
        "out_dir": str(out_dir),
        "strip_mode": args.strip_mode,
        "note": "按场输出拆条+集锦，并汇总逻辑完整率；归因（上游/因果链）后续再分",
        "logic_complete_rates": {
            "strip_module": {
                "rate": _acc_rate(acc_module),
                "matched": acc_module.get("strict", 0),
                "gold": acc_module.get("n_gold", 0),
                "note": "与 eval_offline_strip(gold_events) 同口径，约 82%",
            },
            "strip_timeline": {
                "rate": _acc_rate(acc_timeline),
                "matched": acc_timeline.get("strict", 0),
                "gold": acc_timeline.get("n_gold", 0),
                "n_pred": acc_timeline.get("n_pred", 0),
                "note": "整场上游 timeline 自切再对 strip_gold（串联形态）",
            },
            "strip_online": {
                "rate": _acc_rate(acc_online),
                "matched": acc_online.get("strict", 0),
                "gold": acc_online.get("n_gold", 0),
                "note": "与 eval_online_strip 同口径，约 71%",
            },
            "highlight_offline": {
                "rate": _acc_rate(acc_hl),
                "matched": acc_hl.get("strict", 0),
                "gold": acc_hl.get("n_gold", 0),
                "n_pred": acc_hl.get("n_pred", 0),
                "note": "与 eval_offline_highlight 同口径",
            },
        },
        "matches": manifest,
    }
    sum_path = out_dir / "_summary.json"
    sum_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "n_matches": summary["n_matches"],
                "out_dir": summary["out_dir"],
                "logic_complete_rates": summary["logic_complete_rates"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    print(f"wrote {sum_path}", flush=True)
    return summary


if __name__ == "__main__":
    main()
