#!/usr/bin/env python3
"""仅用已有 build_highlights reel + 新 gold 重算集锦完整率（不重跑 Qwen）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

from metrics import match_golds_to_preds, summarize  # noqa: E402

CAT_MAP = {
    "outcome": "outcome",
    "correction": "correction",
    "danger": "danger",
    "special": "special",
}


def _pred_from_clip(c: Dict[str, Any]) -> Dict[str, Any]:
    ev = c.get("events") or []
    first = ev[0]["type"] if ev else ""
    last = ev[-1]["type"] if ev else ""
    cat = c.get("chain_category") or ""
    return {
        "chain_category": CAT_MAP.get(cat, cat),
        "first_event": first,
        "last_event": last,
        "t0_ms": int(c["t0_ms"]),
        "t1_ms": int(c["t1_ms"]),
        "template_id": c.get("chain_template_id", ""),
    }


def main() -> None:
    index = json.loads((ROOT / "datasets" / "index.json").read_text(encoding="utf-8"))
    reel_dir = ROOT / "reports" / "reels"
    strip_rep = {}
    llm_path = ROOT / "reports" / "report_llm.json"
    if llm_path.exists():
        strip_rep = json.loads(llm_path.read_text(encoding="utf-8")).get("strip") or {}

    all_rows: List[Dict[str, Any]] = []
    missing_reel = 0
    dur_g: List[int] = []
    dur_p: List[int] = []

    for meta in index["matches"]:
        mdir = ROOT / meta["dir"]
        hl_path = mdir / "highlight_gold_no_t2.json"
        if not hl_path.exists():
            hl_path = mdir / "highlight_gold.json"
        golds = json.loads(hl_path.read_text(encoding="utf-8")).get("chains") or []
        if not golds:
            continue
        for g in golds:
            dur_g.append(int(g["t1_ms"]) - int(g["t0_ms"]))

        safe = meta["safe_id"][:60]
        reel_p = reel_dir / f"{safe}.json"
        if not reel_p.exists():
            # 文件名截断不一致时，用更长短前缀模糊匹配
            cands = list(reel_dir.glob(meta["safe_id"][:40] + "*.json"))
            if not cands:
                cands = list(reel_dir.glob(meta["safe_id"][:25] + "*.json"))
            reel_p = cands[0] if cands else None
        if reel_p is None or not reel_p.exists():
            missing_reel += 1
            for g in golds:
                all_rows.append(
                    {
                        "matched": False,
                        "flags": {
                            "a_time": False,
                            "b_category": False,
                            "c_first": False,
                            "d_last": False,
                            "strict": False,
                            "aux_time_cat": False,
                            "aux_time_cat_last": False,
                        },
                    }
                )
            continue

        reel = json.loads(reel_p.read_text(encoding="utf-8"))
        clips = (reel.get("reel") or {}).get("clips") or []
        preds = [_pred_from_clip(c) for c in clips]
        for p in preds:
            dur_p.append(int(p["t1_ms"]) - int(p["t0_ms"]))
        all_rows.extend(match_golds_to_preds(golds, preds))

    hl_sum = summarize(all_rows)
    strip_n = int(strip_rep.get("n") or index["summary"].get("n_strip_cases") or 0)
    strip_strict = int(strip_rep.get("strict_complete") or 0)
    strip_rate = float(strip_rep.get("strict_rate") or 0)
    strip_aux = float(strip_rep.get("aux_time_cat_rate") or 0)

    planned = strip_n + int(hl_sum["n"])
    executed = planned
    passed = strip_strict + int(hl_sum["strict_complete"])
    failed = executed - passed
    pass_rate = round(100.0 * passed / executed, 2) if executed else 0.0

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
        "拆条后端": "causal_chain6.classify (+Qwen)",
        "集锦后端": "causal_chain8.build_highlights (+Qwen, no-llm-narrative)",
        "拆条严格完整率": f"{strip_rate}%",
        "集锦严格完整率": f"{hl_sum['strict_rate']}%",
        "拆条辅(时间+大类)": f"{strip_aux}%",
        "集锦辅(时间+大类)": f"{hl_sum['aux_time_cat_rate']}%",
        "note": "集锦gold=select_moments同源窗+邻近标注补标签；时间匹配含锚点入窗；拆条沿用report_llm",
        "gold_dur_ms_mean": round(sum(dur_g) / max(len(dur_g), 1), 1),
        "pred_dur_ms_mean": round(sum(dur_p) / max(len(dur_p), 1), 1),
        "missing_reel_matches": missing_reel,
    }

    out = {
        "table_row": table_row,
        "strip": strip_rep,
        "highlight_no_t2": hl_sum,
        "fix": "highlight_gold_select_moments_v4",
    }
    out_path = ROOT / "reports" / "report_llm_hl_fix.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "reports" / "table_row_causal_chain.json").write_text(
        json.dumps(table_row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(table_row, ensure_ascii=False, indent=2))
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
