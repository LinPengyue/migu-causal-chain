"""HighlightReel / HighlightChain 数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ChainEdge:
    src: int
    dst: int
    rel: str  # temporal_next | causal_leads_to

    def to_dict(self) -> Dict[str, Any]:
        return {"src": self.src, "dst": self.dst, "rel": self.rel}


@dataclass
class ChainEvent:
    order: int
    type: str
    t_ms: int
    role: str = "event"  # build_up | set_piece | shot | outcome | correction | ...
    global_index: int = -1

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "order": self.order,
            "type": self.type,
            "t_ms": self.t_ms,
            "role": self.role,
        }
        if self.global_index >= 0:
            d["global_index"] = self.global_index
        return d


@dataclass
class HighlightChain:
    clip_id: str
    chain_template_id: str
    chain_label_zh: str
    chain_category: str
    t0_ms: int
    t1_ms: int
    anchor_type: str
    anchor_t_ms: int
    events: List[ChainEvent] = field(default_factory=list)
    context_events: List[ChainEvent] = field(default_factory=list)
    edges: List[ChainEdge] = field(default_factory=list)
    narrative_zh: str = ""
    confidence: float = 0.0
    margin: float = 0.0
    fast_path: bool = False
    validation: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "chain_template_id": self.chain_template_id,
            "chain_label_zh": self.chain_label_zh,
            "chain_category": self.chain_category,
            "t0_ms": self.t0_ms,
            "t1_ms": self.t1_ms,
            "anchor_event": {"type": self.anchor_type, "t_ms": self.anchor_t_ms},
            "events": [e.to_dict() for e in self.events],
            "context_events": [e.to_dict() for e in self.context_events],
            "edges": [e.to_dict() for e in self.edges],
            "narrative_zh": self.narrative_zh,
            "confidence": round(self.confidence, 6),
            "margin": round(self.margin, 6),
            "fast_path": self.fast_path,
            "validation": self.validation,
        }


@dataclass
class HighlightReel:
    match_id: str
    input_file: str
    event_count: int
    clips: List[HighlightChain] = field(default_factory=list)
    ordering: List[str] = field(default_factory=list)
    total_duration_ms: int = 0
    config: Dict[str, Any] = field(default_factory=dict)
    stats: Dict[str, Any] = field(default_factory=dict)
    ground_truth: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "match_id": self.match_id,
            "input_file": self.input_file,
            "event_count": self.event_count,
            "reel": {
                "clips": [c.to_dict() for c in self.clips],
                "ordering": self.ordering,
                "total_duration_ms": self.total_duration_ms,
            },
            "config": self.config,
            "stats": self.stats,
        }
        if self.ground_truth is not None:
            out["ground_truth_chains"] = self.ground_truth
        return out
