"""Story-semantic diagnosis layer on top of structural critic signals.

Structure gaps alone are HYPOTHESIS_NEEDS_VIDEO — never confirmed story defects
without video semantic evidence.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence


CATEGORY_TO_STORY_ROLE = {
    "buildup": "setup_insufficiency",
    "transition": "transition_break",
    "ending": "ending_incomplete",
    "narrative_order": "turn_or_arc_unclear",
    "narrative_causality": "turn_or_arc_unclear",
    "redundancy": "narrative_redundancy",
    "replay_risk": "narrative_redundancy",
    "arc_coverage": "climax_or_arc_gap",
    "timeline_integrity": "structural_integrity",
    "input_integrity": "input_integrity",
}


def _story_role_for_issue(iss: Mapping[str, Any]) -> str:
    cat = str(iss.get("category") or "")
    if cat in CATEGORY_TO_STORY_ROLE:
        return CATEGORY_TO_STORY_ROLE[cat]
    iid = str(iss.get("issue_id") or "")
    if "jump" in iid or "bridge" in iid or "transition" in iid:
        return "transition_break"
    if "ending" in iid or "tail" in iid or "climax" in iid:
        return "ending_incomplete" if "tail" in iid or "ending" in iid else "climax_underplayed"
    if "sparse" in iid or "buildup" in iid or "setup" in iid:
        return "setup_insufficiency"
    return "unspecified_story_hypothesis"


def enrich_issue_semantic_fields(
    iss: Mapping[str, Any],
    *,
    video_semantic_evidence: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Attach required semantic diagnosis fields; do not invent video observations."""
    out = dict(iss)
    sufficiency = str(out.get("evidence_sufficiency") or "")
    story_role = _story_role_for_issue(out)
    out.setdefault("story_role", story_role)
    out.setdefault("observed_evidence", out.get("observation"))
    out.setdefault(
        "missing_information",
        (
            "Whether the structural gap actually harms audience story understanding "
            "is unknown without video semantic observation."
            if sufficiency == "needs_video_verify"
            else out.get("narrative_problem")
        ),
    )
    out.setdefault("causal_explanation", out.get("narrative_problem"))
    # Confidence: structure-only hypotheses stay low.
    if "confidence" not in out:
        if sufficiency == "observed":
            out["confidence"] = 0.7
        elif sufficiency == "structure_inferred":
            out["confidence"] = 0.55
        else:
            out["confidence"] = 0.35

    confirmed = False
    ev = video_semantic_evidence or {}
    # Explicit confirmations from layered/VLM observe (match by issue_id).
    for item in ev.get("confirmed_issue_ids") or []:
        if str(item) == str(out.get("issue_id")):
            confirmed = True
            break
    for di in ev.get("derived_issues") or []:
        if isinstance(di, dict) and str(di.get("issue_id")) == str(out.get("issue_id")):
            if str(di.get("evidence_sufficiency") or "") == "observed":
                confirmed = True
                out["observed_evidence"] = di.get("observation") or out.get("observed_evidence")
                out["missing_information"] = di.get("missing_information") or out.get(
                    "missing_information"
                )
                out["causal_explanation"] = di.get("narrative_problem") or out.get(
                    "causal_explanation"
                )
                if di.get("confidence") is not None:
                    out["confidence"] = di.get("confidence")

    if sufficiency == "needs_video_verify" and not confirmed:
        out["diagnosis_status"] = "HYPOTHESIS_NEEDS_VIDEO"
        out["story_defect_confirmed"] = False
        out["note"] = (
            "Structural anomaly is a hypothesis only; not a confirmed story-quality defect."
        )
    elif sufficiency in ("observed", "structure_inferred") or confirmed:
        # structure_inferred critical (replay etc.) can be confirmed without VLM
        if sufficiency == "structure_inferred" and out.get("category") in (
            "replay_risk",
            "redundancy",
            "narrative_order",
            "narrative_causality",
            "timeline_integrity",
            "input_integrity",
        ):
            out["diagnosis_status"] = "CONFIRMED_STRUCTURE_DEFECT"
            out["story_defect_confirmed"] = True
        elif confirmed or sufficiency == "observed":
            out["diagnosis_status"] = "CONFIRMED_STORY_DEFECT"
            out["story_defect_confirmed"] = True
        else:
            out["diagnosis_status"] = "HYPOTHESIS_NEEDS_VIDEO"
            out["story_defect_confirmed"] = False
    else:
        out["diagnosis_status"] = "HYPOTHESIS_NEEDS_VIDEO"
        out["story_defect_confirmed"] = False

    # Required schema keys always present
    for k in (
        "issue_id",
        "story_role",
        "observed_evidence",
        "missing_information",
        "causal_explanation",
        "confidence",
        "evidence_sufficiency",
    ):
        out.setdefault(k, None)
    return out


def apply_semantic_diagnosis_layer(
    diagnosis: Mapping[str, Any],
    *,
    observations: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return diagnosis copy with semantic fields on every issue."""
    out = dict(diagnosis)
    obs = observations or out.get("layered_observations") or {}
    video_ev = {
        "derived_issues": list(obs.get("derived_issues") or []),
        "confirmed_issue_ids": list(obs.get("confirmed_issue_ids") or []),
        "semantic_provider_used": bool(
            obs.get("semantic_provider_used") and not obs.get("fixture_or_offline")
        ),
    }
    enriched = [
        enrich_issue_semantic_fields(i, video_semantic_evidence=video_ev)
        for i in (out.get("issues") or [])
        if isinstance(i, dict)
    ]
    out["issues"] = enriched
    out["semantic_diagnosis_layer"] = {
        "schema": "v3a_semantic_diagnosis_layer_v1",
        "hypothesis_count": sum(
            1 for i in enriched if i.get("diagnosis_status") == "HYPOTHESIS_NEEDS_VIDEO"
        ),
        "confirmed_story_defect_count": sum(
            1 for i in enriched if i.get("diagnosis_status") == "CONFIRMED_STORY_DEFECT"
        ),
        "confirmed_structure_defect_count": sum(
            1 for i in enriched if i.get("diagnosis_status") == "CONFIRMED_STRUCTURE_DEFECT"
        ),
        "rule": (
            "Without video semantic evidence, structural anomalies remain "
            "HYPOTHESIS_NEEDS_VIDEO and must not drive story-quality ACCEPT/IMPROVED."
        ),
    }
    out["critic_mode"] = (
        str(out.get("critic_mode") or "structural") + "+semantic_hypothesis_layer"
    )
    return out
