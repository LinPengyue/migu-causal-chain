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
    return {
        "schema": "v2_goal_candidate_evidence_v1",
        "candidate_event_id": candidate_event_id,
        "event_time_sec": event_time_sec,
        "localized_media_in": localized_media_in
        if localized_media_in is not None
        else observation.get("media_start_sec"),
        "localized_media_out": localized_media_out
        if localized_media_out is not None
        else observation.get("media_end_sec"),
        "supporting_frame_ids": evidence.get("supporting_frame_ids") or [],
        "observed_action_sequence": evidence.get("observed_action_sequence") or [],
        "shooting_action_evidence": evidence.get("shooting_action_evidence"),
        "goal_result_evidence": evidence.get("goal_result_evidence"),
        "live_or_replay": evidence.get("live_or_replay"),
        "verification_status": evidence.get("verification_status"),
        "uncertainty": evidence.get("uncertainty"),
        "grade": evidence.get("grade"),
        "evidence_reasons": evidence.get("reasons"),
        "render_ready": False,
    }
