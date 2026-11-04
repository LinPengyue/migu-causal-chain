"""Hybrid Rule+API fallback helpers for V3-A self-revision Agent.

See docs/V3_A_HYBRID_API_FALLBACK_CONTRACT.md. Rule track always runs; API track
degrades without pretending semantic success.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from story_video_agent.frames import FrameBudget, FrameStore
from story_video_agent.media import probe_video

from .planner_stage2 import ROLE_KEYS, compile_safe_candidates, _intervals
from .quality_audit import evaluate as quality_evaluate

SEMANTIC_DIMS = (
    "story_element_coverage",
    "narrative_coherence",
    "image_content_quality",
    "live_authenticity",
)


def _num(x: Any) -> Optional[float]:
    try:
        if x is None or isinstance(x, bool):
            return None
        v = float(x)
        return v if v == v else None  # NaN check
    except (TypeError, ValueError):
        return None


def run_rule_verifier(
    story: Mapping[str, Any],
    plan: Mapping[str, Any],
    edl: Sequence[Dict[str, Any]],
    *,
    rendered_video: Optional[Path] = None,
) -> Dict[str, Any]:
    """Always-on structural / technical verifier (Stage-1 evaluate)."""
    rows = [r for r in edl if isinstance(r, dict)]
    audit = quality_evaluate(dict(story), dict(plan), rows, rendered_video=rendered_video)
    p0 = [f for f in (audit.get("hard_gate_findings") or []) if f.get("severity") == "P0"]
    if p0:
        status = "FAILED"
    elif audit.get("diagnostic_issues"):
        status = "RAN_WITH_FINDINGS"
    else:
        status = "PASSED"
    return {
        "track": "rule",
        "ok": True,
        "rule_verification_status": status,
        "audit": audit,
        "p0_count": len(p0),
        "semantic_scores": {d: "NOT_EVALUATED" for d in SEMANTIC_DIMS},
        "note": "Rule track does not certify multimodal semantic quality.",
    }


def not_evaluated_semantic_block() -> Dict[str, Any]:
    return {
        d: {
            "status": "NOT_EVALUATED",
            "summary": "API Verifier unavailable or failed; score not assigned",
            "evidence_refs": [],
            "problems": [],
            "score": None,
        }
        for d in SEMANTIC_DIMS
    }


def run_dual_verifier(
    *,
    story: Mapping[str, Any],
    plan: Mapping[str, Any],
    baseline_edl: Sequence[Dict[str, Any]],
    candidate_edl: Sequence[Dict[str, Any]],
    api_verifier_fn: Callable[..., Dict[str, Any]],
    api_payload: Mapping[str, Any],
    fixture: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Rule always; API optional with honest degrade to NOT_EVALUATED semantics."""
    rule_base = run_rule_verifier(story, plan, baseline_edl)
    rule_cand = run_rule_verifier(story, plan, candidate_edl)
    api_result = api_verifier_fn(api_payload, fixture=fixture)

    if api_result.get("ok") and api_result.get("provider_mode") in ("real", "offline_fixture"):
        semantic_status = (
            "FAILED" if (api_result.get("validated") or {}).get("hard_vetoes") else "PASSED"
        )
        validated = dict(api_result.get("validated") or {})
        dims = dict(validated.get("dimensions") or {})
        for name in SEMANTIC_DIMS:
            d = dims.get(name) if isinstance(dims.get(name), dict) else {}
            d = dict(d)
            if d.get("status") in (None, "", "unknown") and not d.get("evidence_refs"):
                d["status"] = "NOT_EVALUATED"
                d["score"] = None
            # Never invent 0/100 when status is NOT_EVALUATED
            if d.get("status") == "NOT_EVALUATED":
                d["score"] = None
            dims[name] = d
        validated["dimensions"] = dims
        api_out = dict(api_result)
        api_out["validated"] = validated
        return {
            "rule_baseline": rule_base,
            "rule_candidate": rule_cand,
            "api": api_out,
            "rule_verification_status": rule_cand.get("rule_verification_status"),
            "semantic_verification_status": semantic_status,
            "ok_for_semantic_accept": True,
            "ok": True,
            "validated": validated,
            "provider_mode": api_out.get("provider_mode"),
            "error": None,
            "attempts": api_out.get("attempts") or [],
            "rule_fallback_success": False,
            "semantic_pretend_pass": False,
        }

    # Degrade: rule continues; semantic NOT_EVALUATED (not 0/100)
    return {
        "rule_baseline": rule_base,
        "rule_candidate": rule_cand,
        "api": {
            **dict(api_result or {}),
            "ok": False,
            "rule_fallback_success": False,
            "semantic_pretend_pass": False,
            "validated": {
                "issues": [],
                "dimensions": not_evaluated_semantic_block(),
                "hard_vetoes": [],
                "evidence_of_improvement": [],
                "quality_delta_vs_baseline": "NOT_EVALUATED",
                "validated": True,
                "semantic_status": "NOT_EVALUATED",
            },
            "fallback_reason": (api_result or {}).get("error") or "api_verifier_unavailable",
        },
        "rule_verification_status": rule_cand.get("rule_verification_status"),
        "semantic_verification_status": "NOT_EVALUATED",
        "ok_for_semantic_accept": False,
        "ok": False,
        "validated": {
            "issues": [],
            "dimensions": not_evaluated_semantic_block(),
            "hard_vetoes": [],
            "evidence_of_improvement": [],
            "quality_delta_vs_baseline": "NOT_EVALUATED",
            "validated": True,
        },
        "provider_mode": (api_result or {}).get("provider_mode") or "degraded",
        "error": (api_result or {}).get("error") or "api_verifier_unavailable",
        "attempts": (api_result or {}).get("attempts") or [],
        "rule_fallback_success": False,
        "semantic_pretend_pass": False,
        "fallback_reason": (api_result or {}).get("error") or "api_verifier_unavailable",
    }


def build_rule_planner_fallback(
    story: Mapping[str, Any],
    plan: Mapping[str, Any],
    edl: Sequence[Dict[str, Any]],
    audit: Mapping[str, Any],
    *,
    video_duration: Optional[float] = None,
    fallback_reason: str = "planner_api_failed",
) -> Dict[str, Any]:
    """Rule-only planner from Stage-1/2 gaps; no invented semantic revisions."""
    try:
        candidates = compile_safe_candidates(dict(story), dict(plan), list(edl), dict(audit))
    except (ValueError, TypeError) as exc:
        return {
            "ok": True,
            "provider_mode": "rule_fallback",
            "fallback": True,
            "fallback_reason": f"{fallback_reason}|compile_failed:{exc}",
            "validated": {
                "diagnoses": [],
                "revision_intents": [],
                "video_tool_requests": [],
                "notes": "rule_fallback_empty",
                "validated": True,
            },
        }
    diagnoses: List[Dict[str, Any]] = []
    intents: List[Dict[str, Any]] = []
    tools: List[Dict[str, Any]] = []
    for i, c in enumerate(candidates[:4]):
        issue_id = str(c.get("task_id") or f"rule_{i:03d}")
        diagnoses.append({
            "issue_id": issue_id,
            "problem": f"rule:{c.get('issue_kind')}:{c.get('issue_target')}",
            "severity": c.get("severity") or "P0",
            "story_element": c.get("issue_target"),
            "target_segment_id": c.get("target_segment_id"),
            "evidence_refs": [{"kind": "stage1_or_stage2", "ref": c.get("issue_kind")}],
            "expected_improvement": c.get("expected_improvement") or "resolve_rule_diagnostic",
        })
        role = c.get("required_role")
        if not role and c.get("issue_target") in ROLE_KEYS:
            role = f"{c.get('issue_target')}_goal_action"
        anchor_id = None
        if c.get("issue_kind") == "missing_story_element" and c.get("issue_target") in ROLE_KEYS:
            anchor_id = f"score_node:{ROLE_KEYS[str(c['issue_target'])]}"
        elif c.get("target_segment_id"):
            anchor_id = f"edl:{c['target_segment_id']}"
        if role and anchor_id:
            intents.append({
                "intent_id": f"intent_{issue_id}",
                "action": (
                    "search_add"
                    if c.get("issue_kind") == "missing_story_element"
                    else "mark_unresolved"
                ),
                "issue_id": issue_id,
                "role": role,
                "anchor_id": anchor_id,
                "rationale": "rule_determined_gap",
                "expected_improvement": "acquire_evidence_only",
                "risk": "no_semantic_invention",
                "evidence_refs": [{"kind": "rule_fallback"}],
            })
        wins = list(c.get("search_windows") or [])
        if not wins and c.get("score_anchor_sec") is not None:
            wins = _intervals(float(c["score_anchor_sec"]))
        if video_duration is not None:
            wins = [
                w for w in wins
                if _num(w.get("end")) is not None and float(w["end"]) <= float(video_duration) + 1e-6
            ]
        if anchor_id and wins:
            tools.append({
                "request_id": f"tool_{issue_id}",
                "tool": "extract_frames",
                "issue_id": issue_id,
                "anchor_id": anchor_id,
                "question": "Rule fallback: extract frames for PTS/technical check; semantic UNKNOWN without VLM",
                "search_windows": wins[:3],
                "windows_source": "stage2_rule_candidate",
            })
    return {
        "ok": True,
        "provider_mode": "rule_fallback",
        "fallback": True,
        "fallback_reason": fallback_reason,
        "model": None,
        "validated": {
            "diagnoses": diagnoses,
            "revision_intents": intents,
            "video_tool_requests": tools,
            "notes": "rule_fallback_no_semantic_invention",
            "validated": True,
        },
        "est_cost_usd": 0.0,
    }


def run_ffmpeg_observe_without_vlm(
    *,
    video: Path,
    work_dir: Path,
    tool_requests: Sequence[Mapping[str, Any]],
    frame_budget: int = 12,
) -> Dict[str, Any]:
    """VLM-API failure path: FFmpeg/PTS continue; semantic UNKNOWN."""
    work_dir.mkdir(parents=True, exist_ok=True)
    media = probe_video(video)
    store = FrameStore(
        media, out_dir=work_dir / "frames", budget=FrameBudget(max_frames=frame_budget),
    )
    observations: List[Dict[str, Any]] = []
    for tr in tool_requests:
        windows = list(tr.get("search_windows") or [])[:2]
        for i, win in enumerate(windows):
            start, end = float(win["start"]), float(win["end"])
            times = store.sample_times(start, end, count=4)
            frames = []
            for t in times:
                rec = store.extract_at(
                    t, gap_id=str(tr.get("request_id") or "tech"), tool="ffmpeg_fallback",
                )
                frames.append(rec.to_dict())
            observations.append({
                "request_id": f"{tr.get('request_id') or 'tool'}_ff{i}",
                "issue_id": tr.get("issue_id"),
                "anchor_id": tr.get("anchor_id"),
                "ok": True,
                "provider_mode": "ffmpeg_only",
                "vlm": None,
                "semantic_status": "UNKNOWN",
                "frames": frames,
                "window": {"start": start, "end": end},
                "allowed_windows": windows,
                "fact_verified": False,
                "observation_only": True,
                "supports_bound_segment": False,
                "note": "VLM unavailable; frames/PTS only; event remains UNKNOWN",
            })
    return {
        "observations": observations,
        "frame_manifest": store.manifest,
        "any_real_ok": False,
        "vlm_fallback": True,
        "semantic_status": "UNKNOWN",
        "window_schedule_log": [{"reason": "vlm_api_failed_ffmpeg_only"}],
    }


def build_orchestration_status(
    *,
    workflow_completed: bool,
    rule_verification_status: str,
    semantic_verification_status: str,
    fallback_reasons: Sequence[str],
    accepted_revision: bool,
    agent_contributed_improvement: bool,
    best_preserved: bool = True,
) -> Dict[str, Any]:
    return {
        "workflow_completed": bool(workflow_completed),
        "rule_verification_status": rule_verification_status,
        "semantic_verification_status": semantic_verification_status,
        "fallback_reason": list(fallback_reasons) or None,
        "accepted_revision": bool(accepted_revision),
        "agent_contributed_improvement": bool(agent_contributed_improvement),
        "best_accepted_edl_preserved": bool(best_preserved),
        "render_ready": False,
        "release_decision": "NOT_AUTHORIZED",
        "degraded_execution_success": bool(
            workflow_completed and not agent_contributed_improvement
        ),
        "multimodal_self_revision_success": bool(agent_contributed_improvement),
    }
