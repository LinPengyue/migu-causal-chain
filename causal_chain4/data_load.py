"""加载分类样本：A3 jsonl 或 causal JSON → A3Record 列表。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from causal_chain2.a3_schema import A3Record, SCHEMA_VERSION
from causal_chain2.dataset import filter_by_eval_mode, filter_by_tier, load_a3_jsonl

from causal_chain4.io.load_causal_min import load_causal_file
from causal_chain4.mapping.strategies import apply_mapping_chain


def _is_causal_export(path: Path) -> bool:
    if path.suffix.lower() == ".jsonl":
        return False
    if path.suffix.lower() != ".json":
        return False
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "causal_chains" in raw:
        return True
    if isinstance(raw, list) and raw:
        first = raw[0]
        return isinstance(first, dict) and (
            "chain_template_id" in first or "events" in first
        )
    return False


def causal_json_to_records(path: Path, *, profile: Dict[str, Any]) -> List[A3Record]:
    rows, file_meta = load_causal_file(path)
    mapping = str(profile.get("mapping", "annotation_compat"))
    out: List[A3Record] = []
    for i, row in enumerate(rows):
        if file_meta and "_file_meta" not in row:
            row["_file_meta"] = file_meta
        pack, warnings = apply_mapping_chain(row, mapping_spec=mapping, index=i)
        validation: Dict[str, Any] = {
            "mode": "chain4_causal_import",
            "tier": "external",
            "source_file": path.name,
            "warnings": warnings,
        }
        for key in ("bz_id", "segment_time_sketch", "segment_time_video", "is_replay"):
            if pack["meta"].get(key):
                validation[key] = pack["meta"][key]
        out.append(
            A3Record(
                annotation_id=pack["annotation_id"],
                match_id=pack["match_id"],
                chain_category=pack["gold_category"],
                chain_template_id=pack["gold_template_id"],
                events_raw=pack["events_raw"],
                events_normalized=pack["events_normalized"],
                validation=validation,
                schema_version=SCHEMA_VERSION,
            )
        )
    return out


def load_classify_records(
    path: Path,
    *,
    profile: Dict[str, Any],
    filter_tier: str | None = None,
    eval_filter: str = "none",
) -> List[A3Record]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)

    if _is_causal_export(path):
        rows = causal_json_to_records(path, profile=profile)
    else:
        rows = load_a3_jsonl(path)

    rows = filter_by_tier(rows, filter_tier)
    rows = filter_by_eval_mode(rows, eval_filter)
    return rows
