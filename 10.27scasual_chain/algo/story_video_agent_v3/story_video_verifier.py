"""Dual-video story verifier — compare baseline vs candidate using video probes + gates.

Must not accept solely on EDL field diffs. Offline semantic path remains NOT_EVALUATED.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .fresh_e2e_cli import edl_diff, validate_render_rows
from .hybrid_fallback import run_dual_verifier, run_rule_verifier
from .story_timeline import build_story_timeline, protected_goal_segment_ids


def _ffprobe_duration(path: Path) -> Optional[float]:
    if not path.is_file():
        return None
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip():
            return float(r.stdout.strip())
    except Exception:
        return None
    return None


def _goal_windows(edl: Sequence[Mapping[str, Any]]) -> Dict[str, List[float]]:
    out: Dict[str, List[float]] = {}
    for sid in protected_goal_segment_ids(edl):
        for row in edl:
            if str(row.get("segment_id")) != sid:
                continue
            if row.get("include_in_cut", True) is False:
                continue
            mi, mo = row.get("media_in"), row.get("media_out")
            if mi is not None and mo is not None:
                out[sid] = [float(mi), float(mo)]
    return out


def probe_video_pair(
    *,
    baseline_mp4: Path,
    candidate_mp4: Optional[Path],
) -> Dict[str, Any]:
    base_dur = _ffprobe_duration(baseline_mp4)
    cand_dur = _ffprobe_duration(candidate_mp4) if candidate_mp4 else None
    return {
        "baseline_exists": baseline_mp4.is_file(),
        "candidate_exists": bool(candidate_mp4 and candidate_mp4.is_file()),
        "baseline_duration_sec": base_dur,
        "candidate_duration_sec": cand_dur,
        "duration_delta_sec": (
            None
            if base_dur is None or cand_dur is None
            else round(cand_dur - base_dur, 3)
        ),
        "method": "ffprobe_duration_and_existence",
        "note": "Technical probe only; not semantic story quality.",
    }


def verify_story_revision(
    *,
    story: Mapping[str, Any],
    plan: Mapping[str, Any],
    baseline_edl: Sequence[Dict[str, Any]],
    candidate_edl: Sequence[Dict[str, Any]],
    baseline_mp4: Path,
    candidate_mp4: Optional[Path],
    decision: str,
    api_verifier_fn: Optional[Any] = None,
    fixture: Optional[Mapping[str, Any]] = None,
    sent_frame_ids: Optional[Sequence[str]] = None,
    vision_backed: Optional[bool] = None,
    verdict_provenance: Optional[str] = None,
    hard_safety_extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Gate revision accept/reject with hard protections + optional dual verifier.

    Text-only / EDL-only / unknown-frame citations never yield candidate_accepted.
    verdict_provenance is set by the caller execution path (FIXTURE|REAL_VLM|OFFLINE_RULE),
    never from model/fixture content fields.
    """
    from .dual_video_vision_verifier import validate_visual_verifier_payload

    hard_vetoes: List[Dict[str, Any]] = []
    warnings: List[str] = []

    # Replay / render-row validation on candidate
    try:
        validate_render_rows(list(candidate_edl))
        render_rows_ok = True
    except ValueError as exc:
        render_rows_ok = False
        hard_vetoes.append({"kind": "render_row_validation", "detail": str(exc)})

    base_goals = _goal_windows(baseline_edl)
    cand_goals = _goal_windows(candidate_edl)
    for sid, win in base_goals.items():
        if sid not in cand_goals:
            hard_vetoes.append(
                {
                    "kind": "goal_anchor_removed",
                    "segment_id": sid,
                    "baseline_window": win,
                }
            )
        else:
            cwin = cand_goals[sid]
            # Allow tiny float noise only
            if abs(cwin[0] - win[0]) > 0.05 or abs(cwin[1] - win[1]) > 0.05:
                hard_vetoes.append(
                    {
                        "kind": "goal_anchor_window_changed",
                        "segment_id": sid,
                        "baseline_window": win,
                        "candidate_window": cwin,
                    }
                )

    video_probe = probe_video_pair(baseline_mp4=baseline_mp4, candidate_mp4=candidate_mp4)
    if not video_probe["baseline_exists"]:
        hard_vetoes.append({"kind": "missing_baseline_mp4"})
    if decision == "REVISE" and not video_probe["candidate_exists"]:
        hard_vetoes.append({"kind": "missing_candidate_mp4_for_revise"})

    edl_delta = edl_diff(list(baseline_edl), list(candidate_edl))
    if decision == "REVISE" and edl_delta.get("exactly_equal"):
        warnings.append("revise_decision_but_edl_unchanged")
        hard_vetoes.append({"kind": "revise_without_edl_change"})

    # Normalize fixture through visual citation gate when frame ids are known.
    fixture_validated = None
    vision_ok = False
    if fixture is not None:
        gate = validate_visual_verifier_payload(
            dict(fixture),
            sent_frame_ids=list(sent_frame_ids or []),
        )
        fixture_validated = gate["validated"]
        vision_ok = bool(gate.get("ok_for_semantic_accept"))
        if str(fixture.get("quality_delta_vs_baseline") or "").lower() in ("improved", "better"):
            if not gate.get("cited_sent_frame_ids"):
                vision_ok = False
                warnings.extend(list(gate.get("reasons") or []))
                warnings.append("fixture_improved_without_valid_sent_frame_citations")
    if vision_backed is False:
        vision_ok = False
        warnings.append("vision_backed_explicitly_false")

    def _api_stub(payload, fixture=None):  # noqa: ANN001
        fx = fixture_validated if fixture_validated is not None else fixture
        if fx is not None:
            # PASSED only with vision citations; otherwise degrade (NOT_EVALUATED).
            status = "PASSED" if (
                vision_ok
                and bool(sent_frame_ids)
                and str(fx.get("quality_delta_vs_baseline") or "").lower() in ("improved", "better")
                and not fx.get("hard_vetoes")
            ) else "NOT_EVALUATED"
            if status == "PASSED":
                return {
                    "ok": True,
                    "provider_mode": "offline_fixture",
                    "validated": dict(fx),
                    "ok_for_semantic_accept": True,
                    "semantic_verification_status": "PASSED",
                }
            return {
                "ok": False,
                "error": "vision_citations_insufficient_or_text_only",
                "provider_mode": "degraded",
                "validated": dict(fx),
                "ok_for_semantic_accept": False,
                "semantic_verification_status": "NOT_EVALUATED",
            }
        if callable(api_verifier_fn):
            return api_verifier_fn(payload, fixture=fixture)
        return {
            "ok": False,
            "error": "api_verifier_not_authorized",
            "provider_mode": "skipped",
            "ok_for_semantic_accept": False,
            "semantic_verification_status": "NOT_EVALUATED",
        }

    dual = run_dual_verifier(
        story=story,
        plan=plan,
        baseline_edl=baseline_edl,
        candidate_edl=candidate_edl,
        api_verifier_fn=_api_stub,
        api_payload={
            "baseline_mp4": str(baseline_mp4),
            "candidate_mp4": str(candidate_mp4) if candidate_mp4 else None,
            "decision": decision,
            "video_probe": video_probe,
            "sent_frame_ids": list(sent_frame_ids or []),
            "note": "ACCEPT requires vision-backed dual frames; EDL/text alone insufficient.",
        },
        fixture=fixture_validated if fixture_validated is not None else fixture,
    )

    # Prefer explicit vision gate status when provided via stub/fixture.
    semantic_status = str(
        dual.get("semantic_verification_status")
        or (dual.get("api") or {}).get("semantic_verification_status")
        or "NOT_EVALUATED"
    )
    if fixture is not None and not (sent_frame_ids and vision_ok):
        # Text-only fixture claiming improved must not pass.
        if str((fixture_validated or fixture or {}).get("quality_delta_vs_baseline") or "").lower() in (
            "improved", "better",
        ) and not (sent_frame_ids and (fixture_validated or {}).get("evidence_of_improvement")):
            semantic_status = "NOT_EVALUATED"
            warnings.append("text_only_or_uncited_improved_forced_not_evaluated")

    rule_status = str(dual.get("rule_verification_status") or "UNKNOWN")

    improved = False
    val = fixture_validated or (dual.get("validated") or {})
    if str(val.get("quality_delta_vs_baseline") or "").lower() in ("improved", "better"):
        if sent_frame_ids:
            gate2 = validate_visual_verifier_payload(val, sent_frame_ids=list(sent_frame_ids))
            improved = bool(gate2.get("ok_for_semantic_accept") or gate2.get("cited_sent_frame_ids"))
            if not gate2.get("cited_sent_frame_ids"):
                improved = False
                semantic_status = "NOT_EVALUATED"
                warnings.append("improved_rejected_without_sent_frame_citations")
        else:
            improved = False
            semantic_status = "NOT_EVALUATED"
            warnings.append("improved_rejected_without_any_sent_frames")

    accept = False
    if hard_vetoes:
        accept = False
    elif decision == "KEEP":
        accept = False
    elif decision == "UNRESOLVED":
        accept = False
    elif decision == "REVISE":
        accept = (
            semantic_status == "PASSED"
            and bool(dual.get("ok_for_semantic_accept") or improved)
            and render_rows_ok
            and bool(video_probe.get("candidate_exists"))
            and improved
            and not edl_delta.get("exactly_equal")
            and bool(sent_frame_ids)
        )
        if semantic_status == "NOT_EVALUATED":
            warnings.append("refuse_accept_without_semantic_verification")
        if not sent_frame_ids:
            warnings.append("refuse_accept_without_dual_video_frames")

    goal_intact = not any(
        str(v.get("kind") or "").startswith("goal_anchor") for v in hard_vetoes
    )
    hard_safety = compute_independent_hard_safety(
        hard_vetoes=hard_vetoes,
        goal_intact=goal_intact,
        render_rows_ok=render_rows_ok,
        candidate_mp4=candidate_mp4,
        extra=hard_safety_extra,
    )
    # Provenance from caller execution path only — ignore content-claimed source_kind.
    prov = str(verdict_provenance or "").upper()
    if prov not in ("FIXTURE", "REAL_VLM", "OFFLINE_RULE"):
        # Legacy: fixture argument used as test overlay ⇒ FIXTURE; else offline rules.
        prov = "FIXTURE" if fixture is not None else "OFFLINE_RULE"
    phase8_verdict = build_phase8_verdict(
        hard_vetoes=hard_vetoes,
        hard_safety=hard_safety,
        goal_intact=goal_intact,
        render_rows_ok=render_rows_ok,
        semantic_status=semantic_status,
        vision_backed=bool(sent_frame_ids) and (vision_backed is not False),
        sent_frame_ids=list(sent_frame_ids or []),
        validated=val if isinstance(val, dict) else {},
        quality_overlay=fixture if isinstance(fixture, dict) else None,
        accept_candidate=bool(accept),
        verdict_provenance=prov,
        compared_parent_version_id=(
            (fixture or {}).get("compared_parent_version_id")
            if isinstance(fixture, dict)
            else None
        ),
        focus_issue_id=(
            (fixture or {}).get("focus_issue_id") if isinstance(fixture, dict) else None
        ),
    )

    return {
        "schema": "v3a_story_video_verifier_v1",
        "decision_input": decision,
        "hard_vetoes": hard_vetoes,
        "warnings": warnings,
        "render_rows_ok": render_rows_ok,
        "goal_protection": {
            "baseline_goals": base_goals,
            "candidate_goals": cand_goals,
            "intact": not any(
                v.get("kind", "").startswith("goal_anchor") for v in hard_vetoes
            ),
        },
        "video_probe": video_probe,
        "edl_delta": edl_delta,
        "sent_frame_ids": list(sent_frame_ids or []),
        "vision_backed": bool(sent_frame_ids) and (vision_backed is not False),
        "dual_verifier": {
            "rule_verification_status": rule_status,
            "semantic_verification_status": semantic_status,
            "ok_for_semantic_accept": dual.get("ok_for_semantic_accept"),
            "provider_mode": dual.get("provider_mode"),
            "rule_baseline_score": (dual.get("rule_baseline") or {}).get("score"),
            "rule_candidate_score": (dual.get("rule_candidate") or {}).get("score"),
        },
        "dual_verifier_full": dual,
        "candidate_accepted": bool(accept),
        "retain_baseline": not bool(accept),
        "phase8_verdict": phase8_verdict,
        "evidence_basis": (
            "dual_video_vision_frames"
            if sent_frame_ids and semantic_status != "NOT_EVALUATED"
            else "insufficient_visual_evidence"
        ),
        "note": (
            "Semantic accept requires aligned dual-video frames with citable frame_ids. "
            "EDL/text/ffprobe alone never authorizes release. "
            "phase8_verdict is advisory for exploration; accept_candidate does not "
            "synthesize from PROMISING."
        ),
    }


def compute_independent_hard_safety(
    *,
    hard_vetoes: Sequence[Mapping[str, Any]],
    goal_intact: bool,
    render_rows_ok: bool,
    candidate_mp4: Optional[Path] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Machine-verifiable hard safety — independent of narrative accept_candidate.

    PASS only when EDL/render rules, goal protection, PTS (if supplied), and
    first-LIVE proof for newly used footage are all explicitly satisfied.
    Absent first-LIVE proof ⇒ UNKNOWN (not PASS). Confirmed replay/violation ⇒ FAIL.
    """
    extra = dict(extra or {})
    reasons: List[str] = []
    if hard_vetoes:
        kinds = [str(v.get("kind") or "") for v in hard_vetoes]
        if any("replay" in k or "slowmo" in k or "goal_anchor" in k for k in kinds):
            return {
                "safety": "FAIL",
                "reasons": kinds,
                "accept_candidate_ignored": True,
                "first_live_status": extra.get("first_live_status") or "UNKNOWN",
            }
        reasons.extend(kinds)
    if not goal_intact:
        return {
            "safety": "FAIL",
            "reasons": ["goal_protection_broken"],
            "accept_candidate_ignored": True,
            "first_live_status": extra.get("first_live_status") or "UNKNOWN",
        }
    if not render_rows_ok:
        return {
            "safety": "FAIL",
            "reasons": ["render_row_validation_failed"],
            "accept_candidate_ignored": True,
            "first_live_status": extra.get("first_live_status") or "UNKNOWN",
        }
    if extra.get("pts_ok") is False:
        return {
            "safety": "FAIL",
            "reasons": ["source_pts_not_monotonic"],
            "accept_candidate_ignored": True,
            "first_live_status": extra.get("first_live_status") or "UNKNOWN",
        }
    if extra.get("intentional_replay"):
        return {
            "safety": "FAIL",
            "reasons": ["intentional_replay_or_slowmo"],
            "accept_candidate_ignored": True,
            "first_live_status": "FAIL",
        }
    first_live = str(extra.get("first_live_status") or "UNKNOWN").upper()
    # Explicit PASS path requires authoritative first-LIVE for new footage (or no new media).
    new_footage = bool(extra.get("has_new_footage", True))
    if new_footage and first_live not in ("PASS", "FIRST_LIVE_VERIFIED", "VERIFIED"):
        return {
            "safety": "UNKNOWN",
            "reasons": reasons + ["first_live_proof_missing_or_unverified"],
            "accept_candidate_ignored": True,
            "first_live_status": first_live,
            "note": "Absent replay flags are NOT first-LIVE proof.",
        }
    if candidate_mp4 is not None and not Path(candidate_mp4).is_file():
        return {
            "safety": "UNKNOWN",
            "reasons": reasons + ["candidate_mp4_missing"],
            "accept_candidate_ignored": True,
            "first_live_status": first_live,
        }
    # Test/fixture may assert hard safety PASS via execution-path overlay only.
    if extra.get("force_hard_safety") in ("PASS", "FAIL", "UNKNOWN"):
        return {
            "safety": str(extra["force_hard_safety"]),
            "reasons": reasons + ["force_hard_safety_overlay"],
            "accept_candidate_ignored": True,
            "first_live_status": first_live,
        }
    return {
        "safety": "PASS",
        "reasons": reasons,
        "accept_candidate_ignored": True,
        "first_live_status": first_live if new_footage else "N_A_NO_NEW_FOOTAGE",
    }


def build_phase8_verdict(
    *,
    hard_vetoes: Sequence[Mapping[str, Any]],
    goal_intact: bool,
    render_rows_ok: bool,
    semantic_status: str,
    vision_backed: bool,
    sent_frame_ids: Sequence[str],
    validated: Mapping[str, Any],
    quality_overlay: Optional[Mapping[str, Any]] = None,
    fixture: Optional[Mapping[str, Any]] = None,  # legacy alias
    accept_candidate: bool = False,
    verdict_provenance: str = "OFFLINE_RULE",
    hard_safety: Optional[Mapping[str, Any]] = None,
    compared_parent_version_id: Optional[str] = None,
    focus_issue_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Independent soft quality + hard safety verdict (Phase 8).

    Hard safety never depends on accept_candidate. Provenance is caller-set.
    PROMISING must not become accept_candidate / formal IMPROVED.
    """
    from .story_revision_feedback import normalize_quality

    fx = dict(quality_overlay or fixture or {})
    prov = str(verdict_provenance or "OFFLINE_RULE").upper()
    if prov not in ("FIXTURE", "REAL_VLM", "OFFLINE_RULE"):
        prov = "OFFLINE_RULE"
    # Fixtures always stay FIXTURE even if payload claims REAL.
    if fixture is not None and prov != "REAL_VLM":
        # quality_overlay from fixture path keeps FIXTURE
        if prov != "FIXTURE" and quality_overlay is not None and fixture is quality_overlay:
            prov = "FIXTURE"

    hs = dict(
        hard_safety
        or compute_independent_hard_safety(
            hard_vetoes=hard_vetoes,
            goal_intact=goal_intact,
            render_rows_ok=render_rows_ok,
            extra={
                "force_hard_safety": fx.get("phase8_safety") if prov == "FIXTURE" else None,
                "first_live_status": fx.get("first_live_status"),
                "has_new_footage": fx.get("has_new_footage", True),
                "pts_ok": fx.get("pts_ok"),
                "intentional_replay": fx.get("intentional_replay"),
            },
        )
    )
    safety = str(hs.get("safety") or "UNKNOWN").upper()
    if safety not in ("PASS", "FAIL", "UNKNOWN"):
        safety = "UNKNOWN"

    q_raw = (
        fx.get("phase8_quality")
        or fx.get("quality_judgment")
        or validated.get("quality_delta_vs_baseline")
    )
    quality = normalize_quality(q_raw)
    if quality == "BETTER" and not (vision_backed and sent_frame_ids) and prov != "FIXTURE":
        quality = "UNCERTAIN"

    if semantic_status == "PASSED" and vision_backed and sent_frame_ids:
        evidence = "SUFFICIENT"
    elif sent_frame_ids and semantic_status in ("FAILED", "PASSED", "NOT_EVALUATED"):
        evidence = "PARTIAL" if vision_backed else "INSUFFICIENT"
    else:
        evidence = "INSUFFICIENT"

    if fx.get("phase8_evidence"):
        evidence = str(fx["phase8_evidence"]).upper()
        if evidence not in ("SUFFICIENT", "PARTIAL", "INSUFFICIENT"):
            evidence = "INSUFFICIENT"

    issue_effect = str(
        fx.get("issue_effect")
        or validated.get("original_issue_resolved")
        or "UNOBSERVED"
    ).upper()
    if issue_effect in ("TRUE", "YES"):
        issue_effect = "RESOLVED"
    elif issue_effect in ("FALSE", "NO"):
        issue_effect = "UNRESOLVED"
    elif issue_effect not in ("RESOLVED", "PARTIAL", "UNRESOLVED", "UNOBSERVED"):
        if validated.get("original_issue_resolved") is True:
            issue_effect = "RESOLVED"
        elif validated.get("original_issue_resolved") is False:
            issue_effect = "UNRESOLVED"
        else:
            issue_effect = "UNOBSERVED"

    global_regression = str(fx.get("global_regression") or "UNKNOWN").upper()
    if validated.get("introduced_new_defect") is True:
        global_regression = "YES"
    elif validated.get("introduced_new_defect") is False and global_regression == "UNKNOWN":
        global_regression = "NO"

    failure_class = "UNCERTAIN_OR_UNVERIFIED"
    if safety == "FAIL":
        failure_class = "HARD_SAFETY_VETO"
    elif quality in ("BETTER", "PROMISING") and evidence in ("SUFFICIENT", "PARTIAL"):
        failure_class = "POSITIVE"
    elif quality == "WORSE" and evidence == "SUFFICIENT":
        failure_class = "CONFIRMED_NEGATIVE"
    elif evidence == "INSUFFICIENT" or semantic_status == "NOT_EVALUATED":
        failure_class = "TECHNICAL_FAILURE" if not vision_backed else "UNCERTAIN_OR_UNVERIFIED"

    # Specific next-evidence target only — no generic nonempty fallback (P1-6).
    suggested = fx.get("suggested_next_evidence")
    if isinstance(suggested, str) and suggested.strip():
        suggested_out: Any = suggested.strip()
    elif isinstance(suggested, dict) and suggested.get("question"):
        suggested_out = suggested
    else:
        suggested_out = None

    return {
        "schema": "v3a_phase8_verdict_v1",
        "safety": safety,
        "hard_safety": hs,
        "quality": quality,
        "evidence": evidence,
        "issue_effect": issue_effect,
        "global_regression": global_regression,
        "focus_issue_id": focus_issue_id or fx.get("focus_issue_id"),
        "evidence_refs": list(validated.get("evidence_of_improvement") or [])[:12]
        or list(sent_frame_ids)[:12],
        "observed_changes": fx.get("observed_changes")
        or validated.get("observed_visuals"),
        "unresolved_questions": list(fx.get("unresolved_questions") or []),
        "suggested_next_evidence": suggested_out,
        "failure_class": failure_class,
        "compared_parent_version_id": compared_parent_version_id
        or fx.get("compared_parent_version_id"),
        "verdict_provenance": prov,
        "source_kind": prov,  # back-compat alias; always equals provenance
        "accept_candidate_raw": bool(accept_candidate),
        "accept_not_synthesized_from_promising": True,
        "safety_independent_of_accept_candidate": True,
        "note": (
            "Hard safety is independent of narrative accept_candidate. "
            "FIXTURE/OFFLINE_RULE never establish real IMPROVED; REAL_VLM requires "
            "recorded successful provider call + frame bindings."
        ),
    }


def empty_status_gates() -> Dict[str, bool]:
    return {
        "workflow_completed": False,
        "story_diagnosis_valid": False,
        "revision_applied": False,
        "candidate_rendered": False,
        "semantic_verification_passed": False,
        "release_authorized": False,
        "final_mp4_exists": False,
    }


def compute_release_authorization(
    *,
    gates: Mapping[str, Any],
    decision: str,
    edl_changed: bool,
    candidate_accepted: bool,
    goal_anchors_intact: bool,
    hard_vetoes: Sequence[Mapping[str, Any]],
    final_mp4: Path,
    final_edl: Sequence[Mapping[str, Any]],
    diagnosis_issues: Optional[Sequence[Mapping[str, Any]]] = None,
    timeline_aligned: Optional[bool] = None,
    unresolved_critical: bool = False,
) -> Dict[str, Any]:
    """Formal release requires the full conjunction — no single flag suffices."""
    reasons: List[str] = []
    mp4_ok = final_mp4.is_file()
    dur = _ffprobe_duration(final_mp4) if mp4_ok else None
    if not mp4_ok:
        reasons.append("final_mp4_missing")
    elif dur is None or dur <= 0.5:
        reasons.append("final_mp4_undecodable_or_too_short")
        mp4_ok = False

    try:
        validate_render_rows(list(final_edl))
        edl_hard_ok = True
    except ValueError as exc:
        edl_hard_ok = False
        reasons.append(f"final_edl_hard_rule:{exc}")

    # Critical unresolved narrative defects block release.
    blocking_issues = []
    for iss in diagnosis_issues or []:
        if not isinstance(iss, dict):
            continue
        if iss.get("severity") in ("critical", "major") and iss.get("evidence_sufficiency") in (
            "observed", "structure_inferred",
        ):
            if iss.get("category") in (
                "replay_risk", "timeline_integrity", "input_integrity", "narrative_order",
                "narrative_causality", "redundancy",
            ):
                blocking_issues.append(iss.get("issue_id"))
    if blocking_issues or unresolved_critical:
        reasons.append("unresolved_critical_story_defects:" + ",".join(str(x) for x in blocking_issues[:8]))

    if not edl_changed:
        reasons.append("edl_unchanged")
    if not gates.get("candidate_rendered"):
        reasons.append("candidate_not_rendered")
    if not candidate_accepted:
        reasons.append("candidate_not_accepted")
    if not gates.get("semantic_verification_passed"):
        reasons.append("semantic_verification_not_passed")
    if not goal_anchors_intact:
        reasons.append("goal_anchors_not_intact")
    if hard_vetoes:
        reasons.append("hard_vetoes_present")
    if str(decision).upper() != "REVISE":
        reasons.append("decision_not_revise")
    if timeline_aligned is False:
        reasons.append("final_mp4_edl_timeline_misaligned")

    authorized = bool(
        edl_changed
        and gates.get("candidate_rendered")
        and candidate_accepted
        and gates.get("semantic_verification_passed")
        and edl_hard_ok
        and goal_anchors_intact
        and not hard_vetoes
        and mp4_ok
        and str(decision).upper() == "REVISE"
        and not blocking_issues
        and not unresolved_critical
        and timeline_aligned is not False
    )
    return {
        "release_authorized": authorized,
        "reasons": reasons,
        "final_mp4_duration_sec": dur,
        "edl_hard_ok": edl_hard_ok,
        "blocking_issue_ids": blocking_issues,
        "note": (
            "workflow_completed/final_mp4_exists/semantic_verification_passed alone "
            "never authorize formal release."
        ),
    }


def timeline_mp4_aligned(
    *,
    edl: Sequence[Mapping[str, Any]],
    mp4: Path,
    tolerance_sec: float = 2.0,
) -> Dict[str, Any]:
    """Compare MP4 duration to story timeline including placeholder cards."""
    from .story_timeline import build_story_timeline

    tl = build_story_timeline(edl)
    story_dur = float(tl.get("story_duration_sec") or 0.0)
    mp4_dur = _ffprobe_duration(mp4)
    if mp4_dur is None:
        return {"aligned": False, "reason": "mp4_undecodable", "timeline": tl}
    delta = abs(mp4_dur - story_dur)
    return {
        "aligned": delta <= float(tolerance_sec),
        "mp4_duration_sec": mp4_dur,
        "story_duration_sec": story_dur,
        "media_duration_sec": tl.get("media_duration_sec"),
        "placeholder_duration_sec": tl.get("placeholder_duration_sec"),
        "delta_sec": round(delta, 3),
        "tolerance_sec": tolerance_sec,
        "timeline": tl,
        "root_cause_hint": (
            "placeholder_title_cards_included_in_story_duration"
            if float(tl.get("placeholder_duration_sec") or 0) > 0
            else "media_only"
        ),
    }
