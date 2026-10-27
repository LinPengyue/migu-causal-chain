#!/usr/bin/env python3
"""P3 验证：online stateful vs batch prefix replay 等价性 + 无未来泄漏抽检。"""

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
    online_replay,
    prefix_replay,
)
from strip_adapter import AlgoStripAdapter, OnlineStripAdapter  # noqa: E402


def _pred_sig(p: Dict[str, Any]) -> Tuple[Any, ...]:
    return (
        int(p.get("t0_ms") or 0),
        int(p.get("t1_ms") or 0),
        str(p.get("template_id") or ""),
        str(p.get("chain_category") or ""),
    )


def _step_sigs(preds: List[Dict[str, Any]]) -> Set[Tuple[Any, ...]]:
    return {_pred_sig(p) for p in preds}


def compare_replays(
    events: List[Dict[str, Any]],
    *,
    match_id: str,
    stride: int = 1,
    min_prefix: int = 2,
) -> Dict[str, Any]:
    batch = AlgoStripAdapter(profile_name="production", use_llm=False, use_sliding_recall=True)
    online = OnlineStripAdapter(profile_name="production", use_llm=False, use_sliding_recall=True)

    batch_steps = prefix_replay(
        events, batch, match_id=match_id, stride=stride, min_prefix=min_prefix
    )
    online_steps = online_replay(
        events, online, match_id=match_id, stride=stride, min_prefix=min_prefix
    )

    mismatches = []
    n = min(len(batch_steps), len(online_steps))
    for i in range(n):
        t_b, preds_b = batch_steps[i]
        t_o, preds_o = online_steps[i]
        sb, so = _step_sigs(preds_b), _step_sigs(preds_o)
        if t_b != t_o or sb != so:
            mismatches.append(
                {
                    "step": i,
                    "t_batch": t_b,
                    "t_online": t_o,
                    "n_batch": len(preds_b),
                    "n_online": len(preds_o),
                    "only_batch": sorted(sb - so)[:5],
                    "only_online": sorted(so - sb)[:5],
                }
            )

    final_batch = batch.predict(events, match_id=match_id)
    final_online = online.predict(events, match_id=match_id)
    fb, fo = _step_sigs(final_batch), _step_sigs(final_online)

    return {
        "n_events": len(events),
        "n_steps": n,
        "step_mismatches": len(mismatches),
        "mismatch_samples": mismatches[:10],
        "final_match": fb == fo,
        "final_n_batch": len(final_batch),
        "final_n_online": len(final_online),
        "final_only_batch": sorted(fb - fo)[:5],
        "final_only_online": sorted(fo - fb)[:5],
    }


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-matches", type=int, default=3)
    ap.add_argument("--stream-source", choices=["gold_events", "timeline"], default="gold_events")
    ap.add_argument("--prefix-stride", type=int, default=1)
    ap.add_argument("--min-prefix", type=int, default=2)
    args = ap.parse_args()

    index = json.loads((ROOT / "datasets" / "index.json").read_text(encoding="utf-8"))
    matches = index["matches"][: args.limit_matches]

    from run_stream_strip import _load_timeline_events  # noqa: E402

    results = []
    for meta in matches:
        mdir = ROOT / meta["dir"]
        golds = _load_strip_gold(mdir)
        if args.stream_source == "gold_events":
            events = _gold_events_stream(golds)
        else:
            events = _load_timeline_events(mdir)
        r = compare_replays(
            events,
            match_id=str(meta.get("safe_id") or "m"),
            stride=args.prefix_stride,
            min_prefix=args.min_prefix,
        )
        r["safe_id"] = meta["safe_id"]
        results.append(r)
        print(meta["safe_id"][:48], json.dumps(r, ensure_ascii=False), flush=True)

    summary = {
        "n_matches": len(results),
        "all_final_match": all(r["final_match"] for r in results),
        "total_step_mismatches": sum(r["step_mismatches"] for r in results),
        "per_match": results,
    }
    out = ROOT / "reports" / "verify_online_strip.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {out}", flush=True)
    print(
        "SUMMARY",
        {
            "all_final_match": summary["all_final_match"],
            "total_step_mismatches": summary["total_step_mismatches"],
        },
        flush=True,
    )


if __name__ == "__main__":
    main()
