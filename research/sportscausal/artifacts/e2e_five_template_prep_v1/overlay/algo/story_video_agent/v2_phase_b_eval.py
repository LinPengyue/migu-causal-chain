"""Offline Phase B eval against frozen labels (NOT used during discovery)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


def load_croatia_t01_nodes(story_graph_path: Path) -> List[Dict[str, Any]]:
    sg = json.loads(story_graph_path.read_text(encoding="utf-8"))
    want = {
        "opponent_opening_goal_action": "deficit",
        "equalizer_goal_action": "equalizer",
        "go_ahead_goal_action": "go_ahead",
    }
    nodes = []
    for n in sg.get("nodes") or []:
        role = n.get("role")
        if role in want and n.get("media_in") is not None:
            nodes.append(
                {
                    "role": want[role],
                    "source_role": role,
                    "media_in": float(n["media_in"]),
                    "media_out": float(n.get("media_out") or n["media_in"]),
                }
            )
    return nodes


def _windows_from_run(evidence: Dict[str, Any]) -> List[Dict[str, Any]]:
    wins = []
    for o in evidence.get("video_evidence") or []:
        if o.get("media_start_sec") is None:
            continue
        wins.append(
            {
                "start": float(o["media_start_sec"]),
                "end": float(o["media_end_sec"]),
                "tool": o.get("tool"),
                "status": o.get("status"),
                "sampled": o.get("sampled_media_times") or [],
            }
        )
    return wins


def _hit(label: Dict[str, Any], windows: Sequence[Dict[str, Any]], *, tol_sec: float) -> Optional[Dict[str, Any]]:
    """A hit if any observed window overlaps label±tol OR any sampled time within tol of label center."""
    lo = label["media_in"] - tol_sec
    hi = label["media_out"] + tol_sec
    center = 0.5 * (label["media_in"] + label["media_out"])
    for w in windows:
        if w.get("status") == "failed":
            continue
        if not (w["end"] < lo or w["start"] > hi):
            return {"type": "window_overlap", "window": w}
        for t in w.get("sampled") or []:
            if abs(float(t) - center) <= tol_sec:
                return {"type": "sample_near_center", "t": t, "window": w}
    return None


def evaluate_run(
    *,
    run_dir: Path,
    labels: Sequence[Dict[str, Any]],
    media_offset_sec: float = 0.0,
    tol_sec: float = 90.0,
) -> Dict[str, Any]:
    """labels use absolute full-match media times; run may be a subclip with media_offset_sec."""
    evidence = json.loads((run_dir / "story_evidence.json").read_text(encoding="utf-8"))
    discovery = json.loads((run_dir / "story_discovery.json").read_text(encoding="utf-8"))
    trace = json.loads((run_dir / "agent_trace.json").read_text(encoding="utf-8"))
    coverage = json.loads((run_dir / "search_coverage.json").read_text(encoding="utf-8"))

    # Map run-local times → absolute
    windows = []
    for w in _windows_from_run(evidence):
        windows.append(
            {
                **w,
                "start": w["start"] + media_offset_sec,
                "end": w["end"] + media_offset_sec,
                "sampled": [float(t) + media_offset_sec for t in (w.get("sampled") or [])],
            }
        )

    # Labels in clip range only
    clip_lo = media_offset_sec
    # infer clip duration from evidence duration or coverage
    dur = float(trace.get("duration_sec") or coverage.get("duration_sec") or 0)
    clip_hi = media_offset_sec + dur
    labels_in_range = [
        L for L in labels if not (L["media_out"] < clip_lo or L["media_in"] > clip_hi)
    ]

    per = []
    hits = 0
    for L in labels_in_range:
        h = _hit(L, windows, tol_sec=tol_sec)
        per.append({"label": L, "hit": bool(h), "detail": h})
        if h:
            hits += 1

    api = trace.get("api_stats") or {}
    report = {
        "schema": "v2_phase_b_offline_eval_v1",
        "run_dir": str(run_dir),
        "media_offset_sec": media_offset_sec,
        "tol_sec": tol_sec,
        "discovery_status": discovery.get("discovery_status"),
        "labels_in_range": labels_in_range,
        "n_labels_in_range": len(labels_in_range),
        "n_hits": hits,
        "recall_at_tol": (hits / len(labels_in_range)) if labels_in_range else None,
        "per_label": per,
        "frames_used": trace.get("frames_used"),
        "elapsed_sec": trace.get("elapsed_sec"),
        "api": {
            "real_ok": api.get("real_ok"),
            "real_failures": api.get("real_failures"),
            "total_tokens": api.get("total_tokens"),
            "est_cost_usd_real": api.get("est_cost_usd_real"),
            "cost_disclaimer": api.get("cost_disclaimer"),
        },
        "coverage_fraction_observed": coverage.get("fraction_partitions_with_observation"),
        "evidence_status_counts": evidence.get("evidence_status_counts"),
        "n_evidence_items_deduped": len(evidence.get("evidence_items") or []),
        "planner_modes": trace.get("planner_mode_log"),
        "notes": [
            "Offline labels never fed to the agent",
            "Hit = window overlap or sample near label center within tol",
            "Does not score live/replay correctness unless notes mention it",
        ],
        "render_ready": False,
    }
    return report


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Offline Phase B eval (post-hoc labels only)")
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument(
        "--story-graph",
        type=Path,
        default=Path(
            "/tmp/migu-va2c/10.27scasual_chain/reports/phase5/croatia/story_graph.json"
        ),
    )
    p.add_argument("--media-offset-sec", type=float, default=0.0)
    p.add_argument("--tol-sec", type=float, default=90.0)
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args(argv)
    labels = load_croatia_t01_nodes(args.story_graph)
    report = evaluate_run(
        run_dir=args.run_dir,
        labels=labels,
        media_offset_sec=args.media_offset_sec,
        tol_sec=args.tol_sec,
    )
    out = args.out or (args.run_dir / "offline_eval.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
