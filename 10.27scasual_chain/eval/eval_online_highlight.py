#!/usr/bin/env python3
"""在线集锦因果链逻辑完整率。

逻辑完整率：event prefix → select_moments→classify/refine clips；
跨 prefix candidate track，首次 strict 命中计成功。禁止未来事件。

终态可另跑 P5 graph 结构回归；graph 不参与 logic_complete_rate。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "algo"))
sys.path.insert(0, str(ROOT / "eval"))

from causal_chain8.config import load_profile as load_c8_profile  # noqa: E402
from causal_chain8.link_strip_chains import build_match_highlight_chain  # noqa: E402
from eval_common import (  # noqa: E402
    REPORTS,
    ROOT as _ROOT,
    base_report,
    build_highlight_clips,
    fmt_pct,
    gold_events_stream,
    has_cycle,
    highlight_clip_to_pred,
    highlight_logic_by_label_source,
    label_source_counts,
    load_highlight_gold,
    load_index,
    load_strip_gold,
    load_timeline_events,
    make_match_pbar,
    pct,
    pctile,
    should_drop_t2_for_gold,
)
from stream_metrics import score_stream_match  # noqa: E402
from strip_adapter import OnlineStripAdapter  # noqa: E402


def _pred_to_chain(p: Dict[str, Any], *, index: int) -> Dict[str, Any]:
    evs = []
    keys = p.get("event_keys") or []
    ids = p.get("event_ids") or []
    for j, k in enumerate(keys):
        if isinstance(k, (list, tuple)) and len(k) >= 2:
            ev: Dict[str, Any] = {"order": j, "t_ms": int(k[0]), "type": str(k[1])}
            if j < len(ids):
                ev["event_id"] = str(ids[j])
            evs.append(ev)
    return {
        "strip_chain_id": p.get("source") or f"online_{index:02d}",
        "t0_ms": p.get("t0_ms"),
        "t1_ms": p.get("t1_ms"),
        "chain_category": p.get("chain_category") or "",
        "template_id": p.get("template_id") or "",
        "first_event": p.get("first_event") or "",
        "last_event": p.get("last_event") or "",
        "events": evs,
    }


def online_highlight_clip_timeline(
    events: List[Dict[str, Any]],
    *,
    match_id: str,
    profile: Dict[str, Any],
    drop_t2: bool,
    min_prefix: int = 2,
    prefix_stride: int = 1,
) -> List[Tuple[int, List[Dict[str, Any]]]]:
    """按到达顺序对 prefix 跑 highlight selection；禁止未来事件。"""
    snaps: List[Tuple[int, List[Dict[str, Any]]]] = []
    n = len(events)
    if n < min_prefix:
        return snaps
    for i in range(min_prefix, n + 1):
        if prefix_stride > 1 and i != n and ((i - min_prefix) % prefix_stride) != 0:
            continue
        prefix = events[:i]
        t_i = int(prefix[-1]["t_ms"])
        clips, _ = build_highlight_clips(
            prefix,
            match_id=match_id,
            profile=profile,
            drop_t2=drop_t2,
        )
        preds = [highlight_clip_to_pred(c) for c in clips]
        snaps.append((t_i, preds))
    return snaps


def _p5_structural_from_online_strip(
    events: List[Dict[str, Any]],
    adapter: OnlineStripAdapter,
    *,
    match_id: str,
) -> Dict[str, Any]:
    adapter.reset(match_id=match_id)
    for ev in events:
        adapter.feed(ev)
        d = adapter.next_deadline_ms()
        while d is not None and d <= int(ev["t_ms"]):
            adapter.advance_time(d)
            d = adapter.next_deadline_ms()
    while adapter.next_deadline_ms() is not None:
        adapter.advance_time(adapter.next_deadline_ms())
    preds = adapter.flush()
    chains = [_pred_to_chain(p, index=i) for i, p in enumerate(preds)]
    for i, c in enumerate(chains):
        c["strip_chain_id"] = f"{match_id[:16]}_{i:03d}_{c['t0_ms']}_{c['t1_ms']}"
    doc = build_match_highlight_chain(chains, match_id=match_id, source="online_strip")
    nodes = doc.get("nodes") or []
    nids = [n["strip_chain_id"] for n in nodes]
    dup = len(nids) != len(set(nids))
    cycle = has_cycle(nids, doc.get("edges") or [])
    doc2 = build_match_highlight_chain(chains, match_id=match_id, source="online_strip")
    stable = (doc.get("highlight_chain") or {}).get("ordering") == (
        doc2.get("highlight_chain") or {}
    ).get("ordering")
    ord_map = {c: i for i, c in enumerate((doc.get("highlight_chain") or {}).get("ordering") or [])}
    corr_ok = True
    for e in doc.get("edges") or []:
        if e.get("rel") == "correction_of" and ord_map.get(e["src"], -1) >= ord_map.get(e["dst"], -1):
            corr_ok = False
            break
    loss = len(nodes) != len(preds)
    ok = (not dup) and (not cycle) and stable and corr_ok and (not loss)
    return {
        "ok": ok,
        "node_loss": loss,
        "duplicate": dup,
        "cycle": cycle,
        "ordering_stable": stable,
        "correction_order_ok": corr_ok,
        "n_nodes": len(nodes),
        "n_strip_preds": len(preds),
    }


def main(argv: List[str] | None = None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="Online highlight clips logic-complete")
    ap.add_argument("--limit-matches", type=int, default=0, help="0=全部场次（默认）")
    ap.add_argument("--profile", default="production")
    ap.add_argument("--stream-source", choices=["gold_events", "timeline"], default="gold_events")
    ap.add_argument("--min-prefix", type=int, default=2)
    ap.add_argument("--prefix-stride", type=int, default=1)
    ap.add_argument("--out", type=Path, default=REPORTS / "eval_online_highlight.json")
    args = ap.parse_args(argv)

    c8_profile = dict(load_c8_profile(args.profile))
    c8_profile.setdefault("llm", {})
    c8_profile["llm"] = dict(c8_profile.get("llm") or {})
    c8_profile["llm"]["enabled"] = False

    strip_adapter = OnlineStripAdapter(profile_name=args.profile, use_llm=False, use_sliding_recall=True)
    matches = load_index()["matches"]
    if args.limit_matches > 0:
        matches = matches[: args.limit_matches]

    n_gold = n_strict = n_tracks = n_prec = 0
    lats: List[int] = []
    gold_rows_all: List[Dict[str, Any]] = []
    golds_flat: List[Dict[str, Any]] = []
    n_with_gold = 0
    n_struct_pass = 0
    n_struct_fail = 0
    fail_flags = {"node_loss": 0, "duplicate": 0, "cycle": 0, "ordering": 0, "correction": 0}
    gold_file_counts: Dict[str, int] = {}
    label_src_counts = {"annotation": 0, "timeline_heuristic": 0}

    pbar = make_match_pbar("Online Highlight", len(matches))
    try:
        for mi, meta in enumerate(matches):
            mdir = _ROOT / meta["dir"]
            mid = str(meta.get("safe_id") or f"m{mi}")
            strip_golds = load_strip_gold(mdir)
            hl_gold, src_name = load_highlight_gold(mdir)
            if args.stream_source == "gold_events":
                events = gold_events_stream(strip_golds) if strip_golds else []
            else:
                events = load_timeline_events(mdir)

            if events:
                st = _p5_structural_from_online_strip(events, strip_adapter, match_id=mid)
                if st["ok"]:
                    n_struct_pass += 1
                else:
                    n_struct_fail += 1
                    if st["node_loss"]:
                        fail_flags["node_loss"] += 1
                    if st["duplicate"]:
                        fail_flags["duplicate"] += 1
                    if st["cycle"]:
                        fail_flags["cycle"] += 1
                    if not st["ordering_stable"]:
                        fail_flags["ordering"] += 1
                    if not st["correction_order_ok"]:
                        fail_flags["correction"] += 1

                if hl_gold:
                    n_with_gold += 1
                    gold_file_counts[src_name or "highlight_gold"] = (
                        gold_file_counts.get(src_name or "highlight_gold", 0) + 1
                    )
                    for k, v in label_source_counts(hl_gold).items():
                        label_src_counts[k] = label_src_counts.get(k, 0) + v
                    drop_t2 = should_drop_t2_for_gold(src_name, hl_gold)
                    timeline_preds = online_highlight_clip_timeline(
                        events,
                        match_id=mid,
                        profile=c8_profile,
                        drop_t2=drop_t2,
                        min_prefix=args.min_prefix,
                        prefix_stride=args.prefix_stride,
                    )
                    sm = score_stream_match(hl_gold, timeline_preds, require_strict=True)
                    n_gold += int(sm["n_gold"])
                    n_strict += int(sm["strict_complete"])
                    n_tracks += int(sm.get("n_tracks") or sm.get("n_emit_deduped") or 0)
                    n_prec += int(sm["precision_hits"])
                    rows = list(sm.get("gold_rows") or [])
                    gold_rows_all.extend(rows)
                    golds_flat.extend(hl_gold)
                    for r in rows:
                        if r.get("latency_ms") is not None:
                            lats.append(int(r["latency_ms"]))

            by_src = (
                highlight_logic_by_label_source(golds_flat, gold_rows_all)
                if gold_rows_all
                else {}
            )
            ann_logic = (by_src.get("annotation_only") or {}).get("logic_complete_rate")
            p50 = pctile(lats, 0.5)
            p90 = pctile(lats, 0.9)
            lat_part = ""
            if lats:
                lat_part = (
                    f" P50={p50} P90={p90} "
                    f">45s={fmt_pct(pct(sum(1 for x in lats if x > 45_000), len(lats)))}"
                )
            pbar.set_postfix_str(
                f"gold={n_gold} matched={n_strict} "
                f"logic={fmt_pct(pct(n_strict, n_gold))} "
                f"annotation_logic={fmt_pct(ann_logic)}{lat_part}",
                refresh=False,
            )
            pbar.update(1)
    finally:
        pbar.close()

    n_ran = n_struct_pass + n_struct_fail
    report = base_report(
        task="online_highlight",
        config={
            "profile": args.profile,
            "pipeline": "prefix select_moments→clips (logic); OnlineStrip→P5 (structural only)",
            "stream_source": args.stream_source,
            "use_llm": False,
            "min_prefix": args.min_prefix,
            "prefix_stride": args.prefix_stride,
            "limit_matches": args.limit_matches,
        },
    )
    report["n_matches"] = len(matches)
    report["data_sources"] = {
        "stream": args.stream_source,
        "highlight_gold_priority": [
            "highlight_gold_no_t2.json",
            "highlight_gold.json",
            "highlight_gold_with_t2.json",
        ],
        "n_matches_with_nonempty_highlight_gold": n_with_gold,
        "gold_file_counts": gold_file_counts,
        "label_source_counts": label_src_counts,
    }
    report["structural"] = {
        "structural_pass_rate": pct(n_struct_pass, n_ran) if n_ran else None,
        "node_loss": fail_flags["node_loss"],
        "duplicate": fail_flags["duplicate"],
        "cycle": fail_flags["cycle"],
        "ordering": fail_flags["ordering"],
        "correction": fail_flags["correction"],
        "n_pass": n_struct_pass,
        "n_fail": n_struct_fail,
        "incremental": True,
        "note": "P5 graph structural regression only; not logic_complete_rate",
    }

    if n_with_gold and n_gold > 0:
        report["total_gold"] = n_gold
        report["strict_matched"] = n_strict
        report["logic_complete_rate"] = pct(n_strict, n_gold)
        report["precision"] = pct(n_prec, n_tracks) if n_tracks else 0.0
        report["latency_p50"] = pctile(lats, 0.5)
        report["latency_p90"] = pctile(lats, 0.9)
        report["over_45s_rate"] = pct(sum(1 for x in lats if x > 45_000), len(lats))
        report["by_label_source"] = highlight_logic_by_label_source(golds_flat, gold_rows_all)
        report["note"] = (
            "logic_complete_rate from online highlight clips track+strict; "
            "P5 graph excluded"
        )
    else:
        report["logic_complete_rate"] = None
        report["by_label_source"] = highlight_logic_by_label_source([], [])
        report["note"] = (
            "no nonempty highlight-level gold; logic_complete_rate=null; "
            "structural only (not logic-complete)"
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "task": report["task"],
                "total_gold": report.get("total_gold"),
                "strict_matched": report.get("strict_matched"),
                "logic_complete_rate": report["logic_complete_rate"],
                "label_source_counts": label_src_counts,
                "structural_pass_rate": (report.get("structural") or {}).get("structural_pass_rate"),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    print(f"wrote {args.out}", flush=True)
    return report


if __name__ == "__main__":
    main()
