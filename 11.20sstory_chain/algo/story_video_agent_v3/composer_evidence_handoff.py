"""Structured Rule-Composer → V3-A evidence handoff (no Composer reimplementation).

Surfaces fields already present on Phase5/composer EDL rows into Planner context.
Never upgrades event-link / rule inference into visual or FIRST_LIVE verification.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

HANDOFF_SCHEMA = "composer_evidence_handoff_v1"

# Planner-facing dispositions (mapped onto existing revision_intents / tools).
DISPOSITION_KEEP = "KEEP"
DISPOSITION_INSPECT = "INSPECT"
DISPOSITION_REPAIR = "REPAIR"
DISPOSITION_UNRESOLVED = "UNRESOLVED"

# Visual ladder — never auto-promote.
VISUAL_NOT_OBSERVED = "NOT_VISUALLY_OBSERVED"
VISUAL_HISTORICAL_OBS_ONLY = "HISTORICAL_VLM_OBSERVATION_ONLY"
VISUAL_AGENT_BOUND_UNVERIFIED = "AGENT_BOUND_UNVERIFIED_FIRST_LIVE"
# Explicit non-claim: composer is_replay=false is NOT this.
VISUAL_NOT_FIRST_LIVE_CERTIFIED = "NOT_FIRST_LIVE_CERTIFIED"

GOAL_ROLE_MARKERS = (
    "opponent_opening_goal_action",
    "equalizer_goal_action",
    "go_ahead_goal_action",
)

# Disposition → existing schema action (INSPECT stays keep + tools).
DISPOSITION_TO_ACTION = {
    DISPOSITION_KEEP: "keep",
    DISPOSITION_INSPECT: "keep",
    DISPOSITION_UNRESOLVED: "mark_unresolved",
    # REPAIR requires a concrete edit verb; do not invent search_add here.
}


def _role(row: Mapping[str, Any]) -> str:
    return str(row.get("role") or "")


def _is_goal_action_row(row: Mapping[str, Any]) -> bool:
    role = _role(row)
    if role in GOAL_ROLE_MARKERS or role.endswith("_goal_action"):
        return True
    sid = str(row.get("segment_id") or "")
    return "goal_action" in sid


def _compact_evidence_refs(refs: Any, *, limit: int = 4) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(refs, list):
        return out
    for ref in refs[:limit]:
        if isinstance(ref, dict):
            out.append({
                "kind": ref.get("kind"),
                "source": ref.get("source"),
                "event_id": ref.get("event_id") or ref.get("id"),
                "dt_to_score_sec": ref.get("dt_to_score_sec"),
                "note": ref.get("note"),
                "used_as_fact": ref.get("used_as_fact"),
                "evidence_grade": "rule_or_event_association",
            })
        elif ref:
            out.append({"ref": str(ref), "evidence_grade": "opaque_ref"})
    return out


def _is_replay_basis(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Record how is_replay was asserted — never treat as visual LIVE proof."""
    return {
        "is_replay": bool(row.get("is_replay")),
        "shot_kind": row.get("shot_kind"),
        "basis": "composer_rule_or_event_label",
        "not_visual_first_live": True,
        "note": (
            "is_replay=false / shot_kind=live are Rule Composer labels from "
            "event/chain association; they do not certify FIRST_LIVE_VERIFIED."
        ),
    }


def _prior_obs_for_segment(
    segment_id: str,
    prior_observations: Optional[Sequence[Mapping[str, Any]]],
) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    for obs in prior_observations or []:
        if not isinstance(obs, dict):
            continue
        anchor = str(obs.get("anchor_id") or "")
        sid_match = segment_id and (
            anchor.endswith(segment_id)
            or segment_id in anchor
            or obs.get("segment_id") == segment_id
        )
        vlm = obs.get("vlm") if isinstance(obs.get("vlm"), dict) else {}
        if not sid_match and segment_id not in str(vlm.get("cited_frame_ids") or ""):
            # also match when request targeted this edl anchor
            if f"edl:{segment_id}" not in anchor and segment_id not in str(obs.get("request_id") or ""):
                continue
        hits.append({
            "request_id": obs.get("request_id"),
            "anchor_id": obs.get("anchor_id") or f"edl:{segment_id}",
            "provider_mode": obs.get("provider_mode"),
            "model": obs.get("model"),
            "observed_shot": vlm.get("observed_shot"),
            "observed_net": vlm.get("observed_net"),
            "live_or_replay": vlm.get("live_or_replay"),
            "scoreboard_only": vlm.get("scoreboard_only"),
            "fact_verified": bool(obs.get("fact_verified") or vlm.get("fact_verified")),
            "observation_only": True if obs.get("observation_only", True) else bool(vlm.get("observation_only")),
            "cited_frame_ids": list(vlm.get("cited_frame_ids") or [])[:4],
            "confidence": vlm.get("confidence"),
            "cannot_certify_first_live": True,
        })
    return hits[:3]


def _visual_verification_status(
    row: Mapping[str, Any],
    hist_obs: Sequence[Mapping[str, Any]],
) -> str:
    fls = str(row.get("first_live_status") or "").upper()
    if fls in ("FIRST_LIVE_VERIFIED",):
        # Preserve agent-bound claim if already present; handoff does not create it.
        return fls
    if fls in ("NOT_VERIFIED", "UNKNOWN") or row.get("agent_bound"):
        return VISUAL_AGENT_BOUND_UNVERIFIED
    if hist_obs:
        return VISUAL_HISTORICAL_OBS_ONLY
    return VISUAL_NOT_OBSERVED


def _suggested_disposition(
    row: Mapping[str, Any],
    *,
    visual_status: str,
    hist_obs: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    media_in, media_out = row.get("media_in"), row.get("media_out")
    has_window = media_in is not None and media_out is not None
    complete = row.get("goal_action_complete")
    blocking = [str(x) for x in (row.get("blocking_reasons") or []) if x]

    if not has_window:
        return {
            "disposition": DISPOSITION_REPAIR,
            "rationale": "missing_media_window; need local repair/search before keep",
            "prefer_tools": False,
            "prefer_actions": ["search_add", "replace"],
        }
    if complete is False:
        return {
            "disposition": DISPOSITION_REPAIR,
            "rationale": "goal_action_complete=false; composer candidate incomplete",
            "prefer_tools": True,
            "prefer_actions": ["search_add", "replace", "trim"],
        }

    # Historical observation: reusable, never first-LIVE. Decide keep vs inspect.
    if hist_obs:
        shot_seen = any(h.get("observed_shot") is True for h in hist_obs)
        if shot_seen:
            return {
                "disposition": DISPOSITION_KEEP,
                "rationale": (
                    "historical_vlm_observation_present_with_observed_shot; "
                    "keep composer window; still NOT_FIRST_LIVE_CERTIFIED"
                ),
                "prefer_tools": False,
                "prefer_actions": ["keep"],
            }
        return {
            "disposition": DISPOSITION_INSPECT,
            "rationale": (
                "historical_vlm_observation_lacks_observed_shot; "
                "directed re-observe allowed; do not blanket re-search all goals"
            ),
            "prefer_tools": True,
            "prefer_actions": ["keep"],
        }

    if visual_status == VISUAL_NOT_OBSERVED or any(
        b in (
            "awaiting_internal_media_verification",
            "semantic_unverified",
            "phase5_candidate_delivery",
        )
        for b in blocking
    ):
        return {
            "disposition": DISPOSITION_INSPECT,
            "rationale": (
                "composer_candidate_present_but_visually_unverified; "
                "prefer vlm_observe on edl trusted anchor before repair"
            ),
            "prefer_tools": True,
            "prefer_actions": ["keep"],
        }

    if visual_status == VISUAL_AGENT_BOUND_UNVERIFIED:
        return {
            "disposition": DISPOSITION_UNRESOLVED,
            "rationale": "agent_bound_but_first_live_still_unverified; do not invent repair",
            "prefer_tools": False,
            "prefer_actions": ["mark_unresolved"],
        }

    return {
        "disposition": DISPOSITION_KEEP,
        "rationale": "composer_candidate_structurally_usable; no new visual gap flagged",
        "prefer_tools": False,
        "prefer_actions": ["keep"],
    }


def project_segment_handoff(
    row: Mapping[str, Any],
    *,
    prior_observations: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Project one EDL row into a compact handoff record (no new inference of LIVE)."""
    segment_id = str(row.get("segment_id") or "")
    hist = _prior_obs_for_segment(segment_id, prior_observations)
    visual = _visual_verification_status(row, hist)
    suggestion = _suggested_disposition(row, visual_status=visual, hist_obs=hist)
    return {
        "segment_id": segment_id or None,
        "role": _role(row) or None,
        "media_in": row.get("media_in"),
        "media_out": row.get("media_out"),
        "event_ids": list(row.get("event_ids") or [])[:6],
        "frame_ids": list(row.get("frame_ids") or [])[:6],
        "time_provenance": dict(row["time_provenance"])
        if isinstance(row.get("time_provenance"), dict)
        else row.get("time_provenance"),
        "evidence_refs": _compact_evidence_refs(row.get("evidence_refs")),
        "selection_reason": row.get("selection_reason"),
        "render_eligibility": row.get("render_eligibility"),
        "blocking_reasons": list(row.get("blocking_reasons") or [])[:8],
        "is_replay": bool(row.get("is_replay")),
        "is_replay_basis": _is_replay_basis(row),
        "visual_verification_status": visual,
        "first_live_status_on_row": row.get("first_live_status"),
        "goal_anchor_t_sec": row.get("goal_anchor_t_sec"),
        "goal_action_complete": row.get("goal_action_complete"),
        "trusted_anchor_id": f"edl:{segment_id}" if segment_id else None,
        "historical_observations": hist,
        "suggested_planner_disposition": suggestion,
        "evidence_grades": {
            "event_association": bool(row.get("event_ids")),
            "rule_inference": True,
            "visual_observation": bool(hist) or visual in (
                VISUAL_HISTORICAL_OBS_ONLY,
                VISUAL_AGENT_BOUND_UNVERIFIED,
            ),
            "first_live_verified": visual == "FIRST_LIVE_VERIFIED",
        },
        "claims_forbidden": [
            "Do not treat is_replay=false as FIRST_LIVE_VERIFIED",
            "Do not treat scoreboard confirmation as goal-action proof",
            "Do not upgrade historical VLM observation to first-LIVE certification",
        ],
    }


def build_composer_evidence_handoff(
    edl: Sequence[Mapping[str, Any]],
    *,
    prior_observations: Optional[Sequence[Mapping[str, Any]]] = None,
    include_non_goal: bool = False,
    max_segments: int = 6,
) -> Dict[str, Any]:
    """Build additive Planner payload from existing composer/Phase5 EDL rows."""
    segments: List[Dict[str, Any]] = []
    for row in edl:
        if not isinstance(row, dict):
            continue
        if not include_non_goal and not _is_goal_action_row(row):
            continue
        segments.append(
            project_segment_handoff(row, prior_observations=prior_observations)
        )
        if len(segments) >= max_segments:
            break
    by_id = {
        str(s.get("segment_id")): s
        for s in segments
        if s.get("segment_id")
    }
    return {
        "schema": HANDOFF_SCHEMA,
        "source": "phase5_candidate_edl_projection",
        "composer_reexecuted": False,
        "segment_count": len(segments),
        "segments": by_id,
        "segment_order": [s.get("segment_id") for s in segments],
        "decision_protocol": {
            "KEEP": "revision_intents.action=keep; no EDL edit",
            "INSPECT": "revision_intents.action=keep + video_tool_requests on trusted edl anchor",
            "REPAIR": "revision_intents.action in search_add|replace|trim|drop|reorder with evidence",
            "UNRESOLVED": "revision_intents.action=mark_unresolved; do not force edit",
        },
        "note": (
            "Handoff projects existing composer/Phase5 fields only. "
            "Rule inference and event links are not visual verification."
        ),
    }


def map_disposition_to_action(raw: Any) -> Optional[str]:
    """Map KEEP/INSPECT/REPAIR/UNRESOLVED (or aliases) onto existing actions.

    REPAIR alone returns None — caller must supply a concrete edit verb.
    """
    s = str(raw or "").strip()
    if not s:
        return None
    key = s.upper().replace("-", "_")
    if key in ("KEEP", "KEEP_CANDIDATE", "RETAIN"):
        return "keep"
    if key in ("INSPECT", "OBSERVE", "NEED_OBSERVATION", "KEEP_AND_INSPECT"):
        return "keep"
    if key in ("UNRESOLVED", "DEFER", "UNKNOWN"):
        return "mark_unresolved"
    if key in ("REPAIR", "FIX"):
        return None
    return None


def normalize_intent_disposition(it: Mapping[str, Any]) -> Dict[str, Any]:
    """Return optional disposition metadata for a revision_intent object."""
    raw = it.get("disposition") or it.get("composer_disposition") or it.get("decision")
    if raw is None and isinstance(it.get("action"), str):
        act_u = it["action"].strip().upper()
        if act_u in (
            DISPOSITION_KEEP, DISPOSITION_INSPECT,
            DISPOSITION_REPAIR, DISPOSITION_UNRESOLVED,
        ):
            raw = act_u
    if raw is None:
        return {}
    mapped = map_disposition_to_action(raw)
    return {
        "composer_disposition": str(raw).upper(),
        "disposition_mapped_action": mapped,
        "disposition_needs_concrete_repair": str(raw).upper() == DISPOSITION_REPAIR and mapped is None,
    }
