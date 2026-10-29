"""Re-run causal_chain6 strip on plain / enhanced events without touching production params.

Uses the in-repo AlgoStripAdapter (identical MD5 to standalone 8.31).
Does NOT read causal/strip_gold. Does NOT tune margin.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# TYPE_NORM subset — mirror 8.31 build_datasets.norm_type for Goal/Shot etc.
_TYPE_NORM = {
    "shot": "shot",
    "goal": "goal",
    "header_goal": "goal",
    "save": "keeper_save",
    "keeper_save": "keeper_save",
    "pass": "pass",
    "assist": "assist",
    "corner_kick": "corner",
    "corner": "corner",
    "free_kick": "free_kick",
    "penalty": "penalty",
    "throw_in": "throw_in",
    "dribble_past": "dribble_past",
    "dribble_breakthrough": "dribble_breakthrough",
    "ball_possession": "pass",
    "goal_line_clearance": "goal_line_clearance",
    "win_an_aerial_duel": "aerial_won",
    "defensive_action": "successful_tackle",
    "successful_tackle": "successful_tackle",
    "interception": "interception",
    "video_assistant_referee": "var",
    "var": "var",
    "foul_being_fouled": "foul",
    "foul": "foul",
    "red_card": "red_card",
    "yellow_card": "yellow_card",
    "substitution": "substitution",
    "players_enter_the_pitch": "player_entrance",
    "kick_off": "match_start",
    "aerial_won": "aerial_won",
    "cross": "cross",
    "header_shot": "header_shot",
    "lineup": "lineup",
    "full_time": "full_time",
    "receive_a_card": "receive_a_card",
    "射门": "shot",
    "进球": "goal",
    "扑救": "keeper_save",
    "传球": "pass",
    "角球": "corner",
    "任意球": "free_kick",
    "界外球": "throw_in",
    "开球": "match_start",
}


def norm_type(raw: Any) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    key = s.lower().replace(" ", "_")
    if key in _TYPE_NORM:
        return _TYPE_NORM[key]
    if s in _TYPE_NORM:
        return _TYPE_NORM[s]
    return key


def events_to_timeline(events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert delivery-style events → strip internal timeline (same rules as 8.31)."""
    out: List[Dict[str, Any]] = []
    for i, e in enumerate(events):
        media = e.get("media_time") or {}
        t_sec = media.get("event_time_sec")
        if t_sec is None:
            t_sec = media.get("start_time_sec")
        if t_sec is None:
            continue
        typ = norm_type(e.get("event_type") or e.get("event_type_zh") or e.get("comment_label"))
        if not typ:
            continue
        t_ms = int(float(t_sec) * 1000)
        t0 = media.get("start_time_sec")
        t1 = media.get("end_time_sec")
        out.append(
            {
                "event_id": e.get("event_id") or f"e{i:04d}",
                "type": typ,
                "t_ms": t_ms,
                "t0_ms": int(float(t0) * 1000) if t0 is not None else t_ms,
                "t1_ms": int(float(t1) * 1000) if t1 is not None else t_ms,
                "order": i,
                "source": e.get("source") or "original",
            }
        )
    out.sort(key=lambda x: x["t_ms"])
    return out


def _ensure_algo_paths(algo_root: Path) -> None:
    algo = str(algo_root / "algo")
    ev = str(algo_root / "eval")
    for p in (algo, ev):
        if p not in sys.path:
            sys.path.insert(0, p)


def run_strip_predict(
    *,
    timeline_events: Sequence[Dict[str, Any]],
    match_id: str,
    algo_root: Path,
    profile: str = "production",
    label: str = "strip",
) -> Dict[str, Any]:
    """Production rule-only AlgoStripAdapter.predict — no param overrides."""
    algo_root = Path(algo_root)
    _ensure_algo_paths(algo_root)
    from strip_adapter import AlgoStripAdapter  # type: ignore

    adapter = AlgoStripAdapter(profile_name=profile, use_llm=False, use_sliding_recall=True)
    preds = adapter.predict(list(timeline_events), match_id=match_id) if timeline_events else []
    for i, p in enumerate(preds):
        p["clip_id"] = f"clip{i:02d}"
    cats = Counter(str(p.get("chain_category") or "unknown") for p in preds)
    tids = Counter(str(p.get("template_id") or "") for p in preds)
    return {
        "schema": "v2_upstream_strip_json_v1",
        "match_id": match_id,
        "safe_id": match_id.replace(" ", "_"),
        "mode": f"reinfer_{label}",
        "profile": profile,
        "use_llm": False,
        "n_events": len(timeline_events),
        "n_chains": len(preds),
        "chains": preds,
        "category_counts": dict(cats),
        "template_counts": dict(tids),
        "adapter_config": adapter.config_snapshot(),
        "algo_root": str(algo_root),
        "forbidden_inputs": ["*_causal.json", "strip_gold.json"],
        "note": "production profile unchanged; no margin retuning",
    }


def chain_key(c: Dict[str, Any]) -> Tuple[int, int, str, str]:
    return (
        int(c.get("t0_ms") or 0),
        int(c.get("t1_ms") or 0),
        str(c.get("template_id") or c.get("pred_chain_template_id") or ""),
        str(c.get("chain_category") or ""),
    )


def compare_strip_ab(
    *,
    strip_a: Dict[str, Any],
    strip_b: Dict[str, Any],
    missing_candidates: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Compare original (A) vs enhanced (B) predictions."""
    a = strip_a.get("chains") or []
    b = strip_b.get("chains") or []
    ka = Counter(chain_key(c) for c in a)
    kb = Counter(chain_key(c) for c in b)
    only_a = list((ka - kb).elements())
    only_b = list((kb - ka).elements())
    outcome_a = [c for c in a if c.get("chain_category") == "outcome" or c.get("last_event") == "goal"]
    outcome_b = [c for c in b if c.get("chain_category") == "outcome" or c.get("last_event") == "goal"]

    # Per missing-candidate coverage on B
    per_cand = []
    for mg in missing_candidates or []:
        conf = mg.get("score_confirmation_time")
        if conf is None:
            continue
        conf_ms = float(conf) * 1000.0
        hits = []
        for c in outcome_b:
            t0, t1 = int(c.get("t0_ms") or 0), int(c.get("t1_ms") or 0)
            if t0 - 90_000 <= conf_ms <= t1 + 30_000 or abs(0.5 * (t0 + t1) - conf_ms) <= 120_000:
                hits.append(
                    {
                        "clip_id": c.get("clip_id"),
                        "template_id": c.get("template_id"),
                        "chain_category": c.get("chain_category"),
                        "t0_ms": t0,
                        "t1_ms": t1,
                        "first_event": c.get("first_event"),
                        "last_event": c.get("last_event"),
                    }
                )
        per_cand.append(
            {
                "candidate_id": mg.get("candidate_id"),
                "score_before": mg.get("score_before"),
                "score_after": mg.get("score_after"),
                "score_confirmation_time": conf,
                "n_outcome_or_goal_hits_B": len(hits),
                "hits": hits,
            }
        )

    return {
        "schema": "v2_strip_ab_compare_v1",
        "n_chains_A": len(a),
        "n_chains_B": len(b),
        "category_counts_A": strip_a.get("category_counts"),
        "category_counts_B": strip_b.get("category_counts"),
        "n_outcome_or_goal_A": len(outcome_a),
        "n_outcome_or_goal_B": len(outcome_b),
        "n_only_in_A": len(only_a),
        "n_only_in_B": len(only_b),
        "only_in_B_sample": [
            {"t0_ms": k[0], "t1_ms": k[1], "template_id": k[2], "category": k[3]} for k in only_b[:20]
        ],
        "only_in_A_sample": [
            {"t0_ms": k[0], "t1_ms": k[1], "template_id": k[2], "category": k[3]} for k in only_a[:20]
        ],
        "missing_candidate_coverage_B": per_cand,
        "note": "No production param changes; new chains only if enhanced events change geometry/classify",
        "render_ready": False,
    }


def load_or_run_baseline_A(
    *,
    events_path: Path,
    out_dir: Path,
    algo_root: Path,
    match_id: str,
    existing_strip_a: Optional[Path] = None,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if existing_strip_a and Path(existing_strip_a).is_file():
        data = json.loads(Path(existing_strip_a).read_text(encoding="utf-8"))
        (out_dir / "strip_A_original.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return data
    raw = json.loads(Path(events_path).read_text(encoding="utf-8"))
    timeline = events_to_timeline(raw.get("events") or [])
    (out_dir / "timeline_A.json").write_text(
        json.dumps({"n": len(timeline), "events": timeline}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    strip = run_strip_predict(
        timeline_events=timeline, match_id=match_id, algo_root=algo_root, label="A_original"
    )
    strip["source_plain"] = str(events_path)
    (out_dir / "strip_A_original.json").write_text(
        json.dumps(strip, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return strip
