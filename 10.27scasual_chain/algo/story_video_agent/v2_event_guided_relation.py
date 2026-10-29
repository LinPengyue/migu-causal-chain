"""Independent relation review — reject score-order causal fiction."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Set


ALLOWED_TYPES = ("temporal", "causal", "narrative")


def normalize_relation(raw: Dict[str, Any]) -> Dict[str, Any]:
    rtype = str(raw.get("relation_type") or raw.get("kind") or "temporal").lower()
    if rtype not in ALLOWED_TYPES:
        rtype = "narrative"
    return {
        "from_event_id": raw.get("from_event_id"),
        "to_event_id": raw.get("to_event_id"),
        "relation_type": rtype,
        "supporting_evidence_ids": list(raw.get("supporting_evidence_ids") or []),
        "explanation": str(raw.get("explanation") or raw.get("note") or ""),
        "verification_status": str(raw.get("verification_status") or "proposed"),
    }


def review_relations(
    relations: Sequence[Dict[str, Any]],
    *,
    evidence_ids: Optional[Set[str]] = None,
    verified_event_ids: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Downgrade causal edges that lack observable supporting evidence."""
    evidence_ids = evidence_ids or set()
    verified_event_ids = verified_event_ids or set()
    reviewed: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    downgraded: List[Dict[str, Any]] = []

    for raw in relations:
        rel = normalize_relation(raw if isinstance(raw, dict) else {})
        reasons: List[str] = []
        status = "accepted"
        rtype = rel["relation_type"]
        fr, to = rel["from_event_id"], rel["to_event_id"]
        if not fr or not to or fr == to:
            status = "rejected"
            reasons.append("missing_or_identical_endpoints")
        supp = [str(x) for x in rel["supporting_evidence_ids"] if x]
        if rtype == "temporal":
            # Temporal only needs ordered endpoints; evidence optional
            if status != "rejected":
                status = "accepted"
                reasons.append("temporal_order_claim")
        elif rtype == "narrative":
            if not supp and not (
                fr in verified_event_ids and to in verified_event_ids
            ):
                status = "accepted_weak"
                reasons.append("narrative_without_strong_evidence")
            else:
                reasons.append("narrative_link")
        elif rtype == "causal":
            # Causal requires explicit evidence ids that exist, and both events verified
            # OR explanation that cites non-score-order mechanism.
            expl = rel["explanation"].lower()
            score_order_only = bool(
                ("equalizer" in expl or "momentum" in expl or "shifts momentum" in expl)
                and ("lead" in expl or "go-ahead" in expl or "go ahead" in expl)
            ) or ("score" in expl and "then" in expl and not supp)
            has_real_supp = bool(supp) and (
                not evidence_ids or any(s in evidence_ids for s in supp)
            )
            both_verified = fr in verified_event_ids and to in verified_event_ids
            if status == "rejected":
                pass
            elif not has_real_supp:
                # Downgrade causal → narrative or reject
                rel["relation_type"] = "narrative"
                status = "downgraded_causal_to_narrative"
                reasons.append("causal_lacks_supporting_evidence_ids")
                if score_order_only:
                    reasons.append("score_order_is_not_causal_proof")
                downgraded.append(dict(rel, review_status=status, review_reasons=reasons))
            elif not both_verified and not has_real_supp:
                status = "rejected"
                reasons.append("causal_endpoints_not_verified")
            else:
                status = "accepted"
                reasons.append("causal_has_supporting_evidence")
                if score_order_only and has_real_supp:
                    reasons.append("explanation_mentions_momentum_but_evidence_present")

        out = dict(rel)
        out["verification_status"] = status
        out["review_reasons"] = reasons
        if status == "rejected":
            rejected.append(out)
        else:
            reviewed.append(out)

    return {
        "schema": "v2_relation_verification_v1",
        "n_input": len(relations),
        "n_accepted": len(reviewed),
        "n_rejected": len(rejected),
        "n_downgraded": len(downgraded),
        "relations": reviewed,
        "rejected": rejected,
        "downgraded": downgraded,
        "policy": [
            "temporal: order claim ok",
            "narrative: story linkage; weak ok if flagged",
            "causal: requires supporting_evidence_ids; score-order alone insufficient",
        ],
        "render_ready": False,
    }
