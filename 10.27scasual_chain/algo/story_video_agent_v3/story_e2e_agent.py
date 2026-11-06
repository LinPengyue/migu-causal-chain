"""V3-A Story-level End-to-End Agent orchestration.

Pipeline: V3-R baseline (reuse or render) → Global Critic → layered observe →
Revision Planner → optional candidate render → Verifier → status gates → audit.

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

from .fresh_e2e_cli import edl_rows, file_record, validate_render_rows, write_json
from .global_story_critic import (
    merge_observation_into_diagnosis,
    structural_diagnosis,
    write_diagnosis,
)
from .self_revise_agent import apply_candidate_revision
from .story_observe import observe_layers
from .story_revision_planner import plan_from_diagnosis
from .story_timeline import build_story_timeline
from .story_video_verifier import empty_status_gates, verify_story_revision

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

    # Copy initial into delivery staging
    initial_dir = out / "01_initial_story"
    initial_dir.mkdir(parents=True, exist_ok=True)
    _copy_or_link(initial_mp4, initial_dir / "story_clean.mp4")
    write_json(initial_dir / "candidate_edl.json", edl)
    write_json(initial_dir / "story_plan.json", plan)

    best_edl = [dict(r) for r in edl]
    best_mp4 = initial_dir / "story_clean.mp4"
    final_decision = "KEEP"

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

        # Revision plan
        fixture_intents = None
        if inp.fixture_revision:
            fixture_intents = inp.fixture_revision.get("revision_intents")
        rev = plan_from_diagnosis(
            diag,
            observations=obs,
            offline=paid_api is None,
            fixture_intents=fixture_intents,
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
            if llm_rev and llm_rev.get("ok"):
                rev = {
                    **rev,
                    "decision": llm_rev.get("decision") or rev.get("decision"),
                    "revision_intents": llm_rev.get("revision_intents") or rev.get("revision_intents"),
                    "rationale": llm_rev.get("rationale") or rev.get("rationale"),
                    "provider_mode": llm_rev.get("provider_mode"),
                    "offline": False,
                    "semantic_confirmation": bool(obs.get("semantic_provider_used")),
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
            candidate_edl, apply_report = apply_candidate_revision(
                best_edl,
                rev.get("revision_intents") or [],
                observations=[],  # no invented windows offline
            )
            applied_rows = list(apply_report.get("applied") or [])
            gates["revision_applied"] = any(
                a.get("status") in ("applied", "applied_evidence_bound")
                for a in applied_rows
            ) or (candidate_edl != best_edl)
        else:
            gates["revision_applied"] = False

        write_json(round_dir / "candidate_edl.json", candidate_edl)
        write_json(round_dir / "apply_report.json", apply_report)

        candidate_mp4: Optional[Path] = None
        render_info: Dict[str, Any] = {"skipped": True}
        edl_changed = candidate_edl != best_edl
        if final_decision == "REVISE" and (edl_changed or inp.force_render_candidate):
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
        elif not edl_changed:
            render_info = {
                "skipped": True,
                "reason": "edl_unchanged_reuse_baseline",
                "baseline_mp4": str(best_mp4),
            }
            candidate_mp4 = best_mp4
            gates["candidate_rendered"] = False
        write_json(round_dir / "candidate_render.json", render_info)

        # Verifier (optional paid LLM when revising under remaining budget)
        fixture_v = inp.fixture_verifier
        if (
            paid_api is not None
            and final_decision == "REVISE"
            and edl_changed
            and fixture_v is None
        ):
            from .fresh_e2e_cli import edl_diff
            from .story_paid_eval import provider_usage, run_llm_verifier
            from .story_video_verifier import probe_video_pair

            try:
                llm_v = run_llm_verifier(
                    paid_api,
                    baseline_summary={
                        "mp4": str(best_mp4),
                        "segment_count": len(best_edl),
                        "protected_goals": diag.get("protected_goal_segment_ids"),
                    },
                    candidate_summary={
                        "mp4": str(candidate_mp4) if candidate_mp4 else None,
                        "segment_count": len(candidate_edl),
                    },
                    edl_delta=edl_diff(best_edl, candidate_edl),
                    video_probe=probe_video_pair(
                        baseline_mp4=best_mp4, candidate_mp4=candidate_mp4
                    ),
                    audit_dir=round_dir / "paid_api",
                )
                write_json(round_dir / "llm_verifier.json", llm_v)
                if llm_v.get("ok") and isinstance(llm_v.get("validated"), dict):
                    fixture_v = llm_v["validated"]
                usage = provider_usage(paid_api)
                http_calls = int(usage.get("http_attempts") or http_calls)
                est_cost = float(usage.get("est_cost_usd_real") or est_cost)
                round_rec["api_usage_after_verifier"] = usage
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
        )
        write_json(round_dir / "verifier_report.json", vfix)
        gates["semantic_verification_passed"] = (
            str(
                (vfix.get("dual_verifier") or {}).get("semantic_verification_status")
            )
            == "PASSED"
        )

        if vfix.get("candidate_accepted") and candidate_mp4 and candidate_mp4.is_file():
            best_edl = candidate_edl
            best_mp4 = candidate_mp4
            round_rec["accepted"] = True
        else:
            round_rec["accepted"] = False
            round_rec["retain_baseline"] = True

        round_rec["gates_snapshot"] = dict(gates)
        audit["rounds"].append(round_rec)

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

    gates["final_mp4_exists"] = final_mp4.is_file()
    gates["workflow_completed"] = True
    # Release only when semantic passed AND no unresolved critical path
    gates["release_authorized"] = bool(
        gates["semantic_verification_passed"]
        and gates["final_mp4_exists"]
        and final_decision != "UNRESOLVED"
        and not audit.get("error")
    )

    delivery = {
        "release_authorized": gates["release_authorized"],
        "delivery_label": (
            "FORMAL_RELEASE"
            if gates["release_authorized"]
            else "INTERNAL_PREVIEW_NOT_FOR_DELIVERY"
        ),
        "final_mp4": str(final_mp4) if final_mp4.is_file() else None,
        "final_edl": str(final_dir / "final_edl.json"),
        "decision": final_decision,
        "note": (
            "Formal delivery requires release_authorized=true. "
            "Internal preview may exist while gates fail."
            if not gates["release_authorized"]
            else "All status gates passed for formal release."
        ),
    }
    write_json(final_dir / "delivery_status.json", delivery)

    audit["status_gates"] = gates
    audit["delivery"] = delivery
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
