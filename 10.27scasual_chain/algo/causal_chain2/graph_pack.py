"""将 normalized 事件链转为张量包，供纯 PyTorch GNN 使用（不依赖 PyG）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import torch

from causal_chain2.chain_graph_convert import events_to_graph
from causal_chain2.chain_schema import ALL_TEMPLATE_IDS, EVENT_TYPES


def _type_index() -> Dict[str, int]:
    return {t: i for i, t in enumerate(sorted(EVENT_TYPES.keys()))}


def _template_index() -> Dict[str, int]:
    return {t: i for i, t in enumerate(sorted(ALL_TEMPLATE_IDS))}


TYPE_TO_IX = _type_index()
TEMPLATE_TO_IX = _template_index()
NUM_NODE_TYPES = len(TYPE_TO_IX)
NUM_CLASSES = len(TEMPLATE_TO_IX)


@dataclass
class GraphPack:
    x: torch.Tensor
    edge_index: torch.Tensor
    y: torch.Tensor
    edge_label: torch.Tensor
    template_id: str


def pack_from_normalized_events(
    events: List[Dict[str, Any]],
    chain_template_id: str,
    *,
    optional_max_skip: int = 2,
    device: torch.device | None = None,
) -> GraphPack:
    """
    x: [N, 1 + num_types] = [t_norm, one_hot type]
    edge_index: [2, E] 有向边（含 temporal_next 与 optional）
    y: 标量类别 chain_template_id
    edge_label: [E]  1=temporal_next（主干），0=optional（弱负例/辅助）
    """
    min_obj = {"events": events}
    g = events_to_graph(min_obj, optional_max_skip=optional_max_skip)
    nodes = g["nodes"]
    n = len(nodes)
    if n == 0:
        raise ValueError("empty graph")
    t_ms = [float(nodes[i].get("t_ms") or 0.0) for i in range(n)]
    t0, t1 = min(t_ms), max(t_ms)
    span = max(t1 - t0, 1.0)
    t_norm = [(ti - t0) / span for ti in t_ms]

    x = torch.zeros(n, 1 + NUM_NODE_TYPES)
    for i, node in enumerate(nodes):
        x[i, 0] = t_norm[i]
        ti = TYPE_TO_IX.get(node["type"], 0)
        x[i, 1 + ti] = 1.0

    src_list: List[int] = []
    dst_list: List[int] = []
    rel_list: List[int] = []
    id_to_i = {node["id"]: i for i, node in enumerate(nodes)}
    for e in g["edges"]:
        u = id_to_i[e["src"]]
        v = id_to_i[e["dst"]]
        src_list.append(u)
        dst_list.append(v)
        rel_list.append(1 if e["rel"] == "temporal_next" else 0)

    edge_index = torch.tensor([src_list, dst_list], dtype=torch.long)
    edge_label = torch.tensor(rel_list, dtype=torch.float32)
    y = torch.tensor([TEMPLATE_TO_IX[chain_template_id]], dtype=torch.long)

    if device is not None:
        x = x.to(device)
        edge_index = edge_index.to(device)
        y = y.to(device)
        edge_label = edge_label.to(device)

    return GraphPack(
        x=x,
        edge_index=edge_index,
        y=y,
        edge_label=edge_label,
        template_id=chain_template_id,
    )


def pack_from_events_list(
    events: List[Dict[str, Any]],
    *,
    optional_max_skip: int = 2,
    device: torch.device | None = None,
) -> Tuple[torch.Tensor, torch.Tensor]:
    """推理用：仅返回 ``x`` 与 ``edge_index``（不依赖真实标签）。"""
    min_obj = {"events": events}
    g = events_to_graph(min_obj, optional_max_skip=optional_max_skip)
    nodes = g["nodes"]
    n = len(nodes)
    if n == 0:
        raise ValueError("empty graph")
    t_ms = [float(nodes[i].get("t_ms") or 0.0) for i in range(n)]
    t0, t1 = min(t_ms), max(t_ms)
    span = max(t1 - t0, 1.0)
    t_norm = [(ti - t0) / span for ti in t_ms]

    x = torch.zeros(n, 1 + NUM_NODE_TYPES)
    for i, node in enumerate(nodes):
        x[i, 0] = t_norm[i]
        ti = TYPE_TO_IX.get(node["type"], 0)
        x[i, 1 + ti] = 1.0

    src_list: List[int] = []
    dst_list: List[int] = []
    id_to_i = {node["id"]: i for i, node in enumerate(nodes)}
    for e in g["edges"]:
        u = id_to_i[e["src"]]
        v = id_to_i[e["dst"]]
        src_list.append(u)
        dst_list.append(v)

    edge_index = torch.tensor([src_list, dst_list], dtype=torch.long)
    if device is not None:
        x = x.to(device)
        edge_index = edge_index.to(device)
    return x, edge_index
