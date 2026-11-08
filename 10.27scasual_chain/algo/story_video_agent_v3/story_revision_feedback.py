"""Phase 8 revision feedback memory — pure logic / JSON I/O, no API calls.

Architecture contract: docs/PHASE8_FAILURE_AWARE_ITERATIVE_STORY_REVISION_DESIGN.md §2.A
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

QUALITY_LABELS = frozenset({"BETTER", "PROMISING", "SAME", "WORSE", "UNCERTAIN"})
FAILURE_CLASSES = frozenset(
    {
        "CONFIRMED_NEGATIVE",
        "UNCERTAIN_OR_UNVERIFIED",
        "POSITIVE",
        "TECHNICAL_FAILURE",
        "HARD_SAFETY_VETO",
    }
)
_LEGACY_QUALITY = {
    "IMPROVED": "BETTER",
    "BETTER": "BETTER",
    "PROMISING": "PROMISING",
    "SAME": "SAME",
    "WORSE": "WORSE",
    "REGRESSED": "WORSE",
    "UNCERTAIN": "UNCERTAIN",
    "UNRESOLVED": "UNCERTAIN",
    "NOT_EVALUATED": "UNCERTAIN",
    "FAILED": "UNCERTAIN",
}


def normalize_quality(raw: Any) -> str:
    if raw is None:
        return "UNCERTAIN"
    s = str(raw).strip().upper()
    if s in QUALITY_LABELS:
        return s
    return _LEGACY_QUALITY.get(s, "UNCERTAIN")


def _looks_like_content_hash(token: Any) -> bool:
    if token is None:
        return False
    s = str(token).strip().lower()
    if s.startswith("sha256:"):
        s = s[7:]
    if len(s) not in (64, 40):
        return False
    return all(c in "0123456789abcdef" for c in s)


def make_observation_evidence_token(
    *,
    source_sha: Optional[str] = None,
    pts_start: Any = None,
    pts_end: Any = None,
    observation_id: Optional[str] = None,
    frame_hashes: Optional[Sequence[Any]] = None,
    manifest_digest: Optional[str] = None,
) -> Optional[str]:
    """Bind evidence identity to source digest + PTS + frame-*byte* hashes / manifest.

    Round counters, version ids, and plain frame_ids (baseline_a) are rejected —
    they must not create a fresh observation-grade identity.
    """
    try:
        a = float(pts_start)
        b = float(pts_end)
    except (TypeError, ValueError):
        return None
    if b <= a:
        return None
    sha = str(source_sha or "").strip() or "NOSHA"
    content_hashes = [
        str(h).replace("sha256:", "").lower()
        for h in (frame_hashes or [])
        if _looks_like_content_hash(h)
    ][:4]
    man = str(manifest_digest or "").replace("sha256:", "").lower()
    if man and not _looks_like_content_hash(man):
        man = ""
    # observation_id is advisory only when content hashes exist; alone it is NOT enough.
    obs = str(observation_id or "").strip()
    if obs and (
        ":" in obs
        and any(obs.startswith(p) for p in ("v", "r", "round", "cand"))
        or obs.startswith("v")
        and ":r" in obs
    ):
        # Drop round/version-shaped ids from the token material.
        obs = ""
    if content_hashes or man:
        hash_part = ",".join(content_hashes) if content_hashes else "noframes"
        man_part = man or "nomanifest"
        return f"obs:{sha}|{a:.3f}:{b:.3f}|{man_part}|{hash_part}"
    # Without content hashes / manifest digest → window identity only (NOT observation-grade unlock).
    return f"sha:{sha}|{a:.3f}:{b:.3f}"


def is_observation_grade_evidence_token(token: Optional[str]) -> bool:
    """Observation-grade tokens must embed content hashes / manifest, not bare sha: window ids."""
    if not token:
        return False
    s = str(token)
    if s.startswith("verified:"):
        return True
    if not s.startswith("obs:"):
        return False
    # obs:sha|pts|manifest_or_nomanifest|hashes — reject nomanifest+noframes
    parts = s.split("|")
    if len(parts) < 4:
        return False
    man_part = parts[2]
    hash_part = parts[3]
    if man_part not in ("nomanifest", "") and _looks_like_content_hash(man_part):
        return True
    hashes = [h for h in hash_part.split(",") if h and h != "noframes"]
    return bool(hashes) and all(_looks_like_content_hash(h) for h in hashes)


def issue_signature_from_case(case: Mapping[str, Any]) -> Dict[str, Any]:
    """Canonical signature — not raw issue_id alone (IDs may change each round)."""
    problem = case.get("original_story_problem") or {}
    apply_row = ((case.get("candidate_footage") or {}).get("apply")) or {}
    anchors = []
    for key in ("insert_after_segment_id", "before_segment_id", "target_segment_id"):
        v = apply_row.get(key) or case.get(key)
        if v:
            anchors.append(str(v))
    seg_ids = problem.get("segment_ids") or case.get("segment_ids") or []
    for s in seg_ids:
        if s and str(s) not in anchors:
            anchors.append(str(s))
    return {
        "template_id": case.get("template_id") or case.get("match_tag") or "unknown_template",
        "category": problem.get("story_role")
        or problem.get("category")
        or case.get("category")
        or "unknown",
        "anchor_segment_ids": anchors[:4],
        "missing_narrative_info": problem.get("missing_information")
        or case.get("defect_cause_hypothesis")
        or "unspecified",
        "issue_id_raw": case.get("issue_id"),
    }


def candidate_identity(
    *,
    match_id: Optional[str],
    story_template: Optional[str],
    issue_signature: Mapping[str, Any],
    parent_id: Optional[str],
    action: Optional[str],
    source_pts: Optional[Sequence[Any]],
    insert_anchor: Optional[str],
) -> str:
    pts = list(source_pts or [])
    pts_s = ""
    if len(pts) >= 2:
        try:
            pts_s = f"{float(pts[0]):.3f}:{float(pts[1]):.3f}"
        except (TypeError, ValueError):
            pts_s = f"{pts[0]}:{pts[1]}"
    anchors = ",".join(str(x) for x in (issue_signature.get("anchor_segment_ids") or [])[:3])
    cat = issue_signature.get("category") or ""
    missing = str(issue_signature.get("missing_narrative_info") or "")[:80]
    return "|".join(
        [
            str(match_id or ""),
            str(story_template or issue_signature.get("template_id") or ""),
            str(cat),
            anchors,
            missing,
            str(parent_id or ""),
            str(action or ""),
            pts_s,
            str(insert_anchor or ""),
        ]
    )


def _pts_iou(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) < 2 or len(b) < 2:
        return 0.0
    lo = max(float(a[0]), float(b[0]))
    hi = min(float(a[1]), float(b[1]))
    inter = max(0.0, hi - lo)
    if inter <= 0:
        return 0.0
    ua = max(0.0, float(a[1]) - float(a[0]))
    ub = max(0.0, float(b[1]) - float(b[0]))
    union = ua + ub - inter
    return inter / union if union > 0 else 0.0


def classify_failure_class(
    *,
    quality: str,
    evidence_status: str,
    hard_vetoes: Optional[Sequence[Any]] = None,
    technical_error: bool = False,
    semantic_status: Optional[str] = None,
) -> str:
    """Narrative REJECT alone is never CONFIRMED_NEGATIVE."""
    if hard_vetoes:
        return "HARD_SAFETY_VETO"
    if technical_error or str(semantic_status or "").upper() in (
        "NOT_EVALUATED",
        "FAILED",
    ) and evidence_status == "INSUFFICIENT":
        # Truncation / parse / insufficient citations → technical or unverified
        if technical_error:
            return "TECHNICAL_FAILURE"
    q = normalize_quality(quality)
    ev = str(evidence_status or "INSUFFICIENT").upper()
    if q in ("BETTER", "PROMISING") and ev in ("SUFFICIENT", "PARTIAL"):
        return "POSITIVE"
    if q == "WORSE" and ev == "SUFFICIENT":
        return "CONFIRMED_NEGATIVE"
    if technical_error:
        return "TECHNICAL_FAILURE"
    return "UNCERTAIN_OR_UNVERIFIED"


def _evidence_status_from_verifier(verifier_report: Mapping[str, Any]) -> str:
    dual = verifier_report.get("dual_verifier") or {}
    full = verifier_report.get("dual_verifier_full") or {}
    sem = str(
        dual.get("semantic_verification_status")
        or full.get("semantic_verification_status")
        or ""
    ).upper()
    if sem == "PASSED" and verifier_report.get("vision_backed"):
        return "SUFFICIENT"
    if verifier_report.get("sent_frame_ids") and sem in ("FAILED", "PASSED"):
        return "PARTIAL"
    if verifier_report.get("warnings") or full.get("error") or not verifier_report.get(
        "vision_backed"
    ):
        return "INSUFFICIENT"
    if sem in ("NOT_EVALUATED", ""):
        return "INSUFFICIENT"
    return "PARTIAL"


def normalize_feedback(
    round_case_bundle: Mapping[str, Any],
    verifier_report: Mapping[str, Any],
    apply_report: Optional[Mapping[str, Any]] = None,
    *,
    candidate_metadata: Optional[Mapping[str, Any]] = None,
    round_idx: int = 1,
    source_kind: str = "REAL_VIDEO_OR_FIXTURE_EXPLICIT",
) -> List[Dict[str, Any]]:
    """Convert Phase6/7 case bundle + verifier into Phase8 feedback entries."""
    meta = dict(candidate_metadata or {})
    apply_report = apply_report or {}
    evidence_status = _evidence_status_from_verifier(verifier_report)
    hard_vetoes = list(verifier_report.get("hard_vetoes") or [])
    technical = bool(
        (verifier_report.get("dual_verifier_full") or {}).get("error")
        or "parse" in str((verifier_report.get("dual_verifier_full") or {}).get("error") or "").lower()
        or "truncated" in str(verifier_report.get("warnings") or "").lower()
        or evidence_status == "INSUFFICIENT"
        and str(
            (verifier_report.get("dual_verifier") or {}).get("semantic_verification_status") or ""
        ).upper()
        == "NOT_EVALUATED"
    )
    dual_full = verifier_report.get("dual_verifier_full") or {}
    validated = dual_full.get("validated") or {}
    entries: List[Dict[str, Any]] = []
    cases = list(round_case_bundle.get("cases") or [])
    if not cases:
        # Still record a round-level technical entry when verifier failed closed.
        q = normalize_quality(
            (verifier_report.get("dual_verifier") or {}).get("quality_delta_vs_baseline")
            or validated.get("quality_delta_vs_baseline")
        )
        fc = classify_failure_class(
            quality=q,
            evidence_status=evidence_status,
            hard_vetoes=hard_vetoes,
            technical_error=technical,
            semantic_status=(verifier_report.get("dual_verifier") or {}).get(
                "semantic_verification_status"
            ),
        )
        entries.append(
            {
                "schema": "v3a_phase8_feedback_v1",
                "round": round_idx,
                "issue_signature": {
                    "template_id": meta.get("template_id") or "unknown",
                    "category": "unknown",
                    "anchor_segment_ids": [],
                    "missing_narrative_info": "unspecified",
                },
                "intent_id": None,
                "action": None,
                "source_pts": None,
                "parent_version_id": meta.get("parent_version_id"),
                "candidate_version_id": meta.get("candidate_version_id"),
                "quality": q,
                "evidence_status": evidence_status,
                "failure_class": fc,
                "observation": "no_revision_cases; verifier-level feedback only",
                "next_search_requirement": "prefer_alternate_live_with_visible_narrative_function",
                "source_kind": source_kind,
                "evidence_refs": list(verifier_report.get("sent_frame_ids") or []),
                "new_evidence_required_for_retry": True,
                "legacy_accept_candidate": verifier_report.get("candidate_accepted"),
                "sent_frame_ids": list(verifier_report.get("sent_frame_ids") or []),
                "observation_limitations": [
                    "sparse_dual_frames_not_full_video_watch",
                    str((verifier_report.get("dual_verifier_full") or {}).get("error") or ""),
                ],
            }
        )
        return entries

    for case in cases:
        if not isinstance(case, dict):
            continue
        vj = case.get("verifier_judgment") or {}
        # Prefer per-case judgment; fall back to recovered validated judgments.
        q_raw = vj.get("quality_judgment")
        if q_raw is None:
            q_raw = validated.get("quality_delta_vs_baseline")
        q = normalize_quality(q_raw)
        # Opaque REJECT / null judgment with insufficient evidence → UNCERTAIN, not WORSE.
        if q_raw is None and evidence_status == "INSUFFICIENT":
            q = "UNCERTAIN"
            technical = True
        pts_obj = ((case.get("candidate_footage") or {}).get("source_pts")) or {}
        pts = None
        if pts_obj.get("start") is not None and pts_obj.get("end") is not None:
            try:
                pts = [float(pts_obj["start"]), float(pts_obj["end"])]
            except (TypeError, ValueError):
                pts = [pts_obj["start"], pts_obj["end"]]
        apply_row = ((case.get("candidate_footage") or {}).get("apply")) or {}
        sig = issue_signature_from_case(case)
        fc = classify_failure_class(
            quality=q,
            evidence_status=evidence_status,
            hard_vetoes=hard_vetoes,
            technical_error=technical
            or (
                "verifier_or_pipeline_rejected" in list(case.get("failure_reasons") or [])
                and evidence_status != "SUFFICIENT"
            ),
            semantic_status=(verifier_report.get("dual_verifier") or {}).get(
                "semantic_verification_status"
            )
            or vj.get("semantic_verification_status"),
        )
        # Explicit rule: historical Phase7-style opaque REJECT ≠ CONFIRMED_NEGATIVE.
        if fc == "CONFIRMED_NEGATIVE" and evidence_status != "SUFFICIENT":
            fc = "UNCERTAIN_OR_UNVERIFIED"
        next_req = "Find visually evident buildup/pressure/turn, not just chronological bridge"
        if fc == "CONFIRMED_NEGATIVE":
            next_req = "Avoid same-context equivalent PTS+action; try distinct narrative function"
        elif fc == "POSITIVE":
            next_req = "Keep gains; repair residual issues with complementary LIVE"
        elif fc == "TECHNICAL_FAILURE":
            next_req = "Reobserve edit-locus continuous context; do not treat as semantic negative"
        entries.append(
            {
                "schema": "v3a_phase8_feedback_v1",
                "round": round_idx,
                "issue_signature": sig,
                "intent_id": case.get("revision_intent_id"),
                "action": case.get("target_action") or apply_row.get("action"),
                "source_pts": pts,
                "parent_version_id": meta.get("parent_version_id"),
                "candidate_version_id": meta.get("candidate_version_id"),
                "quality": q,
                "evidence_status": evidence_status,
                "failure_class": fc,
                "observation": case.get("actual_observation")
                or vj.get("observed_visuals")
                or "No independently confirmed narrative benefit",
                "next_search_requirement": next_req,
                "source_kind": source_kind,
                "evidence_refs": vj.get("evidence_refs")
                or list(verifier_report.get("sent_frame_ids") or []),
                "new_evidence_required_for_retry": True,
                "candidate_identity": candidate_identity(
                    match_id=meta.get("match_id"),
                    story_template=sig.get("template_id"),
                    issue_signature=sig,
                    parent_id=meta.get("parent_version_id"),
                    action=case.get("target_action") or apply_row.get("action"),
                    source_pts=pts,
                    insert_anchor=apply_row.get("insert_after_segment_id"),
                ),
                "legacy_final_decision": case.get("final_decision"),
                "legacy_failure_reasons": list(case.get("failure_reasons") or []),
                "legacy_accept_candidate": verifier_report.get("candidate_accepted"),
                "pts_permanently_banned": False,
                "sent_frame_ids": list(verifier_report.get("sent_frame_ids") or []),
                "evidence_token": (
                    meta.get("evidence_token")
                    if is_observation_grade_evidence_token(meta.get("evidence_token"))
                    else None
                )
                or make_observation_evidence_token(
                    source_sha=meta.get("source_sha"),
                    pts_start=pts[0] if pts else None,
                    pts_end=pts[1] if pts else None,
                    observation_id=apply_row.get("observation_ref")
                    or case.get("revision_intent_id"),
                    frame_hashes=meta.get("frame_hashes")
                    or verifier_report.get("sent_frame_ids"),
                ),
                "apply_status": apply_row.get("status"),
                "observation_limitations": [
                    "claims_full_video_watch=false",
                    "sparse_or_truncated_verifier_must_not_become_confirmed_negative",
                ],
            }
        )
    return entries


def summarize_feedback(
    memory: Sequence[Mapping[str, Any]],
    current_issue_signatures: Optional[Sequence[Mapping[str, Any]]] = None,
    *,
    max_items: int = 12,
) -> Dict[str, Any]:
    """Compact Planner / search input."""
    rows = list(memory or [])[-max_items:]
    confirmed_neg = [r for r in rows if r.get("failure_class") == "CONFIRMED_NEGATIVE"]
    uncertain = [r for r in rows if r.get("failure_class") == "UNCERTAIN_OR_UNVERIFIED"]
    technical = [r for r in rows if r.get("failure_class") == "TECHNICAL_FAILURE"]
    positive = [r for r in rows if r.get("failure_class") == "POSITIVE"]
    tried = []
    for r in rows:
        tried.append(
            {
                "round": r.get("round"),
                "action": r.get("action"),
                "source_pts": r.get("source_pts"),
                "quality": r.get("quality"),
                "failure_class": r.get("failure_class"),
                "issue_signature": r.get("issue_signature"),
                "next_search_requirement": r.get("next_search_requirement"),
                "new_evidence_required_for_retry": r.get("new_evidence_required_for_retry", True),
            }
        )
    return {
        "schema": "v3a_phase8_feedback_summary_v1",
        "n_records": len(memory or []),
        "tried_revisions": tried,
        "confirmed_negatives": confirmed_neg[-max_items:],
        "uncertain_or_unverified": uncertain[-max_items:],
        "technical_failures": technical[-max_items:],
        "positives": positive[-max_items:],
        "current_issue_signatures": list(current_issue_signatures or []),
        "forbid_identical_retry_without_new_evidence": True,
        "never_permanently_ban_pts": True,
        "opaque_reject_is_not_confirmed_negative": True,
    }


def should_penalize_candidate(
    memory: Sequence[Mapping[str, Any]],
    *,
    issue_signature: Mapping[str, Any],
    action: Optional[str],
    source_pts: Optional[Sequence[Any]],
    iou_threshold: float = 0.6,
    new_evidence_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Context-sensitive overlap penalty; never permanent PTS blacklist."""
    if not source_pts or len(source_pts) < 2:
        return {"penalize": False, "suppress": False, "reason": None}
    try:
        window = [float(source_pts[0]), float(source_pts[1])]
    except (TypeError, ValueError):
        return {"penalize": False, "suppress": False, "reason": None}

    for r in reversed(list(memory or [])):
        if action and str(r.get("action") or "") != str(action):
            continue
        prev_pts = r.get("source_pts") or []
        if len(prev_pts) < 2:
            continue
        try:
            prev = [float(prev_pts[0]), float(prev_pts[1])]
        except (TypeError, ValueError):
            continue
        if _pts_iou(window, prev) < iou_threshold:
            continue
        # Contextual signature: category + anchors + missing-info (P1-8).
        prev_sig = r.get("issue_signature") or {}
        same_cat = prev_sig.get("category") == issue_signature.get("category")
        if not same_cat:
            continue
        prev_anchors = {str(x) for x in (prev_sig.get("anchor_segment_ids") or []) if x}
        cur_anchors = {str(x) for x in (issue_signature.get("anchor_segment_ids") or []) if x}
        # Different story placement (no shared anchors) ⇒ allow same PTS reuse.
        if prev_anchors and cur_anchors and prev_anchors.isdisjoint(cur_anchors):
            continue
        prev_miss = str(prev_sig.get("missing_narrative_info") or "")
        cur_miss = str(issue_signature.get("missing_narrative_info") or "")
        if prev_miss and cur_miss and prev_miss != cur_miss and not prev_anchors.intersection(cur_anchors):
            continue
        # Unlock ONLY with a new observation-grade evidence token (source SHA+PTS+
        # frames/obs id). Round counters / candidate_id must NOT bypass suppression.
        prior_tok = r.get("evidence_token")
        if (
            is_observation_grade_evidence_token(new_evidence_token)
            and is_observation_grade_evidence_token(prior_tok)
            and new_evidence_token != prior_tok
        ):
            continue
        fc = r.get("failure_class")
        if fc == "CONFIRMED_NEGATIVE":
            return {
                "penalize": True,
                "suppress": True,
                "reason": "confirmed_negative_same_context_pts_overlap",
                "pts_permanently_banned": False,
            }
        if fc in ("UNCERTAIN_OR_UNVERIFIED", "TECHNICAL_FAILURE", "POSITIVE"):
            return {
                "penalize": True,
                "suppress": True if fc != "POSITIVE" else True,
                "reason": f"repeat_blocked_need_new_evidence:{fc}",
                "pts_permanently_banned": False,
                "weak_uncertain": fc != "CONFIRMED_NEGATIVE",
            }
    return {"penalize": False, "suppress": False, "reason": None}


class RevisionFeedbackStore:
    """Per-run memory with JSON persistence."""

    def __init__(self) -> None:
        self.schema = "v3a_phase8_feedback_memory_v1"
        self.records: List[Dict[str, Any]] = []

    def extend(self, entries: Sequence[Mapping[str, Any]]) -> None:
        for e in entries:
            row = dict(e)
            row.setdefault("schema", "v3a_phase8_feedback_v1")
            row["pts_permanently_banned"] = False
            self.records.append(row)

    def summary(
        self, current_issue_signatures: Optional[Sequence[Mapping[str, Any]]] = None
    ) -> Dict[str, Any]:
        return summarize_feedback(self.records, current_issue_signatures)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "n_records": len(self.records),
            "records": list(self.records),
            "summary": self.summary(),
        }

    def write_json(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RevisionFeedbackStore":
        store = cls()
        for r in data.get("records") or []:
            if isinstance(r, dict):
                store.records.append(dict(r))
        return store


def load_phase7_round_into_feedback(
    phase7_round_dir: Path,
    *,
    store: Optional[RevisionFeedbackStore] = None,
    source_kind: str = "PHASE7_HISTORICAL_ARTIFACT",
) -> RevisionFeedbackStore:
    """Offline helper: ingest Phase7 round JSON without re-running models."""
    store = store or RevisionFeedbackStore()
    root = Path(phase7_round_dir)
    cases_path = root / "revision_cases.json"
    vfix_path = root / "verifier_report.json"
    apply_path = root / "apply_report.json"
    if not cases_path.is_file() or not vfix_path.is_file():
        return store
    bundle = json.loads(cases_path.read_text(encoding="utf-8"))
    vfix = json.loads(vfix_path.read_text(encoding="utf-8"))
    apply_report = (
        json.loads(apply_path.read_text(encoding="utf-8")) if apply_path.is_file() else {}
    )
    entries = normalize_feedback(
        bundle,
        vfix,
        apply_report,
        candidate_metadata={
            "parent_version_id": "v0",
            "candidate_version_id": "v1_phase7",
            "match_id": None,
        },
        round_idx=1,
        source_kind=source_kind,
    )
    store.extend(entries)
    return store
