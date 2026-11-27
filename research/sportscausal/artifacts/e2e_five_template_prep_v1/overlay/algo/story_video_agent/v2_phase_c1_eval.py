"""Phase C-1 localization eval — NOT window-overlap-as-success."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


def load_gold_actions(story_graph: Path) -> List[Dict[str, Any]]:
    """Gold action intervals from V1 story_graph live goal nodes (offline only).

    Note: if a node is scoreboard-only, mark gold_kind accordingly — do not treat as
    reliable action gold without human confirm. Here we keep role metadata.
    """
    sg = json.loads(story_graph.read_text(encoding="utf-8"))
    want = {
        "opponent_opening_goal_action": "deficit_goal",
        "equalizer_goal_action": "equalizer_goal",
        "go_ahead_goal_action": "go_ahead_goal",
    }
    gold = []
    for n in sg.get("nodes") or []:
        role = n.get("role")
        if role not in want or n.get("media_in") is None:
            continue
        gold.append(
            {
                "role": want[role],
                "source_role": role,
                "media_in": float(n["media_in"]),
                "media_out": float(n.get("media_out") or n["media_in"]),
                "goal_action_complete": n.get("goal_action_complete"),
                "shot_kind": n.get("shot_kind"),
                "gold_reliability": (
                    "action_node"
                    if n.get("goal_action_complete") and n.get("shot_kind") == "live"
                    else "weak_or_non_action"
                ),
            }
        )
    return gold


def _best_event_for_role(events: Sequence[Dict[str, Any]], role: str) -> Optional[Dict[str, Any]]:
    cands = [e for e in events if e.get("narrative_role") == role or role in str(e.get("task_id"))]
    if not cands:
        return None
    # Prefer higher grades
    rank = {
        "action_corroborated": 4,
        "action_localized": 3,
        "goal_candidate": 2,
        "scoreboard_only": 1,
        "unresolved": 0,
    }
    return max(cands, key=lambda e: rank.get(str(e.get("localization_grade")), 0))


def evaluate_localization(
    *,
    run_dir: Path,
    gold: Sequence[Dict[str, Any]],
    media_offset_sec: float = 0.0,
    action_tol_sec: float = 8.0,
    candidate_tol_sec: float = 45.0,
) -> Dict[str, Any]:
    loc = json.loads((run_dir / "localized_events.json").read_text(encoding="utf-8"))
    tasks = json.loads((run_dir / "story_evidence_tasks.json").read_text(encoding="utf-8"))
    trace = json.loads((run_dir / "agent_trace.json").read_text(encoding="utf-8"))
    events = loc.get("events") or []

    # Map local → absolute
    abs_events = []
    for e in events:
        rw = e.get("refined_action_window") or {}
        if rw.get("start") is None:
            continue
        abs_events.append(
            {
                **e,
                "abs_start": float(rw["start"]) + media_offset_sec,
                "abs_end": float(rw["end"]) + media_offset_sec,
                "abs_center": 0.5 * (float(rw["start"]) + float(rw["end"])) + media_offset_sec,
            }
        )

    per = []
    action_hits = 0
    candidate_hits = 0
    n_reliable = 0
    for g in gold:
        reliable = g.get("gold_reliability") == "action_node"
        if reliable:
            n_reliable += 1
        g_center = 0.5 * (g["media_in"] + g["media_out"])
        best = _best_event_for_role(abs_events, g["role"])
        row: Dict[str, Any] = {"gold": g, "matched_event": None}
        if not best:
            row.update(action_hit=False, candidate_hit=False, center_error_sec=None, grade=None)
        else:
            err = abs(best["abs_center"] - g_center)
            grade = best.get("localization_grade")
            # Action hit: tight center error AND grade at least action_localized
            a_hit = err <= action_tol_sec and grade in ("action_localized", "action_corroborated")
            c_hit = err <= candidate_tol_sec  # coarse candidate recall
            row.update(
                matched_event={
                    "task_id": best.get("task_id"),
                    "grade": grade,
                    "abs_start": best["abs_start"],
                    "abs_end": best["abs_end"],
                    "center_error_sec": err,
                },
                action_hit=a_hit,
                candidate_hit=c_hit,
                center_error_sec=err,
                grade=grade,
            )
            if a_hit and reliable:
                action_hits += 1
            if c_hit:
                candidate_hits += 1
        per.append(row)

    grade_hist: Dict[str, int] = {}
    for e in events:
        g = str(e.get("localization_grade") or "none")
        grade_hist[g] = grade_hist.get(g, 0) + 1

    api = trace.get("api_stats") or {}
    return {
        "schema": "v2_localization_eval_v1",
        "run_dir": str(run_dir),
        "media_offset_sec": media_offset_sec,
        "action_tol_sec": action_tol_sec,
        "candidate_tol_sec": candidate_tol_sec,
        "n_gold": len(gold),
        "n_reliable_action_gold": n_reliable,
        "candidate_recall": (candidate_hits / len(gold)) if gold else None,
        "action_localization_recall_on_reliable_gold": (
            (action_hits / n_reliable) if n_reliable else None
        ),
        "grade_histogram": grade_hist,
        "task_counts": tasks.get("counts"),
        "per_gold": per,
        "api": {
            "real_ok": api.get("real_ok"),
            "real_failures": api.get("real_failures"),
            "total_tokens": api.get("total_tokens"),
            "est_cost_usd_real": api.get("est_cost_usd_real"),
            "cost_disclaimer": api.get("cost_disclaimer"),
        },
        "frames_used": trace.get("frames_used"),
        "elapsed_sec": trace.get("elapsed_sec"),
        "notes": [
            "candidate_recall uses center error <= candidate_tol (coarse)",
            "action_localization_recall requires grade action_localized|corroborated AND tight tol",
            "Large partition overlap is NOT counted as action success",
            "V1 scoreboard-only nodes marked weak_or_non_action",
        ],
        "render_ready": False,
    }


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument(
        "--story-graph",
        type=Path,
        default=Path("/tmp/migu-va2c/10.27scasual_chain/reports/phase5/croatia/story_graph.json"),
    )
    p.add_argument("--media-offset-sec", type=float, default=0.0)
    p.add_argument("--action-tol-sec", type=float, default=8.0)
    p.add_argument("--candidate-tol-sec", type=float, default=45.0)
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args(argv)
    gold = load_gold_actions(args.story_graph)
    report = evaluate_localization(
        run_dir=args.run_dir,
        gold=gold,
        media_offset_sec=args.media_offset_sec,
        action_tol_sec=args.action_tol_sec,
        candidate_tol_sec=args.candidate_tol_sec,
    )
    out = args.out or (args.run_dir / "localization_eval.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
