"""输出 A3 jsonl / 1.0-min 扩展格式。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from causal_chain2.a3_schema import SCHEMA_VERSION

from causal_chain4.io.eval_record import PipelineResult


def pipeline_to_a3_row(result: PipelineResult, *, source_file: str = "") -> Dict[str, Any]:
    validation: Dict[str, Any] = {
        "mode": "chain4_pipeline",
        "tier": "inferred",
        "source_file": source_file,
        "warnings": list(result.mapping_warnings),
        "extraction": result.extraction.to_dict(),
        "classification_mode": result.classification.mode,
        "confidence": result.classification.confidence,
    }
    for key in ("segment_time_sketch", "segment_time_video", "is_replay", "bz_id"):
        if result.meta.get(key):
            validation[key] = result.meta[key]

    return {
        "schema_version": SCHEMA_VERSION,
        "annotation_id": result.annotation_id,
        "match_id": result.match_id,
        "chain_category": result.classification.chain_category,
        "chain_template_id": result.classification.chain_template_id,
        "events_raw": result.events_full,
        "events_normalized": result.events_extracted,
        "validation": validation,
    }


def write_a3_jsonl(results: List[PipelineResult], path: Path, *, source_file: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(pipeline_to_a3_row(r, source_file=source_file), ensure_ascii=False) for r in results]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def write_pipeline_jsonl(results: List[PipelineResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r.to_dict(), ensure_ascii=False) for r in results]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
