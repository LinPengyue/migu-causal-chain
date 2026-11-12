"""P10-F read-only evaluation of narrative function risk against sealed human labels.

No model calls, no EDL mutation, no video rendering, no label injection.
The human labels must be collected independently of the risk predictions.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


VALID_RISKS = {"HIGH_UNVERIFIED", "ELEVATED_UNVERIFIED", "UNKNOWN"}
VALID_LABELS = {"NECESSARY", "REDUNDANT", "UNCERTAIN"}


def evaluate_cases(cases: list[Mapping[str, Any]]) -> dict[str, Any]:
    ids: set[str] = set()
    records = []
    errors = []
    for index, case in enumerate(cases):
        cid = str(case.get("case_id") or "")
        match = str(case.get("match_id") or "")
        label = str(case.get("human_label") or "UNCERTAIN").upper()
        risk = str(case.get("risk_level") or "UNKNOWN").upper()
        if not cid or cid in ids or not match or label not in VALID_LABELS or risk not in VALID_RISKS:
            errors.append({"index": index, "reason": "invalid_or_duplicate_case"})
            continue
        ids.add(cid)
        records.append({"case_id": cid, "match_id": match, "label": label,
                        "risk": risk, "is_high": risk == "HIGH_UNVERIFIED"})
    verified = [r for r in records if r["label"] in {"NECESSARY", "REDUNDANT"}]
    positive = [r for r in verified if r["label"] == "NECESSARY"]
    negative = [r for r in verified if r["label"] == "REDUNDANT"]
    tp = sum(r["is_high"] for r in positive)
    fn = len(positive) - tp
    fp = sum(r["is_high"] for r in negative)
    tn = len(negative) - fp
    matches = sorted({r["match_id"] for r in records})
    return {
        "schema": "v3a_phase10f_sealed_case_evaluation_v1",
        "n_cases": len(records), "n_matches": len(matches),
        "matches": matches, "invalid_cases": errors,
        "human_labeled_necessary": len(positive),
        "human_labeled_redundant": len(negative),
        "uncertain_excluded": len(records) - len(verified),
        "high_risk_confusion": {"TP": tp, "FN": fn, "FP": fp, "TN": tn},
        "necessary_recall": tp / len(positive) if positive else None,
        "redundant_false_alarm_rate": fp / len(negative) if negative else None,
        "risk_distribution": dict(Counter(r["risk"] for r in records)),
        "conclusion": (
            "DESCRIPTIVE_ONLY_NO_GENERALIZATION_CLAIM"
            if len(matches) >= 2 and positive and negative and not errors
            else "INSUFFICIENT_BALANCED_CROSSMATCH_EVIDENCE"
        ),
        "limitations": [
            "Role-based risk is not video semantic understanding.",
            "Labels must be sealed before reviewing model risk outputs.",
            "One human label per case is development feedback, not G2 consensus.",
            "Do not treat synthetic examples or known A case as held-out evidence.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Read-only P10-F case evaluator")
    p.add_argument("--cases", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    raw = json.loads(args.cases.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("cases"), list):
        p.error("cases JSON must contain a cases list")
    report = evaluate_cases(raw["cases"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(report["conclusion"])
    return 2 if report["invalid_cases"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
