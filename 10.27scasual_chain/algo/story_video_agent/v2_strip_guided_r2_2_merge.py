"""Merge cached Round-2.1 verified Goals + newly recovered Goals (dedupe, audit)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from story_video_agent.v2_enhanced_events import merge_enhanced_events_payload, write_enhanced_bundle
from story_video_agent.v2_goal_live_replay_audit import apply_audit_correction, audit_inferred_goal


def load_inferred_from_dir(path: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Load inferred goals + verifications from a prior recovery out_dir."""
    path = Path(path)
    goals: List[Dict[str, Any]] = []
    verifications: List[Dict[str, Any]] = []
    inf_p = path / "enhanced" / "inferred_goal_events.json"
    if not inf_p.is_file():
        inf_p = path / "inferred_goal_events.json"
    if inf_p.is_file():
        raw = json.loads(inf_p.read_text(encoding="utf-8"))
        goals = list(raw.get("events") or [])
    vv_p = path / "video_verifications.json"
    if vv_p.is_file():
        raw = json.loads(vv_p.read_text(encoding="utf-8"))
        verifications = list(raw if isinstance(raw, list) else raw.get("verifications") or [])
    return goals, verifications


def _score_key(g: Dict[str, Any]) -> Tuple:
    st = g.get("related_score_transition") or {}
    return (
        tuple(st.get("score_before") or ()),
        tuple(st.get("score_after") or ()),
        round(float((g.get("media_time") or {}).get("event_time_sec") or -1), 1),
    )


def dedupe_inferred_goals(goals: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep one verified goal per score transition; prefer earlier live result time."""
    by_trans: Dict[Tuple, Dict[str, Any]] = {}
    for g in goals:
        if g.get("source") != "video_agent_inferred":
            continue
        st = g.get("related_score_transition") or {}
        key = (tuple(st.get("score_before") or ()), tuple(st.get("score_after") or ()))
        if key == ((), ()):
            key = ("id", g.get("inferred_event_id") or g.get("event_id"))
        prev = by_trans.get(key)
        if prev is None:
            by_trans[key] = g
            continue
        # Prefer verified_action, then earlier result time, then live broadcast_phase
        def rank(x: Dict[str, Any]) -> Tuple:
            ver = 0 if x.get("verification_status") == "verified_action" else 1
            t = float((x.get("goal_result") or {}).get("media_sec") or 1e18)
            live = 0 if (x.get("video_context") or {}).get("broadcast_phase") == "LIVE" else 1
            return (ver, live, t)

        if rank(g) < rank(prev):
            by_trans[key] = g
    return sorted(
        by_trans.values(),
        key=lambda g: float((g.get("media_time") or {}).get("event_time_sec") or 0),
    )


def merge_and_audit_goals(
    *,
    cached_dirs: Sequence[Path],
    fresh_dirs: Sequence[Path],
    original_events_path: Path,
    out_dir: Path,
    match_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Merge goals from dirs, audit live/replay, write enhanced bundle."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    all_goals: List[Dict[str, Any]] = []
    all_vv: List[Dict[str, Any]] = []
    sources = []
    for label, dirs in (("cached", cached_dirs), ("fresh", fresh_dirs)):
        for d in dirs:
            goals, vv = load_inferred_from_dir(Path(d))
            sources.append(
                {
                    "label": label,
                    "path": str(d),
                    "n_goals": len(goals),
                    "n_verifications": len(vv),
                    "reused_no_new_vlm": label == "cached",
                }
            )
            for g in goals:
                g = dict(g)
                g["_source_dir"] = str(d)
                all_goals.append(g)
            for v in vv:
                v = dict(v)
                v["_source_dir"] = str(d)
                all_vv.append(v)

    # Group verifications by candidate / inferred id
    vv_by_cand: Dict[str, List[Dict[str, Any]]] = {}
    for v in all_vv:
        cid = str(v.get("linked_candidate_id") or "unknown")
        vv_by_cand.setdefault(cid, []).append(v)

    audits = []
    corrected_goals = []
    for g in all_goals:
        eid = str(g.get("inferred_event_id") or g.get("event_id") or "")
        cid = eid.replace("inferred_goal_", "") if eid.startswith("inferred_goal_") else ""
        vv = vv_by_cand.get(cid) or []
        # Also match by source dir
        if not vv:
            src = g.get("_source_dir")
            vv = [v for v in all_vv if v.get("_source_dir") == src]
        audit = audit_inferred_goal(inferred_event=g, verifications=vv)
        audits.append(audit)
        corrected_goals.append(apply_audit_correction(g, audit))

    deduped = dedupe_inferred_goals(corrected_goals)
    verified = [g for g in deduped if g.get("verification_status") == "verified_action"]
    unresolved = [g for g in deduped if g.get("verification_status") != "verified_action"]

    bundle = merge_enhanced_events_payload(
        original_events_path=Path(original_events_path),
        inferred_goals=verified,
        match_id=match_id,
    )
    paths = write_enhanced_bundle(out_dir / "enhanced", bundle)

    audit_doc = {
        "schema": "v2_r2_2_goal_merge_audit_v1",
        "sources": sources,
        "n_input_goals": len(all_goals),
        "n_after_dedupe": len(deduped),
        "n_verified_merged": len(verified),
        "n_unresolved_after_audit": len(unresolved),
        "audits": audits,
        "unresolved_goals": [
            {
                "inferred_event_id": g.get("inferred_event_id"),
                "verification_status": g.get("verification_status"),
                "live_replay_audit": g.get("live_replay_audit"),
            }
            for g in unresolved
        ],
        "verified_summary": [
            {
                "inferred_event_id": g.get("inferred_event_id"),
                "score": g.get("related_score_transition"),
                "shot_sec": (g.get("shot_action") or {}).get("media_sec"),
                "result_sec": (g.get("goal_result") or {}).get("media_sec"),
                "live": (g.get("video_context") or {}).get("broadcast_phase"),
                "audit": (g.get("live_replay_audit") or {}).get("status"),
            }
            for g in verified
        ],
        "render_ready": False,
    }
    audit_path = out_dir / "goal_merge_audit.json"
    audit_path.write_text(json.dumps(audit_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Evidence inventory
    evid = {
        "schema": "v2_r2_2_evidence_inventory_v1",
        "n_verifications": len(all_vv),
        "by_candidate": {k: len(v) for k, v in vv_by_cand.items()},
        "verifications": all_vv,
        "render_ready": False,
    }
    evid_path = out_dir / "evidence_inventory.json"
    evid_path.write_text(json.dumps(evid, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "bundle": bundle,
        "verified_goals": verified,
        "unresolved_goals": unresolved,
        "audits": audits,
        "paths": {**{k: str(v) for k, v in paths.items()}, "audit": str(audit_path), "evidence": str(evid_path)},
        "sources": sources,
        "all_verifications": all_vv,
        "render_ready": False,
    }
