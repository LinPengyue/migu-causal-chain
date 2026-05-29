"""整场时间轴 JSON 加载（从 causal_chain/external_io.py 迁入）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from causal_chain2.chain_schema import EVENT_TYPES


def load_timeline_json(path: Path) -> List[Dict[str, Any]]:
    """
    支持 ``{"events": [{"t_ms", "type"}, ...]}`` 或根为事件数组。
    返回按 t_ms 升序的事件列表。
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        events = raw
    else:
        if "events" not in raw:
            raise ValueError("时间轴 JSON 须含 events 数组，或根为数组")
        events = raw["events"]
    out: List[Dict[str, Any]] = []
    for i, e in enumerate(events):
        if not isinstance(e, dict):
            raise ValueError(f"events[{i}] 须为对象")
        if "type" not in e or "t_ms" not in e:
            raise ValueError(f"events[{i}] 须含 type 与 t_ms")
        if e["type"] not in EVENT_TYPES:
            raise ValueError(f"未知事件类型: {e['type']!r}")
        out.append({"t_ms": int(e["t_ms"]), "type": e["type"]})
    out.sort(key=lambda x: x["t_ms"])
    return out
