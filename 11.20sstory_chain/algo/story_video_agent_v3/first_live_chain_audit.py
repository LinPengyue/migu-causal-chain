"""Pipeline first-live visual audit for retained goal anchors (zero paid API).

Reuses first_live_localize.audit_localized_candidate / classify_semantic_label.
Never upgrades metadata, ffmpeg preview success, or scoreboard flips to
FIRST_LIVE_VERIFIED. Paid VLM is out of scope here — call sites must ask first.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .first_live_localize import audit_localized_candidate, collect_event_replay_overlaps
from .pipeline import dump

FIRST_LIVE_STATUSES = (
    "FIRST_LIVE_VERIFIED",
    "POSSIBLE_FIRST_LIVE",
    "REPLAY_DETECTED",
    "UNRESOLVED",
)

_GOAL_ROLE_MARKERS = (
    "goal_action",
    "opening_goal",
    "equalizer_goal",
    "go_ahead_goal",
    "winning_goal",
    "opponent_opening",
)


def _edl_segments(edl: Any) -> List[Dict[str, Any]]:
    if isinstance(edl, list):
        return [s for s in edl if isinstance(s, dict)]
    if isinstance(edl, dict):
        for k in ("segments", "edl", "clips", "items"):
            v = edl.get(k)
            if isinstance(v, list):
                return [s for s in v if isinstance(s, dict)]
        timeline = edl.get("timeline")
        if isinstance(timeline, dict) and isinstance(timeline.get("segments"), list):
            return [s for s in timeline["segments"] if isinstance(s, dict)]
    return []


def is_goal_action_segment(seg: Mapping[str, Any]) -> bool:
    sid = str(seg.get("segment_id") or seg.get("id") or "").lower()
    role = str(seg.get("role") or seg.get("narrative_role") or "").lower()
    blob = f"{sid} {role}"
    if "scoreboard" in blob or "title" in blob:
        return False
    return any(m in blob for m in _GOAL_ROLE_MARKERS) or (
        "goal" in sid and "action" in sid
    )


def map_semantic_to_first_live_status(
    *,
    semantic_label: Optional[str],
    agent_auto_verified: bool = False,
    goal_action_verified_ok: bool = False,
    candidate_extracted_ok: bool = False,
    score_confirm_collision: bool = False,
) -> str:
    """Strict mapping. Extraction / metadata alone never yield FIRST_LIVE_VERIFIED."""
    lab = str(semantic_label or "").strip().lower()
    if lab == "replay":
        return "REPLAY_DETECTED"
    if score_confirm_collision:
        return "UNRESOLVED"
    if lab == "verified_first_live" and agent_auto_verified and goal_action_verified_ok:
        return "FIRST_LIVE_VERIFIED"
    if lab == "possible_first_live":
        return "POSSIBLE_FIRST_LIVE"
    if lab in {"verified_first_live"} and not (agent_auto_verified and goal_action_verified_ok):
        # Refuse to promote incomplete verified claims.
        return "UNRESOLVED"
    # ffmpeg/candidate extract success is evidence packaging only.
    _ = candidate_extracted_ok
    return "UNRESOLVED"


def _nearest_recovery(
    media_in: float,
    recovered: Sequence[Mapping[str, Any]],
    *,
    tol_sec: float = 45.0,
) -> Optional[Dict[str, Any]]:
    best = None
    best_d = None
    for g in recovered:
        action = g.get("goal_action_sec")
        if action is None:
            continue
        d = abs(float(action) - float(media_in))
        if d <= tol_sec and (best_d is None or d < best_d):
            best = dict(g)
            best_d = d
    return best


def _load_events(events_path: Optional[Path]) -> List[Dict[str, Any]]:
    if events_path is None or not Path(events_path).is_file():
        return []
    raw = json.loads(Path(events_path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        rows = raw.get("events") or []
    elif isinstance(raw, list):
        rows = raw
    else:
        rows = []
    out = []
    for e in rows:
        if not isinstance(e, dict):
            continue
        row = dict(e)
        if row.get("event_time_sec") is None and row.get("t_ms") is not None:
            try:
                row["event_time_sec"] = float(row["t_ms"]) / 1000.0
            except (TypeError, ValueError):
                pass
        if row.get("start_time_sec") is None and row.get("event_time_sec") is not None:
            row["start_time_sec"] = row["event_time_sec"]
        if row.get("end_time_sec") is None and row.get("event_time_sec") is not None:
            row["end_time_sec"] = float(row["event_time_sec"]) + 2.0
        out.append(row)
    return out


def audit_retained_goal_first_live(
    *,
    video: Path,
    edl: Any,
    out_dir: Path,
    events_path: Optional[Path] = None,
    goal_recovery: Optional[Mapping[str, Any]] = None,
    enable_paid_vlm: bool = False,
    source_video_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Audit every retained goal-action EDL segment with existing localize primitives.

    enable_paid_vlm must stay False unless the operator approved budget separately.
    When source_video_sha256 is provided it is recorded as the historical source
    identity of this audit (computed at creation time — never backfilled later).
    """
    if enable_paid_vlm:
        raise RuntimeError(
            "Paid first-live VLM disabled in this path; report cost estimate and wait for approval"
        )

    dest = Path(out_dir)
    dest.mkdir(parents=True, exist_ok=True)
    events = _load_events(events_path)
    recovered = list((goal_recovery or {}).get("candidates") or [])
    segs = [
        s for s in _edl_segments(edl)
        if is_goal_action_segment(s) and s.get("include_in_cut", True) is not False
    ]

    rows: List[Dict[str, Any]] = []
    for seg in segs:
        sid = str(seg.get("segment_id") or seg.get("id") or "")
        role = str(seg.get("role") or seg.get("narrative_role") or sid)
        mi = seg.get("media_in")
        mo = seg.get("media_out")
        if mi is None or mo is None:
            rows.append({
                "segment_id": sid,
                "role": role,
                "first_live_status": "UNRESOLVED",
                "reason": "missing_media_window",
                "evidence_gaps": ["missing_media_window"],
                "candidate_extracted_ok": False,
                "visual_verified": False,
            })
            continue

        mi_f, mo_f = float(mi), float(mo)
        rec = _nearest_recovery(mi_f, recovered)
        confirm = None
        score_before = None
        score_after = None
        if rec:
            confirm = rec.get("score_confirmation_sec")
            score_before = rec.get("score_before")
            score_after = rec.get("score_after")
            # Prefer recovery action window when EDL window looks like board-confirm.
            action = rec.get("goal_action_sec")
            if action is not None and confirm is not None and abs(mi_f - float(confirm)) < 0.75:
                # Refuse treating score-confirm as first-live action; shift audit to action.
                mi_f = float(action)
                mo_f = float(action) + max(8.0, mo_f - float(mi))

        score_confirm_collision = (
            confirm is not None and abs(mi_f - float(confirm)) < 0.5
        )

        # Event-level replay pre-check (no VLM).
        replays = collect_event_replay_overlaps(events, media_in=mi_f, media_out=mo_f)
        window = {
            "candidate_id": f"{sid}_{int(mi_f)}",
            "media_in": mi_f,
            "media_out": mo_f,
            "origin": "retained_edl_goal_anchor",
            "priority": 1,
        }
        score_bounds = {
            "last_before_obs": {"media_sec": (float(confirm) - 30.0) if confirm else None},
            "first_after_obs": {"media_sec": float(confirm) if confirm else None},
            "unknown_interval": (
                {"media_in": float(confirm) - 30.0, "media_out": float(confirm)}
                if confirm else None
            ),
        }

        audited = audit_localized_candidate(
            video=video,
            role=role,
            window=window,
            out_dir=dest,
            score_before=score_before,
            score_after=score_after,
            score_confirmation_sec=float(confirm) if confirm is not None else None,
            score_bounds=score_bounds,
            events=events,
            frame_notes=None,
            human_review=None,
            automated_semantic_log=None,
            dense_fps=0.5,
            max_dense_frames=8,
        )

        # Force replay if event spans fully cover the window.
        semantic = audited.get("semantic_label")
        if replays and all(
            float(r.get("start_time_sec") or 0) <= mi_f + 1
            and float(r.get("end_time_sec") or 0) >= mo_f - 1
            for r in replays
        ):
            semantic = "replay"
            audited["semantic_label"] = "replay"
            audited["classification_reason"] = "window_inside_event_replay"

        status = map_semantic_to_first_live_status(
            semantic_label=semantic,
            agent_auto_verified=bool(audited.get("agent_auto_verified")),
            goal_action_verified_ok=bool(audited.get("goal_action_verified_ok")),
            candidate_extracted_ok=bool(audited.get("candidate_extracted_ok")),
            score_confirm_collision=score_confirm_collision,
        )

        obs_mi = float(audited.get("media_in") or mi_f)
        obs_mo = float(audited.get("media_out") or mo_f)
        rows.append({
            "segment_id": sid,
            "role": role,
            "event_ids": list(seg.get("event_ids") or []),
            "media_in": mi_f,
            "media_out": mo_f,
            "source_pts": {"media_in": mi_f, "media_out": mo_f},
            "observation_window": {"media_in": obs_mi, "media_out": obs_mo},
            "evidence_window": {"media_in": obs_mi, "media_out": obs_mo},
            "clip_export": audited.get("clip_export"),
            "score_before": score_before,
            "score_after": score_after,
            "score_confirmation_sec": confirm,
            "goal_recovery_candidate_id": (rec or {}).get("candidate_id"),
            "goal_action_sec": (rec or {}).get("goal_action_sec"),
            "score_confirm_collision": score_confirm_collision,
            "first_live_status": status,
            "semantic_label": semantic,
            "classification_reason": audited.get("classification_reason"),
            "candidate_extracted_ok": bool(audited.get("candidate_extracted_ok")),
            "clip_path": audited.get("clip_path"),
            "frame_paths": audited.get("frame_paths") or [],
            "n_dense_frames": audited.get("n_dense_frames") or 0,
            "evidence_gaps": audited.get("evidence_gaps") or [],
            "agent_auto_verified": bool(audited.get("agent_auto_verified")),
            "goal_action_verified_ok": bool(audited.get("goal_action_verified_ok")),
            "visual_verified": status == "FIRST_LIVE_VERIFIED",
            "source_video_sha256": source_video_sha256,
            "paid_vlm_used": False,
            "note": (
                "Zero-cost structural+frame extraction audit; "
                "metadata/ffmpeg/score-flip alone never certify FIRST_LIVE_VERIFIED"
            ),
        })

    counts = {s: 0 for s in FIRST_LIVE_STATUSES}
    for r in rows:
        counts[r["first_live_status"]] = counts.get(r["first_live_status"], 0) + 1

    report = {
        "schema": "v3a_first_live_chain_audit_v1",
        "source_video": str(video),
        "source_video_sha256": source_video_sha256,
        "n_goal_anchors": len(rows),
        "status_counts": counts,
        "any_first_live_verified": counts.get("FIRST_LIVE_VERIFIED", 0) > 0,
        "any_replay_on_retained": counts.get("REPLAY_DETECTED", 0) > 0,
        "all_resolved_verified": (
            len(rows) > 0 and counts.get("FIRST_LIVE_VERIFIED", 0) == len(rows)
        ),
        "paid_api_calls": 0,
        "enable_paid_vlm": False,
        "goals": rows,
        "render_ready": False,
        "success_claimed": False,
        "note": (
            "Extraction and score/event heuristics produce POSSIBLE/REPLAY/UNRESOLVED. "
            "FIRST_LIVE_VERIFIED requires verified semantic proof (not enabled in zero-cost)."
        ),
    }
    dump(dest / "first_live_visual_audit.json", report)
    return report


def build_goal_recovery_impact(
    *,
    predicted_causal: Mapping[str, Any],
    goal_recovery: Mapping[str, Any],
) -> Dict[str, Any]:
    """Show recovery is not report-only: outcome chains and goal terminals from recovery."""
    chains = list(predicted_causal.get("causal_chains") or [])
    recovery_chains = [
        c for c in chains
        if str(c.get("prediction_source") or "").startswith("v3_goal_recovery")
        or str(c.get("causal_chain_subtype") or "").startswith("V3")
    ]
    recovery_goal_events = []
    for c in chains:
        for e in c.get("events") or []:
            if str(e.get("source") or "") == "v3_goal_recovery" or str(
                e.get("event_id") or ""
            ).startswith("v3_goal_"):
                recovery_goal_events.append({
                    "annotation_id": c.get("annotation_id"),
                    "event_id": e.get("event_id"),
                    "t_ms": e.get("t_ms"),
                    "t_sec": (float(e["t_ms"]) / 1000.0) if e.get("t_ms") is not None else None,
                    "source": e.get("source"),
                })
    adapter = predicted_causal.get("v3_adapter") or {}
    cands = list(goal_recovery.get("candidates") or [])
    with_action = [c for c in cands if c.get("single_goal_increment") and c.get("goal_action_sec") is not None]
    return {
        "schema": "v3a_goal_recovery_impact_v1",
        "goal_recovery_used": bool(adapter.get("goal_recovery_used")),
        "n_recovery_candidates": goal_recovery.get("n_candidates"),
        "n_single_goal": goal_recovery.get("n_single_goal"),
        "n_with_goal_action_sec": goal_recovery.get("n_with_goal_action_sec"),
        "n_v3_outcome_chains": adapter.get("n_v3_outcome_chains"),
        "n_goal_terminals_in_adapted_chains": adapter.get("n_goal_terminals_in_adapted_chains"),
        "n_recovery_sourced_chains": len(recovery_chains),
        "n_recovery_sourced_goal_events": len(recovery_goal_events),
        "recovery_goal_events": recovery_goal_events,
        "entered_predicted_causal": bool(recovery_goal_events) or int(adapter.get("n_v3_outcome_chains") or 0) > 0,
        "candidates_with_action": [
            {
                "candidate_id": c.get("candidate_id"),
                "goal_action_sec": c.get("goal_action_sec"),
                "score_confirmation_sec": c.get("score_confirmation_sec"),
                "score_before": c.get("score_before"),
                "score_after": c.get("score_after"),
                "action_neq_confirm": (
                    abs(float(c["goal_action_sec"]) - float(c["score_confirmation_sec"])) >= 0.5
                    if c.get("goal_action_sec") is not None and c.get("score_confirmation_sec") is not None
                    else None
                ),
            }
            for c in with_action
        ],
    }
