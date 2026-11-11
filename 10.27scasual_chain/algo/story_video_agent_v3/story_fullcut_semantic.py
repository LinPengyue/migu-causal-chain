"""Evidence-grounded *sampled* full-cut story comparison.

The finished baseline and candidate both contribute frames around the change
and its eventual payoff. This is an editorial screening signal, NOT a
continuous-video quality certificate. Final release/Best promotion requires
stronger evidence (native full-video or independent human review).
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Set

SCHEMA = "v3a_fullcut_semantic_screen_v1"
_SAMPLE_NEEDS = {"pre_edit", "edit_impact", "post_edit", "global_ending"}
_ASPECTS = ("information_gain", "beat_continuity", "pacing_tradeoff",
            "redundancy", "global_regression")


def _sha256(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def screen_fullcut_semantic_gain(
    review: Optional[Mapping[str, Any]],
    *,
    frame_pack: Optional[Mapping[str, Any]],
    baseline_mp4: Path,
    candidate_mp4: Path,
    baseline_mp4_sha256: Optional[str] = None,
    candidate_mp4_sha256: Optional[str] = None,
    finish_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Check actual two-cut citations and contextual claims; never auto-promote.

    Model verdicts are untrusted content, including any alleged hash or
    provenance fields. Only this caller can bind bytes and execution mode.
    """
    reasons = []
    frames = list((frame_pack or {}).get("frames") or [])
    if not (frame_pack or {}).get("ok"):
        reasons.append("dual_video_frame_pack_not_valid")
    bsha = _sha256(Path(baseline_mp4))
    csha = _sha256(Path(candidate_mp4))
    if not bsha or not csha:
        reasons.append("missing_or_unreadable_finished_mp4")
    if baseline_mp4_sha256 and bsha != baseline_mp4_sha256:
        reasons.append("baseline_mp4_sha_mismatch")
    if candidate_mp4_sha256 and csha != candidate_mp4_sha256:
        reasons.append("candidate_mp4_sha_mismatch")
    if bsha and csha and bsha == csha:
        reasons.append("identical_finished_mp4_bytes")
    if str(finish_reason or "").lower() == "length":
        reasons.append("vlm_response_truncated")
    by_id: Dict[str, Dict[str, Any]] = {}
    cited_roles: Dict[str, Set[str]] = {"baseline": set(), "candidate": set()}
    hashes: Dict[str, str] = {}
    for fr in frames:
        if not isinstance(fr, Mapping):
            continue
        fid, video = str(fr.get("frame_id") or ""), str(fr.get("video_tag") or "")
        role = str(fr.get("narrative_slot") or "")
        if not fid or video not in cited_roles or fid in by_id:
            reasons.append("duplicate_or_unbound_frame_id")
            continue
        path = Path(str(fr.get("path") or ""))
        sha = _sha256(path)
        if sha is None:
            reasons.append("extracted_frame_file_missing")
            continue
        by_id[fid] = dict(fr)
        cited_roles[video].add(role)
        hashes[fid] = sha
    if not (len(by_id) >= 6 and cited_roles["baseline"] and cited_roles["candidate"]):
        reasons.append("insufficient_citable_dual_frames")
    # Frames from each role must exist on both sides to distinguish omission
    # from story change. Missing global ending => cannot exclude obvious damage.
    missing_slots = _SAMPLE_NEEDS - (
        cited_roles["baseline"] & cited_roles["candidate"]
    )
    if missing_slots:
        reasons.append("unobserved_fullcut_context:" + ",".join(sorted(missing_slots)))
    if not isinstance(review, Mapping):
        reasons.append("missing_structured_fullcut_comparison")

    def _result(status: str, advisory: str, *, details: Optional[dict] = None) -> Dict[str, Any]:
        return {
            "schema": SCHEMA,
            "status": status,
            "quality_advisory": advisory,
            "reasons": reasons,
            "baseline_mp4_sha256": bsha,
            "candidate_mp4_sha256": csha,
            "sampled_frame_sha256": hashes,
            "citable_frames": sorted(by_id),
            "observed_roles_baseline": sorted(cited_roles["baseline"]),
            "observed_roles_candidate": sorted(cited_roles["candidate"]),
            "missing_required_context_slots": sorted(missing_slots),
            "evaluation_scope": "aligned_sampled_finished_cuts_not_continuous_video",
            "claims_full_video_watch": False,
            "audio_and_motion_continuity_checked": False,
            "authorizes_promote_best": False,
            "authorizes_release": False,
            "improvement_verified": False,
            **(details or {}),
        }

    if reasons:
        return _result("UNVERIFIED", "UNCERTAIN")
    assert isinstance(review, Mapping)
    # Require concrete language plus frame refs in BOTH versions. An isolated
    # CANDIDATE shot cannot establish incremental gain over the baseline.
    citations: Dict[str, list] = {}
    aspect_decisions: Dict[str, str] = {}
    for name in _ASPECTS:
        item = review.get(name)
        if not isinstance(item, Mapping):
            reasons.append("missing_aspect:" + name)
            continue
        verdict = str(item.get("verdict") or "").upper()
        detail = str(item.get("observed_difference") or "").strip()
        refs = item.get("frame_ids")
        if not isinstance(refs, list):
            refs = []
        unknown = [str(fid) for fid in refs if str(fid) not in by_id]
        if unknown:
            reasons.append("unknown_frame_ids:" + name)
        used = [str(fid) for fid in refs if str(fid) in by_id]
        if len(detail) < 20:
            reasons.append("non_substantive_aspect:" + name)
        if not any(by_id[fid]["video_tag"] == "baseline" for fid in used) or not any(
            by_id[fid]["video_tag"] == "candidate" for fid in used
        ):
            reasons.append("missing_two_cut_comparison:" + name)
        citations[name] = used
        aspect_decisions[name] = verdict

    info = aspect_decisions.get("information_gain")
    continuity = aspect_decisions.get("beat_continuity")
    pacing = aspect_decisions.get("pacing_tradeoff")
    redundant = aspect_decisions.get("redundancy")
    regressed = aspect_decisions.get("global_regression")
    all_edit = citations.get("information_gain") or []
    if not any(
        str(by_id[fid].get("narrative_slot")) == "edit_impact" for fid in all_edit
    ):
        reasons.append("information_gain_not_cited_at_edit")
    # At least one improvement claim needs a matched pre/post context, not a
    # newly added interesting event in isolation.
    context_refs = (citations.get("beat_continuity") or [])
    if not any(
        str(by_id[fid].get("narrative_slot")) in ("pre_edit", "post_edit")
        for fid in context_refs
    ):
        reasons.append("no_contextual_continuity_citation")

    valid = not reasons
    details = {
        "aspect_verdicts": aspect_decisions,
        "aspect_citations": citations,
        "model_recommendation": review.get("recommendation"),
        "marginal_gain_explanation": review.get("marginal_gain_vs_duration"),
    }
    if not valid:
        return _result("UNVERIFIED", "UNCERTAIN", details=details)
    # A negative, well-cited screen is a meaningful reason to reject the current
    # candidate. It is NOT evidence that this source window is useless forever.
    if (
        info in ("NO", "NONE")
        or continuity == "WORSE"
        or pacing == "NOT_JUSTIFIED"
        or redundant == "YES"
        or regressed == "YES"
    ):
        return _result("SCREENED_NO_GAIN", "SAME", details=details)
    if (
        info == "YES"
        and continuity == "IMPROVED"
        and pacing == "JUSTIFIED"
        and redundant == "NO"
        and regressed == "NO"
        and str(review.get("recommendation") or "").upper() == "CANDIDATE_PREFERABLE"
        and len(str(review.get("marginal_gain_vs_duration") or "").strip()) >= 28
    ):
        return _result("SCREENED_BETTER", "PROMISING", details=details)
    return _result("UNVERIFIED", "UNCERTAIN", details=details)


def constrain_sampled_verifier_payload(
    validated: Mapping[str, Any],
    fullcut_screen: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Convert a sparse-frame model opinion to an advisory, never formal gain.

    Applying this AFTER the real provider call prevents a model's own
    accept_candidate/BETTER/REAL_VLM claims from bypassing final safety gates.
    """
    status = str((fullcut_screen or {}).get("status") or "UNVERIFIED")
    advisory = {
        "SCREENED_BETTER": "PROMISING",
        "SCREENED_NO_GAIN": "SAME",
    }.get(status, "UNCERTAIN")
    return {
        **dict(validated),
        "quality_delta_vs_baseline": "NOT_EVALUATED",
        "accept_candidate": False,
        "soft_quality": advisory,
        "phase8_quality": advisory,
        "global_regression": "UNKNOWN",
        "original_issue_resolved": None,
        "fullcut_semantic_screen_status": status,
        "sampled_stills_not_fullcut_semantic_certificate": True,
    }
