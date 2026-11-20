"""抽取结果数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ExtractionResult:
    events_extracted: List[Dict[str, Any]] = field(default_factory=list)
    extracted_indices: List[int] = field(default_factory=list)
    template_hint: str = ""
    canonical_pattern: List[str] = field(default_factory=list)
    method: str = "canonical_align"
    score: float = 0.0
    transitions_ok: bool = False
    exact_canonical: bool = False
    candidate_templates: List[str] = field(default_factory=list)
    margin: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "events_extracted": self.events_extracted,
            "extracted_indices": self.extracted_indices,
            "template_hint": self.template_hint,
            "canonical_pattern": self.canonical_pattern,
            "method": self.method,
            "score": round(self.score, 4),
            "transitions_ok": self.transitions_ok,
            "exact_canonical": self.exact_canonical,
            "candidate_templates": self.candidate_templates,
            "margin": round(self.margin, 4),
        }
