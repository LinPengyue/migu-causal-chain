#!/usr/bin/env python3
"""脚本 B：有上游事件 + *_causal.json → 输出拆条/集锦 + 逻辑完整率。

流程：
  1) 交付_out 成对 json → scripts/build_datasets → datasets/
  2) 按场跑拆条 + 集锦，并对 gold 算完整率

用法：
  cd 9.31causal_chain
  export PYTHONPATH="$PWD/algo:$PWD/eval"
  python eval/run_e2e_eval.py --limit-matches 2
  python eval/run_e2e_eval.py --src-dir /path/to/交付_out
  python eval/run_e2e_eval.py --skip-build   # datasets 已就绪时
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "algo"))
sys.path.insert(0, str(ROOT / "eval"))

from delivery_io import (  # noqa: E402
    build_datasets_from_src,
    default_src_dir,
    list_causal_pairs,
)
from eval_common import REPORTS  # noqa: E402
import run_linked_pipeline as linked  # noqa: E402


def main(argv: List[str] | None = None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="E2E eval: plain+causal → output + logic rates")
    ap.add_argument("--src-dir", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, default=REPORTS / "e2e_eval")
    ap.add_argument("--limit-matches", type=int, default=0)
    ap.add_argument("--profile", default="production")
    ap.add_argument("--skip-build", action="store_true", help="跳过数据转化（已有 datasets）")
    ap.add_argument(
        "--strip-mode",
        choices=["module", "timeline", "online", "all"],
        default="all",
    )
    ap.add_argument("--module-event-source", choices=["gold_events", "timeline"], default="gold_events")
    ap.add_argument("--online-stream-source", choices=["gold_events", "timeline"], default="gold_events")
    ap.add_argument("--prefix-stride", type=int, default=1)
    ap.add_argument("--min-prefix", type=int, default=2)
    ap.add_argument("--keep-t2", action="store_true")
    args = ap.parse_args(argv)

    src = args.src_dir or default_src_dir()
    if not src.is_dir():
        raise SystemExit(f"missing src-dir: {src}")

    pairs = list_causal_pairs(src)
    if not pairs:
        raise SystemExit(
            f"未找到成对 plain+*_causal.json（目录: {src}）。"
            f"若只有上游事件、无标注，请用: python eval/run_e2e_infer.py"
        )

    if not args.skip_build:
        print(f"[1/2] build_datasets from {src} ({len(pairs)} pairs) ...", flush=True)
        build_datasets_from_src(src, quiet=False)
    else:
        print("[1/2] skip-build", flush=True)

    print("[2/2] strip + highlight + logic rates ...", flush=True)
    linked_argv = [
        "--out-dir",
        str(args.out_dir),
        "--limit-matches",
        str(args.limit_matches),
        "--profile",
        args.profile,
        "--strip-mode",
        args.strip_mode,
        "--module-event-source",
        args.module_event_source,
        "--online-stream-source",
        args.online_stream_source,
        "--prefix-stride",
        str(args.prefix_stride),
        "--min-prefix",
        str(args.min_prefix),
    ]
    if args.keep_t2:
        linked_argv.append("--keep-t2")
    summary = linked.main(linked_argv)
    summary["task"] = "e2e_eval"
    summary["src_dir"] = str(src)
    summary["has_gold"] = True
    summary["n_causal_pairs"] = len(pairs)
    # 回写标注
    out = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    sum_path = out / "_summary.json"
    if sum_path.exists():
        import json

        obj = json.loads(sum_path.read_text(encoding="utf-8"))
        obj["task"] = "e2e_eval"
        obj["src_dir"] = str(src)
        obj["has_gold"] = True
        obj["n_causal_pairs"] = len(pairs)
        sum_path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    main()
