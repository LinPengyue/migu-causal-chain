"""G2.2 first-live retrieval — reuse R2.5/R2.6 live-only mechanisms without paid API.

Loop: candidate retrieve → replay/score-order audit → reject post-score replay →
search earlier → propose continuous first-live-oriented windows.

Never upgrades verification_status to verified_first_live without semantic evidence.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from story_video_agent.v2_event_adapter import load_events_json
from story_video_agent.v2_g0_cross_match_preflight import (
    assert_match_id_consistent,
    reject_forbidden_input_path,
    reject_forbidden_payload,
    sha256_file,
    write_json,
)
from story_video_agent.v2_g2_video_evidence import _cut_continuous_clip, _extract_frame, _ffprobe_duration
from story_video_agent.v2_goal_live_replay_audit import audit_inferred_goal
from story_video_agent.v2_strip_guided_r2_5_live_only import locate_continuous_live_goal_window
from story_video_agent.v2_video_evidence_gate import NOT_VERIFIED


# Human G2.1 Top-1 judgments (append-only reference; do not overwrite G2 history).
G21_HUMAN_TOP1 = {
    ("A_uae_oman", "opening_deficit"): "GOAL_VISUAL_PRESENT_FIRST_LIVE_UNRESOLVED",
    ("A_uae_oman", "equalizer"): "REPLAY_SUSPECTED_FIRST_LIVE_UNRESOLVED",
    ("A_uae_oman", "go_ahead"): "GOAL_ACTION_NOT_IN_WINDOW",
    ("B_osasuna_celta", "opening_deficit"): "POST_SCORE_REPLAY",
    ("B_osasuna_celta", "equalizer"): "POST_SCORE_REPLAY",
    ("B_osasuna_celta", "go_ahead"): "POST_SCORE_REPLAY",
}


def collect_event_replay_overlaps(
    events: Sequence[Dict[str, Any]],
    *,
    media_in: float,
    media_out: float,
) -> List[Dict[str, Any]]:
    """Annotated REPLAY rows overlapping a neighborhood (R2.5 event override source)."""
    out: List[Dict[str, Any]] = []
    for e in events:
        t0 = e.get("media_start_sec")
        t1 = e.get("media_end_sec")
        te = e.get("event_time_sec")
        if te is None and t0 is None:
            continue
        start = float(t0 if t0 is not None else te)
        end = float(t1 if t1 is not None else (float(te) + 3.0 if te is not None else start + 3.0))
        if end < media_in or start > media_out:
            continue
        is_rep = e.get("is_replay") is True or str(e.get("broadcast_phase") or "").upper() == "REPLAY"
        if not is_rep:
            continue
        out.append(
            {
                "event_id": e.get("event_id"),
                "event_type": e.get("event_type"),
                "start_time_sec": start,
                "end_time_sec": end,
                "is_replay": True,
            }
        )
    return out


def build_event_broadcast_timeline(
    events: Sequence[Dict[str, Any]],
    *,
    media_in: float,
    media_out: float,
    step: float = 4.0,
) -> Dict[str, Any]:
    """Zero-API timeline slices from event LIVE/REPLAY labels (reuse R2.5 phase schema)."""
    slices: List[Dict[str, Any]] = []
    t = float(media_in)
    while t < float(media_out) - 0.5:
        s = t
        e = min(float(media_out), t + step)
        hits = [
            ev
            for ev in events
            if ev.get("event_time_sec") is not None
            and s - 0.5 <= float(ev["event_time_sec"]) <= e + 0.5
        ]
        n_rep = sum(
            1
            for ev in hits
            if ev.get("is_replay") is True or str(ev.get("broadcast_phase") or "").upper() == "REPLAY"
        )
        n_live = sum(
            1
            for ev in hits
            if ev.get("is_replay") is not True
            and str(ev.get("broadcast_phase") or "").upper() != "REPLAY"
        )
        has_shot = any("Shot" in str(ev.get("event_type") or "") for ev in hits if ev.get("is_replay") is not True)
        has_net = False  # no Goal typed events typically; keep honest
        if n_rep and not n_live:
            phase = "replay"
        elif n_rep and n_live:
            phase = "transition"
        elif n_live:
            phase = "live"
        else:
            phase = "unknown"
        slices.append(
            {
                "media_in": round(s, 3),
                "media_out": round(e, 3),
                "phase": phase,
                "live_or_replay": phase if phase != "transition" else "mixed_or_ambiguous",
                "has_shot": has_shot,
                "has_net": has_net,
                "n_replay_events": n_rep,
                "n_live_events": n_live,
            }
        )
        t = e
    runs: List[Dict[str, Any]] = []
    for sl in slices:
        if runs and runs[-1]["phase"] == sl["phase"]:
            runs[-1]["media_out"] = sl["media_out"]
            runs[-1]["has_shot"] = runs[-1]["has_shot"] or sl["has_shot"]
            runs[-1]["has_net"] = runs[-1]["has_net"] or sl["has_net"]
        else:
            runs.append(
                {
                    "phase": sl["phase"],
                    "media_in": sl["media_in"],
                    "media_out": sl["media_out"],
                    "has_shot": sl["has_shot"],
                    "has_net": sl["has_net"],
                }
            )
    return {
        "schema": "v2_g22_event_broadcast_timeline_v1",
        "requested": {"media_in": media_in, "media_out": media_out},
        "slices": slices,
        "runs": runs,
        "n_live_slices": sum(1 for s in slices if s["phase"] == "live"),
        "n_replay_slices": sum(1 for s in slices if s["phase"] == "replay"),
        "n_unknown_slices": sum(1 for s in slices if s["phase"] == "unknown"),
        "n_transition_slices": sum(1 for s in slices if s["phase"] == "transition"),
        "basis": "event_annotation_is_replay_broadcast_phase_zero_api",
    }


def classify_post_score_replay_risk(
    *,
    media_in: float,
    media_out: float,
    score_confirmation_sec: float,
    kind: Optional[str] = None,
) -> Dict[str, Any]:
    """Fail-closed heuristic from G2.1 human review: windows hugging confirmation often are post-score replay packages."""
    conf = float(score_confirmation_sec)
    mi, mo = float(media_in), float(media_out)
    starts_near_confirm = abs(mi - conf) <= 8.0 or (conf - 5.0 <= mi <= conf + 2.0)
    covers_confirm = mi <= conf <= mo
    mostly_after = mi >= conf - 3.0
    late_thirdish = (kind or "").startswith("late_third") or "late_third" in str(kind or "")
    risk = False
    label = "candidate_ok_for_earlier_search"
    if mostly_after and covers_confirm:
        risk = True
        label = "POST_SCORE_REPLAY_RISK"
    elif starts_near_confirm and covers_confirm and (mo - conf) >= 5.0:
        risk = True
        label = "POST_SCORE_REPLAY_RISK"
    elif late_thirdish and covers_confirm and (conf - mi) <= 45.0 and (mo >= conf):
        # Default G2 late_third pattern — demote, not auto-accept
        risk = True
        label = "CONFIRM_ANCHORED_LIKELY_REPLAY_PACKAGE"
    return {
        "risk": risk,
        "label": label,
        "starts_near_confirm": starts_near_confirm,
        "covers_confirm": covers_confirm,
        "mostly_after_confirm": mostly_after,
        "render_ready": False,
    }


def score_order_reject(
    *,
    hypothesized_net_sec: Optional[float],
    score_confirmation_sec: float,
) -> Dict[str, Any]:
    """Reuse R2.6 audit rule: result after board confirmation → anomaly."""
    if hypothesized_net_sec is None:
        return {"ok": True, "score_order_anomaly": False}
    # Mirror audit_inferred_goal score_order_anomaly
    synthetic = {
        "shot_action": {"media_sec": float(hypothesized_net_sec) - 1.0},
        "goal_result": {"media_sec": float(hypothesized_net_sec)},
        "related_score_transition": {"score_confirmation_time": float(score_confirmation_sec)},
        "video_context": {},
    }
    audit = audit_inferred_goal(inferred_event=synthetic, verifications=[])
    return {
        "ok": audit.get("status") != "rejected_score_order_anomaly",
        "score_order_anomaly": bool(audit.get("score_order_anomaly")),
        "audit_status": audit.get("status"),
        "issues": audit.get("issues"),
        "render_ready": False,
    }


def live_shots_before_confirm(
    events: Sequence[Dict[str, Any]],
    *,
    prev_sec: float,
    confirm_sec: float,
    score_before: Optional[List[int]] = None,
    score_after: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """LIVE Shot rows before board confirm; reject post-score (score_pair already == after)."""
    rows = []
    after = list(score_after) if score_after is not None else None
    before = list(score_before) if score_before is not None else None
    for e in events:
        t = e.get("event_time_sec")
        if t is None:
            continue
        t = float(t)
        if not (float(prev_sec) - 5 <= t <= float(confirm_sec) + 0.5):
            continue
        et = str(e.get("event_type") or "")
        if "Shot" not in et and "shot" not in et.lower():
            continue
        if e.get("is_replay") is True or str(e.get("broadcast_phase") or "").upper() == "REPLAY":
            continue
        sp = e.get("score_pair")
        sp_l = list(sp) if isinstance(sp, (list, tuple)) else None
        # Fail-closed: shot already carrying the NEW score ⇒ post-goal live, not first-live goal action
        if after is not None and sp_l == after:
            continue
        pref = 0
        if before is not None and sp_l == before:
            pref = -50  # boost
        elif sp_l is None:
            pref = -10
        rows.append(
            {
                "event_id": e.get("event_id"),
                "event_time_sec": t,
                "score_pair": sp,
                "event_type": et,
                "media_start_sec": e.get("media_start_sec"),
                "media_end_sec": e.get("media_end_sec"),
                "_rank": pref + (float(confirm_sec) - t),  # prefer nearer confirm among same pref
            }
        )
    rows.sort(key=lambda r: float(r["_rank"]))
    return rows


def propose_first_live_windows(
    *,
    role: str,
    score_before: Optional[List[int]],
    score_after: List[int],
    prev_sec: float,
    confirm_sec: float,
    events: Sequence[Dict[str, Any]],
    existing_candidates: Sequence[Dict[str, Any]],
    video_duration_sec: float,
) -> Dict[str, Any]:
    """Rank first-live-oriented windows; reject post-score / score-order failures; search earlier."""
    conf = float(confirm_sec)
    prev = float(prev_sec)
    late_third_in = None
    for c in existing_candidates:
        if str(c.get("kind") or "").startswith("late_third") or str(c.get("candidate_id") or "").endswith("_late_third"):
            late_third_in = float(c["media_in"])
            break

    audited_existing = []
    for c in existing_candidates:
        mi, mo = float(c["media_in"]), float(c["media_out"])
        risk = classify_post_score_replay_risk(
            media_in=mi, media_out=mo, score_confirmation_sec=conf, kind=str(c.get("kind") or "")
        )
        # B-pattern: if late_third already shows new score at start, anything starting >= late_third_in is post-score risk
        if late_third_in is not None and mi >= late_third_in - 1.0 and risk.get("covers_confirm"):
            risk = dict(risk)
            risk["risk"] = True
            risk["label"] = "POST_SCORE_REPLAY_RISK_FROM_G21_LATE_THIRD_PATTERN"
        audited_existing.append(
            {
                "candidate_id": c.get("candidate_id"),
                "kind": c.get("kind"),
                "media_in": mi,
                "media_out": mo,
                "clip_path": c.get("clip_path"),
                "g21_post_score_audit": risk,
                "rejected_for_first_live_top1": bool(risk.get("risk")),
                "reason": risk.get("label"),
            }
        )

    # Neighborhood for timeline: prefer earlier than confirm
    neigh_in = max(0.0, min(prev, conf - 300.0))
    neigh_out = min(float(video_duration_sec), conf + 8.0)
    timeline = build_event_broadcast_timeline(events, media_in=neigh_in, media_out=neigh_out, step=5.0)
    replays = collect_event_replay_overlaps(events, media_in=neigh_in, media_out=neigh_out)

    shots = live_shots_before_confirm(
        events,
        prev_sec=max(prev, conf - 300.0),
        confirm_sec=conf,
        score_before=score_before,
        score_after=score_after,
    )
    near_shots = shots[:8]

    proposals: List[Dict[str, Any]] = []

    def _trim_at_replay(mi: float, mo: float, shot_t: float) -> Tuple[float, float, List[str]]:
        notes = []
        for r in replays:
            rs = float(r["start_time_sec"])
            if rs >= shot_t - 0.5:
                if rs < mo:
                    mo = min(mo, rs - 0.05)
                    notes.append(f"trim_out_at_replay_{r.get('event_id')}")
        return mi, mo, notes

    for s in near_shots:
        shot_t = float(s["event_time_sec"])
        hyp_net = min(shot_t + 4.0, conf)
        so = score_order_reject(hypothesized_net_sec=hyp_net, score_confirmation_sec=conf)
        if not so.get("ok"):
            proposals.append(
                {
                    "candidate_id": f"{role}_fl_shot_{s['event_id']}_score_order_reject",
                    "kind": "live_shot_score_order_rejected",
                    "rejected": True,
                    "score_order": so,
                    "shot_sec": shot_t,
                    "net_sec": hyp_net,
                    "reason": "rejected_score_order_anomaly",
                }
            )
            continue
        located = locate_continuous_live_goal_window(
            timeline=timeline, shot_sec=shot_t, result_sec=hyp_net
        )
        # Prefer event media span; use R2.5 locate only as bridgeability check, then clamp tightly.
        if s.get("media_start_sec") is not None and s.get("media_end_sec") is not None:
            mi = float(s["media_start_sec"])
            mo = float(s["media_end_sec"])
        else:
            mi, mo = max(0.0, shot_t - 8.0), min(conf, shot_t + 12.0)
        if located.get("ok"):
            # Intersect with located continuous non-replay span, then clamp to shot neighborhood
            mi = max(mi, float(located["media_in"]))
            mo = min(mo, float(located["media_out"]))
        # Hard clamp: first-live action window stays near the LIVE shot (not 3-minute expand)
        mi = max(mi, shot_t - 12.0)
        mo = min(mo, shot_t + 18.0, conf + 1.0)
        mi, mo, trim_notes = _trim_at_replay(mi, mo, shot_t)
        if mo - mi < 4.0:
            mi = max(0.0, shot_t - 8.0)
            mo = min(conf, shot_t + 10.0)
            mi, mo, trim_notes = _trim_at_replay(mi, mo, shot_t)
        risk = classify_post_score_replay_risk(
            media_in=mi, media_out=mo, score_confirmation_sec=conf, kind="first_live_shot"
        )
        if risk.get("risk") and mi >= conf - 3.0:
            proposals.append(
                {
                    "candidate_id": f"{role}_fl_shot_{s['event_id']}_post_score_reject",
                    "kind": "post_score_rejected",
                    "rejected": True,
                    "media_in": mi,
                    "media_out": mo,
                    "g21_post_score_audit": risk,
                    "reason": risk.get("label"),
                }
            )
            continue
        # Strong boost: continuous LIVE shot before confirm beats any confirm-anchored alt
        live_replay_trim = 1 if trim_notes else 0
        priority = -500.0 + float(s["_rank"]) - 50.0 * live_replay_trim
        proposals.append(
            {
                "candidate_id": f"{role}_first_live_shot_{s['event_id']}",
                "kind": "first_live_oriented_from_live_shot",
                "rejected": False,
                "media_in": round(mi, 3),
                "media_out": round(mo, 3),
                "shot_sec": shot_t,
                "net_sec": hyp_net,
                "shot_event_id": s.get("event_id"),
                "located_window": located,
                "score_order": so,
                "trim_notes": trim_notes,
                "g21_post_score_audit": classify_post_score_replay_risk(
                    media_in=mi, media_out=mo, score_confirmation_sec=conf, kind="first_live_shot"
                ),
                "priority": priority,
                "claims_continuous_live": True,
                "verification_status": "unresolved",
                "semantic_verification_class": NOT_VERIFIED,
                "note": (
                    "Zero-API proposal: LIVE Shot (score!=after) + R2.5 locate/trim at REPLAY; "
                    "shot/net hypothesized — NOT video-semantic verified"
                ),
            }
        )

    # Reuse earlier strip/scene candidates that are NOT post-score risk
    for a in audited_existing:
        if a.get("rejected_for_first_live_top1"):
            continue
        if float(a["media_out"]) > conf + 2:
            continue
        mi_a, mo_a = float(a["media_in"]), float(a["media_out"])
        # Reject windows that heavily overlap annotated REPLAY (not first-live)
        replay_overlap = 0.0
        for r in replays:
            rs, re_ = float(r["start_time_sec"]), float(r["end_time_sec"])
            ov = max(0.0, min(mo_a, re_) - max(mi_a, rs))
            replay_overlap += ov
        if replay_overlap >= 0.5 * (mo_a - mi_a) and (mo_a - mi_a) > 1.0:
            proposals.append(
                {
                    "candidate_id": f"{role}_reuse_{a['candidate_id']}_replay_overlap_reject",
                    "kind": "reused_candidate_replay_overlap_rejected",
                    "rejected": True,
                    "media_in": mi_a,
                    "media_out": mo_a,
                    "reason": "majority_overlap_annotated_replay",
                    "replay_overlap_sec": round(replay_overlap, 3),
                }
            )
            continue
        # Prefer windows ending just before late_third start (failed Top-1 package)
        if late_third_in is not None and mo_a <= late_third_in + 0.5:
            priority = 50.0 + abs(late_third_in - mo_a)
            if "scene" in str(a.get("kind") or ""):
                priority -= 15.0
            if "strip" in str(a.get("kind") or ""):
                priority -= 5.0
        else:
            priority = 80.0 + (conf - mo_a)
        proposals.append(
            {
                "candidate_id": f"{role}_reuse_{a['candidate_id']}",
                "kind": "reused_earlier_g2_candidate",
                "rejected": False,
                "media_in": mi_a,
                "media_out": mo_a,
                "source_candidate_id": a["candidate_id"],
                "clip_path_existing": a.get("clip_path"),
                "g21_post_score_audit": a.get("g21_post_score_audit"),
                "priority": priority,
                "claims_continuous_live": False,
                "verification_status": "unresolved",
                "semantic_verification_class": NOT_VERIFIED,
                "note": "Earlier G2 alternate; late_third demoted per G2.1; still unresolved",
            }
        )

    # Always emit earlier-search blocks when no LIVE-shot proposal survives
    accepted = [p for p in proposals if not p.get("rejected")]
    has_live_shot_prop = any(p.get("kind") == "first_live_oriented_from_live_shot" for p in accepted)
    needs_earlier = not has_live_shot_prop
    if needs_earlier:
        # Prefer stepping back from late_third start (board may already be new there)
        anchor = late_third_in if late_third_in is not None else conf
        cursor = float(anchor) - 5.0
        step_i = 0
        while cursor > prev + 15 and step_i < 5:
            mo = cursor
            mi = max(prev, mo - 35.0)
            if mo - mi >= 8.0:
                proposals.append(
                    {
                        "candidate_id": f"{role}_earlier_search_block_{step_i}",
                        "kind": "needs_earlier_search_block",
                        "rejected": False,
                        "media_in": round(mi, 3),
                        "media_out": round(mo, 3),
                        "priority": 120.0 + step_i * 10.0,
                        "claims_continuous_live": False,
                        "verification_status": "unresolved",
                        "semantic_verification_class": NOT_VERIFIED,
                        "note": "NEEDS_EARLIER_SEARCH block — human must confirm first-live action",
                        "label": "NEEDS_EARLIER_SEARCH",
                    }
                )
            cursor -= 40.0
            step_i += 1

    accepted = [p for p in proposals if not p.get("rejected")]
    accepted.sort(key=lambda p: float(p.get("priority") if p.get("priority") is not None else 1e9))
    topk = accepted[:5]
    top1 = topk[0] if topk else None

    return {
        "role": role,
        "score_before": score_before,
        "score_after": score_after,
        "score_confirmation_sec": conf,
        "previous_score_observation_sec": prev,
        "late_third_media_in": late_third_in,
        "audited_existing_candidates": audited_existing,
        "event_timeline_summary": {
            "n_live": timeline.get("n_live_slices"),
            "n_replay": timeline.get("n_replay_slices"),
            "n_unknown": timeline.get("n_unknown_slices"),
            "n_transition": timeline.get("n_transition_slices"),
        },
        "n_replay_overlaps": len(replays),
        "n_live_shots_before_confirm": len(shots),
        "proposals": proposals,
        "topk_first_live_oriented": topk,
        "top1": top1,
        "needs_earlier_search": needs_earlier or any(p.get("label") == "NEEDS_EARLIER_SEARCH" for p in topk),
        "n_video_verified": 0,
        "verification_status": "unresolved",
        "semantic_verification_class": NOT_VERIFIED,
        "render_ready": False,
    }


def materialize_first_live_pack(
    *,
    video: Path,
    role_result: Dict[str, Any],
    out_dir: Path,
    identity: Dict[str, str],
    video_duration_sec: float,
    max_export: int = 3,
) -> Dict[str, Any]:
    role = role_result["role"]
    role_dir = out_dir / "roles" / role
    clips_dir = role_dir / "clips"
    frames_dir = role_dir / "frames"
    clips_dir.mkdir(parents=True, exist_ok=True)
    frames_dir.mkdir(parents=True, exist_ok=True)
    exported = []
    for p in (role_result.get("topk_first_live_oriented") or [])[:max_export]:
        if p.get("rejected"):
            continue
        # Reuse existing clip if present and same window (±1s)
        existing = p.get("clip_path_existing")
        mi, mo = float(p["media_in"]), float(p["media_out"])
        mi = max(0.0, min(mi, video_duration_sec - 1))
        mo = max(mi + 0.5, min(mo, video_duration_sec))
        if mo - mi > 40:
            mo = mi + 40.0
        cid = str(p["candidate_id"])
        out_clip = clips_dir / f"{cid}_clip_source_continuous.mp4"
        if existing and Path(existing).is_file() and abs(float(p.get("media_in", 0)) - mi) < 1.5:
            # copy reference only in metadata; still cut for consistency of naming
            pass
        cut = _cut_continuous_clip(video=video, media_in=mi, media_out=mo, out_mp4=out_clip)
        frames = []
        for j, ft in enumerate([mi + 1.0, 0.5 * (mi + mo), max(mi + 1.0, mo - 1.5)]):
            fp = frames_dir / f"{cid}_f{j}_{int(ft*1000)}.jpg"
            frames.append(_extract_frame(video=video, media_sec=ft, out_jpg=fp))
        exported.append(
            {
                **p,
                "clip_path": cut.get("path") if cut.get("ok") else None,
                "clip_export": cut,
                "frames": frames,
                "frame_paths": [f["path"] for f in frames if f.get("ok")],
                "identity": dict(identity),
                "live_or_replay": "unknown",  # event-based only; not dense VLM live proof
                "human_review_status": "pending_human_video_review",
                "verification_status": "unresolved",
                "semantic_verification_class": NOT_VERIFIED,
                "checklist": {
                    "shot_action_seen": "pending_human",
                    "ball_in_net_seen": "pending_human",
                    "first_live_not_replay": "pending_human",
                    "score_order_net_before_or_at_confirm": not bool(
                        (p.get("score_order") or {}).get("score_order_anomaly")
                    ),
                    "continuous_clip_no_stitch": bool(cut.get("ok")),
                },
                "render_ready": False,
            }
        )
    top1 = exported[0] if exported else None
    return {
        "role": role,
        "score_before": role_result.get("score_before"),
        "score_after": role_result.get("score_after"),
        "score_confirmation_sec": role_result.get("score_confirmation_sec"),
        "audited_existing_candidates": role_result.get("audited_existing_candidates"),
        "needs_earlier_search": role_result.get("needs_earlier_search"),
        "n_exported": len(exported),
        "top1": top1,
        "exported": exported,
        "verification_status": "unresolved",
        "n_video_verified": 0,
        "semantic_verification_class": NOT_VERIFIED,
        "render_ready": False,
    }


def append_g21_judgment_to_role_evidence(
    *,
    g2_role_evidence_path: Path,
    judgment: str,
    candidate_id: str = "",
) -> Dict[str, Any]:
    """Append G2.1 human Top-1 judgment without overwriting historical candidate records."""
    path = Path(g2_role_evidence_path)
    if not path.is_file():
        return {"ok": False, "reason": "missing_role_evidence"}
    data = json.loads(path.read_text(encoding="utf-8"))
    appendix = data.get("g21_human_review_appendix")
    if not isinstance(appendix, list):
        appendix = []
    entry = {
        "source": "STORY_VA_V2_G2_1_ACTUAL_VIDEO_REVIEW_G2_2_ACTIONS.md",
        "top1_candidate_id": candidate_id or data.get("primary_candidate_id"),
        "judgment": judgment,
        "appended_at_schema": "v2_g21_judgment_appendix_v1",
        "note": "Append-only; does not overwrite candidate checklist history",
        "render_ready": False,
    }
    # idempotent: skip if same judgment already present for same candidate
    if not any(
        a.get("judgment") == judgment and a.get("top1_candidate_id") == entry["top1_candidate_id"]
        for a in appendix
    ):
        appendix.append(entry)
    data["g21_human_review_appendix"] = appendix
    # Also annotate the matching candidate checklist without replacing prior keys
    cid = entry["top1_candidate_id"]
    for c in data.get("candidates") or []:
        if c.get("candidate_id") == cid:
            chk = c.get("checklist")
            if not isinstance(chk, dict):
                chk = {}
            if "g21_human_judgment" not in chk:
                chk["g21_human_judgment"] = judgment
                chk["g21_judgment_note"] = "appended_not_overwrite"
            c["checklist"] = chk
            # demote primary pointer metadata only via appendix flag
            c["g21_rejected_as_first_live_top1"] = judgment in {
                "POST_SCORE_REPLAY",
                "GOAL_ACTION_NOT_IN_WINDOW",
                "REPLAY_SUSPECTED_FIRST_LIVE_UNRESOLVED",
            } or "POST_SCORE" in judgment or "NOT_IN_WINDOW" in judgment
            break
    write_json(path, data)
    return {"ok": True, "path": str(path), "appendix_n": len(appendix)}


def run_g22_first_live(
    *,
    match_id: str,
    match_tag: str,
    video: Path,
    events: Path,
    g1_dir: Path,
    g2_dir: Path,
    out_dir: Path,
    input_source: str = "human_corrected",
) -> Dict[str, Any]:
    t0 = time.time()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    gate = reject_forbidden_input_path(Path(events))
    if not gate.get("ok"):
        report = {"status": "aborted_forbidden_input", "gate": gate, "render_ready": False}
        write_json(out_dir / "cli_report.json", report)
        return report
    raw = json.loads(Path(events).read_text(encoding="utf-8"))
    pg = reject_forbidden_payload(raw if isinstance(raw, dict) else {})
    if not pg.get("ok"):
        report = {"status": "aborted_forbidden_payload", "gate": pg, "render_ready": False}
        write_json(out_dir / "cli_report.json", report)
        return report
    mid = assert_match_id_consistent(cli_match_id=match_id, events_match_id=str(raw.get("match_id") or ""))
    if not mid.get("ok"):
        report = {"status": "aborted_match_id_mismatch", "gate": mid, "render_ready": False}
        write_json(out_dir / "cli_report.json", report)
        return report

    g1_prov = json.loads((Path(g1_dir) / "provenance.json").read_text(encoding="utf-8"))
    selected = json.loads((Path(g1_dir) / "selected_arc.json").read_text(encoding="utf-8")).get("selected_arc") or {}
    events_sha = sha256_file(Path(events))
    video_sha = str(g1_prov.get("video_sha256") or "")
    if not video_sha:
        video_sha = sha256_file(Path(video))
    strip_token = ""
    sp = g1_prov.get("strip_provenance")
    if isinstance(sp, dict):
        strip_token = str(sp.get("strip_provenance") or "")
    else:
        strip_token = str(sp or "")
    identity = {
        "match_id": match_id,
        "video_sha256": video_sha,
        "events_sha256": events_sha,
        "strip_provenance": strip_token,
    }
    write_json(out_dir / "preflight_identity.json", {"identity": identity, "render_ready": False})

    bundle = load_events_json(Path(events), input_source=input_source)
    evs = list(bundle.get("events") or [])
    video_duration = _ffprobe_duration(Path(video))

    conf = selected.get("score_confirmation_sec") or {}
    roles_spec = [
        (
            "opening_deficit",
            selected.get("deficit_score"),
            conf.get("deficit"),
            # prev: earliest prior board time before deficit confirm
            None,
        ),
        (
            "equalizer",
            selected.get("equalizer_score"),
            conf.get("equalizer"),
            conf.get("deficit"),
        ),
        (
            "go_ahead",
            selected.get("go_ahead_score"),
            conf.get("go_ahead"),
            conf.get("equalizer"),
        ),
    ]
    # Fill opening prev from score_path if available
    spath = json.loads((Path(g1_dir) / "score_path.json").read_text(encoding="utf-8")).get("timeline") or []
    if roles_spec[0][2] is not None and spath:
        # time of board before deficit score
        deficit = list(selected.get("deficit_score") or [])
        prev_t = None
        prev_board = None
        for row in spath:
            sc = list(row.get("score") or [])
            if sc == deficit:
                break
            prev_board = sc
            prev_t = row.get("media_start_sec")
        roles_spec[0] = (
            "opening_deficit",
            deficit,
            conf.get("deficit"),
            prev_t if prev_t is not None else max(0.0, float(conf.get("deficit") or 0) - 180.0),
        )
        opening_before = prev_board
    else:
        opening_before = [0, 0]

    role_packs = []
    index_rows = []
    checklist_updates = []

    for role, after, ct, prev in roles_spec:
        if ct is None or not after:
            continue
        before = (
            opening_before
            if role == "opening_deficit"
            else (
                list(selected.get("deficit_score") or [])
                if role == "equalizer"
                else list(selected.get("equalizer_score") or [])
            )
        )
        # Load G2 existing candidates
        g2_role = Path(g2_dir) / "roles" / role / "role_evidence.json"
        existing = []
        if g2_role.is_file():
            existing = list(json.loads(g2_role.read_text(encoding="utf-8")).get("candidates") or [])

        human = G21_HUMAN_TOP1.get((match_tag, role))
        if human and g2_role.is_file():
            append_g21_judgment_to_role_evidence(
                g2_role_evidence_path=g2_role,
                judgment=human,
                candidate_id=f"{role}_late_third",
            )
        checklist_updates.append(
            {
                "match_tag": match_tag,
                "role": role,
                "g21_human_top1_judgment": human,
                "g21_top1_candidate": f"{role}_late_third",
                "note": "Appended judgment; historical G2 records not overwritten",
            }
        )

        prev_sec = float(prev) if prev is not None else max(0.0, float(ct) - 180.0)
        proposed = propose_first_live_windows(
            role=role,
            score_before=before,
            score_after=list(after),
            prev_sec=prev_sec,
            confirm_sec=float(ct),
            events=evs,
            existing_candidates=existing,
            video_duration_sec=video_duration,
        )
        write_json(out_dir / "roles" / role / "first_live_search.json", proposed)
        pack = materialize_first_live_pack(
            video=Path(video),
            role_result=proposed,
            out_dir=out_dir,
            identity=identity,
            video_duration_sec=video_duration,
        )
        pack["g21_human_top1_judgment"] = human
        write_json(out_dir / "roles" / role / "role_first_live_pack.json", pack)
        role_packs.append(pack)
        if pack.get("top1") and pack["top1"].get("clip_path"):
            index_rows.append(
                {
                    "role": role,
                    "candidate_id": pack["top1"]["candidate_id"],
                    "kind": pack["top1"].get("kind"),
                    "media_in": pack["top1"].get("media_in"),
                    "media_out": pack["top1"].get("media_out"),
                    "shot_sec": pack["top1"].get("shot_sec"),
                    "net_sec": pack["top1"].get("net_sec"),
                    "clip_path": pack["top1"].get("clip_path"),
                    "g21_human_top1_judgment": human,
                    "needs_earlier_search": pack.get("needs_earlier_search"),
                    "verification_status": "unresolved",
                    "watchable": True,
                }
            )

    live_audit = {
        "schema": "v2_g22_live_replay_audit_summary_v1",
        "reused_modules": [
            "v2_strip_guided_r2_5_live_only.locate_continuous_live_goal_window",
            "v2_goal_live_replay_audit.audit_inferred_goal (score_order_anomaly)",
            "event-based broadcast timeline mirroring R2.5 phase schema",
        ],
        "new_generic": [
            "classify_post_score_replay_risk (G2.1 human pattern)",
            "zero-API event timeline builder",
            "first-live ranking: reject confirm-anchored late_third; prefer earlier LIVE shot windows",
            "NEEDS_EARLIER_SEARCH blocks",
        ],
        "roles": role_packs,
        "g21_top1_judgments_appended": checklist_updates,
        "render_ready": False,
    }
    write_json(out_dir / "live_replay_audit.json", live_audit)
    write_json(
        out_dir / "candidate_evidence_index.json",
        {"schema": "v2_g22_first_live_index_v1", "rows": index_rows, "render_ready": False},
    )
    write_json(out_dir / "g21_top1_judgment_appendix.json", {"items": checklist_updates, "render_ready": False})

    semantic = {
        "schema": "v2_g22_video_semantic_verification_v1",
        "status": NOT_VERIFIED,
        "n_video_verified": 0,
        "note": "G2.2 proposes first-live-oriented windows only; no paid VLM dense live proof executed",
        "render_ready": False,
    }
    write_json(out_dir / "video_semantic_verification.json", semantic)

    # Top-1/K hit metrics (proxy: whether top1 is not post-score reject and has earlier window)
    metrics = []
    for pack in role_packs:
        top1 = pack.get("top1") or {}
        risk = (top1.get("g21_post_score_audit") or {}).get("risk")
        metrics.append(
            {
                "role": pack["role"],
                "top1_kind": top1.get("kind"),
                "top1_is_late_third": "late_third" in str(top1.get("kind") or ""),
                "top1_post_score_risk": bool(risk),
                "top1_has_shot_hypothesis": top1.get("shot_sec") is not None,
                "needs_earlier_search": pack.get("needs_earlier_search"),
                "g21_human_top1": pack.get("g21_human_top1_judgment"),
                "claimed_first_live_verified": False,
            }
        )

    report = {
        "schema": "v2_g22_cli_report_v1",
        "status": "ok_first_live_retrieval_pack",
        "match_id": match_id,
        "match_tag": match_tag,
        "protagonist_side": selected.get("protagonist_side"),
        "n_roles": len(role_packs),
        "n_watchable_top_clips": len(index_rows),
        "n_video_verified": 0,
        "metrics": metrics,
        "elapsed_sec": round(time.time() - t0, 3),
        "api_calls": 0,
        "api_cost_usd": 0.0,
        "render_ready": False,
        "note": (
            "First-live-oriented candidates exported; Top-1 late_third post-score pattern rejected. "
            "Still unresolved until human/VLM semantic verification."
        ),
    }
    write_json(out_dir / "cli_report.json", report)
    return report
