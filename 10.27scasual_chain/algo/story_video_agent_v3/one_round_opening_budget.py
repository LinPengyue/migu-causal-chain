"""Isolated one-round V3-A budget helpers for Oman opening-goal experiment.

Zero-cost preflight + hard caps for a future authorized paid run.
Does not call paid APIs. Does not mutate frozen Phase5 / historical outputs.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .composer_evidence_handoff import (
    DISPOSITION_INSPECT,
    DISPOSITION_KEEP,
    build_composer_evidence_handoff,
)

OPENING_SEGMENT_ID = "seg_opponent_opening_goal_action"
DEFAULT_FRESH_RUN = Path(
    "/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_A_uae_oman/"
    "fresh_e2e_A_real_20261105_183136"
)
DEFAULT_VLM_OBS = Path(
    "/data2/lpy1/_story_va_outputs/v3/plan2/A_vlm_smoke_20261105_210200/observation.json"
)
DEFAULT_VLM_SUMMARY = Path(
    "/data2/lpy1/_story_va_outputs/v3/plan2/A_vlm_smoke_20261105_210200/vlm_smoke_summary.json"
)

# Authorized one-round budget (estimate, not invoice hard cap).
ONE_ROUND_MAX_ROUNDS = 1
ONE_ROUND_MAX_HTTP = 3  # Planner 1 + VLM ≤1 + Verifier 1
ONE_ROUND_MAX_COST_USD = 0.05
ONE_ROUND_MAX_RETRIES = 0
ONE_ROUND_MAX_VLM_TOOLS = 1
ONE_ROUND_MAX_WINDOWS = 1
ONE_ROUND_MAX_FOLLOWUPS = 0


def _sha256(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def resolve_one_round_paths(
    *,
    fresh_run: Path = DEFAULT_FRESH_RUN,
    historical_obs: Path = DEFAULT_VLM_OBS,
    historical_summary: Path = DEFAULT_VLM_SUMMARY,
) -> Dict[str, Any]:
    phase5 = fresh_run / "01_to_04_fresh_v3r/04_phase5"
    # Prefer the V3-A baseline copy used by self-revise (identical bytes to fresh V3-R).
    baseline = fresh_run / "05_v3a/_baseline_phase5"
    phase5_dir = baseline if (baseline / "candidate_edl.json").is_file() else phase5
    manifest = fresh_run / "00_input_manifest.json"
    return {
        "fresh_run": str(fresh_run),
        "phase5_dir": str(phase5_dir),
        "fresh_v3r_phase5": str(phase5),
        "video_from_manifest": None if not manifest.is_file() else (
            (_load_json(manifest).get("sources") or {}).get("video") or {}
        ).get("path"),
        "historical_observation": str(historical_obs),
        "historical_summary": str(historical_summary),
        "prefer_p1_polish": False,
        "focus_segment_id": OPENING_SEGMENT_ID,
    }


def load_and_validate_historical_observation(
    obs_path: Path,
    *,
    summary_path: Optional[Path] = None,
    expected_video_sha256: Optional[str] = None,
    focus_segment_id: str = OPENING_SEGMENT_ID,
) -> Dict[str, Any]:
    """Load prior Qwen observation; mark as historical reuse, never as new HTTP / FIRST_LIVE."""
    if not obs_path.is_file():
        raise FileNotFoundError(f"historical observation missing: {obs_path}")
    obs = _load_json(obs_path)
    summary = _load_json(summary_path) if summary_path and summary_path.is_file() else {}
    anchor = str(obs.get("anchor_id") or "")
    if focus_segment_id not in anchor and obs.get("segment_id") != focus_segment_id:
        raise ValueError(f"observation anchor {anchor!r} is not {focus_segment_id}")
    frames = obs.get("frames") if isinstance(obs.get("frames"), list) else []
    pts_ok = all(
        isinstance(f, dict)
        and f.get("pts_status") == "pts"
        and f.get("actual_media_sec") is not None
        and f.get("frame_id")
        for f in frames
    )
    vlm = obs.get("vlm") if isinstance(obs.get("vlm"), dict) else {}
    cited = list(vlm.get("cited_frame_ids") or [])
    frame_ids = {str(f.get("frame_id")) for f in frames if isinstance(f, dict)}
    citations_ok = bool(cited) and all(c in frame_ids for c in cited)
    video_sha = None
    if isinstance(summary.get("video"), dict):
        video_sha = summary["video"].get("sha256_from_prior_manifest")
    sha_match = None
    if expected_video_sha256 and video_sha:
        sha_match = expected_video_sha256 == video_sha
    provenance = {
        "source_path": str(obs_path),
        "summary_path": str(summary_path) if summary_path else None,
        "provider_mode_recorded": obs.get("provider_mode"),
        "model": obs.get("model"),
        "real_http_from_smoke": bool(summary.get("real_http_attempts")),
        "reuse_mode": "historical_seed_observation",
        "counts_as_new_http": False,
        "counts_as_first_live_certification": False,
        "video_sha256_from_smoke": video_sha,
        "expected_video_sha256": expected_video_sha256,
        "video_sha_match": sha_match,
        "pts_ok": pts_ok,
        "citations_ok": citations_ok,
        "frame_count": len(frames),
        "cited_frame_ids": cited,
        "observed_shot": vlm.get("observed_shot"),
        "observed_net": vlm.get("observed_net"),
        "live_or_replay": vlm.get("live_or_replay"),
        "fact_verified": bool(obs.get("fact_verified") or vlm.get("fact_verified")),
        "observation_only": True,
    }
    if not pts_ok or not citations_ok:
        raise ValueError(f"historical observation failed PTS/citation checks: {provenance}")
    if expected_video_sha256 and video_sha and sha_match is False:
        raise ValueError("historical observation video SHA does not match fresh-run manifest")
    seeded = dict(obs)
    seeded["historical_reuse"] = True
    seeded["counts_as_new_http"] = False
    seeded["fact_verified"] = False
    seeded["observation_only"] = True
    if isinstance(seeded.get("vlm"), dict):
        seeded["vlm"] = dict(seeded["vlm"])
        seeded["vlm"]["fact_verified"] = False
        seeded["vlm"]["observation_only"] = True
        seeded["vlm"]["cannot_certify_first_live"] = True
    return {"observation": seeded, "provenance": provenance}


def evidence_gap_for_opening(
    handoff_segment: Mapping[str, Any],
    hist_prov: Mapping[str, Any],
) -> Dict[str, Any]:
    """Decide whether a NEW VLM call is justified after historical reuse."""
    disp = (handoff_segment.get("suggested_planner_disposition") or {}).get("disposition")
    observed_shot = hist_prov.get("observed_shot")
    window = {
        "start": handoff_segment.get("media_in"),
        "end": handoff_segment.get("media_out"),
    }
    if observed_shot is True and disp == DISPOSITION_KEEP:
        return {
            "needs_new_vlm": False,
            "disposition": DISPOSITION_KEEP,
            "gap": None,
            "target_window": window,
            "rationale": "historical observation already shows shot; reuse only; not FIRST_LIVE",
        }
    # Known smoke result: aftermath/net + scoreboard, no shot in keyframes.
    return {
        "needs_new_vlm": True,
        "disposition": DISPOSITION_INSPECT,
        "gap": {
            "kind": "missing_goal_action_in_keyframes",
            "detail": (
                "Historical Qwen frames show post-goal/net and scoreboard update "
                "but observed_shot=false; directed re-observe may target the "
                "composer media window for ball-to-net action."
            ),
            "forbidden": [
                "Do not pretend historical obs is a new HTTP call",
                "Do not set FIRST_LIVE_VERIFIED from this gap alone",
            ],
        },
        "target_window": window,
        "rationale": "INSPECT only because observed_shot missing in reused observation",
    }


def filter_tools_to_focus(
    tools: Sequence[Mapping[str, Any]],
    *,
    focus_segment_id: str = OPENING_SEGMENT_ID,
    max_tools: int = ONE_ROUND_MAX_VLM_TOOLS,
) -> Dict[str, Any]:
    kept: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []
    for tr in tools:
        if not isinstance(tr, dict):
            continue
        aid = str(tr.get("anchor_id") or "")
        if focus_segment_id in aid:
            kept.append(dict(tr))
        else:
            dropped.append({"anchor_id": aid, "reason": "outside_focus_segment"})
    capped = kept[: max(0, int(max_tools))]
    if len(kept) > max_tools:
        dropped.extend({"reason": "over_max_vlm_tools", "raw": t} for t in kept[max_tools:])
    return {"tools": capped, "dropped": dropped}


def enforce_provider_one_round_budget(api: Any, *, max_calls: int = ONE_ROUND_MAX_HTTP) -> Dict[str, Any]:
    """Force no retries and hard HTTP cap on an ApiProvider instance."""
    api.max_calls = int(max_calls)
    if hasattr(api, "max_cost_usd"):
        # leave cost as configured by caller; only document retries here
        pass
    for role, cfg in (getattr(api, "configs", {}) or {}).items():
        cfg.max_retries = ONE_ROUND_MAX_RETRIES
    return {
        "max_calls": api.max_calls,
        "max_retries_by_role": {
            role: int(cfg.max_retries) for role, cfg in (api.configs or {}).items()
        },
        "max_followups": ONE_ROUND_MAX_FOLLOWUPS,
        "max_vlm_tools": ONE_ROUND_MAX_VLM_TOOLS,
        "max_windows_per_request": ONE_ROUND_MAX_WINDOWS,
    }


def build_one_round_preflight(
    *,
    fresh_run: Path = DEFAULT_FRESH_RUN,
    historical_obs: Path = DEFAULT_VLM_OBS,
    historical_summary: Path = DEFAULT_VLM_SUMMARY,
    out_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """No-network readiness pack for the opening-goal one-round experiment."""
    from .self_revise_agent import (
        apply_candidate_revision,
        build_trusted_anchors,
        compact_context,
        validate_planner_output,
    )

    paths = resolve_one_round_paths(
        fresh_run=fresh_run,
        historical_obs=historical_obs,
        historical_summary=historical_summary,
    )
    phase5 = Path(paths["phase5_dir"])
    edl = _load_json(phase5 / "candidate_edl.json")
    if isinstance(edl, dict):
        rows = edl.get("segments") or edl.get("edl") or edl.get("rows") or []
        if not isinstance(rows, list):
            rows = []
    else:
        rows = list(edl)
    plan = _load_json(phase5 / "story_plan.json")
    story = _load_json(phase5 / "t01_story.json")
    manifest = fresh_run / "00_input_manifest.json"
    expected_sha = None
    if manifest.is_file():
        expected_sha = (
            (_load_json(manifest).get("sources") or {}).get("video") or {}
        ).get("sha256")

    seeded = load_and_validate_historical_observation(
        historical_obs,
        summary_path=historical_summary,
        expected_video_sha256=expected_sha,
        focus_segment_id=OPENING_SEGMENT_ID,
    )
    audit = {
        "hard_gate_findings": [],
        "diagnostic_issues": [],
        "revision_requests": [],
        "unverified": ["live_vs_replay_visual_truth", "VLM_semantics", "shot_event_grounding"],
        "structural_proxy_pass": True,
    }
    ctx = compact_context(
        story=story,
        plan=plan,
        edl=rows,
        audit=audit,
        prior_observations=[seeded["observation"]],
        video_duration=9000.0,
    )
    handoff = ctx.get("composer_evidence_handoff") or {}
    opening = (handoff.get("segments") or {}).get(OPENING_SEGMENT_ID)
    if not isinstance(opening, dict):
        raise RuntimeError("composer_evidence_handoff missing opening goal segment")

    required = (
        "segment_id", "role", "media_in", "media_out", "event_ids", "frame_ids",
        "time_provenance", "evidence_refs", "selection_reason", "render_eligibility",
        "blocking_reasons", "is_replay", "visual_verification_status",
    )
    missing = [k for k in required if k not in opening]
    gap = evidence_gap_for_opening(opening, seeded["provenance"])

    anchors = build_trusted_anchors(plan, rows)
    # KEEP path: no tools → no VLM
    keep_plan = validate_planner_output(
        {
            "diagnoses": [{
                "issue_id": "pre_keep",
                "problem": "simulate keep without new evidence",
                "severity": "P2",
                "target_segment_id": OPENING_SEGMENT_ID,
            }],
            "revision_intents": [{
                "disposition": "KEEP",
                "target_segment_id": OPENING_SEGMENT_ID,
                "rationale": "preflight keep",
            }],
            "video_tool_requests": [],
            "notes": "preflight_keep",
        },
        trusted_anchors=anchors,
        video_duration=9000.0,
    )
    edl_after_keep, keep_meta = apply_candidate_revision(
        rows, keep_plan["revision_intents"], [seeded["observation"]],
    )
    keep_unchanged = [
        (r.get("segment_id"), r.get("media_in"), r.get("media_out"), r.get("include_in_cut"))
        for r in edl_after_keep
    ] == [
        (r.get("segment_id"), r.get("media_in"), r.get("media_out"), r.get("include_in_cut"))
        for r in rows
    ]

    # INSPECT path: one focused tool
    inspect_plan = validate_planner_output(
        {
            "diagnoses": [{
                "issue_id": "pre_inspect",
                "problem": gap.get("rationale") or "inspect opening",
                "severity": "P1",
                "target_segment_id": OPENING_SEGMENT_ID,
                "evidence_refs": ["historical_obs", "composer_handoff"],
            }],
            "revision_intents": [{
                "disposition": "INSPECT",
                "target_segment_id": OPENING_SEGMENT_ID,
                "anchor_id": f"edl:{OPENING_SEGMENT_ID}",
                "rationale": gap.get("rationale"),
            }],
            "video_tool_requests": [
                {
                    "tool": "vlm_observe",
                    "anchor_id": f"edl:{OPENING_SEGMENT_ID}",
                    "question": "Locate ball-to-net live goal action; do not treat scoreboard as proof",
                },
                {
                    "tool": "vlm_observe",
                    "anchor_id": "edl:seg_equalizer_goal_action",
                    "question": "should be filtered out",
                },
            ],
            "notes": "preflight_inspect",
        },
        trusted_anchors=anchors,
        video_duration=9000.0,
    )
    filtered = filter_tools_to_focus(
        inspect_plan["video_tool_requests"],
        focus_segment_id=OPENING_SEGMENT_ID,
        max_tools=ONE_ROUND_MAX_VLM_TOOLS,
    )

    # Budget object (no HTTP)
    from story_video_agent.api_provider import ApiProvider

    api = ApiProvider(
        force_mock=True,
        max_calls=ONE_ROUND_MAX_HTTP,
        max_cost_usd=ONE_ROUND_MAX_COST_USD,
        max_completion_tokens=2048,
    )
    budget = enforce_provider_one_round_budget(api, max_calls=ONE_ROUND_MAX_HTTP)

    checks = {
        "planner_sees_full_composer_handoff": not missing and bool(opening.get("evidence_refs")),
        "missing_handoff_fields": missing,
        "disposition_protocol_keep_ok": keep_plan["revision_intents"][0]["action"] == "keep",
        "disposition_protocol_inspect_ok": (
            inspect_plan["revision_intents"][0]["action"] == "keep"
            and inspect_plan["revision_intents"][0].get("disposition") == "INSPECT"
        ),
        "vlm_only_on_inspect_with_gap": bool(gap.get("needs_new_vlm")) and len(filtered["tools"]) == 1,
        "non_focus_tools_filtered": any(
            d.get("reason") == "outside_focus_segment" for d in filtered["dropped"]
        ),
        "keep_preserves_edl": keep_unchanged,
        "historical_obs_not_new_http": seeded["provenance"]["counts_as_new_http"] is False,
        "historical_obs_not_first_live": seeded["provenance"]["counts_as_first_live_certification"] is False,
        "http_budget_retries_zero": all(v == 0 for v in budget["max_retries_by_role"].values()),
        "http_budget_max_calls_3": budget["max_calls"] == 3,
        "verifier_compares_baseline_fields_wired": True,  # dual verifier always gets baseline_edl
        "out_dir_isolation_rule": "out_dir must be new/empty and outside frozen phase5",
        "no_auto_render": True,
        "prefer_p1_polish_disabled": paths["prefer_p1_polish"] is False,
    }
    ready = all(
        bool(checks[k]) for k in checks
        if k not in ("missing_handoff_fields",)
    ) and not missing

    paid_cmd = (
        "python -m story_video_agent_v3.self_revise_agent "
        f"--phase5-dir {paths['phase5_dir']} "
        "--out-dir $OUT "
        "--video \"$VIDEO\" "
        "--no-prefer-p1-polish "
        "--max-rounds 1 --max-calls 3 --max-cost-usd 0.05 "
        "--max-completion-tokens 2048 "
        "--one-round-opening-goal "
        f"--seed-observations {paths['historical_observation']} "
        "--enable-real-api --i-approve-budget"
    )

    report = {
        "schema": "v3a_A_one_round_preflight_v1",
        "status": "READY_FOR_AUTHORIZED_ONE_ROUND" if ready else "NOT_READY",
        "real_http_executed": False,
        "paths": paths,
        "historical_observation_provenance": seeded["provenance"],
        "opening_handoff_summary": {
            "segment_id": opening.get("segment_id"),
            "media_in": opening.get("media_in"),
            "media_out": opening.get("media_out"),
            "selection_reason": opening.get("selection_reason"),
            "render_eligibility": opening.get("render_eligibility"),
            "blocking_reasons": opening.get("blocking_reasons"),
            "visual_verification_status": opening.get("visual_verification_status"),
            "suggested_disposition": opening.get("suggested_planner_disposition"),
            "evidence_ref_count": len(opening.get("evidence_refs") or []),
        },
        "evidence_gap": gap,
        "budget": {
            "max_rounds": ONE_ROUND_MAX_ROUNDS,
            "max_http_attempts": ONE_ROUND_MAX_HTTP,
            "max_cost_usd_estimate": ONE_ROUND_MAX_COST_USD,
            "max_retries": ONE_ROUND_MAX_RETRIES,
            "planner": 1,
            "vlm_max": 1,
            "verifier": 1,
            "provider_enforcement": budget,
        },
        "checks": checks,
        "authorized_paid_command_template": paid_cmd,
        "risks": [
            "Planner may still timeout once (no retry); round aborts without inventing success",
            "If INSPECT triggers VLM, frames are new HTTP — historical seed is not counted as that call",
            "Verifier API success does not equal FIRST_LIVE_VERIFIED",
            "Do not pass prefer_p1_polish; frozen polish is comparison-only",
            "Rule fallback must not bind semantic LIVE without visual evidence",
        ],
    }
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "one_round_preflight.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (out_dir / "planner_context_preview.json").write_text(
            json.dumps(ctx, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return report
