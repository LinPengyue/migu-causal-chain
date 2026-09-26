"""从 A3 jsonl 导出清洗后的评测子集（strict / unique_seq / clean）。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from causal_chain2.a3_schema import A3Record
from causal_chain2.dataset import (
    filter_by_eval_mode,
    filter_by_tier,
    load_a3_jsonl,
    seq_to_label_map,
)


def main() -> None:
    ap = argparse.ArgumentParser(description="导出清洗后的 eval A3 jsonl")
    ap.add_argument("--in", dest="in_path", type=Path, required=True)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument(
        "--mode",
        choices=["strict", "unique_seq", "clean"],
        default="clean",
        help="strict=仅 tier strict；unique_seq=序列唯一对应标签；clean=strict 或 unique_seq 并集",
    )
    ap.add_argument(
        "--filter-tier",
        type=str,
        default=None,
        help="可选：先按 tier 过滤（如 strict,relaxed）",
    )
    args = ap.parse_args()

    rows = load_a3_jsonl(args.in_path.expanduser().resolve())
    rows = filter_by_tier(rows, args.filter_tier)
    before = len(rows)
    cleaned = filter_by_eval_mode(rows, args.mode)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for rec in cleaned:
            f.write(json.dumps(rec.to_json_obj(), ensure_ascii=False) + "\n")

    label_map = seq_to_label_map(rows)
    ambig = sum(1 for s, ls in label_map.items() if len(ls) > 1)
    strict_n = sum(1 for r in rows if r.validation.get("tier") == "strict")
    print(
        f"mode={args.mode}  in={before}  out={len(cleaned)}  "
        f"strict_in_source={strict_n}  ambiguous_seqs={ambig}"
    )
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
