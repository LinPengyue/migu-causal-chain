"""V3 Plan-2: frozen 8.31 predictions -> V1 story planning -> V2 evidence gates.

New package, outputs, and branch. Imports V1/V2 as read-only libraries.
Structure dry-run is NOT a video-grounded or deliverable story.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from story_video_agent.v2_event_adapter import load_events_json, INPUT_SOURCES
from story_video_agent.v2_g0_cross_match_preflight import (
    assert_match_id_consistent, reject_forbidden_input_path,
    reject_forbidden_payload, sha256_file, validate_strip_bundle_provenance,
)
from story_video_agent.v2_g1_cross_match_cli import _score_timeline_from_events
from story_video_agent.v2_score_transitions import analyze_last_deficit_arcs
from story_video_agent.v2_strip_adapter import adapt_strip_bundle
from story_video_agent.narrative_composer import compose_story_plan
from story_video_agent.phase5_delivery import (
    build_story_graph, build_story_scope, select_delivery_rows, validate_story_graph,
)

SCHEMA = "story_va_v3_plan2_v1"
SOURCE = "causal_chain6_predicted"
CRITICAL = ("opening_deficit", "equalizer", "go_ahead")
GOALISH = {"Goal", "goal", "进球", "头球破门", "乌龙球", "own_goal", "header_goal"}
FORBIDDEN_STRIP_PARTS = ("gold", "causal.json", "human_label")
MAX_BUILDUP = 5


class V3InputError(ValueError):
    pass


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _safe_output_dir(path: Path, inputs: Sequence[Path]) -> Path:
    target = path.resolve()
    parts = {p.lower() for p in target.parts}
    if "v3" not in parts and not any(p.startswith("v3_") for p in parts):
        raise V3InputError("Output must have a dedicated v3/ path component")
    if any(p in {"v1", "v2"} for p in parts):
        raise V3InputError("V3 output must not be nested in a V1/V2 directory")
    if any(target == p.resolve() or target in p.resolve().parents for p in inputs):
        raise V3InputError("Output must not overlap an input path")
    if target.exists() and any(target.iterdir()):
        raise V3InputError("Refusing to overwrite a nonempty V3 output; choose a new run directory")
    return target


def _check_inputs(match_id: str, events: Path, strips: Path, video: Path) -> Dict[str, str]:
    for p in (events, strips, video):
        if not p.is_file():
            raise V3InputError(f"Missing input: {p}")
    for p in (events, strips):
        if not reject_forbidden_input_path(p)["ok"]:
            raise V3InputError(f"Forbidden gold/causal input path: {p}")
    if any(x in strips.name.lower() for x in FORBIDDEN_STRIP_PARTS):
        raise V3InputError("Predicted strips must not be gold/human/causal data")
    raw_event = json.loads(events.read_text(encoding="utf-8"))
    if not isinstance(raw_event, dict) or not reject_forbidden_payload(raw_event)["ok"]:
        raise V3InputError("Events must be raw non-causal records")
    if not assert_match_id_consistent(
        cli_match_id=match_id, events_match_id=str(raw_event.get("match_id") or "")
    )["ok"]:
        raise V3InputError("match_id disagrees with event source")
    raw_strip = json.loads(strips.read_text(encoding="utf-8"))
    if not isinstance(raw_strip, dict) or not validate_strip_bundle_provenance(raw_strip)["ok"]:
        raise V3InputError("Predicted strip provenance rejected (gold/invalid)")
    if raw_strip.get("match_id") and str(raw_strip["match_id"]) != match_id:
        raise V3InputError("Predicted strip match_id mismatch")
    if not raw_strip.get("chains") and not raw_strip.get("clips"):
        raise V3InputError("No predicted strip chains; require frozen 8.31 prediction output")
    mode = str(raw_strip.get("mode") or (raw_strip.get("config") or {}).get("mode") or "")
    if mode not in {"reinfer_A_original", "algo_predicted", "predicted", "causal_chain6_predicted"}:
        raise V3InputError(f"Unapproved prediction mode {mode!r}; require verified 8.31 prediction provenance")
    return {
        "events_sha256": sha256_file(events),
        "strips_sha256": sha256_file(strips),
        "video_sha256": sha256_file(video),
        "mode": mode,
    }


def to_predicted_causal(
    adapted: Dict[str, Any], *, match_id: str, hashes: Dict[str, str]
) -> Dict[str, Any]:
    """V1-compatible chain fields, explicitly unverified and never promoted to Goal."""
    out: List[Dict[str, Any]] = []
    for c in adapted["chains"]:
        evs = []
        for e in c.get("event_sequence") or []:
            evs.append({
                "event_id": e.get("event_id"), "type": e.get("type"),
                "t_ms": e.get("t_ms"), "t0_ms": e.get("t0_ms"),
                "t1_ms": e.get("t1_ms"), "mapping_status": e.get("mapping_status"),
                "prediction_source": SOURCE, "verification_status": "unverified",
            })
        out.append({
            "chain_id": c["strip_chain_id"],
            "chain_category": c.get("predicted_category"),
            "template_id": c.get("predicted_template_id"),
            "predicted_label": c.get("predicted_label"),
            "first_event": c.get("first_event"),
            "last_event": c.get("last_event"),
            "t0_ms": c["t0_ms"], "t1_ms": c["t1_ms"],
            "event_ids": c.get("source_event_ids") or [],
            "events": evs,
            "confidence": c.get("confidence"),
            "confidence_field": c.get("confidence_field"),
            "margin": c.get("margin"),
            "prediction_source": SOURCE,
            "verification_status": "unverified",
            "goal_action_sec": None,
            "is_video_verified": False,
            "human_causal_relation": None,
            "input_hashes": hashes,
        })
    return {
        "schema": "v3_predicted_causal_v1",
        "match_id": match_id,
        "prediction_source": SOURCE,
        "input_hashes": hashes,
        "n_predicted_chains": len(out),
        "n_dropped": adapted.get("n_dropped"),
        "chain_diagnostics": adapted.get("chain_diagnostics") or [],
        "causal_chains": out,
        "caution": "V1 field compatibility only; not human causal truth, not verified Goal.",
        "render_ready": False,
    }


def _score_path(timeline: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = []
    last = None
    for row in timeline:
        pair = row.get("score")
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            continue
        a, b = int(pair[0]), int(pair[1])
        delta = None
        if last is not None and a >= last[0] and b >= last[1]:
            if a > last[0] and b == last[1]:
                delta = "left"
            elif b > last[1] and a == last[0]:
                delta = "right"
        result.append({
            "score": f"{a}:{b}",
            "t_sec": row.get("media_start_sec"),
            "carrier_event_id": row.get("event_id"),
            "delta_side": delta,
            "time_provenance": "scoreboard_confirmation_only",
            "goal_action_sec": None,
        })
        last = (a, b)
    return result


def _candidate_buildup(
    predicted: Dict[str, Any], arc: Dict[str, Any], *,
    allowed_event_ids: Sequence[str]
) -> List[Dict[str, Any]]:
    """Pick editorial context from real predicted chains, NOT synthetic goal events."""
    t0 = (arc.get("score_confirmation_sec") or {}).get("deficit")
    t1 = (arc.get("score_confirmation_sec") or {}).get("equalizer")
    if t0 is None or t1 is None:
        return []
    permitted = set(allowed_event_ids)
    candidates = []
    for chain in predicted["causal_chains"]:
        if chain.get("last_event") in GOALISH or chain.get("first_event") in GOALISH:
            continue
        if "进球" in str(chain.get("predicted_label") or ""):
            continue
        start = float(chain["t0_ms"]) / 1000.0
        if not float(t0) <= start < float(t1):
            continue
        evs = [e for e in chain.get("events") or []
               if e.get("event_id") and str(e["event_id"]) in permitted
               and str(e.get("type") or "") not in GOALISH
               and e.get("t_ms") is not None]
        if not evs:
            continue
        e = evs[-1]
        candidates.append({
            "event_id": str(e["event_id"]), "type": str(e.get("type") or "unknown"),
            "t_ms": e["t_ms"], "story_role": "蓄力",
            "source": "predicted_causal", "source_chain_id": chain["chain_id"],
            "prediction_source": SOURCE, "prediction_confidence": chain.get("confidence"),
            "verification_status": "unverified", "is_replay": False,
            "time_provenance": "unverified_predicted_event",
        })
    # Max 5 diverse chronologically spread candidates. No inferred causal relationship.
    candidates.sort(key=lambda x: float(x["t_ms"]))
    if len(candidates) > MAX_BUILDUP:
        idx = [round(i * (len(candidates) - 1) / (MAX_BUILDUP - 1))
               for i in range(MAX_BUILDUP)]
        candidates = [candidates[i] for i in idx]
    unique = {c["event_id"]: c for c in candidates}
    return sorted(unique.values(), key=lambda x: float(x["t_ms"]))


def _story_view(
    match_id: str, score_path: List[Dict[str, Any]],
    arc_pack: Dict[str, Any], buildup: List[Dict[str, Any]]
) -> Dict[str, Any]:
    arc = arc_pack.get("selected_arc")
    side = arc.get("protagonist_side") if arc else None
    return {
        "schema_version": "v3_v1_story_view_v1",
        "match_id": match_id,
        "story_tier": "candidate" if arc else "none",
        "is_candidate": bool(arc), "has_story": False,
        "protagonist_side": side,
        "recognition": {"tier": "candidate" if arc else "none",
                        "protagonist_side": side,
                        "present": False,
                        "beats": {"铺垫": [], "蓄力": [x["event_id"] for x in buildup],
                                  "转折": [], "高潮": [], "收尾": []}},
        "score_path": score_path,
        "events": buildup,
        "no_story_reason": None if arc else arc_pack.get("status"),
        "note": "V1-compatible structure view; goals remain unresolved.",
        "render_ready": False,
    }


def _safe_edl(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Use V1 selector but preserve all critical missing-goal placeholders."""
    selected = select_delivery_rows(plan)
    for r in selected:
        r["include_in_cut"] = False
        r["render_ready"] = False
        r["verification_status"] = "unverified"
        if "scoreboard" in str(r.get("role") or ""):
            r["scoreboard_only"] = True
            r["goal_action_complete"] = False
    # Selector intentionally removes blocked/missing media rows: restore them as explicit EDL slots.
    pending = []
    roles = {
        "opponent_opening_goal_action": "opening_deficit",
        "equalizer_goal_action": "equalizer",
        "go_ahead_goal_action": "go_ahead",
    }
    for source_role, role in roles.items():
        rows = [x for x in plan.get("segments") or [] if x.get("role") == source_role]
        actual_verified = False  # V3 stage1/2 cannot produce video verification.
        if not actual_verified:
            p = rows[-1] if rows else {}
            pending.append({
                "segment_id": "v3_goal_placeholder_" + role,
                "beat": p.get("beat") or role,
                "role": source_role, "critical_goal_role": role,
                "media_in": None, "media_out": None,
                "score_confirmation_sec": (p.get("time_provenance") or {}).get("score_anchor_t_sec"),
                "goal_action_sec": None,
                "time_status": "pending_video_first_live",
                "shot_kind": "unknown",
                "verification_status": "unresolved",
                "verification_level": "score_only",
                "render_eligibility": "blocked_unresolved",
                "goal_action_complete": False,
                "include_in_cut": False, "render_ready": False,
                "note": "No goal action without continuous LIVE shot/net video evidence.",
            })
    return selected + pending


def _evidence_tasks(arc: Optional[Dict[str, Any]], edl: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    if not arc:
        return {"schema": "v3_evidence_tasks_v1", "tasks": [], "render_ready": False}
    anchors = arc.get("score_confirmation_sec") or {}
    tasks = []
    for role, anchor in zip(CRITICAL, ("deficit", "equalizer", "go_ahead")):
        tasks.append({
            "role": role,
            "score_before": None if role == "opening_deficit" else
                (arc.get("deficit_score") if role == "equalizer" else arc.get("equalizer_score")),
            "score_after": arc.get("deficit_score") if role == "opening_deficit" else
                (arc.get("equalizer_score") if role == "equalizer" else arc.get("go_ahead_score")),
            "score_confirmation_sec": anchors.get(anchor),
            "goal_action_sec": None,
            "needs": ["first_live_continuous_clip", "observed_shot",
                      "observed_net", "attacking_team_match",
                      "not_replay", "source_pts", "identity_bound_media"],
            "search_policy": "targeted_only_no_unbounded_scan",
            "status": "unresolved",
            "render_ready": False,
        })
    return {"schema": "v3_evidence_tasks_v1", "tasks": tasks,
            "n_unresolved": len(tasks), "render_ready": False}


def run_structure(
    *, match_id: str, events: Path, predicted_strips: Path,
    video: Path, out_dir: Path, input_source: str = "human_corrected"
) -> Dict[str, Any]:
    out = _safe_output_dir(out_dir, (events, predicted_strips, video))
    hashes = _check_inputs(match_id, events, predicted_strips, video)
    event_bundle = load_events_json(events, input_source=input_source)
    adapted = adapt_strip_bundle(predicted_strips, events_path=events, match_id=match_id)
    if adapted["n_dropped"]:
        raise V3InputError(f"Predicted chains dropped during adaptation: {adapted['n_dropped']}")
    predicted = to_predicted_causal(adapted, match_id=match_id, hashes=hashes)
    timeline = _score_timeline_from_events(event_bundle["events"])
    arc_pack = analyze_last_deficit_arcs(timeline, team_names=event_bundle["team_names"])
    selected = arc_pack.get("selected_arc")
    raw_ids = [e["event_id"] for e in event_bundle["events"] if e.get("event_id")]
    buildup = _candidate_buildup(predicted, selected, allowed_event_ids=raw_ids) if selected else []
    score_path = _score_path(timeline)
    story = _story_view(match_id, score_path, arc_pack, buildup)
    # V1 is read-only. Deliberately do NOT supply predicted Goal chains to
    # V1 merge_causal_live_goals: it expects action-time causal truth.
    safe_causal = {"match_id": match_id,
                   "team_1_name": event_bundle["team_names"].get("team_1") or
                                  event_bundle["team_names"].get("left") or "",
                   "team_2_name": event_bundle["team_names"].get("team_2") or
                                  event_bundle["team_names"].get("right") or "",
                   "causal_chains": []}
    plan = compose_story_plan(story, causal=safe_causal, use_llm=False)
    plan["schema"] = "v3_v1_story_plan_v1"
    plan["render_ready"] = False
    plan["story_scope"] = build_story_scope(story, plan)
    plan["v3_guard"] = {
        "predicted_goal_chains_are_not_v1_verified_goal_events": True,
        "no_paid_api": True, "no_render": True, "selected_arc_source": "v2_last_deficit_arc",
    }
    edl = _safe_edl(plan)
    graph = build_story_graph(plan=plan, story=story, delivery_edl=edl)
    ok, errors = validate_story_graph(graph)
    graph["structure_ok"] = ok
    graph["structure_problems"] = errors
    graph["render_ready"] = False
    tasks = _evidence_tasks(selected, edl)
    report = {
        "schema": SCHEMA, "status": "ok_structure_dry_run" if ok and selected else "blocked_structure",
        "match_id": match_id,
        "n_predictions": predicted["n_predicted_chains"],
        "n_adapted": adapted["n_adapted"],
        "selected_arc_side": (selected or {}).get("protagonist_side"),
        "selected_arc_team": (selected or {}).get("protagonist_team_name"),
        "n_buildup_candidates": len(buildup),
        "n_critical_goal_tasks": len(tasks["tasks"]),
        "n_video_verified_goals": 0,
        "story_graph_structure_ok": ok,
        "story_graph_problems": errors,
        "api_calls": 0, "render_ready": False,
        "next": ("v2_targeted_goal_verification" if ok and selected else
                 "audit_predicted_chain_recall_and_story_structure"),
        "input_hashes": hashes,
        "note": "V3 adaptation / V1 story+graph+EDL dry-run only, not video evidence.",
    }
    # All files written under new empty V3 directory, never V1/V2 outputs.
    out.mkdir(parents=True, exist_ok=False) if not out.exists() else None
    dump(out / "predicted_causal.json", predicted)
    dump(out / "selected_arc.json", arc_pack)
    dump(out / "story_view.json", story)
    dump(out / "story_plan.json", plan)
    dump(out / "story_graph.json", graph)
    dump(out / "candidate_edl.json", edl)
    dump(out / "critical_goal_evidence_tasks.json", tasks)
    dump(out / "provenance.json", {
        "schema": "v3_provenance_v1", "match_id": match_id,
        "prediction_source": SOURCE, "prediction_mode": hashes["mode"],
        "input_paths": {"events": str(events), "strips": str(predicted_strips),
                        "video": str(video)},
        "input_hashes": hashes,
        "no_gold": True, "no_v1_v2_writes": True,
        "api_calls": 0, "render_ready": False,
    })
    dump(out / "run_report.json", report)
    return report


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="V3 Plan-2 prediction to V1 structure dry-run")
    p.add_argument("--match-id", required=True)
    p.add_argument("--events", type=Path, required=True)
    p.add_argument("--predicted-strips", type=Path, required=True)
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--input-source", choices=sorted(INPUT_SOURCES), default="human_corrected")
    args = p.parse_args(argv)
    try:
        report = run_structure(match_id=args.match_id, events=args.events,
            predicted_strips=args.predicted_strips, video=args.video,
            out_dir=args.out_dir, input_source=args.input_source)
    except (V3InputError, ValueError, OSError) as exc:
        p.error(str(exc))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ok_structure_dry_run" else 2


if __name__ == "__main__":
    raise SystemExit(main())
