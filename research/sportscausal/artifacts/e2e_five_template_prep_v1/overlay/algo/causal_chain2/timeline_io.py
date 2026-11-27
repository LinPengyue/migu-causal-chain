"""整场时间轴 JSON 加载（从 causal_chain/external_io.py 迁入）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from causal_chain2.chain_schema import EVENT_TYPES
from causal_chain2.event_io import ensure_event_ids


def load_timeline_json(
    path: Path,
    *,
    id_prefix: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    支持 ``{"events": [{"t_ms", "type", "event_id"?}, ...]}`` 或根为事件数组。
    返回按 t_ms 升序的事件列表（保留 event_id/order 等字段）。
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        events = raw
        prefix = id_prefix or Path(path).stem
    else:
        if "events" not in raw:
            raise ValueError("时间轴 JSON 须含 events 数组，或根为数组")
        events = raw["events"]
        prefix = id_prefix or str(raw.get("match_id") or Path(path).stem)

    normalized: List[Dict[str, Any]] = []
    skipped = 0
    for i, e in enumerate(events):
        if not isinstance(e, dict):
            raise ValueError(f"events[{i}] 须为对象")
        if "type" not in e or "t_ms" not in e:
            raise ValueError(f"events[{i}] 须含 type 与 t_ms")
        typ = e["type"]
        # 交付全场事件可能含 schema 外类型：跳过而非中断集锦
        if typ not in EVENT_TYPES:
            skipped += 1
            continue
        ev = dict(e)
        ev["t_ms"] = int(ev["t_ms"])
        normalized.append(ev)

    if skipped:
        # 保持安静可复现；由调用方看 event_count
        pass
    if not normalized:
        raise ValueError(f"时间轴无可用事件（跳过未知类型 {skipped} 条）")

    normalized.sort(key=lambda x: x["t_ms"])
    return ensure_event_ids(normalized, prefix=prefix)
