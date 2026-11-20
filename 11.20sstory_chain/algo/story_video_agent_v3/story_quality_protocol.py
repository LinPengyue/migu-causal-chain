"""Phase10: conservative HUMAN assessment of football story-video deliverables.

Only offline, blinded human judgments can recommend promotion. Sampled VLM
screens, synthetic fixtures, and structural metrics are never human ratings.
This module has no dependency on V3-A editing or on benchmark gold labels.
"""
from __future__ import annotations

import statistics
from typing import Any, Dict, Mapping

QUALITY_SCHEMA = "migu_story_quality_protocol_v1"
RATING_SCHEMA = "migu_story_blind_pair_review_v1"
ALLOCATION_SCHEMA = "migu_story_blind_allocation_v1"
G0_GATES = (
    "first_live", "fact_consistency", "key_action_integrity",
    "temporal_causal_integrity", "source_traceability", "technical_integrity",
)
DIMENSIONS = {
    "story_completeness": 25,
    "narrative_coherence": 25,
    "material_narrative_value": 20,
    "pacing_emotional_progression": 15,
    "ending_theme_resolution": 10,
    "audiovisual_quality": 5,
}
PREFERENCES = frozenset({
    "X_STRONG", "X_SLIGHT", "TIE", "Y_SLIGHT", "Y_STRONG", "BOTH_UNACCEPTABLE",
})


def _score_one(scores: Mapping[str, Any]) -> float:
    if not isinstance(scores, Mapping) or set(scores) != set(DIMENSIONS):
        raise ValueError("all six named story-quality dimensions are required")
    total = 0.0
    for dimension, weight in DIMENSIONS.items():
        number = scores[dimension]
        if type(number) is not int or number < 1 or number > 5:
            raise ValueError(dimension + " must be an integer from 1 to 5")
        total += weight * number / 5.0
    return round(total, 3)


def _gate_status(gates: Mapping[str, Any]) -> str:
    if not isinstance(gates, Mapping) or set(gates) != set(G0_GATES):
        raise ValueError("all six G0 hard gates are required")
    if any(value not in ("PASS", "FAIL", "UNKNOWN") for value in gates.values()):
        raise ValueError("G0 statuses must be PASS, FAIL, or UNKNOWN")
    if "FAIL" in gates.values():
        return "FAIL"
    if "UNKNOWN" in gates.values():
        return "UNKNOWN"
    return "PASS"


def evaluate_blind_story_pair(
    reviews_document: Mapping[str, Any],
    allocation_document: Mapping[str, Any],
    hard_gates_document: Mapping[str, Any],
) -> Dict[str, Any]:
    """Evaluate a blinded X/Y comparison. Never edits EDL or updates BEST.

    The unblinding allocation and G0 audit must be stored separately from the
    individual human review packets during rating. >=3 independent raters are
    needed to recommend a candidate for promotion; one rater is dev feedback.
    """
    if reviews_document.get("schema") != RATING_SCHEMA:
        raise ValueError("review schema mismatch")
    if allocation_document.get("schema") != ALLOCATION_SCHEMA:
        raise ValueError("allocation schema mismatch")
    pair_id = reviews_document.get("pair_id")
    if not isinstance(pair_id, str) or not pair_id.strip():
        raise ValueError("pair_id is required")
    if allocation_document.get("pair_id") != pair_id:
        raise ValueError("pair_id mismatch between reviews and allocation")
    if any(key in reviews_document for key in ("allocation", "version_mapping", "unblinded")):
        raise ValueError("unblinding information leaked into review packet")

    allocation = {k: allocation_document.get(k) for k in ("X", "Y")}
    if set(allocation.values()) != {"baseline", "candidate"}:
        raise ValueError("allocation must assign one baseline and one candidate")
    candidate_side = "X" if allocation["X"] == "candidate" else "Y"
    baseline_side = "Y" if candidate_side == "X" else "X"
    gates = hard_gates_document.get("gates")
    if not isinstance(gates, Mapping) or set(gates) != {"X", "Y"}:
        raise ValueError("hard gate audit needs X and Y")
    gate_statuses = {side: _gate_status(gates[side]) for side in ("X", "Y")}

    raw_reviews = reviews_document.get("reviews")
    if not isinstance(raw_reviews, list) or not raw_reviews:
        raise ValueError("at least one human review is required")
    rater_ids: set[str] = set()
    score_rows: Dict[str, list[float]] = {"X": [], "Y": []}
    dimension_rows: Dict[str, Dict[str, list[int]]] = {
        side: {dim: [] for dim in DIMENSIONS} for side in ("X", "Y")
    }
    preferences: Dict[str, int] = {"baseline": 0, "candidate": 0, "tie": 0, "both_bad": 0}
    serious_candidate_issues: list[Dict[str, Any]] = []
    for idx, review in enumerate(raw_reviews):
        if not isinstance(review, Mapping):
            raise ValueError("review must be an object")
        rater = review.get("rater_id")
        if not isinstance(rater, str) or not rater.strip() or rater in rater_ids:
            raise ValueError("rater_id missing or duplicated")
        rater_ids.add(rater)
        preference = review.get("preference")
        if preference not in PREFERENCES:
            raise ValueError("invalid pairwise preference")
        if preference == "BOTH_UNACCEPTABLE":
            preferences["both_bad"] += 1
        elif preference == "TIE":
            preferences["tie"] += 1
        else:
            preferred_side = preference[0]
            preferred_version = allocation[preferred_side]
            preferences[preferred_version] += 1
        scores = review.get("scores")
        if not isinstance(scores, Mapping) or set(scores) != {"X", "Y"}:
            raise ValueError("both X and Y must be rated independently")
        for side in ("X", "Y"):
            score_rows[side].append(_score_one(scores[side]))
            for dim in DIMENSIONS:
                dimension_rows[side][dim].append(scores[side][dim])
        issues = review.get("issues", [])
        if not isinstance(issues, list):
            raise ValueError("issues must be a list")
        for issue in issues:
            if not isinstance(issue, Mapping) or issue.get("side") not in ("X", "Y"):
                raise ValueError("issue must cite X or Y")
            if issue.get("severity") not in ("critical", "major", "minor", "info"):
                raise ValueError("issue severity invalid")
            if not isinstance(issue.get("description"), str) or not issue["description"].strip():
                raise ValueError("issue description missing")
            if issue["side"] == candidate_side and issue["severity"] == "critical":
                serious_candidate_issues.append({"rater_id": rater, "issue": dict(issue)})

    medians = {
        side: {
            "overall": round(float(statistics.median(score_rows[side])), 3),
            "dimensions": {
                dim: float(statistics.median(dimension_rows[side][dim]))
                for dim in DIMENSIONS
            },
        }
        for side in ("X", "Y")
    }
    candidate = medians[candidate_side]
    baseline = medians[baseline_side]
    n = len(raw_reviews)
    majority = n // 2 + 1
    delta = round(candidate["overall"] - baseline["overall"], 3)
    central_quality_ok = (
        candidate["overall"] >= 75
        and candidate["dimensions"]["story_completeness"] >= 3
        and candidate["dimensions"]["narrative_coherence"] >= 3
        and candidate["dimensions"]["story_completeness"] >= baseline["dimensions"]["story_completeness"] - 1
        and candidate["dimensions"]["narrative_coherence"] >= baseline["dimensions"]["narrative_coherence"] - 1
    )
    majority_prefers_candidate = preferences["candidate"] >= majority
    all_pass = all(status == "PASS" for status in gate_statuses.values())
    any_fail = any(status == "FAIL" for status in gate_statuses.values())
    if any_fail:
        decision = "REJECTED_G0"
    elif not all_pass:
        decision = "UNVERIFIED_G0"
    elif n < 3:
        decision = "DEVELOPMENT_FEEDBACK_ONLY"
    elif serious_candidate_issues:
        decision = "REJECTED_CRITICAL_ISSUE"
    elif majority_prefers_candidate and central_quality_ok and delta >= 3.0:
        decision = "IMPROVED_HUMAN_EVIDENCE"
    elif majority_prefers_candidate and central_quality_ok and delta >= 0:
        decision = "PROMISING_NEEDS_MORE_EVIDENCE"
    else:
        decision = "NOT_IMPROVED"

    return {
        "schema": QUALITY_SCHEMA,
        "pair_id": pair_id,
        "decision": decision,
        "recommend_promotion": decision == "IMPROVED_HUMAN_EVIDENCE",
        "automatic_best_update_allowed": False,
        "baseline_side": baseline_side,
        "candidate_side": candidate_side,
        "rater_count": n,
        "majority_required": majority,
        "preferences": preferences,
        "g0_status": gate_statuses,
        "g1_medians": medians,
        "candidate_minus_baseline": delta,
        "candidate_story_core_ok": central_quality_ok,
        "unresolved_critical_candidate_issues": serious_candidate_issues,
        "limitations": [
            "Protocol validates recorded human ratings, not the truth of ratings or match events.",
            "G0 checks are provided by independent audit; this tool does not inspect MP4 frames.",
            "No model-only evidence, sampled screening, or fixture can promote BEST.",
        ],
    }
