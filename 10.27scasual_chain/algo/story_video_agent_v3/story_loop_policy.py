"""Phase 8 deterministic loop transitions — pure logic, no API calls.

Architecture contract: docs/PHASE8_FAILURE_AWARE_ITERATIVE_STORY_REVISION_DESIGN.md §2.B / §4
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .story_revision_feedback import normalize_quality

NEXT_ACTIONS = frozenset(
    {
        "PROMOTE_BEST",
        "CONTINUE_WORKING",
        "REOBSERVE",
        "REPLAN_FROM_BEST",
        "STOP_NO_ACTION",
        "STOP_BUDGET",
        "STOP_SAFETY",
    }
)

SAFETY_LABELS = frozenset({"PASS", "FAIL", "UNKNOWN"})
EVIDENCE_LABELS = frozenset({"SUFFICIENT", "PARTIAL", "INSUFFICIENT"})


def normalize_safety(raw: Any) -> str:
    s = str(raw or "UNKNOWN").strip().upper()
    return s if s in SAFETY_LABELS else "UNKNOWN"


def normalize_evidence(raw: Any) -> str:
    s = str(raw or "INSUFFICIENT").strip().upper()
    return s if s in EVIDENCE_LABELS else "INSUFFICIENT"


def init_loop_state(
    *,
    version_id: str = "v0",
    edl_path: Optional[str] = None,
    mp4_path: Optional[str] = None,
    source: str = "V3R_BASELINE",
) -> Dict[str, Any]:
    """phase8_loop_state.json contract (§3)."""
    return {
        "schema": "v3a_phase8_loop_v1",
        "initial_baseline_version_id": version_id,
        "best_verified_version_id": version_id,
        "best_verification_tier": "BASELINE_UNVERIFIED",
        "working_version_id": version_id,
        "versions": {
            version_id: {
                "parent_version_id": None,
                "edl_path": edl_path,
                "mp4_path": mp4_path,
                "safety": "UNKNOWN",
                "quality": "BASELINE_UNVERIFIED",
                "source": source,
                "semantic_evidence_refs": [],
            }
        },
        "feedback_memory_path": "phase8_feedback_memory.json",
        "round_history": [],
        "stop_reason": None,
        "delivery_version_id": None,
        "uncertain_reobserve_count": 0,
        "promising_depth": 0,
        "max_uncertain_reobserve": 1,
        "max_promising_depth": 2,
    }


def register_version(
    state: Dict[str, Any],
    *,
    version_id: str,
    parent_version_id: Optional[str],
    edl_path: Optional[str],
    mp4_path: Optional[str],
    safety: Any,
    quality: Any,
    source: str,
    semantic_evidence_refs: Optional[Sequence[Any]] = None,
    round_idx: Optional[int] = None,
) -> Dict[str, Any]:
    state = copy.deepcopy(state)
    state.setdefault("versions", {})[version_id] = {
        "parent_version_id": parent_version_id,
        "edl_path": edl_path,
        "mp4_path": mp4_path,
        "safety": normalize_safety(safety),
        "quality": str(quality),
        "source": source,
        "semantic_evidence_refs": list(semantic_evidence_refs or []),
        "round_idx": round_idx,
    }
    return state


def evaluate_round_transition(
    state: Mapping[str, Any],
    candidate: Mapping[str, Any],
    verifier: Mapping[str, Any],
    budget: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Deterministic next_action / working_ref / best_ref / reason_codes.

    candidate keys (advisory): version_id, parent_version_id, edl_changed, rendered
    verifier keys: safety, quality, evidence, hard_vetoes, issue_effect, global_regression,
                   source_kind, phase8_verdict (optional nested)
    budget keys: rounds_done, max_rounds, http_calls, max_calls, est_cost_usd, max_cost_usd,
                 has_executable_revision, has_distinct_alternative, has_new_visual_target
    """
    budget = dict(budget or {})
    v = dict(verifier or {})
    if isinstance(v.get("phase8_verdict"), Mapping):
        pv = v["phase8_verdict"]
        for k in ("safety", "quality", "evidence", "issue_effect", "global_regression"):
            if k in pv and k not in v:
                v[k] = pv[k]
            elif k in pv:
                v[k] = pv[k]

    safety = normalize_safety(v.get("safety"))
    quality = normalize_quality(v.get("quality"))
    evidence = normalize_evidence(v.get("evidence"))
    hard_vetoes = list(v.get("hard_vetoes") or [])
    source_kind = str(v.get("source_kind") or "REAL")
    edl_changed = bool(candidate.get("edl_changed"))
    rendered = bool(candidate.get("rendered"))
    cand_id = str(candidate.get("version_id") or "candidate")
    parent_id = str(
        candidate.get("parent_version_id")
        or state.get("working_version_id")
        or state.get("best_verified_version_id")
    )
    best_id = str(state.get("best_verified_version_id") or state.get("initial_baseline_version_id"))
    working_id = str(state.get("working_version_id") or best_id)

    rounds_done = int(budget.get("rounds_done") or 0)
    max_rounds = int(budget.get("max_rounds") or 3)
    http_calls = int(budget.get("http_calls") or 0)
    max_calls = budget.get("max_calls")
    est_cost = float(budget.get("est_cost_usd") or 0.0)
    max_cost = budget.get("max_cost_usd")

    def _out(
        next_action: str,
        *,
        working_ref: str,
        best_ref: str,
        reason_codes: Sequence[str],
        promote: bool = False,
        stop_reason: Optional[str] = None,
        record_negative: bool = False,
    ) -> Dict[str, Any]:
        assert next_action in NEXT_ACTIONS
        return {
            "schema": "v3a_phase8_transition_v1",
            "next_action": next_action,
            "working_ref": working_ref,
            "best_ref": best_ref,
            "reason_codes": list(reason_codes),
            "promote": promote,
            "stop_reason": stop_reason,
            "record_confirmed_negative": record_negative,
            "candidate_version_id": cand_id,
            "parent_version_id": parent_id,
            "safety": safety,
            "quality": quality,
            "evidence": evidence,
            "accept_candidate_ignored": True,
            "note": (
                "candidate_accepted boolean does not drive this policy; "
                "formal release remains stricter than exploration."
            ),
        }

    # Budget first (graceful stop preserves best).
    if rounds_done >= max_rounds:
        return _out(
            "STOP_BUDGET",
            working_ref=best_id,
            best_ref=best_id,
            reason_codes=["max_rounds_exhausted"],
            stop_reason="STOP_BUDGET",
        )
    if max_calls is not None and http_calls >= int(max_calls):
        return _out(
            "STOP_BUDGET",
            working_ref=best_id,
            best_ref=best_id,
            reason_codes=["max_http_calls_exhausted"],
            stop_reason="STOP_BUDGET",
        )
    if max_cost is not None and est_cost >= float(max_cost):
        return _out(
            "STOP_BUDGET",
            working_ref=best_id,
            best_ref=best_id,
            reason_codes=["max_cost_exhausted"],
            stop_reason="STOP_BUDGET",
        )

    if hard_vetoes or safety == "FAIL":
        return _out(
            "STOP_SAFETY",
            working_ref=best_id,
            best_ref=best_id,
            reason_codes=["hard_safety_fail_or_veto"],
            stop_reason="STOP_SAFETY",
        )

    if safety == "UNKNOWN":
        reobs = int(state.get("uncertain_reobserve_count") or 0)
        max_reobs = int(state.get("max_uncertain_reobserve") or 1)
        if reobs < max_reobs and budget.get("has_new_visual_target"):
            return _out(
                "REOBSERVE",
                working_ref=working_id,
                best_ref=best_id,
                reason_codes=["safety_unknown_directed_reobserve"],
            )
        return _out(
            "REPLAN_FROM_BEST" if budget.get("has_distinct_alternative") else "STOP_NO_ACTION",
            working_ref=best_id,
            best_ref=best_id,
            reason_codes=["safety_unknown_cannot_approve_working"],
            stop_reason=None if budget.get("has_distinct_alternative") else "STOP_NO_ACTION",
        )

    # safety == PASS below
    if not budget.get("has_executable_revision", True) and not edl_changed:
        return _out(
            "STOP_NO_ACTION",
            working_ref=best_id,
            best_ref=best_id,
            reason_codes=["no_executable_revision_or_valid_source"],
            stop_reason="STOP_NO_ACTION",
        )

    if quality == "WORSE":
        return _out(
            "REPLAN_FROM_BEST",
            working_ref=best_id,
            best_ref=best_id,
            reason_codes=["quality_worse_discard_candidate"],
            record_negative=(evidence == "SUFFICIENT"),
        )

    if quality == "SAME":
        if budget.get("has_distinct_alternative"):
            return _out(
                "REPLAN_FROM_BEST",
                working_ref=best_id,
                best_ref=best_id,
                reason_codes=["quality_same_try_distinct_edit"],
            )
        return _out(
            "STOP_NO_ACTION",
            working_ref=best_id,
            best_ref=best_id,
            reason_codes=["quality_same_no_distinct_alternative"],
            stop_reason="STOP_NO_ACTION",
        )

    if quality == "UNCERTAIN":
        reobs = int(state.get("uncertain_reobserve_count") or 0)
        max_reobs = int(state.get("max_uncertain_reobserve") or 1)
        if evidence != "SUFFICIENT" and reobs < max_reobs and budget.get("has_new_visual_target"):
            return _out(
                "REOBSERVE",
                working_ref=working_id,
                best_ref=best_id,
                reason_codes=["uncertain_directed_reobserve_once"],
            )
        if budget.get("has_distinct_alternative"):
            return _out(
                "REPLAN_FROM_BEST",
                working_ref=best_id,
                best_ref=best_id,
                reason_codes=["uncertain_replan_alternate"],
            )
        return _out(
            "STOP_NO_ACTION",
            working_ref=best_id,
            best_ref=best_id,
            reason_codes=["uncertain_no_new_evidence"],
            stop_reason="STOP_NO_ACTION",
        )

    if quality == "PROMISING":
        depth = int(state.get("promising_depth") or 0)
        max_depth = int(state.get("max_promising_depth") or 2)
        if edl_changed and safety == "PASS" and depth < max_depth:
            return _out(
                "CONTINUE_WORKING",
                working_ref=cand_id,
                best_ref=best_id,
                reason_codes=["promising_continue_working_not_release"],
            )
        if budget.get("has_distinct_alternative"):
            return _out(
                "REPLAN_FROM_BEST",
                working_ref=best_id,
                best_ref=best_id,
                reason_codes=["promising_depth_exhausted_replan"],
            )
        return _out(
            "STOP_NO_ACTION",
            working_ref=best_id,
            best_ref=best_id,
            reason_codes=["promising_stop_without_promote"],
            stop_reason="STOP_NO_ACTION",
        )

    if quality == "BETTER":
        # Fixture / offline never establishes real promote for formal IMPROVED.
        if source_kind.upper() in ("FIXTURE", "OFFLINE_FIXTURE", "PHASE7_HISTORICAL_ARTIFACT"):
            return _out(
                "CONTINUE_WORKING",
                working_ref=cand_id,
                best_ref=best_id,
                reason_codes=[
                    "fixture_better_continues_working_only",
                    "formal_improved_false_for_fixture",
                ],
            )
        can_promote = (
            safety == "PASS"
            and evidence == "SUFFICIENT"
            and edl_changed
            and rendered
            and str(v.get("issue_effect") or "").upper() in ("RESOLVED", "PARTIAL")
            and str(v.get("global_regression") or "NO").upper() in ("NO", "UNKNOWN")
            # UNKNOWN regression blocks formal promote per conservative delivery
        )
        if str(v.get("global_regression") or "").upper() == "YES":
            can_promote = False
        if str(v.get("global_regression") or "").upper() == "UNKNOWN":
            can_promote = False
        if can_promote and str(v.get("issue_effect") or "").upper() == "RESOLVED":
            return _out(
                "PROMOTE_BEST",
                working_ref=cand_id,
                best_ref=cand_id,
                reason_codes=["better_promote_best_with_verified_gain"],
                promote=True,
            )
        # Soft BETTER without full promote criteria → continue working if partial
        if edl_changed and evidence in ("SUFFICIENT", "PARTIAL"):
            return _out(
                "CONTINUE_WORKING",
                working_ref=cand_id,
                best_ref=best_id,
                reason_codes=["better_insufficient_for_promote_continue_working"],
            )
        return _out(
            "REPLAN_FROM_BEST",
            working_ref=best_id,
            best_ref=best_id,
            reason_codes=["better_missing_render_or_evidence"],
        )

    return _out(
        "STOP_NO_ACTION",
        working_ref=best_id,
        best_ref=best_id,
        reason_codes=["unhandled_quality_fallback"],
        stop_reason="STOP_NO_ACTION",
    )


def apply_transition(
    state: Dict[str, Any],
    transition: Mapping[str, Any],
    *,
    candidate_version: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Mutate loop state according to transition (returns new dict)."""
    state = copy.deepcopy(state)
    action = transition.get("next_action")
    hist = {
        "next_action": action,
        "reason_codes": list(transition.get("reason_codes") or []),
        "candidate_version_id": transition.get("candidate_version_id"),
        "working_ref": transition.get("working_ref"),
        "best_ref": transition.get("best_ref"),
        "quality": transition.get("quality"),
        "safety": transition.get("safety"),
    }
    state.setdefault("round_history", []).append(hist)

    if candidate_version and transition.get("candidate_version_id"):
        vid = str(transition["candidate_version_id"])
        state.setdefault("versions", {})[vid] = dict(candidate_version)

    if action == "PROMOTE_BEST":
        state["best_verified_version_id"] = transition["best_ref"]
        state["working_version_id"] = transition["working_ref"]
        state["best_verification_tier"] = "VERIFIED_BETTER"
        state["promising_depth"] = 0
        state["uncertain_reobserve_count"] = 0
    elif action == "CONTINUE_WORKING":
        state["working_version_id"] = transition["working_ref"]
        state["promising_depth"] = int(state.get("promising_depth") or 0) + 1
    elif action == "REOBSERVE":
        state["uncertain_reobserve_count"] = int(state.get("uncertain_reobserve_count") or 0) + 1
    elif action in ("REPLAN_FROM_BEST", "STOP_SAFETY", "STOP_NO_ACTION", "STOP_BUDGET"):
        state["working_version_id"] = transition["best_ref"]
        state["promising_depth"] = 0
        if action.startswith("STOP"):
            state["stop_reason"] = transition.get("stop_reason") or action
            state["delivery_version_id"] = state["best_verified_version_id"]

    return state


def write_loop_state(state: Mapping[str, Any], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
