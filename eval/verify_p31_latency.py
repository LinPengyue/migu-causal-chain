#!/usr/bin/env python3
"""P3.1 验证：final equivalence + online strict/latency（含 >45s 比例）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "algo"))
sys.path.insert(0, str(ROOT / "eval"))

from run_stream_strip import (  # noqa: E402
    _gold_events_stream,
    _load_strip_gold,
    _load_timeline_events,
    online_replay,
)
from stream_metrics import score_stream_match  # noqa: E402
from strip_adapter import AlgoStripAdapter, OnlineStripAdapter  # noqa: E402

LATENCY_THRESH_MS = 45_000


def _pred_sig(p: Dict[str, Any]) -> Tuple[Any, ...]:
    return (
        int(p.get("t0_ms") or 0),
        int(p.get("t1_ms") or 0),
        str(p.get("template_id") or ""),
        str(p.get("chain_category") or ""),
    )


def _step_sigs(preds: List[Dict[str, Any]]) -> Set[Tuple[Any, ...]]:
    return {_pred_sig(p) for p in preds}


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-matches", type=int, default=2)
    ap.add_argument("--stream-source", choices=["gold_events", "timeline"], default="gold_events")
    ap.add_argument("--prefix-stride", type=int, default=1)
    ap.add_argument("--min-prefix", type=int, default=2)
    args = ap.parse_args()

    index = json.loads((ROOT / "datasets" / "index.json").read_text(encoding="utf-8"))
    matches = index["matches"][: args.limit_matches]

    batch_ad = AlgoStripAdapter(profile_name="production", use_llm=False, use_sliding_recall=True)
    online_ad = OnlineStripAdapter(profile_name="production", use_llm=False, use_sliding_recall=True)

    eq_rows = []
    stream_parts = []
    all_lats: List[int] = []

    for meta in matches:
        mdir = ROOT / meta["dir"]
        golds = _load_strip_gold(mdir)
        if not golds:
            continue
        if args.stream_source == "gold_events":
            events = _gold_events_stream(golds)
        else:
            events = _load_timeline_events(mdir)
        mid = str(meta.get("safe_id") or "m")

        final_batch = batch_ad.predict(events, match_id=mid)
        final_online = online_ad.predict(events, match_id=mid)
        fb, fo = _step_sigs(final_batch), _step_sigs(final_online)
        eq_rows.append(
            {
                "safe_id": mid,
                "final_match": fb == fo,
                "n_batch": len(final_batch),
                "n_online": len(final_online),
            }
        )

        timeline_preds = online_replay(
            events,
            online_ad,
            match_id=mid,
            stride=args.prefix_stride,
            min_prefix=args.min_prefix,
        )
        sm = score_stream_match(golds, timeline_preds, require_strict=True)
        slim = {
            k: sm[k]
            for k in (
                "n_gold",
                "n_tracks",
                "strict_complete",
                "strict_rate",
                "recall_rate",
                "precision_rate",
                "latency_ms_p50",
                "latency_ms_p90",
                "latency_ms_mean",
            )
            if k in sm
        }
        for r in sm.get("gold_rows") or []:
            if r.get("latency_ms") is not None:
                all_lats.append(int(r["latency_ms"]))
        stream_parts.append({"safe_id": mid, "summary": slim})
        print(mid[:48], "eq", eq_rows[-1]["final_match"], "A", slim, flush=True)

    n_over = sum(1 for x in all_lats if x > LATENCY_THRESH_MS)
    n_lat = len(all_lats)

    def _pct(a: int, b: int) -> float:
        return round(100.0 * a / b, 2) if b else 0.0

    n_g = sum(int(p["summary"]["n_gold"]) for p in stream_parts)
    n_s = sum(int(p["summary"]["strict_complete"]) for p in stream_parts)
    p50s = [p["summary"].get("latency_ms_p50") for p in stream_parts if p["summary"].get("latency_ms_p50") is not None]
    # recompute global percentiles from all_lats
    all_lats.sort()

    def _q(q: float):
        if not all_lats:
            return None
        return float(all_lats[int(round(q * (len(all_lats) - 1)))])

    summary = {
        "final_equivalence": all(r["final_match"] for r in eq_rows),
        "n_matches_eq": len(eq_rows),
        "eq_rows": eq_rows,
        "online_strict_rate": _pct(n_s, n_g),
        "online_strict_complete": n_s,
        "n_gold": n_g,
        "latency_ms_p50": _q(0.5),
        "latency_ms_p90": _q(0.9),
        "latency_ms_mean": round(sum(all_lats) / len(all_lats), 1) if all_lats else None,
        "n_latency_samples": n_lat,
        "n_latency_gt_45s": n_over,
        "pct_latency_gt_45s": _pct(n_over, n_lat),
        "profile_strip": {
            "post_ms": 60_000,
            "window_ms": 180_000,
            "note": "若 >45s 仍高，属 post_ms/window_ms 结构下限，不继续调参",
        },
        "per_match": stream_parts,
    }
    out = ROOT / "reports" / "verify_p31_latency.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n==== P3.1 ====", flush=True)
    print(
        json.dumps(
            {
                "final_equivalence": summary["final_equivalence"],
                "online_strict": summary["online_strict_rate"],
                "latency_ms_p50": summary["latency_ms_p50"],
                "latency_ms_p90": summary["latency_ms_p90"],
                "pct_gt_45s": summary["pct_latency_gt_45s"],
                "n_gt_45s": summary["n_latency_gt_45s"],
                "n_lat": summary["n_latency_samples"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    print(f"wrote {out}", flush=True)


if __name__ == "__main__":
    main()
