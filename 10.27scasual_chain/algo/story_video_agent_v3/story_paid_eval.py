"""Constrained paid-API helpers for story-level E2E (match-agnostic).

Hard process controls: max_calls, estimate max_cost_usd, max_retries=0.
Estimate is NOT a vendor invoice hard cap — callers must stop if controls fail.
Never log API keys.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from story_video_agent.api_provider import ApiCallError, ApiConfigError, ApiProvider
from story_video_agent.vision_provider import _extract_json_obj

from .remote_vlm_verify import apply_trial_env_overrides


SYSTEM_CRITIC = (
    "You are a football story-cut critic. Reply with strict JSON only. "
    "Judge narrative opening, pressure/buildup, turn, climax, ending, and transitions "
    "from the PROVIDED ordered frames of the finished cut. "
    "Do not invent media timestamps. Do not assume match names or scores. "
    "Distinguish observed vs uncertain. Never treat scoreboard alone as goal action."
)

SYSTEM_RP = (
    "You are a story Revision Planner. Reply with strict JSON only. "
    "Allowed actions: search_add, replace, trim, drop, reorder, keep, mark_unresolved. "
    "Protect goal_action segments unless overturn evidence is explicit. "
    "Do not invent media timestamps. New footage must cite source windows from evidence. "
    "No replay/slow-mo. Prefer mark_unresolved over guessing."
)

SYSTEM_VERIFIER = (
    "You are a dual-cut story verifier. Reply with strict JSON only. "
    "Compare baseline vs candidate using provided evidence. "
    "Refuse accept without video-backed evidence_of_improvement. "
    "Hard-veto replay, duplicate goals, missing protected goals, or narrative regression."
)


def build_capped_provider(
    *,
    max_calls: int = 5,
    max_cost_usd: float = 0.10,
    max_completion_tokens: int = 1024,
) -> ApiProvider:
    apply_trial_env_overrides(
        max_calls=max_calls,
        max_cost_usd=max_cost_usd,
        max_completion_tokens=max_completion_tokens,
        disable_thinking=True,
    )
    api = ApiProvider(
        require_real=True,
        force_mock=False,
        max_calls=int(max_calls),
        max_cost_usd=float(max_cost_usd),
        max_completion_tokens=int(max_completion_tokens),
        required_roles=("planner", "vision"),
    )
    for cfg in (api.configs or {}).values():
        cfg.max_retries = 0
    return api


def provider_usage(api: ApiProvider) -> Dict[str, Any]:
    summary = api.stats.summary() if hasattr(api, "stats") else {}
    return {
        "http_attempts": getattr(api, "_http_attempts", None),
        "max_calls": api.max_calls,
        "max_cost_usd": api.max_cost_usd,
        "est_cost_usd_real": summary.get("est_cost_usd_real"),
        "by_role": summary.get("by_role"),
        "cost_is_estimate_not_invoice_cap": True,
        "max_retries": 0,
    }


def _frame_paths_from_observe(obs: Mapping[str, Any], *, limit: int = 8) -> List[Dict[str, Any]]:
    frames: List[Dict[str, Any]] = []
    global_layer = (obs.get("layers") or {}).get("global") or {}
    for fr in global_layer.get("frames") or []:
        if isinstance(fr, dict) and fr.get("path"):
            frames.append(fr)
        if len(frames) >= limit:
            break
    if len(frames) < max(4, limit // 2):
        for para in (obs.get("layers") or {}).get("paragraph") or []:
            for fr in para.get("frames") or []:
                if isinstance(fr, dict) and fr.get("path"):
                    frames.append(fr)
                if len(frames) >= limit:
                    break
            if len(frames) >= limit:
                break
    return frames[:limit]


def run_vlm_story_critic(
    api: ApiProvider,
    *,
    observations: Mapping[str, Any],
    diagnosis: Mapping[str, Any],
    audit_dir: Path,
) -> Dict[str, Any]:
    frames = _frame_paths_from_observe(observations, limit=8)
    if len(frames) < 2:
        return {
            "ok": False,
            "error": "insufficient_frames_for_vlm_critic",
            "provider_mode": "skipped",
        }
    paths = [Path(f["path"]) for f in frames]
    fids = [str(f.get("frame_id") or f"f{i}") for i, f in enumerate(frames)]
    bindings = [{
        "frame_id": fids[i],
        "requested_media_sec": frames[i].get("requested_media_sec"),
        "actual_media_sec": frames[i].get("actual_media_sec"),
        "pts_status": frames[i].get("pts_status"),
    } for i in range(len(frames))]
    issues_brief = [
        {
            "issue_id": i.get("issue_id"),
            "category": i.get("category"),
            "severity": i.get("severity"),
            "evidence_sufficiency": i.get("evidence_sufficiency"),
            "narrative_problem": i.get("narrative_problem"),
            "story_time_range": i.get("story_time_range"),
            "segment_ids": i.get("segment_ids"),
        }
        for i in (diagnosis.get("issues") or [])[:12]
    ]
    prompt = (
        f"{SYSTEM_CRITIC}\n"
        f"Structural issues (not proof): {json.dumps(issues_brief, ensure_ascii=False)}\n"
        "Return JSON keys: opening, development, turn, climax, ending, transitions, "
        "confirmed_issues, uncertain_issues, derived_issues "
        "(list of {issue_id,severity,category,observation,narrative_problem,"
        "evidence_sufficiency='observed'| 'needs_video_verify', segment_ids, story_time_range}), "
        "overall_narrative_quality, confidence."
    )
    mock = {"opening": "unknown", "derived_issues": [], "confidence": 0}
    try:
        raw = api.vision_json(
            prompt=prompt,
            frame_paths=paths,
            frame_ids=fids,
            mock_obj=mock,
            frame_bindings=bindings,
        )
    except (ApiConfigError, ApiCallError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}", "provider_mode": "degraded"}
    content = str(raw.get("content") or "")
    parsed = None
    try:
        parsed = _extract_json_obj(content)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"parse:{type(exc).__name__}:{exc}",
            "provider_mode": raw.get("provider_mode"),
            "raw_excerpt": content[:1500],
            "est_cost_usd": raw.get("est_cost_usd"),
        }
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "vlm_story_critic.json").write_text(
        json.dumps({"raw_excerpt": content[:4000], "parsed": parsed, "usage": raw.get("usage")},
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    mode = str(raw.get("provider_mode") or "")
    if mode == "openai_compatible":
        mode = "real"
    return {
        "ok": mode == "real" and parsed is not None,
        "provider_mode": mode,
        "parsed": parsed,
        "derived_issues": list((parsed or {}).get("derived_issues") or []),
        "est_cost_usd": raw.get("est_cost_usd"),
        "usage": raw.get("usage"),
        "frame_ids": fids,
        "claims_full_video_watch": False,
        "observation_method": "ordered_multi_frame_vlm",
    }


def run_llm_revision_planner(
    api: ApiProvider,
    *,
    diagnosis: Mapping[str, Any],
    vlm_critic: Mapping[str, Any],
    protected_goal_ids: Sequence[str],
    audit_dir: Path,
) -> Dict[str, Any]:
    payload = {
        "issues": (diagnosis.get("issues") or [])[:12],
        "vlm_critic_summary": {
            k: (vlm_critic.get("parsed") or {}).get(k)
            for k in (
                "opening", "development", "turn", "climax", "ending",
                "transitions", "confirmed_issues", "uncertain_issues",
                "overall_narrative_quality", "confidence",
            )
        },
        "protected_goal_segment_ids": list(protected_goal_ids),
        "constraints": {
            "no_replay": True,
            "no_invented_timestamps": True,
            "protect_goals_without_overturn": True,
            "prefer_unresolved_over_guess": True,
        },
    }
    user = (
        "Given diagnosis + VLM critic summary, propose a story revision plan.\n"
        f"INPUT:\n{json.dumps(payload, ensure_ascii=False)}\n"
        "Return JSON: decision (KEEP|REVISE|UNRESOLVED), rationale, "
        "revision_intents (list with intent_id, action, target_segment_id?, role?, "
        "narrative_purpose, rationale, expected_improvement, risk, evidence_refs, "
        "anchor_id?, search_windows?). "
        "If VLM did not confirm a structural needs_video_verify issue, use UNRESOLVED "
        "or keep — do not invent edits."
    )
    mock = {"decision": "UNRESOLVED", "revision_intents": [], "rationale": "mock"}
    try:
        raw = api.revise_decision(
            system_prompt=SYSTEM_RP,
            user_prompt=user,
            mock_decision=mock,
        )
    except (ApiConfigError, ApiCallError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}", "provider_mode": "degraded"}
    content = str(raw.get("content") or "")
    parsed = None
    try:
        parsed = _extract_json_obj(content)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"parse:{type(exc).__name__}:{exc}",
            "provider_mode": raw.get("provider_mode"),
            "raw_excerpt": content[:1500],
        }
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "llm_revision_planner.json").write_text(
        json.dumps({"raw_excerpt": content[:4000], "parsed": parsed, "usage": raw.get("usage")},
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    mode = str(raw.get("provider_mode") or "")
    if mode == "openai_compatible":
        mode = "real"
    decision = str((parsed or {}).get("decision") or "UNRESOLVED").upper()
    if decision not in ("KEEP", "REVISE", "UNRESOLVED"):
        decision = "UNRESOLVED"
    return {
        "ok": mode == "real" and parsed is not None,
        "provider_mode": mode,
        "decision": decision,
        "revision_intents": list((parsed or {}).get("revision_intents") or []),
        "rationale": (parsed or {}).get("rationale"),
        "est_cost_usd": raw.get("est_cost_usd"),
        "usage": raw.get("usage"),
        "parsed": parsed,
    }


def run_llm_verifier(
    api: ApiProvider,
    *,
    baseline_summary: Mapping[str, Any],
    candidate_summary: Mapping[str, Any],
    edl_delta: Mapping[str, Any],
    video_probe: Mapping[str, Any],
    audit_dir: Path,
) -> Dict[str, Any]:
    user = (
        "Verify whether the candidate story cut is a real improvement.\n"
        f"baseline={json.dumps(baseline_summary, ensure_ascii=False)}\n"
        f"candidate={json.dumps(candidate_summary, ensure_ascii=False)}\n"
        f"edl_delta={json.dumps(edl_delta, ensure_ascii=False)}\n"
        f"video_probe={json.dumps(video_probe, ensure_ascii=False)}\n"
        "Return JSON: hard_vetoes (list), dimensions "
        "(story_element_coverage/narrative_coherence/image_content_quality/live_authenticity "
        "each with status improved|unchanged|regressed|NOT_EVALUATED, summary, evidence_refs), "
        "evidence_of_improvement (list of {claim, evidence_refs}), "
        "quality_delta_vs_baseline, accept_candidate (bool), reasons."
    )
    mock = {
        "hard_vetoes": [],
        "dimensions": {},
        "evidence_of_improvement": [],
        "quality_delta_vs_baseline": "NOT_EVALUATED",
        "accept_candidate": False,
    }
    try:
        raw = api.chat(
            role="planner",
            stats_role="verifier",
            messages=[
                {"role": "system", "content": SYSTEM_VERIFIER},
                {"role": "user", "content": user},
            ],
            cache_key=None,
            mock_content=json.dumps(mock, ensure_ascii=False),
            allow_degraded_fallback=False,
        )
    except (ApiConfigError, ApiCallError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}", "provider_mode": "degraded"}
    content = str(raw.get("content") or "")
    parsed = None
    try:
        parsed = _extract_json_obj(content)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"parse:{type(exc).__name__}:{exc}",
            "provider_mode": raw.get("provider_mode"),
            "raw_excerpt": content[:1500],
        }
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "llm_verifier.json").write_text(
        json.dumps({"raw_excerpt": content[:4000], "parsed": parsed, "usage": raw.get("usage")},
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    mode = str(raw.get("provider_mode") or "")
    if mode == "openai_compatible":
        mode = "real"
    return {
        "ok": mode == "real" and parsed is not None,
        "provider_mode": mode,
        "validated": parsed or {},
        "est_cost_usd": raw.get("est_cost_usd"),
        "usage": raw.get("usage"),
    }
