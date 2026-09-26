#!/usr/bin/env python3
"""离线集锦因果链逻辑完整率。

逻辑完整率：select_moments → classify/refine → highlight clips ↔ highlight_gold*
一对一 strict（time overlap + category + first + last）。

P5 link_strip_chains 仅作独立结构回归，不计入 logic_complete_rate。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "algo"))
sys.path.insert(0, str(ROOT / "eval"))

from causal_chain6.config import load_profile as load_c6_profile  # noqa: E402
from causal_chain6.strip_pipeline import run_strip_highlights_events  # noqa: E402
from causal_chain8.config import load_profile as load_c8_profile  # noqa: E402
from causal_chain8.link_strip_chains import build_match_highlight_chain  # noqa: E402
from eval_common import (  # noqa: E402
    REPORTS,
    ROOT as _ROOT,
    base_report,
    build_highlight_clips,
    clip_to_strip_chain,
    fmt_pct,
    has_cycle,
    highlight_clip_to_pred,
    highlight_logic_by_label_source,
    label_source_counts,
    load_highlight_gold,
    load_index,
    load_timeline_events,
    make_match_pbar,
    pct,
    should_drop_t2_for_gold,
)
from metrics import match_golds_to_preds, summarize  # noqa: E402


def _strip_clips(events: List[Dict[str, Any]], *, match_id: str, profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    s = profile.get("strip") or {}
    out = run_strip_highlights_events(
        events=events,
        match_id=match_id[:32],
        profile=profile,
        model=None,
        processor=None,
        device="cpu",
        max_new_tokens=512,
        pre_ms=int(s.get("pre_ms", 120_000)),
        post_ms=int(s.get("post_ms", 60_000)),
        window_ms=int(s.get("window_ms", 180_000)),
        step_ms=int(s.get("step_ms", 90_000)),
        min_margin=float(s.get("min_margin", 0.08)),
        min_prob_top1=0.0,
        iou_dedupe_thresh=float(s.get("iou_dedupe", 0.5)),
        iou_recall_thresh=float(s.get("iou_recall", 0.45)),
        max_events=int(s.get("max_events", 12)),
        use_sliding_recall=True,
        template_whitelist=None,
        sliding_merge_mode=str(s.get("sliding_merge_mode", "none")),
        sliding_post_nms=str(s.get("sliding_post_nms", "off")),
    )
    return list(out.get("clips") or [])


def _structural_check(clips: List[Dict[str, Any]], doc: Dict[str, Any]) -> Dict[str, Any]:
    nodes = doc.get("nodes") or []
    nids = [n["strip_chain_id"] for n in nodes]
    dup = len(nids) != len(set(nids))
    loss = len(nodes) != len(clips)
    cycle = has_cycle(nids, doc.get("edges") or [])
    chains = [clip_to_strip_chain(c, index=i) for i, c in enumerate(clips)]
    doc2 = build_match_highlight_chain(chains, match_id=doc.get("match_id") or "", source="strip")
    stable = (doc.get("highlight_chain") or {}).get("ordering") == (doc2.get("highlight_chain") or {}).get(
        "ordering"
    )
    ord_map = {c: i for i, c in enumerate((doc.get("highlight_chain") or {}).get("ordering") or [])}
    corr_ok = True
    for e in doc.get("edges") or []:
        if e.get("rel") != "correction_of":
            continue
        if ord_map.get(e["src"], -1) >= ord_map.get(e["dst"], -1):
            corr_ok = False
            break
    ok = (not dup) and (not loss) and (not cycle) and stable and corr_ok
    return {
        "ok": ok,
        "node_loss": loss,
        "duplicate": dup,
        "cycle": cycle,
        "ordering_stable": stable,
        "correction_order_ok": corr_ok,
        "n_nodes": len(nodes),
        "n_clips": len(clips),
    }


def main(argv: List[str] | None = None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="Offline highlight clips logic-complete")
    ap.add_argument("--limit-matches", type=int, default=0, help="0=全部场次（默认）")
    ap.add_argument("--profile", default="production")
    ap.add_argument("--out", type=Path, default=REPORTS / "eval_offline_highlight.json")
    args = ap.parse_args(argv)

    c8_profile = dict(load_c8_profile(args.profile))
    c8_profile.setdefault("llm", {})
    c8_profile["llm"] = dict(c8_profile.get("llm") or {})
    c8_profile["llm"]["enabled"] = False

    c6_profile = dict(load_c6_profile(args.profile))
    c6_profile.setdefault("llm", {})
    c6_profile["llm"] = dict(c6_profile.get("llm") or {})
    c6_profile["llm"]["enabled"] = False

    matches = load_index()["matches"]
    if args.limit_matches > 0:
        matches = matches[: args.limit_matches]

    gold_rows: List[Dict[str, Any]] = []
    golds_flat: List[Dict[str, Any]] = []
    n_with_gold = 0
    n_structural_pass = 0
    n_structural_fail = 0
    n_pred_clips = 0
    fail_flags = {"node_loss": 0, "duplicate": 0, "cycle": 0, "ordering": 0, "correction": 0}
    gold_file_counts: Dict[str, int] = {}
    label_src_counts = {"annotation": 0, "timeline_heuristic": 0}

    pbar = make_match_pbar("Offline Highlight", len(matches))
    try:
        for mi, meta in enumerate(matches):
            mdir = _ROOT / meta["dir"]
            mid = str(meta.get("safe_id") or f"m{mi}")
            events = load_timeline_events(mdir)
            hl_gold, src_name = load_highlight_gold(mdir)

            strip_clips = _strip_clips(events, match_id=mid, profile=c6_profile) if events else []
            chains = [clip_to_strip_chain(c, index=i) for i, c in enumerate(strip_clips)]
            doc = build_match_highlight_chain(chains, match_id=mid, source="causal_chain6_strip")
            st = _structural_check(strip_clips, doc)
            if st["ok"]:
                n_structural_pass += 1
            else:
                n_structural_fail += 1
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
                hl_clips, _stats = (
                    build_highlight_clips(
                        events,
                        match_id=mid,
                        profile=c8_profile,
                        drop_t2=drop_t2,
                    )
                    if events
                    else ([], {})
                )
                preds = [highlight_clip_to_pred(c) for c in hl_clips]
                n_pred_clips += len(preds)
                rows = match_golds_to_preds(hl_gold, preds)
                gold_rows.extend(rows)
                golds_flat.extend(hl_gold)

            if gold_rows:
                summ = summarize(gold_rows)
                n_gold = int(summ.get("n") or 0)
                n_strict = int(summ.get("strict_complete") or 0)
                by_src = highlight_logic_by_label_source(golds_flat, gold_rows)
                ann_logic = (by_src.get("annotation_only") or {}).get("logic_complete_rate")
            else:
                n_gold = n_strict = 0
                ann_logic = None
            pbar.set_postfix_str(
                f"gold={n_gold} matched={n_strict} "
                f"logic={fmt_pct(pct(n_strict, n_gold) if n_gold else None)} "
                f"annotation_logic={fmt_pct(ann_logic)}",
                refresh=False,
            )
            pbar.update(1)
    finally:
        pbar.close()

    n_ran = len(matches)
    report = base_report(
        task="offline_highlight",
        config={
            "profile": args.profile,
            "pipeline": "select_moments→classify/refine→clips (logic); strip→P5 graph (structural only)",
            "use_llm": False,
            "limit_matches": args.limit_matches,
        },
    )
    report["n_matches"] = n_ran
    report["data_sources"] = {
        "events": "timeline.json",
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
        "structural_pass_rate": pct(n_structural_pass, n_ran),
        "node_loss": fail_flags["node_loss"],
        "duplicate": fail_flags["duplicate"],
        "cycle": fail_flags["cycle"],
        "ordering": fail_flags["ordering"],
        "correction": fail_flags["correction"],
        "n_pass": n_structural_pass,
        "n_fail": n_structural_fail,
        "note": "P5 graph structural regression only; not logic_complete_rate",
    }

    if gold_rows:
        summ = summarize(gold_rows)
        report["total_gold"] = int(summ.get("n") or 0)
        report["strict_matched"] = int(summ.get("strict_complete") or 0)
        report["logic_complete_rate"] = summ.get("strict_rate")
        report["precision"] = pct(int(summ.get("strict_complete") or 0), n_pred_clips)
        report["by_label_source"] = highlight_logic_by_label_source(golds_flat, gold_rows)
        report["note"] = (
            "logic_complete_rate = highlight clips vs highlight gold one-to-one strict; "
            "P5 nodes excluded"
        )
    else:
        report["total_gold"] = 0
        report["strict_matched"] = 0
        report["logic_complete_rate"] = None
        report["precision"] = None
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
                "total_gold": report["total_gold"],
                "strict_matched": report["strict_matched"],
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
