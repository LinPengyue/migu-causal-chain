"""events → 图（从 causal_chain/graph_convert.py 迁入）。"""

from __future__ import annotations

from typing import Any, Dict, List

from causal_chain2.chain_schema import EVENT_TYPES


def events_to_graph(
    min_obj: Dict[str, Any], *, optional_max_skip: int = 2
) -> Dict[str, Any]:
    events = min_obj["events"]
    nodes: List[Dict[str, Any]] = []
    for i, ev in enumerate(events):
        nid = f"e{i}"
        et = ev["type"]
        nodes.append(
            {
                "id": nid,
                "type": et,
                "label_zh": EVENT_TYPES.get(et),
                "order": ev.get("order", i),
                "t_ms": ev.get("t_ms"),
            }
        )

    edges: List[Dict[str, Any]] = []
    n = len(events)
    for i in range(n - 1):
        edges.append(
            {
                "src": f"e{i}",
                "dst": f"e{i + 1}",
                "rel": "temporal_next",
                "weight": 1.0,
            }
        )
    for i in range(n):
        for skip in range(2, optional_max_skip + 1):
            j = i + skip
            if j < n:
                edges.append(
                    {
                        "src": f"e{i}",
                        "dst": f"e{j}",
                        "rel": "optional_causal",
                        "weight": 0.25,
                    }
                )

    return {"root_ids": ["e0"] if n else [], "nodes": nodes, "edges": edges}
