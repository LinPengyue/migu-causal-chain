"""可插拔映射策略链。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

from causal_chain2.event_io import ensure_event_ids

from causal_chain8.mapping.presets import (
    CAT_ZH_TO_EN,
    LABEL_ZH_TO_TEMPLATE,
    map_event_annotation_compat,
    map_event_params_first,
    map_event_strict,
    validate_official_zh,
)

EventMapper = Callable[[Dict[str, Any], List[str]], str]


@dataclass
class MappingContext:
    strategy: str = "annotation_compat"
    validate_zh: bool = False
    warnings: List[str] = field(default_factory=list)

    def mapper(self) -> EventMapper:
        if self.strategy == "strict_34":
            return map_event_strict
        if self.strategy == "params_first":
            return map_event_params_first
        return map_event_annotation_compat


def parse_mapping_chain(spec: str) -> List[str]:
    """例如 params_first+strict_34 → 按顺序应用（后者覆盖前者语义时取最后一个 mapper）。"""
    parts = [p.strip() for p in spec.replace(",", "+").split("+") if p.strip()]
    return parts or ["annotation_compat"]


def resolve_mapper(spec: str) -> EventMapper:
    chain = parse_mapping_chain(spec)
    primary = chain[-1]
    ctx = MappingContext(strategy=primary)

    def _map(ev: Dict[str, Any], warnings: List[str]) -> str:
        w: List[str] = []
        if "params_first" in chain:
            en = map_event_params_first(ev, w)
        elif "strict_34" in chain:
            en = map_event_strict(ev, w)
        else:
            en = map_event_annotation_compat(ev, w)
        warnings.extend(w)
        if "strict_34" in chain:
            validate_official_zh(ev, warnings)
        return en

    _ = ctx
    return _map


def normalize_events_raw(
    events: List[Dict[str, Any]],
    *,
    mapper: EventMapper,
    prefix: str,
    warnings: List[str],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    raw_out: List[Dict[str, Any]] = []
    typed: List[Dict[str, Any]] = []
    base_ms = None
    for ev in sorted(events, key=lambda x: (x.get("order", 0), x.get("t_ms", 0))):
        t_ms = ev.get("t_ms")
        if t_ms is not None:
            t_ms = float(t_ms)
            if base_ms is None:
                base_ms = t_ms
        raw_out.append(
            {
                "order": ev.get("order", len(raw_out)),
                "type": ev.get("type"),
                "t_ms": int(t_ms) if t_ms is not None else 0,
            }
        )
        en = mapper(ev, warnings)
        rel = int(t_ms - base_ms) if (t_ms is not None and base_ms is not None) else 0
        typed.append({"order": len(typed), "type": en, "t_ms": rel})

    typed.sort(key=lambda x: (x["t_ms"], x["order"]))
    for i, ev in enumerate(typed):
        ev["order"] = i
    normalized = ensure_event_ids(typed, prefix=prefix)
    return normalized, raw_out


def label_to_template(label_zh: str) -> str:
    tid = LABEL_ZH_TO_TEMPLATE.get(str(label_zh).strip())
    if not tid:
        raise ValueError(f"unknown chain_template_id label: {label_zh!r}")
    return tid


def category_zh_to_en(cat_zh: str, template_id: str) -> str:
    from causal_chain8.schema.templates import CHAIN4_TEMPLATES

    cat = CAT_ZH_TO_EN.get(str(cat_zh).strip())
    if cat:
        return cat
    return CHAIN4_TEMPLATES.get(template_id, {}).get("category", "outcome")


def apply_mapping_chain(
    row: Dict[str, Any],
    *,
    mapping_spec: str,
    index: int,
) -> tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []
    mapper = resolve_mapper(mapping_spec)
    # 交付导出常用 causal_chain_subtype；旧标注则为中文 chain_template_id
    label = str(row.get("chain_template_id", "")).strip()
    if not label:
        label = str(row.get("causal_chain_subtype", "")).strip()
    if not label:
        label = str(row.get("causal_chain_other_name", "")).strip()
    template_id = label_to_template(label)
    cat_zh = str(row.get("chain_category", "")).strip()
    category = category_zh_to_en(cat_zh, template_id)
    ann_id = str(row.get("annotation_id") or f"causal_{index:04d}")
    prefix = ann_id.replace("/", "_")[:32]
    normalized, raw_events = normalize_events_raw(
        list(row.get("events") or []),
        mapper=mapper,
        prefix=prefix,
        warnings=warnings,
    )
    meta = dict(row.get("_file_meta") or {})
    for key in (
        "bz_id",
        "segment_time_sketch",
        "segment_time_video",
        "is_replay",
        "prev_related_id",
        "video_name",
    ):
        if row.get(key):
            meta[key] = row[key]
    if not meta.get("video_name") and isinstance(row.get("_file_meta"), dict):
        meta.setdefault("video_name", row["_file_meta"].get("video_name", ""))

    pack = {
        "annotation_id": ann_id,
        "match_id": str(row.get("match_id") or meta.get("match_id") or ""),
        "gold_template_id": template_id,
        "gold_category": category,
        "gold_label_zh": label,
        "gold_category_zh": cat_zh,
        "events_raw": raw_events,
        "events_normalized": normalized,
        "mapping_warnings": warnings,
        "meta": meta,
    }
    return pack, warnings
