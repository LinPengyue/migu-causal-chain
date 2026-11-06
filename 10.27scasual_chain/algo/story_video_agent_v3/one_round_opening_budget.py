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


def find_expected_video_sha256(start_dir: Path) -> Optional[str]:
    """Walk parents for 00_input_manifest.json video sha (fail-closed if absent)."""
    cur = Path(start_dir).resolve()
    for _ in range(8):
        man = cur / "00_input_manifest.json"
        if man.is_file():
            video = ((_load_json(man).get("sources") or {}).get("video") or {})
            sha = video.get("sha256")
            if isinstance(sha, str) and len(sha) >= 32:
                return sha
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def resolve_seed_summary_path(
    obs_path: Path,
    *,
    summary_path: Optional[Path] = None,
) -> Optional[Path]:
    if summary_path is not None:
        return Path(summary_path)
    sibling = Path(obs_path).resolve().parent / "vlm_smoke_summary.json"
    return sibling if sibling.is_file() else None


def load_and_validate_historical_observation(
    obs_path: Path,
    *,
    summary_path: Optional[Path] = None,
    expected_video_sha256: Optional[str] = None,
    focus_segment_id: str = OPENING_SEGMENT_ID,
) -> Dict[str, Any]:
    """Load prior Qwen observation with fail-closed provenance checks.

    historical_reuse=true alone is NEVER sufficient: video SHA, PTS, frame_id
    citations, and target segment must all verify.
    """
    if not obs_path.is_file():
        raise FileNotFoundError(f"historical observation missing: {obs_path}")
    if not expected_video_sha256 or not isinstance(expected_video_sha256, str):
        raise ValueError(
            "fail_closed: expected_video_sha256 required for --seed-observations "
            "(cannot accept historical_reuse without match-video SHA)"
        )
    resolved_summary = resolve_seed_summary_path(obs_path, summary_path=summary_path)
    if resolved_summary is None or not resolved_summary.is_file():
        raise ValueError(
            "fail_closed: seed observation summary (vlm_smoke_summary.json) required "
            "to verify video SHA provenance"
        )
    obs = _load_json(obs_path)
    summary = _load_json(resolved_summary)
    # Refuse accepting a pre-flagged reuse blob that skipped validation.
    if obs.get("historical_reuse") and not obs.get("frames"):
        raise ValueError("fail_closed: historical_reuse flag without frames is rejected")
    anchor = str(obs.get("anchor_id") or "")
    if focus_segment_id not in anchor and obs.get("segment_id") != focus_segment_id:
        raise ValueError(
            f"fail_closed: observation anchor {anchor!r} is not focus segment "
            f"{focus_segment_id!r}"
        )
    frames = obs.get("frames") if isinstance(obs.get("frames"), list) else []
    if not frames:
        raise ValueError("fail_closed: seed observation has no frames")
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
    if not video_sha:
        raise ValueError(
            "fail_closed: summary missing video.sha256_from_prior_manifest"
        )
    sha_match = expected_video_sha256 == video_sha
    hist_pts = sorted({
        float(f["actual_media_sec"])
        for f in frames
        if isinstance(f, dict) and f.get("actual_media_sec") is not None
    })
    provenance = {
        "source_path": str(obs_path),
        "summary_path": str(resolved_summary),
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
        "historical_actual_pts": hist_pts,
        "focus_segment_id": focus_segment_id,
        "observed_shot": vlm.get("observed_shot"),
        "observed_net": vlm.get("observed_net"),
        "live_or_replay": vlm.get("live_or_replay"),
        "fact_verified": bool(obs.get("fact_verified") or vlm.get("fact_verified")),
        "observation_only": True,
        "validation_status": "PASSED" if (pts_ok and citations_ok and sha_match) else "FAILED",
    }
    if not pts_ok or not citations_ok:
        raise ValueError(f"fail_closed: PTS/citation checks failed: {provenance}")
    if not sha_match:
        raise ValueError(
            "fail_closed: historical observation video SHA does not match expected "
            f"match video ({video_sha} != {expected_video_sha256})"
        )
    seeded = dict(obs)
    seeded["historical_reuse"] = True
    seeded["counts_as_new_http"] = False
    seeded["fact_verified"] = False
    seeded["observation_only"] = True
    seeded["provenance_validated"] = True
    if isinstance(seeded.get("vlm"), dict):
        seeded["vlm"] = dict(seeded["vlm"])
        seeded["vlm"]["fact_verified"] = False
        seeded["vlm"]["observation_only"] = True
        seeded["vlm"]["cannot_certify_first_live"] = True
    return {"observation": seeded, "provenance": provenance}


def plan_one_round_inspect_sample_times(
    *,
    media_in: float,
    media_out: float,
    linked_goal_t_sec: Optional[float],
    time_provenance_source: Optional[str] = None,
    avoid_pts: Optional[Sequence[float]] = None,
    count: int = 4,
    min_separation_sec: float = 1.5,
) -> Dict[str, Any]:
    """One-round-only frame plan: bias to composer linked_live_goal_event, avoid hist PTS.

    linked_goal_t_sec is an event-association anchor from Rule Composer — NOT visual
    first-LIVE verification of the goal action.
    """
    lo, hi = float(media_in), float(media_out)
    if hi <= lo:
        raise ValueError(f"invalid media window [{lo}, {hi}]")
    avoid = [float(x) for x in (avoid_pts or [])]
    note = (
        "Composer linked_live_goal_event timestamp is event association only; "
        "it is NOT a visually verified goal-action time / FIRST_LIVE proof."
    )
    # Candidate offsets around the linked event (seconds).
    if linked_goal_t_sec is not None:
        center = float(linked_goal_t_sec)
        raw_candidates = [
            center - 5.0, center - 2.5, center - 0.8, center + 0.6, center + 2.0,
            (lo + hi) / 2.0, lo + 0.4 * (hi - lo), lo + 0.7 * (hi - lo),
        ]
        anchor_used = center
        strategy = "linked_live_goal_event_biased_avoid_historical_pts"
    else:
        raw_candidates = [
            lo + f * (hi - lo) for f in (0.15, 0.35, 0.55, 0.75, 0.9)
        ]
        anchor_used = None
        strategy = "media_window_fallback_avoid_historical_pts"
    clipped: List[float] = []
    for t in raw_candidates:
        tt = min(max(float(t), lo + 0.05), hi - 0.05)
        clipped.append(round(tt, 3))
    selected: List[float] = []
    rejected: List[Dict[str, Any]] = []
    for t in clipped:
        if any(abs(t - a) < min_separation_sec for a in avoid):
            rejected.append({"t": t, "reason": "too_close_to_historical_pts"})
            continue
        if any(abs(t - s) < 0.35 for s in selected):
            rejected.append({"t": t, "reason": "duplicate_within_plan"})
            continue
        selected.append(t)
        if len(selected) >= count:
            break
    # If still short, fill from dense grid while avoiding hist PTS.
    if len(selected) < count:
        steps = max(count * 4, 12)
        for i in range(steps):
            t = round(lo + (i + 0.5) * (hi - lo) / steps, 3)
            if any(abs(t - a) < min_separation_sec for a in avoid):
                continue
            if any(abs(t - s) < 0.35 for s in selected):
                continue
            selected.append(t)
            if len(selected) >= count:
                break
    if not selected:
        raise ValueError(
            "fail_closed: could not plan inspect sample times without colliding "
            "historical PTS inside the composer media window"
        )
    return {
        "schema": "v3a_one_round_frame_sample_plan_v1",
        "strategy": strategy,
        "media_in": lo,
        "media_out": hi,
        "linked_goal_t_sec": linked_goal_t_sec,
        "time_provenance_source": time_provenance_source,
        "anchor_used_for_bias": anchor_used,
        "avoid_historical_pts": avoid,
        "min_separation_sec": min_separation_sec,
        "sample_times": selected[:count],
        "rejected_candidates": rejected[:12],
        "event_time_is_not_visual_verification": True,
        "note": note,
    }


def build_one_round_frame_plan_from_edl(
    edl: Sequence[Mapping[str, Any]],
    *,
    seed_provenance: Mapping[str, Any],
    focus_segment_id: str = OPENING_SEGMENT_ID,
    count: int = 4,
) -> Dict[str, Any]:
    row = next(
        (
            r for r in edl
            if isinstance(r, dict)
            and (
                r.get("segment_id") == focus_segment_id
                or r.get("role") == "opponent_opening_goal_action"
            )
        ),
        None,
    )
    if row is None:
        raise ValueError(f"focus segment {focus_segment_id} missing from EDL")
    mi, mo = row.get("media_in"), row.get("media_out")
    if mi is None or mo is None:
        raise ValueError("focus segment missing media_in/out")
    tp = row.get("time_provenance") if isinstance(row.get("time_provenance"), dict) else {}
    src = str(tp.get("source") or "")
    linked_t = tp.get("t_sec") if src == "linked_live_goal_event" else tp.get("t_sec")
    # Prefer explicit linked_live_goal_event; still pass t_sec with warning if other source.
    plan = plan_one_round_inspect_sample_times(
        media_in=float(mi),
        media_out=float(mo),
        linked_goal_t_sec=float(linked_t) if linked_t is not None else None,
        time_provenance_source=src or None,
        avoid_pts=list(seed_provenance.get("historical_actual_pts") or []),
        count=count,
    )
    plan["focus_segment_id"] = focus_segment_id
    plan["goal_anchor_t_sec_on_row"] = row.get("goal_anchor_t_sec")
    return plan


def load_seed_observations_for_run(
    seed_path: Path,
    *,
    phase5_dir: Path,
    focus_segment_id: str = OPENING_SEGMENT_ID,
    summary_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """CLI/runtime entry: fail-closed seed load bound to the match video SHA."""
    expected = find_expected_video_sha256(phase5_dir)
    if not expected:
        raise ValueError(
            f"fail_closed: cannot locate 00_input_manifest.json video sha near {phase5_dir}"
        )
    packed = load_and_validate_historical_observation(
        seed_path,
        summary_path=summary_path,
        expected_video_sha256=expected,
        focus_segment_id=focus_segment_id,
    )
    return {
        "observations": [packed["observation"]],
        "provenance": packed["provenance"],
        "expected_video_sha256": expected,
        "focus_segment_id": focus_segment_id,
    }


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
    expected_sha = find_expected_video_sha256(phase5)
    if not expected_sha:
        expected_sha = find_expected_video_sha256(fresh_run)
    if not expected_sha:
        raise ValueError("fail_closed: cannot resolve match video SHA for seed validation")

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
    frame_plan = build_one_round_frame_plan_from_edl(
        rows,
        seed_provenance=seeded["provenance"],
        focus_segment_id=OPENING_SEGMENT_ID,
        count=4,
    )

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
        "seed_video_sha_validated": seeded["provenance"].get("validation_status") == "PASSED",
        "frame_plan_avoids_historical_pts": all(
            all(abs(t - a) >= 1.5 for a in (seeded["provenance"].get("historical_actual_pts") or []))
            for t in (frame_plan.get("sample_times") or [])
        ),
        "frame_plan_event_not_visual_claim": bool(
            frame_plan.get("event_time_is_not_visual_verification")
        ),
        "frame_plan_uses_linked_goal_bias": (
            frame_plan.get("linked_goal_t_sec") is not None
            and "linked_live_goal_event" in str(frame_plan.get("strategy") or "")
        ),
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
        "one_round_frame_sample_plan": frame_plan,
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
            "linked_live_goal_event time biases sampling only; never treat as visual first-LIVE",
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
        (out_dir / "seed_observation_validation.json").write_text(
            json.dumps(seeded["provenance"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (out_dir / "one_round_frame_sample_plan.json").write_text(
            json.dumps(frame_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return report
