"""Offline-only eval for Event-Guided runs.

Gold action windows and causal.json are NEVER fed to the agent.
They may be loaded here AFTER inference for metrics only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _overlap(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    lo = max(a[0], b[0])
    hi = min(a[1], b[1])
    return max(0.0, hi - lo)


def _iou(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    inter = _overlap(a, b)
    if inter <= 0:
        return 0.0
    union = (a[1] - a[0]) + (b[1] - b[0]) - inter
    return inter / union if union > 0 else 0.0


def load_action_gold_from_story_graph(path: Path) -> List[Dict[str, Any]]:
    """Extract action media windows from frozen story_graph (eval only)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    gold = []
    for n in data.get("nodes") or []:
        role = n.get("role") or ""
        if "goal_action" not in str(role):
            continue
        mi, mo = n.get("media_in"), n.get("media_out")
        if mi is None or mo is None:
            continue
        gold.append(
            {
                "id": n.get("id"),
                "role": role,
                "media_start_sec": float(mi),
                "media_end_sec": float(mo),
                "shot_kind": n.get("shot_kind"),
            }
        )
    return gold


def load_causal_chains_offline(path: Path) -> Dict[str, Any]:
    """Load causal.json strictly for post-hoc comparison."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        "schema": "offline_causal_eval_only",
        "n_chains": len(data.get("causal_chains") or []),
        "chain_ids": [
            c.get("chain_id") or c.get("id") for c in (data.get("causal_chains") or [])
        ],
        "note": "NOT used as model input",
    }


def eval_action_windows(
    *,
    verified: Sequence[Dict[str, Any]],
    gold: Sequence[Dict[str, Any]],
    iou_thresh: float = 0.1,
    center_pad_sec: float = 90.0,
) -> Dict[str, Any]:
    """Match verification windows to gold actions (IoU or center proximity).

    center_pad defaults to 90s because Score_Recognition anchors often lag live goals.
    """
    preds = []
    for v in verified:
        s, e = v.get("media_start_sec"), v.get("media_end_sec")
        if s is None or e is None:
            continue
        grade = (v.get("grade") or {}).get("grade") if isinstance(v.get("grade"), dict) else v.get("grade")
        preds.append(
            {
                "task_id": v.get("task_id"),
                "window": (float(s), float(e)),
                "grade": grade,
            }
        )

    hits = []
    missed = []
    for g in gold:
        gw = (float(g["media_start_sec"]), float(g["media_end_sec"]))
        gmid = 0.5 * (gw[0] + gw[1])
        best = None
        best_key = None  # (dist, -iou) lower better
        for p in preds:
            iou = _iou(p["window"], gw)
            pmid = 0.5 * (p["window"][0] + p["window"][1])
            dist = abs(pmid - gmid)
            prox = dist <= center_pad_sec
            key = (dist, -iou)
            if best_key is None or key < best_key:
                best_key = key
                best = (p, iou, prox, dist)
        matched = bool(best and (best[1] >= iou_thresh or best[2]))
        row = {
            "gold_id": g.get("id"),
            "gold_role": g.get("role"),
            "gold_window": list(gw),
            "matched": matched,
            "best_iou": best[1] if best else 0.0,
            "center_distance_sec": best[3] if best else None,
            "center_within_pad": best[2] if best else False,
            "pred_task_id": best[0]["task_id"] if best else None,
            "pred_window": list(best[0]["window"]) if best else None,
            "pred_grade": best[0]["grade"] if best else None,
        }
        (hits if matched else missed).append(row)

    recall = len(hits) / len(gold) if gold else None
    return {
        "schema": "v2_event_guided_action_eval_v1",
        "n_gold": len(gold),
        "n_pred_windows": len(preds),
        "n_hits": len(hits),
        "recall": recall,
        "iou_thresh": iou_thresh,
        "center_pad_sec": center_pad_sec,
        "hits": hits,
        "missed": missed,
        "note": "offline only; gold never entered agent loop",
    }


def eval_inferred_relations_vs_causal(
    *,
    relations: Sequence[Dict[str, Any]],
    causal_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Lightweight structural report — does not score 'correct causality' automatically."""
    kinds = {}
    for r in relations:
        k = str(r.get("kind") or "unknown")
        kinds[k] = kinds.get(k, 0) + 1
    causal_meta = None
    if causal_path and Path(causal_path).is_file():
        causal_meta = load_causal_chains_offline(Path(causal_path))
    return {
        "schema": "v2_event_guided_relation_eval_v1",
        "n_inferred_relations": len(relations),
        "kind_counts": kinds,
        "offline_causal_meta": causal_meta,
        "quality_note": (
            "Automatic causal correctness is not claimed; use human review. "
            "causal.json meta is count-only for offline context."
        ),
    }
