#!/usr/bin/env python3
"""P4 smoke：Qwen 可选接入 batch/online adapter（接口验证，不追指标）。

确认：
  - --use-llm 可加载并跑通
  - pred schema 与 rule-only 一致
  - online final == batch final（同模型）
  - rule-only 默认仍 llm_enabled=false
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "algo"))
sys.path.insert(0, str(ROOT / "eval"))

from run_stream_strip import _gold_events_stream, _load_strip_gold  # noqa: E402
from strip_adapter import AlgoStripAdapter, OnlineStripAdapter  # noqa: E402

PRED_KEYS = {
    "chain_category",
    "first_event",
    "last_event",
    "t0_ms",
    "t1_ms",
    "template_id",
    "source",
    "event_ids",
    "event_keys",
}


def _sig(p: Dict[str, Any]) -> Tuple[Any, ...]:
    return (
        int(p.get("t0_ms") or 0),
        int(p.get("t1_ms") or 0),
        str(p.get("template_id") or ""),
        str(p.get("chain_category") or ""),
    )


def _schema_ok(preds: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    issues: List[str] = []
    for i, p in enumerate(preds):
        missing = PRED_KEYS - set(p.keys())
        if missing:
            issues.append(f"pred[{i}] missing {sorted(missing)}")
        for k in ("t0_ms", "t1_ms"):
            if not isinstance(p.get(k), int):
                issues.append(f"pred[{i}].{k} type={type(p.get(k)).__name__}")
        if not isinstance(p.get("template_id"), str):
            issues.append(f"pred[{i}].template_id not str")
        if not isinstance(p.get("chain_category"), str):
            issues.append(f"pred[{i}].chain_category not str")
    return (not issues), issues


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-matches", type=int, default=1)
    ap.add_argument("--model-path", default="", help="Qwen 权重目录；空则跳过 LLM")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--skip-llm", action="store_true", help="只检查 rule 接口，不加载模型")
    args = ap.parse_args()

    index = json.loads((ROOT / "datasets" / "index.json").read_text(encoding="utf-8"))
    matches = index["matches"][: max(1, args.limit_matches)]

    # 1) rule-only 默认不变
    rule_batch = AlgoStripAdapter(profile_name="production", use_llm=False)
    rule_online = OnlineStripAdapter(profile_name="production", use_llm=False)
    rule_ok = (
        rule_batch.config_snapshot().get("llm_enabled") is False
        and rule_online.config_snapshot().get("llm_enabled") is False
    )

    report: Dict[str, Any] = {
        "rule_only_default_ok": rule_ok,
        "llm_loaded": False,
        "interface_issues": [],
        "matches": [],
    }

    model = processor = None
    if not args.skip_llm:
        from causal_chain2.llm_qwen import load_qwen

        print(f"loading Qwen from {args.model_path} on {args.device} ...", flush=True)
        try:
            model, processor = load_qwen(args.model_path, args.device)
            report["llm_loaded"] = True
        except Exception as e:
            report["interface_issues"].append(f"load_qwen failed: {type(e).__name__}: {e}")
            report["smoke_pass"] = False
            out = ROOT / "reports" / "verify_p4_qwen_smoke.json"
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
            print(f"wrote {out}", flush=True)
            sys.exit(1)

    batch = AlgoStripAdapter(
        profile_name="production",
        model=model,
        processor=processor,
        device=args.device,
        use_llm=True,
        use_sliding_recall=True,
    )
    online = OnlineStripAdapter(
        profile_name="production",
        model=model,
        processor=processor,
        device=args.device,
        use_llm=True,
        use_sliding_recall=True,
    )
    if not batch.config_snapshot().get("llm_enabled"):
        report["interface_issues"].append("AlgoStripAdapter llm_enabled=false under use_llm=True")
    if not online.config_snapshot().get("llm_enabled"):
        report["interface_issues"].append("OnlineStripAdapter llm_enabled=false under use_llm=True")

    all_eq = True
    all_schema = True
    for meta in matches:
        mdir = ROOT / meta["dir"]
        golds = _load_strip_gold(mdir)
        events = _gold_events_stream(golds)
        mid = str(meta.get("safe_id") or "m")
        print(f"smoke match={mid[:48]} n_events={len(events)}", flush=True)

        preds_b = batch.predict(events, match_id=mid)
        preds_o = online.predict(events, match_id=mid)
        ok_b, iss_b = _schema_ok(preds_b)
        ok_o, iss_o = _schema_ok(preds_o)
        sb: Set[Tuple[Any, ...]] = {_sig(p) for p in preds_b}
        so: Set[Tuple[Any, ...]] = {_sig(p) for p in preds_o}
        eq = sb == so
        all_eq = all_eq and eq
        all_schema = all_schema and ok_b and ok_o
        row = {
            "safe_id": mid,
            "n_events": len(events),
            "n_batch": len(preds_b),
            "n_online": len(preds_o),
            "schema_ok": ok_b and ok_o,
            "schema_issues": iss_b + iss_o,
            "final_equivalence": eq,
            "sample_pred": preds_b[0] if preds_b else None,
            "adapter_batch": batch.config_snapshot(),
            "adapter_online": online.config_snapshot(),
        }
        report["matches"].append(row)
        print(
            f"  schema={row['schema_ok']} final_eq={eq} n_b={len(preds_b)} n_o={len(preds_o)}",
            flush=True,
        )
        if iss_b or iss_o:
            report["interface_issues"].extend(iss_b + iss_o)

    report["final_equivalence"] = all_eq
    report["schema_ok"] = all_schema
    report["smoke_pass"] = bool(
        report["rule_only_default_ok"]
        and report["llm_loaded"]
        and all_eq
        and all_schema
        and not report["interface_issues"]
    )
    out = ROOT / "reports" / "verify_p4_qwen_smoke.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n==== P4 smoke ====", flush=True)
    print(
        json.dumps(
            {
                "smoke_pass": report["smoke_pass"],
                "rule_only_default_ok": report["rule_only_default_ok"],
                "llm_loaded": report["llm_loaded"],
                "schema_ok": report["schema_ok"],
                "final_equivalence": report["final_equivalence"],
                "interface_issues": report["interface_issues"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    print(f"wrote {out}", flush=True)
    sys.exit(0 if report["smoke_pass"] else 1)


if __name__ == "__main__":
    main()
