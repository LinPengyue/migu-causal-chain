"""Video-context narrative-fit review for adding source footage to a story cut.

FIRST_LIVE proves broadcast safety, NOT usefulness. Review evidence must bind
three temporal roles (before, candidate, after), an issue, source SHA and PTS.
This is a *review-supported hypothesis*, not proof of improved finished video.
No automatic event-heat/PTS proxy can manufacture semantic support.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from .first_live_window_evidence import window_key

SCHEMA = "v3a_narrative_fit_triplet_review_v1"
SUPPORTED = "REVIEW_SUPPORTED"
REJECTED = "REVIEW_REJECTED"
UNKNOWN = "NEEDS_VIDEO_REVIEW"
_ALLOWED_METHODS = {"human_video_triplet", "vlm_ordered_triplet_frames", "vlm_triplet_video"}
_REQUIRED_ROLES = {"before", "candidate", "after"}


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def load_narrative_fit_store(path: Optional[Path]) -> Dict[str, Any]:
    """Read optional independent reviews. Does not interpret first-live labels."""
    if path is None:
        return {"by_key": {}}
    p = Path(path)
    if p.is_dir():
        p = p / "narrative_fit_store.json"
    if not p.is_file():
        return {"by_key": {}, "load_error": f"missing_narrative_fit_store:{p}"}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("by_key"), dict):
            raise ValueError("expected by_key mapping")
        return data
    except (OSError, ValueError, TypeError) as exc:
        return {"by_key": {}, "load_error": f"{type(exc).__name__}:{exc}"}


def context_for_candidate(
    candidate: Mapping[str, Any],
    edl: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Exact adjacent source cut windows, never inferred from match-specific PTS."""
    ids = (
        str(candidate.get("insert_after_segment_id") or ""),
        str(candidate.get("before_segment_id") or ""),
    )
    found = {}
    for row in edl:
        sid = str(row.get("segment_id") or "")
        if sid not in ids or not row.get("include_in_cut", True):
            continue
        try:
            start, end = float(row["media_in"]), float(row["media_out"])
        except (ValueError, TypeError, KeyError):
            continue
        if start >= end:
            continue
        found[sid] = {
            "segment_id": sid,
            "role": str(row.get("role") or ""),
            "source_pts_start": start,
            "source_pts_end": end,
        }
    return {
        "issue_id": candidate.get("issue_id"),
        "before": found.get(ids[0]),
        "after": found.get(ids[1]),
        "candidate": {
            "source_pts_start": candidate.get("source_pts_start"),
            "source_pts_end": candidate.get("source_pts_end"),
            "event_id": candidate.get("event_id"),
            "event_type": candidate.get("event_type"),
        },
        "semantic_fit_not_inferred_from_gap_or_event_type": True,
    }


def validate_narrative_fit_review(
    record: Optional[Mapping[str, Any]],
    *,
    candidate: Mapping[str, Any],
    source_sha: Optional[str],
    edl: Sequence[Mapping[str, Any]],
    require_files_exist: bool = True,
) -> Dict[str, Any]:
    """A triplet review with cryptographic frame references, not a status string.

    Valid review is still judgment (human/VLM), never a ground-truth improvement
    or a replacement for final cut dual-video Verifier.
    """
    def fail(reason: str) -> Dict[str, Any]:
        return {"status": UNKNOWN, "binding_valid": False, "reason": reason}

    if not isinstance(record, Mapping):
        return fail("missing_triplet_review")
    if record.get("schema") != SCHEMA:
        return fail("wrong_review_schema")
    if not source_sha or str(record.get("source_sha256") or "") != str(source_sha):
        return fail("source_sha_mismatch")
    try:
        st, en = float(candidate["source_pts_start"]), float(candidate["source_pts_end"])
        rs, re = float(record["source_pts_start"]), float(record["source_pts_end"])
    except (KeyError, TypeError, ValueError):
        return fail("missing_candidate_pts")
    if abs(st-rs) > 0.05 or abs(en-re) > 0.05 or en <= st:
        return fail("candidate_pts_mismatch")
    if str(record.get("issue_id") or "") != str(candidate.get("issue_id") or ""):
        return fail("issue_binding_mismatch")
    ctx = context_for_candidate(candidate, edl)
    before, after = ctx["before"], ctx["after"]
    if not before or not after:
        return fail("missing_adjacent_cut_context")
    for label, seg in (("before", before), ("after", after)):
        if str(record.get(f"{label}_segment_id") or "") != seg["segment_id"]:
            return fail(f"{label}_segment_mismatch")
        try:
            a = float(record[f"{label}_pts_start"])
            b = float(record[f"{label}_pts_end"])
        except (ValueError, TypeError, KeyError):
            return fail(f"{label}_pts_missing")
        if abs(a-seg["source_pts_start"]) > 0.05 or abs(b-seg["source_pts_end"]) > 0.05:
            return fail(f"{label}_pts_mismatch")
    verdict = str(record.get("verdict") or "").upper()
    if verdict not in ("SUPPORTS_INSERT", "REJECT_INSERT", "UNCERTAIN"):
        return fail("invalid_review_verdict")
    if str(record.get("review_method") or "") not in _ALLOWED_METHODS:
        return fail("unsupported_review_method")

    frames = record.get("frame_refs")
    if not isinstance(frames, list) or len(frames) < 3:
        return fail("triplet_frame_refs_missing")
    seen = set()
    for fr in frames:
        if not isinstance(fr, Mapping):
            return fail("malformed_frame_ref")
        role = str(fr.get("role") or "")
        if role not in _REQUIRED_ROLES:
            return fail("unknown_frame_role")
        seen.add(role)
        win = {"before": before, "after": after, "candidate": ctx["candidate"]}[role]
        try:
            t = float(fr["source_pts_sec"])
        except (ValueError, TypeError, KeyError):
            return fail("frame_pts_missing")
        if not (float(win["source_pts_start"])-0.05 <= t <= float(win["source_pts_end"])+0.05):
            return fail(f"frame_pts_outside_{role}")
        sha = str(fr.get("sha256") or "").lower().removeprefix("sha256:")
        if len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
            return fail("frame_content_hash_missing")
        if require_files_exist:
            path = Path(str(fr.get("path") or ""))
            if not path.is_file() or _sha_file(path) != sha:
                return fail("frame_file_missing_or_digest_mismatch")
    if seen != _REQUIRED_ROLES:
        return fail("triplet_role_coverage_incomplete")

    review = record.get("narrative_review")
    if not isinstance(review, Mapping):
        return fail("missing_narrative_review")
    for k in ("before_to_candidate", "candidate_to_after", "new_story_information",
              "baseline_comparison"):
        if not isinstance(review.get(k), str) or len(review[k].strip()) < 8:
            return fail(f"missing_{k}_explanation")
    if str(record.get("review_method")) == "vlm_ordered_triplet_frames":
        # The provider must cite actual IDs it was sent for ALL three roles;
        # merely receiving 6 frames does not mean the model inspected them.
        cited = review.get("evidence_frame_ids")
        if not isinstance(cited, list):
            return fail("vlm_citation_list_missing")
        known = {
            str(fr.get("frame_id")): str(fr.get("role"))
            for fr in frames if fr.get("frame_id")
        }
        if not known or any(str(fid) not in known for fid in cited):
            return fail("vlm_cited_unsent_frame_id")
        cited_roles = {known[str(fid)] for fid in cited}
        if cited_roles != _REQUIRED_ROLES:
            return fail("vlm_triplet_citation_coverage_incomplete")
    if verdict == "SUPPORTS_INSERT":
        if not review.get("missing_information_addressed"):
            return fail("no_diagnosed_missing_information_addressed")
        if not review.get("falsifiable_gain"):
            return fail("no_falsifiable_gain")
    status = (
        SUPPORTED if verdict == "SUPPORTS_INSERT"
        else REJECTED if verdict == "REJECT_INSERT"
        else UNKNOWN
    )
    return {
        "status": status,
        "binding_valid": True,
        "reason": "triplet_review_bound_not_proof_of_improvement",
        "review_method": record["review_method"],
        "review_verdict": verdict,
        "story_function": review.get("story_function"),
        "missing_information_addressed": review.get("missing_information_addressed"),
        "new_story_information": review.get("new_story_information"),
        "falsifiable_gain": review.get("falsifiable_gain"),
        "source_review_key": window_key(str(source_sha), st, en),
        "frame_ref_count": len(frames),
    }


def annotate_narrative_fit(
    candidate: Mapping[str, Any],
    *,
    source_sha: Optional[str],
    edl: Sequence[Mapping[str, Any]],
    evidence_store: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    row = dict(candidate)
    row["narrative_context"] = context_for_candidate(row, edl)
    key = window_key(str(source_sha or ""), float(row["source_pts_start"]),
                     float(row["source_pts_end"]))
    store = evidence_store if isinstance(evidence_store, Mapping) else {}
    result = validate_narrative_fit_review(
        (store.get("by_key") or {}).get(key),
        candidate=row,
        source_sha=source_sha,
        edl=edl,
        require_files_exist=True,
    )
    row["narrative_fit"] = result
    row["narrative_fit_status"] = result["status"]
    row["narrative_fit_reviewed"] = bool(result.get("binding_valid"))
    row["narrative_fit_supports_insert"] = result["status"] == SUPPORTED
    row["narrative_fit_rejects_insert"] = result["status"] == REJECTED
    return row


def enforce_narrative_fit_on_plan(
    plan: Mapping[str, Any],
    *,
    search_report: Mapping[str, Any],
    diagnosis: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Independent post-LLM apply gate, including LLM-authored search_add.

    Model-produced prose or a self-declared FIRST_LIVE / narrative-fit flag
    never substitutes for a Search row validated against actual frame bytes.
    This does not constrain existing-footage trim/drop/reorder decisions.
    """
    approved = [
        c for c in (search_report.get("narrative_fit_supported_candidates") or [])
        if isinstance(c, Mapping)
        and c.get("executable_safe_revision") is True
        and c.get("narrative_fit_supports_insert") is True
        and (c.get("narrative_fit") or {}).get("binding_valid") is True
    ]

    confirmed_issues = None
    if diagnosis is not None:
        confirmed_issues = {
            str(i.get("issue_id"))
            for i in (diagnosis.get("issues") or [])
            if isinstance(i, Mapping) and i.get("issue_id")
            and (
                i.get("story_defect_confirmed") is True
                or str(i.get("diagnosis_status") or "") in (
                    "CONFIRMED_STORY_DEFECT", "CONFIRMED_STRUCTURE_DEFECT"
                )
            )
        }

    def approved_for(intent: Mapping[str, Any]) -> bool:
        if confirmed_issues is not None and str(intent.get("issue_id") or "") not in confirmed_issues:
            return False
        span = intent.get("bound_source_window")
        if not isinstance(span, Mapping):
            return False
        try:
            start, end = float(span["start"]), float(span["end"])
        except (KeyError, TypeError, ValueError):
            return False
        iid = str(intent.get("issue_id") or "")
        after = str(intent.get("insert_after_segment_id") or "")
        before = str(intent.get("before_segment_id") or "")
        for c in approved:
            try:
                cs, ce = float(c["source_pts_start"]), float(c["source_pts_end"])
            except (KeyError, TypeError, ValueError):
                continue
            if (abs(cs-start) > .05 or abs(ce-end) > .05
                or str(c.get("issue_id") or "") != iid
                or str(c.get("insert_after_segment_id") or "") != after
                or str(c.get("before_segment_id") or "") != before):
                continue
            return True
        return False

    out = dict(plan)
    intents = []
    blocked = []
    for raw in (out.get("revision_intents") or []):
        if not isinstance(raw, Mapping):
            continue
        it = dict(raw)
        action = str(it.get("action") or "")
        # Replace can obtain new footage from observations even without an
        # explicit bound_source_window (see apply_candidate_revision fallback).
        # Require exact reviewed source-window proof for either action.
        adds_new_source = action in ("search_add", "replace")
        if adds_new_source and not approved_for(it):
            blocked.append({
                "intent_id": it.get("intent_id"),
                "issue_id": it.get("issue_id"),
                "blocked_action": action,
                "reason": (
                    "missing_confirmed_issue_or_authenticated_triplet_narrative_gain"
                    "_for_exact_source_and_anchors"
                ),
            })
            it = {
                **it,
                "action": "mark_unresolved",
                "blocked_original_action": action,
                "block_reason": "missing_bound_video_triplet_narrative_fit",
                "narrative_purpose": "candidate_needs_contextual_video_review",
            }
        intents.append(it)
    out["revision_intents"] = intents
    out["narrative_fit_apply_gate"] = {
        "required": True,
        "approved_candidate_count": len(approved),
        "blocked_intents": blocked,
        "n_blocked": len(blocked),
    }
    mutate = any(
        str(i.get("action") or "") not in ("keep", "mark_unresolved", "unresolved")
        for i in intents
    )
    if blocked and not mutate:
        out["decision"] = "UNRESOLVED"
        out["normalize_note"] = "narrative_fit_apply_gate_blocked_all_mutating_intents"
    return out
