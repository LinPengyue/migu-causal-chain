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
from story_video_agent.vision_provider import EvidenceNormalizationError, _extract_json_obj

from .remote_vlm_verify import apply_trial_env_overrides


def _parse_model_json_lenient(content: str) -> Dict[str, Any]:
    """Parse model JSON; tolerate markdown fences / truncated trailing noise."""
    text = str(content or "").strip()
    if not text:
        raise EvidenceNormalizationError("empty VLM response", failure_status="empty_json")
    try:
        return _extract_json_obj(text)
    except EvidenceNormalizationError:
        # Fallback: largest {...} region (handles truncated tails better than hard fail).
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(text[start : end + 1])


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
    max_completion_tokens: int = 1200,
) -> ApiProvider:
    """Build real API provider with Thinking explicitly disabled in request bodies.

    Token ceiling targets short structured JSON (not Phase-5 512/1024 salvage caps).
    1200 is enough for semantic_evidence / revision intents without inviting long
    reasoning spills; budget remains hard-capped by max_cost_usd.
    """
    env_audit = apply_trial_env_overrides(
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
        # Force thinking-off on the actual EndpointConfig, not only via env.
        cfg.thinking_object_disabled = True
        cfg.send_thinking_params = False
        cfg.enable_thinking = None
        cfg.thinking_budget = None
        if getattr(cfg, "max_completion_tokens", None) is not None:
            cfg.max_completion_tokens = max(
                int(cfg.max_completion_tokens or 0), int(max_completion_tokens)
            )
    # Preflight: confirm request body actually carries thinking disabled.
    api._phase7_env_audit = env_audit  # type: ignore[attr-defined]
    api._phase7_request_preflight = {}  # type: ignore[attr-defined]
    for role, cfg in (api.configs or {}).items():
        _body, req_audit = api.build_chat_request_body(
            cfg,
            messages=[{"role": "user", "content": "preflight"}],
            temperature=0.0,
        )
        api._phase7_request_preflight[role] = {  # type: ignore[attr-defined]
            "model": cfg.model,
            "thinking_in_body": _body.get("thinking"),
            "max_tokens_in_body": _body.get("max_tokens"),
            "max_completion_tokens_in_body": _body.get("max_completion_tokens"),
            "enable_thinking_in_body": _body.get("enable_thinking"),
            "thinking_budget_in_body": _body.get("thinking_budget"),
            "request_audit": req_audit,
            "thinking_object_disabled_cfg": bool(cfg.thinking_object_disabled),
            "note": (
                "Paratera docs do not document thinking object; we still send "
                "thinking={type:disabled} via STORY_*_THINKING_OBJECT_DISABLED / "
                "video_rsi because prior Qwen runs returned text_tokens without "
                "reasoning_tokens when this was set."
            ),
        }
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
        "request_preflight": getattr(api, "_phase7_request_preflight", None),
        "env_thinking_overrides": getattr(api, "_phase7_env_audit", None),
    }


def _call_audit_from_raw(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """Compact per-call audit: model, thinking, tokens, finish_reason, cost."""
    usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
    details = usage.get("completion_tokens_details")
    if not isinstance(details, dict):
        details = {}
    req = raw.get("request_audit") if isinstance(raw.get("request_audit"), dict) else {}
    resp = raw.get("response_audit") if isinstance(raw.get("response_audit"), dict) else {}
    content = str(raw.get("content") or "")
    return {
        "model": raw.get("model"),
        "provider_mode": raw.get("provider_mode"),
        "logical_role": raw.get("logical_role") or req.get("role"),
        "thinking_object_disabled_sent": req.get("thinking_object_disabled_sent"),
        "thinking_params_sent": req.get("thinking_params_sent"),
        "enable_thinking_sent": req.get("enable_thinking_sent"),
        "thinking_budget_sent": req.get("thinking_budget_sent"),
        "token_param_sent": req.get("token_param_sent"),
        "token_limit_sent": req.get("token_limit_sent"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens")
        or resp.get("completion_tokens_reported"),
        "reasoning_tokens": details.get("reasoning_tokens")
        or resp.get("reasoning_tokens"),
        "text_tokens": details.get("text_tokens"),
        "finish_reason": raw.get("finish_reason") or resp.get("finish_reason"),
        "visible_output_chars": resp.get("visible_output_chars")
        if resp.get("visible_output_chars") is not None
        else len(content),
        "est_cost_usd": raw.get("est_cost_usd"),
        "http_ok": raw.get("http_ok"),
        "empty_content": raw.get("empty_content"),
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
    extra_frames: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Vision critic over ordered frames. Prefer short JSON with semantic_evidence.

    When ``extra_frames`` is provided (dense issue-window stills), those are preferred
    over sparse global samples so bridge/ending hypotheses get contiguous coverage.
    Still NOT a native continuous-video watch unless the provider ingested video bytes.
    """
    frames: List[Dict[str, Any]] = []
    if extra_frames:
        for fr in extra_frames:
            if isinstance(fr, dict) and fr.get("path"):
                frames.append(dict(fr))
            if len(frames) >= 10:
                break
    if len(frames) < 2:
        frames = _frame_paths_from_observe(observations, limit=8)
    if len(frames) < 2:
        return {
            "ok": False,
            "error": "insufficient_frames_for_vlm_critic",
            "provider_mode": "skipped",
        }
    paths = [Path(f["path"]) for f in frames]
    fids = []
    bindings = []
    for i, fr in enumerate(frames):
        fid = str(fr.get("frame_id") or f"f{i}")
        fids.append(fid)
        bindings.append(
            {
                "frame_id": fid,
                "requested_media_sec": fr.get("story_sec")
                or fr.get("requested_media_sec")
                or fr.get("actual_media_sec"),
                "actual_media_sec": fr.get("actual_media_sec") or fr.get("story_sec"),
                "pts_status": fr.get("pts_status") or "story_playback",
            }
        )
    issues_brief = [
        {
            "issue_id": i.get("issue_id"),
            "category": i.get("category"),
            "severity": i.get("severity"),
            "evidence_sufficiency": i.get("evidence_sufficiency"),
            "diagnosis_status": i.get("diagnosis_status"),
            "narrative_problem": i.get("narrative_problem"),
            "story_time_range": i.get("story_time_range"),
            "segment_ids": i.get("segment_ids"),
        }
        for i in (diagnosis.get("issues") or [])[:8]
        if str(i.get("evidence_sufficiency") or "") == "needs_video_verify"
        or str(i.get("diagnosis_status") or "") == "HYPOTHESIS_NEEDS_VIDEO"
    ] or [
        {
            "issue_id": i.get("issue_id"),
            "category": i.get("category"),
            "story_time_range": i.get("story_time_range"),
        }
        for i in (diagnosis.get("issues") or [])[:6]
    ]
    prompt = (
        f"{SYSTEM_CRITIC}\n"
        "You see ORDERED still frames from the finished story cut (NOT full native video).\n"
        "For each structural HYPOTHESIS, say whether VIDEO EVIDENCE supports a real story defect.\n"
        "Do NOT confirm from confidence alone. Cite ONLY provided frame_ids.\n"
        "Prefer SHORT JSON. Schema:\n"
        '{"semantic_evidence":[{'
        '"issue_id":str,"story_time":[lo,hi],"observed_fact":str,'
        '"defect_hypothesis":str,"confidence":0-1,'
        '"claims_story_defect":bool,'
        '"missing_story_information":str|null,"why_transition_breaks":str|null,'
        '"evidence_refs":[{"frame_id":str,"note":str}]'
        "}],"
        '"keep_story_if_no_defect":bool,"overall_narrative_quality":str}\n'
        "A large gap in source match time is NORMAL highlight editing, not a defect. "
        "Only claim a transition defect when the supplied frames reveal a specific "
        "missing event, game-state change, or emotional progression essential to understanding "
        "the next beat. For jump issues, fill missing_story_information and "
        "why_transition_breaks with CONCRETE observed facts; otherwise use null and "
        "claims_story_defect=false. Frame citations alone are insufficient.\n"
        "If transition already understandable, set claims_story_defect=false.\n"
        f"HYPOTHESES:{json.dumps(issues_brief, ensure_ascii=False)}\n"
        f"FRAME_IDS:{json.dumps(fids, ensure_ascii=False)}\n"
    )
    mock = {"semantic_evidence": [], "keep_story_if_no_defect": True, "confidence": 0}
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
    parse_error = None
    try:
        parsed = _parse_model_json_lenient(content)
    except Exception as exc:  # noqa: BLE001
        parse_error = f"parse:{type(exc).__name__}:{exc}"
        # Attempt salvage of complete semantic_evidence objects
        from .truncated_response_recovery import extract_complete_array_objects

        salv = extract_complete_array_objects(content, array_key="semantic_evidence")
        if salv.get("objects"):
            parsed = {
                "semantic_evidence": [w["object"] for w in salv["objects"]],
                "recovery": "RECOVERED_PARTIAL_RESPONSE",
            }
            parse_error = f"{parse_error};partial_semantic_evidence_recovered"
    call_audit = _call_audit_from_raw(raw)
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "vlm_story_critic.json").write_text(
        json.dumps(
            {
                "raw_excerpt": content[:8000],
                "parsed": parsed,
                "parse_error": parse_error,
                "usage": raw.get("usage"),
                "finish_reason": raw.get("finish_reason"),
                "sent_frame_ids": fids,
                "call_audit": call_audit,
                "request_audit": raw.get("request_audit"),
                "response_audit": raw.get("response_audit"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    mode = str(raw.get("provider_mode") or "")
    if mode == "openai_compatible":
        mode = "real"
    from .vlm_semantic_evidence import vlm_critic_to_observation_updates

    updates = vlm_critic_to_observation_updates(
        {
            "parsed": parsed or {},
            "observation_method": "dense_or_ordered_multi_frame_vlm",
            "claims_full_video_watch": False,
        },
        sent_frame_ids=fids,
        hypothesis_issues=issues_brief,
    )
    (audit_dir / "vlm_semantic_evidence.json").write_text(
        json.dumps(updates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if parsed is None and not updates.get("semantic_evidence"):
        return {
            "ok": False,
            "error": parse_error or "empty_parsed",
            "provider_mode": mode,
            "raw_excerpt": content[:1500],
            "est_cost_usd": raw.get("est_cost_usd"),
            "usage": raw.get("usage"),
            "finish_reason": raw.get("finish_reason"),
            "frame_ids": fids,
            "claims_full_video_watch": False,
        }
    return {
        "ok": mode == "real" and parsed is not None,
        "provider_mode": mode,
        "parsed": parsed,
        "derived_issues": updates.get("derived_issues") or [],
        "confirmed_issue_ids": updates.get("confirmed_issue_ids") or [],
        "semantic_evidence": updates.get("semantic_evidence") or [],
        "observation_updates": updates,
        "est_cost_usd": raw.get("est_cost_usd"),
        "usage": raw.get("usage"),
        "frame_ids": fids,
        "finish_reason": raw.get("finish_reason"),
        "parse_error": parse_error,
        "claims_full_video_watch": False,
        "observation_method": "dense_or_ordered_multi_frame_vlm",
        "call_audit": call_audit,
        "request_audit": raw.get("request_audit"),
        "response_audit": raw.get("response_audit"),
    }


def run_llm_revision_planner(
    api: ApiProvider,
    *,
    diagnosis: Mapping[str, Any],
    vlm_critic: Mapping[str, Any],
    protected_goal_ids: Sequence[str],
    audit_dir: Path,
    feedback_context: Optional[Mapping[str, Any]] = None,
    search_results: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    fb = None
    if feedback_context:
        fb = feedback_context.get("summary") or feedback_context.get("planner_context") or {
            "tried_revisions": (feedback_context.get("summary") or {}).get("tried_revisions")
            if isinstance(feedback_context.get("summary"), dict)
            else feedback_context.get("tried_revisions")
            or (feedback_context.get("records") or [])[:8],
            "forbid_identical_retry_without_new_evidence": True,
        }
        # Bound size — never dump raw chat logs.
        if isinstance(fb, dict):
            fb = {
                "n_records": fb.get("n_records") or fb.get("n") or len(fb.get("tried_revisions") or []),
                "tried_revisions": list(fb.get("tried_revisions") or [])[:8],
                "next_requirements": [
                    r.get("next_search_requirement")
                    for r in (fb.get("tried_revisions") or [])[:8]
                    if isinstance(r, dict) and r.get("next_search_requirement")
                ][:6],
                "opaque_reject_is_not_confirmed_negative": True,
                "never_permanently_ban_pts": True,
            }
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
        "phase8_feedback_context": fb,
        # The text Planner was previously blind to Search candidates. It must
        # see bounded source/issue/anchor options and whether triplet video
        # evidence actually supports story gain. Event heat is not quality.
        "search_candidates": [
            {
                "candidate_id": c.get("candidate_id"),
                "issue_id": c.get("issue_id"),
                "event_type": c.get("event_type"),
                "source_pts_start": c.get("source_pts_start"),
                "source_pts_end": c.get("source_pts_end"),
                "insert_after_segment_id": c.get("insert_after_segment_id"),
                "before_segment_id": c.get("before_segment_id"),
                "first_live_status": c.get("first_live_status"),
                "narrative_fit_status": c.get("narrative_fit_status"),
                "narrative_fit": c.get("narrative_fit"),
                "narrative_context": c.get("narrative_context"),
            }
            for c in ((search_results or {}).get("verified_candidates") or [])[:8]
            if isinstance(c, Mapping)
        ],
        "constraints": {
            "no_replay": True,
            "no_invented_timestamps": True,
            "protect_goals_without_overturn": True,
            "prefer_unresolved_over_guess": True,
            "do_not_repeat_same_pts_action_without_new_evidence": True,
            "do_not_force_insert_when_no_narrative_live": True,
            "first_live_is_not_narrative_fit": True,
            "never_insert_for_source_time_gap_alone": True,
            "require_review_supported_triplet_for_search_add": True,
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
        "or keep — do not invent edits. "
        "Do NOT propose search_add unless a candidate shows FIRST_LIVE_VERIFIED "
        "AND narrative_fit_status=REVIEW_SUPPORTED. A source-time jump is normal "
        "highlight compression. If no candidate has video-backed story improvement, "
        "use KEEP when the existing cut is understandable, otherwise UNRESOLVED. "
        "Never invent a narrative-fit review, source PTS, or candidate anchor. "
        "If phase8_feedback_context lists prior tried source_pts/actions, choose a "
        "DIFFERENT evidence-backed edit or UNRESOLVED; never treat unverified REJECT "
        "as a permanent negative sample."
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
        parsed = _parse_model_json_lenient(content)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"parse:{type(exc).__name__}:{exc}",
            "provider_mode": raw.get("provider_mode"),
            "raw_excerpt": content[:1500],
        }
    call_audit = _call_audit_from_raw(raw)
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "llm_revision_planner.json").write_text(
        json.dumps(
            {
                "raw_excerpt": content[:4000],
                "parsed": parsed,
                "usage": raw.get("usage"),
                "call_audit": call_audit,
                "request_audit": raw.get("request_audit"),
                "response_audit": raw.get("response_audit"),
                "finish_reason": raw.get("finish_reason"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
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
        "call_audit": call_audit,
        "request_audit": raw.get("request_audit"),
        "response_audit": raw.get("response_audit"),
        "finish_reason": raw.get("finish_reason"),
    }


def run_llm_verifier(
    api: ApiProvider,
    *,
    baseline_summary: Mapping[str, Any],
    candidate_summary: Mapping[str, Any],
    edl_delta: Mapping[str, Any],
    video_probe: Mapping[str, Any],
    audit_dir: Path,
    baseline_mp4: Optional[Path] = None,
    candidate_mp4: Optional[Path] = None,
    baseline_edl: Optional[Sequence[Mapping[str, Any]]] = None,
    candidate_edl: Optional[Sequence[Mapping[str, Any]]] = None,
    work_dir: Optional[Path] = None,
    revision_cases: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Dual-video vision Verifier. Text/EDL/ffprobe-only path is forbidden for ACCEPT.

    Prefer vision_json with aligned narrative frames. If videos/EDLs are missing,
    return NOT_EVALUATED (never authorize on summaries alone).
    """
    del baseline_summary, candidate_summary, edl_delta, video_probe  # not used for ACCEPT
    from .dual_video_vision_verifier import (
        run_dual_video_vision_verifier,
        text_only_verifier_forbidden_result,
    )

    if (
        baseline_mp4 is None
        or candidate_mp4 is None
        or baseline_edl is None
        or candidate_edl is None
        or not Path(baseline_mp4).is_file()
        or not Path(candidate_mp4).is_file()
    ):
        out = text_only_verifier_forbidden_result()
        audit_dir.mkdir(parents=True, exist_ok=True)
        (audit_dir / "llm_verifier.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return out

    result = run_dual_video_vision_verifier(
        api,
        baseline_mp4=Path(baseline_mp4),
        candidate_mp4=Path(candidate_mp4),
        baseline_edl=baseline_edl,
        candidate_edl=candidate_edl,
        work_dir=Path(work_dir or (audit_dir / "dual_frames")),
        audit_dir=audit_dir,
        revision_cases=revision_cases,
    )
    (audit_dir / "llm_verifier.json").write_text(
        json.dumps(
            {
                k: result.get(k)
                for k in (
                    "ok", "provider_mode", "error", "semantic_verification_status",
                    "ok_for_semantic_accept", "sent_frame_ids", "cited_sent_frame_ids",
                    "reasons", "est_cost_usd", "usage", "vision_backed", "validated",
                    "fullcut_semantic_screen",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return result
