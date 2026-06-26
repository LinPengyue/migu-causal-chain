"""读取 A3 jsonl，按需打包为 GraphPack；评测集清洗过滤。"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

import torch

from causal_chain2.a3_schema import A3Record, events_for_graph
from causal_chain2.graph_pack import GraphPack, pack_from_normalized_events


def event_type_sequence(rec: A3Record) -> Tuple[str, ...]:
    return tuple(e["type"] for e in events_for_graph(rec))


def seq_to_label_map(rows: List[A3Record]) -> Dict[Tuple[str, ...], Set[str]]:
    m: Dict[Tuple[str, ...], Set[str]] = defaultdict(set)
    for r in rows:
        m[event_type_sequence(r)].add(r.chain_template_id)
    return m


def is_unique_seq(rec: A3Record, label_map: Dict[Tuple[str, ...], Set[str]]) -> bool:
    labels = label_map.get(event_type_sequence(rec), set())
    return len(labels) == 1


def is_strict_tier(rec: A3Record) -> bool:
    return rec.validation.get("tier") == "strict"


def filter_unique_seq(rows: List[A3Record]) -> List[A3Record]:
    label_map = seq_to_label_map(rows)
    return [r for r in rows if is_unique_seq(r, label_map)]


def filter_strict_tier(rows: List[A3Record]) -> List[A3Record]:
    return [r for r in rows if is_strict_tier(r)]


def filter_eval_clean(rows: List[A3Record]) -> List[A3Record]:
    """保留 strict tier，或事件序列在全集内唯一对应一个 template_id 的样本。"""
    label_map = seq_to_label_map(rows)
    return [r for r in rows if is_strict_tier(r) or is_unique_seq(r, label_map)]


def filter_by_eval_mode(rows: List[A3Record], mode: str | None) -> List[A3Record]:
    if not mode or mode == "none":
        return rows
    if mode == "strict":
        return filter_strict_tier(rows)
    if mode == "unique_seq":
        return filter_unique_seq(rows)
    if mode == "clean":
        return filter_eval_clean(rows)
    raise ValueError(f"unknown eval filter mode: {mode}")


def filter_by_tier(rows: List[A3Record], filter_tier: str | None) -> List[A3Record]:
    """无 tier 的样本始终保留。有 tier 时仅保留落在 filter_tier 逗号列表内的样本。"""
    if not filter_tier or not str(filter_tier).strip():
        return rows
    allowed = {x.strip() for x in str(filter_tier).split(",") if x.strip()}
    if not allowed:
        return rows
    out: List[A3Record] = []
    for r in rows:
        t = r.validation.get("tier")
        if t is None:
            out.append(r)
        elif t in allowed:
            out.append(r)
    return out


def load_a3_jsonl(path: Path) -> List[A3Record]:
    rows: List[A3Record] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(A3Record.from_json_obj(json.loads(line)))
    return rows


def record_to_pack(rec: A3Record, device: torch.device | None = None) -> GraphPack:
    return pack_from_normalized_events(
        rec.events_normalized,
        rec.chain_template_id,
        device=device,
    )
