#!/usr/bin/env python3
"""在 8.31causal_chain 内评测拆条/集锦（只用 algo/ 副本，不改仓库原包）。

- 拆条：causal_chain6.classify（classify_record_v4，对齐 `python -m causal_chain6.classify`）
- 集锦：causal_chain8.build_highlights.run_build_highlights
        （对齐 `python -m causal_chain8.build_highlights ... --no-llm-narrative`）

建议：
  CUDA_VISIBLE_DEVICES=2 PYTHONPATH=8.31causal_chain/algo:8.31causal_chain/eval \\
    python 8.31causal_chain/eval/run_eval.py \\
    --model-path ./models/Qwen2.5-VL --device cuda --use-llm
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
ALGO = ROOT / "algo"
DATA = ROOT / "datasets"
OUT = ROOT / "reports"
sys.path.insert(0, str(ALGO))
sys.path.insert(0, str(ROOT / "eval"))

from metrics import match_golds_to_preds, summarize  # noqa: E402


CAT_MAP = {
    "outcome": "outcome",
    "correction": "correction",
    "danger": "danger",
    "special": "special",
}


def _load_profile(name: str = "production") -> Dict[str, Any]:
    from causal_chain8.config import load_profile

    profile = dict(load_profile(name))
    profile.setdefault("llm", {})
    profile["llm"] = dict(profile["llm"])
    return profile


def _pred_from_chain(chain, *, fallback_cat: str = "") -> Dict[str, Any]:
    events = list(chain.events or [])
    first = events[0].type if events else ""
    last = events[-1].type if events else ""
    cat = getattr(chain, "chain_category", None) or fallback_cat
    return {
        "chain_category": CAT_MAP.get(cat, cat),
        "first_event": first,
        "last_event": last,
        "t0_ms": int(chain.t0_ms),
        "t1_ms": int(chain.t1_ms),
        "template_id": getattr(chain, "chain_template_id", ""),
    }


def run_strip_match(
    timeline: List[Dict[str, Any]],
    golds: List[Dict[str, Any]],
    *,
    profile: Dict[str, Any],
    model=None,
    processor=None,
    device: str = "cpu",
    use_llm: bool = False,
) -> Dict[str, Any]:
    """拆条：逐条 → causal_chain6.classify_record_v4（与 classify CLI 同内核）。"""
    from causal_chain6.config import load_profile as load_c6_profile
    from causal_chain6.io.eval_record import EvalRecord
    from causal_chain6.llm.agent import classify_record_v4
    from causal_chain6.schema.templates import CHAIN4_TEMPLATES

    _ = timeline  # 拆条按条送入，不依赖整场 discover
    c6_profile = dict(load_c6_profile("production"))
    c6_profile.setdefault("llm", {})
    c6_profile["llm"] = dict(c6_profile.get("llm") or {})
    c6_profile["llm"]["enabled"] = bool(use_llm and model is not None)
    if profile:
        for k in ("robust_classify", "rules_mode"):
            if k in profile:
                c6_profile[k] = profile[k]

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
            profile=c6_profile,
            model=model,
            processor=processor,
            device=device,
            max_new_tokens=512,
        )
        tid = result.chain_template_id
        cat = result.chain_category or (CHAIN4_TEMPLATES.get(tid) or {}).get("category") or ""
        preds.append(
            {
                "chain_category": CAT_MAP.get(cat, cat),
                "first_event": events[0]["type"],
                "last_event": events[-1]["type"],
                "t0_ms": int(g["t0_ms"]),
                "t1_ms": int(g["t1_ms"]),
                "template_id": tid,
                "backend": "causal_chain6.classify",
            }
        )

    rows = match_golds_to_preds(golds, preds)
    return {
        "summary": summarize(rows),
        "n_preds": len(preds),
        "backend": "causal_chain6.classify",
        "rows": rows,
    }


def run_highlight_match(
    timeline_path: Path,
    golds: List[Dict[str, Any]],
    *,
    model_path: str,
    profile_name: str = "production",
    model=None,
    processor=None,
    device: str = "cuda",
    use_llm: bool = True,
    llm_assist: bool = False,
    ambiguous_margin: float = 0.12,
    reel_out: Path | None = None,
) -> Dict[str, Any]:
    """集锦：对齐 build_highlights；llm_assist 时强制 Qwen 分类 + extract refine。"""
    from causal_chain8.build_highlights import run_build_highlights
    from causal_chain8.highlight_io import write_reel_json

    margin = 0.99 if llm_assist else ambiguous_margin
    reel = run_build_highlights(
        timeline_path=timeline_path,
        model_path=model_path or "",
        profile_name=profile_name,
        device=device,
        ambiguous_margin=margin,
        use_llm_narrative=False,
        skip_llm=not use_llm,
        model=model,
        processor=processor,
    )
    if reel_out is not None:
        reel_out.parent.mkdir(parents=True, exist_ok=True)
        write_reel_json(reel_out, reel.to_dict())

    preds = [_pred_from_chain(c) for c in reel.clips]
    rows = match_golds_to_preds(golds, preds)
    return {
        "summary": summarize(rows),
        "n_preds": len(preds),
        "backend": "causal_chain8.build_highlights",
        "select_stats": (reel.stats or {}).get("select"),
        "reel_stats": {
            "moments_selected": (reel.stats or {}).get("moments_selected"),
            "clips_final": (reel.stats or {}).get("clips_final"),
            "fast_path": (reel.stats or {}).get("fast_path"),
            "llm_path": (reel.stats or {}).get("llm_path"),
        },
        "rows": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-matches", type=int, default=0, help="0=全部63场")
    ap.add_argument("--model-path", type=str, default="", help="Qwen 权重目录；空则 rule-only")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--profile", default="production")
    ap.add_argument("--rule-only", action="store_true", help="不上 Qwen（调试用）")
    ap.add_argument("--use-llm", action="store_true", default=False, help="启用 Qwen（推荐）")
    ap.add_argument(
        "--highlight-llm-assist",
        action="store_true",
        default=False,
        help="集锦强制 Qwen 分类(margin=0.99) + 建议配合 production_llm_assist profile",
    )
    ap.add_argument("--tasks", default="strip,highlight", help="strip,highlight")
    ap.add_argument(
        "--reel-dir",
        type=str,
        default="",
        help="集锦 reel 输出子目录名（相对 reports/），默认 reels",
    )
    ap.add_argument(
        "--report-name",
        type=str,
        default="",
        help="报告文件名（相对 reports/），默认按 use_llm 选择",
    )
    args = ap.parse_args()

    use_llm = (not args.rule_only) and (args.use_llm or bool(args.model_path))
    if args.rule_only:
        use_llm = False

    if args.highlight_llm_assist and args.profile == "production":
        args.profile = "production_llm_assist"

    model = processor = None
    if use_llm:
        from causal_chain2.llm_qwen import load_qwen

        print(f"loading Qwen from {args.model_path} on {args.device} ...")
        model, processor = load_qwen(args.model_path, args.device)

    profile = _load_profile(args.profile)
    index = json.loads((DATA / "index.json").read_text(encoding="utf-8"))
    matches = index["matches"]
    if args.limit_matches > 0:
        matches = matches[: args.limit_matches]

    tasks = {t.strip() for t in args.tasks.split(",") if t.strip()}
    OUT.mkdir(parents=True, exist_ok=True)
    reel_subdir = args.reel_dir or (
        "reels_llm_assist" if args.highlight_llm_assist else "reels"
    )
    reel_dir = OUT / reel_subdir
    reel_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"tasks={sorted(tasks)} profile={args.profile} "
        f"llm_assist={args.highlight_llm_assist} reel_dir={reel_dir}"
    )

    strip_rows_all: List[Dict[str, Any]] = []
    hl_rows_all: List[Dict[str, Any]] = []
    per_match: List[Dict[str, Any]] = []

    for mi, meta in enumerate(matches):
        mdir = ROOT / meta["dir"]
        timeline_path = mdir / "timeline.json"
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))["events"]
        strip_gold = json.loads((mdir / "strip_gold.json").read_text(encoding="utf-8"))
        hl_path = mdir / "highlight_gold_no_t2.json"
        if not hl_path.exists():
            hl_path = mdir / "highlight_gold.json"
        hl_gold = json.loads(hl_path.read_text(encoding="utf-8")).get("chains") or []

        rec: Dict[str, Any] = {"match_id": meta["match_id"], "safe_id": meta["safe_id"]}
        print(
            f"[{mi+1}/{len(matches)}] {meta['safe_id'][:50]} "
            f"ev={len(timeline)} strip={len(strip_gold)} hl={len(hl_gold)}"
        )

        if "strip" in tasks and strip_gold:
            r = run_strip_match(
                timeline,
                strip_gold,
                profile=profile,
                model=model,
                processor=processor,
                device=args.device,
                use_llm=use_llm,
            )
            rec["strip"] = r["summary"]
            strip_rows_all.extend(r["rows"])
            print("  strip", r["summary"])

        if "highlight" in tasks and hl_gold:
            r = run_highlight_match(
                timeline_path,
                hl_gold,
                model_path=args.model_path,
                profile_name=args.profile,
                model=model,
                processor=processor,
                device=args.device,
                use_llm=use_llm,
                llm_assist=args.highlight_llm_assist,
                reel_out=reel_dir / f"{meta['safe_id'][:60]}.json",
            )
            rec["highlight"] = r["summary"]
            rec["highlight_reel_stats"] = r.get("reel_stats")
            hl_rows_all.extend(r["rows"])
            print("  highlight", r["summary"], r.get("reel_stats"))

        per_match.append(rec)
        mid = {
            "strip": summarize(strip_rows_all),
            "highlight": summarize(hl_rows_all),
            "done_matches": mi + 1,
            "profile": args.profile,
            "highlight_llm_assist": args.highlight_llm_assist,
        }
        (OUT / "report_llm_partial.json").write_text(
            json.dumps(mid, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    # 只跑集锦时，拆条指标沿用已有 report_llm
    strip_sum = summarize(strip_rows_all)
    if "strip" not in tasks:
        prev = OUT / "report_llm.json"
        if prev.exists():
            strip_sum = json.loads(prev.read_text(encoding="utf-8")).get("strip") or strip_sum

    hl_sum = summarize(hl_rows_all)
    planned = int(index["summary"].get("n_strip_cases", 0)) + int(
        index["summary"].get("n_highlight_cases_no_t2")
        or index["summary"].get("n_highlight_cases", 0)
    )
    # 填表：拆条用全量条数，集锦用本次
    strip_n = int(strip_sum.get("n") or 0)
    executed = strip_n + int(hl_sum["n"])
    passed = int(strip_sum.get("strict_complete") or 0) + int(hl_sum["strict_complete"])
    failed = executed - passed
    pass_rate = round(100.0 * passed / executed, 2) if executed else 0.0

    backend_hl = "causal_chain8.build_highlights"
    if use_llm:
        backend_hl += " (+Qwen"
        if args.highlight_llm_assist:
            backend_hl += ", force-classify+llm_refine"
        backend_hl += ", no-llm-narrative)"

    table_row = {
        "测试阶段": "中期测试",
        "测试模块": "因果链编排算法工具 v2.0",
        "计划总用例": planned,
        "执行总用例": executed,
        "通过": passed,
        "失败": failed,
        "阻塞": 0,
        "不支持": 0,
        "执行通过率": f"{pass_rate}%",
        "主指标": "因果逻辑完整率(时间∩∧大类∧首事件∧末事件)",
        "拆条后端": "causal_chain6.classify (+Qwen)" if use_llm or strip_n else "causal_chain6.classify",
        "集锦后端": backend_hl,
        "拆条严格完整率": f"{strip_sum.get('strict_rate', 0)}%",
        "集锦严格完整率": f"{hl_sum['strict_rate']}%",
        "拆条辅(时间+大类)": f"{strip_sum.get('aux_time_cat_rate', 0)}%",
        "集锦辅(时间+大类)": f"{hl_sum['aux_time_cat_rate']}%",
        "rule_only": not use_llm,
        "model_path": args.model_path if use_llm else "",
        "gpu": "CUDA_VISIBLE_DEVICES",
        "highlight_llm_assist": args.highlight_llm_assist,
        "profile": args.profile,
        "reel_dir": reel_subdir,
    }

    report = {
        "table_row": table_row,
        "strip": strip_sum,
        "highlight_no_t2": hl_sum,
        "per_match": per_match,
        "config": {
            "use_llm": use_llm,
            "highlight_llm_assist": args.highlight_llm_assist,
            "model_path": args.model_path,
            "profile": args.profile,
            "n_matches": len(matches),
            "tasks": sorted(tasks),
            "reel_dir": reel_subdir,
        },
    }
    if args.report_name:
        out_path = OUT / args.report_name
    elif args.highlight_llm_assist:
        out_path = OUT / "report_hl_llm_assist.json"
    else:
        out_path = OUT / ("report_llm.json" if use_llm else "report_rule_only.json")
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not args.highlight_llm_assist:
        (OUT / "table_row_causal_chain.json").write_text(
            json.dumps(table_row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    else:
        (OUT / "table_row_hl_llm_assist.json").write_text(
            json.dumps(table_row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print("\n==== 填表行 ====")
    print(json.dumps(table_row, ensure_ascii=False, indent=2))
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
