"""Story-level Revision Planner — problem-driven edits; protect goal anchors.

Reuses EDL action protocol: search_add / replace / trim / drop / reorder / keep / mark_unresolved.
Does not invent media timestamps. Offline mode must not pretend KEEP when issues
remain needs_video_verify without semantic confirmation.

Phase 6: structural time-gaps alone are HYPOTHESIS_NEEDS_VIDEO — do not auto
search_add merely because source PTS gaps are large. Duration pad is never a
quality proxy. Each mutating intent must bind issue→evidence→edit→expected_effect.
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
    "unresolved",  # alias → mark_unresolved
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
    *,
    require_narrative_fit: bool = False,
) -> List[Dict[str, Any]]:
    """Build intents from Search candidates with explicit evidence-tier gating.

    EVENT_PTS_CANDIDATE (event-chain LIVE + PTS) may be proposed for observation
    but is NOT an executable safe revision. Only FIRST_LIVE_VERIFIED windows may
    become search_add that mutates the working EDL.
    """
    intents: List[Dict[str, Any]] = []
    used_issues: set = set()
    # Prefer precomputed executable list when present; else fall back to annotated verified.
    pool = list(search_results.get("executable_first_live_candidates") or [])
    if not pool:
        pool = [
            c
            for c in (search_results.get("verified_candidates") or [])
            if isinstance(c, dict) and c.get("executable_safe_revision")
        ]
    if require_narrative_fit:
        # Safety is independent of narrative value. A FIRST_LIVE clip without
        # video-observed before→candidate→after gains is proposal-only.
        all_candidates = [
            c for c in (search_results.get("verified_candidates") or [])
            if isinstance(c, dict)
        ]
        pool = [
            c for c in pool
            if c.get("narrative_fit_supports_insert") is True
            and (c.get("narrative_fit") or {}).get("binding_valid") is True
        ]
        propose_pool = [
            c for c in all_candidates
            if c not in pool and not c.get("narrative_fit_rejects_insert")
        ]
    else:
        propose_pool = list(search_results.get("propose_only_event_pts_candidates") or [])
        if not propose_pool:
            propose_pool = [
                c
                for c in (search_results.get("verified_candidates") or [])
                if isinstance(c, dict) and not c.get("executable_safe_revision")
            ]

    def _mk_base(c: Mapping[str, Any], i: int) -> Dict[str, Any]:
        issue_id = str(c.get("issue_id") or "")
        role = str(c.get("role") or "buildup_bridge_action")
        start = c.get("source_pts_start")
        end = c.get("source_pts_end")
        insert_after = c.get("insert_after_segment_id")
        sw = c.get("search_window") or {}
        order_claim = "requires_apply_neighbor_pts_check"
        if (
            start is not None
            and end is not None
            and isinstance(sw, dict)
            and sw.get("lo") is not None
            and sw.get("hi") is not None
            and float(start) >= float(sw["lo"]) - 1e-3
            and float(end) <= float(sw["hi"]) + 1e-3
            and sw.get("kind") in ("bridge_between_cuts", "post_climax_aftermath")
        ):
            order_claim = "search_window_bounded_between_neighbors"
        cand_id = str(c.get("candidate_id") or f"auto_{i}")
        tier = str(c.get("evidence_tier") or "EVENT_PTS_CANDIDATE")
        return {
            "intent_id": f"search_add_{i}_{cand_id}",
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
            "evidence_tier": tier,
            "first_live_status": c.get("first_live_status"),
            "executable_safe_revision": bool(c.get("executable_safe_revision")),
            "expected_improvement": (
                "If and only if the bound footage supplies the missing narrative "
                "information for the diagnosed issue — not merely longer runtime"
            ),
            "expected_observable_improvement": (
                "Adjacent story beats should show a clearer causal/emotional transition "
                "attributable to the inserted window; falsify if insert is redundant, "
                "replay-like, or breaks chronology"
            ),
            "defect_cause_hypothesis": (
                "Missing intermediate narrative information between adjacent cuts"
            ),
            "falsification_evidence": (
                "Insert adds duration without new story info; breaks PTS order; "
                "introduces replay/scoreboard-as-action; or original issue remains"
            ),
            "duration_pad_not_quality_proxy": True,
            "risk": ",".join(c.get("risks") or []) or "search_bound_unverified_first_live",
            "goal_anchor_impact": "none_insert_non_goal_only",
            "causality_impact": order_claim,
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
                    "kind": "evidence_tier",
                    "ref": tier,
                    "first_live_status": c.get("first_live_status"),
                },
                {
                    "kind": "event_chain_live_credibility",
                    "ref": (c.get("live") or {}).get("broadcast_phase"),
                    "confidence": c.get("confidence"),
                    "note": "Not equivalent to FIRST_LIVE_VERIFIED",
                },
            ],
            "story_defect_fit": c.get("story_defect_fit"),
            "narrative_fit_status": c.get("narrative_fit_status"),
            "narrative_fit": c.get("narrative_fit"),
            "narrative_context": c.get("narrative_context"),
            "gap_balance": c.get("gap_balance"),
            "reject_or_defer_reason": c.get("reject_or_defer_reason"),
        }

    for i, c in enumerate(pool):
        if not isinstance(c, dict):
            continue
        if len([x for x in intents if x.get("action") == "search_add"]) >= 2:
            break
        issue_id = str(c.get("issue_id") or "")
        if issue_id and issue_id in used_issues:
            continue
        if "goal_action" in str(c.get("role") or ""):
            continue
        if c.get("source_pts_start") is None or c.get("source_pts_end") is None:
            continue
        insert_after = c.get("insert_after_segment_id")
        if insert_after and str(insert_after) in set(protect):
            pass
        cand_id = str(c.get("candidate_id") or f"auto_{i}")
        base = _mk_base(c, i)
        base.update(
            {
                "action": "search_add",
                "rationale": (
                    f"FIRST_LIVE_VERIFIED event {c.get('event_id')} @ "
                    f"{c.get('source_pts_start')}-{c.get('source_pts_end')}s for issue {issue_id}"
                ),
                "why_candidate_solves_problem": (
                    f"Candidate {cand_id} has authenticated first-live attestation in the "
                    f"gap for issue {issue_id}; still requires confirmed story defect and "
                    "post-edit verifier — event-chain LIVE alone is insufficient"
                ),
            }
        )
        intents.append(base)
        if issue_id:
            used_issues.add(issue_id)

    # Propose-only EVENT_PTS rows: visible mark_unresolved, never silent search_add.
    for i, c in enumerate(propose_pool):
        if not isinstance(c, dict):
            continue
        if len(intents) >= 6:
            break
        issue_id = str(c.get("issue_id") or "")
        if "goal_action" in str(c.get("role") or ""):
            continue
        if c.get("source_pts_start") is None or c.get("source_pts_end") is None:
            continue
        # Skip issues already covered by an executable search_add.
        if issue_id and issue_id in used_issues:
            continue
        cand_id = str(c.get("candidate_id") or f"propose_{i}")
        base = _mk_base(c, 100 + i)
        base.update(
            {
                "intent_id": f"propose_observe_{i}_{cand_id}",
                "action": "mark_unresolved",
                "blocked_original_action": "search_add",
                "block_reason": (
                    "candidate_not_first_live_or_narrative_fit_supported;"
                    "propose_for_triplet_video_review_only"
                ),
                "rationale": (
                    f"EVENT_PTS_CANDIDATE {cand_id} @ "
                    f"{c.get('source_pts_start')}-{c.get('source_pts_end')}s is event-chain "
                    "LIVE/PTS or FIRST_LIVE evidence alone; defer apply until "
                    "video-triplet narrative fit confirms story value"
                ),
                "why_candidate_solves_problem": (
                    "Not claimed as a solved defect — event metadata screening only"
                ),
                "narrative_purpose": "defer_until_first_live_and_story_fit",
            }
        )
        intents.append(base)
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
        elif cat == "redundancy" and (len(sids) >= 2 or iss.get("preferred_drop_segment_id")):
            # Prefer audit-selected drop (non-goal contained in goal, etc.).
            drop_sid = iss.get("preferred_drop_segment_id")
            if drop_sid and str(drop_sid) in protect_set:
                drop_sid = None
            if not drop_sid and iss.get("duplicate_decision") == "human_review":
                intents.append(
                    {
                        "intent_id": f"struct_dup_human_{i}",
                        "action": "mark_unresolved",
                        "issue_id": iss.get("issue_id"),
                        "target_segment_id": sids[0] if sids else None,
                        "narrative_purpose": "human_review_ambiguous_duplicate",
                        "rationale": iss.get("observation") or iss.get("narrative_problem"),
                        "expected_improvement": "await_human_choice_of_keep_drop",
                        "risk": "do_not_auto_delete_ambiguous_pair",
                        "goal_anchor_impact": "none",
                        "evidence_refs": [{"kind": "diagnosis", "ref": iss.get("issue_id")}],
                    }
                )
                continue
            if not drop_sid and len(sids) >= 2:
                # Fallback: drop later non-protected segment.
                drop_sid = sids[-1] if sids[-1] not in protect_set else (
                    sids[0] if sids[0] not in protect_set else None
                )
            if drop_sid:
                intents.append(
                    {
                        "intent_id": f"struct_drop_dup_{i}",
                        "action": "drop",
                        "issue_id": iss.get("issue_id"),
                        "target_segment_id": str(drop_sid),
                        "narrative_purpose": "remove_duplicate_shot",
                        "rationale": iss.get("observation") or iss.get("narrative_problem"),
                        "expected_improvement": "remove_redundant_repeat_keep_verified_goal",
                        "risk": "low",
                        "goal_anchor_impact": "none",
                        "preferred_keep_segment_id": iss.get("preferred_keep_segment_id"),
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


def _issue_confirmed_for_mutate(iss: Mapping[str, Any]) -> bool:
    """Only confirmed story/structure defects may drive mutating search_add/trim/replace."""
    if iss.get("story_defect_confirmed") is True:
        return True
    if str(iss.get("diagnosis_status") or "") in (
        "CONFIRMED_STORY_DEFECT",
        "CONFIRMED_STRUCTURE_DEFECT",
    ):
        return True
    # Backward-compatible: explicit structure categories without semantic layer yet.
    if (
        iss.get("evidence_sufficiency") in ("structure_inferred", "observed")
        and iss.get("category")
        in (
            "replay_risk",
            "redundancy",
            "narrative_order",
            "narrative_causality",
            "timeline_integrity",
        )
    ):
        return True
    return False


def _annotate_problem_driven(intent: Dict[str, Any], iss: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Ensure issue→evidence→edit→expected_effect binding fields exist (no invention of facts)."""
    out = dict(intent)
    if iss:
        out.setdefault("issue_id", iss.get("issue_id"))
        out.setdefault(
            "original_problem",
            iss.get("observed_evidence") or iss.get("observation"),
        )
        out.setdefault(
            "why_hurts_story",
            iss.get("causal_explanation") or iss.get("narrative_problem"),
        )
        out.setdefault(
            "missing_information",
            iss.get("missing_information"),
        )
        out.setdefault("diagnosis_status", iss.get("diagnosis_status"))
        out.setdefault("story_defect_confirmed", iss.get("story_defect_confirmed"))
    out.setdefault("duration_pad_not_quality_proxy", True)
    out.setdefault(
        "answers",
        {
            "what_is_wrong": out.get("original_problem"),
            "why_it_hurts_understanding": out.get("why_hurts_story"),
            "what_to_add_drop_or_adjust": out.get("action"),
            "why_candidate_helps": out.get("why_candidate_solves_problem") or out.get("rationale"),
            "expected_observable_improvement": out.get("expected_observable_improvement")
            or out.get("expected_improvement"),
            "falsification_evidence": out.get("falsification_evidence"),
        },
    )
    return out


def plan_from_diagnosis(
    diagnosis: Mapping[str, Any],
    *,
    observations: Optional[Mapping[str, Any]] = None,
    offline: bool = True,
    fixture_intents: Optional[Sequence[Mapping[str, Any]]] = None,
    search_results: Optional[Mapping[str, Any]] = None,
    feedback_context: Optional[Mapping[str, Any]] = None,
    budget: Optional[Mapping[str, Any]] = None,
    require_narrative_fit: bool = False,
    keep_unconfirmed_temporal_gap: bool = False,
    use_fullcut_learning: bool = False,
) -> Dict[str, Any]:
    """Produce story-level revision plan with explicit decision.

    Decision rules (Phase 6 honest + Phase 8 feedback):
    - critical/major CONFIRMED structure defects → REVISE (drop/reorder/trim/replace)
    - HYPOTHESIS_NEEDS_VIDEO alone → UNRESOLVED (do not auto search_add on large PTS gaps)
    - search_add only when issue is a confirmed defect AND verified LIVE candidates exist
    - search failed / no credible material → UNRESOLVED (not fake KEEP)
    - no actionable confirmed issues → KEEP
    - fixture_intents when provided (tests) override auto intents but still pass protect filter
    - feedback_context (optional) blocks identical PTS/action retries without new evidence
    - if feedback wiped remaining LIVE options → stop (UNRESOLVED), do not force-insert
    """
    issues = list(diagnosis.get("issues") or [])
    issues_by_id = {
        str(i.get("issue_id")): i for i in issues if isinstance(i, dict) and i.get("issue_id")
    }
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
    # Prefer search results already filtered by evidence_search feedback_context.
    search_results = dict(search_results or {}) if search_results is not None else None
    if search_results is not None and feedback_context and not search_results.get(
        "feedback_filter_applied"
    ):
        from .story_evidence_search import _apply_feedback_to_candidates

        fb = _apply_feedback_to_candidates(
            list(search_results.get("verified_candidates") or []), feedback_context
        )
        search_results = {
            **search_results,
            **fb,
            "search_success": bool(fb.get("verified_candidates")),
        }
    # search_ok: any EVENT_PTS candidates (for propose/defer paths).
    # executable_search_ok: FIRST_LIVE_VERIFIED only (drives search_confirmation/REVISE).
    search_ok = bool(
        search_results
        and search_results.get("search_success")
        and (search_results.get("verified_candidates") or [])
    )
    executable_search_ok = bool(
        search_results
        and (
            search_results.get("executable_search_success")
            or any(
                isinstance(c, dict) and c.get("executable_safe_revision")
                for c in (search_results.get("verified_candidates") or [])
            )
        )
    )
    feedback_summary = None
    if feedback_context is not None:
        feedback_summary = feedback_context.get("summary") or feedback_context.get(
            "planner_context"
        )
        if feedback_summary is None and feedback_context.get("records") is not None:
            from .story_revision_feedback import summarize_feedback

            feedback_summary = summarize_feedback(list(feedback_context.get("records") or []))

    critical_struct = [
        i
        for i in issues
        if i.get("severity") == "critical"
        and _issue_confirmed_for_mutate(i)
        and i.get("category") not in ("input_integrity",)
    ]
    major_struct = [
        i
        for i in issues
        if (
            i.get("severity") in ("critical", "major")
            or (
                use_fullcut_learning
                and i.get("category") == "redundancy"
                and i.get("severity") == "minor"
                and i.get("preferred_drop_segment_id")
                and i.get("evidence_frame_refs")
                and str(i.get("evidence_tier") or "") == "DEFECT_CONFIRMED"
            )
        )
        and _issue_confirmed_for_mutate(i)
        and i.get("category") in (
            "replay_risk", "redundancy", "narrative_order", "narrative_causality",
            "timeline_integrity",
        )
    ]
    input_blockers = [
        i for i in issues if i.get("category") == "input_integrity" and i.get("severity") == "critical"
    ]
    hypotheses = [
        i
        for i in issues
        if str(i.get("diagnosis_status") or "") == "HYPOTHESIS_NEEDS_VIDEO"
        or (
            i.get("evidence_sufficiency") == "needs_video_verify"
            and not _issue_confirmed_for_mutate(i)
        )
    ]
    confirmed_for_search = [i for i in issues if _issue_confirmed_for_mutate(i)]
    confirmed_issue_ids = {
        str(i.get("issue_id")) for i in confirmed_for_search if i.get("issue_id")
    }

    intents: List[Dict[str, Any]] = []
    decision = "KEEP"
    rationale_parts: List[str] = []
    fullcut_edit_selection: Optional[Dict[str, Any]] = None

    if input_blockers:
        decision = "UNRESOLVED"
        rationale_parts.append("critical_input_integrity_blockers")
        for i, iss in enumerate(input_blockers):
            intents.append(
                _annotate_problem_driven(
                    {
                        "intent_id": f"unresolved_input_{i}",
                        "action": "mark_unresolved",
                        "issue_id": iss.get("issue_id"),
                        "narrative_purpose": "cannot_revise_without_required_inputs",
                        "rationale": iss.get("observation"),
                        "expected_improvement": "none_until_inputs_fixed",
                        "risk": "fail_closed",
                        "evidence_refs": [{"kind": "diagnosis", "ref": iss.get("issue_id")}],
                    },
                    iss,
                )
            )
    elif fixture_intents is not None:
        intents = [_annotate_problem_driven(dict(x), issues_by_id.get(str(x.get("issue_id") or ""))) for x in fixture_intents]
        actions = {str(x.get("action")) for x in intents}
        if actions <= {"keep"} or not intents:
            decision = "KEEP"
        elif actions <= {"keep", "mark_unresolved", "unresolved"}:
            decision = "UNRESOLVED"
        else:
            decision = "REVISE"
        rationale_parts.append("fixture_intents")
    else:
        # Search-bound inserts ONLY for confirmed defects (not mere PTS-gap hypotheses)
        # AND only FIRST_LIVE_VERIFIED executable candidates (see evidence tiers).
        search_intents_all = (
            _intents_from_verified_search(
                search_results or {}, protect,
                require_narrative_fit=require_narrative_fit,
            ) if search_ok else []
        )
        search_intents = []
        deferred_hypothesis_search = []
        for it in search_intents_all:
            iid = str(it.get("issue_id") or "")
            act = str(it.get("action") or "")
            annotated = _annotate_problem_driven(it, issues_by_id.get(iid))
            if act == "search_add" and iid and iid in confirmed_issue_ids:
                search_intents.append(annotated)
            elif act == "search_add":
                deferred_hypothesis_search.append(
                    _annotate_problem_driven(
                        {
                            **it,
                            "action": "mark_unresolved",
                            "blocked_original_action": "search_add",
                            "block_reason": (
                                "hypothesis_needs_video_not_confirmed_story_defect;"
                                "refusing_auto_add_on_large_source_gap_alone"
                            ),
                            "narrative_purpose": "defer_until_semantic_confirmation",
                        },
                        issues_by_id.get(iid),
                    )
                )
            else:
                # propose_observe / mark_unresolved from EVENT_PTS tier
                deferred_hypothesis_search.append(annotated)

        struct_intents = _structure_intents(major_struct or critical_struct, protect)
        struct_exec = [
            _annotate_problem_driven(it, issues_by_id.get(str(it.get("issue_id") or "")))
            for it in struct_intents
            if str(it.get("action")) in ("drop", "reorder", "replace", "trim", "search_add")
        ]

        if search_intents or struct_exec:
            decision = "REVISE"
            if use_fullcut_learning:
                from .story_fullcut_learning import prioritize_confirmed_edits

                fullcut_edit_selection = prioritize_confirmed_edits(
                    structure_intents=struct_exec,
                    insert_intents=search_intents,
                    feedback_context=feedback_context,
                    max_mutations=1,
                )
                intents.extend(fullcut_edit_selection["selected"])
                rationale_parts.append(str(fullcut_edit_selection["reason"]))
                if fullcut_edit_selection["deferred"]:
                    rationale_parts.append("other_edits_deferred_until_single_edit_verified")
            else:
                # Legacy offline-fixture behavior: retain test-controlled multiple edits.
                intents.extend(search_intents)
                intents.extend(struct_exec)
                if search_intents:
                    rationale_parts.append(
                        "confirmed_defect_plus_first_live_verified_search_candidates"
                    )
                if struct_exec:
                    rationale_parts.append("confirmed_structure_executable_repairs")
        elif critical_struct and not search_ok:
            decision = "REVISE"
            rationale_parts.append("critical_confirmed_structure_defects")
            intents.extend(
                [
                    _annotate_problem_driven(it, issues_by_id.get(str(it.get("issue_id") or "")))
                    for it in (
                        _structure_intents(critical_struct, protect)
                        or [
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
                        ]
                    )
                ]
            )
        elif (
            keep_unconfirmed_temporal_gap
            and hypotheses
            and not confirmed_for_search
            and all(
                bool(i.get("temporal_discontinuity_only"))
                for i in hypotheses
            )
        ):
            # An editor may intentionally jump 20+ minutes. Without video
            # evidence of omitted story state, no story defect was established.
            decision = "KEEP"
            rationale_parts.append("temporal_jump_alone_not_story_defect_keep_baseline")
            intents.append({
                "intent_id": "keep_unconfirmed_temporal_gap",
                "action": "keep",
                "narrative_purpose": "preserve_intentional_temporal_compression",
                "rationale": "Source-time discontinuity is an observation, not proof of missing narrative information.",
                "evidence_refs": [],
                "duration_pad_not_quality_proxy": True,
            })
        elif hypotheses or deferred_hypothesis_search:
            decision = "UNRESOLVED"
            rationale_parts.append(
                "hypothesis_needs_video_no_auto_search_add_on_gap_alone"
            )
            if deferred_hypothesis_search:
                intents.extend(deferred_hypothesis_search)
                rationale_parts.append("search_candidates_deferred_pending_semantic_confirmation")
            else:
                for i, iss in enumerate(hypotheses):
                    intents.append(
                        _annotate_problem_driven(
                            {
                                "intent_id": f"unresolved_hypothesis_{i}",
                                "action": "mark_unresolved",
                                "issue_id": iss.get("issue_id"),
                                "target_segment_id": (iss.get("segment_ids") or [None])[0],
                                "narrative_purpose": "await_video_semantic_confirmation",
                                "rationale": (
                                    "Structural gap is HYPOTHESIS_NEEDS_VIDEO; refusing to "
                                    "treat large source interval as confirmed story defect."
                                ),
                                "expected_improvement": "none_until_semantic_evidence",
                                "falsification_evidence": (
                                    "If video shows transition already clear, keep baseline"
                                ),
                                "risk": "do_not_guess_edits",
                                "evidence_refs": [
                                    {
                                        "kind": "diagnosis",
                                        "ref": iss.get("issue_id"),
                                        "sufficiency": "needs_video_verify",
                                        "diagnosis_status": iss.get("diagnosis_status"),
                                    }
                                ],
                            },
                            iss,
                        )
                    )
        else:
            decision = "KEEP"
            rationale_parts.append("no_actionable_confirmed_defects")
            intents.append(
                {
                    "intent_id": "keep_baseline",
                    "action": "keep",
                    "narrative_purpose": "retain_v3r_baseline",
                    "rationale": "No confirmed revision targets after semantic diagnosis layer.",
                    "expected_improvement": "none",
                    "risk": "none",
                    "evidence_refs": [],
                    "duration_pad_not_quality_proxy": True,
                    "answers": {
                        "what_is_wrong": None,
                        "why_it_hurts_understanding": None,
                        "what_to_add_drop_or_adjust": "keep",
                        "why_candidate_helps": None,
                        "expected_observable_improvement": "none",
                        "falsification_evidence": None,
                    },
                }
            )

    intents = _protect_filter(intents, protect)
    # Normalize actions
    for it in intents:
        act = str(it.get("action") or "")
        if act == "unresolved":
            it["action"] = "mark_unresolved"
            act = "mark_unresolved"
        if act not in ALLOWED_ACTIONS and act != "mark_unresolved":
            it["action"] = "mark_unresolved"
            it["normalize_note"] = "unknown_action_mapped_to_mark_unresolved"

    # Honesty: REVISE with only keep/mark_unresolved → UNRESOLVED
    acts = {str(it.get("action") or "") for it in intents}
    if decision == "REVISE" and (not acts or acts <= {"keep", "mark_unresolved"}):
        decision = "UNRESOLVED"
        rationale_parts.append("revise_without_mutating_intents_normalized")

    # Phase 8: if feedback wiped all LIVE options, stop rather than force-insert.
    if (
        feedback_summary
        and not search_ok
        and decision == "UNRESOLVED"
        and (search_results or {}).get("feedback_filtered_candidates")
    ):
        rationale_parts.append(
            "no_remaining_live_candidates_after_feedback_filter_stop_forced_insert"
        )

    return {
        "schema": "v3a_story_revision_plan_v1",
        "decision": decision,
        "rationale": ";".join(rationale_parts),
        "offline": offline,
        "semantic_confirmation": semantic_ok,
        # Only FIRST_LIVE_VERIFIED candidates count as confirmation for REVISE/fallback.
        "search_confirmation": executable_search_ok,
        "narrative_fit_required": require_narrative_fit,
        "narrative_fit_confirmation": bool(
            (search_results or {}).get("narrative_fit_supported_candidates")
        ),
        "event_pts_search_available": search_ok,
        "protected_goal_segment_ids": protect,
        "revision_intents": intents,
        "feedback_context": feedback_summary,
        "fullcut_learning_enabled": use_fullcut_learning,
        "fullcut_edit_selection": fullcut_edit_selection,
        "budget": dict(budget or {}),
        "phase6_rules": {
            "no_auto_add_on_large_source_gap_alone": True,
            "duration_pad_not_quality_proxy": True,
            "require_confirmed_defect_for_search_add": True,
            "require_narrative_fit_triplet_before_insert": require_narrative_fit,
            "temporal_jump_alone_can_be_kept": keep_unconfirmed_temporal_gap,
            "one_confirmed_edit_per_round": use_fullcut_learning,
            "hypothesis_status": "HYPOTHESIS_NEEDS_VIDEO",
        },
        "phase8_rules": {
            "use_prior_round_feedback": bool(feedback_summary),
            "block_identical_pts_action_without_new_evidence": True,
            "never_permanently_ban_pts": True,
            "unverified_reject_is_not_confirmed_negative": True,
            "stop_if_no_narrative_live_after_filter": True,
        },
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
        "search_feedback_filter": {
            "filtered_count": len((search_results or {}).get("feedback_filtered_candidates") or []),
            "kept_count": len((search_results or {}).get("verified_candidates") or []),
        },
    }
