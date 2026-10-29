"""Strict action evidence — keyword-only grades are not enough for action_localized."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from story_video_agent.v2_score_transitions import parse_score_pairs

_FRAME_CITE = re.compile(r"\bf[_-]?\d{3,}\b|\bframe\s*#?\s*\d+", re.I)
_SHOT = re.compile(
    r"\b(?:shoot|shot|strike|header|volley|finish(?:es|ed)?|tap[- ]?in)\b|射门|头球|抽射|推射",
    re.I,
)
_NET = re.compile(
    r"ball\s+(?:in|into|enters?|cross(?:es)?)\s+(?:the\s+)?(?:net|goal)|into\s+the\s+net|"
    r"hits?\s+the\s+net|keeper\s+beaten|入网|破门|球进",
    re.I,
)
_CELEB = re.compile(r"celebrat|knee\s*slide|group\s*hug|庆祝|跪滑", re.I)
_REPLAY = re.compile(r"\breplay\b|slo(?:w)?[- ]?mo|回放|慢镜", re.I)
_LIVE = re.compile(r"\blive\b|直播", re.I)
_NEG_ACTION = re.compile(
    r"no\s+(?:goal|shot)|midfield\s+(?:only|build)|static\s+scene|no\s+high-intensity",
    re.I,
)


def _blob(observation: Dict[str, Any]) -> str:
    perc = observation.get("perception") or {}
    parts = [
        str(perc.get("notes") or ""),
        " ".join(str(a) for a in (perc.get("observed_actions") or [])),
        str(observation.get("notes") or ""),
    ]
    return " | ".join(parts)


def _frame_ids(observation: Dict[str, Any]) -> List[str]:
    frames = observation.get("frames") or []
    ids = [str(f.get("frame_id")) for f in frames if isinstance(f, dict) and f.get("frame_id")]
    perc = observation.get("perception") or {}
    for fid in perc.get("frame_ids") or []:
        if str(fid) not in ids:
            ids.append(str(fid))
    return ids


def extract_action_sequence(observation: Dict[str, Any]) -> List[str]:
    perc = observation.get("perception") or {}
    acts = [str(a) for a in (perc.get("observed_actions") or []) if str(a).strip()]
    return acts[:12]


def grade_with_frame_evidence(
    *,
    observation: Dict[str, Any],
    window_span_sec: Optional[float] = None,
) -> Dict[str, Any]:
    """Stricter than C-1 keyword grade: require frame cites for action_localized."""
    text = _blob(observation)
    frame_ids = _frame_ids(observation)
    cites = bool(_FRAME_CITE.search(text)) or bool(frame_ids)
    has_shot = bool(_SHOT.search(text)) and not bool(_NEG_ACTION.search(text) and not _SHOT.search(text))
    # If negative says no shot, override
    if re.search(r"no\s+shot|no\s+goal", text, re.I) and not _NET.search(text):
        has_shot = bool(_SHOT.search(text) and _FRAME_CITE.search(text))
    has_net = bool(_NET.search(text))
    celeb = bool(_CELEB.search(text))
    scores = parse_score_pairs(text)
    has_replay = bool(_REPLAY.search(text))
    has_live = bool(_LIVE.search(text))
    # A single "replay angle" cutaway after a live shot/net must not wipe localization.
    if has_replay and (has_shot and has_net):
        live_or_replay = "mixed"
    elif has_replay and has_live:
        live_or_replay = "mixed"
    elif has_replay:
        live_or_replay = "replay"
    elif has_live:
        live_or_replay = "live"
    else:
        live_or_replay = "unknown"

    span = window_span_sec
    if span is None and observation.get("media_start_sec") is not None:
        span = float(observation["media_end_sec"]) - float(observation["media_start_sec"])
    too_wide = span is not None and span > 20.0

    reasons: List[str] = []
    shooting_evidence = has_shot and cites
    goal_result_evidence = has_net and cites
    if has_shot and not cites:
        reasons.append("shot_keyword_without_frame_cite")
    if has_net and not cites:
        reasons.append("result_keyword_without_frame_cite")
    if celeb and not has_shot:
        reasons.append("celebration_without_shot")
    if live_or_replay == "mixed":
        reasons.append("live_action_with_replay_cutaway")

    verification_status = "unresolved"
    grade = "unresolved"
    # Pure replay-only windows cannot be action_localized; mixed/unknown/live can.
    if (
        shooting_evidence
        and goal_result_evidence
        and not too_wide
        and live_or_replay != "replay"
    ):
        grade = "action_localized"
        verification_status = "verified_action"
        reasons.append("shot_and_net_with_frame_evidence")
    elif shooting_evidence or (goal_result_evidence and has_shot):
        grade = "goal_candidate"
        verification_status = "candidate_needs_refine"
        reasons.append("partial_frame_bound_action")
    elif scores or celeb:
        grade = "goal_candidate" if celeb else "scoreboard_only"
        verification_status = "score_or_celebration_only"
        reasons.append("no_clear_shot_net_frame_evidence")
    else:
        reasons.append("insufficient_evidence")

    if too_wide and grade == "action_localized":
        grade = "goal_candidate"
        verification_status = "candidate_needs_refine"
        reasons.append("window_too_wide")

    uncertainty = 0.7
    if grade == "action_localized":
        uncertainty = 0.25
    elif grade == "goal_candidate":
        uncertainty = 0.55
    elif grade == "scoreboard_only":
        uncertainty = 0.6

    timing = localize_goal_action_times(observation=observation, evidence_hint={
        "shooting_action_evidence": bool(shooting_evidence),
        "goal_result_evidence": bool(goal_result_evidence),
        "supporting_frame_ids": frame_ids,
        "grade": grade,
    })
    # Do not treat keyword+any-frame as verified action times.
    if grade == "action_localized" and not timing.get("action_time_resolved"):
        grade = "goal_candidate"
        verification_status = "candidate_needs_refine"
        reasons.append("missing_shot_or_result_frame_time")
        uncertainty = max(uncertainty, 0.55)

    return {
        "grade": grade,
        "verification_status": verification_status,
        "shooting_action_evidence": bool(shooting_evidence),
        "goal_result_evidence": bool(goal_result_evidence),
        "has_shot_like_keyword": has_shot,
        "has_net_keyword": has_net,
        "live_or_replay": live_or_replay,
        "score_pairs": scores,
        "supporting_frame_ids": frame_ids,
        "frame_cite_in_text": cites,
        "observed_action_sequence": extract_action_sequence(observation),
        "window_span_sec": span,
        "uncertainty": uncertainty,
        "reasons": reasons,
        "keyword_only_insufficient": has_shot and not cites,
        "observation_window": {
            "media_in": observation.get("media_start_sec"),
            "media_out": observation.get("media_end_sec"),
        },
        "shot_action": timing.get("shot_action"),
        "goal_result": timing.get("goal_result"),
        "edit_window": timing.get("edit_window"),
        "action_time_resolved": bool(timing.get("action_time_resolved")),
        "timing_notes": timing.get("notes") or [],
    }


def _frame_time_map(observation: Dict[str, Any]) -> Dict[str, float]:
    """Map frame_id → best available media seconds (actual PTS preferred)."""
    out: Dict[str, float] = {}
    for fr in observation.get("frames") or []:
        if not isinstance(fr, dict) or not fr.get("frame_id"):
            continue
        fid = str(fr["frame_id"])
        t = fr.get("actual_media_sec")
        if t is None:
            t = fr.get("requested_media_sec")
        if t is not None:
            out[fid] = float(t)
    perc = observation.get("perception") or {}
    for b in perc.get("frame_time_bindings") or []:
        if not isinstance(b, dict) or not b.get("frame_id"):
            continue
        fid = str(b["frame_id"])
        t = b.get("actual_media_sec")
        if t is None:
            t = b.get("requested_media_sec")
        if t is not None:
            out[fid] = float(t)
    return out


def _frames_near_keyword(text: str, pattern: re.Pattern[str], known_ids: Sequence[str]) -> List[str]:
    """Heuristic: frame ids mentioned in the same clause as shot/net keywords."""
    hits: List[str] = []
    if not text:
        return hits
    # split on sentence-ish boundaries
    chunks = re.split(r"[;\n\.]|。|；", text)
    for ch in chunks:
        if not pattern.search(ch):
            continue
        for fid in known_ids:
            if re.search(rf"\b{re.escape(fid)}\b", ch, re.I):
                if fid not in hits:
                    hits.append(fid)
    return hits


def localize_goal_action_times(
    *,
    observation: Dict[str, Any],
    evidence_hint: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Separate observation window vs shot time vs result time vs edit window.

    Never uses the observation-window midpoint as the goal action time.
    Requires cited frame media times for shot and/or result.
    """
    hint = evidence_hint or {}
    fmap = _frame_time_map(observation)
    cited = [str(x) for x in (hint.get("supporting_frame_ids") or _frame_ids(observation))]
    cited = [c for c in cited if c in fmap]
    text = _blob(observation)
    notes: List[str] = []

    shot_ids = _frames_near_keyword(text, _SHOT, cited)
    net_ids = _frames_near_keyword(text, _NET, cited)

    # If model cited frames but did not bind keywords to ids, do NOT invent assignment
    # from "first/last cited" unless both shot and net keywords exist AND >=2 cited times.
    if not shot_ids and not net_ids and cited and hint.get("shooting_action_evidence") and hint.get("goal_result_evidence"):
        notes.append("cited_frames_without_keyword_binding; refusing first/last fallback")
    elif len(cited) >= 2 and hint.get("shooting_action_evidence") and hint.get("goal_result_evidence"):
        if not shot_ids and _SHOT.search(text):
            # ordered by time: earliest cited with shot keyword elsewhere still unbound
            notes.append("shot_keyword_present_but_no_frame_binding")
        if not net_ids and _NET.search(text):
            notes.append("net_keyword_present_but_no_frame_binding")

    shot_action = None
    if shot_ids:
        fid = min(shot_ids, key=lambda i: fmap[i])
        shot_action = {
            "frame_id": fid,
            "media_sec": fmap[fid],
            "role": "shot_action",
            "all_frame_ids": shot_ids,
        }
    goal_result = None
    if net_ids:
        fid = max(net_ids, key=lambda i: fmap[i])
        goal_result = {
            "frame_id": fid,
            "media_sec": fmap[fid],
            "role": "goal_result",
            "all_frame_ids": net_ids,
        }

    # Edit window: pad around resolved action times only (not full observation window).
    edit_window = None
    times = []
    if shot_action:
        times.append(float(shot_action["media_sec"]))
    if goal_result:
        times.append(float(goal_result["media_sec"]))
    if times:
        t0, t1 = min(times), max(times)
        # short pad for cut candidates; still not render_ready
        edit_window = {
            "media_in": round(max(0.0, t0 - 2.0), 3),
            "media_out": round(t1 + 3.0, 3),
            "basis": "shot_and_or_result_frame_times",
        }

    obs_in = observation.get("media_start_sec")
    obs_out = observation.get("media_end_sec")
    action_time_resolved = bool(shot_action) and bool(goal_result)
    if shot_action and goal_result and float(goal_result["media_sec"]) + 1e-6 < float(shot_action["media_sec"]):
        notes.append("result_before_shot_time_order_suspect")
        action_time_resolved = False

    return {
        "observation_window": {"media_in": obs_in, "media_out": obs_out},
        "shot_action": shot_action,
        "goal_result": goal_result,
        "edit_window": edit_window,
        "action_time_resolved": action_time_resolved,
        "frame_time_map_cited": {k: fmap[k] for k in cited},
        "notes": notes,
        # Explicit: midpoint of observation window is forbidden as action time
        "forbidden_midpoint_of_observation_window": (
            round(0.5 * (float(obs_in) + float(obs_out)), 3)
            if obs_in is not None and obs_out is not None
            else None
        ),
    }


def merge_action_evidence_windows(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate shot/result evidence across adjacent live observations."""
    shots = []
    results = []
    live_flags = []
    for r in rows:
        ev = r.get("evidence") or r
        if ev.get("live_or_replay") == "replay":
            continue
        if ev.get("shot_action"):
            shots.append(ev["shot_action"])
        if ev.get("goal_result"):
            results.append(ev["goal_result"])
        live_flags.append(ev.get("live_or_replay"))
    shot = min(shots, key=lambda x: float(x["media_sec"])) if shots else None
    result = max(results, key=lambda x: float(x["media_sec"])) if results else None
    ok = bool(shot) and bool(result) and float(result["media_sec"]) >= float(shot["media_sec"]) - 0.5
    edit = None
    if shot and result:
        edit = {
            "media_in": round(float(shot["media_sec"]) - 2.0, 3),
            "media_out": round(float(result["media_sec"]) + 3.0, 3),
            "basis": "aggregated_shot_result_frames",
        }
    return {
        "shot_action": shot,
        "goal_result": result,
        "edit_window": edit,
        "action_time_resolved": ok,
        "n_source_rows": len(rows),
        "live_or_replay_votes": sorted({str(x) for x in live_flags if x}),
    }


def build_goal_candidate_record(
    *,
    candidate_event_id: str,
    event_time_sec: Optional[float],
    observation: Dict[str, Any],
    evidence: Dict[str, Any],
    localized_media_in: Optional[float] = None,
    localized_media_out: Optional[float] = None,
) -> Dict[str, Any]:
    edit = evidence.get("edit_window") or {}
    return {
        "schema": "v2_goal_candidate_evidence_v1",
        "candidate_event_id": candidate_event_id,
        "event_time_sec": event_time_sec,
        "observation_window": evidence.get("observation_window")
        or {
            "media_in": observation.get("media_start_sec"),
            "media_out": observation.get("media_end_sec"),
        },
        "shot_action": evidence.get("shot_action"),
        "goal_result": evidence.get("goal_result"),
        "edit_window": edit or None,
        "localized_media_in": localized_media_in
        if localized_media_in is not None
        else (edit.get("media_in") if edit else None),
        "localized_media_out": localized_media_out
        if localized_media_out is not None
        else (edit.get("media_out") if edit else None),
        "supporting_frame_ids": evidence.get("supporting_frame_ids") or [],
        "observed_action_sequence": evidence.get("observed_action_sequence") or [],
        "shooting_action_evidence": evidence.get("shooting_action_evidence"),
        "goal_result_evidence": evidence.get("goal_result_evidence"),
        "live_or_replay": evidence.get("live_or_replay"),
        "verification_status": evidence.get("verification_status"),
        "uncertainty": evidence.get("uncertainty"),
        "grade": evidence.get("grade"),
        "action_time_resolved": evidence.get("action_time_resolved"),
        "evidence_reasons": evidence.get("reasons"),
        "render_ready": False,
    }
