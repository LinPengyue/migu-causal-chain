"""读取 A3 jsonl，按需打包为 GraphPack。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

import torch

from causal_chain2.a3_schema import A3Record
from causal_chain2.graph_pack import GraphPack, pack_from_normalized_events


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
