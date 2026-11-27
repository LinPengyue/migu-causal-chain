"""事件字段规范化：event_id 透传与自动生成。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _pick_event_id(raw: Dict[str, Any]) -> Optional[str]:
    for key in ("event_id", "id", "eventId"):
        val = raw.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return None


def ensure_event_ids(
    events: List[Dict[str, Any]],
    *,
    prefix: str = "evt",
) -> List[Dict[str, Any]]:
    """保留 type/t_ms/order 及已有字段；缺失 event_id 时按 prefix 自动生成。"""
    out: List[Dict[str, Any]] = []
    safe_prefix = prefix.strip() or "evt"
    for i, raw in enumerate(events):
        if not isinstance(raw, dict):
            raise ValueError(f"events[{i}] must be a dict")
        ev = dict(raw)
        eid = _pick_event_id(ev)
        if not eid:
            eid = f"{safe_prefix}_e{i:04d}"
        ev["event_id"] = eid
        if "order" not in ev:
            ev["order"] = i
        out.append(ev)
    return out


def compact_event(ev: Dict[str, Any], *, order: Optional[int] = None) -> Dict[str, Any]:
    """LLM prompt 用紧凑事件（含 event_id）。"""
    d: Dict[str, Any] = {
        "event_id": ev.get("event_id", ""),
        "order": ev.get("order", order if order is not None else 0),
        "type": ev.get("type"),
        "t_ms": ev.get("t_ms"),
    }
    return d


def events_for_output(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """写 JSON 输出用：标准事件列表。"""
    return [
        {
            "event_id": e.get("event_id", ""),
            "order": e.get("order", i),
            "type": e["type"],
            "t_ms": int(e["t_ms"]),
        }
        for i, e in enumerate(events)
    ]
