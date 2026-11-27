"""A3 分层记录：events_raw / events_normalized / 校验元数据。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


SCHEMA_VERSION = "1.0-a3"


@dataclass
class A3Record:
    """单条训练/推理样本（图级标签为 chain_template_id）。

    ``validation`` 常含 ``mode``、``tier``（strict|relaxed|rejected）、``normalized`` 等；构图仅用 ``events_normalized``。
    推荐 ``events_normalized`` 每条含 ``event_id``、``order``、``type``、``t_ms``。
    """

    annotation_id: str
    match_id: str
    chain_category: str
    chain_template_id: str
    events_raw: List[Dict[str, Any]]
    events_normalized: List[Dict[str, Any]]
    validation: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_json_obj(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "annotation_id": self.annotation_id,
            "match_id": self.match_id,
            "chain_category": self.chain_category,
            "chain_template_id": self.chain_template_id,
            "events_raw": self.events_raw,
            "events_normalized": self.events_normalized,
            "validation": self.validation,
        }

    @staticmethod
    def from_json_obj(o: Dict[str, Any]) -> "A3Record":
        return A3Record(
            annotation_id=o["annotation_id"],
            match_id=o["match_id"],
            chain_category=o["chain_category"],
            chain_template_id=o["chain_template_id"],
            events_raw=list(o.get("events_raw", o["events_normalized"])),
            events_normalized=list(o["events_normalized"]),
            validation=dict(o.get("validation", {})),
            schema_version=o.get("schema_version", SCHEMA_VERSION),
        )


def events_for_graph(rec: A3Record) -> List[Dict[str, Any]]:
    """构图一律使用 normalized 序列。"""
    return rec.events_normalized
