"""Predicted Strip Chain Adapter — 8.31 causal_chain6 → V2 standard strips.

NEVER reads causal.json / strip_gold / human causal labels.
prediction_source is always causal_chain6_predicted; verification_status starts unverified.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple


class StripAdapterError(ValueError):
    pass


def _sec_from_ms(ms: Any) -> Optional[float]:
    if ms is None:
        return None
    return float(ms) / 1000.0


def load_upstream_strip_json(path: Path) -> Dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise StripAdapterError(f"missing strip.json: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise StripAdapterError("strip.json must be an object")
    for bad in ("causal_chains", "strip_gold", "gold_chains", "story_graph"):
        if bad in raw:
            raise StripAdapterError(f"refusing strip payload with forbidden key '{bad}'")
    chains = raw.get("chains") or raw.get("clips") or []
    if not isinstance(chains, list):
        raise StripAdapterError("strip.json needs chains[] or clips[]")
    return raw


def _event_id_set_from_events_json(events_path: Optional[Path]) -> Set[str]:
    if not events_path or not Path(events_path).is_file():
        return set()
    data = json.loads(Path(events_path).read_text(encoding="utf-8"))
    return {str(e.get("event_id")) for e in (data.get("events") or []) if e.get("event_id")}


def sanitize_predicted_chain(
    raw: Dict[str, Any],
    *,
    match_id: str,
    index: int,
    known_event_ids: Optional[Set[str]] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """Project one upstream clip/chain → V2 strip record + diagnostics."""
    diags: List[str] = []
    known_event_ids = known_event_ids or set()
    t0_ms = raw.get("t0_ms")
    t1_ms = raw.get("t1_ms")
    if t0_ms is None or t1_ms is None:
        diags.append("missing_t0_or_t1_ms")
        return {}, diags
    t0_sec = _sec_from_ms(t0_ms)
    t1_sec = _sec_from_ms(t1_ms)
    assert t0_sec is not None and t1_sec is not None
    if t1_sec < t0_sec:
        diags.append("time_order_inverted")
        t0_sec, t1_sec = t1_sec, t0_sec
        t0_ms, t1_ms = t1_ms, t0_ms

    clip_id = str(raw.get("clip_id") or raw.get("proposal_id") or f"clip{index:02d}")
    tid = str(
        raw.get("pred_chain_template_id")
        or raw.get("template_id")
        or raw.get("chain_template_id")
        or ""
    )
    label = str(raw.get("pred_chain_label_zh") or raw.get("predicted_label") or "")
    category = str(raw.get("chain_category") or raw.get("predicted_category") or "")

    evs = raw.get("events") if isinstance(raw.get("events"), list) else []
    source_ids: List[str] = []
    if raw.get("event_ids"):
        source_ids = [str(x) for x in raw["event_ids"]]
    else:
        source_ids = [str(e.get("event_id")) for e in evs if e.get("event_id") is not None]

    missing_ids = [eid for eid in source_ids if known_event_ids and eid not in known_event_ids]
    if missing_ids:
        diags.append(f"event_ids_not_in_events_json:{len(missing_ids)}")

    seq = []
    for e in evs:
        seq.append(
            {
                "event_id": e.get("event_id"),
                "type": e.get("type") or e.get("event_type"),
                "t_ms": e.get("t_ms"),
                "t0_ms": e.get("t0_ms"),
                "t1_ms": e.get("t1_ms"),
                "mapping_status": (
                    "exact"
                    if (not known_event_ids or str(e.get("event_id")) in known_event_ids)
                    else "unconfirmed"
                ),
            }
        )

    conf = None
    conf_src = None
    for ck in ("prob_top1", "confidence", "prob", "score"):
        if raw.get(ck) is not None:
            conf = float(raw[ck])
            conf_src = ck
            break
    margin = raw.get("margin")
    if margin is not None:
        try:
            margin = float(margin)
        except (TypeError, ValueError):
            margin = None

    if not category and not tid:
        diags.append("missing_category_and_template")

    out = {
        "schema": "v2_predicted_strip_chain_v1",
        "strip_chain_id": f"strip_{clip_id}",
        "clip_id": clip_id,
        "proposal_id": raw.get("proposal_id"),
        "match_id": match_id,
        "t0_ms": int(t0_ms),
        "t1_ms": int(t1_ms),
        "t0_sec": round(t0_sec, 3),
        "t1_sec": round(t1_sec, 3),
        "predicted_category": category or None,
        "predicted_template_id": tid or None,
        "predicted_label": label or None,
        "source_event_ids": source_ids,
        "event_sequence": seq,
        "first_event": raw.get("first_event") or (seq[0].get("type") if seq else None),
        "last_event": raw.get("last_event") or (seq[-1].get("type") if seq else None),
        "confidence": conf,
        "confidence_field": conf_src,
        "margin": margin,
        "prediction_source": "causal_chain6_predicted",
        "verification_status": "unverified",
        "upstream_source": raw.get("source"),
        "diagnostics": diags,
        "render_ready": False,
    }
    return out, diags


def adapt_strip_bundle(
    strip_path: Path,
    *,
    events_path: Optional[Path] = None,
    match_id: Optional[str] = None,
) -> Dict[str, Any]:
    raw = load_upstream_strip_json(Path(strip_path))
    mid = match_id or str(raw.get("match_id") or "")
    known = _event_id_set_from_events_json(events_path)
    chains_in = raw.get("chains") or raw.get("clips") or []
    adapted: List[Dict[str, Any]] = []
    all_diags: List[Dict[str, Any]] = []
    dropped = 0
    for i, c in enumerate(chains_in):
        if not isinstance(c, dict):
            dropped += 1
            continue
        row, diags = sanitize_predicted_chain(c, match_id=mid, index=i, known_event_ids=known)
        if not row:
            dropped += 1
            all_diags.append({"index": i, "diagnostics": diags})
            continue
        adapted.append(row)
        if diags:
            all_diags.append({"strip_chain_id": row["strip_chain_id"], "diagnostics": diags})

    # duplicate / overlap diagnostics (do not silent-merge)
    overlaps = []
    for i, a in enumerate(adapted):
        for b in adapted[i + 1 :]:
            lo = max(a["t0_sec"], b["t0_sec"])
            hi = min(a["t1_sec"], b["t1_sec"])
            if hi > lo and (hi - lo) / max(1e-6, min(a["t1_sec"] - a["t0_sec"], b["t1_sec"] - b["t0_sec"])) > 0.5:
                overlaps.append(
                    {
                        "a": a["strip_chain_id"],
                        "b": b["strip_chain_id"],
                        "overlap_sec": round(hi - lo, 3),
                    }
                )

    cat_counts: Dict[str, int] = {}
    for c in adapted:
        k = str(c.get("predicted_category") or "unknown")
        cat_counts[k] = cat_counts.get(k, 0) + 1

    return {
        "schema": "v2_predicted_strip_bundle_v1",
        "match_id": mid,
        "prediction_source": "causal_chain6_predicted",
        "upstream_strip_path": str(strip_path),
        "events_path": str(events_path) if events_path else None,
        "n_upstream": len(chains_in),
        "n_adapted": len(adapted),
        "n_dropped": dropped,
        "category_counts": cat_counts,
        "overlap_diagnostics": overlaps,
        "chain_diagnostics": all_diags,
        "forbidden_as_model_input": [
            "causal.json",
            "strip_gold.json",
            "human causal labels",
            "V1 story_graph roles",
        ],
        "chains": adapted,
        "render_ready": False,
        "note": (
            "Predicted strips are unverified hypotheses. "
            "Category/template ≠ proven live goal action."
        ),
    }


def planner_strip_digest(bundle: Dict[str, Any], *, max_chains: int = 40) -> Dict[str, Any]:
    """Compact digest for DeepSeek — no gold roles."""
    chains = list(bundle.get("chains") or [])
    # Prefer outcome/danger/correction, then by confidence
    def key(c: Dict[str, Any]) -> tuple:
        cat = str(c.get("predicted_category") or "")
        pri = 0 if cat in ("outcome", "danger", "correction") else 1
        conf = float(c.get("confidence") or 0.0)
        return (pri, -conf, float(c.get("t0_sec") or 0))

    ranked = sorted(chains, key=key)
    picked = ranked[:max_chains]
    picked.sort(key=lambda c: float(c.get("t0_sec") or 0))
    return {
        "match_id": bundle.get("match_id"),
        "prediction_source": bundle.get("prediction_source"),
        "n_chains_total": bundle.get("n_adapted"),
        "category_counts": bundle.get("category_counts"),
        "rules": [
            "Strips are algorithm predictions, not verified video actions",
            "Do not treat predicted_category=goal/outcome as confirmed goal clip",
            "Global narrative links ≠ local causal edges inside a strip",
            "Score-order of goals is not sufficient for inter-chain causal",
        ],
        "chains": [
            {
                "strip_chain_id": c["strip_chain_id"],
                "t0_sec": c["t0_sec"],
                "t1_sec": c["t1_sec"],
                "predicted_category": c.get("predicted_category"),
                "predicted_template_id": c.get("predicted_template_id"),
                "predicted_label": c.get("predicted_label"),
                "confidence": c.get("confidence"),
                "margin": c.get("margin"),
                "source_event_ids": c.get("source_event_ids"),
                "first_event": c.get("first_event"),
                "last_event": c.get("last_event"),
                "verification_status": c.get("verification_status"),
            }
            for c in picked
        ],
    }


def offline_key_goal_coverage(
    bundle: Dict[str, Any],
    *,
    weak_goal_centers_sec: Sequence[float],
    pad_sec: float = 90.0,
) -> Dict[str, Any]:
    """Offline-only coverage check vs weak time centers — NOT fed to the agent."""
    rows = []
    for gc in weak_goal_centers_sec:
        near = []
        for c in bundle.get("chains") or []:
            mid = 0.5 * (float(c["t0_sec"]) + float(c["t1_sec"]))
            if abs(mid - float(gc)) <= pad_sec:
                near.append(
                    {
                        "strip_chain_id": c["strip_chain_id"],
                        "predicted_category": c.get("predicted_category"),
                        "predicted_label": c.get("predicted_label"),
                        "center_sec": round(mid, 3),
                        "delta_sec": round(mid - float(gc), 3),
                    }
                )
        rows.append(
            {
                "goal_center_sec": gc,
                "n_nearby_strips": len(near),
                "nearby": near,
                "has_outcome_or_goalish": any(
                    (x.get("predicted_category") in ("outcome",))
                    or ("goal" in str(x.get("predicted_label") or "").lower())
                    or ("进球" in str(x.get("predicted_label") or ""))
                    for x in near
                ),
            }
        )
    return {
        "schema": "v2_strip_goal_coverage_offline_v1",
        "pad_sec": pad_sec,
        "rows": rows,
        "note": "Offline diagnostic only; weak centers never enter agent prompts",
    }
