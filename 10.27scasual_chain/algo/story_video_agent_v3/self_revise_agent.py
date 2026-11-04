"""V3-A self-revision Agent: real LLM Planner + VLM observe + model Verifier.

Pivot away from rule-only Stage-2 sorting. The LLM diagnoses story quality and
proposes revisions; VLM observes planner-requested windows; Verifier combines
Stage-1 hard gates with model semantic findings. Max three rounds.

Hard rules:
- Never invent score/goal facts or free media timestamps.
- Search windows must cite trusted anchors (T01 score nodes / existing EDL).
- VLM observation is NOT first-LIVE verification.
- Real HTTP requires enable_real_api AND i_approve_budget AND STORY_API_ENABLE=1.
- API failure must be reported honestly; never silently claim Agent success via
  rule/mock/cache fallback.
- Never mutate frozen V3-R Phase5 inputs; working copies only under out_dir.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from story_video_agent.api_provider import (
    COST_DISCLAIMER,
    ApiCallError,
    ApiConfigError,
    ApiProvider,
    api_enabled,
)
from story_video_agent.frames import FrameBudget, FrameStore
from story_video_agent.media import probe_video
from story_video_agent.vision_provider import _extract_json_obj

from .quality_audit import evaluate as quality_evaluate
from .remote_vlm_verify import apply_trial_env_overrides

SCHEMA = "v3a_self_revise_run_v1"
MAX_ROUNDS = 3
MAX_DIAGNOSES = 8
MAX_TOOL_REQUESTS = 4
MAX_FRAMES_PER_REQUEST = 4
LOOKBACK_SEC = 180.0
AFTER_ANCHOR_SEC = 15.0
MAX_WINDOW_SPAN = 30.0
ALLOWED_ACTIONS = {
    "search_add", "replace", "trim", "drop", "reorder", "keep", "mark_unresolved",
}
ACTION_ALIASES = {
    "add": "search_add",
    "insert": "search_add",
    "insert_segment": "search_add",
    "search": "search_add",
    "locate": "search_add",
    "recover": "search_add",
    "append": "search_add",
    "remove": "drop",
    "delete": "drop",
    "exclude": "drop",
    "shorten": "trim",
    "cut": "trim",
    "swap": "replace",
    "substitute": "replace",
    "resequence": "reorder",
    "unresolved": "mark_unresolved",
    "skip": "mark_unresolved",
}
ALLOWED_TOOLS = {"extract_frames", "vlm_observe", "widen_search"}
TOOL_ALIASES = {
    "frames": "extract_frames",
    "extract": "extract_frames",
    "observe": "vlm_observe",
    "vlm": "vlm_observe",
    "vision": "vlm_observe",
    "widen": "widen_search",
    "search_widen": "widen_search",
}


def _normalize_action(raw: Any) -> Optional[str]:
    s = str(raw or "").strip()
    if not s:
        return None
    if s in ALLOWED_ACTIONS:
        return s
    low = s.lower()
    if low in ACTION_ALIASES:
        return ACTION_ALIASES[low]
    # e.g. insert_opponent_opening_goal_action → search_add
    for key, mapped in ACTION_ALIASES.items():
        if low.startswith(key + "_") or low.startswith(key):
            return mapped
    if "search" in low or "insert" in low or "add" in low or "recover" in low or "locate" in low:
        return "search_add"
    if "drop" in low or "remove" in low or "delete" in low:
        return "drop"
    if "trim" in low or "shorten" in low:
        return "trim"
    if "replace" in low or "swap" in low:
        return "replace"
    if "reorder" in low:
        return "reorder"
    return None


def _normalize_tool(raw: Any) -> Optional[str]:
    s = str(raw or "").strip()
    if s in ALLOWED_TOOLS:
        return s
    low = s.lower()
    if low in TOOL_ALIASES:
        return TOOL_ALIASES[low]
    if "vlm" in low or "vision" in low or "observe" in low:
        return "vlm_observe"
    if "frame" in low or "extract" in low:
        return "extract_frames"
    if "widen" in low:
        return "widen_search"
    return None

PLANNER_SYSTEM = """You are a football story-video revision Planner.
Diagnose the CURRENT story cut against T01 selected-arc goals and narrative needs.
Return ONLY JSON with keys:
  diagnoses, revision_intents, video_tool_requests, notes.
You MAY identify missing critical elements, coherence gaps, unnecessary shots,
and which video tools to call next.
You MUST NOT invent scores, goal events, or absolute media timestamps.
Every search_window must cite an anchor_id from trusted_anchors (code expands
lookback). Cite evidence_refs from provided artifacts only.
Selecting a tool requests observation; it does NOT verify first LIVE goal.
Do not claim render_ready or production release.
"""

VERIFIER_SYSTEM = """You are a football story-video semantic Verifier.
Given the candidate EDL, hard-gate findings, and VLM observations, return ONLY JSON:
  issues, dimension_notes, revision_suggestions, quality_delta_vs_baseline.
Each issue needs: issue_id, severity(P0|P1|P2), dimension, target_segment_id,
problem, evidence_refs, suggested_fix.
Dimensions: story_element_coverage, narrative_coherence, shot_relevance,
image_content_quality.
Observations are NOT proof of first LIVE. Do not invent timestamps or scores.
Never set render_ready true. If evidence is insufficient, say so.
"""

VLM_SYSTEM_HINT = (
    "Describe only what is visible in the provided frames. "
    "Relate to the planner question. Flag suspected omissions or wrong shots. "
    "Suggest next search only using program-provided media times. "
    "Never claim first-LIVE or goal fact verified from these frames alone."
)


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _num(x: Any) -> Optional[float]:
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _edl_rows(edl: Any) -> List[Dict[str, Any]]:
    if isinstance(edl, list):
        return [r for r in edl if isinstance(r, dict)]
    if isinstance(edl, dict):
        for k in ("segments", "edl", "rows"):
            v = edl.get(k)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
    return []


def build_trusted_anchors(plan: Mapping[str, Any], edl: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Trusted media-time sources the model may cite; never free-form times."""
    anchors: List[Dict[str, Any]] = []
    arc = (plan.get("story_scope") or {}).get("selected_arc") or {}
    for key in ("behind_start", "equalizer", "go_ahead"):
        node = arc.get(key)
        if not isinstance(node, dict):
            continue
        t = _num(node.get("t_sec"))
        if t is None:
            continue
        anchors.append({
            "anchor_id": f"score_node:{key}",
            "kind": "T01_selected_arc_score_node",
            "arc_key": key,
            "t_sec": t,
            "score": node.get("score"),
            "note": "score_confirmation_NOT_goal_action",
        })
    for i, ext in enumerate(arc.get("lead_extends") or []):
        if not isinstance(ext, dict):
            continue
        t = _num(ext.get("t_sec"))
        if t is None:
            continue
        anchors.append({
            "anchor_id": f"score_node:lead_extend_{i}",
            "kind": "T01_selected_arc_score_node",
            "arc_key": f"lead_extend_{i}",
            "t_sec": t,
            "score": ext.get("score"),
            "note": "score_confirmation_NOT_goal_action",
        })
    for row in edl:
        sid = str(row.get("segment_id") or "")
        start, end = _num(row.get("media_in")), _num(row.get("media_out"))
        if not sid or start is None or end is None or end <= start:
            continue
        anchors.append({
            "anchor_id": f"edl:{sid}",
            "kind": "existing_edl_segment",
            "segment_id": sid,
            "role": row.get("role"),
            "media_in": start,
            "media_out": end,
        })
    return anchors


def expand_windows_from_anchor(
    anchor: Mapping[str, Any],
    *,
    lookback: float = LOOKBACK_SEC,
    after: float = AFTER_ANCHOR_SEC,
    video_duration: Optional[float] = None,
) -> List[Dict[str, float]]:
    if anchor.get("kind") == "existing_edl_segment":
        start = max(0.0, float(anchor["media_in"]) - 4.0)
        end = float(anchor["media_out"]) + 4.0
        if video_duration is not None:
            end = min(end, float(video_duration))
        return [{"start": round(start, 3), "end": round(min(start + MAX_WINDOW_SPAN, end), 3)}]
    t = _num(anchor.get("t_sec"))
    if t is None:
        raise ValueError("anchor missing t_sec")
    start = max(0.0, t - lookback)
    end = t + after
    if video_duration is not None:
        end = min(end, float(video_duration))
        start = min(start, end)
    out: List[Dict[str, float]] = []
    cur = start
    while cur < end - 1e-6 and len(out) < 8:
        stop = min(end, cur + MAX_WINDOW_SPAN)
        out.append({"start": round(cur, 3), "end": round(stop, 3)})
        cur = stop
    return out


def compact_context(
    *,
    story: Mapping[str, Any],
    plan: Mapping[str, Any],
    edl: Sequence[Dict[str, Any]],
    audit: Mapping[str, Any],
    predicted_causal: Optional[Mapping[str, Any]] = None,
    stage2_proposal: Optional[Mapping[str, Any]] = None,
    prior_observations: Optional[Sequence[Mapping[str, Any]]] = None,
    video_duration: Optional[float] = None,
) -> Dict[str, Any]:
    """Pack planner/verifier inputs; keep payload small and evidence-labelled."""
    anchors = build_trusted_anchors(plan, edl)
    arc = (plan.get("story_scope") or {}).get("selected_arc") or {}
    edl_brief = [{
        "segment_id": r.get("segment_id"),
        "role": r.get("role"),
        "media_in": r.get("media_in"),
        "media_out": r.get("media_out"),
        "event_ids": r.get("event_ids"),
        "is_replay": r.get("is_replay"),
        "shot_kind": r.get("shot_kind"),
        "beat": r.get("beat") or r.get("narrative_beat"),
    } for r in edl]
    # Keep prompt small: only goal-ish chains near selected-arc score times.
    chains_brief = []
    arc_times = []
    for key in ("behind_start", "equalizer", "go_ahead"):
        t = _num((arc.get(key) or {}).get("t_sec")) if isinstance(arc.get(key), dict) else None
        if t is not None:
            arc_times.append(t)
    if isinstance(predicted_causal, dict):
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for ch in predicted_causal.get("causal_chains") or []:
            if not isinstance(ch, dict):
                continue
            atoms = ch.get("atoms") or ch.get("events") or []
            brief_atoms = []
            nearest = None
            for a in atoms:
                if not isinstance(a, dict):
                    continue
                typ = str(a.get("type") or a.get("event_type") or "")
                t = _num(a.get("t_sec"))
                if t is None and _num(a.get("t_ms")) is not None:
                    t = float(a["t_ms"]) / 1000.0
                if t is not None and arc_times:
                    d = min(abs(t - at) for at in arc_times)
                    nearest = d if nearest is None else min(nearest, d)
                if "goal" in typ.lower() or typ in ("进球", "Goal", "Assist", "Shot"):
                    brief_atoms.append({
                        "event_id": a.get("event_id") or a.get("id"),
                        "type": typ,
                        "t_sec": t,
                        "is_replay": a.get("is_replay") or a.get("event_is_replay"),
                    })
                if len(brief_atoms) >= 6:
                    break
            if not brief_atoms:
                continue
            scored.append((nearest if nearest is not None else 1e9, {
                "chain_id": ch.get("chain_id") or ch.get("id"),
                "terminal_type": ch.get("terminal_type") or ch.get("outcome"),
                "atoms": brief_atoms,
            }))
        scored.sort(key=lambda x: x[0])
        chains_brief = [c for _, c in scored[:8]]
    s2_tasks = []
    for t in ((stage2_proposal or {}).get("selected_tasks") or [])[:4]:
        if not isinstance(t, dict):
            continue
        s2_tasks.append({
            "task_id": t.get("task_id"),
            "issue_kind": t.get("issue_kind"),
            "severity": t.get("severity"),
            "issue_target": t.get("issue_target"),
            "score_anchor_sec": t.get("score_anchor_sec"),
            "search_windows": (t.get("search_windows") or [])[:3],
            "anchor_kind": t.get("anchor_kind"),
        })
    return {
        "match_id": plan.get("match_id") or story.get("match_id"),
        "title": plan.get("title") or story.get("title"),
        "protagonist": plan.get("protagonist") or story.get("protagonist"),
        "selected_arc_brief": {
            k: {"t_sec": (arc.get(k) or {}).get("t_sec"), "score": (arc.get(k) or {}).get("score")}
            for k in ("behind_start", "equalizer", "go_ahead")
            if isinstance(arc.get(k), dict)
        },
        "trusted_anchors": anchors,
        "video_duration_sec": video_duration,
        "candidate_edl": edl_brief,
        "stage1_hard_gates": audit.get("hard_gate_findings") or [],
        "stage1_diagnostics": audit.get("diagnostic_issues") or [],
        "stage1_revision_requests": audit.get("revision_requests") or [],
        "stage1_unverified": audit.get("unverified") or [],
        "stage1_structural_proxy_pass": audit.get("structural_proxy_pass"),
        "stage2_selected_tasks": s2_tasks,
        "predicted_causal_sample": chains_brief,
        "prior_observations": list(prior_observations or [])[-4:],
        "constraints": {
            "cannot_invent_scores_or_goal_facts": True,
            "cannot_invent_absolute_timestamps": True,
            "must_cite_trusted_anchors_for_search": True,
            "vlm_is_observation_only": True,
            "max_diagnoses": MAX_DIAGNOSES,
            "max_video_tool_requests": MAX_TOOL_REQUESTS,
            "render_ready": False,
        },
    }


def _parse_model_json(content: str) -> Dict[str, Any]:
    obj = _extract_json_obj(content)
    if not isinstance(obj, dict):
        raise ValueError("model JSON must be an object")
    return obj


def validate_planner_output(
    raw: Mapping[str, Any],
    *,
    trusted_anchors: Sequence[Mapping[str, Any]],
    video_duration: Optional[float],
) -> Dict[str, Any]:
    """Reject invented times; expand windows only from cited anchors."""
    by_id = {str(a["anchor_id"]): a for a in trusted_anchors}
    diagnoses = raw.get("diagnoses")
    if not isinstance(diagnoses, list):
        raise ValueError("diagnoses must be a list")
    diagnoses = diagnoses[:MAX_DIAGNOSES]
    clean_diag = []
    for i, d in enumerate(diagnoses):
        if not isinstance(d, dict):
            continue
        refs = d.get("evidence_refs")
        if isinstance(refs, list):
            norm_refs = [{"ref": x} if isinstance(x, str) else x for x in refs if x]
        else:
            norm_refs = []
        clean_diag.append({
            "issue_id": str(d.get("issue_id") or d.get("diagnosis_id") or f"diag_{i:03d}"),
            "problem": str(d.get("problem") or d.get("detail") or "")[:800],
            "severity": d.get("severity") if d.get("severity") in ("P0", "P1", "P2") else "P2",
            "target_segment_id": d.get("target_segment_id") or d.get("target"),
            "story_element": d.get("story_element") or d.get("kind"),
            "evidence_refs": norm_refs,
            "expected_improvement": str(d.get("expected_improvement") or d.get("suggested_fix") or "")[:400],
        })
    intents = raw.get("revision_intents")
    if not isinstance(intents, list):
        intents = []
    clean_intents = []
    dropped_intents = []
    for i, it in enumerate(intents[:MAX_DIAGNOSES]):
        if not isinstance(it, dict):
            continue
        action = _normalize_action(it.get("action"))
        if action is None:
            dropped_intents.append({"raw_action": it.get("action"), "reason": "unmapped_action"})
            continue
        # Prefer explicit role; else recover from verbose action strings.
        role = it.get("role")
        if not role and isinstance(it.get("action"), str) and "goal_action" in it["action"]:
            role = it["action"].replace("insert_", "").replace("add_", "")
        clean_intents.append({
            "intent_id": str(it.get("intent_id") or f"intent_{i:03d}"),
            "action": action,
            "raw_action": it.get("action"),
            "issue_id": it.get("issue_id"),
            "target_segment_id": it.get("target_segment_id"),
            "role": role,
            "anchor_id": it.get("anchor_id"),
            "rationale": str(it.get("rationale") or "")[:600],
            "expected_improvement": str(it.get("expected_improvement") or "")[:400],
            "risk": str(it.get("risk") or "")[:400],
            "evidence_refs": it.get("evidence_refs") if isinstance(it.get("evidence_refs"), list) else [],
        })
    tools = raw.get("video_tool_requests")
    if not isinstance(tools, list):
        tools = []
    clean_tools = []
    dropped_tools = []
    for i, tr in enumerate(tools[:MAX_TOOL_REQUESTS]):
        if not isinstance(tr, dict):
            continue
        tool = _normalize_tool(tr.get("tool"))
        if tool is None:
            dropped_tools.append({"raw_tool": tr.get("tool"), "reason": "unmapped_tool"})
            continue
        aid = str(tr.get("anchor_id") or "")
        if aid not in by_id:
            dropped_tools.append({"raw_tool": tr.get("tool"), "anchor_id": aid, "reason": "unknown_anchor"})
            continue
        windows = expand_windows_from_anchor(by_id[aid], video_duration=video_duration)
        # Optional refine: allow listing subset indices only, not free timestamps
        idx = tr.get("window_indices")
        if isinstance(idx, list) and idx:
            picked = []
            for j in idx:
                if isinstance(j, int) and 0 <= j < len(windows):
                    picked.append(windows[j])
            windows = picked or windows[:3]
        else:
            windows = windows[:3]
        clean_tools.append({
            "request_id": str(tr.get("request_id") or f"tool_{i:03d}"),
            "tool": tool,
            "issue_id": tr.get("issue_id"),
            "anchor_id": aid,
            "question": str(tr.get("question") or "")[:600],
            "search_windows": windows,
            "windows_source": "trusted_anchor_expansion",
        })
    if not clean_diag and not clean_intents and not clean_tools:
        raise ValueError("planner produced no usable diagnoses/intents/tools after validation")
    return {
        "diagnoses": clean_diag,
        "revision_intents": clean_intents,
        "video_tool_requests": clean_tools,
        "dropped_intents": dropped_intents,
        "dropped_tools": dropped_tools,
        "notes": (
            json.dumps(raw.get("notes"), ensure_ascii=False)
            if isinstance(raw.get("notes"), (dict, list))
            else str(raw.get("notes") or "")
        )[:800],
        "validated": True,
    }


def validate_verifier_output(raw: Mapping[str, Any]) -> Dict[str, Any]:
    issues = raw.get("issues")
    if not isinstance(issues, list):
        raise ValueError("verifier issues must be a list")
    clean = []
    for i, iss in enumerate(issues[:MAX_DIAGNOSES]):
        if not isinstance(iss, dict):
            continue
        clean.append({
            "issue_id": str(iss.get("issue_id") or f"v_{i:03d}"),
            "severity": iss.get("severity") if iss.get("severity") in ("P0", "P1", "P2") else "P2",
            "dimension": str(iss.get("dimension") or "unknown"),
            "target_segment_id": iss.get("target_segment_id"),
            "problem": str(iss.get("problem") or "")[:800],
            "evidence_refs": iss.get("evidence_refs") if isinstance(iss.get("evidence_refs"), list) else [],
            "suggested_fix": str(iss.get("suggested_fix") or "")[:400],
        })
    return {
        "issues": clean,
        "dimension_notes": raw.get("dimension_notes") if isinstance(raw.get("dimension_notes"), dict) else {},
        "revision_suggestions": raw.get("revision_suggestions") if isinstance(raw.get("revision_suggestions"), list) else [],
        "quality_delta_vs_baseline": str(raw.get("quality_delta_vs_baseline") or "")[:600],
        "validated": True,
    }


def call_llm_planner(
    api: ApiProvider,
    context: Mapping[str, Any],
    *,
    fixture: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    if fixture is not None:
        validated = validate_planner_output(
            fixture,
            trusted_anchors=context["trusted_anchors"],
            video_duration=context.get("video_duration_sec"),
        )
        return {
            "ok": True,
            "provider_mode": "offline_fixture",
            "raw": fixture,
            "validated": validated,
            "usage": {"real_requests": 0},
            "est_cost_usd": 0.0,
        }
    user = json.dumps(context, ensure_ascii=False)
    # Intentionally no usable mock_decision for real Agent runs: failure must surface.
    resp = api.plan_decision(
        system_prompt=PLANNER_SYSTEM,
        user_prompt=user,
        mock_decision={"error": "mock_not_allowed_for_self_revise_agent"},
    )
    mode = str(resp.get("provider_mode") or "")
    content = str(resp.get("content") or "")
    if mode != "real" or resp.get("error"):
        return {
            "ok": False,
            "provider_mode": mode or "degraded",
            "error": str(resp.get("error") or f"planner_not_real:{mode}"),
            "raw_content": content,
            "raw_excerpt": content[:8000],
            "usage": resp.get("usage"),
            "est_cost_usd": resp.get("est_cost_usd"),
            "model": resp.get("model"),
        }
    try:
        raw = _parse_model_json(content)
        validated = validate_planner_output(
            raw,
            trusted_anchors=context["trusted_anchors"],
            video_duration=context.get("video_duration_sec"),
        )
    except Exception as exc:
        return {
            "ok": False,
            "provider_mode": mode,
            "error": f"planner_parse_or_validate:{type(exc).__name__}:{exc}",
            "raw_content": content,
            "raw_excerpt": content[:8000],
            "usage": resp.get("usage"),
            "est_cost_usd": resp.get("est_cost_usd"),
            "model": resp.get("model"),
        }
    return {
        "ok": True,
        "provider_mode": mode,
        "model": resp.get("model"),
        "raw": raw,
        "validated": validated,
        "raw_content": content,
        "raw_excerpt": content[:8000],
        "usage": resp.get("usage"),
        "est_cost_usd": resp.get("est_cost_usd"),
        "cost_disclaimer": COST_DISCLAIMER,
    }


def call_llm_verifier(
    api: ApiProvider,
    payload: Mapping[str, Any],
    *,
    fixture: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    if fixture is not None:
        return {
            "ok": True,
            "provider_mode": "offline_fixture",
            "validated": validate_verifier_output(fixture),
            "raw": fixture,
            "usage": {"real_requests": 0},
            "est_cost_usd": 0.0,
        }
    resp = api.plan_decision(
        system_prompt=VERIFIER_SYSTEM,
        user_prompt=json.dumps(payload, ensure_ascii=False),
        mock_decision={"error": "mock_not_allowed_for_self_revise_agent"},
    )
    mode = str(resp.get("provider_mode") or "")
    content = str(resp.get("content") or "")
    if mode != "real" or resp.get("error"):
        return {
            "ok": False,
            "provider_mode": mode or "degraded",
            "error": str(resp.get("error") or f"verifier_not_real:{mode}"),
            "raw_excerpt": content[:2000],
            "usage": resp.get("usage"),
            "est_cost_usd": resp.get("est_cost_usd"),
        }
    try:
        raw = _parse_model_json(content)
        validated = validate_verifier_output(raw)
    except Exception as exc:
        return {
            "ok": False,
            "provider_mode": mode,
            "error": f"verifier_parse_or_validate:{type(exc).__name__}:{exc}",
            "raw_excerpt": content[:2000],
            "usage": resp.get("usage"),
            "est_cost_usd": resp.get("est_cost_usd"),
        }
    return {
        "ok": True,
        "provider_mode": mode,
        "model": resp.get("model"),
        "raw": raw,
        "validated": validated,
        "raw_excerpt": content[:4000],
        "usage": resp.get("usage"),
        "est_cost_usd": resp.get("est_cost_usd"),
        "cost_disclaimer": COST_DISCLAIMER,
    }


def run_vlm_observations(
    api: ApiProvider,
    *,
    video: Path,
    work_dir: Path,
    tool_requests: Sequence[Mapping[str, Any]],
    frame_budget: int = 12,
) -> Dict[str, Any]:
    """Extract real frames for planner windows and call VLM; observation-only."""
    work_dir.mkdir(parents=True, exist_ok=True)
    media = probe_video(video)
    store = FrameStore(
        media,
        out_dir=work_dir / "frames",
        budget=FrameBudget(max_frames=frame_budget),
    )
    observations: List[Dict[str, Any]] = []
    for tr in tool_requests:
        if tr.get("tool") not in ("extract_frames", "vlm_observe", "widen_search"):
            continue
        windows = tr.get("search_windows") or []
        if not windows:
            continue
        win = windows[0]
        start, end = float(win["start"]), float(win["end"])
        times = store.sample_times(start, end, count=min(MAX_FRAMES_PER_REQUEST, 4))
        frames = []
        for ti, t in enumerate(times):
            rec = store.extract_at(
                t,
                gap_id=str(tr.get("request_id") or "obs"),
                tool="self_revise_observe",
            )
            frames.append(rec.to_dict())
        prompt = (
            f"{VLM_SYSTEM_HINT}\n"
            f"Planner question: {tr.get('question')}\n"
            f"issue_id: {tr.get('issue_id')}\n"
            f"anchor_id: {tr.get('anchor_id')}\n"
            f"window: [{start:.3f},{end:.3f}]\n"
            "Return JSON keys: visible_content, story_relation, suspected_errors,"
            "shot_suggestions, next_search_request, cited_frame_ids, confidence,"
            "fact_verified(false), observation_only(true)."
        )
        mock_obj = {
            "visible_content": "mock_forbidden",
            "story_relation": "",
            "suspected_errors": [],
            "shot_suggestions": [],
            "next_search_request": None,
            "cited_frame_ids": [f["frame_id"] for f in frames[:1]],
            "confidence": 0.0,
            "fact_verified": False,
            "observation_only": True,
        }
        paths = [Path(f["path"]) for f in frames]
        fids = [f["frame_id"] for f in frames]
        bindings = [{
            "frame_id": f["frame_id"],
            "requested_media_sec": f.get("requested_media_sec"),
            "actual_media_sec": f.get("actual_media_sec"),
            "pts_status": f.get("pts_status"),
        } for f in frames]
        try:
            raw_resp = api.vision_json(
                prompt=prompt,
                frame_paths=paths,
                frame_ids=fids,
                mock_obj=mock_obj,
                frame_bindings=bindings,
            )
        except (ApiConfigError, ApiCallError) as exc:
            observations.append({
                "request_id": tr.get("request_id"),
                "ok": False,
                "error": f"{type(exc).__name__}:{exc}",
                "provider_mode": "degraded",
                "frames": frames,
                "fact_verified": False,
                "observation_only": True,
            })
            continue
        mode = str(raw_resp.get("provider_mode") or "")
        if mode == "openai_compatible":
            mode = "real"
        content = str(raw_resp.get("content") or "")
        parsed = None
        parse_error = None
        try:
            parsed = _parse_model_json(content)
        except Exception as exc:
            parse_error = f"{type(exc).__name__}:{exc}"
        ok = mode == "real" and not raw_resp.get("error") and parsed is not None
        if parsed is not None:
            parsed["fact_verified"] = False
            parsed["observation_only"] = True
        observations.append({
            "request_id": tr.get("request_id"),
            "issue_id": tr.get("issue_id"),
            "anchor_id": tr.get("anchor_id"),
            "ok": ok,
            "provider_mode": mode,
            "model": raw_resp.get("model"),
            "error": None if ok else (str(raw_resp.get("error") or parse_error or f"not_real:{mode}")),
            "frames": frames,
            "window": {"start": start, "end": end},
            "vlm": parsed,
            "raw_excerpt": content[:3000],
            "usage": raw_resp.get("usage"),
            "est_cost_usd": raw_resp.get("est_cost_usd"),
            "fact_verified": False,
            "observation_only": True,
        })
    return {
        "observations": observations,
        "frame_manifest": store.manifest,
        "any_real_ok": any(o.get("ok") and o.get("provider_mode") == "real" for o in observations),
    }


def apply_candidate_revision(
    baseline_edl: Sequence[Dict[str, Any]],
    intents: Sequence[Mapping[str, Any]],
    observations: Sequence[Mapping[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Conservative working-copy edits only. Prefer mark_unresolved until evidence exists.

    Does NOT invent new media timestamps. search_add only records a pending slot
    when VLM observed something useful; still leaves media_in/out null until a
    later evidence-bound stage fills them from frame PTS.
    """
    edl = copy.deepcopy(list(baseline_edl))
    applied: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    by_id = {str(r.get("segment_id")): i for i, r in enumerate(edl)}
    obs_ok = [o for o in observations if o.get("ok")]
    for it in intents:
        action = it.get("action")
        sid = it.get("target_segment_id")
        if action in ("keep", "mark_unresolved"):
            applied.append({"intent": it.get("intent_id"), "action": action, "status": "recorded"})
            continue
        if action == "drop":
            if sid and sid in by_id:
                # Soft-drop: mark excluded rather than deleting history
                edl[by_id[sid]]["include_in_cut"] = False
                edl[by_id[sid]]["agent_drop_reason"] = it.get("rationale")
                applied.append({"intent": it.get("intent_id"), "action": "drop", "segment_id": sid})
            else:
                rejected.append({"intent": it.get("intent_id"), "reason": "missing_segment"})
            continue
        if action == "trim" and sid and sid in by_id:
            # Trim only within existing bounds using observation frame PTS midpoints — never invent.
            frames = []
            for o in obs_ok:
                if o.get("issue_id") == it.get("issue_id"):
                    frames.extend(o.get("frames") or [])
            pts = [_num(f.get("actual_media_sec")) or _num(f.get("requested_media_sec")) for f in frames]
            pts = [p for p in pts if p is not None]
            row = edl[by_id[sid]]
            mi, mo = _num(row.get("media_in")), _num(row.get("media_out"))
            if mi is None or mo is None or not pts:
                rejected.append({"intent": it.get("intent_id"), "reason": "no_pts_for_trim"})
                continue
            lo, hi = min(pts), max(pts)
            if not (mi - 1e-3 <= lo <= mo + 1e-3 and mi - 1e-3 <= hi <= mo + 1e-3):
                rejected.append({"intent": it.get("intent_id"), "reason": "pts_outside_segment"})
                continue
            # Shrink toward observed span but keep >=2s
            new_in = max(mi, lo - 1.0)
            new_out = min(mo, hi + 1.0)
            if new_out - new_in < 2.0:
                rejected.append({"intent": it.get("intent_id"), "reason": "trim_too_short"})
                continue
            row["media_in"], row["media_out"] = round(new_in, 3), round(new_out, 3)
            row["agent_trim"] = True
            applied.append({"intent": it.get("intent_id"), "action": "trim", "segment_id": sid,
                            "media_in": row["media_in"], "media_out": row["media_out"]})
            continue
        if action in ("search_add", "replace"):
            # Do not fabricate a finished goal cut. Record pending evidence slot only.
            applied.append({
                "intent": it.get("intent_id"),
                "action": action,
                "status": "pending_evidence_slot",
                "role": it.get("role"),
                "anchor_id": it.get("anchor_id"),
                "note": "no_media_times_invented; requires Stage evidence binding",
            })
            continue
        if action == "reorder":
            rejected.append({"intent": it.get("intent_id"), "reason": "reorder_requires_explicit_order_list"})
            continue
        rejected.append({"intent": it.get("intent_id"), "reason": f"unsupported_or_unsafe:{action}"})
    return edl, {"applied": applied, "rejected": rejected, "edl_row_count": len(edl)}


def hard_gate_blocks(audit: Mapping[str, Any]) -> bool:
    findings = audit.get("hard_gate_findings") or []
    return any(str(f.get("severity")) == "P0" for f in findings if isinstance(f, dict))


def decide_accept(
    *,
    baseline_audit: Mapping[str, Any],
    candidate_audit: Mapping[str, Any],
    verifier: Mapping[str, Any],
    revision_meta: Mapping[str, Any],
) -> Dict[str, Any]:
    """Accept only with evidence of improvement and no new P0 hard gates."""
    base_p0 = sum(1 for f in (baseline_audit.get("hard_gate_findings") or []) if f.get("severity") == "P0")
    cand_p0 = sum(1 for f in (candidate_audit.get("hard_gate_findings") or []) if f.get("severity") == "P0")
    applied = revision_meta.get("applied") or []
    meaningful = [a for a in applied if a.get("action") in ("trim", "drop") or a.get("status") == "pending_evidence_slot"]
    model_delta = ""
    if verifier.get("ok"):
        model_delta = str((verifier.get("validated") or {}).get("quality_delta_vs_baseline") or "")
    # Structural improvement: fewer P0 hard gates
    improved_gates = cand_p0 < base_p0
    # Without bound media times, pending slots alone do not count as story improvement
    improved = improved_gates
    accept = bool(improved and cand_p0 == 0)
    reason = []
    if not meaningful:
        reason.append("no_safe_revision_applied")
    if not improved:
        reason.append("no_hard_gate_improvement")
    if cand_p0 > base_p0:
        reason.append("new_or_worsened_p0")
        accept = False
    if cand_p0 > 0 and not improved_gates:
        reason.append("p0_still_open")
        accept = False
    if not verifier.get("ok"):
        reason.append("model_verifier_failed")
        # Do not accept on verifier failure
        accept = False
    return {
        "accept": accept,
        "reasons": reason or ["accepted_structural_improvement"],
        "baseline_p0": base_p0,
        "candidate_p0": cand_p0,
        "model_quality_delta": model_delta,
        "pending_only": all(a.get("status") == "pending_evidence_slot" for a in meaningful) if meaningful else False,
    }


def write_phase5_workdir(out_phase5: Path, *, story: Any, plan: Any, edl: Any, rendered: Optional[Path]) -> None:
    out_phase5.mkdir(parents=True, exist_ok=True)
    (out_phase5 / "t01_story.json").write_text(json.dumps(story, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_phase5 / "story_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_phase5 / "candidate_edl.json").write_text(json.dumps(edl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if rendered and rendered.is_file():
        # Do not re-render; optional copy reference for audit if present
        dest = out_phase5 / rendered.name
        if not dest.exists():
            try:
                os.symlink(rendered.resolve(), dest)
            except OSError:
                pass


def run_self_revise(
    *,
    phase5_dir: Path,
    out_dir: Path,
    video: Optional[Path] = None,
    predicted_causal: Optional[Path] = None,
    stage2_proposal: Optional[Path] = None,
    audit_path: Optional[Path] = None,
    enable_real_api: bool = False,
    i_approve_budget: bool = False,
    max_rounds: int = 2,
    max_calls: int = 8,
    max_cost_usd: float = 1.0,
    max_completion_tokens: int = 2048,
    planner_fixture: Optional[Path] = None,
    verifier_fixture: Optional[Path] = None,
    skip_vlm: bool = False,
) -> Dict[str, Any]:
    phase5_dir = phase5_dir.resolve()
    out_dir = out_dir.resolve()
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError(f"out_dir must be empty/new: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    story = _load_json(phase5_dir / "t01_story.json")
    plan = _load_json(phase5_dir / "story_plan.json")
    edl_obj = _load_json(phase5_dir / "candidate_edl.json")
    baseline_edl = _edl_rows(edl_obj)
    audit_file = audit_path or (phase5_dir / "v3a_quality_audit.json")
    baseline_audit = _load_json(audit_file) if audit_file.is_file() else None
    if baseline_audit is None:
        # Read-only structural audit into out_dir; does not touch freeze dir
        tmp = out_dir / "_baseline_phase5"
        write_phase5_workdir(tmp, story=story, plan=plan, edl=edl_obj, rendered=phase5_dir / "story_qc.mp4")
        baseline_audit = audit_phase5_dir(tmp, rendered_video=None)
        (out_dir / "baseline_quality_audit.json").write_text(
            json.dumps(baseline_audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    pc = _load_json(predicted_causal) if predicted_causal and predicted_causal.is_file() else None
    s2 = _load_json(stage2_proposal) if stage2_proposal and stage2_proposal.is_file() else None

    enrich_video = None
    # Prefer explicit video; else enrich metadata path if present beside run
    if video and video.is_file():
        enrich_video = video
    video_duration = None
    if enrich_video:
        try:
            video_duration = float(probe_video(enrich_video).duration_sec)
        except Exception:
            video_duration = None

    source_sha = {
        "story": _sha(phase5_dir / "t01_story.json"),
        "plan": _sha(phase5_dir / "story_plan.json"),
        "edl": _sha(phase5_dir / "candidate_edl.json"),
        "audit": _sha(audit_file) if audit_file.is_file() else None,
    }

    real_mode = bool(enable_real_api and i_approve_budget)
    fixture_mode = planner_fixture is not None
    if real_mode and fixture_mode:
        raise ValueError("refuse mixing real API with planner fixture")
    if enable_real_api and not i_approve_budget:
        raise ValueError("Real API refused: pass i_approve_budget after budget approval")
    if real_mode and not api_enabled():
        os.environ["STORY_API_ENABLE"] = "1"
    if real_mode:
        apply_trial_env_overrides(
            max_calls=max_calls,
            max_cost_usd=max_cost_usd,
            max_completion_tokens=max_completion_tokens,
            disable_thinking=True,
        )

    api = None
    if real_mode:
        api = ApiProvider(
            require_real=True,
            force_mock=False,
            max_calls=max_calls,
            max_cost_usd=max_cost_usd,
            max_completion_tokens=max_completion_tokens,
            required_roles=["planner", "vision"],
        )
    elif fixture_mode:
        api = ApiProvider(force_mock=True, max_calls=0, max_cost_usd=0.0)
    else:
        # Config-audit / dry structure without claiming success
        api = ApiProvider(force_mock=True, max_calls=0, max_cost_usd=0.0)

    p_fix = _load_json(planner_fixture) if planner_fixture else None
    v_fix = _load_json(verifier_fixture) if verifier_fixture else None

    rounds: List[Dict[str, Any]] = []
    current_edl = copy.deepcopy(baseline_edl)
    best = {
        "edl": copy.deepcopy(baseline_edl),
        "audit": baseline_audit,
        "round": 0,
        "accepted": False,
    }
    observations_acc: List[Dict[str, Any]] = []
    agent_success = False
    abort_reason = None

    n_rounds = max(1, min(int(max_rounds), MAX_ROUNDS))
    for r in range(1, n_rounds + 1):
        round_dir = out_dir / f"round_{r:02d}"
        round_dir.mkdir(parents=True, exist_ok=True)
        ctx = compact_context(
            story=story, plan=plan, edl=current_edl, audit=baseline_audit if r == 1 else best["audit"],
            predicted_causal=pc, stage2_proposal=s2,
            prior_observations=observations_acc, video_duration=video_duration,
        )
        (round_dir / "planner_context.json").write_text(
            json.dumps(ctx, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        if not real_mode and not fixture_mode:
            abort_reason = "real_api_not_enabled_or_not_approved"
            rounds.append({
                "round": r,
                "aborted": True,
                "reason": abort_reason,
                "note": "No mock/cache disguised as Agent success.",
            })
            break

        try:
            planner = call_llm_planner(api, ctx, fixture=p_fix if r == 1 else (p_fix if fixture_mode else None))
        except (ApiConfigError, ApiCallError) as exc:
            planner = {"ok": False, "error": f"{type(exc).__name__}:{exc}", "provider_mode": "degraded"}
        (round_dir / "planner_result.json").write_text(
            json.dumps(planner, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if not planner.get("ok"):
            abort_reason = f"planner_failed:{planner.get('error')}"
            rounds.append({"round": r, "planner": planner, "aborted": True, "reason": abort_reason})
            break

        validated = planner["validated"]
        obs_pack: Dict[str, Any] = {"observations": [], "any_real_ok": False}
        if not skip_vlm and enrich_video and validated.get("video_tool_requests"):
            if real_mode:
                try:
                    obs_pack = run_vlm_observations(
                        api,
                        video=enrich_video,
                        work_dir=round_dir / "vlm",
                        tool_requests=validated["video_tool_requests"],
                    )
                except (ApiConfigError, ApiCallError, OSError, ValueError) as exc:
                    obs_pack = {
                        "observations": [],
                        "any_real_ok": False,
                        "error": f"{type(exc).__name__}:{exc}",
                    }
            elif fixture_mode:
                obs_pack = {
                    "observations": [{
                        "request_id": "fixture_obs",
                        "ok": True,
                        "provider_mode": "offline_fixture",
                        "fact_verified": False,
                        "observation_only": True,
                        "vlm": {
                            "visible_content": "fixture: no real frames",
                            "observation_only": True,
                            "fact_verified": False,
                        },
                    }],
                    "any_real_ok": False,
                    "note": "fixture_skip_real_vlm",
                }
        (round_dir / "vlm_observations.json").write_text(
            json.dumps(obs_pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        observations_acc.extend(obs_pack.get("observations") or [])

        cand_edl, rev_meta = apply_candidate_revision(
            current_edl, validated.get("revision_intents") or [], obs_pack.get("observations") or [],
        )
        cand_phase = round_dir / "candidate_phase5"
        write_phase5_workdir(cand_phase, story=story, plan=plan, edl=cand_edl, rendered=None)
        cand_audit = audit_phase5_dir(cand_phase, rendered_video=None)
        (round_dir / "candidate_quality_audit.json").write_text(
            json.dumps(cand_audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (round_dir / "revision_meta.json").write_text(
            json.dumps(rev_meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        ver_payload = {
            "baseline_hard_gates": baseline_audit.get("hard_gate_findings"),
            "candidate_hard_gates": cand_audit.get("hard_gate_findings"),
            "planner_diagnoses": validated.get("diagnoses"),
            "revision_meta": rev_meta,
            "observations": [{
                "request_id": o.get("request_id"),
                "ok": o.get("ok"),
                "provider_mode": o.get("provider_mode"),
                "window": o.get("window"),
                "vlm": o.get("vlm"),
                "fact_verified": False,
            } for o in (obs_pack.get("observations") or [])],
            "constraints": ctx["constraints"],
        }
        try:
            verifier = call_llm_verifier(api, ver_payload, fixture=v_fix if fixture_mode else None)
        except (ApiConfigError, ApiCallError) as exc:
            verifier = {"ok": False, "error": f"{type(exc).__name__}:{exc}", "provider_mode": "degraded"}
        (round_dir / "verifier_result.json").write_text(
            json.dumps(verifier, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        decision = decide_accept(
            baseline_audit=baseline_audit,
            candidate_audit=cand_audit,
            verifier=verifier,
            revision_meta=rev_meta,
        )
        (round_dir / "accept_decision.json").write_text(
            json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        round_rec = {
            "round": r,
            "planner_ok": True,
            "planner_provider_mode": planner.get("provider_mode"),
            "planner_model": planner.get("model"),
            "diagnoses": validated.get("diagnoses"),
            "revision_intents": validated.get("revision_intents"),
            "video_tool_requests": validated.get("video_tool_requests"),
            "vlm_any_real_ok": obs_pack.get("any_real_ok"),
            "verifier_ok": verifier.get("ok"),
            "verifier_provider_mode": verifier.get("provider_mode"),
            "revision_meta": rev_meta,
            "accept_decision": decision,
            "est_cost_usd_planner": planner.get("est_cost_usd"),
            "est_cost_usd_verifier": verifier.get("est_cost_usd"),
        }
        rounds.append(round_rec)

        if decision.get("accept"):
            current_edl = cand_edl
            best = {"edl": cand_edl, "audit": cand_audit, "round": r, "accepted": True}
            agent_success = True
        else:
            # rollback candidate; keep baseline/best
            current_edl = copy.deepcopy(best["edl"])

        # Clear fixture reuse after first round in fixture mode still ok; real mode continues
        if real_mode and api is not None:
            usage = api.stats.summary()
            if api.max_calls is not None and usage.get("http_attempts", 0) >= api.max_calls:
                abort_reason = "max_calls_reached"
                break
            if api.max_cost_usd is not None and usage.get("est_cost_usd_real", 0) >= api.max_cost_usd:
                abort_reason = "max_cost_reached"
                break

    usage = api.stats.summary() if api is not None else {}
    # Honest success: real provider participation when required
    real_participation = False
    if real_mode:
        real_participation = any(
            (rr.get("planner_provider_mode") == "real") or (rr.get("verifier_provider_mode") == "real")
            or rr.get("vlm_any_real_ok")
            for rr in rounds if not rr.get("aborted")
        )
        if not real_participation:
            agent_success = False
            abort_reason = abort_reason or "no_real_provider_participation"

    summary = {
        "schema": SCHEMA,
        "match_id": plan.get("match_id") or story.get("match_id"),
        "phase5_dir": str(phase5_dir),
        "out_dir": str(out_dir),
        "frozen_inputs_untouched": True,
        "source_sha256": source_sha,
        "enable_real_api": enable_real_api,
        "i_approve_budget": i_approve_budget,
        "fixture_mode": fixture_mode,
        "video": str(enrich_video) if enrich_video else None,
        "video_duration_sec": video_duration,
        "max_rounds": n_rounds,
        "rounds_executed": len(rounds),
        "rounds": rounds,
        "best_round": best.get("round"),
        "accepted_any_revision": bool(best.get("accepted")),
        "agent_claimed_success": bool(agent_success and real_participation if real_mode else agent_success and fixture_mode),
        "abort_reason": abort_reason,
        "api_usage": usage,
        "cost_disclaimer": COST_DISCLAIMER,
        "edl_modified_frozen_phase5": False,
        "render_ready": False,
        "release_decision": "NOT_AUTHORIZED",
        "note": (
            "Acceptance requires real model participation (when real mode), hard-gate "
            "improvement, and honest failure reporting. VLM observations never certify first LIVE."
        ),
    }
    (out_dir / "self_revise_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "best_candidate_edl.json").write_text(
        json.dumps(best["edl"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def audit_phase5_dir(phase5: Path, rendered_video: Optional[Path] = None) -> Dict[str, Any]:
    story = _load_json(phase5 / "t01_story.json")
    plan = _load_json(phase5 / "story_plan.json")
    edl = _load_json(phase5 / "candidate_edl.json")
    return quality_evaluate(story, plan, edl, rendered_video=rendered_video)


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="V3-A LLM+VLM self-revision Agent (max 3 rounds)")
    p.add_argument("--phase5-dir", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--video", type=Path, default=None)
    p.add_argument("--predicted-causal", type=Path, default=None)
    p.add_argument("--stage2-proposal", type=Path, default=None)
    p.add_argument("--audit", type=Path, default=None)
    p.add_argument("--max-rounds", type=int, default=2)
    p.add_argument("--max-calls", type=int, default=8)
    p.add_argument("--max-cost-usd", type=float, default=1.0)
    p.add_argument("--max-completion-tokens", type=int, default=2048)
    p.add_argument("--enable-real-api", action="store_true")
    p.add_argument("--i-approve-budget", action="store_true")
    p.add_argument("--planner-fixture", type=Path, default=None)
    p.add_argument("--verifier-fixture", type=Path, default=None)
    p.add_argument("--skip-vlm", action="store_true")
    p.add_argument("--config-audit-only", action="store_true")
    args = p.parse_args(argv)

    if args.config_audit_only:
        apply_trial_env_overrides(
            max_calls=args.max_calls,
            max_cost_usd=args.max_cost_usd,
            max_completion_tokens=args.max_completion_tokens,
        )
        # force enable check without HTTP
        status = {
            "api_enabled_env": api_enabled(),
            "STORY_API_ENABLE": os.environ.get("STORY_API_ENABLE"),
            "planner_model": os.environ.get("STORY_LLM_MODEL"),
            "vision_model": os.environ.get("STORY_VLM_MODEL"),
            "base_url_set": bool(os.environ.get("STORY_LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL")),
            "max_calls": args.max_calls,
            "max_cost_usd": args.max_cost_usd,
            "http_requests_sent": 0,
            "render_ready": False,
        }
        args.out_dir.mkdir(parents=True, exist_ok=True)
        path = args.out_dir / "config_audit_only.json"
        path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "ok_config_audit_only", "path": str(path), **status}, ensure_ascii=False))
        return 0

    if args.out_dir.resolve().is_relative_to(args.phase5_dir.resolve()):
        p.error("out-dir must be outside frozen phase5 directory")

    try:
        summary = run_self_revise(
            phase5_dir=args.phase5_dir,
            out_dir=args.out_dir,
            video=args.video,
            predicted_causal=args.predicted_causal,
            stage2_proposal=args.stage2_proposal,
            audit_path=args.audit,
            enable_real_api=args.enable_real_api,
            i_approve_budget=args.i_approve_budget,
            max_rounds=args.max_rounds,
            max_calls=args.max_calls,
            max_cost_usd=args.max_cost_usd,
            max_completion_tokens=args.max_completion_tokens,
            planner_fixture=args.planner_fixture,
            verifier_fixture=args.verifier_fixture,
            skip_vlm=args.skip_vlm,
        )
    except Exception as exc:
        print(json.dumps({
            "status": "failed",
            "error": f"{type(exc).__name__}:{exc}",
            "agent_claimed_success": False,
            "render_ready": False,
        }, ensure_ascii=False))
        return 2

    print(json.dumps({
        "status": "ok" if summary.get("agent_claimed_success") else "completed_without_agent_success",
        "out_dir": summary.get("out_dir"),
        "rounds": summary.get("rounds_executed"),
        "accepted_any_revision": summary.get("accepted_any_revision"),
        "agent_claimed_success": summary.get("agent_claimed_success"),
        "abort_reason": summary.get("abort_reason"),
        "api_usage": {
            "http_attempts": (summary.get("api_usage") or {}).get("http_attempts"),
            "est_cost_usd_real": (summary.get("api_usage") or {}).get("est_cost_usd_real"),
            "real_ok": (summary.get("api_usage") or {}).get("real_ok"),
            "real_failures": (summary.get("api_usage") or {}).get("real_failures"),
        },
        "edl_modified_frozen_phase5": False,
        "render_ready": False,
    }, ensure_ascii=False))
    return 0 if summary.get("rounds_executed", 0) > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
