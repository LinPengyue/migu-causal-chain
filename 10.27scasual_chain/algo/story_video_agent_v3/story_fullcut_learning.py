"""Turn authenticated sampled full-cut review into next-round edit strategy.

No new label becomes an actual story defect by itself. This module records
*conditional* negative evidence, not a universal PTS ban or proven regression.
Prioritize non-additive structural fixes only when independently confirmed.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

SCHEMA = "v3a_fullcut_revision_learning_v1"


def _sha256_digest(value: Any) -> bool:
    raw = str(value or "").lower()
    return len(raw) == 64 and all(c in "0123456789abcdef" for c in raw)


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
        and _sha256_digest(source_sha256)
        and _sha256_digest(s.get("baseline_mp4_sha256"))
        and _sha256_digest(s.get("candidate_mp4_sha256"))
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
            "target_segment_id": it.get("target_segment_id"),
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
    records = [
        x for x in ((feedback_context or {}).get("records") or [])
        if isinstance(x, Mapping)
    ]
    structural = [
        dict(x) for x in structure_intents
        if str(x.get("action") or "") in ("drop", "reorder", "trim")
    ]
    additions = [
        dict(x) for x in insert_intents
        if str(x.get("action") or "") in ("search_add", "replace")
    ]
    current_issues = {
        str(it.get("issue_id") or "") for it in structural + additions
        if it.get("issue_id")
    }
    current_anchors = {
        str(anchor)
        for it in structural + additions
        for anchor in (
            it.get("insert_after_segment_id"),
            it.get("before_segment_id"),
            it.get("target_segment_id"),
        ) if anchor
    }
    # Historical no-gain evidence is contextual. A failure on a different
    # story issue (or an unrelated anchor) must not control this edit choice.
    def same_issue_context(row: Mapping[str, Any]) -> bool:
        if str(row.get("issue_id") or "") in current_issues:
            return True
        previous = {
            str(v) for v in (
                (row.get("issue_signature") or {}).get("anchor_segment_ids") or []
            ) if v
        }
        return bool(previous and current_anchors and
                    previous.intersection(current_anchors))
    recent_no_gain = any(
        str(r.get("screen_status") or "").upper() == "SCREENED_NO_GAIN"
        and r.get("alternative_edit_priority") == "CONFIRMED_NON_ADDITIVE"
        and str(r.get("source_kind") or "").upper() == "REAL_VLM"
        and same_issue_context(r)
        for r in records[-12:]
    )
    # Avoid the identical failed structural action in the SAME run, while
    # preserving distinct target segments. Footage additions are handled by
    # the separate PTS/anchor/observation-grade Search feedback filter.
    def repeated_structural_failure(it: Mapping[str, Any]) -> bool:
        target = str(it.get("target_segment_id") or "")
        if not target:
            return False
        return any(
            str(r.get("screen_status") or "") == "SCREENED_NO_GAIN"
            and str(r.get("source_kind") or "") == "REAL_VLM"
            and str(r.get("action") or "") == str(it.get("action") or "")
            and str(r.get("target_segment_id") or "") == target
            and (
                str(r.get("issue_id") or "") == str(it.get("issue_id") or "")
                or target in {
                    str(x) for x in (
                        (r.get("issue_signature") or {}).get("anchor_segment_ids") or []
                    )
                }
            )
            for r in records[-12:]
        )

    skipped_repeat = [
        it for it in structural if repeated_structural_failure(it)
    ]
    structural = [
        it for it in structural if not repeated_structural_failure(it)
    ]
    # Non-additive fixes are preferable when independently confirmed. A single
    # edit per round makes full-cut A/B attribution interpretable.
    ranked = structural + additions
    if not ranked:
        return {
            "selected": [], "deferred": [], "recent_no_gain": recent_no_gain,
            "skipped_repeated_structural": skipped_repeat,
            "reason": "no_fresh_confirmed_executable_mutations",
        }
    limit = max(1, int(max_mutations))
    return {
        "selected": ranked[:limit],
        "deferred": ranked[limit:],
        "recent_no_gain": recent_no_gain,
        "skipped_repeated_structural": skipped_repeat,
        "reason": (
            "fullcut_failure_favors_confirmed_nonadditive_repair"
            if recent_no_gain and structural
            else "one_issue_one_edit_for_attributable_fullcut_delta"
        ),
        "no_new_unverified_edits_synthesized": True,
    }


def enforce_confirmed_nonadditive_edits(
    plan: Mapping[str, Any],
    *,
    diagnosis: Mapping[str, Any],
    edl: Sequence[Mapping[str, Any]],
    feedback_context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Post-LLM safety for deletion/reordering of *existing* story footage.

    The LLM can recommend a change, but may not invent a confirmed diagnosis or
    remove arbitrary EDL segments. This runs on production after an LLM overlay;
    offline Phase8 fixtures retain their historical control-flow contract.
    """
    issues = _issue_by_id(diagnosis)
    rows = {
        str(r.get("segment_id")): r for r in edl
        if isinstance(r, Mapping) and r.get("segment_id")
        and r.get("include_in_cut", True)
    }
    protected = {
        str(x) for x in diagnosis.get("protected_goal_segment_ids") or []
    }
    failed_existing = [
        r for r in ((feedback_context or {}).get("records") or [])
        if isinstance(r, Mapping)
        and r.get("screen_status") == "SCREENED_NO_GAIN"
        and r.get("source_kind") == "REAL_VLM"
        and str(r.get("action") or "") in ("drop", "reorder", "trim")
    ]

    def already_failed_same_target(it: Mapping[str, Any]) -> bool:
        return any(
            str(r.get("action") or "") == str(it.get("action") or "")
            and str(r.get("target_segment_id") or "")
                == str(it.get("target_segment_id") or "")
            and str(r.get("issue_id") or "") == str(it.get("issue_id") or "")
            for r in failed_existing[-12:]
        )

    def essential(sid: str) -> bool:
        r = rows.get(sid) or {}
        role = str(r.get("role") or "").lower()
        return (sid in protected or any(x in role for x in
                ("goal_action", "scoreboard", "title", "ending", "wrap")))

    def authorizes(it: Mapping[str, Any]) -> bool:
        action = str(it.get("action") or "")
        target = str(it.get("target_segment_id") or "")
        iss = issues.get(str(it.get("issue_id") or "")) or {}
        if not iss or target not in rows or essential(target):
            return False
        if not (
            iss.get("story_defect_confirmed") is True
            or iss.get("diagnosis_status") in (
                "CONFIRMED_STORY_DEFECT", "CONFIRMED_STRUCTURE_DEFECT"
            )
        ):
            return False
        category = str(iss.get("category") or "")
        known = {
            str(x) for x in iss.get("segment_ids") or [] if x
        }
        if category == "redundancy" and action == "drop":
            return (
                str(iss.get("preferred_drop_segment_id") or "") == target
                and target in known
            )
        if category == "replay_risk" and action == "drop":
            return target in known
        if category == "narrative_order" and action == "reorder":
            moves = {
                str(x) for x in it.get("move_segment_ids") or [] if x
            }
            return (
                target in known and moves
                and moves.issubset(known)
                and not any(essential(x) for x in moves)
            )
        if category in ("redundancy", "narrative_order") and action == "trim":
            # evaluate_trim_bounds still independently requires time/frame evidence
            return (
                target in known and bool(iss.get("evidence_frame_refs"))
                and str(iss.get("evidence_tier") or "") == "DEFECT_CONFIRMED"
            )
        return False

    output = dict(plan)
    selected = []
    blocked = []
    for raw in output.get("revision_intents") or []:
        if not isinstance(raw, Mapping):
            continue
        it = dict(raw)
        action = str(it.get("action") or "")
        if action in ("drop", "reorder", "trim") and (
            not authorizes(it) or already_failed_same_target(it)
        ):
            blocked.append({
                "intent_id": it.get("intent_id"),
                "issue_id": it.get("issue_id"),
                "target_segment_id": it.get("target_segment_id"),
                "attempted_action": action,
                "reason": (
                    "already_screened_no_gain_same_action_target"
                    if already_failed_same_target(it) else
                    "missing_confirmed_issue_exact_target_or_protected_segment"
                ),
            })
            it.update({
                "action": "mark_unresolved",
                "blocked_original_action": action,
                "block_reason": "nonadditive_edit_requires_exact_confirmed_issue",
            })
        selected.append(it)
    output["revision_intents"] = selected
    output["nonadditive_apply_gate"] = {
        "required": True,
        "blocked_intents": blocked,
        "n_blocked": len(blocked),
        "explicitly_protected_goals": sorted(protected),
    }
    mutating = any(
        str(i.get("action") or "") not in ("keep", "mark_unresolved", "unresolved")
        for i in selected
    )
    if blocked and not mutating:
        output["decision"] = "UNRESOLVED"
        output["normalize_note"] = "nonadditive_apply_gate_blocked_all_mutations"
    return output
