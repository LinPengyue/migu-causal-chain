"""Zero-HTTP, provenance-preserving replay of a saved Stage-1 model body.

NOT a new model result, not a semantic approval, and not a LIVE/EDL gate.
Keeps historical Run02 output untouched; works on copies in a NEW out-dir.
Python 3.9 compatible.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .story_first_hypotheses import (
    build_observation_plan, evidence_matrix, parse_hypotheses,
)
from .story_first_poc_cli import parse_model_json, write_json


def recover_singleton_array_shapes(
    original: Mapping[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Only recover unambiguous Stage-1 scalar/object -> one-element array.

    Do not invent events, relations, evidence, prose, probes, timestamps, or
    missing fields. Strict parse_hypotheses still makes the final decision.
    """
    obj = copy.deepcopy(dict(original))
    rows = obj.get("hypotheses")
    if not isinstance(rows, list):
        raise ValueError("hypotheses_must_be_list")
    fixes = []
    for i, h in enumerate(rows):
        if not isinstance(h, dict):
            continue
        for field, kind in (
            ("proposed_long_range_relations", dict),
            ("falsification_conditions", str),
            ("observation_queries", dict),
        ):
            val = h.get(field)
            if isinstance(val, kind):
                h[field] = [val]
                fixes.append({
                    "index": i,
                    "field": field,
                    "operation": "wrap_existing_value_in_single_element_array",
                    "original_type": type(val).__name__,
                    "new_type": "list",
                })
    return obj, {
        "schema_recovery": "SINGLETON_ARRAY_SHAPE_ONLY_V1",
        "converted_fields": fixes,
        "converted_count": len(fixes),
        "content_added_or_removed": False,
        "semantic_quality_re_evaluated": False,
        "video_observed": False,
        "first_live_certified": False,
        "edl_modified": False,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run02 saved raw offline schema audit")
    parser.add_argument("--prepared-story-input", type=Path, required=True)
    parser.add_argument("--raw-response", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--max-hypotheses", type=int, default=2)
    args = parser.parse_args(argv)
    if not 1 <= args.max_hypotheses <= 5:
        parser.error("max_hypotheses must be in [1,5]")
    if not args.prepared_story_input.is_file() or not args.raw_response.is_file():
        parser.error("input files not found")
    if args.out_dir.exists() and (
        not args.out_dir.is_dir() or any(args.out_dir.iterdir())
    ):
        parser.error("output must be a new empty directory (no overwrite)")
    try:
        prepared = json.loads(args.prepared_story_input.read_text(encoding="utf-8"))
        raw_bytes = args.raw_response.read_bytes()
        raw = parse_model_json(raw_bytes.decode("utf-8"))
        fixed, audit = recover_singleton_array_shapes(raw)
        audit.update({
            "source_raw_path": str(args.raw_response),
            "source_raw_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "source_prepared_sha256": hashlib.sha256(
                args.prepared_story_input.read_bytes()
            ).hexdigest(),
            "http_attempts": 0,
            "paid_http_authorized": False,
            "source_run": "RUN02_EXISTING_RAW_NOT_NEW_MODEL_RESULT",
        })
        validated = parse_hypotheses(
            fixed, prepared, max_hypotheses=args.max_hypotheses
        )
        audit["structurally_accepted"] = len(validated["hypotheses"])
        audit["structurally_rejected"] = len(validated["rejected"])
        audit["story_stage1_passed"] = False
        audit["status"] = "OFFLINE_SCHEMA_RECOVERY_UNVERIFIED"
        # No historical artifacts may be overwritten.
        args.out_dir.mkdir(parents=True, exist_ok=True)
        write_json(args.out_dir / "schema_recovery_audit.json", audit)
        write_json(args.out_dir / "recovered_raw_shape.json", fixed)
        write_json(args.out_dir / "schema_recovery_hypotheses.json", validated)
        write_json(args.out_dir / "schema_recovery_evidence_matrix.json",
                   evidence_matrix(prepared, validated))
        write_json(args.out_dir / "schema_recovery_observation_plan.json",
                   build_observation_plan(prepared, validated))
        print(json.dumps({
            "status": audit["status"],
            "structurally_accepted": audit["structurally_accepted"],
            "structurally_rejected": audit["structurally_rejected"],
            "http_attempts": 0,
            "story_stage1_passed": False,
            "out_dir": str(args.out_dir),
        }, ensure_ascii=False))
        return 0
    except Exception as exc:
        print("OFFLINE_SCHEMA_RECOVERY_FAILED: " + str(exc)[:200], file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
