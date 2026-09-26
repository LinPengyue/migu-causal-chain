"""chain4 内部样本：含抽取与分类结果。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from causal_chain6.io.extraction_result import ExtractionResult


@dataclass
class ClassifyResultV4:
    chain_template_id: str = ""
    chain_category: str = ""
    confidence: float = 0.0
    rationale: str = ""
    mode: str = "rule_only"


@dataclass
class PipelineResult:
    annotation_id: str
    match_id: str
    events_full: List[Dict[str, Any]]
    extraction: ExtractionResult
    classification: ClassifyResultV4
    gold_template_id: Optional[str] = None
    gold_category: Optional[str] = None
    gold_label_zh: str = ""
    mapping_warnings: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def events_extracted(self) -> List[Dict[str, Any]]:
        return self.extraction.events_extracted

    def to_dict(self) -> Dict[str, Any]:
        return {
            "annotation_id": self.annotation_id,
            "match_id": self.match_id,
            "events_full": self.events_full,
            "events_extracted": self.events_extracted,
            "extraction": self.extraction.to_dict(),
            "chain_template_id": self.classification.chain_template_id,
            "chain_category": self.classification.chain_category,
            "confidence": self.classification.confidence,
            "classification": {
                "chain_template_id": self.classification.chain_template_id,
                "chain_category": self.classification.chain_category,
                "confidence": self.classification.confidence,
                "rationale": self.classification.rationale,
                "mode": self.classification.mode,
            },
            "gold_template_id": self.gold_template_id,
            "mapping_warnings": self.mapping_warnings,
            "meta": self.meta,
        }


@dataclass
class EvalRecord:
    annotation_id: str
    match_id: str
    gold_template_id: str
    gold_category: str
    gold_label_zh: str
    gold_category_zh: str
    events_raw: List[Dict[str, Any]]
    events_normalized: List[Dict[str, Any]] = field(default_factory=list)
    events_extracted: List[Dict[str, Any]] = field(default_factory=list)
    extraction: Optional[ExtractionResult] = None
    mapping_warnings: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    gold_template_id_relabel: Optional[str] = None
    pred_template_id: Optional[str] = None

    @property
    def types_normalized(self) -> List[str]:
        return [str(e.get("type", "")) for e in self.events_normalized]

    @property
    def types_extracted(self) -> List[str]:
        if self.events_extracted:
            return [str(e.get("type", "")) for e in self.events_extracted]
        return self.types_normalized

    # 兼容旧字段名
    @property
    def events_core(self) -> List[Dict[str, Any]]:
        return self.events_extracted or self.events_normalized

    @property
    def types_core(self) -> List[str]:
        return self.types_extracted

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "annotation_id": self.annotation_id,
            "match_id": self.match_id,
            "gold_template_id": self.gold_template_id,
            "gold_category": self.gold_category,
            "gold_label_zh": self.gold_label_zh,
            "gold_category_zh": self.gold_category_zh,
            "events_raw": self.events_raw,
            "events_normalized": self.events_normalized,
            "events_extracted": self.events_extracted,
            "mapping_warnings": self.mapping_warnings,
            "meta": self.meta,
            "gold_template_id_relabel": self.gold_template_id_relabel,
            "pred_template_id": self.pred_template_id,
        }
        if self.extraction:
            d["extraction"] = self.extraction.to_dict()
        return d
