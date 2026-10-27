#!/usr/bin/env python3
"""顺序调用 4 个 causal_chain 评测入口，汇总到 reports/causal_chain_selftest_summary.json。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "algo"))
sys.path.insert(0, str(ROOT / "eval"))

from eval_common import (  # noqa: E402
    REPORTS,
    ROOT as _ROOT,
    label_source_counts,
    load_highlight_gold,
    load_index,
)
from eval_offline_highlight import main as offline_hl_main  # noqa: E402
from eval_offline_strip import main as offline_strip_main  # noqa: E402
from eval_online_highlight import main as online_hl_main  # noqa: E402
from eval_online_strip import main as online_strip_main  # noqa: E402


def _hl_gold_coverage() -> Dict[str, Any]:
    matches = load_index()["matches"]
    n_file = 0
    n_nonempty = 0
    sources: Dict[str, int] = {}
    label_src = {"annotation": 0, "timeline_heuristic": 0}
    for meta in matches:
        mdir = _ROOT / meta["dir"]
        chains, src = load_highlight_gold(mdir)
        for name in ("highlight_gold_no_t2.json", "highlight_gold.json", "highlight_gold_with_t2.json"):
            if (mdir / name).exists():
                n_file += 1
                break
        if chains:
            n_nonempty += 1
            sources[src or "?"] = sources.get(src or "?", 0) + 1
            for k, v in label_source_counts(chains).items():
                label_src[k] = label_src.get(k, 0) + v
    return {
        "n_matches": len(matches),
        "n_matches_with_highlight_gold_file": n_file,
        "n_matches_with_nonempty_highlight_gold": n_nonempty,
        "highlight_gold_exists": n_nonempty > 0,
        "gold_file_counts": sources,
        "label_source_counts": label_src,
        "note": (
            "highlight_gold_* 为集锦片段级标注（category/first/last/t0/t1）；"
            "用于 highlight clips 一对一逻辑完整率；P5 graph 仅结构回归"
        ),
    }


def _row(
    *,
    gold: Any,
    matched: Any,
    logic_rate: Any,
    precision: Any = None,
    latency_p50: Any = None,
    latency_p90: Any = None,
    over_45s: Any = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "gold": gold,
        "matched": matched,
        "logic_rate": logic_rate,
    }
    if precision is not None:
        out["precision"] = precision
    if latency_p50 is not None or latency_p90 is not None or over_45s is not None:
        out["latency_p50"] = latency_p50
        out["latency_p90"] = latency_p90
        out["over_45s_rate"] = over_45s
    return out


def _hl_slice(by_src: Optional[Dict[str, Any]], key: str) -> Dict[str, Any]:
    s = (by_src or {}).get(key) or {}
    return _row(
        gold=s.get("total_gold"),
        matched=s.get("strict_matched"),
        logic_rate=s.get("logic_complete_rate"),
    )


def _build_summary_table(r1: Dict, r2: Dict, r3: Dict, r4: Dict) -> Dict[str, Any]:
    off_by = r2.get("by_label_source") or {}
    on_by = r4.get("by_label_source") or {}
    st_off = r2.get("structural") or {}
    st_on = r4.get("structural") or {}
    return {
        "offline_strip": _row(
            gold=r1.get("total_gold"),
            matched=r1.get("strict_matched"),
            logic_rate=r1.get("logic_complete_rate"),
            precision=r1.get("precision"),
        ),
        "offline_highlight": {
            "all": _row(
                gold=r2.get("total_gold"),
                matched=r2.get("strict_matched"),
                logic_rate=r2.get("logic_complete_rate"),
                precision=r2.get("precision"),
            ),
            "annotation_only": _hl_slice(off_by, "annotation_only"),
            "timeline_heuristic_only": _hl_slice(off_by, "timeline_heuristic_only"),
            "label_source_counts": (r2.get("data_sources") or {}).get("label_source_counts"),
        },
        "online_strip": _row(
            gold=r3.get("total_gold"),
            matched=r3.get("strict_matched"),
            logic_rate=r3.get("logic_complete_rate"),
            precision=r3.get("precision"),
            latency_p50=r3.get("latency_p50"),
            latency_p90=r3.get("latency_p90"),
            over_45s=r3.get("over_45s_rate"),
        ),
        "online_highlight": {
            "all": _row(
                gold=r4.get("total_gold"),
                matched=r4.get("strict_matched"),
                logic_rate=r4.get("logic_complete_rate"),
                precision=r4.get("precision"),
                latency_p50=r4.get("latency_p50"),
                latency_p90=r4.get("latency_p90"),
                over_45s=r4.get("over_45s_rate"),
            ),
            "annotation_only": _hl_slice(on_by, "annotation_only"),
            "timeline_heuristic_only": _hl_slice(on_by, "timeline_heuristic_only"),
            "label_source_counts": (r4.get("data_sources") or {}).get("label_source_counts"),
        },
        "p5_structural": {
            "offline": {
                "n_matches": r2.get("n_matches"),
                "pass_rate": st_off.get("structural_pass_rate"),
                "n_pass": st_off.get("n_pass"),
                "n_fail": st_off.get("n_fail"),
                "node_loss": st_off.get("node_loss"),
                "duplicate": st_off.get("duplicate"),
                "cycle": st_off.get("cycle"),
                "ordering": st_off.get("ordering"),
                "correction": st_off.get("correction"),
            },
            "online": {
                "n_matches": (st_on.get("n_pass") or 0) + (st_on.get("n_fail") or 0),
                "pass_rate": st_on.get("structural_pass_rate"),
                "n_pass": st_on.get("n_pass"),
                "n_fail": st_on.get("n_fail"),
                "node_loss": st_on.get("node_loss"),
                "duplicate": st_on.get("duplicate"),
                "cycle": st_on.get("cycle"),
                "ordering": st_on.get("ordering"),
                "correction": st_on.get("correction"),
            },
        },
    }


def main(argv: List[str] | None = None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="Causal-chain 4-eval selftest")
    ap.add_argument("--limit-matches", type=int, default=0, help="0=全部63场（默认）；仅调试时显式限制")
    ap.add_argument("--stream-source", choices=["gold_events", "timeline"], default="gold_events")
    ap.add_argument(
        "--event-source",
        choices=["timeline", "gold_events"],
        default="gold_events",
        help="offline_strip 事件源（无静默 fallback）",
    )
    ap.add_argument("--out", type=Path, default=REPORTS / "causal_chain_selftest_summary.json")
    args = ap.parse_args(argv)

    lim = str(args.limit_matches)
    stages = [
        ("1/4", "Offline Strip", "offline_strip"),
        ("2/4", "Offline Highlight", "offline_highlight"),
        ("3/4", "Online Strip", "online_strip"),
        ("4/4", "Online Highlight", "online_highlight"),
    ]

    def _banner(idx: str, title: str) -> None:
        print(f"\n{'=' * 60}", flush=True)
        print(f"[{idx}] {title}", flush=True)
        print(f"{'=' * 60}", flush=True)

    _banner(*stages[0][:2])
    r1 = offline_strip_main(
        [
            "--limit-matches",
            lim,
            "--event-source",
            args.event_source,
            "--out",
            str(REPORTS / "eval_offline_strip.json"),
        ]
    )
    _banner(*stages[1][:2])
    r2 = offline_hl_main(["--limit-matches", lim, "--out", str(REPORTS / "eval_offline_highlight.json")])
    _banner(*stages[2][:2])
    r3 = online_strip_main(
        [
            "--limit-matches",
            lim,
            "--stream-source",
            args.stream_source,
            "--out",
            str(REPORTS / "eval_online_strip.json"),
        ]
    )
    _banner(*stages[3][:2])
    r4 = online_hl_main(
        [
            "--limit-matches",
            lim,
            "--stream-source",
            args.stream_source,
            "--out",
            str(REPORTS / "eval_online_highlight.json"),
        ]
    )

    coverage = _hl_gold_coverage()
    table = _build_summary_table(r1, r2, r3, r4)
    summary: Dict[str, Any] = {
        "limit_matches": args.limit_matches,
        "n_matches": r2.get("n_matches") or len(load_index()["matches"]),
        "rule_only": True,
        "use_llm": False,
        "stream_source": args.stream_source,
        "event_source": args.event_source,
        "scripts": {
            "offline_strip": "eval/eval_offline_strip.py",
            "offline_highlight": "eval/eval_offline_highlight.py",
            "online_strip": "eval/eval_online_strip.py",
            "online_highlight": "eval/eval_online_highlight.py",
        },
        "summary_table": table,
        "data_sources": {
            "offline_strip": r1.get("data_sources"),
            "offline_highlight": r2.get("data_sources"),
            "online_strip": r3.get("data_sources"),
            "online_highlight": r4.get("data_sources"),
        },
        "highlight_gold_coverage": coverage,
        "results": {
            "offline_strip": r1,
            "offline_highlight": {
                k: r2.get(k)
                for k in (
                    "total_gold",
                    "strict_matched",
                    "logic_complete_rate",
                    "precision",
                    "by_label_source",
                    "structural",
                )
            },
            "online_strip": {
                k: r3.get(k)
                for k in (
                    "total_gold",
                    "strict_matched",
                    "logic_complete_rate",
                    "precision",
                    "latency_p50",
                    "latency_p90",
                    "over_45s_rate",
                )
            },
            "online_highlight": {
                k: r4.get(k)
                for k in (
                    "total_gold",
                    "strict_matched",
                    "logic_complete_rate",
                    "precision",
                    "latency_p50",
                    "latency_p90",
                    "over_45s_rate",
                    "by_label_source",
                    "structural",
                )
            },
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n==== summary_table ====", flush=True)
    print(json.dumps(table, ensure_ascii=False, indent=2), flush=True)
    print(f"wrote {args.out}", flush=True)
    return summary


if __name__ == "__main__":
    main()
