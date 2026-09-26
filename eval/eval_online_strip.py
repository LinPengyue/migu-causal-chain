#!/usr/bin/env python3
"""在线拆条因果链逻辑完整率。

event stream → OnlineStripEngine (feed/advance_time) → one-to-one gold match
禁止未来事件。
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

from eval_common import (  # noqa: E402
    REPORTS,
    ROOT as _ROOT,
    base_report,
    fmt_pct,
    gold_events_stream,
    load_index,
    load_strip_gold,
    load_timeline_events,
    make_match_pbar,
    pct,
    pctile,
)
from run_stream_strip import online_replay  # noqa: E402
from stream_metrics import score_stream_match  # noqa: E402
from strip_adapter import OnlineStripAdapter  # noqa: E402

LATENCY_GT_MS = 45_000


def main(argv: List[str] | None = None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="Online strip logic-complete")
    ap.add_argument("--limit-matches", type=int, default=0, help="0=全部场次（默认）")
    ap.add_argument("--profile", default="production")
    ap.add_argument("--stream-source", choices=["gold_events", "timeline"], default="gold_events")
    ap.add_argument("--prefix-stride", type=int, default=1)
    ap.add_argument("--min-prefix", type=int, default=2)
    ap.add_argument("--out", type=Path, default=REPORTS / "eval_online_strip.json")
    args = ap.parse_args(argv)

    adapter = OnlineStripAdapter(profile_name=args.profile, use_llm=False, use_sliding_recall=True)
    matches = load_index()["matches"]
    if args.limit_matches > 0:
        matches = matches[: args.limit_matches]

    n_gold = n_matched = n_tracks = n_strict = n_prec = 0
    lats: List[int] = []

    pbar = make_match_pbar("Online Strip", len(matches))
    try:
        for mi, meta in enumerate(matches):
            mdir = _ROOT / meta["dir"]
            golds = load_strip_gold(mdir)
            if golds:
                if args.stream_source == "gold_events":
                    events = gold_events_stream(golds)
                else:
                    events = load_timeline_events(mdir)
                mid = str(meta.get("safe_id") or f"m{mi}")
                timeline_preds = online_replay(
                    events,
                    adapter,
                    match_id=mid,
                    stride=args.prefix_stride,
                    min_prefix=args.min_prefix,
                )
                sm = score_stream_match(golds, timeline_preds, require_strict=True)
                n_gold += int(sm["n_gold"])
                n_matched += int(sm["recall_matched"])
                n_tracks += int(sm.get("n_tracks") or sm["n_emit_deduped"])
                n_strict += int(sm["strict_complete"])
                n_prec += int(sm["precision_hits"])
                for r in sm.get("gold_rows") or []:
                    if r.get("latency_ms") is not None:
                        lats.append(int(r["latency_ms"]))

            n_over = sum(1 for x in lats if x > LATENCY_GT_MS)
            p50 = pctile(lats, 0.5)
            p90 = pctile(lats, 0.9)
            pbar.set_postfix_str(
                f"gold={n_gold} matched={n_strict} "
                f"logic={fmt_pct(pct(n_strict, n_gold))} "
                f"precision={fmt_pct(pct(n_prec, n_tracks))} "
                f"P50={p50 if p50 is not None else 'n/a'} "
                f"P90={p90 if p90 is not None else 'n/a'} "
                f">45s={fmt_pct(pct(n_over, len(lats)))}",
                refresh=False,
            )
            pbar.update(1)
    finally:
        pbar.close()

    n_over = sum(1 for x in lats if x > LATENCY_GT_MS)
    report = base_report(
        task="online_strip",
        config={
            "profile": args.profile,
            "adapter": "OnlineStripAdapter",
            "stream_source": args.stream_source,
            "use_llm": False,
            "prefix_stride": args.prefix_stride,
            "min_prefix": args.min_prefix,
            "limit_matches": args.limit_matches,
        },
    )
    report.update(
        {
            "total_gold": n_gold,
            "strict_matched": n_strict,
            "logic_complete_rate": pct(n_strict, n_gold),
            "precision": pct(n_prec, n_tracks),
            "latency_p50": pctile(lats, 0.5),
            "latency_p90": pctile(lats, 0.9),
            "over_45s_rate": pct(n_over, len(lats)),
            "n_matched": n_matched,
            "n_tracks": n_tracks,
            "n_matches": len(matches),
            "data_sources": {
                "gold": "strip_gold.json",
                "stream": "gold_events merged" if args.stream_source == "gold_events" else "timeline.json",
            },
            "note": "P3 online feed/advance_time; no future events; bipartite one-to-one",
        }
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "task",
                    "total_gold",
                    "strict_matched",
                    "logic_complete_rate",
                    "precision",
                    "latency_p50",
                    "latency_p90",
                    "over_45s_rate",
                )
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    print(f"wrote {args.out}", flush=True)
    return report


if __name__ == "__main__":
    main()
