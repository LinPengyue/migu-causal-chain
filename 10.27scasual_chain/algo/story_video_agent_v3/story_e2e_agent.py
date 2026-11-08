"""V3-A Story-level End-to-End Agent orchestration.

Pipeline: V3-R baseline → Critic → Search → Evidence Verification →
Revision Planner → EDL apply → Render → Verifier → status gates / human review.

Default: zero HTTP. Real API requires explicit authorization flags (not used here
unless caller passes enable_real_api).
"""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .fresh_e2e_cli import edl_diff, edl_rows, file_record, validate_render_rows, write_json
from .global_story_critic import (
    merge_observation_into_diagnosis,
    structural_diagnosis,
    write_diagnosis,
)
from .self_revise_agent import apply_candidate_revision
from .story_duplicate_audit import (
    apply_auto_drops,
    audit_edl_duplicates,
    write_audit,
)
from .story_evidence_search import (
    run_story_evidence_search,
    search_candidates_to_observations,
)
from .story_observe import observe_layers
from .story_revision_planner import plan_from_diagnosis
from .final_goal_evidence import build_delivery_and_candidate_evidence
from .story_timeline import build_story_timeline
from .story_video_verifier import (
    compute_release_authorization,
    empty_status_gates,
    timeline_mp4_aligned,
    verify_story_revision,
)

SCHEMA = "v3a_story_e2e_run_v1"
MAX_ROUNDS = 3


@dataclass
class StoryE2EInputs:
    match_json: Path
    source_mp4: Path
    out_dir: Path
    # Optional frozen V3-R baseline for regression (any match).
    phase5_dir: Optional[Path] = None
    initial_story_mp4: Optional[Path] = None
    baseline_edl: Optional[Path] = None
    story_plan: Optional[Path] = None
    t01_story: Optional[Path] = None
    # Fresh V3-R path (JSON+MP4 alone is insufficient without events/causal atoms).
    events_json: Optional[Path] = None
    causal_atoms_json: Optional[Path] = None
    match_id: Optional[str] = None
    algo_root: Optional[Path] = None
    run_fresh_v3r: bool = False
    skip_vlm: bool = True
    enable_real_api: bool = False
    i_approve_budget: bool = False
    force_render_initial: bool = False
    force_render_candidate: bool = False
    smoke_render: bool = True
    fixture_revision: Optional[Mapping[str, Any]] = None
    fixture_verifier: Optional[Mapping[str, Any]] = None
    max_rounds: int = MAX_ROUNDS
    max_calls: int = 5
    max_cost_usd: float = 0.10
    max_retries: int = 0


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _copy_or_link(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        dst.symlink_to(src.resolve())
    except OSError:
        shutil.copy2(src, dst)


def resolve_baseline(inp: StoryE2EInputs) -> Dict[str, Any]:
    """Locate or stage V3-R baseline artifacts under out_dir/00_baseline.

    Honest input contract:
    - match_json + source_mp4 alone do NOT produce Phase5; V3-R needs events +
      causal atoms (or a reused Phase5 directory).
    - When run_fresh_v3r=True and events/causal are provided, invoke closed_loop
      run_match to generate Phase5 under out_dir (never mutate foreign Phase5).
    """
    base_dir = inp.out_dir / "00_baseline"
    base_dir.mkdir(parents=True, exist_ok=True)
    phase5 = inp.phase5_dir
    edl_path = inp.baseline_edl
    plan_path = inp.story_plan
    mp4_path = inp.initial_story_mp4
    t01_path = inp.t01_story
    fresh_meta: Optional[Dict[str, Any]] = None

    raw_only = (
        inp.match_json.is_file()
        and inp.source_mp4.is_file()
        and phase5 is None
        and edl_path is None
        and not inp.run_fresh_v3r
    )

    if inp.run_fresh_v3r:
        events = inp.events_json
        causal = inp.causal_atoms_json
        if events is None or causal is None or not events.is_file() or not causal.is_file():
            return {
                "ok": False,
                "missing": ["events_json", "causal_atoms_json"],
                "reuse_frozen_v3r": False,
                "raw_json_mp4_sufficient": False,
                "paths": {},
                "note": (
                    "run_fresh_v3r requires --events-json and --causal-atoms-json in addition "
                    "to match JSON + source MP4. Match JSON alone is not a V3-R input."
                ),
            }
        from .closed_loop_cli import run_match

        fresh_root = inp.out_dir / "01_to_04_fresh_v3r"
        fresh_root.mkdir(parents=True, exist_ok=True)
        algo = inp.algo_root or Path(__file__).resolve().parents[2]
        mid = inp.match_id or inp.match_json.stem
        fresh_meta = run_match(
            match_id=str(mid),
            events_path=events,
            causal_atoms_path=causal,
            video=inp.source_mp4,
            out_dir=fresh_root,
            algo_root=Path(algo),
            skip_render=False,
        )
        phase5 = fresh_root / "04_phase5"

    if phase5 and phase5.is_dir():
        edl_path = edl_path or (phase5 / "candidate_edl.json")
        plan_path = plan_path or (phase5 / "story_plan.json")
        mp4_path = mp4_path or (phase5 / "story_clean.mp4")
        t01_path = t01_path or (phase5 / "t01_story.json")

    missing = []
    for label, p in (
        ("baseline_edl", edl_path),
        ("story_plan", plan_path),
        ("initial_story_mp4", mp4_path),
    ):
        if p is None or not Path(p).is_file():
            missing.append(label)

    staged = {
        "phase5_dir": str(phase5) if phase5 else None,
        "missing": missing,
        "reuse_frozen_v3r": bool(phase5 and not missing and not inp.run_fresh_v3r),
        "ran_fresh_v3r": bool(inp.run_fresh_v3r and not missing),
        "raw_json_mp4_sufficient": False,
        "raw_only_attempt_detected": bool(raw_only),
        "fresh_meta": fresh_meta,
        "paths": {},
    }

    if missing:
        staged["ok"] = False
        staged["note"] = (
            "V3-A story E2E requires a V3-R Phase5 baseline (EDL + plan + initial MP4). "
            "match_json + source_mp4 alone are NOT sufficient. Provide --phase5-dir for "
            "regression, or --run-fresh-v3r with --events-json and --causal-atoms-json."
        )
        return staged

    # Stage working copies (never mutate frozen Phase5)
    for name, src in (
        ("candidate_edl.json", Path(edl_path)),
        ("story_plan.json", Path(plan_path)),
        ("story_clean.mp4", Path(mp4_path)),
    ):
        dst = base_dir / name
        if name.endswith(".mp4"):
            _copy_or_link(src, dst)
        else:
            shutil.copy2(src, dst)
        staged["paths"][name] = str(dst)

    if t01_path and Path(t01_path).is_file():
        shutil.copy2(t01_path, base_dir / "t01_story.json")
        staged["paths"]["t01_story.json"] = str(base_dir / "t01_story.json")

    # Optional re-render of initial via V3-R renderer
    rendered_initial = None
    if inp.force_render_initial:
        rendered_initial = _render_edl(
            plan=_read_json(base_dir / "story_plan.json"),
            video=inp.source_mp4,
            edl=edl_rows(_read_json(base_dir / "candidate_edl.json")),
            out_dir=inp.out_dir / "01_initial_render",
        )
        staged["paths"]["re_rendered_initial"] = rendered_initial.get("story_clean")
        if rendered_initial.get("story_clean"):
            _copy_or_link(Path(rendered_initial["story_clean"]), base_dir / "story_clean.mp4")

    staged["ok"] = True
    staged["initial_render"] = rendered_initial
    return staged


def _render_edl(
    *,
    plan: Mapping[str, Any],
    video: Path,
    edl: Sequence[Mapping[str, Any]],
    out_dir: Path,
) -> Dict[str, Any]:
    from story_video_agent.phase5_delivery import render_dual_delivery

    rows = validate_render_rows([dict(r) for r in edl])
    out_dir.mkdir(parents=True, exist_ok=True)
    result = render_dual_delivery(
        plan=dict(plan),
        video=Path(video),
        out_dir=out_dir,
        delivery_edl=rows,
    )
    clean = out_dir / "story_clean.mp4"
    qc = out_dir / "story_qc.mp4"
    return {
        "ok": clean.is_file(),
        "story_clean": str(clean) if clean.is_file() else None,
        "story_qc": str(qc) if qc.is_file() else None,
        "renderer": "phase5_delivery.render_dual_delivery",
        "raw": {k: result.get(k) for k in ("clean", "qc") if isinstance(result, dict)},
    }


def smoke_render_one_segment(
    *,
    plan: Mapping[str, Any],
    video: Path,
    edl: Sequence[Mapping[str, Any]],
    out_dir: Path,
) -> Dict[str, Any]:
    """Prove renderer path with a single short media segment (not a delivery claim)."""
    rows = edl_rows(edl) if not isinstance(edl, list) else list(edl)
    media_row = None
    for r in rows:
        if r.get("include_in_cut", True) is False:
            continue
        if r.get("media_in") is not None and r.get("media_out") is not None:
            media_row = dict(r)
            break
    if media_row is None:
        return {"ok": False, "error": "no_media_row"}
    # Shorten to ≤3s for speed
    mi, mo = float(media_row["media_in"]), float(media_row["media_out"])
    media_row["media_out"] = min(mo, mi + 3.0)
    media_row["segment_id"] = str(media_row.get("segment_id") or "smoke") + "_smoke"
    return _render_edl(plan=plan, video=video, edl=[media_row], out_dir=out_dir)


def run_story_e2e(inp: StoryE2EInputs) -> Dict[str, Any]:
    t0 = time.time()
    out = inp.out_dir
    out.mkdir(parents=True, exist_ok=True)
    gates = empty_status_gates()
    http_calls = 0
    est_cost = 0.0
    audit: Dict[str, Any] = {
        "schema": SCHEMA,
        "started_unix": t0,
        "out_dir": str(out),
        "inputs": {
            "match_json": str(inp.match_json),
            "source_mp4": str(inp.source_mp4),
            "phase5_dir": str(inp.phase5_dir) if inp.phase5_dir else None,
            "skip_vlm": inp.skip_vlm,
            "enable_real_api": inp.enable_real_api,
            "i_approve_budget": inp.i_approve_budget,
            "run_fresh_v3r": inp.run_fresh_v3r,
            "max_calls": inp.max_calls,
            "max_cost_usd": inp.max_cost_usd,
        },
        "http_calls": 0,
        "est_cost_usd": 0.0,
        "rounds": [],
        "status_gates": gates,
        "disclaimer": (
            "Offline/dry-run does not claim real multimodal story understanding. "
            "release_authorized stays false unless hard gates + semantic pass."
        ),
    }

    if inp.enable_real_api and not inp.i_approve_budget:
        audit["error"] = "real_api_requested_without_budget_approval"
        write_json(out / "story_e2e_audit.json", audit)
        return audit

    paid_api = None
    if inp.enable_real_api and inp.i_approve_budget:
        from .story_paid_eval import build_capped_provider, provider_usage

        if int(inp.max_calls) > 5 or float(inp.max_cost_usd) > 0.10 or int(inp.max_rounds) > 1:
            audit["error"] = (
                "paid_eval_refused_budget_exceeds_frozen_protocol "
                "(max_rounds<=1, max_calls<=5, max_cost_usd<=0.10, retries=0)"
            )
            write_json(out / "story_e2e_audit.json", audit)
            return audit
        try:
            paid_api = build_capped_provider(
                max_calls=int(inp.max_calls),
                max_cost_usd=float(inp.max_cost_usd),
            )
            st = paid_api.status()
            if not st.get("planner_ready") or not st.get("vision_ready"):
                audit["error"] = "paid_api_config_incomplete"
                audit["api_status_safe"] = {
                    "planner_ready": st.get("planner_ready"),
                    "vision_ready": st.get("vision_ready"),
                }
                write_json(out / "story_e2e_audit.json", audit)
                return audit
            audit["api_preflight"] = {
                "configured": True,
                "max_calls": paid_api.max_calls,
                "max_cost_usd_estimate": paid_api.max_cost_usd,
                "max_retries": 0,
                "cost_is_estimate_not_invoice_cap": True,
            }
        except Exception as exc:  # noqa: BLE001
            audit["error"] = f"paid_api_init_failed:{type(exc).__name__}:{exc}"
            write_json(out / "story_e2e_audit.json", audit)
            return audit

    baseline = resolve_baseline(inp)
    write_json(out / "00_baseline_resolve.json", baseline)
    if not baseline.get("ok"):
        audit["baseline"] = baseline
        audit["error"] = "baseline_unresolved"
        gates["workflow_completed"] = True
        audit["status_gates"] = gates
        write_json(out / "story_e2e_audit.json", audit)
        return audit

    edl = edl_rows(_read_json(Path(baseline["paths"]["candidate_edl.json"])))
    plan = _read_json(Path(baseline["paths"]["story_plan.json"]))
    story = {}
    t01p = baseline["paths"].get("t01_story.json")
    if t01p and Path(t01p).is_file():
        story = _read_json(Path(t01p))
    initial_mp4 = Path(baseline["paths"]["story_clean.mp4"])

    # Smoke-render to prove V3-R renderer wiring (non-delivery)
    smoke = None
    if inp.smoke_render:
        smoke = smoke_render_one_segment(
            plan=plan,
            video=inp.source_mp4,
            edl=edl,
            out_dir=out / "00_render_smoke",
        )
        write_json(out / "00_render_smoke.json", smoke)
    audit["render_smoke"] = smoke

    # Baseline duplicate audit on V3-R intake (prevent inheriting stock repeats).
    baseline_dup = audit_edl_duplicates(
        edl,
        source_mp4=inp.source_mp4 if inp.source_mp4.is_file() else None,
        enable_visual=False,  # structural PTS first; visual optional later
    )
    write_audit(out / "00_baseline" / "duplicate_audit.json", baseline_dup)
    edl_after_dup, dup_apply = apply_auto_drops(edl, baseline_dup)
    if dup_apply.get("changed"):
        write_json(out / "00_baseline" / "edl_after_duplicate_auto_drop.json", edl_after_dup)
        write_json(out / "00_baseline" / "duplicate_auto_drop_report.json", dup_apply)
        edl = edl_after_dup
    audit["baseline_duplicate_audit"] = {
        "finding_count": baseline_dup.get("finding_count"),
        "auto_drop_segment_ids": baseline_dup.get("auto_drop_segment_ids"),
        "human_review_count": baseline_dup.get("human_review_count"),
        "applied": dup_apply,
    }

    # Copy initial into delivery staging
    initial_dir = out / "01_initial_story"
    initial_dir.mkdir(parents=True, exist_ok=True)
    write_json(initial_dir / "candidate_edl.json", edl)
    write_json(initial_dir / "story_plan.json", plan)
    # If baseline auto-drop changed EDL, MUST re-render. Never pair modified EDL
    # with the original MP4 (fail closed → BLOCKED).
    dedupe_render_blocked = False
    if dup_apply.get("changed"):
        write_json(out / "00_baseline" / "duplicate_drop_ledger.json", dup_apply.get("drop_ledger") or [])
        try:
            cleaned_render = _render_edl(
                plan=plan,
                video=inp.source_mp4,
                edl=edl,
                out_dir=initial_dir / "cleaned_baseline_render",
            )
            write_json(initial_dir / "cleaned_baseline_render.json", cleaned_render)
            if cleaned_render.get("story_clean") and Path(cleaned_render["story_clean"]).is_file():
                _copy_or_link(Path(cleaned_render["story_clean"]), initial_dir / "story_clean.mp4")
                audit["baseline_duplicate_audit"]["render_ok"] = True
            else:
                dedupe_render_blocked = True
                audit["baseline_duplicate_audit"]["render_ok"] = False
                audit["baseline_duplicate_audit"]["render_note"] = (
                    "dedupe_changed_edl_but_render_missing_mp4_fail_closed"
                )
        except Exception as exc:  # noqa: BLE001
            dedupe_render_blocked = True
            audit["baseline_duplicate_audit"]["render_ok"] = False
            audit["baseline_duplicate_audit"]["render_error"] = f"{type(exc).__name__}:{exc}"
        if dedupe_render_blocked:
            # Do not copy original MP4 beside modified EDL — leave marker and block delivery.
            write_json(
                initial_dir / "DEDUP_RENDER_BLOCKED.json",
                {
                    "blocked": True,
                    "reason": "edl_deduped_but_render_failed_refuse_pair_with_original_mp4",
                    "dropped": dup_apply.get("dropped"),
                },
            )
            audit["error"] = "dedupe_render_failed_fail_closed"
            audit["delivery_status_forced"] = "BLOCKED"
    else:
        _copy_or_link(initial_mp4, initial_dir / "story_clean.mp4")

    best_edl = [dict(r) for r in edl]
    best_mp4 = initial_dir / "story_clean.mp4"
    if audit.get("delivery_status_forced") == "BLOCKED":
        gates["workflow_completed"] = True
        gates["final_mp4_exists"] = False
        final_dir = out / "99_final"
        final_dir.mkdir(parents=True, exist_ok=True)
        write_json(final_dir / "final_edl.json", best_edl)
        delivery = {
            "release_authorized": False,
            "delivery_label": "BLOCKED",
            "delivery_status": "BLOCKED",
            "blocked_reasons": ["dedupe_render_failed_edl_mp4_mismatch_refused"],
            "final_mp4": None,
            "final_edl": str(final_dir / "final_edl.json"),
            "decision": "UNRESOLVED",
            "note": "EDL was deduped but re-render failed; refusing to pair modified EDL with original MP4.",
        }
        write_json(final_dir / "delivery_status.json", delivery)
        audit["status_gates"] = gates
        audit["delivery"] = delivery
        audit["ok"] = False
        write_json(out / "story_e2e_audit.json", audit)
        write_json(out / "status_gates.json", gates)
        return audit
    final_decision = "KEEP"
    last_candidate_bundle: Dict[str, Any] = {}
    metrics = {
        "revise_proposed": 0,
        "edl_changed_rounds": 0,
        "candidate_rendered": 0,
        "candidate_accepted": 0,
        "search_success_rounds": 0,
        "invalid_candidate": 0,
        "goal_damage_flags": 0,
        "false_or_unverified_improve_claims": 0,
    }

    for round_idx in range(1, max(1, min(inp.max_rounds, MAX_ROUNDS)) + 1):
        round_dir = out / f"02_round_{round_idx:02d}"
        round_dir.mkdir(parents=True, exist_ok=True)
        round_rec: Dict[str, Any] = {"round": round_idx}

        # Critic
        diag = structural_diagnosis(
            edl=best_edl,
            story_plan=plan,
            initial_story_mp4=best_mp4,
            source_video=inp.source_mp4,
        )
        # Observe (ffmpeg layers always; optional paid VLM critic)
        obs = observe_layers(
            story_mp4=best_mp4,
            source_mp4=inp.source_mp4,
            edl=best_edl,
            work_dir=round_dir / "observe",
            diagnosis_issues=diag.get("issues") or [],
            skip_vlm=True,  # VLM is invoked explicitly below when authorized
        )
        vlm_critic = None
        llm_rev = None
        if paid_api is not None:
            from .story_paid_eval import (
                provider_usage,
                run_llm_revision_planner,
                run_vlm_story_critic,
            )

            try:
                vlm_critic = run_vlm_story_critic(
                    paid_api,
                    observations=obs,
                    diagnosis=diag,
                    audit_dir=round_dir / "paid_api",
                )
            except Exception as exc:  # noqa: BLE001
                vlm_critic = {"ok": False, "error": f"{type(exc).__name__}:{exc}"}
            write_json(round_dir / "vlm_story_critic.json", vlm_critic or {})
            if vlm_critic and vlm_critic.get("ok"):
                obs = dict(obs)
                obs["semantic_provider_used"] = True
                obs["fixture_or_offline"] = False
                obs["vlm_results"] = [vlm_critic]
                derived = []
                for di in vlm_critic.get("derived_issues") or []:
                    if not isinstance(di, dict):
                        continue
                    di = dict(di)
                    di.setdefault("evidence_sufficiency", "observed")
                    di.setdefault("suggested_fix", "revise_with_evidence")
                    di.setdefault("story_time_range", [0.0, 0.0])
                    di.setdefault("segment_ids", [])
                    derived.append(di)
                obs["derived_issues"] = derived
            usage = provider_usage(paid_api)
            http_calls = int(usage.get("http_attempts") or http_calls)
            est_cost = float(usage.get("est_cost_usd_real") or est_cost)
            round_rec["api_usage_after_vlm"] = usage
            if http_calls >= int(inp.max_calls) or est_cost >= float(inp.max_cost_usd):
                audit["budget_stop"] = {
                    "reason": "cap_reached_after_vlm",
                    "http_calls": http_calls,
                    "est_cost_usd": est_cost,
                }
                # Fail closed: no further paid calls.
                paid_api = None

        diag = merge_observation_into_diagnosis(diag, obs)
        write_diagnosis(round_dir / "story_diagnosis.json", diag)
        gates["story_diagnosis_valid"] = bool(diag.get("story_diagnosis_valid"))
        round_rec["diagnosis_issue_count"] = len(diag.get("issues") or [])
        round_rec["semantic_observation_claimed"] = diag.get("semantic_observation_claimed")

        # Active evidence search (Critic gaps → source PTS candidates)
        events_path = inp.events_json if inp.events_json and inp.events_json.is_file() else None
        if events_path is None and inp.phase5_dir is not None:
            # Prefer enriched events beside a reused Phase5 tree (match-agnostic layout).
            sibling = Path(inp.phase5_dir).resolve().parent / "01_enrich" / "events_enriched.json"
            if sibling.is_file():
                events_path = sibling
        search_report = run_story_evidence_search(
            diagnosis=diag,
            edl=best_edl,
            match_json=inp.match_json if inp.match_json.is_file() else None,
            events_json=events_path,
        )
        write_json(round_dir / "evidence_search.json", search_report)
        search_obs = search_candidates_to_observations(search_report)
        round_rec["search_success"] = bool(search_report.get("search_success"))
        round_rec["search_verified_count"] = len(search_report.get("verified_candidates") or [])

        # Optional one budget-limited directed re-verify (paid only; never loops).
        if (
            paid_api is not None
            and not search_report.get("search_success")
            and any(
                i.get("evidence_sufficiency") == "needs_video_verify"
                for i in (diag.get("issues") or [])
                if isinstance(i, dict)
            )
            and http_calls < int(inp.max_calls)
            and est_cost < float(inp.max_cost_usd)
        ):
            # Re-run search once after merging any VLM-derived issues (already merged).
            # No second paid call here — search is local; budget reserved for planner/verifier.
            search_report["directed_research_attempted"] = True
            search_report["directed_research_note"] = (
                "budget_reserved_for_planner_verifier; local event-chain search already ran"
            )
            write_json(round_dir / "evidence_search.json", search_report)

        # Revision plan
        fixture_intents = None
        if inp.fixture_revision:
            fixture_intents = inp.fixture_revision.get("revision_intents")
        rev = plan_from_diagnosis(
            diag,
            observations=obs,
            offline=paid_api is None,
            fixture_intents=fixture_intents,
            search_results=search_report,
        )
        if paid_api is not None and fixture_intents is None:
            from .story_paid_eval import provider_usage, run_llm_revision_planner

            try:
                llm_rev = run_llm_revision_planner(
                    paid_api,
                    diagnosis=diag,
                    vlm_critic=vlm_critic or {},
                    protected_goal_ids=list(diag.get("protected_goal_segment_ids") or []),
                    audit_dir=round_dir / "paid_api",
                )
            except Exception as exc:  # noqa: BLE001
                llm_rev = {"ok": False, "error": f"{type(exc).__name__}:{exc}"}
            write_json(round_dir / "llm_revision_planner.json", llm_rev or {})
            search_backed = bool(rev.get("search_confirmation")) and str(rev.get("decision")).upper() == "REVISE"
            if llm_rev and llm_rev.get("ok"):
                llm_intents = list(llm_rev.get("revision_intents") or [])
                llm_acts = {
                    str(i.get("action") or "")
                    for i in llm_intents
                    if isinstance(i, dict)
                }
                llm_has_mut = bool(llm_acts - {"keep", "mark_unresolved"})
                if llm_has_mut:
                    rev = {
                        **rev,
                        "decision": llm_rev.get("decision") or rev.get("decision"),
                        "revision_intents": llm_intents,
                        "rationale": llm_rev.get("rationale") or rev.get("rationale"),
                        "provider_mode": llm_rev.get("provider_mode"),
                        "offline": False,
                        "semantic_confirmation": bool(obs.get("semantic_provider_used")),
                    }
                elif search_backed:
                    # Keep executable search-bound REVISE; do not let empty LLM UNRESOLVED erase it.
                    rev = {
                        **rev,
                        "provider_mode": llm_rev.get("provider_mode"),
                        "offline": False,
                        "semantic_confirmation": bool(obs.get("semantic_provider_used")),
                        "llm_overlay_note": (
                            "llm_returned_no_mutating_intents; retained_search_bound_revise"
                        ),
                        "llm_rationale": llm_rev.get("rationale"),
                    }
                else:
                    rev = {
                        **rev,
                        "decision": llm_rev.get("decision") or rev.get("decision"),
                        "revision_intents": llm_intents or rev.get("revision_intents"),
                        "rationale": llm_rev.get("rationale") or rev.get("rationale"),
                        "provider_mode": llm_rev.get("provider_mode"),
                        "offline": False,
                        "semantic_confirmation": bool(obs.get("semantic_provider_used")),
                    }
                # Honesty: mark_unresolved/keep-only must not be labeled REVISE.
                acts = {
                    str(i.get("action") or "")
                    for i in (rev.get("revision_intents") or [])
                    if isinstance(i, dict)
                }
                if str(rev.get("decision")).upper() == "REVISE" and (
                    not acts or acts <= {"keep", "mark_unresolved"}
                ):
                    rev["decision"] = "UNRESOLVED"
                    rev["normalize_note"] = (
                        "revise_label_without_mutating_intents_normalized_to_unresolved"
                    )
            else:
                if search_backed:
                    rev = {
                        **rev,
                        "offline": False,
                        "llm_overlay_note": "llm_revision_planner_failed_retained_search_bound_revise",
                        "llm_error": (llm_rev or {}).get("error"),
                    }
                else:
                    # Paid planner failed → fail closed to UNRESOLVED, do not pretend KEEP.
                    rev = {
                        **rev,
                        "decision": "UNRESOLVED",
                        "rationale": f"llm_revision_planner_failed:{(llm_rev or {}).get('error')}",
                        "offline": False,
                    }
            usage = provider_usage(paid_api)
            http_calls = int(usage.get("http_attempts") or http_calls)
            est_cost = float(usage.get("est_cost_usd_real") or est_cost)
            round_rec["api_usage_after_rp"] = usage
            if http_calls >= int(inp.max_calls) or est_cost >= float(inp.max_cost_usd):
                audit["budget_stop"] = {
                    "reason": "cap_reached_after_revision_planner",
                    "http_calls": http_calls,
                    "est_cost_usd": est_cost,
                }
                paid_api = None
        if inp.fixture_revision and inp.fixture_revision.get("decision"):
            rev["decision"] = inp.fixture_revision["decision"]
            if fixture_intents is None and rev["decision"] == "KEEP":
                rev["revision_intents"] = [
                    {
                        "intent_id": "fixture_keep",
                        "action": "keep",
                        "narrative_purpose": "fixture",
                    }
                ]
        write_json(round_dir / "revision_plan.json", rev)
        final_decision = str(rev.get("decision") or "UNRESOLVED")
        round_rec["decision"] = final_decision

        candidate_edl = [dict(r) for r in best_edl]
        apply_report: Dict[str, Any] = {"skipped": True}
        if final_decision == "REVISE":
            # Bind search-verified observations (real PTS) — never invent windows.
            candidate_edl, apply_report = apply_candidate_revision(
                best_edl,
                rev.get("revision_intents") or [],
                observations=search_obs,
            )
            applied_rows = list(apply_report.get("applied") or [])
            gates["revision_applied"] = any(
                a.get("status") in ("applied", "applied_evidence_bound")
                for a in applied_rows
            ) or (candidate_edl != best_edl)
            # If REVISE produced no EDL mutation, fail closed to UNRESOLVED.
            if candidate_edl == best_edl and not any(
                a.get("status") in ("applied", "applied_evidence_bound")
                for a in applied_rows
            ):
                final_decision = "UNRESOLVED"
                rev = {
                    **rev,
                    "decision": "UNRESOLVED",
                    "normalize_note": "revise_intents_failed_to_mutate_edl",
                }
                write_json(round_dir / "revision_plan.json", rev)
                round_rec["decision"] = final_decision
        else:
            gates["revision_applied"] = False

        # Candidate-stage duplicate audit (same safety rules as baseline intake).
        cand_dup = audit_edl_duplicates(
            candidate_edl,
            source_mp4=inp.source_mp4 if inp.source_mp4.is_file() else None,
            enable_visual=False,
        )
        write_audit(round_dir / "candidate_duplicate_audit.json", cand_dup)
        candidate_edl, cand_dup_apply = apply_auto_drops(candidate_edl, cand_dup)
        write_json(round_dir / "candidate_duplicate_drop_report.json", cand_dup_apply)
        if cand_dup_apply.get("changed"):
            write_json(round_dir / "candidate_duplicate_drop_ledger.json", cand_dup_apply.get("drop_ledger") or [])
            round_rec["candidate_duplicate_auto_drops"] = cand_dup_apply.get("dropped")

        write_json(round_dir / "candidate_edl.json", candidate_edl)
        write_json(round_dir / "apply_report.json", apply_report)
        write_json(
            round_dir / "edl_diff.json",
            edl_diff(best_edl, candidate_edl) if candidate_edl != best_edl else {"changed": False},
        )

        candidate_mp4: Optional[Path] = None
        render_info: Dict[str, Any] = {"skipped": True}
        edl_changed = candidate_edl != best_edl
        cand_dedupe_render_blocked = False
        # Render when EDL actually changed (safety+authenticity gates still apply later).
        if edl_changed and (final_decision == "REVISE" or inp.force_render_candidate):
            try:
                render_info = _render_edl(
                    plan=plan,
                    video=inp.source_mp4,
                    edl=candidate_edl,
                    out_dir=round_dir / "candidate_render",
                )
                if render_info.get("story_clean"):
                    candidate_mp4 = Path(render_info["story_clean"])
                    gates["candidate_rendered"] = True
            except Exception as exc:  # noqa: BLE001
                render_info = {"ok": False, "error": str(exc)}
                gates["candidate_rendered"] = False
                if cand_dup_apply.get("changed"):
                    cand_dedupe_render_blocked = True
                    render_info["fail_closed"] = (
                        "candidate_deduped_edl_render_failed_refuse_original_mp4"
                    )
            if edl_changed and cand_dup_apply.get("changed") and not gates.get("candidate_rendered"):
                cand_dedupe_render_blocked = True
        elif not edl_changed:
            render_info = {
                "skipped": True,
                "reason": "edl_unchanged_reuse_baseline",
                "baseline_mp4": str(best_mp4),
            }
            candidate_mp4 = best_mp4
            gates["candidate_rendered"] = False
        write_json(round_dir / "candidate_render.json", render_info)

        # Verifier: dual-video vision when revising with a real candidate render
        fixture_v = inp.fixture_verifier
        sent_frame_ids: List[str] = list(
            (inp.fixture_verifier or {}).get("sent_frame_ids") or []
        )
        vision_backed = bool(sent_frame_ids)
        llm_v = None
        if (
            paid_api is not None
            and final_decision == "REVISE"
            and edl_changed
            and candidate_mp4 is not None
            and candidate_mp4.is_file()
            and fixture_v is None
        ):
            from .story_paid_eval import provider_usage, run_llm_verifier
            from .story_video_verifier import probe_video_pair

            try:
                llm_v = run_llm_verifier(
                    paid_api,
                    baseline_summary={"mp4": str(best_mp4)},
                    candidate_summary={"mp4": str(candidate_mp4)},
                    edl_delta=edl_diff(best_edl, candidate_edl),
                    video_probe=probe_video_pair(
                        baseline_mp4=best_mp4, candidate_mp4=candidate_mp4
                    ),
                    audit_dir=round_dir / "paid_api",
                    baseline_mp4=best_mp4,
                    candidate_mp4=candidate_mp4,
                    baseline_edl=best_edl,
                    candidate_edl=candidate_edl,
                    work_dir=round_dir / "paid_api" / "dual_frames",
                )
                write_json(round_dir / "llm_verifier.json", llm_v)
                if isinstance(llm_v.get("validated"), dict):
                    fixture_v = llm_v["validated"]
                sent_frame_ids = list(llm_v.get("sent_frame_ids") or [])
                vision_backed = bool(llm_v.get("vision_backed")) and bool(sent_frame_ids)
                usage = provider_usage(paid_api)
                http_calls = int(usage.get("http_attempts") or http_calls)
                est_cost = float(usage.get("est_cost_usd_real") or est_cost)
                round_rec["api_usage_after_verifier"] = usage
                round_rec["verifier_sent_frame_ids"] = sent_frame_ids
            except Exception as exc:  # noqa: BLE001
                write_json(
                    round_dir / "llm_verifier.json",
                    {"ok": False, "error": f"{type(exc).__name__}:{exc}"},
                )

        vfix = verify_story_revision(
            story=story or plan,
            plan=plan,
            baseline_edl=best_edl,
            candidate_edl=candidate_edl,
            baseline_mp4=best_mp4,
            candidate_mp4=candidate_mp4,
            decision=final_decision,
            fixture=fixture_v,
            sent_frame_ids=sent_frame_ids,
            vision_backed=vision_backed if sent_frame_ids else False,
        )
        write_json(round_dir / "verifier_report.json", vfix)
        gates["semantic_verification_passed"] = (
            str(
                (vfix.get("dual_verifier") or {}).get("semantic_verification_status")
            )
            == "PASSED"
            and bool(vfix.get("vision_backed"))
        )

        if final_decision == "REVISE":
            metrics["revise_proposed"] += 1
        if round_rec.get("search_success"):
            metrics["search_success_rounds"] += 1
        if edl_changed:
            metrics["edl_changed_rounds"] += 1
        if gates.get("candidate_rendered"):
            metrics["candidate_rendered"] += 1
        if vfix.get("hard_vetoes"):
            metrics["invalid_candidate"] += 1
        if not (vfix.get("goal_protection") or {}).get("intact", True):
            metrics["goal_damage_flags"] += 1
        dual = vfix.get("dual_verifier") or {}
        if (
            str(dual.get("quality_delta_vs_baseline") or "").lower() == "improved"
            and not vfix.get("vision_backed")
        ):
            metrics["false_or_unverified_improve_claims"] += 1

        if vfix.get("candidate_accepted") and candidate_mp4 and candidate_mp4.is_file():
            best_edl = candidate_edl
            best_mp4 = candidate_mp4
            round_rec["accepted"] = True
            metrics["candidate_accepted"] += 1
        else:
            round_rec["accepted"] = False
            round_rec["retain_baseline"] = True

        if edl_changed and candidate_mp4 and candidate_mp4.is_file() and gates.get("candidate_rendered"):
            last_candidate_bundle = {
                "round": round_idx,
                "round_dir": str(round_dir),
                "baseline_mp4": str(initial_dir / "story_clean.mp4"),
                "baseline_edl": str(initial_dir / "candidate_edl.json"),
                "candidate_mp4": str(candidate_mp4),
                "candidate_edl": str(round_dir / "candidate_edl.json"),
                "edl_diff": str(round_dir / "edl_diff.json"),
                "evidence_search": str(round_dir / "evidence_search.json"),
                "revision_plan": str(round_dir / "revision_plan.json"),
                "verifier_report": str(round_dir / "verifier_report.json"),
                "story_diagnosis": str(round_dir / "story_diagnosis.json"),
                "goal_anchors_intact": bool((vfix.get("goal_protection") or {}).get("intact", True)),
                "hard_vetoes": list(vfix.get("hard_vetoes") or []),
                "semantic_status": (vfix.get("dual_verifier") or {}).get(
                    "semantic_verification_status"
                ),
                "candidate_accepted": bool(vfix.get("candidate_accepted")),
                "modified_source_pts": [
                    {
                        "segment_id": a.get("segment_id"),
                        "media_in": a.get("media_in"),
                        "media_out": a.get("media_out"),
                        "action": a.get("action"),
                    }
                    for a in (apply_report.get("applied") or [])
                    if a.get("status") in ("applied", "applied_evidence_bound")
                    and a.get("media_in") is not None
                ],
            }

        round_rec["gates_snapshot"] = dict(gates)
        round_rec["edl_changed"] = bool(edl_changed)
        audit["rounds"].append(round_rec)
        audit["last_verifier"] = {
            "candidate_accepted": vfix.get("candidate_accepted"),
            "sent_frame_ids": vfix.get("sent_frame_ids"),
            "hard_vetoes": vfix.get("hard_vetoes"),
            "goal_protection": vfix.get("goal_protection"),
            "warnings": vfix.get("warnings"),
        }
        audit["last_diagnosis_issues"] = list(diag.get("issues") or [])
        audit["edl_changed_any"] = bool(audit.get("edl_changed_any")) or bool(edl_changed)

        # Stop early when KEEP/UNRESOLVED (no further paid/offline loops needed)
        if final_decision in ("KEEP", "UNRESOLVED"):
            break
        if not vfix.get("candidate_accepted"):
            break

    # Final delivery staging
    final_dir = out / "99_final"
    final_dir.mkdir(parents=True, exist_ok=True)
    final_mp4 = final_dir / "story_final.mp4"
    _copy_or_link(best_mp4, final_mp4)
    write_json(final_dir / "final_edl.json", best_edl)
    write_json(final_dir / "story_timeline.json", build_story_timeline(best_edl))
    align = timeline_mp4_aligned(edl=best_edl, mp4=final_mp4, tolerance_sec=2.0)
    write_json(final_dir / "timeline_mp4_alignment.json", align)

    gates["final_mp4_exists"] = final_mp4.is_file()
    gates["workflow_completed"] = True

    last_v = audit.get("last_verifier") or {}
    release = compute_release_authorization(
        gates=gates,
        decision=final_decision,
        edl_changed=bool(audit.get("edl_changed_any")),
        candidate_accepted=bool(last_v.get("candidate_accepted")),
        goal_anchors_intact=bool((last_v.get("goal_protection") or {}).get("intact", True)),
        hard_vetoes=list(last_v.get("hard_vetoes") or []),
        final_mp4=final_mp4,
        final_edl=best_edl,
        diagnosis_issues=list(audit.get("last_diagnosis_issues") or []),
        timeline_aligned=bool(align.get("aligned")),
        unresolved_critical=final_decision == "UNRESOLVED",
    )
    gates["release_authorized"] = bool(release.get("release_authorized"))
    write_json(final_dir / "release_gate.json", release)

    # Candidate human-review package: safe playable preview when auto semantic is uncertain.
    human_review: Dict[str, Any] = {"required": False}
    if last_candidate_bundle:
        hr_dir = final_dir / "human_review_candidate"
        hr_dir.mkdir(parents=True, exist_ok=True)
        cand_src = Path(last_candidate_bundle["candidate_mp4"])
        base_src = Path(last_candidate_bundle["baseline_mp4"])
        cand_dst = hr_dir / "v3a_candidate.mp4"
        base_dst = hr_dir / "v3r_baseline.mp4"
        if cand_src.is_file():
            _copy_or_link(cand_src, cand_dst)
        if base_src.is_file():
            _copy_or_link(base_src, base_dst)
        # Stage EDL/diff/evidence copies for review.
        for key, name in (
            ("candidate_edl", "v3a_candidate_edl.json"),
            ("edl_diff", "edl_diff.json"),
            ("evidence_search", "evidence_search.json"),
            ("revision_plan", "revision_plan.json"),
            ("verifier_report", "verifier_report.json"),
            ("story_diagnosis", "story_diagnosis.json"),
        ):
            src = Path(last_candidate_bundle.get(key) or "")
            if src.is_file():
                shutil.copy2(src, hr_dir / name)
        write_json(hr_dir / "modified_source_pts.json", last_candidate_bundle.get("modified_source_pts") or [])
        write_json(hr_dir / "baseline_edl.json", edl_rows(_read_json(Path(last_candidate_bundle["baseline_edl"]))) if Path(last_candidate_bundle["baseline_edl"]).is_file() else [])

        safe_preview = (
            cand_dst.is_file()
            and bool(last_candidate_bundle.get("goal_anchors_intact"))
            and not last_candidate_bundle.get("hard_vetoes")
        )
        semantic = str(last_candidate_bundle.get("semantic_status") or "")
        accepted = bool(last_candidate_bundle.get("candidate_accepted"))
        needs_human = safe_preview and not gates["release_authorized"] and (
            not accepted
            or semantic in ("", "NOT_EVALUATED", "UNKNOWN", "INCONCLUSIVE")
            or not gates.get("semantic_verification_passed")
        )
        human_review = {
            "required": bool(needs_human),
            "label": "HUMAN_REVIEW_REQUIRED" if needs_human else (
                "CANDIDATE_AUTO_ACCEPTED" if accepted else "CANDIDATE_BLOCKED"
            ),
            "safe_playable_preview": bool(safe_preview),
            "auto_release_forbidden": True,
            "dir": str(hr_dir),
            "v3r_baseline_mp4": str(base_dst) if base_dst.is_file() else None,
            "v3a_candidate_mp4": str(cand_dst) if cand_dst.is_file() else None,
            "bundle": last_candidate_bundle,
            "note": (
                "Candidate is for human story judgment only. "
                "Uncertainty must not be auto-labeled success or failure for formal release."
            ),
        }
        write_json(hr_dir / "human_review_status.json", human_review)

    # Final EDL first-live evidence (not V3-R historical stats). Inherit only on
    # identical video SHA + media/evidence windows; otherwise re-verify.
    prior_v3r_fl: Dict[str, Any] = {}
    fl_path = out / "01_to_04_fresh_v3r" / "05_live_audit" / "first_live_visual_audit.json"
    if fl_path.is_file():
        try:
            prior_v3r_fl = _read_json(fl_path)
        except Exception:  # noqa: BLE001
            prior_v3r_fl = {}

    recovery_payload: Dict[str, Any] = {}
    recovery_path = out / "01_to_04_fresh_v3r" / "03_v1_adapt" / "goal_recovery.json"
    if recovery_path.is_file():
        try:
            recovery_payload = _read_json(recovery_path)
        except Exception:  # noqa: BLE001
            recovery_payload = {}
    predicted_causal: Dict[str, Any] = {}
    pred_path = out / "01_to_04_fresh_v3r" / "03_v1_adapt" / "predicted_causal.json"
    if pred_path.is_file():
        try:
            predicted_causal = _read_json(pred_path)
        except Exception:  # noqa: BLE001
            predicted_causal = {}
    story_graph: Dict[str, Any] = {}
    graph_path = (
        Path(baseline["paths"].get("story_graph.json") or "")
        if baseline.get("paths")
        else Path()
    )
    if not graph_path.is_file():
        graph_path = out / "01_to_04_fresh_v3r" / "04_phase5" / "story_graph.json"
    if graph_path.is_file():
        try:
            story_graph = _read_json(graph_path)
        except Exception:  # noqa: BLE001
            story_graph = {}

    events_for_fl = inp.events_json
    enrich_events = out / "01_to_04_fresh_v3r" / "01_enrich" / "events_enriched.json"
    if enrich_events.is_file():
        events_for_fl = enrich_events

    candidate_edl_for_evidence = None
    if last_candidate_bundle.get("candidate_edl"):
        cpath = Path(last_candidate_bundle["candidate_edl"])
        if cpath.is_file():
            try:
                candidate_edl_for_evidence = edl_rows(_read_json(cpath))
            except Exception:  # noqa: BLE001
                candidate_edl_for_evidence = None

    evidence_pack = build_delivery_and_candidate_evidence(
        delivery_edl=best_edl,
        candidate_edl=candidate_edl_for_evidence,
        video=inp.source_mp4,
        out_dir=final_dir / "goal_evidence",
        events_path=events_for_fl,
        goal_recovery=recovery_payload,
        prior_v3r_audit=prior_v3r_fl or None,
        predicted_causal=predicted_causal,
        story_graph=story_graph,
        final_mp4=final_mp4,
    )
    delivery_fl = evidence_pack["delivery"]
    candidate_fl = evidence_pack.get("candidate")
    lineage = evidence_pack["lineage"]
    write_json(final_dir / "final_goal_evidence_manifest.json", delivery_fl)
    write_json(final_dir / "goal_lineage_report.json", lineage)
    if candidate_fl is not None:
        write_json(final_dir / "candidate_goal_evidence_manifest.json", candidate_fl)
    # Keep prior V3-R audit as historical reference only (not release authority).
    write_json(
        final_dir / "first_live_visual_audit.json",
        {
            "schema": "v3a_first_live_historical_v3r_ref_v1",
            "authority_for_release": False,
            "path": str(fl_path) if fl_path.is_file() else None,
            "note": "V3-R audit is inheritance candidate only; RELEASE_READY uses final_goal_evidence_manifest",
            "v3r_status_counts": (prior_v3r_fl or {}).get("status_counts"),
        },
    )

    audit["first_live_visual"] = {
        "authority": "final_delivery_edl",
        "path": str(final_dir / "final_goal_evidence_manifest.json"),
        "status_counts": delivery_fl.get("status_counts"),
        "n_goal_anchors": delivery_fl.get("n_goal_anchors"),
        "any_first_live_verified": delivery_fl.get("any_first_live_verified"),
        "any_replay_on_retained": delivery_fl.get("any_replay_on_retained"),
        "n_inherited": delivery_fl.get("n_inherited"),
        "n_reverified": delivery_fl.get("n_reverified"),
        "goals": [
            {
                "segment_id": g.get("segment_id"),
                "role": g.get("role"),
                "first_live_status": g.get("first_live_status"),
                "source_media_in": g.get("source_media_in"),
                "source_media_out": g.get("source_media_out"),
                "evidence_binding": g.get("evidence_binding"),
                "inherited": g.get("inherited"),
            }
            for g in (delivery_fl.get("goals") or [])
        ],
        "candidate_separate": {
            "path": str(final_dir / "candidate_goal_evidence_manifest.json") if candidate_fl else None,
            "status_counts": (candidate_fl or {}).get("status_counts"),
            "n_goal_anchors": (candidate_fl or {}).get("n_goal_anchors"),
        },
        "v3r_historical_ref": str(fl_path) if fl_path.is_file() else None,
    }
    audit["goal_lineage"] = {
        "path": str(final_dir / "goal_lineage_report.json"),
        "n_final_goal_segments": lineage.get("n_final_goal_segments"),
        "n_structurally_traced_to_mp4": lineage.get("n_structurally_traced_to_mp4"),
        "duplicate_segment_ids": lineage.get("duplicate_segment_ids"),
    }

    # Formal delivery status: RELEASE_READY | HUMAN_REVIEW_REQUIRED | BLOCKED
    blocked_reasons: List[str] = []
    if audit.get("delivery_status_forced") == "BLOCKED" or audit.get("error") == "dedupe_render_failed_fail_closed":
        blocked_reasons.append("dedupe_render_failed_edl_mp4_mismatch_refused")
    if not gates.get("final_mp4_exists"):
        blocked_reasons.append("final_mp4_missing")
    if align.get("aligned") is False:
        blocked_reasons.append("final_mp4_edl_timeline_misaligned")
    hard = list(last_v.get("hard_vetoes") or [])
    if hard:
        blocked_reasons.append("hard_vetoes_present")
    if not (last_v.get("goal_protection") or {}).get("intact", True):
        blocked_reasons.append("goal_anchors_damaged")
    if final_decision == "UNRESOLVED" and not human_review.get("required") and not gates.get("release_authorized"):
        # unresolved without a safe playable candidate preview
        if not (human_review.get("v3a_candidate_mp4") or last_candidate_bundle.get("candidate_mp4")):
            blocked_reasons.append("unresolved_without_safe_candidate_preview")
    # Retained replay as first-live is a hard integrity failure (final EDL authority).
    if delivery_fl.get("any_replay_on_retained"):
        blocked_reasons.append("retained_goal_replay_detected_as_first_live")
    # Missing lineage to final MP4 blocks auto-release claims.
    if int(lineage.get("n_final_goal_segments") or 0) <= 0:
        blocked_reasons.append("final_edl_missing_goal_anchors")
    if lineage.get("duplicate_segment_ids"):
        blocked_reasons.append("duplicate_goal_segment_ids_in_final_edl")
    # RELEASE_READY requires every *final delivery* goal FIRST_LIVE_VERIFIED.
    fl_counts = delivery_fl.get("status_counts") or {}
    n_fl_goals = int(delivery_fl.get("n_goal_anchors") or 0)
    all_fl_verified = (
        n_fl_goals > 0
        and int(fl_counts.get("FIRST_LIVE_VERIFIED") or 0) == n_fl_goals
        and bool(delivery_fl.get("all_resolved_verified"))
    )
    if gates.get("release_authorized") and not all_fl_verified:
        # Fail closed on release; still allow HUMAN_REVIEW_REQUIRED if preview is safe.
        gates["release_authorized"] = False
        release["release_authorized"] = False
        release.setdefault("reasons", []).append("final_edl_first_live_not_fully_verified")

    if gates["release_authorized"] and all_fl_verified:
        delivery_label = "RELEASE_READY"
    elif human_review.get("required") and human_review.get("safe_playable_preview") and not blocked_reasons:
        delivery_label = "HUMAN_REVIEW_REQUIRED"
    elif blocked_reasons:
        delivery_label = "BLOCKED"
    elif human_review.get("required"):
        delivery_label = "HUMAN_REVIEW_REQUIRED"
    else:
        delivery_label = "BLOCKED"
        blocked_reasons.append("no_release_and_no_safe_human_review_preview")

    # Do not advertise a "final" MP4 when BLOCKED for EDL/MP4 mismatch.
    publishable_mp4 = str(final_mp4) if final_mp4.is_file() and delivery_label != "BLOCKED" else (
        str(final_mp4) if final_mp4.is_file() and delivery_label == "HUMAN_REVIEW_REQUIRED" else (
            str(final_mp4) if final_mp4.is_file() and delivery_label == "RELEASE_READY" else None
        )
    )
    if delivery_label == "BLOCKED" and "dedupe_render_failed" in ",".join(blocked_reasons):
        publishable_mp4 = None

    delivery = {
        "release_authorized": gates["release_authorized"],
        "delivery_label": delivery_label,
        "delivery_status": delivery_label,
        "blocked_reasons": blocked_reasons,
        "human_review": human_review,
        "final_mp4": publishable_mp4 if delivery_label == "RELEASE_READY" else (
            str(final_mp4) if final_mp4.is_file() and delivery_label == "HUMAN_REVIEW_REQUIRED" else publishable_mp4
        ),
        "final_edl": str(final_dir / "final_edl.json"),
        "decision": final_decision,
        "release_gate": release,
        "metrics": metrics,
        "timeline_mp4_alignment": {
            k: align.get(k)
            for k in (
                "aligned", "mp4_duration_sec", "story_duration_sec",
                "media_duration_sec", "placeholder_duration_sec", "delta_sec",
                "root_cause_hint",
            )
        },
        "first_live_visual": audit.get("first_live_visual"),
        "final_goal_evidence_manifest": str(final_dir / "final_goal_evidence_manifest.json"),
        "goal_lineage_report": str(final_dir / "goal_lineage_report.json"),
        "goal_lineage": audit.get("goal_lineage"),
        "note": (
            "Formal delivery requires release_authorized=true under full conjunction gates. "
            "workflow_completed / final_mp4_exists / semantic_verification_passed alone never authorize. "
            "HUMAN_REVIEW_REQUIRED means a safe candidate preview exists for human judgment. "
            "RELEASE_READY requires FIRST_LIVE_VERIFIED on every final-delivery EDL goal "
            "(final_goal_evidence_manifest), not V3-R historical first-live stats."
            if not gates["release_authorized"]
            else "RELEASE_READY: all formal release conjunction gates passed including final-EDL first-live."
        ),
    }
    write_json(final_dir / "delivery_status.json", delivery)

    audit["status_gates"] = gates
    audit["delivery"] = delivery
    audit["metrics"] = metrics
    audit["baseline"] = {
        "initial_mp4": str(initial_dir / "story_clean.mp4"),
        "records": {
            "initial": file_record(initial_dir / "story_clean.mp4"),
            "final": file_record(final_mp4),
            "smoke": file_record(Path((smoke or {}).get("story_clean") or "/__none__")),
        },
    }
    audit["http_calls"] = http_calls
    audit["est_cost_usd"] = est_cost
    audit["elapsed_sec"] = round(time.time() - t0, 3)
    audit["ok"] = True
    write_json(out / "story_e2e_audit.json", audit)
    write_json(out / "status_gates.json", gates)
    return audit
