"""Event Input Adapter — whitelist-only events for Event-Guided Story Agent.

Supports:
  - human_corrected: existing migu events.json
  - upstream_detected: same schema projected from future 咪咕 upstream API

NEVER accepts causal.json / story roles / causal edges as model input.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

INPUT_SOURCES = ("human_corrected", "upstream_detected")

# Top-level event fields allowed through (others dropped).
_EVENT_ALLOW = {
    "event_id",
    "event_type",
    "event_type_id",
    "event_type_zh",
    "media_time",
    "video_context",
    "attributes",  # further filtered
}

# Nested video_context whitelist
_VC_ALLOW = {"broadcast_phase", "is_replay", "is_slow_motion"}

# Nested attributes whitelist — raw detection cues only (no story/causal labels)
_ATTR_ALLOW = {
    "Score_Recognition",
    "Related_Player",
    "Body_Part",
    "Goal_Type",
    "Match_Phase",
    "Pitch_Area",
    "Shot_Type_Camera_Angle",
}

# Hard reject substrings in keys (defense in depth)
_FORBIDDEN_KEY_SUBSTR = (
    "causal",
    "story",
    "narrative",
    "protagonist",
    "beat",
    "chain",
    "relation",
    "edl",
    "compose",
    "role",
    "hypothesis",
)


class EventAdapterError(ValueError):
    pass


def _forbid_key(key: str) -> bool:
    k = key.lower()
    return any(s in k for s in _FORBIDDEN_KEY_SUBSTR)


def _parse_score_token(token: str) -> Optional[Tuple[int, int]]:
    text = str(token).strip().replace("：", ":").replace("-", ":").replace("–", ":")
    if ":" not in text:
        return None
    a, b = text.split(":", 1)
    try:
        return int(a.strip()), int(b.strip())
    except ValueError:
        return None


def sanitize_raw_event(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Project one raw events.json item → standard event (or None if unusable)."""
    if not isinstance(raw, dict):
        return None
    for k in raw:
        if _forbid_key(str(k)):
            # Drop entire event if it carries forbidden top-level story/causal keys
            # (should not appear in clean events.json; safety net).
            continue
    eid = raw.get("event_id")
    et = raw.get("event_type") or raw.get("event_type_id")
    mt = raw.get("media_time") or {}
    if not eid or not et or not isinstance(mt, dict):
        return None
    start = mt.get("start_time_sec")
    end = mt.get("end_time_sec")
    etime = mt.get("event_time_sec")
    if start is None or end is None:
        return None

    vc_in = raw.get("video_context") if isinstance(raw.get("video_context"), dict) else {}
    vc = {k: vc_in.get(k) for k in _VC_ALLOW if k in vc_in}

    attrs_in = raw.get("attributes") if isinstance(raw.get("attributes"), dict) else {}
    attrs: Dict[str, Any] = {}
    for k, v in attrs_in.items():
        if k in _ATTR_ALLOW and not _forbid_key(k):
            attrs[k] = v

    scoreboard = None
    score_pair = None
    score_source = None
    sr = attrs.get("Score_Recognition")
    if isinstance(sr, list) and sr:
        scoreboard = str(sr[0])
        score_pair = _parse_score_token(scoreboard)
        score_source = "attributes.Score_Recognition"
    elif isinstance(sr, str) and sr:
        scoreboard = sr
        score_pair = _parse_score_token(sr)
        score_source = "attributes.Score_Recognition"
    # Fallback: many Foul_Being_fouled rows only store the board under scores.score_recognition
    # (not attributes). Without this, first LIVE 3:1 @ event_000118 is skipped and the
    # trajectory wrongly anchors on a later REPLAY Substitution.
    if score_pair is None:
        scores_in = raw.get("scores") if isinstance(raw.get("scores"), dict) else {}
        sr2 = scores_in.get("score_recognition")
        if isinstance(sr2, str) and sr2.strip():
            scoreboard = sr2.strip()
            score_pair = _parse_score_token(scoreboard)
            score_source = "scores.score_recognition"
        elif isinstance(sr2, list) and sr2:
            scoreboard = str(sr2[0]).strip()
            score_pair = _parse_score_token(scoreboard)
            score_source = "scores.score_recognition"

    return {
        "schema": "v2_standard_event_v1",
        "event_id": str(eid),
        "event_type": str(et),
        "event_type_id": str(raw.get("event_type_id") or "") or None,
        "event_type_zh": str(raw.get("event_type_zh") or "") or None,
        "media_start_sec": float(start),
        "media_end_sec": float(end),
        "event_time_sec": float(etime) if etime is not None else None,
        "scoreboard": scoreboard,
        "score_pair": list(score_pair) if score_pair else None,
        "score_source": score_source,
        "is_replay": bool(vc.get("is_replay")) if vc.get("is_replay") is not None else None,
        "broadcast_phase": vc.get("broadcast_phase"),
        "is_slow_motion": bool(vc.get("is_slow_motion")) if vc.get("is_slow_motion") is not None else None,
        "attributes": attrs,
    }


def load_events_json(
    path: Path,
    *,
    input_source: str = "human_corrected",
) -> Dict[str, Any]:
    if input_source not in INPUT_SOURCES:
        raise EventAdapterError(f"input_source must be one of {INPUT_SOURCES}")
    path = Path(path)
    if not path.is_file():
        raise EventAdapterError(f"events file missing: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("events"), list):
        raise EventAdapterError("events.json must be an object with events[]")

    # Refuse accidental causal payload
    for bad in ("causal_chains", "causal", "story_graph", "story_plan", "edges"):
        if bad in raw:
            raise EventAdapterError(f"refusing events payload containing forbidden key '{bad}'")

    std: List[Dict[str, Any]] = []
    dropped = 0
    for item in raw["events"]:
        s = sanitize_raw_event(item if isinstance(item, dict) else {})
        if s is None:
            dropped += 1
            continue
        std.append(s)

    teams = raw.get("teams") if isinstance(raw.get("teams"), dict) else {}
    # Only pass team display names if present — not story roles.
    team_names = {}
    for k in ("team_1", "team_2", "left", "right", "home", "away"):
        if k in teams and isinstance(teams[k], dict) and teams[k].get("name"):
            team_names[k] = str(teams[k]["name"])
        elif k in teams and isinstance(teams[k], str):
            team_names[k] = teams[k]

    return {
        "schema": "v2_event_bundle_v1",
        "input_source": input_source,
        "source_path": str(path),
        "match_id": raw.get("match_id"),
        "team_names": team_names,
        "events": std,
        "n_raw": len(raw["events"]),
        "n_kept": len(std),
        "n_dropped": dropped,
        "filtered_out_note": (
            "Dropped non-whitelisted fields including annotation scores, "
            "story/causal keys, and non-allowlisted attributes"
        ),
        "forbidden_as_model_input": [
            "causal.json",
            "causal_chains",
            "story roles",
            "story_graph",
            "precomputed narrative edges",
        ],
    }


def _board_is_live(e: Dict[str, Any]) -> bool:
    if e.get("is_replay") is True:
        return False
    if str(e.get("broadcast_phase") or "").upper() == "REPLAY":
        return False
    return True


def score_transition_anchors(events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Detect scoreboard state changes from whitelisted Score_Recognition only.

    Prefer earliest LIVE observation of a new score when the first sighting is REPLAY.
    """
    timed = [
        e
        for e in events
        if e.get("score_pair") and e.get("event_time_sec") is not None
    ]
    timed.sort(key=lambda e: float(e["event_time_sec"]))
    anchors: List[Dict[str, Any]] = []
    prev = None
    i = 0
    while i < len(timed):
        e = timed[i]
        pair = tuple(e["score_pair"])
        if prev is not None and pair == prev:
            i += 1
            continue
        chosen = e
        if prev is not None and not _board_is_live(e):
            for j in range(i + 1, len(timed)):
                e2 = timed[j]
                if tuple(e2["score_pair"]) != pair:
                    break
                if _board_is_live(e2):
                    chosen = e2
                    break
        if prev is None:
            anchors.append(
                {
                    "kind": "initial_score",
                    "score_pair": list(pair),
                    "event_id": chosen["event_id"],
                    "event_time_sec": chosen["event_time_sec"],
                    "media_start_sec": chosen["media_start_sec"],
                    "media_end_sec": chosen["media_end_sec"],
                    "event_type": chosen["event_type"],
                    "is_replay": chosen.get("is_replay"),
                    "first_sighting_event_id": e["event_id"],
                    "first_sighting_is_replay": bool(e.get("is_replay")),
                }
            )
        else:
            anchors.append(
                {
                    "kind": "score_change",
                    "score_before": list(prev),
                    "score_after": list(pair),
                    "event_id": chosen["event_id"],
                    "event_time_sec": chosen["event_time_sec"],
                    "media_start_sec": chosen["media_start_sec"],
                    "media_end_sec": chosen["media_end_sec"],
                    "event_type": chosen["event_type"],
                    "is_replay": chosen.get("is_replay"),
                    "first_sighting_event_id": e["event_id"],
                    "first_sighting_is_replay": bool(e.get("is_replay")),
                }
            )
        prev = pair
        while i < len(timed) and tuple(timed[i]["score_pair"]) == pair:
            i += 1
    return anchors


def candidate_events_near_anchors(
    events: Sequence[Dict[str, Any]],
    anchors: Sequence[Dict[str, Any]],
    *,
    pad_sec: float = 45.0,
    prefer_types: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Select nearby events as verification candidates (no story roles assigned)."""
    prefer_types = prefer_types or {"Goal", "Shot", "Save", "Corner_kick", "Pass"}
    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for a in anchors:
        if a.get("kind") != "score_change":
            continue
        t = float(a["event_time_sec"])
        window = (t - pad_sec, t + pad_sec)
        nearby = [
            e
            for e in events
            if e.get("event_time_sec") is not None
            and window[0] <= float(e["event_time_sec"]) <= window[1]
        ]
        # Prefer action-like types, then by proximity
        nearby.sort(
            key=lambda e: (
                0 if e.get("event_type") in prefer_types else 1,
                abs(float(e["event_time_sec"]) - t),
            )
        )
        for e in nearby[:6]:
            if e["event_id"] in seen:
                continue
            seen.add(e["event_id"])
            out.append(
                {
                    "anchor": {
                        "score_before": a.get("score_before"),
                        "score_after": a.get("score_after"),
                        "anchor_event_id": a.get("event_id"),
                        "anchor_time_sec": a.get("event_time_sec"),
                    },
                    "event": e,
                }
            )
    return out


def planner_event_digest(bundle: Dict[str, Any], *, max_events: int = 80) -> Dict[str, Any]:
    """Compact, story-role-free digest for DeepSeek (anchors + subsampled events)."""
    events = bundle.get("events") or []
    anchors = score_transition_anchors(events)
    # Subsample: all Goals/Shots + score-change neighbors + uniform fill
    important = [
        e
        for e in events
        if e.get("event_type") in {"Goal", "Shot", "Save", "Kick_off", "Full_time"}
        or e.get("score_pair")
    ]
    important_ids = {e["event_id"] for e in important}
    rest = [e for e in events if e["event_id"] not in important_ids]
    step = max(1, len(rest) // max(1, max_events - len(important)))
    sampled = important + rest[::step]
    sampled = sampled[:max_events]
    sampled.sort(key=lambda e: float(e.get("event_time_sec") or e["media_start_sec"]))
    return {
        "input_source": bundle.get("input_source"),
        "match_id": bundle.get("match_id"),
        "team_names": bundle.get("team_names"),
        "n_events": bundle.get("n_kept"),
        "score_anchors": anchors,
        "events": [
            {
                "event_id": e["event_id"],
                "event_type": e["event_type"],
                "event_time_sec": e.get("event_time_sec"),
                "media_start_sec": e["media_start_sec"],
                "media_end_sec": e["media_end_sec"],
                "scoreboard": e.get("scoreboard"),
                "score_pair": e.get("score_pair"),
                "is_replay": e.get("is_replay"),
                "broadcast_phase": e.get("broadcast_phase"),
            }
            for e in sampled
        ],
        "rules": [
            "Events are raw detections only — no pre-assigned story roles",
            "Do not invent causal labels from annotations",
            "Use event times as search anchors; verify actions in video",
            "Score_Recognition is a board state cue, not proven goal action",
        ],
    }
