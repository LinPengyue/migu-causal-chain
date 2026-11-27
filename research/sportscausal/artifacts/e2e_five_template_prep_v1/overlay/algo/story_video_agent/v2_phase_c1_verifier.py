"""Independent localization grading — does not trust LLM self-labels."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from story_video_agent.v2_score_transitions import parse_score_pairs

LOCALIZATION_GRADES = (
    "scoreboard_only",
    "goal_candidate",
    "action_localized",
    "action_corroborated",
    "unresolved",
)

_ACTION_HINTS = re.compile(
    r"shot|shoot|strike|header|cross(?:es|ed)?|finish|volley|tap[- ]?in|"
    r"ball\s+(?:in|into)\s+(?:the\s+)?net|hits?\s+the\s+net|goal\s+line|"
    r"射门|头球|入网|破门|推射|抽射|凌空",
    re.I,
)
_RESULT_HINTS = re.compile(
    r"goal|scored|score\s+changes?|celebrat|into\s+the\s+net|keeper\s+beaten|"
    r"进球|破门|入网|庆祝|比分变化",
    re.I,
)
_PRE_HINTS = re.compile(
    r"build[- ]?up|pass(?:es|ing)?|dribbl|approach|run(?:ning)?\s+into|"
    r"进攻|传球|盘带|前插|配合",
    re.I,
)
_REPLAY_HINTS = re.compile(r"replay|slo(?:w)?[- ]?mo|回放|慢镜|集锦|highlight", re.I)
_LIVE_HINTS = re.compile(r"\blive\b|直播", re.I)


def _blob(observation: Dict[str, Any]) -> str:
    perc = observation.get("perception") or {}
    parts = [
        str(perc.get("notes") or ""),
        " ".join(str(a) for a in (perc.get("observed_actions") or [])),
        str(observation.get("notes") or ""),
    ]
    return " | ".join(parts)


def grade_localization(
    *,
    observation: Dict[str, Any],
    task_role: str,
    expected_score_after: Optional[tuple] = None,
    window_span_sec: Optional[float] = None,
) -> Dict[str, Any]:
    """Assign localization grade from visible evidence only."""
    text = _blob(observation)
    if observation.get("error") or not text.strip():
        return {
            "grade": "unresolved",
            "has_pre_action": False,
            "has_goal_result": False,
            "has_shot_like_action": False,
            "live_or_replay": "unknown",
            "score_pairs": [],
            "reasons": ["empty_or_failed_observation"],
            "needs_further_verify": True,
        }

    scores = parse_score_pairs(text)
    has_shot = bool(_ACTION_HINTS.search(text))
    has_result = bool(_RESULT_HINTS.search(text))
    has_pre = bool(_PRE_HINTS.search(text))
    live_or_replay = "unknown"
    if _REPLAY_HINTS.search(text):
        live_or_replay = "replay"
    elif _LIVE_HINTS.search(text):
        live_or_replay = "live"

    span = window_span_sec
    if span is None and observation.get("media_start_sec") is not None:
        span = float(observation["media_end_sec"]) - float(observation["media_start_sec"])

    reasons: List[str] = []
    # Wide windows cannot claim action_localized even with action words.
    too_wide = span is not None and span > 20.0

    grade = "unresolved"
    if has_shot and has_result and not too_wide and live_or_replay != "replay":
        grade = "action_localized"
        reasons.append("shot_like_and_result_in_narrow_window")
    elif has_shot or (has_result and has_pre):
        grade = "goal_candidate"
        reasons.append("partial_action_cues")
    elif scores:
        grade = "scoreboard_only"
        reasons.append("scoreboard_visible_without_action")
    else:
        grade = "unresolved"
        reasons.append("no_score_or_action_cues")

    if too_wide and grade == "action_localized":
        grade = "goal_candidate"
        reasons.append("window_too_wide_for_action_localized")

    corroborated = False
    if grade in ("action_localized", "goal_candidate") and scores and live_or_replay == "live":
        if expected_score_after is None or expected_score_after in scores:
            if grade == "action_localized" and has_shot and has_result:
                corroborated = True
                grade = "action_corroborated"
                reasons.append("live_action_score_consistent")

    return {
        "grade": grade,
        "has_pre_action": has_pre,
        "has_goal_result": has_result,
        "has_shot_like_action": has_shot,
        "live_or_replay": live_or_replay,
        "score_pairs": scores,
        "window_span_sec": span,
        "reasons": reasons,
        "needs_further_verify": grade not in ("action_corroborated",),
        "action_corroborated_not_production_auth": True,
        "task_role": task_role,
    }


def build_localized_event_record(
    *,
    task: Dict[str, Any],
    observation: Dict[str, Any],
    grade_info: Dict[str, Any],
) -> Dict[str, Any]:
    perc = observation.get("perception") or {}
    frames = observation.get("frames") or []
    sampled = observation.get("sampled_media_times") or [
        f.get("requested_media_sec") for f in frames if isinstance(f, dict)
    ]
    return {
        "schema": "v2_localized_event_v1",
        "task_id": task.get("task_id"),
        "narrative_role": task.get("narrative_need"),
        "candidate_window": task.get("candidate_window"),
        "refined_action_window": {
            "start": observation.get("media_start_sec"),
            "end": observation.get("media_end_sec"),
        },
        "sampled_media_times": sampled,
        "frame_ids": list(perc.get("frame_ids") or []),
        "frames": frames,
        "visible_actions": list(perc.get("observed_actions") or []),
        "notes": str(perc.get("notes") or "")[:1200],
        "localization_grade": grade_info.get("grade"),
        "has_pre_action": grade_info.get("has_pre_action"),
        "has_goal_result": grade_info.get("has_goal_result"),
        "live_or_replay": grade_info.get("live_or_replay"),
        "score_pairs": grade_info.get("score_pairs"),
        "needs_further_verify": grade_info.get("needs_further_verify"),
        "edl_candidate_interval": {
            "media_in": observation.get("media_start_sec"),
            "media_out": observation.get("media_end_sec"),
            "usable_for_compose": grade_info.get("grade")
            in ("action_localized", "action_corroborated", "goal_candidate"),
            "not_render_authorized": True,
        },
        "verification": grade_info,
        "render_ready": False,
    }
