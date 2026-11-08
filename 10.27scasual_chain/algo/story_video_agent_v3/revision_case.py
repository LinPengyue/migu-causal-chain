"""Problem → revision → verification case records for the unified main chain."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence


def build_revision_case(
    *,
    match_tag: Optional[str] = None,
    issue: Optional[Mapping[str, Any]] = None,
    intent: Optional[Mapping[str, Any]] = None,
    apply_row: Optional[Mapping[str, Any]] = None,
    search_candidate: Optional[Mapping[str, Any]] = None,
    before_after_windows: Optional[Mapping[str, Any]] = None,
    verifier_judgment: Optional[Mapping[str, Any]] = None,
    pts_safety: Optional[Mapping[str, Any]] = None,
    candidate_accepted: bool = False,
    formal_final_is_baseline: bool = True,
) -> Dict[str, Any]:
    """One revision closed-loop record (issue→evidence→edit→expected→actual→verdict)."""
    iss = dict(issue or {})
    it = dict(intent or {})
    vj = dict(verifier_judgment or {})
    q = str(vj.get("quality_judgment") or vj.get("judgment") or "").upper() or None
    original_resolved = vj.get("original_issue_resolved")
    new_defect = vj.get("introduced_new_defect")
    # ACCEPT requires: candidate_accepted AND original issue resolved AND no new defect
    # AND pts safety AND not merely BETTER aesthetics.
    pts_ok = True if pts_safety is None else bool(pts_safety.get("ok", True))
    accept = bool(
        candidate_accepted
        and pts_ok
        and original_resolved is True
        and new_defect is not True
        and q == "BETTER"
    )
    # BETTER alone never implies IMPROVED / ACCEPT when gates fail
    fail_reasons: List[str] = []
    if not pts_ok:
        fail_reasons.append("pts_or_safety_gate")
    if q in ("SAME", "WORSE", "UNRESOLVED"):
        fail_reasons.append(f"quality_judgment_{q}")
    if original_resolved is False:
        fail_reasons.append("original_issue_not_resolved")
    if new_defect is True:
        fail_reasons.append("introduced_new_defect")
    if q == "BETTER" and not accept:
        fail_reasons.append("BETTER_not_auto_ACCEPT")
    if not candidate_accepted:
        fail_reasons.append("verifier_or_pipeline_rejected")

    return {
        "schema": "v3a_revision_case_v1",
        "match_tag": match_tag,
        "issue_id": iss.get("issue_id") or it.get("issue_id"),
        "revision_intent_id": it.get("intent_id"),
        "original_story_problem": {
            "observation": iss.get("observed_evidence") or iss.get("observation"),
            "missing_information": iss.get("missing_information"),
            "causal_explanation": iss.get("causal_explanation") or iss.get("narrative_problem"),
            "story_role": iss.get("story_role"),
            "diagnosis_status": iss.get("diagnosis_status"),
            "story_defect_confirmed": iss.get("story_defect_confirmed"),
            "confidence": iss.get("confidence"),
            "evidence_sufficiency": iss.get("evidence_sufficiency"),
        },
        "video_observation_evidence": it.get("video_observation_evidence")
        or iss.get("observed_evidence"),
        "defect_cause_hypothesis": it.get("defect_cause_hypothesis")
        or iss.get("causal_explanation"),
        "target_action": it.get("action"),
        "candidate_footage": {
            "source_pts": it.get("bound_source_window")
            or (
                {
                    "start": (search_candidate or {}).get("source_pts_start"),
                    "end": (search_candidate or {}).get("source_pts_end"),
                }
                if search_candidate
                else None
            ),
            "event_ids": it.get("event_ids"),
            "why_solves_problem": it.get("why_candidate_solves_problem")
            or it.get("rationale"),
            "apply": apply_row,
        },
        "before_after_video_windows": before_after_windows,
        "expected_improvement": it.get("expected_observable_improvement")
        or it.get("expected_improvement"),
        "falsification_evidence": it.get("falsification_evidence")
        or it.get("what_would_falsify"),
        "actual_observation": vj.get("observed_visuals") or vj.get("actual_observation"),
        "verifier_judgment": {
            "quality_judgment": q,
            "original_issue_resolved": original_resolved,
            "introduced_new_defect": new_defect,
            "evidence_refs": vj.get("evidence_refs"),
            "confidence": vj.get("confidence"),
            "note": (
                "Verifier must check whether the original diagnosed problem was solved, "
                "not only which cut looks nicer. BETTER ≠ ACCEPT ≠ IMPROVED."
            ),
        },
        "pts_safety": pts_safety,
        "final_decision": "ACCEPT" if accept else "REJECT",
        "failure_reasons": fail_reasons,
        "formal_final_is_baseline": bool(formal_final_is_baseline) or not accept,
        "bindings": {
            "issue_id": iss.get("issue_id") or it.get("issue_id"),
            "evidence": it.get("evidence_refs"),
            "edit": it.get("action"),
            "expected_effect": it.get("expected_observable_improvement")
            or it.get("expected_improvement"),
        },
        "duration_pad_forbidden_as_quality_proxy": True,
    }


def build_revision_cases_for_round(
    *,
    diagnosis: Mapping[str, Any],
    revision_plan: Mapping[str, Any],
    apply_report: Optional[Mapping[str, Any]] = None,
    search_report: Optional[Mapping[str, Any]] = None,
    verifier_per_intent: Optional[Mapping[str, Mapping[str, Any]]] = None,
    pts_safety: Optional[Mapping[str, Any]] = None,
    candidate_accepted: bool = False,
    match_tag: Optional[str] = None,
) -> Dict[str, Any]:
    issues_by_id = {
        str(i.get("issue_id")): i
        for i in (diagnosis.get("issues") or [])
        if isinstance(i, dict) and i.get("issue_id")
    }
    apply_by_intent = {}
    for row in (apply_report or {}).get("applied") or []:
        if isinstance(row, dict) and row.get("intent"):
            apply_by_intent[str(row["intent"])] = row
    search_by_issue = {}
    for c in (search_report or {}).get("verified_candidates") or []:
        if isinstance(c, dict) and c.get("issue_id"):
            search_by_issue.setdefault(str(c["issue_id"]), c)

    cases: List[Dict[str, Any]] = []
    for intent in revision_plan.get("revision_intents") or []:
        if not isinstance(intent, dict):
            continue
        if str(intent.get("action") or "") in ("keep", "mark_unresolved"):
            # Still record unresolved/keep for audit trail when bound to an issue.
            if not intent.get("issue_id") and str(intent.get("action")) == "keep":
                continue
        iid = str(intent.get("issue_id") or "")
        intent_id = str(intent.get("intent_id") or "")
        vj = (verifier_per_intent or {}).get(intent_id) or (verifier_per_intent or {}).get(iid)
        cases.append(
            build_revision_case(
                match_tag=match_tag,
                issue=issues_by_id.get(iid),
                intent=intent,
                apply_row=apply_by_intent.get(intent_id),
                search_candidate=search_by_issue.get(iid),
                verifier_judgment=vj,
                pts_safety=pts_safety,
                candidate_accepted=candidate_accepted,
                formal_final_is_baseline=not candidate_accepted,
            )
        )
    return {
        "schema": "v3a_revision_case_bundle_v1",
        "match_tag": match_tag,
        "n_cases": len(cases),
        "cases": cases,
    }
