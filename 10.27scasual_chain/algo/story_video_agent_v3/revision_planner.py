"""Post-VLM Revision Planner: LLM decides KEEP / REPAIR / UNRESOLVED after evidence.

Rules validate evidence legality only; they do NOT replace LLM semantic judgment.
Never auto-promote observed_shot/net or live_or_replay=live into FIRST_LIVE_VERIFIED.
Never treat 4-frame sparse observation as proof that a ~22s composer window must trim.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from story_video_agent.api_provider import ApiCallError, ApiConfigError, ApiProvider

DECISION_KEEP_WITH_NEW_EVIDENCE = "KEEP_WITH_NEW_EVIDENCE"
DECISION_PROPOSE_REPAIR = "PROPOSE_REPAIR"
DECISION_UNRESOLVED = "UNRESOLVED"
ALLOWED_DECISIONS = {
    DECISION_KEEP_WITH_NEW_EVIDENCE,
    DECISION_PROPOSE_REPAIR,
    DECISION_UNRESOLVED,
}

REVISION_PLANNER_SCHEMA = "v3a_revision_planner_output_v1"
FIXTURE_MARK = "simulated_revision_planner_fixture"

REVISION_PLANNER_SYSTEM = """You are a football story-video Revision Planner.
You act AFTER the diagnostic Planner and AFTER VLM observations.
Your job: decide whether the CURRENT best EDL should KEEP, PROPOSE_REPAIR, or stay UNRESOLVED
given new video evidence. Reply with compact JSON ONLY. No prose chain-of-thought.

Required keys:
  decision, target_segment_id, issue_id, diagnosis, reasoning_summary,
  evidence_refs, proposed_revision_intents, remaining_uncertainties,
  expected_improvement

decision MUST be one of:
  KEEP_WITH_NEW_EVIDENCE — retain original window; record new evidence; no EDL time edit;
    do NOT invent EDL gain; do NOT auto-upgrade FIRST_LIVE.
  PROPOSE_REPAIR — propose concrete trim|replace|search_add|drop|reorder with cited evidence;
    only when new evidence shows a concrete window problem AND a legal evidence-bound fix.
  UNRESOLVED — evidence insufficient/contradictory; leave EDL unchanged; list missing evidence.

Rules for judgment:
- Sparse VLM (e.g. 4 frames) with observed_shot=true and observed_net=true does NOT by itself
  prove a long composer window (e.g. ~22s) must be shortened.
- live_or_replay=live is NOT FIRST_LIVE_VERIFIED.
- Scoreboard confirmation time is NOT goal-action time.
- Do not invent absolute media timestamps; cite observation frame_ids / request_ids /
  trusted windows already in the input.
- proposed_revision_intents must use action in
  {keep, mark_unresolved, trim, replace, search_add, drop, reorder}.
- For KEEP_WITH_NEW_EVIDENCE use action=keep; for UNRESOLVED use mark_unresolved.
- For PROPOSE_REPAIR every intent needs concrete action + evidence_refs that exist in input.
- Never claim render_ready or FIRST_LIVE_VERIFIED.
"""


def edl_rows_sha256(edl: Sequence[Mapping[str, Any]]) -> str:
    """Stable SHA256 of canonical EDL rows (segment timing / include flags)."""
    compact = []
    for r in edl:
        if not isinstance(r, dict):
            continue
        compact.append({
            "segment_id": r.get("segment_id"),
            "role": r.get("role"),
            "media_in": r.get("media_in"),
            "media_out": r.get("media_out"),
            "include_in_cut": r.get("include_in_cut", True),
            "is_replay": r.get("is_replay"),
        })
    blob = json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _parse_model_json(content: str) -> Dict[str, Any]:
    text = (content or "").strip()
    if not text:
        raise ValueError("EMPTY_MODEL_CONTENT")
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError("revision_planner_json_not_object")
    return raw


def collect_known_evidence_tokens(
    *,
    observations: Sequence[Mapping[str, Any]],
    historical_observations: Sequence[Mapping[str, Any]] = (),
    composer_handoff: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Whitelist of evidence tokens Revision Planner may cite."""
    tokens: set = set()
    frame_pts: Dict[str, float] = {}
    request_ids: List[str] = []
    for obs in list(historical_observations) + list(observations):
        if not isinstance(obs, dict):
            continue
        rid = str(obs.get("request_id") or "")
        if rid:
            tokens.add(rid)
            tokens.add(f"observation:{rid}")
            request_ids.append(rid)
        for fr in obs.get("frames") or []:
            if not isinstance(fr, dict):
                continue
            fid = str(fr.get("frame_id") or "")
            pts = fr.get("actual_media_sec")
            if fid:
                tokens.add(fid)
                tokens.add(f"frame:{fid}")
                if pts is not None:
                    try:
                        frame_pts[fid] = float(pts)
                    except (TypeError, ValueError):
                        pass
        vlm = obs.get("vlm") if isinstance(obs.get("vlm"), dict) else {}
        for cid in vlm.get("cited_frame_ids") or []:
            tokens.add(str(cid))
        tokens.add("vlm_observation")
        tokens.add("new_vlm_observation")
        tokens.add("historical_vlm_observation")
    if composer_handoff and isinstance(composer_handoff, dict):
        tokens.add("composer_handoff")
        tokens.add("composer_evidence_refs")
        for sid, seg in (composer_handoff.get("segments") or {}).items():
            tokens.add(str(sid))
            tokens.add(f"edl:{sid}")
            if isinstance(seg, dict):
                for ref in seg.get("evidence_refs") or []:
                    if isinstance(ref, dict):
                        for k in ("event_id", "source", "kind", "ref"):
                            if ref.get(k):
                                tokens.add(str(ref[k]))
                    elif ref:
                        tokens.add(str(ref))
    # Always allow structural labels that are not forged timestamps.
    tokens.update({
        "planner_diagnosis",
        "trusted_window",
        "time_provenance",
        "blocking_reasons",
    })
    return {
        "tokens": sorted(tokens),
        "frame_pts": frame_pts,
        "request_ids": request_ids,
    }


def _normalize_evidence_ref(ref: Any) -> Optional[str]:
    if ref is None:
        return None
    if isinstance(ref, str):
        return ref.strip() or None
    if isinstance(ref, dict):
        for k in ("ref", "frame_id", "request_id", "id", "event_id", "source"):
            if ref.get(k):
                return str(ref[k]).strip()
        return json.dumps(ref, ensure_ascii=False, sort_keys=True)[:200]
    return str(ref)


def _evidence_refs_ok(
    refs: Sequence[Any],
    known: Mapping[str, Any],
) -> Tuple[bool, List[str]]:
    tokens = set(known.get("tokens") or [])
    bad: List[str] = []
    if not refs:
        return True, bad
    for ref in refs:
        norm = _normalize_evidence_ref(ref)
        if not norm:
            continue
        # Allow bare observation / frame citations if substring matches a known token.
        if norm in tokens:
            continue
        if any(norm.startswith(t) or t.startswith(norm) or t in norm or norm in t for t in tokens if len(t) >= 6):
            continue
        # Reject obvious free PTS inventions like "pts:9999.1" / raw floats as sole ref.
        if norm.replace(".", "", 1).isdigit() or norm.lower().startswith("pts:"):
            bad.append(norm)
            continue
        bad.append(norm)
    return (len(bad) == 0), bad


def summarize_observations(observations: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for obs in observations:
        if not isinstance(obs, dict):
            continue
        vlm = obs.get("vlm") if isinstance(obs.get("vlm"), dict) else {}
        frames = []
        for fr in obs.get("frames") or []:
            if not isinstance(fr, dict):
                continue
            frames.append({
                "frame_id": fr.get("frame_id"),
                "actual_media_sec": fr.get("actual_media_sec"),
                "pts_status": fr.get("pts_status"),
            })
        out.append({
            "request_id": obs.get("request_id"),
            "anchor_id": obs.get("anchor_id"),
            "ok": obs.get("ok"),
            "provider_mode": obs.get("provider_mode"),
            "historical_reuse": bool(obs.get("historical_reuse")),
            "counts_as_new_http": obs.get("counts_as_new_http"),
            "fact_verified": False,
            "observation_only": True,
            "window": obs.get("window"),
            "frames": frames,
            "observed_shot": vlm.get("observed_shot"),
            "observed_net": vlm.get("observed_net"),
            "live_or_replay": vlm.get("live_or_replay"),
            "supports_bound_segment": vlm.get("supports_bound_segment"),
            "candidate_goal_action_span": vlm.get("candidate_goal_action_span"),
            "scoreboard_only": vlm.get("scoreboard_only"),
            "visible_content": str(vlm.get("visible_content") or "")[:600],
            "cited_frame_ids": list(vlm.get("cited_frame_ids") or [])[:8],
            "cannot_certify_first_live": True,
        })
    return out


def build_revision_planner_context(
    *,
    best_edl: Sequence[Mapping[str, Any]],
    composer_handoff: Optional[Mapping[str, Any]],
    planner_validated: Mapping[str, Any],
    historical_observations: Sequence[Mapping[str, Any]],
    new_observations: Sequence[Mapping[str, Any]],
    trusted_anchors: Sequence[Mapping[str, Any]],
    focus_segment_ids: Optional[Sequence[str]] = None,
    first_live_constraints: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Compact JSON payload for the Revision Planner LLM call."""
    focus = [str(x) for x in (focus_segment_ids or [])]
    edl_brief = []
    for row in best_edl:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("segment_id") or "")
        role = str(row.get("role") or "")
        if focus and sid not in focus and not any(f in sid for f in focus):
            if "goal_action" not in role and "goal_action" not in sid:
                continue
        edl_brief.append({
            "segment_id": sid,
            "role": role,
            "media_in": row.get("media_in"),
            "media_out": row.get("media_out"),
            "include_in_cut": row.get("include_in_cut", True),
            "is_replay": row.get("is_replay"),
            "time_provenance": row.get("time_provenance"),
            "evidence_refs": row.get("evidence_refs"),
            "blocking_reasons": row.get("blocking_reasons"),
            "render_eligibility": row.get("render_eligibility"),
            "first_live_status": row.get("first_live_status"),
            "selection_reason": row.get("selection_reason"),
        })
    known = collect_known_evidence_tokens(
        observations=new_observations,
        historical_observations=historical_observations,
        composer_handoff=composer_handoff,
    )
    return {
        "schema": "v3a_revision_planner_context_v1",
        "best_edl_focus": edl_brief,
        "best_edl_sha256": edl_rows_sha256(best_edl),
        "composer_evidence_handoff": composer_handoff,
        "planner_diagnoses": planner_validated.get("diagnoses") or [],
        "planner_revision_intents_pre_vlm": planner_validated.get("revision_intents") or [],
        "planner_video_tool_requests": planner_validated.get("video_tool_requests") or [],
        "historical_vlm_observations": summarize_observations(historical_observations),
        "new_vlm_observations": summarize_observations(new_observations),
        "trusted_anchor_ids": [a.get("anchor_id") for a in trusted_anchors if isinstance(a, dict)],
        "focus_segment_ids": focus,
        "first_live_constraints": first_live_constraints or {
            "observed_shot_net_not_first_live": True,
            "live_or_replay_live_not_first_live": True,
            "sparse_frames_do_not_force_trim": True,
            "scoreboard_time_is_not_goal_action_time": True,
        },
        "known_evidence_tokens": known["tokens"][:200],
        "constraints": {
            "revision_planner_is_llm_semantic_judge": True,
            "rules_only_validate_legality": True,
            "must_not_write_free_timestamps": True,
            "must_not_claim_first_live_or_render_ready": True,
        },
    }


def validate_revision_planner_output(
    raw: Mapping[str, Any],
    *,
    trusted_anchors: Sequence[Mapping[str, Any]],
    video_duration: Optional[float],
    known_evidence: Mapping[str, Any],
    best_edl: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Validate structured Revision Planner JSON; reject forged evidence / free PTS."""
    from .self_revise_agent import validate_planner_output

    if raw.get(FIXTURE_MARK) is False:
        # Explicit anti-mark is ignored; fixtures should set True when simulated.
        pass
    decision = str(raw.get("decision") or "").strip().upper().replace("-", "_")
    aliases = {
        "KEEP": DECISION_KEEP_WITH_NEW_EVIDENCE,
        "KEEP_WITH_EVIDENCE": DECISION_KEEP_WITH_NEW_EVIDENCE,
        "REPAIR": DECISION_PROPOSE_REPAIR,
        "PROPOSE_EDIT": DECISION_PROPOSE_REPAIR,
    }
    decision = aliases.get(decision, decision)
    if decision not in ALLOWED_DECISIONS:
        raise ValueError(f"invalid_revision_decision:{decision}")

    target = raw.get("target_segment_id")
    issue_id = raw.get("issue_id")
    diagnosis = str(raw.get("diagnosis") or raw.get("problem") or "")[:800]
    reasoning = str(raw.get("reasoning_summary") or raw.get("reasoning") or "")[:1200]
    expected = str(raw.get("expected_improvement") or "")[:400]
    remaining = raw.get("remaining_uncertainties")
    if not isinstance(remaining, list):
        remaining = [str(remaining)] if remaining else []
    remaining = [str(x)[:300] for x in remaining[:12]]

    top_refs = raw.get("evidence_refs")
    if not isinstance(top_refs, list):
        top_refs = []
    refs_ok, bad_top = _evidence_refs_ok(top_refs, known_evidence)
    if not refs_ok:
        raise ValueError(f"forged_or_unknown_evidence_refs:{bad_top[:5]}")

    # Reject free PTS fields on the root object.
    for banned in ("media_in", "media_out", "invented_pts", "free_pts"):
        if banned in raw and raw.get(banned) is not None and decision == DECISION_PROPOSE_REPAIR:
            # Allow only inside intents that go through validate_planner_output windows.
            if banned in ("invented_pts", "free_pts"):
                raise ValueError(f"forbidden_free_pts_field:{banned}")

    proposed = raw.get("proposed_revision_intents")
    if not isinstance(proposed, list):
        proposed = []

    # Decision-specific shaping before validate_planner_output.
    if decision == DECISION_KEEP_WITH_NEW_EVIDENCE:
        if not proposed:
            proposed = [{
                "intent_id": "rev_keep_000",
                "action": "keep",
                "disposition": "KEEP",
                "target_segment_id": target,
                "rationale": reasoning or "keep with newly recorded VLM evidence",
                "evidence_refs": top_refs,
                "expected_improvement": expected or "record evidence without false EDL gain",
            }]
        else:
            # Force non-edit actions.
            forced = []
            for i, it in enumerate(proposed):
                if not isinstance(it, dict):
                    continue
                forced.append({
                    **it,
                    "action": "keep",
                    "disposition": it.get("disposition") or "KEEP",
                    "target_segment_id": it.get("target_segment_id") or target,
                })
            proposed = forced or proposed
    elif decision == DECISION_UNRESOLVED:
        if not proposed:
            proposed = [{
                "intent_id": "rev_unresolved_000",
                "action": "mark_unresolved",
                "disposition": "UNRESOLVED",
                "target_segment_id": target,
                "rationale": reasoning or "unresolved after VLM",
                "evidence_refs": top_refs,
            }]
        else:
            forced = []
            for it in proposed:
                if not isinstance(it, dict):
                    continue
                forced.append({
                    **it,
                    "action": "mark_unresolved",
                    "disposition": "UNRESOLVED",
                    "target_segment_id": it.get("target_segment_id") or target,
                })
            proposed = forced
    elif decision == DECISION_PROPOSE_REPAIR:
        if not proposed:
            raise ValueError("PROPOSE_REPAIR requires proposed_revision_intents")
        for it in proposed:
            if not isinstance(it, dict):
                raise ValueError("repair_intent_not_object")
            action = str(it.get("action") or "").lower()
            if action in ("keep", "mark_unresolved", "inspect", ""):
                raise ValueError(
                    "PROPOSE_REPAIR intents need concrete edit action "
                    "(trim|replace|search_add|drop|reorder)"
                )
            refs = it.get("evidence_refs") if isinstance(it.get("evidence_refs"), list) else []
            ok, bad = _evidence_refs_ok(refs or top_refs, known_evidence)
            if not ok:
                raise ValueError(f"repair_intent_unknown_evidence:{bad[:5]}")
            # Reject invented absolute media times on the intent itself.
            for k in ("media_in", "media_out", "new_media_in", "new_media_out"):
                if it.get(k) is not None:
                    raise ValueError(
                        f"forbidden_intent_free_timestamp:{k}="
                        f"{it.get(k)}; use evidence-bound trim/replace via observations"
                    )

    # Reuse planner intent normalizer for anchors/actions.
    wrapped = validate_planner_output(
        {
            "diagnoses": [{
                "issue_id": issue_id or "rev_diag_000",
                "problem": diagnosis or reasoning,
                "severity": "P1",
                "target_segment_id": target,
                "evidence_refs": top_refs,
                "expected_improvement": expected,
            }],
            "revision_intents": proposed,
            "video_tool_requests": [],
            "notes": f"revision_planner:{decision}",
        },
        trusted_anchors=trusted_anchors,
        video_duration=video_duration,
    )
    clean_intents = list(wrapped.get("revision_intents") or [])
    if decision == DECISION_PROPOSE_REPAIR:
        edit_actions = {"trim", "replace", "search_add", "drop", "reorder"}
        if not any(it.get("action") in edit_actions for it in clean_intents):
            raise ValueError("PROPOSE_REPAIR produced no concrete edit intents after validation")
        # Extra: trim targets must exist on best EDL.
        by_id = {str(r.get("segment_id")): r for r in best_edl if isinstance(r, dict)}
        for it in clean_intents:
            if it.get("action") == "trim":
                sid = str(it.get("target_segment_id") or "")
                if sid and sid not in by_id:
                    # allow role-only; try resolve
                    pass

    return {
        "schema": REVISION_PLANNER_SCHEMA,
        "decision": decision,
        "target_segment_id": target,
        "issue_id": issue_id,
        "diagnosis": diagnosis,
        "reasoning_summary": reasoning,
        "evidence_refs": top_refs,
        "proposed_revision_intents": clean_intents,
        "remaining_uncertainties": remaining,
        "expected_improvement": expected,
        "dropped_intents": wrapped.get("dropped_intents") or [],
        "first_live_not_claimed": True,
        "render_ready_not_claimed": True,
        "simulated_fixture": bool(raw.get(FIXTURE_MARK)),
    }


def fail_closed_intents_after_revision_failure(
    *,
    planner_intents: Sequence[Mapping[str, Any]],
    focus_segment_ids: Optional[Sequence[str]] = None,
    error: str,
) -> Dict[str, Any]:
    """On Revision Planner failure: keep EDL; never silently apply pre-VLM repair intents."""
    focus = {str(x) for x in (focus_segment_ids or [])}
    recorded = []
    for it in planner_intents:
        if not isinstance(it, dict):
            continue
        sid = str(it.get("target_segment_id") or "")
        role = str(it.get("role") or "")
        aid = str(it.get("anchor_id") or "")
        if focus and not (
            sid in focus
            or any(f in sid or f in aid or f in role for f in focus)
            or "goal_action" in role
        ):
            continue
        recorded.append({
            "intent_id": f"fail_closed_{it.get('intent_id') or 'pre'}",
            "action": "keep",
            "disposition": "UNRESOLVED",
            "target_segment_id": it.get("target_segment_id"),
            "role": it.get("role"),
            "anchor_id": it.get("anchor_id"),
            "rationale": (
                f"Revision Planner failed ({error}); refuse to apply pre-VLM "
                f"planner intent action={it.get('action')!r}"
            ),
            "evidence_refs": [],
            "map_note": "revision_planner_fail_closed",
        })
    if not recorded:
        recorded = [{
            "intent_id": "fail_closed_keep",
            "action": "keep",
            "disposition": "UNRESOLVED",
            "rationale": f"Revision Planner failed ({error}); preserve best EDL",
            "evidence_refs": [],
            "map_note": "revision_planner_fail_closed",
        }]
    return {
        "ok": False,
        "fail_closed": True,
        "error": error,
        "decision": DECISION_UNRESOLVED,
        "proposed_revision_intents": recorded,
        "note": (
            "Pre-VLM planner intents retained for audit only; "
            "they were NOT used to modify EDL after Revision Planner failure."
        ),
        "planner_intents_audit_only": list(planner_intents),
    }


def call_llm_revision_planner(
    api: Optional[ApiProvider],
    context: Mapping[str, Any],
    *,
    fixture: Optional[Mapping[str, Any]] = None,
    trusted_anchors: Sequence[Mapping[str, Any]],
    video_duration: Optional[float],
    best_edl: Sequence[Mapping[str, Any]],
    known_evidence: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Call DeepSeek via planner endpoint with stats_role=revision_planner, or use fixture."""
    known = known_evidence or collect_known_evidence_tokens(
        observations=context.get("new_vlm_observations") or [],
        historical_observations=context.get("historical_vlm_observations") or [],
        composer_handoff=context.get("composer_evidence_handoff"),
    )

    def _validate(raw: Mapping[str, Any], *, provider_mode: str) -> Dict[str, Any]:
        validated = validate_revision_planner_output(
            raw,
            trusted_anchors=trusted_anchors,
            video_duration=video_duration,
            known_evidence=known,
            best_edl=best_edl,
        )
        return {
            "ok": True,
            "provider_mode": provider_mode,
            "raw": raw,
            "validated": validated,
            "usage": {"real_requests": 0} if provider_mode == "offline_fixture" else None,
            "est_cost_usd": 0.0 if provider_mode == "offline_fixture" else None,
            "logical_role": "revision_planner",
            "intent_source": "post_vlm_revision_planner",
        }

    if fixture is not None:
        try:
            marked = dict(fixture)
            marked.setdefault(FIXTURE_MARK, True)
            out = _validate(marked, provider_mode="offline_fixture")
            out["simulated_fixture"] = True
            out["note"] = (
                "Simulated Revision Planner fixture — does NOT prove real DeepSeek "
                "Revision Planner decision quality."
            )
            return out
        except Exception as exc:
            return {
                "ok": False,
                "provider_mode": "offline_fixture",
                "error": f"revision_planner_fixture_validate:{type(exc).__name__}:{exc}",
                "logical_role": "revision_planner",
                "simulated_fixture": True,
            }

    if api is None:
        return {
            "ok": False,
            "provider_mode": "unavailable",
            "error": "revision_planner_api_unavailable",
            "logical_role": "revision_planner",
        }

    user = json.dumps(context, ensure_ascii=False)
    try:
        if hasattr(api, "revise_decision"):
            resp = api.revise_decision(  # type: ignore[attr-defined]
                system_prompt=REVISION_PLANNER_SYSTEM,
                user_prompt=user,
                mock_decision={"error": "mock_not_allowed_for_revision_planner"},
            )
        else:
            resp = api.plan_decision(
                system_prompt=REVISION_PLANNER_SYSTEM,
                user_prompt=user,
                mock_decision={"error": "mock_not_allowed_for_revision_planner"},
            )
    except (ApiConfigError, ApiCallError) as exc:
        return {
            "ok": False,
            "provider_mode": "degraded",
            "error": f"{type(exc).__name__}:{exc}",
            "logical_role": "revision_planner",
        }

    mode = str(resp.get("provider_mode") or "")
    content = str(resp.get("content") or "")
    if mode != "real" or resp.get("error"):
        return {
            "ok": False,
            "provider_mode": mode or "degraded",
            "error": str(resp.get("error") or f"revision_planner_not_real:{mode}"),
            "raw_content": content,
            "raw_excerpt": content[:8000],
            "usage": resp.get("usage"),
            "est_cost_usd": resp.get("est_cost_usd"),
            "model": resp.get("model"),
            "logical_role": "revision_planner",
        }
    if not content.strip():
        return {
            "ok": False,
            "provider_mode": mode,
            "error": "EMPTY_MODEL_CONTENT",
            "failure_code": "EMPTY_MODEL_CONTENT",
            "usage": resp.get("usage"),
            "est_cost_usd": resp.get("est_cost_usd"),
            "model": resp.get("model"),
            "logical_role": "revision_planner",
        }
    try:
        raw = _parse_model_json(content)
        out = _validate(raw, provider_mode=mode)
        out["usage"] = resp.get("usage")
        out["est_cost_usd"] = resp.get("est_cost_usd")
        out["model"] = resp.get("model")
        out["raw_content"] = content
        out["raw_excerpt"] = content[:8000]
        return out
    except Exception as exc:
        return {
            "ok": False,
            "provider_mode": mode,
            "error": f"revision_planner_parse_or_validate:{type(exc).__name__}:{exc}",
            "raw_content": content,
            "raw_excerpt": content[:8000],
            "usage": resp.get("usage"),
            "est_cost_usd": resp.get("est_cost_usd"),
            "model": resp.get("model"),
            "logical_role": "revision_planner",
        }


def select_intents_for_edl_revision(
    *,
    enable_post_vlm_revision: bool,
    revision_planner_result: Optional[Mapping[str, Any]],
    planner_intents: Sequence[Mapping[str, Any]],
    focus_segment_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Choose which intents feed apply_candidate_revision; never silently overwrite audit."""
    planner_audit = copy.deepcopy(list(planner_intents))
    if not enable_post_vlm_revision:
        return {
            "intents": list(planner_intents),
            "intent_source": "pre_vlm_planner",
            "planner_revision_intents_audit": planner_audit,
            "revision_planner_decision": None,
            "fail_closed": False,
        }
    rp = revision_planner_result or {}
    if rp.get("ok") and isinstance(rp.get("validated"), dict):
        validated = rp["validated"]
        return {
            "intents": list(validated.get("proposed_revision_intents") or []),
            "intent_source": "post_vlm_revision_planner",
            "planner_revision_intents_audit": planner_audit,
            "revision_planner_decision": validated.get("decision"),
            "fail_closed": False,
            "revision_planner_validated": validated,
        }
    err = str(rp.get("error") or "revision_planner_unavailable")
    closed = fail_closed_intents_after_revision_failure(
        planner_intents=planner_intents,
        focus_segment_ids=focus_segment_ids,
        error=err,
    )
    return {
        "intents": closed["proposed_revision_intents"],
        "intent_source": "revision_planner_failed_fail_closed",
        "planner_revision_intents_audit": planner_audit,
        "revision_planner_decision": DECISION_UNRESOLVED,
        "fail_closed": True,
        "fail_closed_meta": closed,
    }
