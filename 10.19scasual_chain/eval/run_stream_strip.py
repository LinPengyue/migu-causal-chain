#!/usr/bin/env python3
"""8.31 Phase-1：流式拆条评测（prefix replay）+ 离线分类对照。

硬约束：
  - 评测只造流 / 打分，不内置终局触发或 lookback
  - V1 adapter：每次 predict(prefix) 只看当前 prefix，底层 batch strip

示例：
  cd 8.31causal_chain
  export PYTHONPATH=$PWD/algo:$PWD/eval
  python -u eval/run_stream_strip.py --rule-only --limit-matches 2
  python -u eval/run_stream_strip.py --rule-only --stream-source gold_events
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
ALGO = ROOT / "algo"
DATA = ROOT / "datasets"
OUT = ROOT / "reports"
sys.path.insert(0, str(ALGO))
sys.path.insert(0, str(ROOT / "eval"))

from metrics import match_golds_to_preds, summarize  # noqa: E402
from stream_metrics import (  # noqa: E402
    gold_t_ready,
    prefix_curve_for_gold,
    score_oracle_upper,
    score_stream_match,
)
from strip_adapter import AlgoStripAdapter, OnlineStripAdapter  # noqa: E402


def _load_strip_gold(mdir: Path) -> List[Dict[str, Any]]:
    p = mdir / "strip_gold.json"
    if not p.exists():
        return []
    obj = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(obj, list):
        return obj
    return list(obj.get("chains") or [])


def _load_timeline_events(mdir: Path) -> List[Dict[str, Any]]:
    p = mdir / "timeline.json"
    if not p.exists():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    evs = raw.get("events") if isinstance(raw, dict) else raw
    out = []
    for i, e in enumerate(evs or []):
        if e.get("t_ms") is None or not e.get("type"):
            continue
        out.append(
            {
                "order": int(e.get("order", i)),
                "type": e["type"],
                "t_ms": int(e["t_ms"]),
                "event_id": e.get("event_id") or f"t{i:04d}",
            }
        )
    out.sort(key=lambda x: (x["t_ms"], x["order"]))
    return out


def _gold_events_stream(golds: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """可控回放：本场全部 gold 事件按 t_ms 合并去重。"""
    seen = set()
    out: List[Dict[str, Any]] = []
    for g in golds:
        for e in g.get("events") or []:
            if e.get("t_ms") is None or not e.get("type"):
                continue
            key = (int(e["t_ms"]), str(e["type"]))
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "order": len(out),
                    "type": str(e["type"]),
                    "t_ms": int(e["t_ms"]),
                    "event_id": e.get("event_id") or f"g{len(out):04d}",
                }
            )
    out.sort(key=lambda x: (x["t_ms"], x["order"]))
    for i, e in enumerate(out):
        e["order"] = i
    return out


def _oracle_slice(
    timeline: Sequence[Dict[str, Any]], gold: Dict[str, Any]
) -> List[Dict[str, Any]]:
    t0, t1 = int(gold["t0_ms"]), int(gold["t1_ms"])
    sl = [e for e in timeline if t0 <= int(e["t_ms"]) <= t1]
    if sl:
        return sl
    # 时钟错位时回退 gold 自身事件（仍是 oracle 边界，非评测触发器）
    return [
        {
            "order": j,
            "type": e.get("type"),
            "t_ms": int(e["t_ms"]),
            "event_id": e.get("event_id") or f"og{j:04d}",
        }
        for j, e in enumerate(gold.get("events") or [])
        if e.get("t_ms") is not None and e.get("type")
    ]


def run_offline_classify(
    golds: List[Dict[str, Any]],
    *,
    model=None,
    processor=None,
    device: str = "cpu",
    use_llm: bool = False,
    profile_name: str = "production",
) -> Dict[str, Any]:
    """离线分类完整率：gold 事件序列 → classify_record_v4（与 8.31 拆条列同构）。"""
    from causal_chain6.config import load_profile
    from causal_chain6.io.eval_record import EvalRecord
    from causal_chain6.llm.agent import classify_record_v4
    from causal_chain6.schema.templates import CHAIN4_TEMPLATES

    profile = dict(load_profile(profile_name))
    profile.setdefault("llm", {})
    profile["llm"] = dict(profile.get("llm") or {})
    profile["llm"]["enabled"] = bool(use_llm and model is not None)

    preds: List[Dict[str, Any]] = []
    for i, g in enumerate(golds):
        events = []
        for j, e in enumerate(g.get("events") or []):
            events.append(
                {
                    "order": int(e.get("order", j)),
                    "type": e.get("type") or "",
                    "t_ms": int(e.get("t_ms") or 0),
                    "event_id": e.get("event_id") or f"e{j:04d}",
                }
            )
        if not events:
            continue
        rec = EvalRecord(
            annotation_id=str(g.get("annotation_id") or f"strip_{i}"),
            match_id=str(g.get("match_id") or "eval"),
            gold_template_id="",
            gold_category=str(g.get("chain_category") or ""),
            gold_label_zh="",
            gold_category_zh="",
            events_raw=list(events),
            events_normalized=list(events),
            events_extracted=list(events),
        )
        result = classify_record_v4(
            rec,
            profile=profile,
            model=model,
            processor=processor,
            device=device,
            max_new_tokens=512,
        )
        tid = result.chain_template_id
        cat = result.chain_category or (CHAIN4_TEMPLATES.get(tid) or {}).get("category") or ""
        preds.append(
            {
                "chain_category": cat,
                "first_event": events[0]["type"],
                "last_event": events[-1]["type"],
                "t0_ms": int(g["t0_ms"]),
                "t1_ms": int(g["t1_ms"]),
                "template_id": tid,
            }
        )
    rows = match_golds_to_preds(golds, preds)
    return {"summary": summarize(rows), "rows": rows, "backend": "causal_chain6.classify"}


def prefix_replay(
    events: List[Dict[str, Any]],
    adapter: AlgoStripAdapter,
    *,
    match_id: str,
    stride: int = 1,
    min_prefix: int = 1,
) -> List[Tuple[int, List[Dict[str, Any]]]]:
    """按时间序增大 prefix，每次只喂当前 prefix（batch/stateless）。"""
    n = len(events)
    if n == 0:
        return []
    stride = max(1, int(stride))
    min_prefix = max(1, int(min_prefix))
    out: List[Tuple[int, List[Dict[str, Any]]]] = []
    indices = list(range(min_prefix, n + 1, stride))
    if indices[-1] != n:
        indices.append(n)
    for i in indices:
        prefix = events[:i]
        t_i = int(prefix[-1]["t_ms"])
        preds = adapter.predict(prefix, match_id=match_id)
        out.append((t_i, preds))
    return out


def online_replay(
    events: List[Dict[str, Any]],
    adapter: OnlineStripAdapter,
    *,
    match_id: str,
    stride: int = 1,
    min_prefix: int = 1,
) -> List[Tuple[int, List[Dict[str, Any]]]]:
    """P3.1：逐事件 feed + 时钟推进；在 deadline 与采样步输出 candidate chains。"""
    n = len(events)
    if n == 0:
        return []
    stride = max(1, int(stride))
    min_prefix = max(1, int(min_prefix))
    adapter.reset(match_id=match_id)
    out: List[Tuple[int, List[Dict[str, Any]]]] = []
    n_fed = 0

    def _drain_until(until_ms: Optional[int]) -> None:
        while True:
            d = adapter.next_deadline_ms()
            if d is None:
                break
            if until_ms is not None and d >= until_ms:
                break
            preds = adapter.advance_time(d)
            if n_fed >= min_prefix:
                out.append((int(d), preds))

    for i, ev in enumerate(events):
        t_ev = int(ev["t_ms"])
        _drain_until(t_ev)
        preds = adapter.feed(ev)
        n_fed += 1
        step = i + 1
        if step < min_prefix:
            continue
        if (step - min_prefix) % stride != 0 and step != n:
            continue
        out.append((t_ev, preds))

    # 末事件之后：推进所有已武装 deadline，再 flush（对齐 batch full）
    _drain_until(None)
    preds = adapter.flush()
    t_final = int(events[-1]["t_ms"])
    if adapter.clock_ms is not None:
        t_final = max(t_final, int(adapter.clock_ms))
    out.append((t_final, preds))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="8.31 stream strip eval (prefix replay)")
    ap.add_argument("--limit-matches", type=int, default=0)
    ap.add_argument("--model-path", type=str, default="", help="Qwen 权重目录；空则 rule-only")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--profile", default="production")
    ap.add_argument("--rule-only", action="store_true")
    ap.add_argument("--use-llm", action="store_true")
    ap.add_argument(
        "--stream-source",
        choices=["timeline", "gold_events"],
        default="timeline",
        help="timeline=检测事件流(更真)；gold_events=标注事件合并流(更齐)",
    )
    ap.add_argument(
        "--adapter",
        choices=["batch", "online"],
        default="batch",
        help="batch=prefix replay + AlgoStripAdapter；online=P3 stateful feed",
    )
    ap.add_argument("--prefix-stride", type=int, default=1, help="每隔 k 个事件跑一次 predict/feed")
    ap.add_argument("--min-prefix", type=int, default=2)
    ap.add_argument(
        "--sliding-recall",
        action="store_true",
        default=True,
        help="打开 strip 滑窗召回（默认开，对齐算法 strip 管线）",
    )
    ap.add_argument("--no-sliding-recall", action="store_true", help="关闭滑窗（加速）")
    ap.add_argument("--run-a", action="store_true", default=True)
    ap.add_argument("--run-b", action="store_true", default=True)
    ap.add_argument("--run-c", action="store_true", default=False, help="前缀曲线（较重）")
    ap.add_argument("--run-offline", action="store_true", default=True)
    ap.add_argument("--no-b", action="store_true")
    ap.add_argument("--no-offline", action="store_true")
    ap.add_argument("--with-c", action="store_true")
    args = ap.parse_args()

    if args.no_b:
        args.run_b = False
    if args.no_offline:
        args.run_offline = False
    if args.with_c:
        args.run_c = True

    use_llm = (not args.rule_only) and (args.use_llm or False)
    if args.rule_only:
        use_llm = False
    use_sliding = not bool(args.no_sliding_recall)

    model = processor = None
    if use_llm:
        from causal_chain2.llm_qwen import load_qwen

        print(f"loading Qwen from {args.model_path} on {args.device} ...", flush=True)
        model, processor = load_qwen(args.model_path, args.device)

    if args.adapter == "online":
        adapter = OnlineStripAdapter(
            profile_name=args.profile,
            model=model,
            processor=processor,
            device=args.device if use_llm else "cpu",
            use_llm=use_llm,
            use_sliding_recall=use_sliding,
        )
    else:
        adapter = AlgoStripAdapter(
            profile_name=args.profile,
            model=model,
            processor=processor,
            device=args.device if use_llm else "cpu",
            use_llm=use_llm,
            use_sliding_recall=use_sliding,
        )

    index = json.loads((DATA / "index.json").read_text(encoding="utf-8"))
    matches = index["matches"]
    if args.limit_matches > 0:
        matches = matches[: args.limit_matches]

    OUT.mkdir(parents=True, exist_ok=True)

    offline_rows_all: List[Dict[str, Any]] = []
    stream_parts: List[Dict[str, Any]] = []
    oracle_preds_all: List[List[Dict[str, Any]]] = []
    oracle_golds_all: List[Dict[str, Any]] = []
    curves: List[Dict[str, Any]] = []
    all_timeline_preds: List[Tuple[int, List[Dict[str, Any]]]] = []
    # 全局 A：按场合并后再汇总更清晰——每场单独 score 再加权
    stream_summaries = []

    for mi, meta in enumerate(matches):
        mdir = ROOT / meta["dir"]
        golds = _load_strip_gold(mdir)
        print(
            f"[{mi+1}/{len(matches)}] {meta['safe_id'][:48]} gold={len(golds)}",
            flush=True,
        )
        if not golds:
            continue

        if args.run_offline:
            off = run_offline_classify(
                golds,
                model=model,
                processor=processor,
                device=args.device if use_llm else "cpu",
                use_llm=use_llm,
                profile_name=args.profile,
            )
            offline_rows_all.extend(off["rows"])
            print("  offline", off["summary"], flush=True)

        if args.stream_source == "gold_events":
            events = _gold_events_stream(golds)
        else:
            events = _load_timeline_events(mdir)
        print(
            f"  stream_source={args.stream_source} n_events={len(events)} "
            f"sliding={use_sliding} stride={args.prefix_stride}",
            flush=True,
        )

        timeline_preds: List[Tuple[int, List[Dict[str, Any]]]] = []
        if args.run_a or args.run_c:
            mid = str(meta.get("safe_id") or meta.get("match_id") or f"m{mi}")
            if args.adapter == "online":
                timeline_preds = online_replay(
                    events,
                    adapter,
                    match_id=mid,
                    stride=args.prefix_stride,
                    min_prefix=args.min_prefix,
                )
            else:
                timeline_preds = prefix_replay(
                    events,
                    adapter,
                    match_id=mid,
                    stride=args.prefix_stride,
                    min_prefix=args.min_prefix,
                )
            print(f"  stream_steps={len(timeline_preds)} adapter={args.adapter}", flush=True)

        if args.run_a and timeline_preds:
            sm = score_stream_match(golds, timeline_preds, require_strict=True)
            # 精简落盘
            slim = {
                k: v
                for k, v in sm.items()
                if k not in ("gold_rows", "emits", "tracks")
            }
            slim["n_gold_rows"] = len(sm.get("gold_rows") or [])
            slim["n_tracks"] = sm.get("n_tracks") or sm.get("n_emit_deduped")
            stream_summaries.append(slim)
            stream_parts.append(
                {
                    "safe_id": meta["safe_id"],
                    "summary": slim,
                    "gold_rows": sm.get("gold_rows"),
                    # 样例核查用：只保留演化长度>1 的 track 摘要
                    "tracks_multi": [
                        t for t in (sm.get("tracks") or []) if int(t.get("n_states") or 0) > 1
                    ][:20],
                }
            )
            print(
                "  streamA",
                {
                    k: slim[k]
                    for k in (
                        "n_gold",
                        "n_tracks",
                        "strict_rate",
                        "recall_rate",
                        "precision_rate",
                        "latency_ms_p50",
                        "latency_ms_p90",
                    )
                    if k in slim
                },
                flush=True,
            )

        if args.run_b:
            preds_per = []
            for g in golds:
                # B：oracle 输入边界上的真实流切片。timeline 空切片不回退补 gold.events
                # （避免主评测隐性对齐）；gold_events 源下切片即标注事件本身。
                if args.stream_source == "gold_events":
                    sl = _oracle_slice(events, g)
                    if not sl:
                        sl = _oracle_slice([], g)
                else:
                    t0, t1 = int(g["t0_ms"]), int(g["t1_ms"])
                    sl = [e for e in events if t0 <= int(e["t_ms"]) <= t1]
                preds_per.append(adapter.predict(sl, match_id="oracle") if sl else [])
            oracle_golds_all.extend(golds)
            oracle_preds_all.extend(preds_per)

        if args.run_c and timeline_preds:
            for g in golds:
                curves.append(
                    {
                        "safe_id": meta["safe_id"],
                        "annotation_id": g.get("annotation_id"),
                        "t_ready": gold_t_ready(g),
                        "curve": prefix_curve_for_gold(g, timeline_preds),
                    }
                )

        partial = {
            "done_matches": mi + 1,
            "offline": summarize(offline_rows_all) if offline_rows_all else {},
            "stream_source": args.stream_source,
        }
        (OUT / "report_stream_partial.json").write_text(
            json.dumps(partial, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    offline_sum = summarize(offline_rows_all) if offline_rows_all else {}
    # 合并各场 stream 指标（按 gold 加权）
    stream_sum: Dict[str, Any] = {}
    if stream_parts:
        n_g = sum(int(p["summary"]["n_gold"]) for p in stream_parts)
        n_s = sum(int(p["summary"]["strict_complete"]) for p in stream_parts)
        n_m = sum(int(p["summary"]["recall_matched"]) for p in stream_parts)
        n_aux = sum(int(p["summary"]["aux_time_cat_complete"]) for p in stream_parts)
        n_emit = sum(int(p["summary"].get("n_tracks") or p["summary"]["n_emit_deduped"]) for p in stream_parts)
        n_ph = sum(int(p["summary"]["precision_hits"]) for p in stream_parts)
        lats = []
        for p in stream_parts:
            for r in p.get("gold_rows") or []:
                if r.get("latency_ms") is not None:
                    lats.append(int(r["latency_ms"]))
        lats.sort()

        def _pct(a, b):
            return round(100.0 * a / b, 2) if b else 0.0

        def _q(q):
            if not lats:
                return None
            return float(lats[int(round(q * (len(lats) - 1)))])

        stream_sum = {
            "n_gold": n_g,
            "n_emit_deduped": n_emit,
            "n_tracks": n_emit,
            "recall_matched": n_m,
            "n_matched_gold": n_m,
            "n_unique_matched_tracks": n_ph,
            "one_to_one_ok": n_m == n_ph,
            "recall_rate": _pct(n_m, n_g),
            "strict_complete": n_s,
            "strict_rate": _pct(n_s, n_g),
            "aux_time_cat_complete": n_aux,
            "aux_time_cat_rate": _pct(n_aux, n_g),
            "precision_hits": n_ph,
            "precision_rate": _pct(n_ph, n_emit),
            "latency_ms_p50": _q(0.5),
            "latency_ms_p90": _q(0.9),
            "latency_ms_mean": round(sum(lats) / len(lats), 1) if lats else None,
            "dedupe_mode": "candidate_track_continuity",
            "match_mode": "bipartite_max_weight_one_to_one",
        }

    oracle_sum = {}
    if oracle_golds_all:
        oracle_sum = score_oracle_upper(oracle_golds_all, oracle_preds_all)
        oracle_sum = {k: v for k, v in oracle_sum.items() if k != "rows"}

    table_row = {
        "测试阶段": "中期测试",
        "测试模块": "因果链编排算法工具 v2.x (8.31 流式拆条 Phase1)",
        "离线分类严格完整率": f"{offline_sum.get('strict_rate', 0)}%",
        "流式拆条严格完整率": f"{stream_sum.get('strict_rate', 0)}%",
        "流式召回率": f"{stream_sum.get('recall_rate', 0)}%",
        "流式精确率(track连续性)": f"{stream_sum.get('precision_rate', 0)}%",
        "流式candidate数(tracks)": stream_sum.get("n_tracks"),
        "流式时延P50_ms": stream_sum.get("latency_ms_p50"),
        "流式时延P90_ms": stream_sum.get("latency_ms_p90"),
        "B上界严格完整率": f"{oracle_sum.get('strict_rate', 0)}%",
        "stream_source": args.stream_source,
        "rule_only": not use_llm,
        "sliding_recall": use_sliding,
        "prefix_stride": args.prefix_stride,
        "adapter": adapter.config_snapshot(),
        "dedupe_mode": "candidate_track_continuity",
        "match_mode": "bipartite_max_weight_one_to_one",
        "matched_gold": stream_sum.get("n_matched_gold"),
        "unique_matched_tracks": stream_sum.get("n_unique_matched_tracks"),
        "one_to_one_ok": stream_sum.get("one_to_one_ok"),
        "note": "评测只造流；跨prefix用track连续性；gold↔track一对一最大权匹配；触发/lookback属算法profile.strip",
    }

    report = {
        "table_row": table_row,
        "offline_classify": offline_sum,
        "stream_A": stream_sum,
        "stream_A_prefix_replay": stream_sum,
        "stream_A_mode": args.adapter,
        "stream_B_oracle_upper": oracle_sum,
        "per_match_stream": [
            {"safe_id": p["safe_id"], "summary": p["summary"]} for p in stream_parts
        ],
        "prefix_curves_C": curves if args.run_c else [],
        "config": {
            "use_llm": use_llm,
            "stream_source": args.stream_source,
            "prefix_stride": args.prefix_stride,
            "min_prefix": args.min_prefix,
            "sliding_recall": use_sliding,
            "n_matches": len(matches),
            "adapter_mode": args.adapter,
            "adapter": adapter.config_snapshot(),
            "dedupe": "candidate_track_continuity",
            "phase": "P3_online" if args.adapter == "online" else 1,
        },
        "baseline_before_track_link": {
            "note": "修改前 rule-only+gold_events（签名首次出现）",
            "n_emit_deduped": 1474,
            "strict_rate": 74.37,
            "precision_rate": 21.23,
            "B_strict_rate": 81.46,
            "offline_strict_rate": 90.62,
        },
    }
    tag = "llm" if use_llm else "rule"
    adapter_tag = args.adapter
    out_path = OUT / f"report_stream_strip_{tag}_{adapter_tag}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.adapter == "batch":
        legacy_path = OUT / f"report_stream_strip_{tag}.json"
        legacy_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "table_row_stream_strip.json").write_text(
        json.dumps(table_row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("\n==== 填表/对照 ====", flush=True)
    print(json.dumps(table_row, ensure_ascii=False, indent=2), flush=True)
    print(f"wrote {out_path}", flush=True)


if __name__ == "__main__":
    main()
