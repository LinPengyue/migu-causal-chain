"""Turn authenticated sampled full-cut review into next-round edit strategy.

No new label becomes an actual story defect by itself. This module records
*conditional* negative evidence, not a universal PTS ban or proven regression.
Prioritize non-additive structural fixes only when independently confirmed.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

SCHEMA = "v3a_fullcut_revision_learning_v1"


def _issue_by_id(diagnosis: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    return {
        str(i["issue_id"]): i
        for i in (diagnosis.get("issues") or [])
        if isinstance(i, Mapping) and i.get("issue_id")
    }


def extract_fullcut_learning(
    *,
    screen: Optional[Mapping[str, Any]],
    revision_plan: Mapping[str, Any],
    diagnosis: Mapping[str, Any],
    parent_version_id: str,
    candidate_version_id: str,
    source_sha256: Optional[str],
    round_idx: int,
    provider_mode: str = "REAL_VLM",
) -> Dict[str, Any]:
    """Record feedback from review of two finished-cut MP4s, with issue/action anchors.

    SCREENED_NO_GAIN is *partial* evidence, never CONFIRMED_NEGATIVE.
    No new source PTS or trim bounds are invented; only original bound windows
    already applied to the candidate may be described.
    """
    s = dict(screen or {})
    status = str(s.get("status") or "UNVERIFIED").upper()
    # Calling this on a fixture or unbound LLM label must not create
    # seemingly-real learning examples.
    admissible = (
        provider_mode == "REAL_VLM"
        and status in ("SCREENED_NO_GAIN", "SCREENED_BETTER")
        and isinstance(s.get("baseline_mp4_sha256"), str)
        and len(str(s.get("baseline_mp4_sha256"))) == 64
        and isinstance(s.get("candidate_mp4_sha256"), str)
        and len(str(s.get("candidate_mp4_sha256"))) == 64
        and s.get("authorizes_promote_best") is False
        and s.get("improvement_verified") is False
        and bool(s.get("sampled_frame_sha256"))
    )
    issue_map = _issue_by_id(diagnosis)
    rows: List[Dict[str, Any]] = []
    for it in (revision_plan.get("revision_intents") or []):
        if not isinstance(it, Mapping):
            continue
        act = str(it.get("action") or "")
        if act not in ("search_add", "drop", "trim", "reorder", "replace"):
            continue
        iid = str(it.get("issue_id") or "")
        iss = issue_map.get(iid) or {}
        window = it.get("bound_source_window")
        pts = None
        if isinstance(window, Mapping):
            try:
                a, b = float(window["start"]), float(window["end"])
                if b > a:
                    pts = [a, b]
            except (KeyError, ValueError, TypeError):
                pass
        anchors = [
            str(v) for v in (
                it.get("insert_after_segment_id"),
                it.get("before_segment_id"),
                it.get("target_segment_id"),
            ) if v
        ]
        if not anchors:
            anchors = [str(x) for x in iss.get("segment_ids") or [] if x]
        sig = {
            "category": iss.get("category") or "unknown",
            "story_role": iss.get("story_role"),
            "anchor_segment_ids": anchors[:4],
            "missing_narrative_info": iss.get("missing_information") or "unspecified",
            "issue_id_raw": iid,
        }
        if status == "SCREENED_NO_GAIN":
            advice = (
                "avoid_repeating_same_context_add; seek_confirmed_redundancy_"
                "drop_or_story_structure_fix_before_any_new_footage"
                if act == "search_add"
                else "reassess_exact_structural_fix_with_specific_video_evidence"
            )
        elif status == "SCREENED_BETTER":
            advice = "keep_as_promising_candidate_only; require_full_story_review"
        else:
            advice = "new_observation_needed"
        rows.append({
            "schema": SCHEMA,
            "round": round_idx,
            "issue_id": iid,
            "issue_signature": sig,
            "intent_id": it.get("intent_id"),
            "action": act,
            "source_pts": pts,
            "parent_version_id": parent_version_id,
            "candidate_version_id": candidate_version_id,
            "source_sha256": source_sha256,
            "baseline_mp4_sha256": s.get("baseline_mp4_sha256"),
            "candidate_mp4_sha256": s.get("candidate_mp4_sha256"),
            "screen_status": status,
            "quality": "SAME" if status == "SCREENED_NO_GAIN" else "PROMISING",
            "evidence_status": "PARTIAL",
            "failure_class": "UNCERTAIN_OR_UNVERIFIED"
            if status == "SCREENED_NO_GAIN" else "POSITIVE",
            "source_kind": provider_mode,
            "observation": "sampled_pair_review_not_fullcut_ground_truth",
            "next_search_requirement": advice,
            "alternative_edit_priority": (
                "CONFIRMED_NON_ADDITIVE" if status == "SCREENED_NO_GAIN"
                else "PRESERVE_AND_REOBSERVE"
            ),
            "new_evidence_required_for_retry": True,
            "pts_permanently_banned": False,
            "screen_aspect_verdicts": dict(s.get("aspect_verdicts") or {}),
            "screen_frame_sha256": dict(s.get("sampled_frame_sha256") or {}),
            "observation_limitations": [
                "sampled_finished_cut_frames_not_full_video_audio",
                "screened_negative_is_not_confirmed_negative",
            ],
        })
    return {
        "schema": SCHEMA,
        "admissible": admissible,
        "screen_status": status,
        "entries": rows if admissible else [],
        "strategy": (
            "PREFER_CONFIRMED_NON_ADDITIVE"
            if admissible and status == "SCREENED_NO_GAIN"
            else "NO_OVERRIDE"
        ),
        "source_binding_required": True,
        "does_not_confirm_new_story_defects": True,
        "does_not_permanently_ban_source_pts": True,
    }


def prioritize_confirmed_edits(
    *,
    structure_intents: Sequence[Mapping[str, Any]],
    insert_intents: Sequence[Mapping[str, Any]],
    feedback_context: Optional[Mapping[str, Any]],
    max_mutations: int = 1,
) -> Dict[str, Any]:
    """One change per iteration enables causal attribution in full-cut review.

    Structural deletion/reordering must already be supported by Critic and
    _structure_intents; feedback never makes an unconfirmed action executable.
    """
    records = list((feedback_context or {}).get("records") or [])
    recent_no_gain = any(
        str(r.get("screen_status") or "").upper() == "SCREENED_NO_GAIN"
        and r.get("alternative_edit_priority") == "CONFIRMED_NON_ADDITIVE"
        and str(r.get("source_kind") or "").upper() == "REAL_VLM"
        for r in records[-12:]
    )
    structural = [
        dict(x) for x in structure_intents
        if str(x.get("action") or "") in ("drop", "reorder", "trim")
    ]
    additions = [
        dict(x) for x in insert_intents
        if str(x.get("action") or "") in ("search_add", "replace")
    ]
    # Non-additive fixes are preferable by default when actually established,
    # even without past failure; do not make several confounded edits at once.
    ranked = structural + additions
    if not ranked:
        return {
            "selected": [], "deferred": [], "recent_no_gain": recent_no_gain,
            "reason": "no_confirmed_executable_mutations",
        }
    limit = max(1, int(max_mutations))
    return {
        "selected": ranked[:limit],
        "deferred": ranked[limit:],
        "recent_no_gain": recent_no_gain,
        "reason": (
            "fullcut_failure_favors_confirmed_nonadditive_repair"
            if recent_no_gain and structural
            else "one_issue_one_edit_for_attributable_fullcut_delta"
        ),
        "no_new_unverified_edits_synthesized": True,
    }
