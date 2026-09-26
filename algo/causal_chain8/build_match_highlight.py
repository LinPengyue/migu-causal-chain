#!/usr/bin/env python3
"""CLI：strip chains → 全场集锦因果链（P5 MVP）。

示例：
  PYTHONPATH=algo python -m causal_chain8.build_match_highlight \\
    --strip-gold datasets/matches/.../strip_gold.json --match-id demo --out out.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _load_strip_chains(path: Path) -> List[Dict[str, Any]]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        if "chains" in obj:
            return list(obj.get("chains") or [])
        if "clips" in obj:
            return list(obj.get("clips") or [])
        if "nodes" in obj:
            return list(obj.get("nodes") or [])
    raise ValueError(f"unsupported strip input shape: {path}")


def main(argv: List[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="P5: link strip chains into match highlight_chain")
    ap.add_argument("--strip-gold", type=Path, default=None, help="strip_gold.json")
    ap.add_argument("--strip-json", type=Path, default=None, help="strip pipeline out (clips) 或 chains json")
    ap.add_argument("--match-id", type=str, default="")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)

    src_path = args.strip_gold or args.strip_json
    if src_path is None:
        ap.error("need --strip-gold or --strip-json")
    chains = _load_strip_chains(src_path)
    source = "strip_gold" if args.strip_gold else "strip_json"
    mid = args.match_id or src_path.parent.name

    from causal_chain8.link_strip_chains import build_match_highlight_chain

    out = build_match_highlight_chain(chains, match_id=mid, source=source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "match_id": out["match_id"],
                "n_nodes": out["stats"]["n_strip_chains"],
                "n_edges": out["stats"]["n_edges"],
                "rel_counts": out["stats"]["rel_counts"],
                "out": str(args.out),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
