"""V3 remote VLM goal-action verification — reuses V2 ApiProvider/VisionProvider read-only.

Default path is mock + zero-HTTP config audit. Real billed HTTP requires BOTH
``enable_real_api`` and ``i_approve_budget``. Never mutates V2 packages.
VLM inference is stored separately from cross-checked visible evidence; high
confidence alone never upgrades ``possible_first_live`` → ``verified_first_live``.
"""
from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from story_video_agent.api_provider import (
    COST_DISCLAIMER,
    ApiCallError,
    ApiConfigError,
    ApiProvider,
    api_enabled,
    load_endpoint_configs,
    resolve_effective_caps,
)
from story_video_agent.frames import FrameBudget, FrameStore
from story_video_agent.media import probe_video
from story_video_agent.vision_provider import (
    EvidenceNormalizationError,
    VisionProvider,
    _extract_json_obj,
    classify_normalization_failure,
    normalize_evidence,
)
from story_video_agent.v2_video_evidence_gate import AUTOMATED, NOT_VERIFIED

from .pipeline import dump

GOAL_VERIFY_SCHEMA_HINT = {
    "observed_shot": "bool",
    "observed_net": "bool",
    "attacking_team_match": "bool|null",
    "attacking_side_notes": "string",
    "live_or_replay": "live|replay|unknown",
    "claims_continuous_live": "bool",
    "shot_frame_ids": "string[]",
    "net_frame_ids": "string[]",
    "live_frame_ids": "string[]",
    "uncertain": "string[]",
    "confidence": "0-1",
    "frame_ids": "NON-EMPTY cited subset of allowed ids",
    "notes": "string",
}


def scrub_config_audit(
    *,
    max_calls: int = 3,
    max_cost_usd: float = 0.5,
    max_completion_tokens: int = 2048,
    tcp_probe: bool = True,
) -> Dict[str, Any]:
    """Zero-HTTP config check: models, caps, key presence, optional TCP. No secrets."""
    configs = load_endpoint_configs()
    caps = resolve_effective_caps(
        max_calls=max_calls,
        max_cost_usd=max_cost_usd,
        max_completion_tokens=max_completion_tokens,
    )
    api = ApiProvider(
        force_mock=True,
        max_calls=max_calls,
        max_cost_usd=max_cost_usd,
        max_completion_tokens=max_completion_tokens,
    )
    status = api.status()
    net: List[Dict[str, Any]] = []
    if tcp_probe:
        seen = set()
        for role, cfg in configs.items():
            if not cfg.base_url:
                continue
            raw = cfg.base_url if "://" in cfg.base_url else f"https://{cfg.base_url}"
            host = urlparse(raw).hostname
            if not host or host in seen:
                continue
            seen.add(host)
            try:
                ip = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)[0][4][0]
                sock = socket.create_connection((host, 443), timeout=5)
                sock.close()
                net.append({"host": host, "dns_ip": ip, "tcp_443": "ok", "roles": role})
            except OSError as exc:
                net.append({
                    "host": host,
                    "tcp_443": "fail",
                    "error": type(exc).__name__,
                    "detail": str(exc)[:160],
                    "roles": role,
                })
    vision = status["vision"]
    planner = status["planner"]
    return {
        "schema": "v3_api_config_audit_zero_http_v1",
        "http_requests_sent": 0,
        "api_enabled_env": api_enabled(),
        "STORY_API_ENABLE": os.environ.get("STORY_API_ENABLE"),
        "STORY_API_SMOKE": os.environ.get("STORY_API_SMOKE"),
        "models": {"planner": planner.get("model"), "vision": vision.get("model")},
        "base_urls": {
            "planner": planner.get("base_url"),
            "vision": vision.get("base_url"),
        },
        "api_key_set": {
            "planner": planner.get("api_key_set"),
            "vision": vision.get("api_key_set"),
        },
        "vision": {
            "request_profile": vision.get("request_profile"),
            "token_param": vision.get("token_param"),
            "max_completion_tokens": vision.get("max_completion_tokens"),
            "send_thinking_params": vision.get("send_thinking_params"),
            "thinking_object_disabled": vision.get("thinking_object_disabled"),
            "default_temperature": vision.get("default_temperature"),
            "configured": bool(configs["vision"].configured()),
        },
        "effective_caps": caps,
        "network_tcp_probes": net,
        "provider_status_mode": status.get("mode"),
        "cost_disclaimer": COST_DISCLAIMER,
        "ready_for_mock": True,
        "ready_for_real_when_approved": bool(
            configs["vision"].configured()
            and vision.get("api_key_set")
            and any(x.get("tcp_443") == "ok" for x in net)
        ),
        "recommendations": {
            "max_http_calls_first_trial": 3,
            "disable_thinking": True,
            "prefer_STORY_VLM_REQUEST_PROFILE": "video_rsi",
            "suggested_max_completion_tokens": 2048,
            "note_env_cap_tight": (
                "If STORY_API_MAX_COMPLETION_TOKENS is very low (e.g. 256), "
                "raise it for vision JSON or responses may truncate / empty_json."
            ),
        },
        "note": (
            "Zero HTTP chat/completions. Keys never printed. "
            "Real billed vision requires --enable-real-api AND --i-approve-budget."
        ),
    }


def make_api(
    *,
    enable_real_api: bool,
    i_approve_budget: bool,
    max_calls: int = 3,
    max_cost_usd: float = 0.5,
    max_completion_tokens: int = 2048,
) -> ApiProvider:
    """Build ApiProvider. Real mode only when both enable flags are set."""
    if enable_real_api and not i_approve_budget:
        raise ApiConfigError(
            "Refusing real API: --enable-real-api set but --i-approve-budget missing"
        )
    if enable_real_api and i_approve_budget:
        # Ensure STORY_API_ENABLE so require_real path is consistent with V2
        os.environ.setdefault("STORY_API_ENABLE", "1")
        # Prefer thinking disabled for VLM unless user already set profile
        os.environ.setdefault("STORY_VLM_REQUEST_PROFILE", "video_rsi")
        return ApiProvider(
            force_mock=False,
            require_real=True,
            max_calls=max_calls,
            max_cost_usd=max_cost_usd,
            max_completion_tokens=max_completion_tokens,
            required_roles=("vision",),
        )
    return ApiProvider(
        force_mock=True,
        max_calls=max_calls,
        max_cost_usd=max_cost_usd,
        max_completion_tokens=max_completion_tokens,
        required_roles=("vision",),
    )


def _goal_verify_prompt(
    *,
    gap_id: str,
    media_in: float,
    media_out: float,
    score_before: Optional[Sequence[int]],
    score_after: Optional[Sequence[int]],
    attacking_team_hint: str,
    frame_ids: Sequence[str],
    round_name: str,
) -> str:
    return (
        "You verify whether a football FIRST-LIVE goal action is visible in these frames. "
        "Return ONE JSON object with keys exactly matching: "
        f"{json.dumps(GOAL_VERIFY_SCHEMA_HINT, ensure_ascii=False)}. "
        "Rules: cite only frame_ids you used; never invent media timestamps; "
        "shot means a clear strike/header toward goal; net means ball clearly over the line "
        "or visibly in the net on a cited frame; celebration alone is NOT net; "
        "scoreboard-only is NOT goal action; if unsure, set false/unknown and list in uncertain. "
        f"gap_id={gap_id}; round={round_name}; window=[{media_in:.3f},{media_out:.3f}]; "
        f"score_before={list(score_before) if score_before is not None else None}; "
        f"score_after={list(score_after) if score_after is not None else None}; "
        f"expected_attacking_team_hint={attacking_team_hint!r}; "
        f"allowed_frame_ids={list(frame_ids)}."
    )


def _mock_goal_obj(frame_ids: Sequence[str], *, net_clear: bool = False) -> Dict[str, Any]:
    cited = list(frame_ids[: min(3, len(frame_ids))]) or []
    return {
        "observed_shot": True,
        "observed_net": bool(net_clear),
        "attacking_team_match": True,
        "attacking_side_notes": "mock: red attackers toward far goal (heuristic)",
        "live_or_replay": "live",
        "claims_continuous_live": True,
        "shot_frame_ids": cited[:1],
        "net_frame_ids": cited[1:2] if net_clear else [],
        "live_frame_ids": cited,
        "uncertain": [] if net_clear else ["ball_over_line_not_clear_on_wide_angle"],
        "confidence": 0.42 if not net_clear else 0.71,
        "frame_ids": cited,
        "notes": (
            "mock VLM goal-verify — observation_only; not factual verification; "
            "must not auto-upgrade to verified_first_live without cross-check"
        ),
        "observed_actions": ["shot", "box_scramble"] + (["ball_in_net"] if net_clear else []),
        "possible_teams": [],
        "story_relation": "mock goal-verify round",
    }


def extract_dense_frames(
    *,
    video: Path,
    media_in: float,
    media_out: float,
    out_dir: Path,
    count: int,
    gap_id: str,
    tool: str,
) -> Tuple[FrameStore, List[Dict[str, Any]]]:
    media = probe_video(Path(video))
    store = FrameStore(
        media,
        out_dir=out_dir,
        budget=FrameBudget(max_frames=max(count + 5, 40)),
    )
    records = store.extract_window(
        start=float(media_in),
        end=float(media_out),
        count=int(count),
        gap_id=gap_id,
        tool=tool,
    )
    rows = []
    for r in records:
        rows.append({
            "frame_id": r.frame_id,
            "path": str(r.path),
            "requested_media_sec": r.requested_media_sec,
            "actual_media_sec": r.actual_media_sec,
            "pts_status": r.pts_status,
        })
    return store, rows


def _parse_goal_fields(raw: Dict[str, Any]) -> Dict[str, Any]:
    def _b(key: str) -> Optional[bool]:
        if key not in raw:
            return None
        v = raw.get(key)
        if isinstance(v, bool):
            return v
        if isinstance(v, str) and v.lower() in {"true", "false"}:
            return v.lower() == "true"
        return None

    live = str(raw.get("live_or_replay") or "unknown").lower()
    if live not in {"live", "replay", "unknown"}:
        live = "unknown"
    return {
        "observed_shot": _b("observed_shot"),
        "observed_net": _b("observed_net"),
        "attacking_team_match": _b("attacking_team_match"),
        "claims_continuous_live": _b("claims_continuous_live"),
        "live_or_replay": live,
        "shot_frame_ids": [str(x) for x in (raw.get("shot_frame_ids") or [])],
        "net_frame_ids": [str(x) for x in (raw.get("net_frame_ids") or [])],
        "live_frame_ids": [str(x) for x in (raw.get("live_frame_ids") or [])],
        "uncertain": [str(x) for x in (raw.get("uncertain") or [])],
        "confidence": float(raw["confidence"]) if isinstance(raw.get("confidence"), (int, float)) else None,
        "attacking_side_notes": str(raw.get("attacking_side_notes") or ""),
        "notes": str(raw.get("notes") or ""),
    }


def call_goal_verify_round(
    *,
    api: ApiProvider,
    frames: Sequence[Dict[str, Any]],
    gap_id: str,
    media_in: float,
    media_out: float,
    score_before: Optional[Sequence[int]],
    score_after: Optional[Sequence[int]],
    attacking_team_hint: str,
    round_name: str,
) -> Dict[str, Any]:
    frame_ids = [f["frame_id"] for f in frames]
    paths = [Path(f["path"]) for f in frames]
    bindings = [
        {
            "frame_id": f["frame_id"],
            "requested_media_sec": f.get("requested_media_sec"),
            "actual_media_sec": f.get("actual_media_sec"),
            "pts_status": f.get("pts_status"),
        }
        for f in frames
    ]
    prompt = _goal_verify_prompt(
        gap_id=gap_id,
        media_in=media_in,
        media_out=media_out,
        score_before=score_before,
        score_after=score_after,
        attacking_team_hint=attacking_team_hint,
        frame_ids=frame_ids,
        round_name=round_name,
    )
    mock_obj = _mock_goal_obj(frame_ids, net_clear=False)
    try:
        raw_resp = api.vision_json(
            prompt=prompt,
            frame_paths=paths,
            frame_ids=frame_ids,
            mock_obj=mock_obj,
            frame_bindings=bindings,
        )
    except (ApiConfigError, ApiCallError) as exc:
        return {
            "round": round_name,
            "ok": False,
            "error": type(exc).__name__,
            "message": str(exc),
            "failure_status": getattr(exc, "failure_status", "config_error"),
            "provider_mode": "degraded",
            "vlm_inference": None,
            "normalized_evidence": None,
        }

    mode = str(raw_resp.get("provider_mode") or raw_resp.get("provider") or "")
    if mode == "openai_compatible":
        mode = "real"
    if raw_resp.get("error") or mode == "degraded":
        return {
            "round": round_name,
            "ok": False,
            "error": "degraded",
            "message": str(raw_resp.get("error") or "degraded"),
            "failure_status": raw_resp.get("failure_status") or "degraded",
            "provider_mode": "degraded",
            "usage": raw_resp.get("usage"),
            "est_cost_usd": raw_resp.get("est_cost_usd"),
            "vlm_inference": None,
            "normalized_evidence": None,
        }

    try:
        raw = _extract_json_obj(str(raw_resp.get("content") or ""))
        evidence = normalize_evidence(
            raw,
            gap_id=gap_id,
            frame_ids=frame_ids,
            frame_bindings=bindings,
            provider_mode=mode if mode in ("mock", "real", "cache") else "mock",
            model=str(raw_resp.get("model") or ""),
            raw_response_excerpt=str(raw_resp.get("content") or "")[:800],
        )
        goal_fields = _parse_goal_fields(raw)
        return {
            "round": round_name,
            "ok": True,
            "provider_mode": mode,
            "usage": raw_resp.get("usage"),
            "est_cost_usd": raw_resp.get("est_cost_usd"),
            "cost_disclaimer": raw_resp.get("cost_disclaimer") or COST_DISCLAIMER,
            "vlm_inference": {
                **goal_fields,
                "raw_keys": sorted(raw.keys()),
                "observation_only": True,
                "fact_verified": False,
            },
            "normalized_evidence": evidence,
            "cited_frame_ids": evidence.get("frame_ids") or [],
        }
    except EvidenceNormalizationError as exc:
        return {
            "round": round_name,
            "ok": False,
            "error": "EvidenceNormalizationError",
            "message": str(exc),
            "failure_status": getattr(exc, "failure_status", None)
            or classify_normalization_failure(str(exc)),
            "provider_mode": mode,
            "usage": raw_resp.get("usage"),
            "est_cost_usd": raw_resp.get("est_cost_usd"),
            "raw_response_excerpt": str(raw_resp.get("content") or "")[:800],
            "vlm_inference": None,
            "normalized_evidence": None,
        }


def cross_check_visible_evidence(
    *,
    vlm_inference: Optional[Dict[str, Any]],
    frames: Sequence[Dict[str, Any]],
    score_bounds: Optional[Dict[str, Any]],
    media_in: float,
    media_out: float,
) -> Dict[str, Any]:
    """Separate visible/score constraints from VLM claims. Never trust VLM alone."""
    gaps: List[str] = []
    ok_bits: Dict[str, bool] = {
        "frames_have_pts_or_requested": bool(frames),
        "window_nonempty": float(media_out) > float(media_in) + 0.2,
    }
    if not frames:
        gaps.append("no_frames")
    last_b = (score_bounds or {}).get("last_before_obs") or {}
    first_a = (score_bounds or {}).get("first_after_obs") or {}
    # Action window should not start after first_after board (post-score risk)
    if first_a.get("media_sec") is not None and media_in >= float(first_a["media_sec"]) + 2.0:
        gaps.append("candidate_starts_after_first_after_score")
        ok_bits["score_order_ok"] = False
    else:
        ok_bits["score_order_ok"] = True
    if last_b.get("media_sec") is not None and media_out < float(last_b["media_sec"]) - 15.0:
        gaps.append("candidate_ends_well_before_last_before_score")

    inf = vlm_inference or {}
    # VLM claims recorded but not accepted as facts yet
    claimed_shot = inf.get("observed_shot") is True
    claimed_net = inf.get("observed_net") is True
    claimed_live = inf.get("live_or_replay") == "live"
    claimed_team = inf.get("attacking_team_match") is True
    cited = set(inf.get("shot_frame_ids") or []) | set(inf.get("net_frame_ids") or [])
    allowed = {f["frame_id"] for f in frames}
    if cited - allowed:
        gaps.append("vlm_cited_unknown_frame_ids")
    if claimed_shot and not (inf.get("shot_frame_ids") or []):
        gaps.append("shot_claimed_without_shot_frame_ids")
        claimed_shot = False
    if claimed_net and not (inf.get("net_frame_ids") or []):
        gaps.append("net_claimed_without_net_frame_ids")
        claimed_net = False
    if inf.get("uncertain"):
        gaps.append("vlm_listed_uncertainties")
    if not claimed_net:
        gaps.append("observed_net_unconfirmed")
    if not claimed_shot:
        gaps.append("observed_shot_unconfirmed")
    if not claimed_live:
        gaps.append("live_unconfirmed")
    if not claimed_team:
        gaps.append("attacking_team_unconfirmed")

    # High confidence alone never enough
    conf = inf.get("confidence")
    auto_upgrade_blocked = True
    reasons_block = [
        "possible_first_live_cannot_auto_upgrade_from_vlm_confidence",
        "require_shot_and_net_frame_citations_plus_live_plus_team_plus_score_order",
    ]
    accept_verified = (
        claimed_shot
        and claimed_net
        and claimed_live
        and claimed_team
        and ok_bits.get("score_order_ok")
        and not (cited - allowed)
        and not gaps  # strict: any uncertainty blocks auto verify
    )
    # Even if accept_verified structureally true, mock mode must not claim automated verify
    return {
        "vlm_claims": {
            "observed_shot": claimed_shot,
            "observed_net": claimed_net,
            "live_or_replay": inf.get("live_or_replay"),
            "attacking_team_match": claimed_team,
            "confidence": conf,
        },
        "visible_crosscheck": ok_bits,
        "evidence_gaps": gaps,
        "auto_upgrade_from_confidence_blocked": auto_upgrade_blocked,
        "block_reasons": reasons_block,
        "structurally_ready_for_automated_verify": bool(accept_verified),
        "note": (
            "VLM inference ≠ verified fact. Cross-check must pass AND provider_mode=real "
            "AND automated semantic log written before Gate may accept automated_video_verified."
        ),
    }


def run_remote_vlm_verification(
    *,
    video: Path,
    media_in: float,
    media_out: float,
    out_dir: Path,
    role: str = "opening_deficit",
    score_before: Optional[Sequence[int]] = None,
    score_after: Optional[Sequence[int]] = None,
    score_bounds: Optional[Dict[str, Any]] = None,
    attacking_team_hint: str = "home/attacking team matching score delta",
    enable_real_api: bool = False,
    i_approve_budget: bool = False,
    max_calls: int = 3,
    max_cost_usd: float = 0.5,
    max_completion_tokens: int = 2048,
    round1_frames: int = 8,
    round2_frames: int = 12,
) -> Dict[str, Any]:
    """Multi-round dense verify inside candidate window only (no full-match expand)."""
    dest = Path(out_dir)
    if dest.exists() and any(dest.iterdir()):
        raise RuntimeError(f"Refusing nonempty VLM verify out dir: {dest}")
    dest.mkdir(parents=True, exist_ok=True)

    audit = scrub_config_audit(
        max_calls=max_calls,
        max_cost_usd=max_cost_usd,
        max_completion_tokens=max_completion_tokens,
        tcp_probe=True,
    )
    dump(dest / "api_config_audit_zero_http.json", audit)

    api = make_api(
        enable_real_api=enable_real_api,
        i_approve_budget=i_approve_budget,
        max_calls=max_calls,
        max_cost_usd=max_cost_usd,
        max_completion_tokens=max_completion_tokens,
    )
    vision = VisionProvider(api=api, force_mock=bool(api.force_mock))
    dump(dest / "api_provider_status.json", api.status())

    gap_id = f"v3_p3_{role}_goal_verify"
    frames_dir = dest / "frames"
    rounds: List[Dict[str, Any]] = []

    # Round 1 — dense inspect (capped inside candidate)
    span = float(media_out) - float(media_in)
    # Keep within candidate; optionally focus mid window if long
    r1_in, r1_out = float(media_in), float(media_out)
    if span > 12.0:
        mid = 0.5 * (r1_in + r1_out)
        r1_in = max(float(media_in), mid - 6.0)
        r1_out = min(float(media_out), mid + 6.0)
    _, frames1 = extract_dense_frames(
        video=video,
        media_in=r1_in,
        media_out=r1_out,
        out_dir=frames_dir / "round1",
        count=round1_frames,
        gap_id=gap_id,
        tool="dense_action_inspect",
    )
    dump(dest / "round1_frames.json", frames1)
    r1 = call_goal_verify_round(
        api=api,
        frames=frames1,
        gap_id=gap_id,
        media_in=r1_in,
        media_out=r1_out,
        score_before=score_before,
        score_after=score_after,
        attacking_team_hint=attacking_team_hint,
        round_name="round1_dense",
    )
    rounds.append(r1)

    # Round 2 — adaptive densify only if net unclear, still inside original candidate
    need_r2 = True
    if r1.get("ok") and (r1.get("vlm_inference") or {}).get("observed_net") is True:
        need_r2 = False
    r2_frames: List[Dict[str, Any]] = []
    if need_r2 and api.stats.summary().get("http_attempts", 0) < (max_calls or 3):
        # Focus on earlier half of candidate (pre-celebration / action)
        focus_out = min(float(media_out), float(media_in) + min(10.0, span * 0.7))
        _, r2_frames = extract_dense_frames(
            video=video,
            media_in=float(media_in),
            media_out=focus_out,
            out_dir=frames_dir / "round2",
            count=round2_frames,
            gap_id=gap_id + "_dense2",
            tool="dense_action_inspect",
        )
        dump(dest / "round2_frames.json", r2_frames)
        try:
            r2 = call_goal_verify_round(
                api=api,
                frames=r2_frames,
                gap_id=gap_id + "_dense2",
                media_in=float(media_in),
                media_out=focus_out,
                score_before=score_before,
                score_after=score_after,
                attacking_team_hint=attacking_team_hint,
                round_name="round2_adaptive_densify",
            )
        except ApiCallError as exc:
            r2 = {
                "round": "round2_adaptive_densify",
                "ok": False,
                "error": type(exc).__name__,
                "message": str(exc),
                "failure_status": getattr(exc, "failure_status", ""),
                "blocked_further": True,
            }
        rounds.append(r2)

    # Pick best inference (prefer later ok round with net, else last ok)
    best_inf = None
    best_round = None
    for r in rounds:
        if not r.get("ok"):
            continue
        best_inf = r.get("vlm_inference")
        best_round = r.get("round")
        if best_inf and best_inf.get("observed_net") is True:
            break

    all_frames = list(frames1) + list(r2_frames)
    cross = cross_check_visible_evidence(
        vlm_inference=best_inf,
        frames=all_frames,
        score_bounds=score_bounds,
        media_in=media_in,
        media_out=media_out,
    )

    usage = api.stats.summary()
    provider_mode = "mock" if api.force_mock or not api.require_real else "real"
    # Automated verify ONLY in real mode with structural readiness and no gaps
    can_auto = (
        provider_mode == "real"
        and cross.get("structurally_ready_for_automated_verify")
        and not cross.get("evidence_gaps")
    )
    semantic_log = {
        "schema": "v3_automated_semantic_log_v1",
        "role": role,
        "provider_mode": provider_mode,
        "best_round": best_round,
        "vlm_inference": best_inf,
        "visible_crosscheck": cross,
        "verified_first_live": False,
        "observed_shot": False,
        "observed_net": False,
        "live": False,
        "attacking_team_match": False,
        "continuous": False,
        "shot_sec": None,
        "net_sec": None,
        "note": "Defaults fail-closed; only flipped when can_auto",
    }
    if can_auto and best_inf:
        # Map cited frames to PTS
        by_id = {f["frame_id"]: f for f in all_frames}
        shot_ids = best_inf.get("shot_frame_ids") or []
        net_ids = best_inf.get("net_frame_ids") or []
        shot_sec = None
        net_sec = None
        if shot_ids and shot_ids[0] in by_id:
            fr = by_id[shot_ids[0]]
            shot_sec = fr.get("actual_media_sec") or fr.get("requested_media_sec")
        if net_ids and net_ids[0] in by_id:
            fr = by_id[net_ids[0]]
            net_sec = fr.get("actual_media_sec") or fr.get("requested_media_sec")
        semantic_log.update({
            "verified_first_live": True,
            "observed_shot": True,
            "observed_net": True,
            "live": True,
            "attacking_team_match": True,
            "continuous": bool(best_inf.get("claims_continuous_live")),
            "shot_sec": shot_sec,
            "net_sec": net_sec,
            "semantic_verification_class": AUTOMATED,
        })
    else:
        semantic_log["semantic_verification_class"] = NOT_VERIFIED
        semantic_log["remain_unresolved_reason"] = (
            "mock_path" if provider_mode != "real"
            else ("crosscheck_gaps:" + ",".join(cross.get("evidence_gaps") or ["unknown"]))
        )

    log_path = dest / "automated_semantic_log.json"
    dump(log_path, semantic_log)

    summary = {
        "schema": "v3_remote_vlm_verify_summary_v1",
        "role": role,
        "media_in": media_in,
        "media_out": media_out,
        "enable_real_api": enable_real_api,
        "i_approve_budget": i_approve_budget,
        "provider_mode": provider_mode,
        "n_rounds": len(rounds),
        "rounds": [
            {
                "round": r.get("round"),
                "ok": r.get("ok"),
                "provider_mode": r.get("provider_mode"),
                "failure_status": r.get("failure_status"),
                "observed_shot": (r.get("vlm_inference") or {}).get("observed_shot"),
                "observed_net": (r.get("vlm_inference") or {}).get("observed_net"),
                "live_or_replay": (r.get("vlm_inference") or {}).get("live_or_replay"),
                "confidence": (r.get("vlm_inference") or {}).get("confidence"),
                "usage": r.get("usage"),
                "est_cost_usd": r.get("est_cost_usd"),
            }
            for r in rounds
        ],
        "crosscheck": cross,
        "automated_semantic_log_path": str(log_path),
        "agent_auto_verified": bool(semantic_log.get("verified_first_live")),
        "verification_status": (
            "verified_first_live" if semantic_log.get("verified_first_live") else "unresolved"
        ),
        "semantic_label": (
            "verified_first_live" if semantic_log.get("verified_first_live")
            else "possible_first_live"
        ),
        "api_usage": usage,
        "http_attempts": usage.get("http_attempts"),
        "output_budget_exceeded": bool(api.status().get("output_budget_exceeded")),
        "cost_disclaimer": COST_DISCLAIMER,
        "render_ready": False,
        "vision_stats": vision.stats.to_dict(),
        "config_audit_path": str(dest / "api_config_audit_zero_http.json"),
    }
    dump(dest / "rounds_full.json", rounds)
    dump(dest / "vlm_verify_summary.json", summary)
    return summary
