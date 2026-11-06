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
) -> Dict[str, Any]:
    """Gate revision accept/reject with hard protections + optional dual verifier."""
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
    # Dual verifier (rule always; API optional)
    def _api_stub(payload, fixture=None):  # noqa: ANN001
        if fixture is not None:
            return {
                "ok": True,
                "provider_mode": "offline_fixture",
                "validated": dict(fixture),
            }
        if callable(api_verifier_fn):
            return api_verifier_fn(payload, fixture=fixture)
        return {"ok": False, "error": "api_verifier_not_authorized", "provider_mode": "skipped"}

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
            "note": "Verifier should use actual videos when API authorized; EDL-only is insufficient for semantic accept.",
        },
        fixture=fixture,
    )

    semantic_status = str(dual.get("semantic_verification_status") or "NOT_EVALUATED")
    rule_status = str(dual.get("rule_verification_status") or "UNKNOWN")

    improved = False
    if fixture and fixture.get("quality_delta_vs_baseline") == "improved":
        improved = True
    elif decision == "REVISE" and edl_delta.get("exactly_equal"):
        warnings.append("revise_decision_but_edl_unchanged")
    elif decision == "REVISE" and not edl_delta.get("exactly_equal"):
        # Structural change present; without semantic pass cannot claim improvement
        warnings.append("edl_changed_but_semantic_not_confirmed")

    accept = False
    if hard_vetoes:
        accept = False
    elif decision == "KEEP":
        accept = False  # no revision to accept; baseline retained
    elif decision == "UNRESOLVED":
        accept = False
    elif decision == "REVISE":
        # Only accept when semantic passed AND no hard vetoes AND candidate exists
        accept = (
            semantic_status == "PASSED"
            and bool(dual.get("ok_for_semantic_accept"))
            and render_rows_ok
            and video_probe.get("candidate_exists")
            and improved
        )
        if semantic_status == "NOT_EVALUATED":
            warnings.append("refuse_accept_without_semantic_verification")

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
        "dual_verifier": {
            "rule_verification_status": rule_status,
            "semantic_verification_status": semantic_status,
            "ok_for_semantic_accept": dual.get("ok_for_semantic_accept"),
            "provider_mode": dual.get("provider_mode"),
            "rule_baseline_score": (dual.get("rule_baseline") or {}).get("score"),
            "rule_candidate_score": (dual.get("rule_candidate") or {}).get("score"),
            # Do not dump full dual blob twice; keep summary. Full in audit file if needed.
        },
        "dual_verifier_full": dual,
        "candidate_accepted": bool(accept),
        "retain_baseline": not bool(accept),
        "evidence_basis": (
            "video_probe+rule+optional_api"
            if semantic_status != "NOT_EVALUATED"
            else "video_probe+rule_only_semantic_not_evaluated"
        ),
        "note": (
            "Semantic accept requires authorized dual-video verification. "
            "EDL field comparison alone never authorizes release."
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
