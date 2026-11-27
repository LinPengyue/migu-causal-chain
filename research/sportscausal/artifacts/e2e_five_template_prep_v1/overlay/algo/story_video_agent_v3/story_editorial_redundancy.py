"""Propose an independently frame-bound non-additive story edit.

A VLM may spot a redundant non-goal beat absent from structural overlap audits.
Claims become a precisely targeted, reviewable *candidate* only if two
distinct EDL segments are actually represented by extracted, hashed frames.
A candidate is NOT a formally verified narrative-quality improvement.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence


def validate_editorial_redundancy_claims(
    claims: Sequence[Mapping[str, Any]],
    *,
    frame_bindings: Sequence[Mapping[str, Any]],
    timeline: Mapping[str, Any],
    protected_goal_ids: Sequence[str],
    max_issues: int = 1,
) -> Dict[str, Any]:
    """Only a confirmable *edit target* enters a proposed story diagnosis.

    The two cited frames must be independently extracted source-bound bytes
    from TWO distinct story segments (the drop target and comparator).
    Merely repeating a segment name or hallucinating frame IDs cannot create
    a drop intent. Final promotion still needs full-cut evaluation.
    """
    valid_segments = {
        str(s.get("segment_id")): s
        for s in (timeline.get("segments") or [])
        if s.get("segment_id") and s.get("has_media_window")
    }
    protected = {str(x) for x in protected_goal_ids}
    frames: Dict[str, Dict[str, str]] = {}
    for fr in frame_bindings:
        if not isinstance(fr, Mapping):
            continue
        fid, sid = str(fr.get("frame_id") or ""), str(fr.get("segment_id") or "")
        if not fid or fid in frames or sid not in valid_segments:
            continue
        path = Path(str(fr.get("path") or ""))
        if not path.is_file():
            continue
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
        frames[fid] = {"segment_id": sid, "sha256": digest}
    issues: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for i, raw in enumerate(claims or []):
        if not isinstance(raw, Mapping):
            continue
        target = str(raw.get("target_segment_id") or "")
        comparator = str(raw.get("comparison_segment_id") or "")
        reason = str(raw.get("observed_fact") or "").strip()
        harm = str(raw.get("why_redundant") or "").strip()
        citations = raw.get("evidence_refs")
        refs: List[str] = [
            str(x.get("frame_id") or "")
            for x in citations
            if isinstance(x, Mapping) and x.get("frame_id")
        ] if isinstance(citations, list) else []
        reason_reject = None
        if (
            not target or not comparator or target == comparator
            or target not in valid_segments or comparator not in valid_segments
        ):
            reason_reject = "target_or_comparator_not_in_distinct_active_edl_segments"
        else:
            role = str(valid_segments[target].get("role") or "").lower()
            if (target in protected or any(
                word in role for word in (
                    "goal_action", "scoreboard", "confirm", "ending", "wrap", "title",
                )
            )):
                reason_reject = "protected_or_essential_story_segment"
        if reason_reject is None and (
            len(reason) < 18 or len(harm) < 18
            or reason.lower() == harm.lower()
        ):
            reason_reject = "generic_or_missing_distinct_visual_explanation"
        if reason_reject is None and (
            len(set(refs)) < 2
            or any(fid not in frames for fid in refs)
        ):
            reason_reject = "missing_or_fabricated_cited_frame"
        if reason_reject is None:
            cited_segments = {frames[fid]["segment_id"] for fid in refs}
            if target not in cited_segments or comparator not in cited_segments:
                reason_reject = "citations_do_not_cover_both_story_segments"
        if reason_reject is not None:
            rejected.append({
                "claim_index": i, "target_segment_id": target,
                "reason": reason_reject,
            })
            continue
        drop_seg = valid_segments[target]
        compare_seg = valid_segments[comparator]
        issues.append({
            "issue_id": f"editorial_redundancy_{target}_vs_{comparator}",
            "category": "redundancy",
            "severity": "major",
            "segment_ids": [comparator, target],
            "preferred_keep_segment_id": comparator,
            "preferred_drop_segment_id": target,
            "observation": reason,
            "observed_evidence": reason,
            "narrative_problem": harm,
            "causal_explanation": harm,
            "story_time_range": [
                min(float(drop_seg["story_in"]), float(compare_seg["story_in"])),
                max(float(drop_seg["story_out"]), float(compare_seg["story_out"])),
            ],
            "evidence_sufficiency": "observed",
            "evidence_tier": "DEFECT_CONFIRMED",
            "claim_status": "DEFECT_CONFIRMED",
            "evidence_frame_refs": refs,
            "evidence_refs": [
                {
                    "kind": "story_frame_sha256",
                    "frame_id": fid,
                    "sha256": frames[fid]["sha256"],
                    "segment_id": frames[fid]["segment_id"],
                }
                for fid in refs
            ],
            "observation_scope": {
                "method": "sparse_story_frame_comparison",
                "claims_full_video_watch": False,
            },
            "suggested_fix": "drop_redundant_non_goal_segment_and_verify_fullcut",
            "story_defect_confirmed": True,
            "model_based_edit_proposal": True,
            "note": (
                "Bound model judgment permits a candidate drop only. "
                "It is not independent human proof or BEST/release approval."
            ),
        })
        if len(issues) >= max(1, max_issues):
            break
    return {
        "schema": "v3a_editorial_redundancy_candidate_v1",
        "issues": issues,
        "rejected": rejected,
        "frame_count_with_hashes": len(frames),
        "does_not_authorize_best_promotion": True,
        "no_new_pts_created": True,
    }



def validate_editorial_irrelevance_claims(
    claims: Sequence[Mapping[str, Any]],
    *,
    frame_bindings: Sequence[Mapping[str, Any]],
    timeline: Mapping[str, Any],
    protected_goal_ids: Sequence[str],
    max_issues: int = 1,
) -> Dict[str, Any]:
    """Video-cited *hypotheses* for independent but narratively unhelpful cuts.

    Unlike repeated footage, unrelated content can be unique. Require frame
    citations from the exact BEFORE, TARGET, AFTER neighboring story segments.
    Never call an absence-of-contribution judgment a confirmed defect from
    sparse stills; these issues can direct re-observation or P10-C exploration
    but cannot bypass confirmed-nonadditive mutation gates.
    """
    active = [
        seg for seg in (timeline.get("segments") or [])
        if isinstance(seg, Mapping) and seg.get("segment_id") and seg.get("has_media_window")
    ]
    ids = [str(seg["segment_id"]) for seg in active]
    if len(ids) != len(set(ids)):
        return {"schema": "v3a_editorial_irrelevance_candidate_v1",
                "issues": [], "rejected": [{"reason": "ambiguous_segment_ids"}],
                "story_defect_confirmed": False}
    protected = {str(x) for x in protected_goal_ids}
    frames: Dict[str, Dict[str, str]] = {}
    for fr in frame_bindings:
        if not isinstance(fr, Mapping):
            continue
        fid, sid = str(fr.get("frame_id") or ""), str(fr.get("segment_id") or "")
        if not fid or fid in frames or sid not in ids:
            continue
        path = Path(str(fr.get("path") or ""))
        if not path.is_file():
            continue
        try:
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
        frames[fid] = {"segment_id": sid, "sha256": sha}

    issues: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for index, raw in enumerate(claims or []):
        if not isinstance(raw, Mapping):
            continue
        target = str(raw.get("target_segment_id") or "")
        visual = str(raw.get("observed_content") or "").strip()
        missing = str(raw.get("why_not_support_story") or "").strip()
        continuity = str(raw.get("why_removal_may_preserve_continuity") or "").strip()
        cited = raw.get("evidence_refs")
        refs = [
            str(x.get("frame_id") or "") for x in cited
            if isinstance(x, Mapping) and x.get("frame_id")
        ] if isinstance(cited, list) else []
        reason = None
        if target not in ids or ids.index(target) in (0, len(ids) - 1):
            reason = "target_must_have_two_active_media_neighbors"
        else:
            seg = active[ids.index(target)]
            role = str(seg.get("role") or "").lower()
            if target in protected or any(word in role for word in (
                "goal", "scoreboard", "confirm", "ending", "wrap", "title",
                "opening", "penalty", "red_card", "var",
            )):
                reason = "protected_or_essential_story_segment"
        if reason is None and (
            len(visual) < 18 or len(missing) < 18 or len(continuity) < 18
            or visual.lower() == missing.lower()
        ):
            reason = "missing_specific_visual_narrative_explanation"
        if reason is None and (
            len(set(refs)) < 3 or any(fid not in frames for fid in refs)
        ):
            reason = "missing_or_fabricated_cited_frames"
        if reason is None:
            pos = ids.index(target)
            expected = {ids[pos - 1], target, ids[pos + 1]}
            if not expected.issubset({frames[fid]["segment_id"] for fid in refs}):
                reason = "not_cited_exact_before_target_after_context"
        if reason is not None:
            rejected.append({"claim_index": index, "target_segment_id": target,
                             "reason": reason})
            continue

        pos = ids.index(target)
        before, segment, after = active[pos-1:pos+2]
        issues.append({
            "issue_id": f"story_irrelevance_hypothesis_{target}",
            "category": "narrative_relevance",
            "severity": "minor",
            "segment_ids": [ids[pos-1], target, ids[pos+1]],
            "target_segment_id": target,
            "preferred_drop_segment_id": target,
            "story_time_range": [
                float(before["story_in"]), float(after["story_out"])
            ],
            "observation": visual,
            "narrative_problem": missing,
            "expected_edit_effect_hypothesis": continuity,
            "evidence_sufficiency": "needs_video_verify",
            "diagnosis_status": "HYPOTHESIS_NEEDS_VIDEO",
            "story_defect_confirmed": False,
            "claim_status": "VIDEO_CITED_RELEVANCE_HYPOTHESIS",
            "observation_scope": {
                "method": "sparse_before_target_after_frames",
                "claims_full_video_watch": False,
            },
            "evidence_frame_refs": refs,
            "evidence_refs": [
                {"kind": "story_frame_sha256", "frame_id": fid,
                 "sha256": frames[fid]["sha256"],
                 "segment_id": frames[fid]["segment_id"]}
                for fid in refs
            ],
            "suggested_fix": "observe_full_target_and_context_before_any_edit",
            "no_automatic_edit_authorized": True,
            "model_based_edit_proposal": True,
            "note": "A unique video event may still be irrelevant, but three cited stills never prove removal improves the finished story.",
        })
        if len(issues) >= max(1, max_issues):
            break
    return {
        "schema": "v3a_editorial_irrelevance_candidate_v1",
        "issues": issues,
        "rejected": rejected,
        "story_defect_confirmed": False,
        "requires_video_reobservation": bool(issues),
        "no_automatic_edit_authorized": True,
        "no_new_pts_created": True,
    }
