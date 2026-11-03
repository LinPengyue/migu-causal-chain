"""V3-A Stage-2 constrained Planner: evidence requests, NEVER automatic EDL edits.

Reads frozen V3-R Phase5 artifacts plus Stage-1 audit. Default mode is fully
offline and free; real LLM planner requires explicit opt-in and cost approval.
The LLM may choose/order prevalidated repair tasks but cannot create timestamps,
events, patches or claims of verification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

SCHEMA = "v3a_stage2_planner_proposals_v1"
ROLE_KEYS = {
    "opponent_opening": "behind_start",
    "equalizer": "equalizer",
    "go_ahead": "go_ahead",
}
P0_TYPES = {
    "missing_story_element",
    "goal_window_incomplete",
    "replay_as_primary",
    "known_integrity_failure",
    "technical_decode_error",
    "bad_media_window",
    "duplicated_goal_event",
}
P1_TYPES = {"beat_order_inversion"}
MAX_TASKS = 4
MAX_WINDOWS_PER_TASK = 8
MAX_WINDOW_SPAN_SEC = 30.0
LOOKBACK_SEC = 180.0
AFTER_SCORE_SEC = 15.0

SYSTEM_PROMPT = (
    "You are a constrained repair-priority planner for football story video. "
    'Return ONLY a JSON object {"selected_task_ids":["existing_id",...]}. '
    "Select/reorder only IDs from candidate_tasks in the user JSON. "
    "Prefer P0 missing first-live goal footage. You cannot invent match facts, "
    "timestamps, events, candidate IDs, evidence, or edit the EDL. "
    "Selecting a task requests evidence acquisition; it does NOT verify it. "
    "Do not select P2 title-card freeze warnings as source damage."
)


def _num(x: Any) -> Optional[float]:
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v >= 0 else None


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _intervals(anchor: float) -> List[Dict[str, float]]:
    """Time intervals are computed from a score-path anchor, not an LLM guess."""
    start = max(0.0, anchor - LOOKBACK_SEC)
    end = anchor + AFTER_SCORE_SEC
    result: List[Dict[str, float]] = []
    while start < end - 1e-6 and len(result) < MAX_WINDOWS_PER_TASK:
        stop = min(end, start + MAX_WINDOW_SPAN_SEC)
        result.append({"start": round(start, 3), "end": round(stop, 3)})
        start = stop
    if start < end - 1e-6:
        raise ValueError("search bounds exceed planner window cap")
    return result


def _row_by_id(edl: Sequence[Dict[str, Any]], target: str) -> Optional[Dict[str, Any]]:
    exact = [r for r in edl if str(r.get("segment_id") or "") == target]
    return exact[0] if len(exact) == 1 else None


def _task_for_issue(
    issue: Dict[str, Any], ordinal: int, plan: Dict[str, Any],
    edl: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    kind = issue.get("kind")
    severity = issue.get("severity")
    if kind not in P0_TYPES | P1_TYPES or severity not in ("P0", "P1"):
        return None
    target = str(issue.get("target") or "")
    task_id = f"issue_{ordinal:03d}"
    base: Dict[str, Any] = {
        "task_id": task_id,
        "issue_id": task_id,
        "issue_kind": kind,
        "severity": severity,
        "issue_target": target,
        "state": "PROPOSED_ONLY",
        "requires_video_evidence": True,
        "may_edit_edl": False,
        "evidence_status": "UNVERIFIED",
        "evidence_refs": [],
        "search_windows": [],
        "expected_improvement": "resolve_specific_diagnostic_issue",
        "risk": "false_live_or_irrelevant_shot",
        "hard_gates": [
            "no_invented_event_or_media_time", "correct_team_and_score",
            "first_live_goal_must_be_independently_checked",
            "do_not_replace_proven_good_edl_without_comparison",
        ],
    }
    if kind == "missing_story_element":
        if target not in ROLE_KEYS:
            return None
        arc = (plan.get("story_scope") or {}).get("selected_arc") or {}
        node = arc.get(ROLE_KEYS[target])
        if not isinstance(node, dict):
            return None
        anchor = _num(node.get("t_sec"))
        if anchor is None:
            return None
        base.update({
            "repair_intent": "add_missing_role_after_evidence_verification",
            "required_role": f"{target}_goal_action",
            "target_segment_id": None,
            "search_profile": "score_anchored_goal_action_search",
            "anchor_kind": "score_path_confirmation_NOT_goal_action",
            "score_anchor_sec": anchor,
            "search_windows": _intervals(anchor),
            "evidence_refs": [{
                "kind": "T01_selected_arc_score_node",
                "arc_key": ROLE_KEYS[target],
                "score": node.get("score"),
                "t_sec": anchor,
                "verification": "SOURCE_ANCHOR_ONLY",
            }],
            "expected_improvement": f"recover_{target}_live_goal_visual",
        })
        return base

    # Non-missing issues reference a real existing EDL segment; never fabricate
    # a segment or choose an arbitrary time from a string such as "e1,e2".
    row = _row_by_id(edl, target)
    if row is None:
        base.update({
            "repair_intent": "manual_diagnosis_required",
            "target_segment_id": None,
            "evidence_status": "UNRESOLVED_TARGET",
            "risk": "issue_does_not_bind_to_single_existing_segment",
        })
        return base
    start, end = _num(row.get("media_in")), _num(row.get("media_out"))
    base.update({
        "repair_intent": "inspect_existing_segment_before_any_change",
        "target_segment_id": target,
        "evidence_refs": [{
            "kind": "V3R_candidate_edl_segment",
            "segment_id": target,
            "event_ids": [str(e) for e in (row.get("event_ids") or [])],
            "verification": "EDL_REFERENCE_ONLY",
        }],
    })
    if start is not None and end is not None and end > start:
        # Inspect near source cut; no 180-second search for an existing segment.
        base["search_windows"] = [
            {"start": round(max(0.0, start - 4.0), 3),
             "end": round(min(start + MAX_WINDOW_SPAN_SEC, end + 4.0), 3)}
        ] if min(start + MAX_WINDOW_SPAN_SEC, end + 4.0) > max(0.0, start - 4.0) else []
        base["search_profile"] = "inspect_existing_cut_neighborhood"
    return base


def compile_safe_candidates(
    story: Dict[str, Any], plan: Dict[str, Any], edl: Sequence[Dict[str, Any]],
    audit: Dict[str, Any],
) -> List[Dict[str, Any]]:
    if audit.get("schema") != "v3a_story_quality_audit_v1":
        raise ValueError("wrong Stage-1 audit schema")
    match = str(plan.get("match_id") or story.get("match_id") or "")
    audit_match = str(audit.get("match_id") or "")
    if not match or not audit_match or match != audit_match:
        raise ValueError("match_id mismatch; refusing cross-match planner evidence")
    if audit.get("release_decision") != "NOT_AUTHORIZED" or audit.get("render_ready") is not False:
        raise ValueError("Stage-1 must not grant render_ready")
    issues = audit.get("revision_requests")
    if not isinstance(issues, list):
        raise ValueError("invalid revision_requests")
    items = []
    for i, issue in enumerate(issues):
        if not isinstance(issue, dict):
            continue
        task = _task_for_issue(issue, i, plan, edl)
        if task is not None:
            items.append(task)
    return sorted(items, key=lambda t: (0 if t["severity"] == "P0" else 1, t["task_id"]))


def select_ids(raw: Dict[str, Any], candidates: Sequence[Dict[str, Any]]) -> List[str]:
    """Strictly allow an ordered subset of trusted candidate IDs, no extra fields."""
    if not isinstance(raw, dict) or set(raw) != {"selected_task_ids"}:
        raise ValueError("LLM reply must have only selected_task_ids")
    values = raw["selected_task_ids"]
    if not isinstance(values, list) or len(values) > MAX_TASKS:
        raise ValueError("invalid candidate selection length")
    allowed = {c["task_id"] for c in candidates}
    if any(not isinstance(v, str) or v not in allowed for v in values):
        raise ValueError("model suggested non-existent task")
    if len(values) != len(set(values)):
        raise ValueError("duplicate model-selected task IDs")
    return values


def compile_proposal(
    story: Dict[str, Any], plan: Dict[str, Any], edl: Sequence[Dict[str, Any]],
    audit: Dict[str, Any], *, llm_response: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    candidates = compile_safe_candidates(story, plan, edl, audit)
    fallback_ids = [c["task_id"] for c in candidates[:MAX_TASKS]]
    mode, reason, chosen = "rule_fallback", "offline_default", fallback_ids
    if llm_response is not None:
        try:
            chosen = select_ids(llm_response, candidates)
            mode, reason = "validated_llm_selection", "selection_only_no_edits"
        except ValueError as exc:
            mode, reason, chosen = "rule_fallback", f"llm_rejected:{exc}", fallback_ids
    lookup = {x["task_id"]: x for x in candidates}
    selected = [lookup[i] for i in chosen]
    return {
        "schema": SCHEMA,
        "match_id": str(plan.get("match_id") or story.get("match_id")),
        "mode": mode,
        "mode_reason": reason,
        "llm_authority": "select_and_order_existing_evidence_tasks_only",
        "selected_tasks": selected,
        "candidate_task_count": len(candidates),
        "unselected_task_ids": sorted(set(lookup) - set(chosen)),
        "source_audit_schema": audit.get("schema"),
        "metrics_are_structural_proxies": True,
        "source_render_ready": False,
        "render_ready": False,
        "edl_modified": False,
        "requires_stage3_video_evidence": bool(selected),
        "stage2_status": "PROPOSAL_ONLY",
        "release_decision": "NOT_AUTHORIZED",
        "max_revision_rounds_in_later_stage": 3,
    }


def _real_llm_selection(candidates: Sequence[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Strict opt-in: never run a billed request via default CLI path."""
    from story_video_agent.api_provider import ApiProvider, api_enabled
    if not api_enabled():
        raise ValueError("real LLM requires STORY_API_ENABLE=1 and explicit CLI approval")
    fallback = {"selected_task_ids": [c["task_id"] for c in candidates[:MAX_TASKS]]}
    provider = ApiProvider(
        require_real=True, required_roles=["planner"], max_calls=1,
        max_completion_tokens=256,
    )
    prompt = {
        "candidate_tasks": [{
            "task_id": c["task_id"], "severity": c["severity"],
            "issue_kind": c["issue_kind"], "issue_target": c["issue_target"],
            "repair_intent": c["repair_intent"],
            "evidence_status": c["evidence_status"],
        } for c in candidates],
        "limit": MAX_TASKS,
        "source_claims": "not_visually_verified",
    }
    response = provider.plan_decision(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=json.dumps(prompt, ensure_ascii=False),
        mock_decision=fallback,
    )
    provenance = {
        "provider_mode": response.get("provider_mode"),
        "api_usage": provider.stats.summary(),
        "invalid_or_degraded": True,
    }
    if response.get("provider_mode") != "real" or response.get("error"):
        return None, provenance
    try:
        result = json.loads(str(response.get("content") or ""))
    except json.JSONDecodeError:
        return None, provenance
    provenance["invalid_or_degraded"] = False
    return result, provenance


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Stage-2 evidence-proposal Planner (does NOT modify EDL)")
    p.add_argument("--phase5-dir", type=Path, required=True)
    p.add_argument("--audit", type=Path, default=None)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--llm-response-file", type=Path, default=None,
                   help="offline test fixture; not evidence or accepted event data")
    p.add_argument("--enable-real-llm", action="store_true")
    p.add_argument("--approve-api-cost", action="store_true")
    args = p.parse_args(argv)
    if args.enable_real_llm and (not args.approve_api_cost or args.llm_response_file):
        p.error("real LLM requires --approve-api-cost and forbids --llm-response-file")
    phase = args.phase5_dir
    paths = {
        "story": phase / "t01_story.json", "plan": phase / "story_plan.json",
        "edl": phase / "candidate_edl.json",
        "audit": args.audit or phase / "v3a_quality_audit.json",
    }
    try:
        objs = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in paths.items()}
        candidates = compile_safe_candidates(objs["story"], objs["plan"], objs["edl"], objs["audit"])
    except (OSError, ValueError, TypeError) as exc:
        p.error("invalid or unavailable frozen artifacts: " + str(exc))
    llm = None
    provenance = {"provider_mode": "none", "api_usage": {"real_requests": 0}}
    if args.llm_response_file:
        try:
            llm = json.loads(args.llm_response_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            p.error("invalid offline response fixture: " + str(exc))
        provenance["provider_mode"] = "offline_response_fixture"
    elif args.enable_real_llm and candidates:
        try:
            llm, provenance = _real_llm_selection(candidates)
        except Exception as exc:
            p.error(f"real planner failed; no EDL or output changed: {type(exc).__name__}: {exc}")
    proposal = compile_proposal(objs["story"], objs["plan"], objs["edl"], objs["audit"],
                                llm_response=llm)
    proposal["source_sha256"] = {name: _sha(path) for name, path in paths.items()}
    proposal["planner_execution"] = provenance
    output = args.out or (phase.parent / "v3a_stage2_planner_proposal.json")
    if output.resolve() in {path.resolve() for path in paths.values()}:
        p.error("cannot overwrite source artifacts")
    # Never create or overwrite a file inside the frozen Phase5 directory.
    if output.resolve().is_relative_to(phase.resolve()):
        p.error("output must be outside frozen Phase5 directory")
    if output.exists():
        p.error("proposal output already exists; choose a new --out path")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(proposal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "proposal": str(output), "mode": proposal["mode"],
        "selected_tasks": len(proposal["selected_tasks"]),
        "edl_modified": False, "render_ready": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
