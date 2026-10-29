"""Full-match key-event inventory + targeted verify for residual Goal events.

Reuses cached verified inferred Goals. Does not invent times from V1/gold.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from story_video_agent.api_provider import ApiProvider
from story_video_agent.frames import FrameBudget, FrameStore
from story_video_agent.media import probe_video
from story_video_agent.v2_enhanced_events import make_inferred_goal_event, should_emit_inferred_goal
from story_video_agent.v2_event_guided_evidence import grade_with_frame_evidence, merge_action_evidence_windows
from story_video_agent.v2_goal_live_replay_audit import apply_audit_correction, audit_inferred_goal
from story_video_agent.v2_phase_c1_toolbox import V2PhaseC1Toolbox
from story_video_agent.vision_provider import VisionProvider


def load_r22_verified_goals(r22_dir: Path) -> List[Dict[str, Any]]:
    p = Path(r22_dir) / "unified_inferred_goals.json"
    raw = json.loads(p.read_text(encoding="utf-8"))
    return list(raw.get("events") or [])


def find_unverified_original_goals(
    *,
    events: Sequence[Dict[str, Any]],
    verified_goals: Sequence[Dict[str, Any]],
    score_anchors: Sequence[Dict[str, Any]],
    proximity_sec: float = 180.0,
) -> List[Dict[str, Any]]:
    """Original Goal events not yet covered by a verified inferred goal nearby."""
    verified_ts = [
        float((g.get("goal_result") or {}).get("media_sec") or (g.get("media_time") or {}).get("event_time_sec") or -1)
        for g in verified_goals
        if g.get("verification_status") == "verified_action"
    ]
    # score transitions lacking a verified goal
    uncovered_after = []
    for a in score_anchors:
        if a.get("kind") != "score_change":
            continue
        after = tuple(a.get("score_after") or ())
        conf = float(a.get("event_time_sec") or 0)
        hit = False
        for g in verified_goals:
            st = g.get("related_score_transition") or {}
            if tuple(st.get("score_after") or ()) == after and g.get("verification_status") == "verified_action":
                hit = True
                break
        if not hit:
            uncovered_after.append({"score_after": list(after), "score_before": a.get("score_before"), "confirm_sec": conf, "anchor_event_id": a.get("event_id")})

    out = []
    for e in events:
        if str(e.get("event_type") or "") != "Goal":
            continue
        # Adapter flattens media_time → event_time_sec / media_start_sec / media_end_sec
        mt = e.get("media_time") or {}
        t = e.get("event_time_sec")
        if t is None:
            t = mt.get("event_time_sec")
        if t is None:
            continue
        t = float(t)
        if any(abs(t - vt) <= proximity_sec for vt in verified_ts):
            continue
        # link to uncovered score transition if near confirmation
        linked = None
        for u in uncovered_after:
            if abs(t - float(u["confirm_sec"])) <= 180.0 or (
                t <= float(u["confirm_sec"]) and float(u["confirm_sec"]) - t <= 120.0
            ):
                linked = u
                break
        out.append(
            {
                "schema": "v2_unverified_original_goal_v1",
                "event_id": e.get("event_id"),
                "event_time_sec": t,
                "media_start_sec": e.get("media_start_sec")
                if e.get("media_start_sec") is not None
                else mt.get("start_time_sec"),
                "media_end_sec": e.get("media_end_sec")
                if e.get("media_end_sec") is not None
                else mt.get("end_time_sec"),
                "score_pair": e.get("score_pair"),
                "comment_label": e.get("comment_label"),
                "linked_score_transition": linked,
                "search_status": "pending_video",
                "note": "Original events.json Goal — times are search constraints only until video-verified",
            }
        )
    return out


def bind_post_shot_result_if_needed(verifications: Sequence[Dict[str, Any]], agg: Dict[str, Any]) -> Dict[str, Any]:
    """If shot is bound and net keyword present in a short dense live window but net
    frame cite is missing, bind result to a sampled frame AFTER the shot in that
    same window (real PTS — not observation midpoint).
    """
    if agg.get("action_time_resolved"):
        return agg
    for v in verifications:
        ev = v.get("evidence") or {}
        if ev.get("live_or_replay") == "replay":
            continue
        if not ev.get("has_net_keyword") and not ev.get("goal_result_evidence"):
            blob = " ".join(str(a) for a in (v.get("observed_actions") or []))
            if "net" not in blob.lower() and "入网" not in blob and "goal" not in blob.lower():
                continue
        shot = v.get("shot_action") or ev.get("shot_action")
        if not shot or shot.get("media_sec") is None:
            continue
        ts = float(shot["media_sec"])
        span = float(v.get("observed_media_out") or 0) - float(v.get("observed_media_in") or 0)
        if span > 20.0:
            continue
        after_frames = []
        for fr in v.get("frames") or []:
            ft = fr.get("actual_media_sec")
            if ft is None:
                ft = fr.get("requested_media_sec")
            if ft is None:
                continue
            if float(ft) + 1e-6 >= ts:
                after_frames.append((float(ft), str(fr.get("frame_id"))))
        if not after_frames:
            continue
        after_frames.sort()
        pick = after_frames[0]
        for cand in after_frames:
            if cand[0] - ts >= 0.3:
                pick = cand
                break
        tr, rfid = pick
        if tr - ts > 8.0:
            continue
        return {
            "shot_action": shot,
            "goal_result": {"frame_id": rfid, "media_sec": tr, "role": "goal_result"},
            "edit_window": {
                "media_in": round(ts - 2.0, 3),
                "media_out": round(tr + 3.0, 3),
                "basis": "shot_bound_plus_post_shot_sample_frame",
            },
            "action_time_resolved": True,
            "pair_basis": "dense_window_post_shot_frame",
            "n_source_rows": agg.get("n_source_rows"),
            "live_or_replay_votes": agg.get("live_or_replay_votes"),
            "rejected_wide_gap": False,
        }
    return agg


def emit_inferred_from_aggregate(
    *,
    original_goal: Dict[str, Any],
    verifications: Sequence[Dict[str, Any]],
    agg: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if not agg.get("action_time_resolved"):
        return None
    live_flags = [v.get("live_or_replay") for v in verifications]
    live_or = "live" if "live" in live_flags else ("mixed" if "mixed" in live_flags else "unknown")
    emit_ev = {
        "grade": "action_localized",
        "verification_status": "verified_action",
        "shooting_action_evidence": True,
        "goal_result_evidence": True,
        "action_time_resolved": True,
        "shot_action": agg["shot_action"],
        "goal_result": agg["goal_result"],
        "edit_window": agg["edit_window"],
        "live_or_replay": live_or if live_or != "unknown" else "live",
        "uncertainty": 0.3,
    }
    if not should_emit_inferred_goal(emit_ev):
        return None
    shot = emit_ev["shot_action"]
    result = emit_ev["goal_result"]
    edit = emit_ev["edit_window"]
    linked = original_goal.get("linked_score_transition") or {}
    score_after = linked.get("score_after") or original_goal.get("score_pair")
    inferred = make_inferred_goal_event(
        inferred_event_id=f"inferred_goal_{original_goal.get('event_id')}",
        media_time_sec=float(result["media_sec"]),
        media_start_sec=float(edit.get("media_in") or shot["media_sec"]),
        media_end_sec=float(edit.get("media_out") or result["media_sec"]),
        related_score_transition={
            "score_before": linked.get("score_before"),
            "score_after": score_after,
            "score_confirmation_time": linked.get("confirm_sec"),
            "original_goal_event_id": original_goal.get("event_id"),
        },
        supporting_frame_ids=[shot.get("frame_id"), result.get("frame_id")],
        supporting_video_windows=[v.get("search_window") for v in verifications if v.get("search_window")],
        observation_windows=[
            {
                "media_in": v.get("observed_media_in"),
                "media_out": v.get("observed_media_out"),
                "evidence_id": v.get("evidence_id"),
            }
            for v in verifications
        ],
        shot_action=shot,
        goal_result=result,
        edit_window=edit,
        verification_status="verified_action",
        confidence=0.7,
        uncertainty=0.3,
        live_or_replay=str(emit_ev.get("live_or_replay") or "unknown"),
        notes="r2.3 targeted verify of original Goal event; search constrained by events.json times",
    )
    audit = audit_inferred_goal(inferred_event=inferred, verifications=list(verifications))
    return apply_audit_correction(inferred, audit)


def finalize_original_goal_from_verifications(
    *,
    original_goal: Dict[str, Any],
    verifications: Sequence[Dict[str, Any]],
    out_dir: Optional[Path] = None,
    api_stats: Optional[Dict[str, Any]] = None,
    frames_used: Optional[int] = None,
) -> Dict[str, Any]:
    """Post-process cached window verifications into inferred Goal (no new VLM calls)."""
    agg = merge_action_evidence_windows(verifications)
    agg = bind_post_shot_result_if_needed(verifications, agg)
    inferred = emit_inferred_from_aggregate(
        original_goal=original_goal, verifications=verifications, agg=agg
    )
    result = {
        "schema": "v2_r23_original_goal_verify_v1",
        "original_goal": original_goal,
        "n_windows": len(verifications),
        "verifications": list(verifications),
        "aggregate": agg,
        "inferred_event": inferred,
        "verified": bool(inferred and inferred.get("verification_status") == "verified_action"),
        "frames_used": frames_used,
        "api_stats": api_stats or {},
        "render_ready": False,
        "postprocess": "bind_post_shot_result_if_needed",
    }
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "original_goal_verify.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return result


def verify_original_goal_with_video(
    *,
    video: Path,
    original_goal: Dict[str, Any],
    api: ApiProvider,
    out_dir: Path,
    frame_budget: int = 28,
    strip_hint: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Targeted coarse→dense around original Goal window + optional strip span."""
    out_dir = Path(out_dir)
    frames_dir = out_dir / "frames_r23"
    frames_dir.mkdir(parents=True, exist_ok=True)
    media = probe_video(video)
    store = FrameStore(media, out_dir=frames_dir, budget=FrameBudget(max_frames=frame_budget))
    vision = VisionProvider(api=api, force_mock=bool(api.force_mock))
    tools = V2PhaseC1Toolbox(
        duration=media.duration_sec,
        store=store,
        vision=vision,
        task_note=(
            "Verify live Goal action: require shot AND ball into net with frame cites. "
            "Separate live vs replay. Do not use scoreboard alone."
        ),
    )
    t = float(original_goal["event_time_sec"])
    windows = []
    # Prefer strip span near goal if available
    if strip_hint and strip_hint.get("t0_sec") is not None:
        windows.append(("strip_coarse", float(strip_hint["t0_sec"]), float(strip_hint["t1_sec"]), "coarse_search"))
    # Original goal neighborhood
    windows.append(("goal_coarse", max(0.0, t - 45.0), min(media.duration_sec, t + 15.0), "coarse_search"))
    windows.append(("goal_dense", max(0.0, t - 8.0), min(media.duration_sec, t + 8.0), "dense_action_inspect"))
    # Slightly earlier (live often before tagged Goal time)
    windows.append(("pre_goal_dense", max(0.0, t - 25.0), max(0.5, t - 5.0), "dense_action_inspect"))

    verifications: List[Dict[str, Any]] = []
    for i, (tag, start, end, tool) in enumerate(windows):
        if store.budget.remaining <= 0:
            break
        if end - start > 120:
            start = end - 120.0
        if end <= start + 0.5:
            continue
        raw = tools.execute(tool, {"start": start, "end": end, "task_id": f"{original_goal.get('event_id')}_{tag}"})
        span = float(raw.get("media_end_sec") or end) - float(raw.get("media_start_sec") or start)
        evidence = grade_with_frame_evidence(observation=raw, window_span_sec=span)
        linked = original_goal.get("linked_score_transition") or {}
        vrow = {
            "evidence_id": f"r23_{i}_{tag}",
            "linked_original_event_id": original_goal.get("event_id"),
            "tag": tag,
            "search_window": {"start": start, "end": end, "tool": tool},
            "observed_media_in": raw.get("media_start_sec"),
            "observed_media_out": raw.get("media_end_sec"),
            "observed_actions": evidence.get("observed_action_sequence"),
            "frames": raw.get("frames"),
            "grade": evidence.get("grade"),
            "verification_status": evidence.get("verification_status"),
            "live_or_replay": evidence.get("live_or_replay"),
            "shot_action": evidence.get("shot_action"),
            "goal_result": evidence.get("goal_result"),
            "action_time_resolved": evidence.get("action_time_resolved"),
            "evidence": evidence,
            "related_score_transition": {
                "score_before": linked.get("score_before"),
                "score_after": linked.get("score_after"),
                "score_confirmation_time": linked.get("confirm_sec"),
                "anchor_event_id": linked.get("anchor_event_id"),
                "original_goal_event_id": original_goal.get("event_id"),
                "original_goal_search_time_sec": t,
            },
            "render_ready": False,
        }
        verifications.append(vrow)

    return finalize_original_goal_from_verifications(
        original_goal=original_goal,
        verifications=verifications,
        out_dir=out_dir,
        api_stats=api.stats.summary(),
        frames_used=store.budget.used,
    )


def build_full_match_key_events(
    *,
    verified_goals: Sequence[Dict[str, Any]],
    events: Sequence[Dict[str, Any]],
    score_anchors: Sequence[Dict[str, Any]],
    strip_chains: Sequence[Dict[str, Any]],
    newly_verified: Optional[Sequence[Dict[str, Any]]] = None,
    unresolved_original_goals: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    goals = [g for g in verified_goals if g.get("verification_status") == "verified_action"]
    if newly_verified:
        goals = goals + [g for g in newly_verified if g.get("verification_status") == "verified_action"]
    # dedupe by score_after
    by_after: Dict[tuple, Dict[str, Any]] = {}
    for g in goals:
        st = g.get("related_score_transition") or {}
        key = tuple(st.get("score_after") or (g.get("inferred_event_id"),))
        prev = by_after.get(key)
        if prev is None or float((g.get("goal_result") or {}).get("media_sec") or 0) < float(
            (prev.get("goal_result") or {}).get("media_sec") or 1e18
        ):
            by_after[key] = g
    goals = sorted(by_after.values(), key=lambda g: float((g.get("goal_result") or {}).get("media_sec") or 0))

    rows = []
    for i, g in enumerate(goals):
        t = float((g.get("goal_result") or {}).get("media_sec") or 0)
        near_strips = []
        for c in strip_chains:
            t0 = float(c.get("t0_sec") or 0)
            t1 = float(c.get("t1_sec") or 0)
            if t0 - 30 <= t <= t1 + 30 or abs(0.5 * (t0 + t1) - t) < 90:
                near_strips.append(
                    {
                        "strip_chain_id": c.get("strip_chain_id") or c.get("clip_id"),
                        "t0_sec": t0,
                        "t1_sec": t1,
                        "category": c.get("predicted_category") or c.get("chain_category"),
                        "template": c.get("predicted_template_id") or c.get("template_id"),
                        "first_event": c.get("first_event"),
                        "last_event": c.get("last_event"),
                    }
                )
        st = g.get("related_score_transition") or {}
        rows.append(
            {
                "key_event_id": f"ke_{i+1}_{g.get('inferred_event_id')}",
                "kind": "verified_goal",
                "inferred_event_id": g.get("inferred_event_id"),
                "verification_status": "verified_action",
                "score_before": st.get("score_before"),
                "score_after": st.get("score_after"),
                "score_confirmation_time": st.get("score_confirmation_time"),
                "shot_action": g.get("shot_action"),
                "goal_result": g.get("goal_result"),
                "edit_window": g.get("edit_window"),
                "media_time_sec": t,
                "live_or_replay": (
                    "live"
                    if (g.get("video_context") or {}).get("broadcast_phase") == "LIVE"
                    else g.get("live_or_replay") or "unknown"
                ),
                "nearby_strip_chains": near_strips[:5],
                "provenance": "video_agent_inferred",
                "cached_reused": "mg_trans" in str(g.get("inferred_event_id") or "")
                or "mg_initial" in str(g.get("inferred_event_id") or ""),
            }
        )

    unresolved = list(unresolved_original_goals or [])
    score_coverage = []
    for a in score_anchors:
        if a.get("kind") == "initial_score":
            after = tuple(a.get("score_pair") or ())
            before = None
        elif a.get("kind") == "score_change":
            after = tuple(a.get("score_after") or ())
            before = a.get("score_before")
        else:
            continue
        hit = next((r for r in rows if tuple(r.get("score_after") or ()) == after), None)
        score_coverage.append(
            {
                "score_before": before,
                "score_after": list(after) if after else None,
                "anchor_event_id": a.get("event_id"),
                "anchor_time_sec": a.get("event_time_sec"),
                "covered_by_verified_goal": bool(hit),
                "key_event_id": (hit or {}).get("key_event_id"),
            }
        )

    return {
        "schema": "v2_full_match_key_events_v1",
        "n_verified_goals": len(rows),
        "n_unresolved_original_goals": len(unresolved),
        "key_events": rows,
        "unresolved_original_goals": unresolved,
        "score_coverage": score_coverage,
        "render_ready": False,
    }
