"""Offline P10-D experiment auditor: never interprets fixture as autonomy.

Read-only local JSON. No HTTP, no model calls, no BEST updates.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


def assess_run(root: Path) -> dict[str, Any]:
    audit_file = root / "story_e2e_audit.json"
    provenance_file = root / "02_round_01" / "phase10_exploratory" / "phase10d_provenance.json"
    trial_file = root / "02_round_01" / "phase10_exploratory" / "exploratory_trial.json"
    result: dict[str, Any] = {
        "schema": "v3a_phase10d_readonly_audit_v1",
        "autonomous_candidate_status": "UNVERIFIED",
        "human_story_quality": "UNVERIFIED",
        "release_authorized": False,
        "best_updated": False,
        "inputs_present": {},
        "reasons": [],
    }
    def read(path: Path) -> Mapping[str, Any] | None:
        result["inputs_present"][path.name] = path.is_file()
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, ValueError, UnicodeError):
            result["reasons"].append("invalid_json:" + path.name)
            return None

    audit = read(audit_file)
    provenance = read(provenance_file)
    trial = read(trial_file)
    if not audit or not provenance or not trial:
        result["reasons"].append("incomplete_experiment_evidence")
        return result
    result["http_attempts"] = provenance.get("http_attempts_so_far")
    result["estimated_cost_usd"] = provenance.get("est_cost_usd_so_far")
    result["candidate_status"] = trial.get("status")
    if provenance.get("fixture_used") or trial.get("source") == "FIXTURE":
        result["autonomous_candidate_status"] = "FIXTURE_ONLY"
        result["reasons"].append("fixture_is_not_autonomous_model_decision")
        return result
    if not (
        provenance.get("model_planner_called") is True
        and provenance.get("planner_ok") is True
        and provenance.get("planner_provider_mode") == "real"
        and provenance.get("real_model_proposal") is True
        and trial.get("source") == "REAL_LLM"
    ):
        result["autonomous_candidate_status"] = "NO_VERIFIED_REAL_PLANNER_PROPOSAL"
        result["reasons"].append("missing_model_provenance_or_planner_declined")
        return result
    if not isinstance(provenance.get("model_selected_target"), str) or not isinstance(
        provenance.get("model_selected_action"), str
    ):
        result["reasons"].append("missing_model_chosen_target_or_action")
        return result
    result["autonomous_candidate_status"] = (
        "MODEL_PROPOSED_AND_RENDERED"
        if trial.get("candidate_rendered") is True
        and trial.get("blind_pair_status") == "BLIND_PAIR_READY"
        and provenance.get("candidate_rendered") is True
        else "MODEL_PROPOSED_BUT_NOT_RENDERED"
    )
    result["reasons"].append("human_quality_requires_independent_blind_review")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline, read-only P10-D audit")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    result = assess_run(args.run_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(result["autonomous_candidate_status"])
    return 0 if result["autonomous_candidate_status"] != "UNVERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
