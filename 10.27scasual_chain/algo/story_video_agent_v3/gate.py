"""V3 evidence handoff: targeted V2 strict gate, no automatic final rendering.

Takes a V3 structure run and a role-indexed evidence pack. Never imports or
modifies V1/V2 run files. Neither human QC nor automated verification alone
grants final delivery; the render gate remains closed.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from story_video_agent.v2_video_evidence_gate import (
    AUTOMATED, HUMAN_REVIEWED, evaluate_video_verification_claim,
)
from .pipeline import CRITICAL, V3InputError, dump


def _gate_goal(goal: Dict[str, Any], expected: Dict[str, str],
               *, allow_human: bool, duration: Optional[float]) -> Dict[str, Any]:
    if goal.get("live_or_replay") != "live":
        return {"ok": False, "reason": "not_unambiguous_first_live", "level": "unresolved"}
    # Additional fail-closed constraints: V2 checks media/semantic log,
    # V3 must also require affirmative video observations before calling V2.
    if not all(goal.get(k) is True for k in
               ("observed_shot", "observed_net", "first_live_visual_ok",
                "attacking_team_match", "claims_continuous_live")):
        return {"ok": False, "reason": "incomplete_shot_net_team_first_live", "level": "unresolved"}
    if goal.get("net_seen_only_in_replay") or goal.get("wrong_team_shot"):
        return {"ok": False, "reason": "replay_or_wrong_attacker", "level": "unresolved"}
    if goal.get("scoreboard_only") or goal.get("cross_window_stitch"):
        return {"ok": False, "reason": "scoreboard_or_cross_window_stitch", "level": "unresolved"}
    if goal.get("semantic_verification_class") not in (
        AUTOMATED, HUMAN_REVIEWED if allow_human else AUTOMATED
    ):
        return {"ok": False, "reason": "unsupported_or_missing_semantic_class", "level": "unresolved"}
    result = evaluate_video_verification_claim(
        goal=goal, expected_identity=expected, video_duration_sec=duration,
        allow_human_reviewed=allow_human,
    )
    return {**result, "render_ready": False}


def review_evidence(
    *, v3_run_dir: Path, evidence_pack: Path, output_dir: Path,
    allow_human: bool = False, duration: Optional[float] = None
) -> Dict[str, Any]:
    run = Path(v3_run_dir).resolve()
    dest = Path(output_dir).resolve()
    if "v3" not in {p.lower() for p in dest.parts}:
        raise V3InputError("Verification output must have v3/ path component")
    if dest == run or dest in run.parents:
        raise V3InputError("Do not overwrite V3 structure dry-run root")
    if dest.exists() and any(dest.iterdir()):
        raise V3InputError("Refusing to overwrite existing verification artifacts")
    provenance = json.loads((run / "provenance.json").read_text(encoding="utf-8"))
    expected = {
        "match_id": provenance["match_id"],
        "video_sha256": provenance["input_hashes"]["video_sha256"],
        "events_sha256": provenance["input_hashes"]["events_sha256"],
        "strip_provenance": provenance["input_hashes"]["strips_sha256"],
    }
    payload = json.loads(evidence_pack.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("goals"), list):
        raise V3InputError("Evidence pack needs goals[]")
    old_edl = json.loads((run / "candidate_edl.json").read_text(encoding="utf-8"))
    roles: Dict[str, Dict[str, Any]] = {}
    duplicated = set()
    for row in payload["goals"]:
        role = row.get("role")
        if role not in CRITICAL:
            raise V3InputError(f"Unknown critical goal role: {role}")
        if role in roles:
            duplicated.add(role)
        roles[role] = row
    if duplicated:
        raise V3InputError(f"Duplicate evidence roles: {sorted(duplicated)}")
    decisions = {}
    out_edl = copy.deepcopy(old_edl)
    for role in CRITICAL:
        g = roles.get(role)
        decision = (_gate_goal(g, expected, allow_human=allow_human, duration=duration)
                    if g else {"ok": False, "level": "unresolved",
                               "reason": "missing_evidence_pack_role"})
        decisions[role] = decision
        if decision.get("ok") and decision.get("level") == "video_verified":
            # Only replace its own dedicated placeholder. No unverified goal
            # clips sneak through V1's guessed/scoreboard windows.
            for row in out_edl:
                if row.get("critical_goal_role") == role:
                    row.update({
                        "media_in": float(g["media_in"]),
                        "media_out": float(g["media_out"]),
                        "goal_action_sec": float(g["net_sec"]),
                        "shot_sec": float(g["shot_sec"]),
                        "net_sec": float(g["net_sec"]),
                        "time_status": "video_first_live_evidence",
                        "shot_kind": "live",
                        "verification_level": "video_verified",
                        "verification_status": ("human_video_reviewed" if
                            g.get("semantic_verification_class") == HUMAN_REVIEWED else
                            "automated_video_verified"),
                        "goal_action_complete": True,
                        "render_eligibility": "candidate_review_only",
                        "include_in_cut": False,
                        "render_ready": False,
                    })
    n_pass = sum(1 for x in decisions.values()
                 if x.get("ok") and x.get("level") == "video_verified")
    report = {
        "schema": "v3_critical_video_gate_v1",
        "match_id": expected["match_id"],
        "n_critical": len(CRITICAL),
        "n_video_verified": n_pass,
        "all_critical_video_verified": n_pass == len(CRITICAL),
        "decisions": decisions,
        "status": "candidate_for_visual_qc" if n_pass == len(CRITICAL) else "blocked_missing_goal_evidence",
        "candidate_edl_ready_for_render_review": n_pass == len(CRITICAL),
        "visual_qc_pass": False,
        "render_ready": False,
        "note": "V2 gate reused; requires separate visual QC and explicit rendering decision.",
    }
    dest.mkdir(parents=True, exist_ok=True)
    dump(dest / "verification_report.json", report)
    dump(dest / "verified_candidate_edl.json", out_edl)
    return report


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="V3 targeted critical goal V2 evidence gate")
    p.add_argument("--v3-run-dir", type=Path, required=True)
    p.add_argument("--evidence-pack", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--allow-human-reviewed", action="store_true")
    p.add_argument("--video-duration-sec", type=float)
    args = p.parse_args(argv)
    try:
        report = review_evidence(
            v3_run_dir=args.v3_run_dir, evidence_pack=args.evidence_pack,
            output_dir=args.out_dir, allow_human=args.allow_human_reviewed,
            duration=args.video_duration_sec,
        )
    except (OSError, ValueError, KeyError) as exc:
        p.error(str(exc))
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["all_critical_video_verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
