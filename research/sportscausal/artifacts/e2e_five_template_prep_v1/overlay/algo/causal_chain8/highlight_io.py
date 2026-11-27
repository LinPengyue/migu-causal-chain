"""读写 timeline / reel JSON。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from causal_chain2.timeline_io import load_timeline_json


def load_timeline_document(path: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """返回 (events, meta)。meta 含 match_id、ground_truth_chains 等。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return load_timeline_json(path), {}
    events = load_timeline_json(path)
    meta = {k: v for k, v in raw.items() if k != "events"}
    return events, meta


def write_reel_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
