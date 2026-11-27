"""Phase B structured story evidence items + candidate dedup."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


OBSERVATION_STATUSES = ("observed", "hypothesized", "unresolved", "failed")
VERIFICATION_STATUSES = ("unverified", "corroborated", "verified", "rejected")
NARRATIVE_ROLES = (
    "unknown",
    "scoreboard",
    "deficit_indicator",
    "equalizer_candidate",
    "go_ahead_candidate",
    "lead_extend_candidate",
    "possible_goal",
    "celebration",
    "replay_candidate",
    "attack_buildup",
    "other",
)


def empty_evidence_item(**kwargs: Any) -> Dict[str, Any]:
    item = {
        "schema": "v2_story_evidence_item_v1",
        "event_type": "unknown",
        "team_side": None,
        "team_name": None,
        "media_start": None,
        "media_end": None,
        "frame_ids": [],
        "observation_status": "observed",
        "live_or_replay": "unknown",
        "scoreboard_before": None,
        "scoreboard_after": None,
        "narrative_role": "unknown",
        "supporting_observations": [],
        "conflicting_observations": [],
        "uncertainty": [],
        "verification_status": "unverified",
        "source_tool": None,
        "raw_actions": [],
        "notes": "",
    }
    item.update(kwargs)
    return item


def _role_from_text(text: str) -> str:
    t = text.lower()
    if "replay" in t or "回放" in t:
        return "replay_candidate"
    if "celebrat" in t or "庆祝" in t:
        return "celebration"
    if "scoreboard" in t or "score" in t or "比分" in t:
        return "scoreboard"
    if "goal" in t or "进球" in t or "net" in t or "入网" in t:
        return "possible_goal"
    if "attack" in t or "shot" in t or "射门" in t or "进攻" in t:
        return "attack_buildup"
    return "unknown"


def _live_flag(text: str) -> str:
    t = text.lower()
    if "replay" in t or "回放" in t:
        return "replay"
    if "live" in t or "直播" in t:
        return "live"
    return "unknown"


def items_from_observation(obs: Dict[str, Any], *, tool: Optional[str] = None) -> List[Dict[str, Any]]:
    """Build evidence items from one tool observation (not one item per action string)."""
    if obs.get("error"):
        return [
            empty_evidence_item(
                event_type="tool_failure",
                media_start=obs.get("media_start_sec"),
                media_end=obs.get("media_end_sec"),
                observation_status="failed",
                verification_status="unverified",
                source_tool=tool or obs.get("tool"),
                notes=str(obs.get("message") or obs.get("error") or ""),
                uncertainty=["tool_call_failed"],
            )
        ]

    perc = obs.get("perception") or {}
    actions = [str(a) for a in (perc.get("observed_actions") or [])]
    notes = str(perc.get("notes") or "")
    blob = " | ".join(actions + [notes])
    role = _role_from_text(blob)
    # Prefer a single primary item per window; attach actions as supporting text.
    item = empty_evidence_item(
        event_type="visual_window",
        media_start=obs.get("media_start_sec"),
        media_end=obs.get("media_end_sec"),
        frame_ids=list(perc.get("frame_ids") or []),
        observation_status="observed" if perc.get("normalized_ok") else "unresolved",
        live_or_replay=_live_flag(blob),
        narrative_role=role,
        supporting_observations=actions[:12],
        uncertainty=[] if perc.get("normalized_ok") else ["perception_not_normalized"],
        verification_status="unverified",
        source_tool=tool or obs.get("tool") or obs.get("purpose"),
        raw_actions=actions,
        notes=notes[:800],
    )
    # Sparse samples cannot claim a full goal action was localized.
    if role == "possible_goal":
        item["uncertainty"].append(
            "sparse_frames_cannot_prove_full_goal_action; needs localize/verify"
        )
        item["observation_status"] = "hypothesized"
    return [item]


def _bucket_key(item: Dict[str, Any], *, time_bin_sec: float = 30.0) -> str:
    start = item.get("media_start")
    if start is None:
        start = -1.0
    bin_id = int(float(start) // time_bin_sec) if start is not None and start >= 0 else -1
    role = str(item.get("narrative_role") or "unknown")
    team = str(item.get("team_name") or item.get("team_side") or "?")
    return f"{bin_id}|{role}|{team}"


def dedupe_evidence_items(
    items: Sequence[Dict[str, Any]], *, time_bin_sec: float = 30.0
) -> List[Dict[str, Any]]:
    """Merge items that share time-bin + narrative_role + team."""
    buckets: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for raw in items:
        item = dict(raw)
        key = _bucket_key(item, time_bin_sec=time_bin_sec)
        if key not in buckets:
            buckets[key] = item
            order.append(key)
            continue
        cur = buckets[key]
        # Merge frame ids / supporting obs; keep earliest start / latest end.
        fids = list(dict.fromkeys(list(cur.get("frame_ids") or []) + list(item.get("frame_ids") or [])))
        cur["frame_ids"] = fids
        cur["supporting_observations"] = list(
            dict.fromkeys(
                list(cur.get("supporting_observations") or [])
                + list(item.get("supporting_observations") or [])
            )
        )[:20]
        cur["raw_actions"] = list(
            dict.fromkeys(list(cur.get("raw_actions") or []) + list(item.get("raw_actions") or []))
        )[:20]
        cur["uncertainty"] = list(
            dict.fromkeys(list(cur.get("uncertainty") or []) + list(item.get("uncertainty") or []))
        )
        for field in ("media_start", "media_end"):
            a, b = cur.get(field), item.get(field)
            if a is None:
                cur[field] = b
            elif b is not None:
                cur[field] = min(float(a), float(b)) if field == "media_start" else max(float(a), float(b))
        # Escalate verification if either side is stronger.
        rank = {"unverified": 0, "corroborated": 1, "verified": 2, "rejected": -1}
        if rank.get(str(item.get("verification_status")), 0) > rank.get(
            str(cur.get("verification_status")), 0
        ):
            cur["verification_status"] = item.get("verification_status")
        if str(item.get("observation_status")) == "observed" and cur.get("observation_status") != "failed":
            if cur.get("observation_status") in ("hypothesized", "unresolved"):
                cur["observation_status"] = "observed"
        buckets[key] = cur
    return [buckets[k] for k in order]


def count_by_status(items: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for it in items:
        st = str(it.get("observation_status") or "unknown")
        out[st] = out.get(st, 0) + 1
        vs = str(it.get("verification_status") or "unverified")
        out[f"verify:{vs}"] = out.get(f"verify:{vs}", 0) + 1
    return out
