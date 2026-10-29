"""Build round2_comparison.json from fixed/rule/agent run directories."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


def _load(p: Path) -> Optional[Dict[str, Any]]:
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def summarize_run(run_dir: Path) -> Dict[str, Any]:
    run_dir = Path(run_dir)
    cli = _load(run_dir / "cli_report.json") or {}
    disc = _load(run_dir / "story_discovery.json") or {}
    evid = _load(run_dir / "story_evidence.json") or {}
    auto = _load(run_dir / "autonomous_search_trace.json") or {}
    rel = _load(run_dir / "relation_verification.json") or {}
    ale = _load(run_dir / "action_localization_eval.json") or {}
    weak = ale.get("weak_reference_goals") or {}
    strict_g = ale.get("strict_action_gold") or {}
    api = cli.get("api_stats") or ( _load(run_dir / "agent_trace.json") or {} ).get("api_stats") or {}
    return {
        "run_dir": str(run_dir),
        "mode": cli.get("planner_mode") or disc.get("mode"),
        "discovery_status": disc.get("discovery_status") or cli.get("discovery_status"),
        "n_localized": disc.get("n_localized") or cli.get("n_localized"),
        "grade_counts": evid.get("grade_counts") or cli.get("grade_counts"),
        "strict_action_gold_n": strict_g.get("n_refs"),
        "strict_action_gold_recall": strict_g.get("strict_localization_recall"),
        "weak_ref_strict_recall": weak.get("strict_localization_recall"),
        "weak_ref_loose_recall": weak.get("loose_candidate_recall"),
        "weak_ref_rows": [
            {
                "role": r.get("role"),
                "center_error_sec": r.get("center_error_sec"),
                "iou": r.get("iou"),
                "matched_strict": r.get("matched_strict"),
                "matched_loose": r.get("matched_loose"),
                "pred_window": r.get("pred_window"),
                "completeness": r.get("action_completeness_audit"),
            }
            for r in (weak.get("rows") or [])
        ],
        "n_llm_mid_loop": auto.get("n_llm_mid_loop"),
        "n_rule_baseline": auto.get("n_rule_baseline"),
        "relation_n_accepted": rel.get("n_accepted"),
        "relation_n_downgraded": rel.get("n_downgraded"),
        "relation_n_rejected": rel.get("n_rejected"),
        "elapsed_sec": cli.get("elapsed_sec")
        or (_load(run_dir / "agent_trace.json") or {}).get("elapsed_sec"),
        "frames_used": cli.get("frames_used"),
        "est_cost_usd_real": api.get("est_cost_usd_real"),
        "real_ok": api.get("real_ok"),
        "render_ready": False,
    }


def build_comparison(
    *,
    fixed_dir: Optional[Path],
    rule_dir: Optional[Path],
    agent_dir: Optional[Path],
    audit_dir: Optional[Path],
    out_path: Path,
) -> Dict[str, Any]:
    modes = {}
    if fixed_dir:
        modes["event_fixed"] = summarize_run(fixed_dir)
    if rule_dir:
        modes["event_rule"] = summarize_run(rule_dir)
    if agent_dir:
        modes["event_agent"] = summarize_run(agent_dir)

    agent = modes.get("event_agent") or {}
    rule = modes.get("event_rule") or {}
    fixed = modes.get("event_fixed") or {}

    def _f(x):
        return x if isinstance(x, (int, float)) and x is not None else None

    agent_gain = {
        "vs_rule_weak_strict_delta": (
            None
            if _f(agent.get("weak_ref_strict_recall")) is None
            or _f(rule.get("weak_ref_strict_recall")) is None
            else round(
                float(agent["weak_ref_strict_recall"]) - float(rule["weak_ref_strict_recall"]),
                4,
            )
        ),
        "vs_rule_weak_loose_delta": (
            None
            if _f(agent.get("weak_ref_loose_recall")) is None
            or _f(rule.get("weak_ref_loose_recall")) is None
            else round(
                float(agent["weak_ref_loose_recall"]) - float(rule["weak_ref_loose_recall"]),
                4,
            )
        ),
        "vs_fixed_weak_strict_delta": (
            None
            if _f(agent.get("weak_ref_strict_recall")) is None
            or _f(fixed.get("weak_ref_strict_recall")) is None
            else round(
                float(agent["weak_ref_strict_recall"]) - float(fixed["weak_ref_strict_recall"]),
                4,
            )
        ),
        "autonomy_llm_mid_loop": agent.get("n_llm_mid_loop"),
        "cost_usd_agent": agent.get("est_cost_usd_real"),
        "cost_usd_rule": rule.get("est_cost_usd_real"),
        "verdict_notes": [],
    }
    if agent_gain["autonomy_llm_mid_loop"]:
        agent_gain["verdict_notes"].append(
            "Event-Agent issued mid-loop DeepSeek tool decisions (not terminal-only)."
        )
    if (agent_gain["vs_rule_weak_strict_delta"] or 0) > 0:
        agent_gain["verdict_notes"].append(
            "Event-Agent improved weak-ref strict localization vs Event-Rule."
        )
    elif agent_gain["vs_rule_weak_strict_delta"] == 0:
        agent_gain["verdict_notes"].append(
            "No weak-ref strict recall gain vs Event-Rule on this match."
        )
    elif agent_gain["vs_rule_weak_strict_delta"] is not None:
        agent_gain["verdict_notes"].append(
            "Event-Agent did NOT beat Event-Rule on weak-ref strict recall."
        )

    out = {
        "schema": "v2_event_guided_round2_comparison_v1",
        "r1_audit_dir": str(audit_dir) if audit_dir else None,
        "modes": modes,
        "agent_independent_gain": agent_gain,
        "policy": {
            "no_pm90s_action_recall": True,
            "strict_gold_excludes_weak_refs": True,
            "render_ready": False,
        },
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--fixed-dir", type=Path)
    p.add_argument("--rule-dir", type=Path)
    p.add_argument("--agent-dir", type=Path)
    p.add_argument("--audit-dir", type=Path)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    build_comparison(
        fixed_dir=args.fixed_dir,
        rule_dir=args.rule_dir,
        agent_dir=args.agent_dir,
        audit_dir=args.audit_dir,
        out_path=args.out,
    )
    print(f"wrote {args.out}")
