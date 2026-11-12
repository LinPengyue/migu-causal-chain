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
    "You are a sports-broadcast story-cut critic. Reply with strict JSON only. "
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


def _story_frame_segment_id(
    timeline: Mapping[str, Any], story_sec: Any, *, seam_guard_sec: float = 0.4,
) -> Optional[str]:
    """Bind sampled finished-story frames only away from uncertain cut seams.

    Decoder/audio/transition timing can differ slightly from EDL timing. An
    exact boundary's EDL owner is well-defined, but a decoded frame at that
    nominal second must not certify visual content on either side.
    """
    from .story_timeline import story_time_to_media
    try:
        mapped = story_time_to_media(timeline, float(story_sec))
    except (TypeError, ValueError, OverflowError):
        return None
    if not mapped:
        return None
    seg = mapped.get("segment") or {}
    try:
        t = float(story_sec)
        begin, end = float(seg["story_in"]), float(seg["story_out"])
    except (TypeError, ValueError, KeyError):
        return None
    if t - begin < seam_guard_sec or end - t < seam_guard_sec:
        return None
    return str(mapped.get("segment_id")) or None


def select_critic_frame_bundle(
    observations: Mapping[str, Any],
    diagnosis: Mapping[str, Any],
    *,
    extra_frames: Optional[Sequence[Mapping[str, Any]]] = None,
    max_frames: int = 10,
) -> Dict[str, Any]:
    """Balance bounded critique across the whole *finished* story.

    Prior implementation sent dense frames from only the FIRST structure
    hypothesis, or the FIRST eight global frames (often missing the ending).
    Reuse already extracted fullcut global/paragraph frames, reserving a few
    slots for the dense issue, then spread the rest across distinct segments.
    No extra VLM call. Do not classify segments with missing visual coverage.
    """
    timeline = diagnosis.get("timeline") or {}
    active = list(timeline.get("segments") or [])
    media_ids = [
        str(x.get("segment_id")) for x in active
        if x.get("has_media_window") and x.get("segment_id")
    ]
    max_frames = max(0, min(int(max_frames), 10))
    if max_frames == 0:
        return {
            "frames": [], "coverage": {
                "covered_segment_ids": [], "unobserved_media_segment_ids": media_ids,
                "all_media_segments_covered": False, "claims_full_video_watch": False,
            }
        }

    def _bind(fr: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(fr, Mapping) or not fr.get("path"):
            return None
        item = dict(fr)
        t = item.get("story_sec")
        if t is None:
            # Legacy global/paragraph observation entries before P11.
            t = item.get("requested_media_sec")
        # Never trust an unvalidated user-provided segment_id; only map
        # finished-cut time against the EDL, excluding uncertain cut seams.
        item["segment_id"] = _story_frame_segment_id(timeline, t)
        return item

    layers = observations.get("layers") or {}
    raw_global = list((layers.get("global") or {}).get("frames") or [])
    raw_para = [
        fr for para in (layers.get("paragraph") or []) if isinstance(para, Mapping)
        for fr in (para.get("frames") or [])
    ]
    dense = [x for x in (_bind(fr) for fr in (extra_frames or [])) if x]
    global_candidates = [x for x in (_bind(fr) for fr in raw_global) if x]
    paragraph_candidates = [x for x in (_bind(fr) for fr in raw_para) if x]

    selected: List[Dict[str, Any]] = []
    seen_keys: set[str] = set()

    def add(fr: Mapping[str, Any]) -> bool:
        key = str(fr.get("frame_id") or fr.get("path") or "")
        if not key or key in seen_keys or len(selected) >= max_frames:
            return False
        selected.append(dict(fr))
        seen_keys.add(key)
        return True

    # Dense evidence still gets local continuity, but cannot monopolize the
    # entire Critic VLM packet. Spread samples over the detected issue window.
    dense_slots = min(len(dense), max(1, max_frames // 3)) if dense else 0
    if dense_slots:
        indices = (
            [len(dense) // 2] if dense_slots == 1 else
            [round(i * (len(dense) - 1) / (dense_slots - 1))
             for i in range(dense_slots)]
        )
        for i in indices:
            add(dense[i])

    available = max_frames - len(selected)
    # One representative frame per observed segment first; select from across
    # the full ordered timeline rather than always from the opening.
    distinct: Dict[str, Dict[str, Any]] = {}
    for fr in global_candidates + paragraph_candidates:
        sid = str(fr.get("segment_id") or "")
        if sid and sid not in distinct:
            distinct[sid] = fr
    ordered = [distinct[sid] for sid in
               [str(seg.get("segment_id")) for seg in active] if sid in distinct]
    if available > 0 and ordered:
        if len(ordered) <= available:
            picks = ordered
        elif available == 1:
            picks = [ordered[len(ordered) // 2]]
        else:
            picks = [ordered[round(i * (len(ordered) - 1) / (available - 1))]
                     for i in range(available)]
        for fr in picks:
            add(fr)

    # Remaining slots preserve end-to-end overview and useful source context
    # even when the timeline is missing from a legacy fixture.
    for pool in (global_candidates, paragraph_candidates, dense):
        for fr in pool:
            if len(selected) >= max_frames:
                break
            add(fr)
    # Selection intentionally reserves dense issue frames first, but the
    # model is told the resulting packet is ORDERED. Never send issue-late
    # frames before opening frames: this can manufacture visual jump/reversal
    # impressions and corrupt story-level transition judgment.
    def _story_clock(fr: Mapping[str, Any]) -> float:
        t = fr.get("story_sec")
        if t is None:
            t = fr.get("requested_media_sec")
        try:
            return float(t)
        except (TypeError, ValueError, OverflowError):
            return float("inf")

    selected.sort(key=_story_clock)
    covered = set(str(fr.get("segment_id")) for fr in selected if fr.get("segment_id"))
    return {
        "frames": selected,
        "coverage": {
            "schema": "v3a_vlm_critic_frame_coverage_v1",
            "sent_frame_count": len(selected),
            "media_segment_count": len(media_ids),
            "covered_segment_ids": [sid for sid in media_ids if sid in covered],
            "unobserved_media_segment_ids": [sid for sid in media_ids if sid not in covered],
            "all_media_segments_covered": bool(media_ids) and all(sid in covered for sid in media_ids),
            "claims_full_video_watch": False,
            "semantic_relevance_unobserved_is_unknown": True,
            "dense_issue_frames_available": len(dense),
            "global_frames_available": len(global_candidates),
            "paragraph_frames_available": len(paragraph_candidates),
        },
    }


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
    bundle = select_critic_frame_bundle(
        observations, diagnosis, extra_frames=extra_frames, max_frames=10,
    )
    frames = bundle["frames"]
    frame_coverage = bundle["coverage"]
    if len(frames) < 2:
        return {
            "ok": False,
            "error": "insufficient_frames_for_vlm_critic",
            "provider_mode": "skipped",
            "frame_coverage": frame_coverage,
        }
    paths = [Path(f["path"]) for f in frames]
    timeline = diagnosis.get("timeline") or {}
    fids = []
    bindings = []
    editorial_frame_bindings = []
    for i, fr in enumerate(frames):
        fid = str(fr.get("frame_id") or f"f{i}")
        fids.append(fid)
        story_sec_raw = fr.get("story_sec")
        if story_sec_raw is None:
            story_sec_raw = fr.get("requested_media_sec")
        editorial_frame_bindings.append({
            "frame_id": fid,
            "segment_id": _story_frame_segment_id(timeline, story_sec_raw),
            "story_sec": story_sec_raw,
            "path": str(fr.get("path") or ""),
        })
        bindings.append(
            {
                "frame_id": fid,
                "requested_media_sec": (
                    fr.get("story_sec") if fr.get("story_sec") is not None
                    else fr.get("requested_media_sec", fr.get("actual_media_sec"))
                ),
                "actual_media_sec": (
                    fr.get("actual_media_sec") if fr.get("actual_media_sec") is not None
                    else fr.get("story_sec")
                ),
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
    # P10-B: expose only Agent-inferred long-range story structure; no gold.
    graph_prompt = None
    if isinstance(diagnosis.get("agent_narrative_graph"), Mapping):
        from .story_inferred_narrative_graph import graph_planner_context
        try:
            graph_prompt = graph_planner_context(diagnosis["agent_narrative_graph"])
        except ValueError:
            graph_prompt = None
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
        '"keep_story_if_no_defect":bool,"overall_narrative_quality":str,'
        '"redundancy_claims":[{"target_segment_id":str,'
        '"comparison_segment_id":str,"observed_fact":str,'
        '"why_redundant":str,"evidence_refs":[{"frame_id":str,"note":str}]}],'
        '"irrelevance_claims":[{"target_segment_id":str,'
        '"observed_content":str,"why_not_support_story":str,'
        '"why_removal_may_preserve_continuity":str,'
        '"evidence_refs":[{"frame_id":str,"note":str}]}]}\n'
        "Redundancy_claims is OPTIONAL (max ONE). Only report a redundant non-goal "
        "scene when sent frames from TWO DIFFERENT EDL segments concretely show "
        "the same narrative information, and identify the exact expendable target. "
        "Do not declare redundant because two clips show the same team or pitch. "
        "Never target a goal, scoreboard, title, or ending; cite both segments.\n"
        "Irrelevance_claims is OPTIONAL (max ONE) and is DIFFERENT from repeated footage: "
        "a unique event may add no information to the specific narrative goal. "
        "Only hypothesize this for a non-protected TARGET when you have ACTUAL "
        "cited frames from the exact preceding, target and following EDL media segments. "
        "Describe the visible target, why it does not support this story, and "
        "why omitting it might preserve before-to-after continuity. Never claim "
        "that sparse frames prove the whole segment is useless, or that a goal "
        "action/scoreboard should be removed. No citations means NO claim.\n"
        "A large gap in source match time is NORMAL highlight editing, not a defect. "
        "Only claim a transition defect when the supplied frames reveal a specific "
        "missing event, game-state change, or emotional progression essential to understanding "
        "the next beat. For jump issues, fill missing_story_information and "
        "why_transition_breaks with CONCRETE observed facts; otherwise use null and "
        "claims_story_defect=false. Frame citations alone are insufficient.\n"
        "If transition already understandable, set claims_story_defect=false.\n"
        f"HYPOTHESES:{json.dumps(issues_brief, ensure_ascii=False)}\n"
        f"FRAME_IDS:{json.dumps(fids, ensure_ascii=False)}\n"
        f"FRAME_TO_EDL:{json.dumps([{'frame_id': x['frame_id'], 'segment_id': x.get('segment_id')} for x in editorial_frame_bindings], ensure_ascii=False)}\n"
        f"AGENT_NARRATIVE_GRAPH_HINTS:{json.dumps(graph_prompt, ensure_ascii=False)}\n"
        "Graph hints identify where to LOOK for missing or repeated narrative "
        "information, never evidence of a defect by themselves. Observe supplied "
        "frames and report concrete match-state transitions, not assumed causal claims.\n"
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
                "frame_coverage": frame_coverage,
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
    from .story_editorial_redundancy import validate_editorial_redundancy_claims

    editorial_result = validate_editorial_redundancy_claims(
        (parsed or {}).get("redundancy_claims") or []
        if mode == "real" and parsed is not None and not parse_error else [],
        frame_bindings=editorial_frame_bindings,
        timeline=timeline,
        protected_goal_ids=diagnosis.get("protected_goal_segment_ids") or [],
    )
    (audit_dir / "vlm_editorial_redundancy_candidates.json").write_text(
        json.dumps(editorial_result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    from .story_editorial_redundancy import validate_editorial_irrelevance_claims
    irrelevance_result = validate_editorial_irrelevance_claims(
        (parsed or {}).get("irrelevance_claims") or []
        if mode == "real" and parsed is not None and not parse_error else [],
        frame_bindings=editorial_frame_bindings,
        timeline=timeline,
        protected_goal_ids=diagnosis.get("protected_goal_segment_ids") or [],
    )
    (audit_dir / "vlm_editorial_irrelevance_hypotheses.json").write_text(
        json.dumps(irrelevance_result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
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
            "frame_coverage": frame_coverage,
            "claims_full_video_watch": False,
        }
    return {
        "ok": mode == "real" and parsed is not None,
        "provider_mode": mode,
        "parsed": parsed,
        "derived_issues": (
            list(updates.get("derived_issues") or [])
            + list(editorial_result.get("issues") or [])
            + list(irrelevance_result.get("issues") or [])
        ),
        "editorial_redundancy_candidates": editorial_result,
        "editorial_irrelevance_hypotheses": irrelevance_result,
        "confirmed_issue_ids": updates.get("confirmed_issue_ids") or [],
        "semantic_evidence": updates.get("semantic_evidence") or [],
        "observation_updates": updates,
        "est_cost_usd": raw.get("est_cost_usd"),
        "usage": raw.get("usage"),
        "frame_ids": fids,
        "frame_coverage": frame_coverage,
        "finish_reason": raw.get("finish_reason"),
        "parse_error": parse_error,
        "claims_full_video_watch": False,
        "observation_method": "dense_or_ordered_multi_frame_vlm",
        "call_audit": call_audit,
        "request_audit": raw.get("request_audit"),
        "response_audit": raw.get("response_audit"),
    }


def _planner_video_critic_context(
    critic: Mapping[str, Any],
    *,
    max_items: int = 4,
) -> Dict[str, Any]:
    """Pass bounded *validated* visual observations to the text Planner.

    Earlier handoff included overall-quality text but dropped issue-level
    observations and explicit KEEP findings. Sampled stills remain advisory.
    """
    parsed = critic.get("parsed") or {}
    if not isinstance(parsed, Mapping):
        parsed = {}
    coverage = critic.get("frame_coverage") or {}
    if not isinstance(coverage, Mapping):
        coverage = {}
    sent_ids = {str(x) for x in critic.get("frame_ids") or [] if x}
    real = (
        critic.get("ok") is True
        and str(critic.get("provider_mode") or "") == "real"
        and bool(sent_ids)
    )
    rows: List[Dict[str, Any]] = []
    if real:
        # Only citation-normalized observations, never raw model frame_ids.
        for item in critic.get("semantic_evidence") or []:
            if not isinstance(item, Mapping):
                continue
            cited = [
                str(x) for x in item.get("frame_refs") or []
                if x and str(x) in sent_ids
            ]
            if not cited:
                continue
            rows.append({
                "issue_id": item.get("issue_id"),
                "evidence_tier": item.get("evidence_tier"),
                "frame_refs": cited[:6],
                "observed_fact": str(item.get("observed_fact") or "")[:420],
                "defect_hypothesis": str(item.get("defect_hypothesis") or "")[:420],
                "missing_story_information": str(
                    item.get("missing_story_information") or ""
                )[:260],
                "why_transition_breaks": str(
                    item.get("why_transition_breaks") or ""
                )[:260],
                "supports_original_issue": item.get("supports_original_issue") is True,
            })
            if len(rows) >= max_items:
                break
    return {
        "observation_status": "REAL_SAMPLED_FRAMES" if real else "UNAVAILABLE",
        "keep_story_if_no_defect_in_observed_frames": (
            parsed.get("keep_story_if_no_defect")
            if real and isinstance(parsed.get("keep_story_if_no_defect"), bool)
            else None
        ),
        "overall_narrative_quality_model_text": (
            str(parsed.get("overall_narrative_quality") or "")[:240] if real else ""
        ),
        "visual_evidence_with_checkable_frame_ids": rows,
        "covered_segment_ids": (
            list(coverage.get("covered_segment_ids") or [])[:24] if real else []
        ),
        "unobserved_media_segment_ids": (
            list(coverage.get("unobserved_media_segment_ids") or [])[:24]
            if real else []
        ),
        "claims_full_video_watch": False,
        "do_not_infer_unobserved_content_from_absence_of_claims": True,
        "model_verdict_does_not_certify_video_quality": True,
    }


def _planner_edit_function_hints(
    diagnosis: Mapping[str, Any],
    protected_goal_ids: Sequence[str],
    *,
    max_items: int = 12,
) -> List[Dict[str, Any]]:
    """Describe editable clips and their neighbors; roles are hypotheses only."""
    segments = [
        x for x in ((diagnosis.get("timeline") or {}).get("segments") or [])
        if isinstance(x, Mapping) and x.get("has_media_window")
    ]
    protected = {str(x) for x in protected_goal_ids}
    result: List[Dict[str, Any]] = []
    for i, seg in enumerate(segments):
        sid = str(seg.get("segment_id") or "")
        role = str(seg.get("role") or "")
        if not sid or sid in protected or any(
            x in role.lower()
            for x in ("goal_action", "scoreboard", "title", "ending", "wrap")
        ):
            continue
        before = segments[i - 1] if i > 0 else {}
        after = segments[i + 1] if i + 1 < len(segments) else {}
        result.append({
            "target_segment_id": sid,
            "target_role_hint": role,
            "before_role_hint": before.get("role"),
            "after_role_hint": after.get("role"),
            "duration_sec": round(
                float(seg.get("story_out") or 0.0)
                - float(seg.get("story_in") or 0.0), 2
            ),
            "narrative_function_status": "UNVERIFIED_ROLE_HINT",
            "question_before_drop_or_trim": (
                "What setup, effort, tension, anticipation or causal state "
                "would be lost, and is that information visible in adjacent clips?"
            ),
        })
        if len(result) >= max_items:
            break
    return result


def run_llm_revision_planner(
    api: ApiProvider,
    *,
    diagnosis: Mapping[str, Any],
    vlm_critic: Mapping[str, Any],
    protected_goal_ids: Sequence[str],
    audit_dir: Path,
    feedback_context: Optional[Mapping[str, Any]] = None,
    search_results: Optional[Mapping[str, Any]] = None,
    allow_exploratory_proposals: bool = False,
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
    # Authenticated non-additive defects are sparse and must not disappear
    # behind twelve source-time-gap hypotheses. Preserve exact segment
    # targets, while leaving model-only unsupported claims unconfirmed.
    all_issues = [
        i for i in (diagnosis.get("issues") or [])
        if isinstance(i, Mapping)
    ]
    prioritized_issues = sorted(
        all_issues,
        key=lambda i: (
            0 if (
                i.get("category") in ("redundancy", "narrative_order", "replay_risk")
                and (i.get("story_defect_confirmed") is True
                     or i.get("diagnosis_status") in
                     ("CONFIRMED_STORY_DEFECT", "CONFIRMED_STRUCTURE_DEFECT"))
            ) else 1,
            0 if i.get("severity") in ("major", "critical") else 1,
        ),
    )
    graph_for_planner = None
    if isinstance(diagnosis.get("agent_narrative_graph"), Mapping):
        from .story_inferred_narrative_graph import graph_planner_context
        try:
            graph_for_planner = graph_planner_context(diagnosis["agent_narrative_graph"])
        except ValueError:
            graph_for_planner = None
    payload = {
        "agent_inferred_narrative_graph": graph_for_planner,
        "issues": prioritized_issues[:12],
        "edl_segment_refs": [
            {
                "segment_id": x.get("segment_id"),
                "role": x.get("role"),
                "source_window": [x.get("media_in"), x.get("media_out")],
            }
            for x in ((diagnosis.get("timeline") or {}).get("segments") or [])[:60]
            if isinstance(x, Mapping)
        ],
        "vlm_critic_summary": {
            k: (vlm_critic.get("parsed") or {}).get(k)
            for k in (
                "opening", "development", "turn", "climax", "ending",
                "transitions", "confirmed_issues", "uncertain_issues",
                "overall_narrative_quality", "confidence",
            )
        },
        "video_critic_observations": _planner_video_critic_context(vlm_critic),
        "existing_clip_narrative_function_hints": _planner_edit_function_hints(
            diagnosis, protected_goal_ids,
        ),
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
        "phase10c_exploratory_opt_in": bool(allow_exploratory_proposals),
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
        "Use video_critic_observations to distinguish a cited observed fact, "
        "a merely hypothesized defect, and an observed KEEP finding. "
        "No-defect in a sampled frame packet is not proof that unobserved clips "
        "are good. Existing-clip narrative-function hints are structural only; "
        "before proposing a removal, consider the anticipation and causal "
        "context that viewers could lose. Do not optimize duration alone. "
        "If VLM did not confirm a structural needs_video_verify issue, use UNRESOLVED "
        "or keep — do not invent edits. "
        "Prefer ONE evidence-backed edit per iteration. If a confirmed "
        "redundancy issue explicitly names preferred_drop_segment_id, consider "
        "dropping that exact non-goal cut before searching for more footage; "
        "explain which story information is duplicated and the expected change "
        "in coherence/pacing. Only cite existing segment IDs in EDL_SEGMENT_REFS "
        "and only use issue_id from supplied diagnosis. "
        "Do NOT invent drop targets, source PTS, trim bounds, or confirmation status. "
        "The Agent narrative graph is a STRUCTURAL HYPOTHESIS of long-range "
        "state and role relationships; use it to reason about what needs to be "
        "observed next, not as an authenticated causal fact or confirmed defect. "
        "An unconfirmed semantic hypothesis is not an executable edit. "
        "Do NOT propose search_add unless a candidate shows FIRST_LIVE_VERIFIED "
        "AND narrative_fit_status=REVIEW_SUPPORTED. A source-time jump is normal "
        "highlight compression. If no candidate has video-backed story improvement, "
        "use KEEP when the existing cut is understandable, otherwise UNRESOLVED. "
        "Never invent a narrative-fit review, source PTS, or candidate anchor. "
        "If phase8_feedback_context lists prior tried source_pts/actions, choose a "
        "DIFFERENT evidence-backed edit or UNRESOLVED; never treat unverified REJECT "
        "as a permanent negative sample."
    )
    if allow_exploratory_proposals:
        user += (
            "\nPHASE10-C OPTIONAL EXPLORATION (SEPARATE, NON-RELEASE OUTPUT): "
            "Even when the formal decision is KEEP/UNRESOLVED, you MAY give up to "
            "ONE conditional idea in exploratory_intents, or [] when none is "
            "worth testing. This is a story-quality HYPOTHESIS, not a confirmed "
            "defect and NOT a normal revision_intent. Return "
            "'exploratory_intents':[{'action':'drop|trim|reorder',"
            "'target_segment_id':exact_existing_id,'hypothesis':meaningful_story_problem,"
            "'expected_effect':expected_coherence_or_pacing_gain,"
            "'risk':what_story_information_might_be_lost,"
            "'media_in':number_if_trim,'media_out':number_if_trim,"
            "'insert_before_segment_id':id_if_reorder}]. "
            "Use video_critic_observations: a frame-cited KEEP/no-defect observation "
            "is evidence against blindly dropping a clip, NOT proof that all unseen "
            "footage is good. For each deletion or trim, explicitly weigh lost "
            "narrative function against information gain. The clip role hints are "
            "not video proof or authorization. Do not drop only to shorten runtime. "
            "If visual comparison is missing, prefer [] to unsupported deletion. "
            "Assess the narrative FUNCTION of each candidate in the FULL "
            "before-target-after sequence, not merely whether it adds a new "
            "score or factual event. A pursuit, pressure, effort or anticipation "
            "shot can be essential to understanding why a later turn feels "
            "earned, even when the scoreboard already states the deficit. "
            "Do NOT prefer buildup/bridge removal by default. Before proposing "
            "drop/trim, explain what motivational or temporal information the "
            "audience loses, why adjacent clips can or cannot carry that "
            "function, and what video evidence is still missing. If uncertain, "
            "return [] rather than treating shorter runtime as better pacing. "
            "Never propose protected goal action, scoreboard, opening/title or ending. "
            "For trim, only use an EXISTING EDL source window and choose a "
            "strictly contained sub-window; never invent extra source footage. "
            "If evidence insufficient for any reasonable idea, return []. "
            "Exploratory suggestions are merely independent render candidates "
            "and never change formal KEEP/UNRESOLVED or best version."
        )
    mock = {
        "decision": "UNRESOLVED", "revision_intents": [],
        "exploratory_intents": [], "rationale": "mock",
    }
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
        "exploratory_intents": (
            list((parsed or {}).get("exploratory_intents") or [])[:1]
            if allow_exploratory_proposals
            and isinstance((parsed or {}).get("exploratory_intents"), list)
            else []
        ),
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
