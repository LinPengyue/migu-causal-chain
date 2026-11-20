"""Audit the rendered story MP4 visually — do not trust EDL/PTS alone."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from story_video_agent.frames import FrameBudget, FrameStore
from story_video_agent.media import probe_video
from story_video_agent.v2_phase_c1_toolbox import V2PhaseC1Toolbox
from story_video_agent.v2_strip_guided_r2_5_live_only import (
    _NET,
    _SHOT,
    _blob_from_raw,
    classify_live_replay,
)
from story_video_agent.vision_provider import VisionProvider

_PHASE = {
    "pre_shot": re.compile(r"(approach|dribble|build[- ]?up|带球|推进|准备射|before the shot)", re.I),
    "shot": _SHOT,
    "net": _NET,
    "celebrate": re.compile(r"(celebrat|欢呼|庆祝|拥抱|arms?\s+raised)", re.I),
}


def _playback_map_from_edl(edl: Dict[str, Any]) -> List[Dict[str, Any]]:
    play_t = 0.0
    rows: List[Dict[str, Any]] = []
    for s in edl.get("segments") or []:
        dur = float(s.get("duration_sec") or 0)
        if s.get("role") == "goal":
            rows.append(
                {
                    "key_event_id": (s.get("source_node_ids") or [None])[0],
                    "source_media_in": s.get("media_in"),
                    "source_media_out": s.get("media_out"),
                    "shot_sec": s.get("shot_sec"),
                    "result_sec": s.get("result_sec"),
                    "story_play_in": round(play_t, 3),
                    "story_play_out": round(play_t + dur, 3),
                    "live_or_replay_edl": s.get("live_or_replay"),
                }
            )
        play_t += dur
    return rows


def audit_final_mp4_goals(
    *,
    story_mp4: Path,
    edl: Dict[str, Any],
    goal_audits: Sequence[Dict[str, Any]],
    vision: VisionProvider,
    frames_dir: Path,
    max_frames: int = 48,
) -> Dict[str, Any]:
    """Observe each goal's playback interval in the rendered MP4."""
    story_mp4 = Path(story_mp4)
    media = probe_video(story_mp4)
    store = FrameStore(media, out_dir=frames_dir, budget=FrameBudget(max_frames=max_frames))
    tools = V2PhaseC1Toolbox(
        duration=media.duration_sec,
        store=store,
        vision=vision,
        task_note=(
            "FINAL STORY MP4 AUDIT. Describe ONLY what is visible in these story frames. "
            "Say explicitly if this looks like live match play vs 回放/slow-mo replay. "
            "Do NOT use 直播 corner badge alone as proof of live action. "
            "Report whether pre-shot approach, shot/strike, ball into net, and celebration appear. "
            "Do not invent actions."
        ),
    )
    playback = _playback_map_from_edl(edl)
    by_id = {g.get("key_event_id"): g for g in goal_audits}
    goals_out: List[Dict[str, Any]] = []

    for row in playback:
        kid = row["key_event_id"]
        g = by_id.get(kid) or {}
        pin, pout = float(row["story_play_in"]), float(row["story_play_out"])
        # Sample early / mid / late thirds inside the goal clip
        span = max(0.8, pout - pin)
        probes = [
            ("pre_or_early", pin + min(1.0, span * 0.15), pin + min(3.5, span * 0.35)),
            ("mid_action", pin + span * 0.35, pin + span * 0.7),
            ("late_result", pin + span * 0.65, pout - 0.05),
        ]
        phase_hits = {"pre_shot": False, "shot": False, "net": False, "celebrate": False}
        observations: List[Dict[str, Any]] = []
        statuses: List[str] = []
        for name, a, b in probes:
            if b <= a + 0.4:
                b = a + 0.6
            a = max(0.0, min(a, media.duration_sec - 0.5))
            b = max(a + 0.5, min(b, media.duration_sec))
            try:
                # Prefer verify_live_replay (fewer frames) then dense if needed.
                raw = tools.execute(
                    "verify_live_replay",
                    {"start": a, "end": min(b, a + 6.0), "task_id": f"final_{kid}_{name}"},
                )
                if raw.get("error") or not _blob_from_raw(raw).strip():
                    raw = tools.execute(
                        "dense_action_inspect",
                        {"start": a, "end": b, "task_id": f"final_{kid}_{name}_dense"},
                    )
            except Exception as exc:  # noqa: BLE001
                observations.append({"probe": name, "error": str(exc)})
                statuses.append("unknown")
                continue
            if raw.get("error"):
                observations.append(
                    {
                        "probe": name,
                        "error": raw.get("error"),
                        "message": raw.get("message"),
                        "story_play_in": round(a, 3),
                        "story_play_out": round(b, 3),
                    }
                )
                statuses.append("unknown")
                continue
            lr = classify_live_replay(raw)
            blob = _blob_from_raw(raw)
            probe_phases = {pk: bool(rx.search(blob)) for pk, rx in _PHASE.items()}
            for pk, hit in probe_phases.items():
                if hit:
                    phase_hits[pk] = True
            # Do NOT upgrade mixed→live for late celebration; mixed fails acceptance.
            status = lr["live_or_replay"]
            statuses.append(status)
            observations.append(
                {
                    "probe": name,
                    "story_play_in": round(a, 3),
                    "story_play_out": round(b, 3),
                    "live_or_replay": status,
                    "classifier_raw": lr["live_or_replay"],
                    "badge_alone": lr.get("badge_alone_not_sufficient"),
                    "blob_excerpt": lr.get("blob_excerpt", "")[:350],
                    "observed_actions": lr.get("observed_actions") or [],
                    "probe_phases": probe_phases,
                }
            )

        fail: List[str] = []
        strong_replay = any(s == "replay" for s in statuses)
        has_mixed = any(s == "mixed_or_ambiguous" for s in statuses)
        has_live = any(s == "live" for s in statuses)
        # Shot+net must co-occur on the SAME live probe — no cross-probe stitch.
        same_probe_complete = False
        for obs in observations:
            if obs.get("live_or_replay") != "live":
                continue
            pp = obs.get("probe_phases") or {}
            if pp.get("shot") and pp.get("net"):
                same_probe_complete = True
                break
            blob = str(obs.get("blob_excerpt") or "")
            acts = " ".join(str(a) for a in (obs.get("observed_actions") or []))
            text = f"{blob} {acts}"
            if _SHOT.search(text) and _NET.search(text):
                same_probe_complete = True
                break

        if strong_replay or has_mixed:
            fail.append("final_mp4_contains_replay_or_mixed")
        if not has_live:
            fail.append("final_mp4_live_unconfirmed")
        if not phase_hits["shot"]:
            fail.append("final_mp4_missing_shot_action")
        if not phase_hits["net"]:
            fail.append("final_mp4_missing_net_result")
        if phase_hits["shot"] and phase_hits["net"] and not same_probe_complete:
            fail.append("final_mp4_shot_net_cross_probe_stitch")
        truncated = bool(phase_hits["shot"] and not phase_hits["net"])
        if truncated:
            fail.append("possible_early_truncation_before_net")

        # Score-order: live net must precede trusted score confirmation when known.
        result_sec = row.get("result_sec") or g.get("verified_result_sec")
        conf = g.get("score_confirmation_time")
        if result_sec is not None and conf is not None:
            if float(result_sec) > float(conf) + 1.0:
                fail.append("final_mp4_result_after_score_confirmation")

        live_ok = has_live and not strong_replay and not has_mixed
        passed = (
            len(fail) == 0
            and live_ok
            and phase_hits["shot"]
            and phase_hits["net"]
            and same_probe_complete
        )

        goals_out.append(
            {
                "key_event_id": kid,
                "score_before": g.get("score_before"),
                "score_after": g.get("score_after"),
                "source_media_in": row.get("source_media_in"),
                "source_media_out": row.get("source_media_out"),
                "verified_shot_sec": row.get("shot_sec") or g.get("verified_shot_sec"),
                "verified_result_sec": row.get("result_sec") or g.get("verified_result_sec"),
                "story_play_in": pin,
                "story_play_out": pout,
                "frame_evidence": {
                    "pre_shot_approach": phase_hits["pre_shot"],
                    "shot_action": phase_hits["shot"],
                    "net_result": phase_hits["net"],
                    "celebration": phase_hits["celebrate"],
                    "same_live_probe_shot_and_net": same_probe_complete,
                },
                "live_or_replay_final": (
                    "replay"
                    if strong_replay
                    else (
                        "mixed_or_ambiguous"
                        if has_mixed
                        else ("live" if live_ok else "unknown")
                    )
                ),
                "incorrect_crop": truncated,
                "observations": observations,
                "pass": passed,
                "fail_reasons": fail,
                "note": (
                    "Acceptance based on rendered MP4 observation, not EDL/PTS alone. "
                    "Any mixed/replay probe fails; shot+net must share one live probe."
                ),
            }
        )

    all_pass = len(goals_out) == 5 and all(g.get("pass") for g in goals_out)
    return {
        "schema": "v2_r25_final_mp4_visual_audit_v1",
        "story_mp4": str(story_mp4),
        "n_goals_audited": len(goals_out),
        "n_pass": sum(1 for g in goals_out if g.get("pass")),
        "all_five_goals_visual_pass": all_pass,
        "acceptance_failed": not all_pass,
        "goals": goals_out,
        "render_ready": False,
        "policy": (
            "Any goal lacking complete live shot+net OR containing replay/mixed → whole story fails. "
            "late_only_mixed is NOT accepted. Shot+net must appear on the same live probe "
            "(no cross-probe stitch). Historical shot/result PTS must not substitute for "
            "final-frame observation."
        ),
    }
