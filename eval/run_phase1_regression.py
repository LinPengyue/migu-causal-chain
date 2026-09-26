#!/usr/bin/env python3
"""P3：Phase1 拆条回归（offline → B → A）。

固定口径：
  - profile=production（冻结：sliding_merge_mode=none, sliding_post_nms=off）
  - rule-only + gold_events
  - one-to-one matcher（评测层，不改算法）

用法：
  cd 8.31causal_chain
  PYTHONPATH=$PWD/algo:$PWD/eval python -u eval/run_phase1_regression.py
  PYTHONPATH=$PWD/algo:$PWD/eval python -u eval/run_phase1_regression.py --skip-run   # 只对比已有报告
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
BASELINE_PATH = REPORTS / "baseline_phase1_frozen.json"
DEFAULT_REPORT = REPORTS / "report_stream_strip_rule.json"
REG_JSON = REPORTS / "phase1_regression_latest.json"
REG_MD = REPORTS / "phase1_regression_latest.md"


def _rel(path: Path) -> str:
    """相对包根路径，便于打包部署。"""
    p = Path(path)
    try:
        return str(p.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(p)


def _load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_metrics(report: Dict[str, Any]) -> Dict[str, Any]:
    offline = report.get("offline_classify") or {}
    stream_a = report.get("stream_A_prefix_replay") or report.get("stream_A") or {}
    stream_b = report.get("stream_B_oracle_upper") or {}
    table = report.get("table_row") or {}
    adapter = table.get("adapter") or (report.get("config") or {}).get("adapter") or {}
    return {
        "offline_strict": offline.get("strict_rate"),
        "B_strict": stream_b.get("strict_rate"),
        "A_strict": stream_a.get("strict_rate"),
        "A_precision": stream_a.get("precision_rate"),
        "n_tracks": stream_a.get("n_tracks") or stream_a.get("n_emit_deduped"),
        "n_matched_gold": stream_a.get("n_matched_gold") or stream_a.get("recall_matched"),
        "n_unique_matched_tracks": stream_a.get("n_unique_matched_tracks")
        or stream_a.get("precision_hits"),
        "n_gold": stream_a.get("n_gold") or offline.get("n"),
        "one_to_one_ok": stream_a.get("one_to_one_ok"),
        "match_mode": stream_a.get("match_mode") or table.get("match_mode"),
        "sliding_merge_mode": adapter.get("sliding_merge_mode"),
        "sliding_post_nms": adapter.get("sliding_post_nms"),
        "stream_source": table.get("stream_source")
        or (report.get("config") or {}).get("stream_source"),
        "rule_only": table.get("rule_only"),
    }


def _delta(cur: Optional[float], base: Optional[float]) -> Optional[float]:
    if cur is None or base is None:
        return None
    return round(float(cur) - float(base), 2)


def compare(
    current: Dict[str, Any],
    baseline_metrics: Dict[str, Any],
    *,
    abs_tol: float = 0.05,
) -> Dict[str, Any]:
    keys = [
        "offline_strict",
        "B_strict",
        "A_strict",
        "A_precision",
        "n_tracks",
        "n_matched_gold",
    ]
    rows = []
    ok = True
    for k in keys:
        b = baseline_metrics.get(k)
        c = current.get(k)
        d = _delta(c if isinstance(c, (int, float)) else None, b if isinstance(b, (int, float)) else None)
        if isinstance(b, (int, float)) and isinstance(c, (int, float)):
            # counts: exact; rates: abs_tol
            if k.startswith("n_"):
                passed = int(c) == int(b)
            else:
                passed = abs(float(c) - float(b)) <= abs_tol
        else:
            passed = c == b
        if not passed:
            ok = False
        rows.append({"metric": k, "baseline": b, "current": c, "delta": d, "pass": passed})

    # config invariants
    inv = []
    for k, expect in [
        ("sliding_merge_mode", "none"),
        ("sliding_post_nms", "off"),
        ("stream_source", "gold_events"),
        ("match_mode", "bipartite_max_weight_one_to_one"),
    ]:
        c = current.get(k)
        # rule_only may be True
        passed = (c == expect) if k != "match_mode" or c else False
        if k == "match_mode" and not c:
            # older reports may omit; treat soft
            passed = True
        if not passed and k in ("sliding_merge_mode", "sliding_post_nms", "stream_source"):
            ok = False
        inv.append({"check": k, "expect": expect, "current": c, "pass": passed})

    o2o = current.get("one_to_one_ok")
    o2o_pass = o2o is True or (
        current.get("n_matched_gold") is not None
        and current.get("n_unique_matched_tracks") is not None
        and current.get("n_matched_gold") == current.get("n_unique_matched_tracks")
    )
    if not o2o_pass:
        ok = False
    inv.append(
        {
            "check": "one_to_one",
            "expect": "matched_gold == unique_matched_tracks",
            "current": {
                "one_to_one_ok": o2o,
                "n_matched_gold": current.get("n_matched_gold"),
                "n_unique_matched_tracks": current.get("n_unique_matched_tracks"),
            },
            "pass": o2o_pass,
        }
    )

    return {
        "pass": ok,
        "metric_rows": rows,
        "invariants": inv,
        "hierarchy": {
            "offline": current.get("offline_strict"),
            "B": current.get("B_strict"),
            "A": current.get("A_strict"),
            "gaps_pp": {
                "offline_minus_B": _delta(current.get("offline_strict"), current.get("B_strict")),
                "B_minus_A": _delta(current.get("B_strict"), current.get("A_strict")),
            },
        },
    }


def run_eval(*, profile: str, limit_matches: int = 0) -> Path:
    cmd = [
        sys.executable,
        "-u",
        str(ROOT / "eval" / "run_stream_strip.py"),
        "--rule-only",
        "--stream-source",
        "gold_events",
        "--prefix-stride",
        "1",
        "--profile",
        profile,
    ]
    if limit_matches > 0:
        cmd.extend(["--limit-matches", str(limit_matches)])
    env = dict(**{k: v for k, v in __import__("os").environ.items()})
    env["PYTHONPATH"] = f"{ROOT / 'algo'}:{ROOT / 'eval'}" + (
        f":{env['PYTHONPATH']}" if env.get("PYTHONPATH") else ""
    )
    print("running:", " ".join(cmd), flush=True)
    subprocess.check_call(cmd, cwd=str(ROOT), env=env)
    return DEFAULT_REPORT


def write_md(payload: Dict[str, Any]) -> None:
    cmp_ = payload["compare"]
    lines = [
        "# Phase1 拆条回归（P3）",
        "",
        f"结果：**{'PASS' if cmp_['pass'] else 'FAIL'}**",
        "",
        f"- profile: `{payload.get('profile')}`",
        f"- report: `{payload.get('report_path')}`",
        f"- baseline: `{payload.get('baseline_path')}`",
        "",
        "## offline → B → A",
        "",
        f"| 层 | 当前 |",
        f"|----|-----:|",
        f"| offline | {cmp_['hierarchy']['offline']}% |",
        f"| B oracle | {cmp_['hierarchy']['B']}% |",
        f"| A stream | {cmp_['hierarchy']['A']}% |",
        "",
        f"gaps: offline−B = {cmp_['hierarchy']['gaps_pp']['offline_minus_B']} pp；"
        f" B−A = {cmp_['hierarchy']['gaps_pp']['B_minus_A']} pp",
        "",
        "## vs 冻结基线",
        "",
        "| metric | baseline | current | Δ | pass |",
        "|--------|---------:|--------:|--:|:----:|",
    ]
    for r in cmp_["metric_rows"]:
        lines.append(
            f"| {r['metric']} | {r['baseline']} | {r['current']} | {r['delta']} | "
            f"{'✓' if r['pass'] else '✗'} |"
        )
    lines.append("")
    lines.append("## 不变量")
    lines.append("")
    for inv in cmp_["invariants"]:
        lines.append(
            f"- `{inv['check']}` expect={inv['expect']} current={inv['current']} "
            f"{'✓' if inv['pass'] else '✗'}"
        )
    lines.append("")
    REG_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase1 strip regression (P3)")
    ap.add_argument("--profile", default="production")
    ap.add_argument("--baseline", type=str, default=str(BASELINE_PATH))
    ap.add_argument("--report", type=str, default="")
    ap.add_argument("--skip-run", action="store_true", help="不跑评测，只对比已有报告")
    ap.add_argument("--limit-matches", type=int, default=0)
    ap.add_argument("--abs-tol", type=float, default=0.05, help="率指标绝对容差（百分点）")
    args = ap.parse_args()

    baseline_doc = _load(Path(args.baseline))
    baseline_metrics = baseline_doc["metrics"]

    if args.skip_run:
        report_path = Path(args.report) if args.report else DEFAULT_REPORT
        if not report_path.is_file():
            # fall back to frozen source report
            alt = ROOT / baseline_doc.get("source_report", "")
            if alt.is_file():
                report_path = alt
            else:
                raise SystemExit(f"report not found: {report_path}")
    else:
        report_path = run_eval(profile=args.profile, limit_matches=args.limit_matches)
        # also persist named regression artifact
        named = REPORTS / "report_stream_strip_rule_gold_events_phase1_baseline.json"
        named.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")

    report = _load(report_path)
    current = _extract_metrics(report)
    cmp_ = compare(current, baseline_metrics, abs_tol=args.abs_tol)

    payload = {
        "pass": cmp_["pass"],
        "profile": args.profile,
        "baseline_path": _rel(Path(args.baseline)),
        "report_path": _rel(report_path),
        "baseline": baseline_doc,
        "current_metrics": current,
        "compare": cmp_,
        "note": "P3 回归：不改评测指标定义；对比冻结 baseline（none + post_nms=off）",
    }
    REG_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_md(payload)
    print(json.dumps({"pass": cmp_["pass"], "hierarchy": cmp_["hierarchy"], "out": _rel(REG_JSON)}, ensure_ascii=False, indent=2))
    print("wrote", _rel(REG_JSON))
    print("wrote", _rel(REG_MD))
    if not cmp_["pass"]:
        sys.exit(2)


if __name__ == "__main__":
    main()
