"""Story-level Revision Planner — narrative purpose per edit; protect goal anchors.

Reuses EDL action protocol: search_add / replace / trim / drop / reorder / keep / mark_unresolved.
Does not invent media timestamps. Offline mode must not pretend KEEP when issues
remain needs_video_verify without semantic confirmation.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from .story_timeline import protected_goal_segment_ids

ALLOWED_ACTIONS = {
    "search_add",
    "replace",
    "trim",
    "drop",
    "reorder",
    "keep",
    "mark_unresolved",
}


def _protect_filter(
    intents: Sequence[Mapping[str, Any]],
    protect_ids: Sequence[str],
) -> List[Dict[str, Any]]:
    """Refuse mutating protected goal_action segments without explicit overturn evidence."""
    out: List[Dict[str, Any]] = []
    protect = set(protect_ids)
    for it in intents:
        action = str(it.get("action") or "")
        sid = str(it.get("target_segment_id") or "")
        if (
            sid in protect
            and action in ("drop", "trim", "replace", "reorder")
            and not it.get("allow_modify_protected_goal")
            and not it.get("overturn_evidence_refs")
        ):
            out.append(
                {
                    **dict(it),
                    "action": "keep",
                    "blocked_original_action": action,
                    "block_reason": "protected_goal_anchor_without_overturn_evidence",
                    "narrative_purpose": it.get("narrative_purpose")
                    or "preserve_confirmed_goal_action",
                }
            )
            continue
        out.append(dict(it))
    return out


def plan_from_diagnosis(
    diagnosis: Mapping[str, Any],
    *,
    observations: Optional[Mapping[str, Any]] = None,
    offline: bool = True,
    fixture_intents: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Produce story-level revision plan with explicit decision.

    Decision rules (honest):
    - critical structure_inferred (replay etc.) → REVISE intents
    - only needs_video_verify and offline/no semantic → UNRESOLVED (retain baseline)
    - no actionable issues → KEEP
    - fixture_intents when provided (tests) override auto intents but still pass protect filter
    """
    issues = list(diagnosis.get("issues") or [])
    protect = list(diagnosis.get("protected_goal_segment_ids") or [])
    if not protect:
        # Fallback from timeline segments if critic omitted
        for seg in (diagnosis.get("timeline") or {}).get("segments") or []:
            if "goal_action" in str(seg.get("role") or ""):
                protect.append(str(seg.get("segment_id")))

    semantic_ok = bool(
        observations
        and observations.get("semantic_provider_used")
        and not observations.get("fixture_or_offline")
    )

    critical_struct = [
        i
        for i in issues
        if i.get("severity") == "critical"
        and i.get("evidence_sufficiency") in ("structure_inferred", "observed")
        and i.get("category") not in ("input_integrity",)
    ]
    input_blockers = [
        i for i in issues if i.get("category") == "input_integrity" and i.get("severity") == "critical"
    ]
    needs_verify = [
        i for i in issues if i.get("evidence_sufficiency") == "needs_video_verify"
    ]

    intents: List[Dict[str, Any]] = []
    decision = "KEEP"
    rationale_parts: List[str] = []

    if input_blockers:
        decision = "UNRESOLVED"
        rationale_parts.append("critical_input_integrity_blockers")
        for i, iss in enumerate(input_blockers):
            intents.append(
                {
                    "intent_id": f"unresolved_input_{i}",
                    "action": "mark_unresolved",
                    "issue_id": iss.get("issue_id"),
                    "narrative_purpose": "cannot_revise_without_required_inputs",
                    "rationale": iss.get("observation"),
                    "expected_improvement": "none_until_inputs_fixed",
                    "risk": "fail_closed",
                    "evidence_refs": [{"kind": "diagnosis", "ref": iss.get("issue_id")}],
                }
            )
    elif fixture_intents is not None:
        intents = [dict(x) for x in fixture_intents]
        actions = {str(x.get("action")) for x in intents}
        if actions <= {"keep"} or not intents:
            decision = "KEEP"
        elif "mark_unresolved" in actions and actions <= {"keep", "mark_unresolved"}:
            decision = "UNRESOLVED"
        else:
            decision = "REVISE"
        rationale_parts.append("fixture_intents")
    elif critical_struct:
        decision = "REVISE"
        rationale_parts.append("critical_structure_or_observed_defects")
        for i, iss in enumerate(critical_struct):
            sids = list(iss.get("segment_ids") or [])
            action = "drop" if iss.get("category") == "replay_risk" else "mark_unresolved"
            if action == "drop" and sids and sids[0] in protect:
                action = "mark_unresolved"
            intents.append(
                {
                    "intent_id": f"rev_crit_{i}",
                    "action": action,
                    "issue_id": iss.get("issue_id"),
                    "target_segment_id": sids[0] if sids else None,
                    "narrative_purpose": {
                        "replay_risk": "remove_forbidden_replay_material",
                        "redundancy": "remove_duplicate_shot",
                        "timeline_integrity": "restore_cut_edl_alignment",
                    }.get(str(iss.get("category")), "address_critical_defect"),
                    "rationale": iss.get("narrative_problem"),
                    "expected_improvement": iss.get("suggested_fix"),
                    "risk": "must_not_invent_timestamps",
                    "evidence_refs": [
                        {
                            "kind": "diagnosis",
                            "ref": iss.get("issue_id"),
                            "sufficiency": iss.get("evidence_sufficiency"),
                        }
                    ],
                }
            )
    elif needs_verify and (offline or not semantic_ok):
        decision = "UNRESOLVED"
        rationale_parts.append(
            "needs_video_verify_without_semantic_confirmation_not_disguised_as_keep"
        )
        for i, iss in enumerate(needs_verify):
            intents.append(
                {
                    "intent_id": f"unresolved_nv_{i}",
                    "action": "mark_unresolved",
                    "issue_id": iss.get("issue_id"),
                    "target_segment_id": (iss.get("segment_ids") or [None])[0],
                    "narrative_purpose": "pending_layered_semantic_confirmation",
                    "rationale": iss.get("narrative_problem"),
                    "expected_improvement": "resolve_after_authorized_multimodal_pass",
                    "risk": "do_not_guess_edits",
                    "evidence_refs": [
                        {
                            "kind": "diagnosis",
                            "ref": iss.get("issue_id"),
                            "sufficiency": "needs_video_verify",
                        }
                    ],
                }
            )
    else:
        decision = "KEEP"
        rationale_parts.append("no_actionable_confirmed_defects")
        intents.append(
            {
                "intent_id": "keep_baseline",
                "action": "keep",
                "narrative_purpose": "retain_v3r_baseline",
                "rationale": "No confirmed revision targets after diagnosis.",
                "expected_improvement": "none",
                "risk": "none",
                "evidence_refs": [],
            }
        )

    intents = _protect_filter(intents, protect)
    # Normalize actions
    for it in intents:
        if str(it.get("action")) not in ALLOWED_ACTIONS:
            it["action"] = "mark_unresolved"
            it["normalize_note"] = "unknown_action_mapped_to_mark_unresolved"

    return {
        "schema": "v3a_story_revision_plan_v1",
        "decision": decision,
        "rationale": ";".join(rationale_parts),
        "offline": offline,
        "semantic_confirmation": semantic_ok,
        "protected_goal_segment_ids": protect,
        "revision_intents": intents,
        "narrative_purposes_supported": [
            "supplement_buildup",
            "adjust_non_goal_segments",
            "repair_transitions",
            "drop_redundant_or_meaningless",
            "improve_ending_closure",
            "preserve_true_match_time_and_causality",
            "protect_confirmed_goal_anchors",
        ],
        "constraints": {
            "no_replay_or_slowmo": True,
            "no_scoreboard_time_as_goal_action": True,
            "new_footage_must_trace_to_source_pts": True,
            "max_rounds": 3,
        },
    }
