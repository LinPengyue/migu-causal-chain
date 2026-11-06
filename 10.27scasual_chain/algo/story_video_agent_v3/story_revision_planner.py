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


def _intents_from_verified_search(
    search_results: Mapping[str, Any],
    protect: Sequence[str],
) -> List[Dict[str, Any]]:
    """Build executable search_add intents from verified LIVE candidates."""
    intents: List[Dict[str, Any]] = []
    used_issues: set = set()
    for i, c in enumerate(search_results.get("verified_candidates") or []):
        if not isinstance(c, dict):
            continue
        if len(intents) >= 2:
            break  # keep candidate reviewable: at most two search-bound inserts
        issue_id = str(c.get("issue_id") or "")
        # One insert per issue to keep EDL changes focused and reviewable.
        if issue_id and issue_id in used_issues:
            continue
        role = str(c.get("role") or "buildup_bridge_action")
        if "goal_action" in role:
            continue  # never invent goal anchors from search
        start = c.get("source_pts_start")
        end = c.get("source_pts_end")
        if start is None or end is None:
            continue
        insert_after = c.get("insert_after_segment_id")
        if insert_after and str(insert_after) in set(protect):
            # Inserting *after* a protected goal is fine; do not mutate the goal row.
            pass
        cand_id = str(c.get("candidate_id") or f"auto_{i}")
        intents.append(
            {
                "intent_id": f"search_add_{i}_{cand_id}",
                "action": "search_add",
                "issue_id": issue_id or None,
                "role": role,
                "anchor_id": f"search:{cand_id}",
                "target_segment_id": None,
                "insert_after_segment_id": insert_after,
                "before_segment_id": c.get("before_segment_id"),
                "bound_source_window": {
                    "start": float(start),
                    "end": float(end),
                },
                "new_segment_id": f"seg_{role}_{cand_id}".replace(":", "_")[:80],
                "event_ids": [c.get("event_id")] if c.get("event_id") else [],
                "narrative_purpose": c.get("narrative_function") or "supplement_from_search",
                "rationale": (
                    f"Verified LIVE event {c.get('event_id')} @ "
                    f"{start}-{end}s for issue {issue_id}"
                ),
                "expected_improvement": (
                    "Bridge sparse/abrupt story beats or extend ending closure "
                    "using real source footage"
                ),
                "risk": ",".join(c.get("risks") or []) or "search_bound_unverified_first_live",
                "goal_anchor_impact": "none_insert_non_goal_only",
                "causality_impact": "preserves_source_pts_order_relative_to_neighbors",
                "affected_segments": [insert_after, c.get("before_segment_id")],
                "evidence_refs": [
                    {"kind": "diagnosis", "ref": issue_id},
                    {"kind": "search_candidate", "ref": cand_id},
                    {
                        "kind": "source_pts",
                        "ref": f"{start}:{end}",
                        "event_id": c.get("event_id"),
                    },
                    {
                        "kind": "live_credibility",
                        "ref": (c.get("live") or {}).get("broadcast_phase"),
                        "confidence": c.get("confidence"),
                    },
                ],
            }
        )
        if issue_id:
            used_issues.add(issue_id)
    return intents


def _structure_intents(issues: Sequence[Mapping[str, Any]], protect: Sequence[str]) -> List[Dict[str, Any]]:
    """Executable structure repairs (drop / reorder) that do not invent PTS."""
    intents: List[Dict[str, Any]] = []
    protect_set = set(protect)
    for i, iss in enumerate(issues):
        cat = str(iss.get("category") or "")
        sids = [str(x) for x in (iss.get("segment_ids") or []) if x]
        if cat == "replay_risk" and sids:
            sid = sids[0]
            action = "mark_unresolved" if sid in protect_set else "drop"
            intents.append(
                {
                    "intent_id": f"struct_drop_replay_{i}",
                    "action": action,
                    "issue_id": iss.get("issue_id"),
                    "target_segment_id": sid,
                    "narrative_purpose": "remove_forbidden_replay_material",
                    "rationale": iss.get("narrative_problem"),
                    "expected_improvement": "eliminate_replay_or_slowmo_from_delivery",
                    "risk": "must_not_touch_verified_goals",
                    "goal_anchor_impact": "none" if sid not in protect_set else "blocked",
                    "evidence_refs": [{"kind": "diagnosis", "ref": iss.get("issue_id")}],
                }
            )
        elif cat == "redundancy" and len(sids) >= 2:
            # Drop the later duplicate; never drop a protected goal.
            drop_sid = sids[-1] if sids[-1] not in protect_set else (
                sids[0] if sids[0] not in protect_set else None
            )
            if drop_sid:
                intents.append(
                    {
                        "intent_id": f"struct_drop_dup_{i}",
                        "action": "drop",
                        "issue_id": iss.get("issue_id"),
                        "target_segment_id": drop_sid,
                        "narrative_purpose": "remove_duplicate_shot",
                        "rationale": iss.get("narrative_problem"),
                        "expected_improvement": "remove_redundant_repeat",
                        "risk": "low",
                        "goal_anchor_impact": "none",
                        "evidence_refs": [{"kind": "diagnosis", "ref": iss.get("issue_id")}],
                    }
                )
        elif cat == "narrative_order" and sids:
            # Explicit reorder: move misplaced development after climax to before climax
            # when diagnosis lists the misplaced segment ids.
            intents.append(
                {
                    "intent_id": f"struct_reorder_{i}",
                    "action": "reorder",
                    "issue_id": iss.get("issue_id"),
                    "target_segment_id": sids[0],
                    "segment_order_hint": "move_listed_before_first_climax",
                    "move_segment_ids": sids,
                    "narrative_purpose": "restore_rising_action_before_climax",
                    "rationale": iss.get("narrative_problem"),
                    "expected_improvement": "fix_beat_order_without_new_footage",
                    "risk": "must_not_reorder_protected_goals",
                    "goal_anchor_impact": "goals_stay_fixed",
                    "evidence_refs": [
                        {
                            "kind": "diagnosis",
                            "ref": iss.get("issue_id"),
                            "sufficiency": iss.get("evidence_sufficiency"),
                        }
                    ],
                }
            )
    return intents


def plan_from_diagnosis(
    diagnosis: Mapping[str, Any],
    *,
    observations: Optional[Mapping[str, Any]] = None,
    offline: bool = True,
    fixture_intents: Optional[Sequence[Mapping[str, Any]]] = None,
    search_results: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Produce story-level revision plan with explicit decision.

    Decision rules (honest):
    - critical structure_inferred (replay etc.) → REVISE intents
    - needs_video_verify → run/consume search; REVISE only with verified PTS candidates
    - search failed / no credible material → UNRESOLVED (not fake KEEP)
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
    search_ok = bool(
        search_results
        and search_results.get("search_success")
        and (search_results.get("verified_candidates") or [])
    )

    critical_struct = [
        i
        for i in issues
        if i.get("severity") == "critical"
        and i.get("evidence_sufficiency") in ("structure_inferred", "observed")
        and i.get("category") not in ("input_integrity",)
    ]
    major_struct = [
        i
        for i in issues
        if i.get("severity") in ("critical", "major")
        and i.get("evidence_sufficiency") in ("structure_inferred", "observed")
        and i.get("category") in (
            "replay_risk", "redundancy", "narrative_order", "narrative_causality",
            "timeline_integrity",
        )
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
    else:
        # Prefer executable search-bound inserts when available.
        search_intents = _intents_from_verified_search(search_results or {}, protect) if search_ok else []
        struct_intents = _structure_intents(major_struct or critical_struct, protect)
        # Filter structure intents that would only mark_unresolved
        struct_exec = [
            it for it in struct_intents
            if str(it.get("action")) in ("drop", "reorder", "replace", "trim", "search_add")
        ]

        if search_intents or struct_exec:
            decision = "REVISE"
            intents.extend(search_intents)
            intents.extend(struct_exec)
            if search_intents:
                rationale_parts.append("verified_search_candidates_bound_to_source_pts")
            if struct_exec:
                rationale_parts.append("structure_inferred_executable_repairs")
        elif critical_struct and not search_ok:
            # Legacy critical path without search material.
            decision = "REVISE"
            rationale_parts.append("critical_structure_or_observed_defects")
            intents.extend(_structure_intents(critical_struct, protect) or [
                {
                    "intent_id": f"rev_crit_{i}",
                    "action": "mark_unresolved",
                    "issue_id": iss.get("issue_id"),
                    "target_segment_id": (iss.get("segment_ids") or [None])[0],
                    "narrative_purpose": "address_critical_defect",
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
                for i, iss in enumerate(critical_struct)
            ])
            # If all became mark_unresolved, normalize later.
        elif needs_verify:
            decision = "UNRESOLVED"
            rationale_parts.append(
                "needs_video_verify_and_search_found_no_credible_live_material"
                if search_results is not None
                else "needs_video_verify_without_search_or_semantic_confirmation"
            )
            for i, iss in enumerate(needs_verify):
                intents.append(
                    {
                        "intent_id": f"unresolved_nv_{i}",
                        "action": "mark_unresolved",
                        "issue_id": iss.get("issue_id"),
                        "target_segment_id": (iss.get("segment_ids") or [None])[0],
                        "narrative_purpose": "pending_search_or_semantic_confirmation",
                        "rationale": iss.get("narrative_problem"),
                        "expected_improvement": "resolve_after_search_or_authorized_multimodal_pass",
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

    # Honesty: REVISE with only keep/mark_unresolved → UNRESOLVED
    acts = {str(it.get("action") or "") for it in intents}
    if decision == "REVISE" and (not acts or acts <= {"keep", "mark_unresolved"}):
        decision = "UNRESOLVED"
        rationale_parts.append("revise_without_mutating_intents_normalized")

    return {
        "schema": "v3a_story_revision_plan_v1",
        "decision": decision,
        "rationale": ";".join(rationale_parts),
        "offline": offline,
        "semantic_confirmation": semantic_ok,
        "search_confirmation": search_ok,
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
