#!/usr/bin/env python3
"""离线拆条因果链逻辑完整率（B 类口径）。

clip/events → causal_chain6 strip → pred → one-to-one strict match
禁止 gold.events → classify；禁止 timeline 空窗静默 fallback。
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
    clip_events_for_gold,
    fmt_pct,
    load_index,
    load_strip_gold,
    load_timeline_events,
    make_match_pbar,
    pct,
)
from stream_metrics import score_oracle_upper  # noqa: E402
from strip_adapter import AlgoStripAdapter  # noqa: E402


def main(argv: List[str] | None = None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="Offline strip logic-complete (B-style)")
    ap.add_argument(
        "--event-source",
        choices=["timeline", "gold_events"],
        required=True,
        help="timeline=按 gold 窗切片（空=unscorable）；gold_events=单模块评测",
    )
    ap.add_argument("--limit-matches", type=int, default=0, help="0=全部场次（默认）")
    ap.add_argument("--profile", default="production")
    ap.add_argument("--out", type=Path, default=REPORTS / "eval_offline_strip.json")
    args = ap.parse_args(argv)

    adapter = AlgoStripAdapter(profile_name=args.profile, use_llm=False, use_sliding_recall=True)
    matches = load_index()["matches"]
    if args.limit_matches > 0:
        matches = matches[: args.limit_matches]

    golds_all: List[Dict[str, Any]] = []
    preds_per: List[List[Dict[str, Any]]] = []
    n_pred = 0
    n_unscorable = 0
    n_scorable = 0

    pbar = make_match_pbar("Offline Strip", len(matches))
    try:
        for mi, meta in enumerate(matches):
            mdir = _ROOT / meta["dir"]
            golds = load_strip_gold(mdir)
            timeline = load_timeline_events(mdir) if args.event_source == "timeline" else []
            mid = str(meta.get("safe_id") or f"m{mi}")
            if golds:
                for g in golds:
                    clip = clip_events_for_gold(g, timeline, event_source=args.event_source)
                    if not clip:
                        n_unscorable += 1
                        continue
                    preds = adapter.predict(clip, match_id=f"{mid}_oracle")
                    golds_all.append(g)
                    preds_per.append(preds)
                    n_pred += len(preds)
                    n_scorable += 1

            scored = (
                score_oracle_upper(golds_all, preds_per)
                if golds_all
                else {"n_gold": 0, "strict_complete": 0}
            )
            n_gold = int(scored["n_gold"])
            n_strict = int(scored["strict_complete"])
            pbar.set_postfix_str(
                f"gold={n_gold} matched={n_strict} "
                f"logic={fmt_pct(pct(n_strict, n_gold))} "
                f"precision={fmt_pct(pct(n_strict, n_pred) if n_pred else None)}",
                refresh=False,
            )
            pbar.update(1)
    finally:
        pbar.close()

    scored = score_oracle_upper(golds_all, preds_per) if golds_all else {
        "n_gold": 0,
        "strict_complete": 0,
        "strict_rate": None,
    }
    n_gold = int(scored["n_gold"])
    n_strict = int(scored["strict_complete"])
    report = base_report(
        task="offline_strip",
        config={
            "profile": args.profile,
            "adapter": "AlgoStripAdapter",
            "mode": "per_gold_clip_strip_B",
            "event_source": args.event_source,
            "use_llm": False,
            "limit_matches": args.limit_matches,
        },
    )
    report.update(
        {
            "total_gold": n_gold,
            "strict_matched": n_strict,
            "logic_complete_rate": pct(n_strict, n_gold) if n_gold else None,
            "precision": pct(n_strict, n_pred) if n_pred else (0.0 if n_gold else None),
            "n_matches": len(matches),
            "n_pred_total": n_pred,
            "n_scorable": n_scorable,
            "n_unscorable": n_unscorable,
            "data_sources": {
                "gold": "strip_gold.json",
                "event_source": args.event_source,
                "clip_events": (
                    "timeline slice by gold[t0,t1]; empty→unscorable"
                    if args.event_source == "timeline"
                    else "gold.events → strip (module eval; not classify)"
                ),
                "n_scorable": n_scorable,
                "n_unscorable": n_unscorable,
            },
            "note": (
                "B-style oracle clip strip; not offline classify; "
                "no silent timeline→gold.events fallback"
            ),
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
                    "n_unscorable",
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
