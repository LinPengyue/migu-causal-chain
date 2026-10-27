"""读取 1.0-min causal JSON（数组或 causal_chains 包装）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


def load_causal_rows(path: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw, {}

    if isinstance(raw, dict) and "causal_chains" in raw:
        meta = {k: v for k, v in raw.items() if k != "causal_chains"}
        rows: List[Dict[str, Any]] = []
        for chain in raw["causal_chains"]:
            row = dict(chain)
            row.setdefault("match_id", meta.get("match_id", path.stem))
            row.setdefault("schema_version", meta.get("schema_version", "1.0-min"))
            row["_file_meta"] = meta
            rows.append(row)
        return rows, meta

    raise ValueError(f"{path}: expected JSON array or object with causal_chains")


def load_causal_file(path: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return load_causal_rows(path)
