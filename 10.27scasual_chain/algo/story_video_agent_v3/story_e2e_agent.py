"""V3-A Story-level End-to-End Agent — **unified main chain**.

Official pipeline (do not fork a second revise loop via run_self_revise):

  match input → events/causal → V3-R initial story → global observe →
  Critic diagnosis → Planner intents → source evidence search →
  EDL safety (incl. source PTS order) → candidate MP4 → dual-video verify →
  accept/reject → final delivery + evidence.

`run_self_revise` remains a specialized VLM/opening/fixture laboratory entry.
Production / CLI story runs must go through `run_story_e2e`.

Default: zero HTTP. Real API requires explicit authorization flags.
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
from .story_edl_safety import check_source_pts_monotonic, classify_revision_status
from .story_evidence_search import (
    run_story_evidence_search,
    search_candidates_to_observations,
)
from .story_observe import observe_layers
from .story_revision_planner import plan_from_diagnosis
from .story_narrative_fit import (
    enforce_narrative_fit_on_plan,
    load_narrative_fit_store,
)
from .revision_case import build_revision_cases_for_round
from .story_revision_feedback import (
    RevisionFeedbackStore,
    normalize_feedback,
)
from .story_loop_policy import (
    apply_transition,
    evaluate_round_transition,
    init_loop_state,
    write_loop_state,
)
from .final_goal_evidence import build_delivery_and_candidate_evidence, sha256_file
from .story_timeline import build_story_timeline
from .story_inferred_narrative_graph import (
    attach_validated_video_review,
    build_inferred_narrative_graph,
    graph_observation_targets,
    rebase_narrative_graph,
)
from .story_revision_feedback import make_observation_evidence_token
from .first_live_window_evidence import (
    build_local_first_live_evidence_pack,
    diff_new_source_windows,
    load_evidence_store,
    looks_like_content_hash,
    window_key as first_live_window_key,
)
from .story_video_verifier import (
    build_first_live_window_ledger,
    compute_release_authorization,
    empty_status_gates,
    timeline_mp4_aligned,
    verify_story_revision,
)
import hashlib

SCHEMA = "v3a_story_e2e_run_v1"
UNIFIED_CHAIN_ID = "v3a_unified_story_self_revise_main_v1"
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
    # Phase10-C opt-in exploratory sandbox; no release/acceptance path changed.
    phase10_explore: bool = False
    phase10_explore_fixture: Optional[Mapping[str, Any]] = None
    smoke_render: bool = True
    fixture_revision: Optional[Mapping[str, Any]] = None
    fixture_verifier: Optional[Mapping[str, Any]] = None
    # Optional per-round fixture overlays for offline Phase8 multi-round control-flow tests.
    # Each item may include revision_intents/decision and/or verifier fields (phase8_*).
    # confirm_issue_ids: mark structural issues CONFIRMED without scripting intents/candidates.
    phase8_round_fixtures: Optional[Sequence[Mapping[str, Any]]] = None
    confirm_issue_ids: Optional[Sequence[str]] = None
    # Optional directory/JSON of validated first-LIVE evidence packs (source SHA + PTS).
    first_live_evidence_dir: Optional[Path] = None
    # Optional independently reviewed BEFORE→CANDIDATE→AFTER video evidence.
    narrative_fit_evidence_dir: Optional[Path] = None
    # When True, build local frame-pack evidence for new windows from source MP4 (zero HTTP).
    build_local_first_live_evidence: bool = False
    max_rounds: int = MAX_ROUNDS
    max_calls: int = 5
    max_cost_usd: float = 0.10
    max_retries: int = 0
    # Separate named mode for future paid multi-round; default False keeps frozen guard.
    phase8_paid_multi_round: bool = False


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_events_enriched_path(path: Optional[Path]) -> bool:
    """True when path is the V3-R enrich_files output (not raw 赛事.json)."""
    if path is None:
        return False
    p = Path(path)
    if p.name == "events_enriched.json":
        return True
    # Parent folder convention: .../01_enrich/events_enriched.json
    return p.parent.name == "01_enrich" and p.suffix == ".json" and "enrich" in p.name


def resolve_events_json_for_agent(
    *,
    events_json: Optional[Path] = None,
    phase5_dir: Optional[Path] = None,
    out_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Prefer V3-R ``01_enrich/events_enriched.json`` over raw delivery events.

    Search/Critic/Planner evidence must not silently fall back to raw ``赛事.json``
    when the upstream enrich artifact exists beside Phase5 or under a fresh V3-R
    tree. Explicit ``events_enriched.json`` paths still win. Does **not** re-run
    ``enrich_files`` or invent a parallel event_union.
    """
    enriched_candidates: List[Path] = []
    if phase5_dir is not None:
        enriched_candidates.append(
            Path(phase5_dir).resolve().parent / "01_enrich" / "events_enriched.json"
        )
    if out_dir is not None:
        enriched_candidates.append(
            Path(out_dir).resolve() / "01_to_04_fresh_v3r" / "01_enrich" / "events_enriched.json"
        )
    for cand in enriched_candidates:
        if cand.is_file():
            # Raw events_json must not bypass enriched sibling.
            if events_json is None or not _is_events_enriched_path(events_json):
                return cand
            break
    if events_json is not None and Path(events_json).is_file():
        return Path(events_json)
    for cand in enriched_candidates:
        if cand.is_file():
            return cand
    return None


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
        "unified_main_chain": {
            "id": UNIFIED_CHAIN_ID,
            "entry": "run_story_e2e",
            "does_not_call_run_self_revise": True,
            "reuses": [
                "structural_diagnosis",
                "observe_layers",
                "apply_semantic_diagnosis_layer",
                "run_story_evidence_search",
                "plan_from_diagnosis",
                "apply_candidate_revision",
                "check_source_pts_monotonic",
                "verify_story_revision",
                "build_revision_cases_for_round",
                "recover_per_revision_judgments",
            ],
            "specialized_lab_entry": "run_self_revise",
            "phase6": {
                "semantic_hypothesis_layer": True,
                "no_auto_add_on_large_source_gap_alone": True,
                "BETTER_not_auto_IMPROVED": True,
                "revision_case_closed_loop": True,
            },
            "phase8": {
                "failure_aware_iterative_revision": True,
                "modules": [
                    "story_revision_feedback",
                    "story_loop_policy",
                ],
                "accept_candidate_does_not_drive_loop": True,
                "phase8_paid_multi_round_default": False,
            },
        },
        "started_unix": t0,
        "out_dir": str(out),
        "inputs": {
            "match_json": str(inp.match_json),
            "source_mp4": str(inp.source_mp4),
            "phase5_dir": str(inp.phase5_dir) if inp.phase5_dir else None,
            "skip_vlm": inp.skip_vlm,
            "enable_real_api": inp.enable_real_api,
            "i_approve_budget": inp.i_approve_budget,
            "phase8_paid_multi_round": bool(inp.phase8_paid_multi_round),
            "phase10_explore": bool(inp.phase10_explore),
            "phase10_explore_fixture": bool(inp.phase10_explore_fixture is not None),
            "first_live_evidence_dir": (
                str(inp.first_live_evidence_dir) if inp.first_live_evidence_dir else None
            ),
            "narrative_fit_evidence_dir": (
                str(inp.narrative_fit_evidence_dir) if inp.narrative_fit_evidence_dir else None
            ),
            "run_fresh_v3r": inp.run_fresh_v3r,
            "max_rounds": inp.max_rounds,
            "max_calls": inp.max_calls,
            "max_cost_usd": inp.max_cost_usd,
        },
        "http_calls": 0,
        "est_cost_usd": 0.0,
        "rounds": [],
        "status_gates": gates,
        "revision_status_totals": {"APPLIED": 0, "VERIFIED": 0, "IMPROVED": 0},
        "disclaimer": (
            "Offline/dry-run does not claim real multimodal story understanding. "
            "release_authorized stays false unless hard gates + semantic pass. "
            "APPLIED ≠ VERIFIED ≠ IMPROVED."
        ),
    }

    if inp.enable_real_api and not inp.i_approve_budget:
        audit["error"] = "real_api_requested_without_budget_approval"
        write_json(out / "story_e2e_audit.json", audit)
        return audit

    paid_api = None
    if inp.enable_real_api and inp.i_approve_budget:
        from .story_paid_eval import build_capped_provider, provider_usage

        rounds_ok = int(inp.max_rounds) <= 1 or bool(inp.phase8_paid_multi_round)
        if int(inp.max_calls) > 5 or float(inp.max_cost_usd) > 0.10 or not rounds_ok:
            audit["error"] = (
                "paid_eval_refused_budget_exceeds_frozen_protocol "
                "(max_rounds<=1 unless phase8_paid_multi_round=True; "
                "max_calls<=5, max_cost_usd<=0.10, retries=0)"
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
            from .story_paid_eval import provider_usage as _provider_usage_preflight

            audit["api_preflight"] = {
                "configured": True,
                "max_calls": paid_api.max_calls,
                "max_cost_usd_estimate": paid_api.max_cost_usd,
                "max_retries": 0,
                "cost_is_estimate_not_invoice_cap": True,
                "max_completion_tokens": paid_api.max_completion_tokens,
                "request_body_preflight": getattr(
                    paid_api, "_phase7_request_preflight", None
                ),
                "env_thinking_overrides": getattr(paid_api, "_phase7_env_audit", None),
                "usage_snapshot": _provider_usage_preflight(paid_api),
            }
            write_json(out / "api_request_preflight.json", audit["api_preflight"])
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
    working_edl = [dict(r) for r in best_edl]
    working_mp4 = best_mp4
    feedback_store = RevisionFeedbackStore()
    loop_state = init_loop_state(
        version_id="v0",
        edl_path=str(initial_dir / "candidate_edl.json"),
        mp4_path=str(best_mp4),
        source="V3R_BASELINE",
    )
    version_edl: Dict[str, List[Dict[str, Any]]] = {"v0": [dict(r) for r in best_edl]}
    version_mp4: Dict[str, Path] = {"v0": best_mp4}
    version_snapshots: Dict[str, Dict[str, Any]] = {
        "v0": {
            "version_id": "v0",
            "role": "initial_baseline",
            "edl_path": str(initial_dir / "candidate_edl.json"),
            "mp4_path": str(best_mp4),
            "safety": "UNKNOWN",
            "quality": "BASELINE_UNVERIFIED",
            "verdict_provenance": "OFFLINE_RULE",
            "goal_protection_intact": True,
            "semantic_verification_passed": False,
            "candidate_rendered": True,
            "hard_vetoes": [],
            "diagnosis_issues": [],
            "gates": {},
        }
    }
    pending_reobserve: Optional[Dict[str, Any]] = None
    source_sha = sha256_file(inp.source_mp4) if inp.source_mp4.is_file() else None
    # Retain EVERY source-bound cut, including protected goal/score windows,
    # for narrative-relevance review. Structural protection is not evidence of
    # semantic necessity; this read-only inventory never edits or rates clips.
    from .story_cut_relevance_audit import build_cut_relevance_inventory
    cut_inventory = build_cut_relevance_inventory(best_edl, source_sha256=source_sha)
    write_json(out / "00_baseline" / "cut_relevance_inventory.json", cut_inventory)
    audit["cut_relevance_inventory"] = {
        "status": "SEMANTIC_RELEVANCE_UNVERIFIED",
        "segment_count": cut_inventory["segment_count"],
        "path": str(out / "00_baseline" / "cut_relevance_inventory.json"),
    }
    first_live_evidence_store = load_evidence_store(inp.first_live_evidence_dir)
    narrative_fit_evidence_store = load_narrative_fit_store(inp.narrative_fit_evidence_dir)
    # Offline fixtures explicitly exercise older loop behavior; never bypass
    # the narrative evidence gate in a real paid/production execution.
    narrative_fit_required = not (
        not inp.enable_real_api and (
            inp.fixture_revision is not None
            or inp.phase8_round_fixtures is not None
            or bool(inp.confirm_issue_ids)
        )
    )
    audit["narrative_fit_required"] = narrative_fit_required
    audit["narrative_fit_review_store_n"] = len(
        narrative_fit_evidence_store.get("by_key") or {}
    )
    first_live_prior_ledger: Dict[str, Any] = {
        "schema": "v3a_first_live_window_ledger_v1",
        "source_sha": source_sha or "MISSING_SOURCE_SHA",
        "windows": [],
    }
    audit["first_live_evidence_store_n"] = len(first_live_evidence_store.get("by_key") or {})
    version_snapshots["v0"]["source_sha256"] = source_sha
    version_snapshots["v0"]["edl_sha256"] = hashlib.sha256(
        json.dumps(best_edl, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    version_snapshots["v0"]["mp4_sha256"] = (
        sha256_file(best_mp4) if best_mp4.is_file() else None
    )
    audit["phase8_loop_state"] = loop_state
    audit["phase8_feedback_memory"] = feedback_store.to_dict()
    audit["source_sha256"] = source_sha
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

    previous_narrative_graph: Optional[Dict[str, Any]] = None
    for round_idx in range(1, max(1, min(inp.max_rounds, MAX_ROUNDS)) + 1):
        round_dir = out / f"02_round_{round_idx:02d}"
        round_dir.mkdir(parents=True, exist_ok=True)
        round_rec: Dict[str, Any] = {"round": round_idx}

        # Critic on current WORKING parent (not only last accepted best).
        parent_version_id = str(loop_state.get("working_version_id") or "v0")
        diag = structural_diagnosis(
            edl=working_edl,
            story_plan=plan,
            initial_story_mp4=working_mp4,
            source_video=inp.source_mp4,
        )
        # P10-B: rederive an inference-only, source/EDL-bound narrative graph.
        # NEVER read benchmark gold labels in this production path. Graph role
        # hints and editorial adjacency are NOT story defects or match causation.
        narrative_graph = build_inferred_narrative_graph(
            edl=working_edl, story_plan=plan, source_sha256=source_sha,
        )
        narrative_graph = rebase_narrative_graph(narrative_graph, previous_narrative_graph)
        graph_targets = graph_observation_targets(narrative_graph, max_targets=2)
        diag["agent_narrative_graph"] = narrative_graph
        diag["graph_observation_targets"] = graph_targets
        write_json(round_dir / "agent_narrative_graph_pre_observe.json", narrative_graph)
        write_json(round_dir / "agent_graph_observation_targets.json", graph_targets)
        # Observe (ffmpeg layers always; optional paid VLM critic)
        obs = observe_layers(
            story_mp4=working_mp4,
            source_mp4=inp.source_mp4,
            edl=working_edl,
            work_dir=round_dir / "observe",
            diagnosis_issues=(
                (graph_targets if inp.fixture_revision is None and
                 inp.phase8_round_fixtures is None else [])
                + list(diag.get("issues") or [])
            ),
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

            # Prefer dense ordered stills around the first HYPOTHESIS that needs video
            # (bridge/jump/ending). Still NOT a native continuous-video bitstream watch.
            extra_frames: List[Dict[str, Any]] = []
            dense_meta: Dict[str, Any] = {}
            try:
                from .vlm_semantic_evidence import extract_dense_frames_for_issue

                hyp = None
                for iss in diag.get("issues") or []:
                    if not isinstance(iss, dict):
                        continue
                    if str(iss.get("evidence_sufficiency") or "") != "needs_video_verify":
                        continue
                    iid = str(iss.get("issue_id") or "")
                    if any(
                        k in iid
                        for k in ("jump", "bridge", "transition", "ending", "sparse", "buildup")
                    ) or str(iss.get("category") or "") in (
                        "transition",
                        "ending",
                        "buildup",
                    ):
                        hyp = iss
                        break
                if hyp is None:
                    for iss in diag.get("issues") or []:
                        if (
                            isinstance(iss, dict)
                            and str(iss.get("evidence_sufficiency") or "")
                            == "needs_video_verify"
                        ):
                            hyp = iss
                            break
                if hyp is not None and working_mp4 and Path(working_mp4).is_file():
                    dense_meta = extract_dense_frames_for_issue(
                        story_mp4=Path(working_mp4),
                        edl=working_edl,
                        issue=hyp,
                        out_dir=round_dir / "paid_api" / "dense_observe",
                        fps=1.0,
                        max_frames=6,
                        pad_sec=1.0,
                    )
                    extra_frames = list(dense_meta.get("frames") or [])
                    write_json(round_dir / "paid_api" / "dense_observe_meta.json", dense_meta)
            except Exception as exc:  # noqa: BLE001
                dense_meta = {"ok": False, "error": f"{type(exc).__name__}:{exc}"}
                write_json(round_dir / "paid_api" / "dense_observe_meta.json", dense_meta)

            try:
                vlm_critic = run_vlm_story_critic(
                    paid_api,
                    observations=obs,
                    diagnosis=diag,
                    audit_dir=round_dir / "paid_api",
                    extra_frames=extra_frames or None,
                )
            except Exception as exc:  # noqa: BLE001
                vlm_critic = {"ok": False, "error": f"{type(exc).__name__}:{exc}"}
            if isinstance(vlm_critic, dict) and dense_meta:
                vlm_critic = dict(vlm_critic)
                vlm_critic["dense_observe"] = {
                    "ok": dense_meta.get("ok"),
                    "issue_id": dense_meta.get("issue_id"),
                    "story_time_range": dense_meta.get("story_time_range"),
                    "n_frames": len(extra_frames),
                    "claims_full_video_watch": False,
                    "observation_method": dense_meta.get("observation_method"),
                    "note": dense_meta.get("note"),
                }
            write_json(round_dir / "vlm_story_critic.json", vlm_critic or {})
            if vlm_critic and (
                vlm_critic.get("ok")
                or vlm_critic.get("derived_issues")
                or vlm_critic.get("semantic_evidence")
            ):
                obs = dict(obs)
                obs["semantic_provider_used"] = bool(vlm_critic.get("ok"))
                obs["fixture_or_offline"] = False
                obs["vlm_results"] = [vlm_critic]
                # Preserve claim_status / evidence_refs from the evidence bridge.
                # Do NOT force evidence_sufficiency=observed (that skipped frame checks).
                derived = []
                for di in vlm_critic.get("derived_issues") or []:
                    if not isinstance(di, dict):
                        continue
                    di = dict(di)
                    di.setdefault("suggested_fix", "needs_more_video_evidence")
                    di.setdefault("story_time_range", [0.0, 0.0])
                    di.setdefault("segment_ids", [])
                    derived.append(di)
                obs["derived_issues"] = derived
                obs["semantic_evidence"] = list(vlm_critic.get("semantic_evidence") or [])
                obs["confirmed_issue_ids"] = list(
                    vlm_critic.get("confirmed_issue_ids") or []
                )
                obs["observation_scope"] = (vlm_critic.get("observation_updates") or {}).get(
                    "observation_scope"
                ) or {
                    "method": vlm_critic.get("observation_method"),
                    "claims_full_video_watch": False,
                }
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
        # Update graph with citation-normalized video *claims*, not new facts;
        # note VLM evidence is still sparse sampling, not fullcut human judgment.
        narrative_graph = attach_validated_video_review(
            narrative_graph,
            observations=obs,
            diagnosis_issues=diag.get("issues") or [],
        )
        diag["agent_narrative_graph"] = narrative_graph
        previous_narrative_graph = narrative_graph
        write_json(round_dir / "agent_narrative_graph.json", narrative_graph)
        # Offline confirm AFTER semantic merge so HYPOTHESIS layer cannot wipe it.
        # Does NOT inject revision intents or candidate PTS — search/planner choose.
        confirm_ids = set(str(x) for x in (inp.confirm_issue_ids or []) if x)
        if inp.phase8_round_fixtures and round_idx - 1 < len(inp.phase8_round_fixtures):
            _fx0 = inp.phase8_round_fixtures[round_idx - 1] or {}
            for x in _fx0.get("confirm_issue_ids") or []:
                if x:
                    confirm_ids.add(str(x))
        if confirm_ids:
            for iss in diag.get("issues") or []:
                if not isinstance(iss, dict):
                    continue
                iid = str(iss.get("issue_id") or "")
                matched = iid in confirm_ids or any(
                    iid.startswith(str(p).rstrip("*"))
                    for p in confirm_ids
                    if str(p).endswith("*") or str(p).endswith("_")
                )
                if matched:
                    iss["story_defect_confirmed"] = True
                    iss["diagnosis_status"] = "CONFIRMED_STORY_DEFECT"
                    iss["evidence_sufficiency"] = (
                        "observed"
                        if iss.get("evidence_sufficiency") == "needs_video_verify"
                        else (iss.get("evidence_sufficiency") or "observed")
                    )
                    iss["confirmation_basis"] = list(iss.get("confirmation_basis") or []) + [
                        "phase8_offline_confirm_issue_ids"
                    ]
        write_diagnosis(round_dir / "story_diagnosis.json", diag)
        gates["story_diagnosis_valid"] = bool(diag.get("story_diagnosis_valid"))
        round_rec["diagnosis_issue_count"] = len(diag.get("issues") or [])
        round_rec["semantic_observation_claimed"] = diag.get("semantic_observation_claimed")
        round_rec["agent_narrative_graph"] = {
            "schema": narrative_graph.get("schema"),
            "node_count": (narrative_graph.get("summary") or {}).get("node_count"),
            "unreviewed_transition_count": (narrative_graph.get("summary") or {}).get("unreviewed_narrative_transitions"),
            "model_reviewed_transition_count": (narrative_graph.get("summary") or {}).get("model_reviewed_transitions"),
            "observation_target_count": len(graph_targets),
            "benchmark_gold_used": False,
        }

        # Active evidence search (Critic gaps → source PTS candidates).
        # Prefer V3-R events_enriched.json; raw events_json must not bypass it.
        events_path = resolve_events_json_for_agent(
            events_json=inp.events_json,
            phase5_dir=inp.phase5_dir,
            out_dir=out,
        )
        fb_ctx = feedback_store.to_dict()
        search_report = run_story_evidence_search(
            diagnosis=diag,
            edl=working_edl,
            match_json=inp.match_json if inp.match_json.is_file() else None,
            events_json=events_path,
            feedback_context=fb_ctx,
            first_live_evidence_store=first_live_evidence_store,
            narrative_fit_evidence_store=narrative_fit_evidence_store,
            source_sha256=source_sha,
        )
        # The review queue exposes source/anchor triples for targeted
        # BEFORE→CANDIDATE→AFTER visual inspection; it never self-certifies.
        write_json(
            round_dir / "narrative_fit_review_queue.json",
            {
                "schema": "v3a_narrative_fit_review_queue_v1",
                "source_sha256": source_sha,
                "issue_candidates": [
                    {
                        "candidate_id": c.get("candidate_id"),
                        "issue_id": c.get("issue_id"),
                        "narrative_context": c.get("narrative_context"),
                        "narrative_fit_status": c.get("narrative_fit_status"),
                        "narrative_fit_reason": (c.get("narrative_fit") or {}).get("reason"),
                        "first_live_status": c.get("first_live_status"),
                    }
                    for c in (search_report.get("verified_candidates") or [])[:15]
                ],
                "note": (
                    "Prioritize video-backed story information, not time-gap balancing "
                    "or highlight duration. Missing review does not authorize insert."
                ),
            },
        )
        search_report["events_json_resolved_via"] = (
            "events_enriched"
            if events_path is not None and _is_events_enriched_path(events_path)
            else ("explicit_events_json" if events_path is not None else "match_json_only")
        )
        # Phase8 narrative-fit: one or two narrowly targeted real VLM reviews.
        # This path is impossible without enable_real_api + i_approve_budget.
        # Preserve at least TWO remaining HTTP attempts (Planner + Verifier).
        fit_reviews: List[Dict[str, Any]] = []
        if paid_api is not None and narrative_fit_required:
            from .story_narrative_fit_vlm import run_vlm_narrative_triplet_review
            from .story_paid_eval import provider_usage as _fit_provider_usage

            fit_store_by_key = narrative_fit_evidence_store.setdefault("by_key", {})
            for c in list(search_report.get("executable_first_live_candidates") or [])[:2]:
                if c.get("narrative_fit_reviewed"):
                    continue
                usage_before = _fit_provider_usage(paid_api)
                attempted = int(usage_before.get("http_attempts") or http_calls)
                # A contextual review costs one call; two are held for LLM
                # Planner and post-render dual-video Verifier.
                if int(inp.max_calls) - attempted < 3:
                    fit_reviews.append({
                        "candidate_id": c.get("candidate_id"),
                        "status": "skipped_reserved_planner_verifier_budget",
                    })
                    break
                if float(usage_before.get("est_cost_usd_real") or 0.0) >= float(inp.max_cost_usd):
                    break
                fit_dir = round_dir / "narrative_fit_vlm" / str(
                    c.get("candidate_id") or "candidate"
                ).replace("/", "_")[:64]
                fit_result = run_vlm_narrative_triplet_review(
                    paid_api,
                    source_mp4=inp.source_mp4,
                    source_sha=str(source_sha or ""),
                    candidate=c,
                    edl=working_edl,
                    out_dir=fit_dir,
                )
                fit_reviews.append({
                    "candidate_id": c.get("candidate_id"),
                    "ok": bool(fit_result.get("ok")),
                    "status": (fit_result.get("validation") or {}).get("status"),
                    "reason": (fit_result.get("validation") or {}).get("reason")
                    or fit_result.get("error"),
                    "path": str(fit_dir / "narrative_fit_review.json"),
                })
                if (
                    fit_result.get("ok")
                    and isinstance(fit_result.get("review"), dict)
                    and fit_result.get("source_review_key")
                ):
                    fit_store_by_key[str(fit_result["source_review_key"])] = fit_result["review"]

            usage_after = _fit_provider_usage(paid_api)
            http_calls = int(usage_after.get("http_attempts") or http_calls)
            est_cost = float(usage_after.get("est_cost_usd_real") or est_cost)
            round_rec["api_usage_after_narrative_fit"] = usage_after
            if fit_reviews and fit_store_by_key:
                # Re-run local Search to move supported triplets ahead of
                # heat-only events, and suppress visually rejected candidates.
                search_report = run_story_evidence_search(
                    diagnosis=diag,
                    edl=working_edl,
                    match_json=inp.match_json if inp.match_json.is_file() else None,
                    events_json=events_path,
                    feedback_context=fb_ctx,
                    first_live_evidence_store=first_live_evidence_store,
                    narrative_fit_evidence_store=narrative_fit_evidence_store,
                    source_sha256=source_sha,
                )
                search_report["events_json_resolved_via"] = (
                    "events_enriched"
                    if events_path is not None and _is_events_enriched_path(events_path)
                    else ("explicit_events_json" if events_path is not None else "match_json_only")
                )
            write_json(round_dir / "narrative_fit_vlm_summary.json", {
                "schema": "v3a_narrative_fit_vlm_summary_v1",
                "reviews": fit_reviews,
                "http_calls_after": http_calls,
                "estimated_cost_usd_after": est_cost,
                "claims_full_video_watch": False,
                "note": (
                    "Only explicitly authorized real VLM path uses API. "
                    "Fit evidence is a model judgment, not measured final quality."
                ),
            })
            if http_calls >= int(inp.max_calls) or est_cost >= float(inp.max_cost_usd):
                paid_api = None

        # Re-write queue after optional contextual VLM review, so review status
        # matches the final Search shortlist used by Planner.
        write_json(
            round_dir / "narrative_fit_review_queue.json",
            {
                "schema": "v3a_narrative_fit_review_queue_v1",
                "source_sha256": source_sha,
                "issue_candidates": [
                    {
                        "candidate_id": c.get("candidate_id"),
                        "issue_id": c.get("issue_id"),
                        "narrative_context": c.get("narrative_context"),
                        "narrative_fit_status": c.get("narrative_fit_status"),
                        "narrative_fit_reason": (c.get("narrative_fit") or {}).get("reason"),
                        "first_live_status": c.get("first_live_status"),
                    }
                    for c in (search_report.get("verified_candidates") or [])[:15]
                ],
                "vlm_contextual_reviews": fit_reviews,
                "note": (
                    "Missing triplet evidence never authorizes source-footage insertion. "
                    "A positive fit review is not a finished-cut quality result."
                ),
            },
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
        round_fx = None
        if inp.phase8_round_fixtures and round_idx - 1 < len(inp.phase8_round_fixtures):
            round_fx = inp.phase8_round_fixtures[round_idx - 1]
        if inp.fixture_revision:
            fixture_intents = inp.fixture_revision.get("revision_intents")
        if round_fx and round_fx.get("revision_intents") is not None:
            fixture_intents = round_fx.get("revision_intents")
        rev = plan_from_diagnosis(
            diag,
            observations=obs,
            offline=paid_api is None,
            fixture_intents=fixture_intents,
            search_results=search_report,
            feedback_context=fb_ctx,
            require_narrative_fit=narrative_fit_required,
            keep_unconfirmed_temporal_gap=narrative_fit_required,
            use_fullcut_learning=narrative_fit_required and fixture_intents is None,
            budget={
                "max_rounds": inp.max_rounds,
                "round_idx": round_idx,
                "max_calls": inp.max_calls,
                "max_cost_usd": inp.max_cost_usd,
                "http_calls_so_far": http_calls,
                "est_cost_usd_so_far": est_cost,
            },
        )
        write_json(round_dir / "planner_feedback_context.json", rev.get("feedback_context") or {})
        write_json(round_dir / "fullcut_edit_selection.json", rev.get("fullcut_edit_selection") or {})
        paid_api_was_used_for_planner = False
        if paid_api is not None and fixture_intents is None:
            from .story_paid_eval import provider_usage, run_llm_revision_planner

            try:
                llm_rev = run_llm_revision_planner(
                    paid_api,
                    diagnosis=diag,
                    vlm_critic=vlm_critic or {},
                    protected_goal_ids=list(diag.get("protected_goal_segment_ids") or []),
                    audit_dir=round_dir / "paid_api",
                    feedback_context=fb_ctx,
                    search_results=search_report,
                    allow_exploratory_proposals=bool(
                        inp.phase10_explore and round_idx == 1
                    ),
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
                llm_decision = str(llm_rev.get("decision") or "").upper()
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
                else:
                    # REAL_VLM mark_unresolved / KEEP / empty-mutate is an explicit
                    # refusal. Never silently retain Search-bound REVISE (real-run
                    # Round2 bug: mark_unresolved overridden → repeated 3504 apply).
                    note = "llm_unresolved_or_keep_only_honored"
                    if search_backed:
                        note = (
                            "llm_unresolved_or_keep_only_overrides_search_bound_revise"
                        )
                    rev = {
                        **rev,
                        "decision": llm_decision
                        if llm_decision in {"UNRESOLVED", "KEEP"}
                        else ("KEEP" if llm_acts <= {"keep"} and llm_acts else "UNRESOLVED"),
                        "revision_intents": llm_intents,
                        "rationale": llm_rev.get("rationale") or rev.get("rationale"),
                        "provider_mode": llm_rev.get("provider_mode"),
                        "offline": False,
                        "semantic_confirmation": bool(obs.get("semantic_provider_used")),
                        "llm_overlay_note": note,
                        "llm_rationale": llm_rev.get("rationale"),
                        "search_revise_suppressed_by_llm": bool(search_backed),
                        "suppressed_search_intents": list(rev.get("revision_intents") or [])
                        if search_backed
                        else [],
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
                # Paid planner failed → fail closed to UNRESOLVED (do not silently
                # re-apply Search revise; that caused duplicate invalid bridges).
                rev = {
                    **rev,
                    "decision": "UNRESOLVED",
                    "revision_intents": [],
                    "rationale": f"llm_revision_planner_failed:{(llm_rev or {}).get('error')}",
                    "offline": False,
                    "llm_overlay_note": (
                        "llm_revision_planner_failed_fail_closed_unresolved"
                        + ("; search_bound_revise_not_retained" if search_backed else "")
                    ),
                    "llm_error": (llm_rev or {}).get("error"),
                    "search_revise_suppressed_by_llm": bool(search_backed),
                }
            paid_api_was_used_for_planner = True
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
        if round_fx and round_fx.get("decision"):
            rev["decision"] = round_fx["decision"]
        if inp.fixture_revision and inp.fixture_revision.get("decision") and not (
            round_fx and round_fx.get("decision")
        ):
            rev["decision"] = inp.fixture_revision["decision"]
            if fixture_intents is None and rev["decision"] == "KEEP":
                rev["revision_intents"] = [
                    {
                        "intent_id": "fixture_keep",
                        "action": "keep",
                        "narrative_purpose": "fixture",
                    }
                ]
        if narrative_fit_required:
            # Both rule and model edits are candidates, never license to
            # remove unrelated cuts. Bind existing-footage repairs to exact
            # confirmed diagnosis and unprotected segment before applying.
            from .story_fullcut_learning import enforce_confirmed_nonadditive_edits

            rev = enforce_confirmed_nonadditive_edits(
                rev, diagnosis=diag, edl=working_edl,
                feedback_context=fb_ctx,
            )
            # Adding/replacing source footage additionally requires independent
            # first-live and BEFORE→CANDIDATE→AFTER narrative evidence.
            rev = enforce_narrative_fit_on_plan(
                rev, search_report=search_report, diagnosis=diag,
            )
            if fixture_intents is None:
                from .story_fullcut_learning import enforce_one_edit_per_round

                rev = enforce_one_edit_per_round(rev)
        write_json(round_dir / "revision_plan.json", rev)
        final_decision = str(rev.get("decision") or "UNRESOLVED")
        round_rec["decision"] = final_decision

        # Phase10-C is intentionally OUTSIDE the formal revision/Verifier/Best
        # loop: one source-bound, hypothesis-only candidate may be rendered
        # for blinded human feedback when the strict Planner cannot confirm a
        # defect. The working parent, production EDL, and release status remain
        # untouched. No new LLM/VLM call is made here.
        if inp.phase10_explore and round_idx == 1:
            exploratory_dir = round_dir / "phase10_exploratory"
            proposal = None
            proposal_source = None
            no_proposal_reason = "NO_AUTHORIZED_EXPLORATORY_PROPOSAL"
            if final_decision == "REVISE":
                no_proposal_reason = "FORMAL_REVISION_TAKES_PRIORITY"
            elif inp.phase10_explore_fixture is not None:
                data = inp.phase10_explore_fixture
                proposal = (
                    data.get("proposal") if isinstance(data.get("proposal"), dict)
                    else data
                )
                proposal_source = "FIXTURE"
            elif (
                paid_api_was_used_for_planner
                and isinstance(llm_rev, dict)
                and llm_rev.get("ok") is True
                and str(llm_rev.get("provider_mode") or "") == "real"
            ):
                raw_proposals = llm_rev.get("exploratory_intents") or []
                if raw_proposals and isinstance(raw_proposals[0], dict):
                    proposal = raw_proposals[0]
                    proposal_source = "REAL_LLM"
                else:
                    no_proposal_reason = "REAL_PLANNER_DECLINED_EXPLORATION"
            if proposal is not None and proposal_source is not None:
                from .story_exploratory_cut import execute_exploratory_trial

                try:
                    exp = execute_exploratory_trial(
                        baseline_edl=working_edl,
                        proposal=proposal,
                        source=proposal_source,
                        baseline_mp4=working_mp4,
                        source_mp4=inp.source_mp4,
                        story_plan=plan,
                        out_dir=exploratory_dir,
                        renderer=_render_edl,
                    )
                except Exception as exc:  # noqa: BLE001
                    exp = {
                        "schema": "v3a_phase10c_exploratory_candidate_v1",
                        "status": "BLOCKED",
                        "reason": f"exploratory_stage_exception:{type(exc).__name__}:{exc}",
                        "release_authorized": False,
                        "promote_best": False,
                        "candidate_rendered": False,
                        "blind_pair_status": "NO_CANDIDATE_PAIR",
                    }
                    write_json(exploratory_dir / "exploratory_trial.json", exp)
            else:
                exp = {
                    "schema": "v3a_phase10c_exploratory_candidate_v1",
                    "status": "SKIPPED",
                    "reason": no_proposal_reason,
                    "candidate_rendered": False,
                    "blind_pair_status": "NO_CANDIDATE_PAIR",
                    "release_authorized": False,
                    "promote_best": False,
                }
                write_json(exploratory_dir / "exploratory_trial.json", exp)
            # Immutable per-run evidence that a candidate was selected by a
            # REAL planner rather than a local fixture or heuristic. This is
            # a provenance assertion, not a quality or autonomy success claim.
            experiment_provenance = {
                "schema": "v3a_phase10d_model_autonomy_provenance_v1",
                "model_planner_called": bool(paid_api_was_used_for_planner),
                "planner_ok": bool(isinstance(llm_rev, dict) and llm_rev.get("ok") is True),
                "planner_provider_mode": (
                    llm_rev.get("provider_mode") if isinstance(llm_rev, dict) else None
                ),
                "exploration_source": exp.get("source"),
                "model_selected_target": (
                    proposal.get("target_segment_id")
                    if proposal_source == "REAL_LLM" and isinstance(proposal, dict)
                    else None
                ),
                "model_selected_action": (
                    proposal.get("action")
                    if proposal_source == "REAL_LLM" and isinstance(proposal, dict)
                    else None
                ),
                "real_model_proposal": bool(
                    proposal_source == "REAL_LLM"
                    and paid_api_was_used_for_planner
                    and isinstance(llm_rev, dict) and llm_rev.get("ok") is True
                ),
                "fixture_used": bool(inp.phase10_explore_fixture is not None),
                "candidate_rendered": bool(exp.get("candidate_rendered")),
                "candidate_story_quality": "UNVERIFIED",
                "formal_best": "UNCHANGED",
                "http_attempts_so_far": http_calls,
                "est_cost_usd_so_far": est_cost,
            }
            write_json(exploratory_dir / "phase10d_provenance.json", experiment_provenance)
            exp_summary = {
                k: exp.get(k)
                for k in (
                    "status", "reason", "source", "candidate_rendered",
                    "blind_pair_status", "blind_review_dir", "candidate_mp4",
                    "release_authorized", "promote_best",
                )
            }
            audit["phase10c_exploratory"] = exp_summary
            round_rec["phase10c_exploratory"] = exp_summary

        candidate_edl = [dict(r) for r in working_edl]
        apply_report: Dict[str, Any] = {"skipped": True}
        if final_decision == "REVISE":
            # Bind search-verified observations (real PTS) — never invent windows.
            candidate_edl, apply_report = apply_candidate_revision(
                working_edl,
                rev.get("revision_intents") or [],
                observations=search_obs,
            )
            applied_rows = list(apply_report.get("applied") or [])
            gates["revision_applied"] = any(
                a.get("status") in ("applied", "applied_evidence_bound")
                for a in applied_rows
            ) or (candidate_edl != working_edl)
            # If REVISE produced no EDL mutation, fail closed to UNRESOLVED.
            if candidate_edl == working_edl and not any(
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
            edl_diff(working_edl, candidate_edl) if candidate_edl != working_edl else {"changed": False},
        )

        # Safety: source PTS order must pass *before* any candidate render.
        pts_gate = check_source_pts_monotonic(candidate_edl)
        write_json(round_dir / "edl_pts_safety.json", pts_gate)
        round_rec["edl_pts_safety_ok"] = bool(pts_gate.get("ok"))
        if not pts_gate.get("ok"):
            # Fail closed: discard unsafe candidate EDL; do not render.
            apply_report = {
                **apply_report,
                "pts_safety_blocked_render": True,
                "pts_breaks": pts_gate.get("breaks") or [],
            }
            write_json(round_dir / "apply_report.json", apply_report)
            candidate_edl = [dict(r) for r in working_edl]
            final_decision = "UNRESOLVED"
            rev = {
                **rev,
                "decision": "UNRESOLVED",
                "normalize_note": "candidate_edl_failed_source_pts_monotonic_pre_render",
            }
            write_json(round_dir / "revision_plan.json", rev)
            round_rec["decision"] = final_decision
            gates["revision_applied"] = False

        candidate_mp4: Optional[Path] = None
        render_info: Dict[str, Any] = {"skipped": True}
        edl_changed = candidate_edl != working_edl
        cand_dedupe_render_blocked = False
        # Render when EDL actually changed (safety+authenticity gates still apply later).
        if (
            edl_changed
            and pts_gate.get("ok")
            and (final_decision == "REVISE" or inp.force_render_candidate)
        ):
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
        elif not pts_gate.get("ok"):
            render_info = {
                "skipped": True,
                "reason": "blocked_by_source_pts_monotonic_safety",
                "breaks": pts_gate.get("breaks") or [],
                "baseline_mp4": str(working_mp4),
                "parent_version_id": parent_version_id,
            }
            candidate_mp4 = working_mp4
            gates["candidate_rendered"] = False
            edl_changed = False
        elif not edl_changed:
            render_info = {
                "skipped": True,
                "reason": "edl_unchanged_reuse_working_parent",
                "baseline_mp4": str(working_mp4),
                "parent_version_id": parent_version_id,
            }
            candidate_mp4 = working_mp4
            gates["candidate_rendered"] = False
        write_json(round_dir / "candidate_render.json", render_info)

        # Verifier: dual-video vision when revising with a real candidate render.
        # Provenance is set by execution path only (P0-1) — never from model content.
        quality_overlay: Optional[Dict[str, Any]] = None
        verdict_provenance = "OFFLINE_RULE"
        used_test_fixture = False
        if round_fx and round_fx.get("fixture_verifier") is not None:
            quality_overlay = dict(round_fx.get("fixture_verifier") or {})
            used_test_fixture = True
        elif round_fx and any(
            k.startswith("phase8_")
            or k
            in (
                "quality_judgment",
                "issue_effect",
                "global_regression",
                "sent_frame_ids",
                "suggested_next_evidence",
                "focus_issue_id",
                "first_live_status",
            )
            for k in (round_fx.keys() if isinstance(round_fx, dict) else [])
        ):
            quality_overlay = {
                **(dict(inp.fixture_verifier) if inp.fixture_verifier else {}),
                **{
                    k: round_fx[k]
                    for k in round_fx
                    if k.startswith("phase8_")
                    or k
                    in (
                        "quality_judgment",
                        "quality_delta_vs_baseline",
                        "issue_effect",
                        "global_regression",
                        "sent_frame_ids",
                        "hard_vetoes",
                        "observed_changes",
                        "suggested_next_evidence",
                        "focus_issue_id",
                        "first_live_status",
                        "has_new_footage",
                        "pts_ok",
                        "intentional_replay",
                    )
                },
                "compared_parent_version_id": parent_version_id,
            }
            used_test_fixture = True
        elif inp.fixture_verifier is not None:
            quality_overlay = dict(inp.fixture_verifier)
            used_test_fixture = True
        if used_test_fixture:
            verdict_provenance = "FIXTURE"
        sent_frame_ids: List[str] = list(
            (quality_overlay or {}).get("sent_frame_ids") or []
        )
        vision_backed = bool(sent_frame_ids)
        llm_v = None
        real_provider_validated: Optional[Dict[str, Any]] = None
        fullcut_semantic_screen: Optional[Dict[str, Any]] = None
        if (
            paid_api is not None
            and final_decision == "REVISE"
            and edl_changed
            and candidate_mp4 is not None
            and candidate_mp4.is_file()
            and not used_test_fixture
        ):
            from .story_paid_eval import provider_usage, run_llm_verifier
            from .story_video_verifier import probe_video_pair

            try:
                # Provisional cases (pre-verifier) drive match-agnostic focus text.
                provisional_cases = build_revision_cases_for_round(
                    diagnosis=diag,
                    revision_plan=rev,
                    apply_report=apply_report,
                    search_report=search_report,
                    verifier_per_intent={},
                    pts_safety=pts_gate,
                    candidate_accepted=False,
                    match_tag=inp.match_id,
                )
                write_json(
                    round_dir / "paid_api" / "provisional_revision_cases.json",
                    provisional_cases,
                )
                llm_v = run_llm_verifier(
                    paid_api,
                    baseline_summary={"mp4": str(working_mp4), "version_id": parent_version_id},
                    candidate_summary={"mp4": str(candidate_mp4)},
                    edl_delta=edl_diff(working_edl, candidate_edl),
                    video_probe=probe_video_pair(
                        baseline_mp4=working_mp4, candidate_mp4=candidate_mp4
                    ),
                    audit_dir=round_dir / "paid_api",
                    baseline_mp4=working_mp4,
                    candidate_mp4=candidate_mp4,
                    baseline_edl=working_edl,
                    candidate_edl=candidate_edl,
                    work_dir=round_dir / "paid_api" / "dual_frames",
                    revision_cases=list(provisional_cases.get("cases") or []),
                )
                write_json(round_dir / "llm_verifier.json", llm_v)
                # Separate channel: real provider output is NEVER labeled FIXTURE.
                if (
                    isinstance(llm_v.get("validated"), dict)
                    and bool(llm_v.get("sent_frame_ids"))
                    and str(llm_v.get("provider_mode") or "") in ("real", "openai_compatible")
                ):
                    verdict_provenance = "REAL_VLM"
                    fullcut_semantic_screen = dict(
                        llm_v.get("fullcut_semantic_screen") or {}
                    )
                    # A few still pairs establish only a *screening hypothesis*.
                    # They cannot confirm audio/rhythm or exclude problems in
                    # unseen story beats. Never convert sampled-stills BETTER
                    # into formal IMPROVED / PROMOTE_BEST.
                    from .story_fullcut_semantic import constrain_sampled_verifier_payload

                    screened = str(fullcut_semantic_screen.get("status") or "")
                    real_provider_validated = constrain_sampled_verifier_payload(
                        dict(llm_v["validated"]), fullcut_semantic_screen,
                    )
                    quality_overlay = real_provider_validated
                    round_rec["fullcut_semantic_screen_status"] = (
                        screened or "NOT_EVALUATED"
                    )
                    write_json(
                        round_dir / "fullcut_semantic_screen.json",
                        fullcut_semantic_screen or {
                            "status": "UNVERIFIED",
                            "reason": "no_structured_fullcut_screen_from_real_vlm",
                            "authorizes_promote_best": False,
                        },
                    )
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

        if isinstance(quality_overlay, dict):
            quality_overlay = {
                **quality_overlay,
                "compared_parent_version_id": parent_version_id,
            }
            # Strip any content-claimed provenance / first-LIVE; path + ledger win.
            quality_overlay.pop("source_kind", None)
            quality_overlay.pop("first_live_status", None)
        # Per-window first-LIVE ledger: bind NEW source windows via EDL diff (not
        # apply_report alone). Missing EDL-new windows from the ledger ⇒ UNKNOWN.
        edl_diff_windows = diff_new_source_windows(
            working_edl,
            candidate_edl,
            source_sha=source_sha,
        )
        apply_windows: List[Dict[str, Any]] = []
        for a in apply_report.get("applied") or []:
            if not isinstance(a, dict):
                continue
            seg = a.get("segment") if isinstance(a.get("segment"), dict) else a
            mi, mo = seg.get("media_in"), seg.get("media_out")
            if mi is None or mo is None:
                bsw = a.get("bound_source_window") if isinstance(a.get("bound_source_window"), dict) else {}
                mi, mo = bsw.get("start"), bsw.get("end")
            if mi is None or mo is None:
                continue
            apply_windows.append(
                {
                    "source_pts_start": float(mi),
                    "source_pts_end": float(mo),
                    "segment_id": seg.get("segment_id") or a.get("new_segment_id"),
                    "evidence_status": seg.get("evidence_status") or a.get("evidence_status"),
                    "first_live_status": seg.get("first_live_status") or "NOT_VERIFIED",
                    "origin": "apply_report",
                }
            )
        # Merge by key; prefer EDL-diff as authoritative list of new footage.
        by_key: Dict[str, Dict[str, Any]] = {}
        for w in edl_diff_windows:
            by_key[str(w["key"])] = dict(w)
        for w in apply_windows:
            k = first_live_window_key(
                source_sha or "MISSING_SOURCE_SHA",
                float(w["source_pts_start"]),
                float(w["source_pts_end"]),
            )
            if k not in by_key:
                # Present in apply_report but not EDL-diff — still track.
                by_key[k] = {**w, "key": k, "source_sha": source_sha, "origin": "apply_only"}
            else:
                by_key[k] = {**by_key[k], **w, "key": k}
        new_windows = list(by_key.values())
        # Optional: build/attach local source inspection packs (zero HTTP).
        if inp.build_local_first_live_evidence and inp.source_mp4.is_file() and source_sha:
            for w in new_windows:
                k = str(w.get("key") or "")
                if k in (first_live_evidence_store.get("by_key") or {}):
                    w["validated_evidence"] = first_live_evidence_store["by_key"][k]
                    continue
                pack_dir = round_dir / "first_live_evidence" / k.replace("|", "_").replace(":", "-")
                pack = build_local_first_live_evidence_pack(
                    source_mp4=inp.source_mp4,
                    source_sha=str(source_sha),
                    pts_start=float(w["source_pts_start"]),
                    pts_end=float(w["source_pts_end"]),
                    out_dir=pack_dir,
                    segment_id=str(w.get("segment_id") or "") or None,
                )
                if pack.get("ok"):
                    first_live_evidence_store.setdefault("by_key", {})[k] = pack
                    w["validated_evidence"] = pack
        else:
            for w in new_windows:
                k = str(w.get("key") or "")
                if k in (first_live_evidence_store.get("by_key") or {}):
                    w["validated_evidence"] = first_live_evidence_store["by_key"][k]
        first_live_ledger = build_first_live_window_ledger(
            source_sha=source_sha,
            new_windows=new_windows,
            prior_ledger=first_live_prior_ledger,
            evidence_store=first_live_evidence_store,
        )
        write_json(round_dir / "first_live_window_ledger.json", first_live_ledger)
        write_json(round_dir / "edl_new_source_windows.json", {"windows": edl_diff_windows})
        # Carry verified windows forward for unchanged ancestor reuse.
        if first_live_ledger.get("windows"):
            prior_by = {
                str(w.get("key")): w
                for w in (first_live_prior_ledger.get("windows") or [])
                if isinstance(w, dict) and w.get("key")
            }
            for w in first_live_ledger["windows"]:
                if w.get("status") == "FIRST_LIVE_VERIFIED" and w.get("key"):
                    prior_by[str(w["key"])] = w
            first_live_prior_ledger = {
                "schema": "v3a_first_live_window_ledger_v1",
                "source_sha": source_sha or "MISSING_SOURCE_SHA",
                "windows": list(prior_by.values()),
            }
        omission = bool(edl_changed) and bool(edl_diff_windows) and not new_windows
        hard_safety_extra = {
            "pts_ok": bool(pts_gate.get("ok")),
            "has_new_footage": bool(edl_diff_windows) or bool(new_windows),
            "intentional_replay": any(
                a.get("is_replay") for a in (apply_report.get("applied") or []) if isinstance(a, dict)
            ),
            "first_live_ledger": first_live_ledger,
            "source_provenance_ok": bool(source_sha),
            "require_candidate_mp4": bool(edl_changed) and verdict_provenance != "FIXTURE",
            "edl_diff_window_omission": omission,
            "force_hard_safety": (quality_overlay or {}).get("phase8_safety")
            if verdict_provenance == "FIXTURE"
            else None,
        }
        # Soft quality payload may come from fixture OR real provider channel;
        # provenance is always the execution-path tag (never content-claimed).
        soft_payload = quality_overlay
        if verdict_provenance == "REAL_VLM" and real_provider_validated is not None:
            soft_payload = real_provider_validated
        vfix = verify_story_revision(
            story=story or plan,
            plan=plan,
            baseline_edl=working_edl,
            candidate_edl=candidate_edl,
            baseline_mp4=working_mp4,
            candidate_mp4=candidate_mp4,
            decision=final_decision,
            fixture=soft_payload,
            sent_frame_ids=sent_frame_ids,
            vision_backed=vision_backed if sent_frame_ids else False,
            verdict_provenance=verdict_provenance,
            hard_safety_extra=hard_safety_extra,
        )
        # Full-cut comparison: measured duration/EDL cost, no invented quality.
        # Keep separate from the existing safety and semantic verifier.
        from .story_fullcut_delta import compare_fullcut_edls
        fullcut_delta = compare_fullcut_edls(
            working_edl, candidate_edl,
        )
        fullcut_delta["baseline_mp4_path"] = (
            str(working_mp4) if working_mp4 else None
        )
        fullcut_delta["candidate_mp4_path"] = (
            str(candidate_mp4) if candidate_mp4 else None
        )
        fullcut_delta["baseline_mp4_exists"] = bool(
            working_mp4 and Path(working_mp4).is_file()
        )
        fullcut_delta["candidate_mp4_exists"] = bool(
            candidate_mp4 and Path(candidate_mp4).is_file()
        )
        fullcut_delta["semantic_screen_status"] = (
            (fullcut_semantic_screen or {}).get("status") or "NOT_EVALUATED"
        )
        fullcut_delta["fullcut_improvement_not_authenticated"] = True
        write_json(round_dir / "fullcut_delta_report.json", fullcut_delta)
        round_rec["fullcut_delta_report"] = str(
            round_dir / "fullcut_delta_report.json"
        )
        write_json(round_dir / "verifier_report.json", vfix)
        round_rec["verdict_provenance"] = verdict_provenance
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

        # Legacy accept field retained for Phase6/7 audit readers; loop uses phase8 policy.
        if vfix.get("candidate_accepted") and candidate_mp4 and candidate_mp4.is_file():
            round_rec["accepted"] = True
            metrics["candidate_accepted"] += 1
        else:
            round_rec["accepted"] = False
            round_rec["retain_baseline"] = True

        applied_bound = any(
            a.get("status") in ("applied", "applied_evidence_bound")
            for a in (apply_report.get("applied") or [])
        ) and not apply_report.get("pts_safety_blocked_render")
        q_delta = None
        val = (vfix.get("dual_verifier_full") or {}).get("validated") or {}
        if isinstance(val, dict):
            q_delta = val.get("quality_delta_vs_baseline")
        if q_delta is None:
            q_delta = (vfix.get("dual_verifier") or {}).get("quality_delta_vs_baseline")
        fixture_quality_disclaimer = None
        if inp.fixture_verifier and bool(vfix.get("candidate_accepted")):
            fixture_quality_disclaimer = (
                "synthetic_gate_wiring_not_real_quality - fixture verifier must not "
                "be reported as authentic story IMPROVED"
            )
            q_delta_for_status = None
        else:
            q_delta_for_status = q_delta
        rev_status = classify_revision_status(
            edl_changed=bool(edl_changed),
            applied_bound=bool(applied_bound),
            candidate_rendered=bool(gates.get("candidate_rendered")),
            candidate_accepted=bool(vfix.get("candidate_accepted")),
            vision_backed=bool(vfix.get("vision_backed")),
            semantic_passed=bool(gates.get("semantic_verification_passed")),
            quality_delta=q_delta_for_status,
            safety_ok=bool(pts_gate.get("ok")),
        )
        if fixture_quality_disclaimer:
            rev_status["fixture_quality_disclaimer"] = fixture_quality_disclaimer
            rev_status["IMPROVED"] = False
        write_json(round_dir / "revision_status.json", rev_status)
        round_rec["revision_status"] = rev_status
        for k in ("APPLIED", "VERIFIED", "IMPROVED"):
            if rev_status.get(k):
                audit["revision_status_totals"][k] = int(
                    audit["revision_status_totals"].get(k) or 0
                ) + 1

        # Phase 6: problem→revision→verify case bundle (always written).
        per_intent_v: Dict[str, Any] = {}
        for item in (
            (vfix.get("per_revision_judgments_recovered") or [])
            + list(((vfix.get("validated") or {}).get("per_revision_judgments") or []))
        ):
            if isinstance(item, dict):
                # recovered wrapper vs raw judgment
                j = item.get("judgment") if isinstance(item.get("judgment"), dict) else item
                key = str(j.get("intent_id") or j.get("revision_intent_id") or "")
                if key:
                    per_intent_v[key] = j
                if j.get("issue_id"):
                    per_intent_v[str(j["issue_id"])] = j
        case_bundle = build_revision_cases_for_round(
            diagnosis=diag,
            revision_plan=rev,
            apply_report=apply_report,
            search_report=search_report,
            verifier_per_intent=per_intent_v,
            pts_safety=pts_gate,
            candidate_accepted=bool(vfix.get("candidate_accepted")),
            match_tag=inp.match_id,
        )
        write_json(round_dir / "revision_cases.json", case_bundle)
        round_rec["revision_case_count"] = int(case_bundle.get("n_cases") or 0)
        audit["last_revision_cases"] = case_bundle

        cand_version_id = f"v{round_idx}"
        parent_edl_snapshot = [dict(r) for r in working_edl]
        parent_mp4_snapshot = working_mp4
        phase8_verdict = dict(vfix.get("phase8_verdict") or {})
        # Fixture overlays may force soft quality for control-flow tests; provenance stays FIXTURE.
        if used_test_fixture and round_fx:
            if round_fx.get("phase8_quality"):
                phase8_verdict["quality"] = str(round_fx["phase8_quality"]).upper()
            if round_fx.get("phase8_safety"):
                phase8_verdict["safety"] = str(round_fx["phase8_safety"]).upper()
            if round_fx.get("phase8_evidence"):
                phase8_verdict["evidence"] = str(round_fx["phase8_evidence"]).upper()
            if round_fx.get("issue_effect"):
                phase8_verdict["issue_effect"] = str(round_fx["issue_effect"]).upper()
            if round_fx.get("global_regression"):
                phase8_verdict["global_regression"] = str(round_fx["global_regression"]).upper()
            if round_fx.get("suggested_next_evidence") is not None:
                phase8_verdict["suggested_next_evidence"] = round_fx.get(
                    "suggested_next_evidence"
                )
            phase8_verdict["verdict_provenance"] = "FIXTURE"
            phase8_verdict["source_kind"] = "FIXTURE"
        else:
            phase8_verdict["verdict_provenance"] = verdict_provenance
            phase8_verdict["source_kind"] = verdict_provenance
        # Independent of LLM quality labels: sampled stills cannot establish
        # no global regression or certify complete audio/tempo continuity.
        # Explicit loop policy gate prevents unreviewed PROMOTE_BEST even if a
        # future payload accidentally reintroduces quality=BETTER.
        if verdict_provenance == "REAL_VLM":
            phase8_verdict["require_fullcut_semantic_gate"] = True
            phase8_verdict["fullcut_gate_promote"] = False
            phase8_verdict["fullcut_semantic_screen_status"] = (
                (fullcut_semantic_screen or {}).get("status") or "NOT_EVALUATED"
            )
            phase8_verdict["fullcut_semantic_observation_scope"] = (
                "aligned_sampled_finished_cuts_not_continuous_video"
            )
        # Compared against best requires parent==best OR an explicit vs-best observation.
        # Parent==working≠best alone is NOT a full-story best comparison (P1-F).
        best_id_now = str(loop_state.get("best_verified_version_id") or "v0")
        compared_against_best = parent_version_id == best_id_now
        vs_best_done = False
        if round_fx and round_fx.get("compared_against_best") is not None:
            # Fixture may only force this under FIXTURE provenance.
            if verdict_provenance == "FIXTURE":
                compared_against_best = bool(round_fx.get("compared_against_best"))
                vs_best_done = compared_against_best
        if parent_version_id != best_id_now and not vs_best_done:
            compared_against_best = False
            phase8_verdict["best_comparison_status"] = "PENDING_OR_SKIPPED"
            phase8_verdict["review_pending_vs_best"] = True
        else:
            phase8_verdict["best_comparison_status"] = (
                "COMPARED_PARENT_IS_BEST" if compared_against_best else "NOT_COMPARED"
            )
        phase8_verdict["compared_against_best"] = compared_against_best

        # Observation-grade evidence token: source SHA + PTS + frame-*byte* hashes /
        # manifest digest. Never round/version counters or plain frame_ids.
        primary_pts = None
        content_frame_hashes: List[str] = []
        manifest_digest = None
        for w in new_windows:
            ve = w.get("validated_evidence") if isinstance(w.get("validated_evidence"), dict) else None
            if ve and ve.get("manifest_digest"):
                primary_pts = [w.get("source_pts_start"), w.get("source_pts_end")]
                manifest_digest = str(ve.get("manifest_digest"))
                content_frame_hashes = [
                    str(f.get("sha256"))
                    for f in (ve.get("frames") or [])
                    if isinstance(f, dict) and looks_like_content_hash(f.get("sha256"))
                ][:4]
                break
        if primary_pts is None:
            for a in apply_report.get("applied") or []:
                if not isinstance(a, dict):
                    continue
                seg = a.get("segment") if isinstance(a.get("segment"), dict) else a
                if seg.get("media_in") is not None and seg.get("media_out") is not None:
                    primary_pts = [seg.get("media_in"), seg.get("media_out")]
                    break
        # sent_frame_ids are labels, not hashes — only keep if already content digests.
        for tok in list(sent_frame_ids or [])[:8]:
            if looks_like_content_hash(tok):
                content_frame_hashes.append(str(tok).replace("sha256:", "").lower())
        obs_token = make_observation_evidence_token(
            source_sha=source_sha,
            pts_start=(primary_pts or [None, None])[0],
            pts_end=(primary_pts or [None, None])[1],
            frame_hashes=content_frame_hashes or None,
            manifest_digest=manifest_digest,
        )
        fb_entries = normalize_feedback(
            case_bundle,
            vfix,
            apply_report,
            candidate_metadata={
                "parent_version_id": parent_version_id,
                "candidate_version_id": cand_version_id,
                "match_id": inp.match_id,
                "source_sha": source_sha,
                "evidence_token": obs_token,
                "frame_hashes": content_frame_hashes[:4],
                "manifest_digest": manifest_digest,
            },
            round_idx=round_idx,
            source_kind=str(phase8_verdict.get("verdict_provenance") or "OFFLINE_RULE"),
        )
        for e in fb_entries:
            if e.get("quality") in (None, "UNCERTAIN") and phase8_verdict.get("quality"):
                e["quality"] = phase8_verdict["quality"]
            if phase8_verdict.get("failure_class"):
                e["failure_class"] = phase8_verdict["failure_class"]
            if obs_token:
                e["evidence_token"] = obs_token
        # Convert SOURCE-BOUND two-finished-cut screening into actionable
        # *conditional* feedback for next round; never a ground-truth negative.
        # Production-only: offline fixtures must not masquerade as observation.
        from .story_fullcut_learning import extract_fullcut_learning

        fullcut_learning = extract_fullcut_learning(
            screen=fullcut_semantic_screen,
            revision_plan=rev,
            diagnosis=diag,
            parent_version_id=parent_version_id,
            candidate_version_id=cand_version_id,
            source_sha256=source_sha,
            round_idx=round_idx,
            provider_mode=verdict_provenance,
        )
        write_json(round_dir / "fullcut_revision_learning.json", fullcut_learning)
        feedback_store.extend(fb_entries)
        feedback_store.extend(fullcut_learning.get("entries") or [])
        round_rec["fullcut_feedback_entries"] = len(
            fullcut_learning.get("entries") or []
        )
        feedback_store.write_json(out / "phase8_feedback_memory.json")
        feedback_store.write_json(round_dir / "phase8_feedback_memory_snapshot.json")

        has_alt = bool(search_report.get("feedback_filtered_candidates")) or bool(
            (search_report.get("verified_candidates_before_feedback") or [])
            and not (search_report.get("verified_candidates") or [])
        )
        has_distinct = bool(search_report.get("verified_candidates")) and bool(
            search_report.get("feedback_filtered_candidates")
        )
        # A previously diagnosed, executable non-additive alternative must
        # remain available when the sampled full-cut screen rejects a bridge.
        # Otherwise SAME would STOP prematurely without trying that alternative.
        deferred_evidence_edits = list(
            (rev.get("fullcut_edit_selection") or {}).get("deferred") or []
        )
        deferred_evidence_edits.extend(
            list((rev.get("one_edit_apply_gate") or {}).get("deferred_intents") or [])
        )
        has_distinct = has_distinct or bool(deferred_evidence_edits)
        round_rec["deferred_confirmed_alternatives"] = len(deferred_evidence_edits)
        suggested = phase8_verdict.get("suggested_next_evidence")
        specific_reobserve = None
        if isinstance(suggested, dict) and suggested.get("question") and (
            suggested.get("story_window") or suggested.get("source_pts") or suggested.get("issue_id")
        ):
            specific_reobserve = suggested
        elif isinstance(suggested, Mapping) and suggested.get("question"):
            specific_reobserve = dict(suggested)
        transition = evaluate_round_transition(
            loop_state,
            {
                "version_id": cand_version_id,
                "parent_version_id": parent_version_id,
                "edl_changed": bool(edl_changed),
                "rendered": bool(gates.get("candidate_rendered")),
                "mp4_exists": bool(candidate_mp4 and Path(candidate_mp4).is_file()),
            },
            {
                **phase8_verdict,
                "hard_vetoes": list(vfix.get("hard_vetoes") or []),
                "phase8_verdict": phase8_verdict,
                "source_kind": phase8_verdict.get("verdict_provenance"),
                "compared_against_best": compared_against_best,
            },
            {
                "rounds_done": round_idx,
                "max_rounds": min(int(inp.max_rounds), MAX_ROUNDS),
                "http_calls": http_calls,
                "max_calls": inp.max_calls if paid_api is not None else None,
                "est_cost_usd": est_cost,
                "max_cost_usd": inp.max_cost_usd if paid_api is not None else None,
                "has_executable_revision": final_decision == "REVISE" and bool(edl_changed),
                "has_distinct_alternative": has_distinct or has_alt,
                "has_new_visual_target": bool(specific_reobserve),
                "specific_reobserve_target": specific_reobserve,
            },
        )
        write_json(round_dir / "phase8_transition.json", transition)
        loop_state = apply_transition(
            loop_state,
            transition,
            candidate_version={
                "parent_version_id": parent_version_id,
                "edl_path": str(round_dir / "candidate_edl.json"),
                "mp4_path": str(candidate_mp4) if candidate_mp4 else None,
                "safety": phase8_verdict.get("safety"),
                "quality": phase8_verdict.get("quality"),
                "source": phase8_verdict.get("source_kind") or "REAL",
                "semantic_evidence_refs": list(phase8_verdict.get("evidence_refs") or []),
                "round_idx": round_idx,
            },
        )
        version_edl[cand_version_id] = [dict(r) for r in candidate_edl]
        if candidate_mp4:
            version_mp4[cand_version_id] = Path(candidate_mp4)
        edl_digest = hashlib.sha256(
            json.dumps(candidate_edl, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        mp4_digest = (
            sha256_file(Path(candidate_mp4))
            if candidate_mp4 and Path(candidate_mp4).is_file()
            else None
        )
        version_snapshots[cand_version_id] = {
            "version_id": cand_version_id,
            "parent_version_id": parent_version_id,
            "round_idx": round_idx,
            "edl_path": str(round_dir / "candidate_edl.json"),
            "mp4_path": str(candidate_mp4) if candidate_mp4 else None,
            "source_sha256": source_sha,
            "edl_sha256": edl_digest,
            "mp4_sha256": mp4_digest,
            "first_live_ledger": first_live_ledger,
            "evidence_token": obs_token,
            "safety": phase8_verdict.get("safety"),
            "quality": phase8_verdict.get("quality"),
            "evidence": phase8_verdict.get("evidence"),
            "verdict_provenance": phase8_verdict.get("verdict_provenance"),
            "goal_protection_intact": bool(
                (vfix.get("goal_protection") or {}).get("intact", True)
            ),
            "semantic_verification_passed": bool(gates.get("semantic_verification_passed")),
            "candidate_rendered": bool(gates.get("candidate_rendered")),
            "hard_vetoes": list(vfix.get("hard_vetoes") or []),
            "diagnosis_issues": list(diag.get("issues") or []),
            "gates": {
                "candidate_rendered": bool(gates.get("candidate_rendered")),
                "semantic_verification_passed": bool(gates.get("semantic_verification_passed")),
                "revision_applied": bool(gates.get("revision_applied")),
            },
            "phase8_verdict": phase8_verdict,
            "compared_against_best": compared_against_best,
            "best_comparison_status": phase8_verdict.get("best_comparison_status"),
            "pts_ok": bool(pts_gate.get("ok")),
        }

        write_json(round_dir / "version_snapshot.json", version_snapshots[cand_version_id])

        # Update working / best pointers from transition (never from accept alone).
        next_action = str(transition.get("next_action") or "")
        if transition.get("promote") and next_action == "PROMOTE_BEST":
            best_edl = [dict(r) for r in candidate_edl]
            if candidate_mp4 and Path(candidate_mp4).is_file():
                best_mp4 = Path(candidate_mp4)
            working_edl = [dict(r) for r in best_edl]
            working_mp4 = best_mp4
            pending_reobserve = None
        elif (
            next_action == "CONTINUE_WORKING"
            and edl_changed
            and gates.get("candidate_rendered")
            and candidate_mp4
            and Path(candidate_mp4).is_file()
        ):
            working_edl = [dict(r) for r in candidate_edl]
            working_mp4 = Path(candidate_mp4)
            pending_reobserve = None
        elif next_action == "REOBSERVE" and specific_reobserve:
            pending_reobserve = {
                **dict(specific_reobserve),
                "pending_candidate_version_id": cand_version_id,
                "round_idx": round_idx,
                "parent_version_id": parent_version_id,
                "candidate_mp4": str(candidate_mp4) if candidate_mp4 else None,
                "source_sha256": source_sha,
                "bound_once": True,
            }
            write_json(round_dir / "reobserve_target.json", pending_reobserve)
            # P1-E: extract target-specific frame manifest (not JSON-only "reobserve").
            reobs_dir = round_dir / "directed_reobserve"
            reobs_dir.mkdir(parents=True, exist_ok=True)
            pts = specific_reobserve.get("source_pts") or specific_reobserve.get("story_window")
            frame_manifest = {
                "schema": "v3a_directed_reobserve_manifest_v1",
                "source_sha256": source_sha,
                "candidate_version_id": cand_version_id,
                "question": specific_reobserve.get("question"),
                "source_pts": pts,
                "frames": [],
                "new_evidence_extracted": False,
                "status": "NEEDS_VLM_BUDGET",
            }
            # Offline / zero-HTTP: record ordered PTS samples + hashes of existing
            # candidate bytes when available; do not claim visual verification.
            if candidate_mp4 and Path(candidate_mp4).is_file() and pts and len(pts) >= 2:
                try:
                    t0, t1 = float(pts[0]), float(pts[1])
                    samples = [
                        round(t0 + (t1 - t0) * x, 3) for x in (0.15, 0.5, 0.85)
                    ]
                    frame_manifest["frames"] = [
                        {
                            "frame_id": f"reobs_{cand_version_id}_{i}",
                            "source_pts_sec": s,
                            "role": "directed_reobserve_sample",
                        }
                        for i, s in enumerate(samples)
                    ]
                    frame_manifest["candidate_mp4_sha256"] = sha256_file(Path(candidate_mp4))
                    frame_manifest["new_evidence_extracted"] = bool(frame_manifest["frames"])
                    frame_manifest["status"] = (
                        "FRAME_MANIFEST_READY_AWAITING_VLM"
                        if paid_api is not None
                        else "NEEDS_VLM_BUDGET"
                    )
                except (TypeError, ValueError):
                    frame_manifest["status"] = "STOP_UNVERIFIED"
            else:
                frame_manifest["status"] = "STOP_UNVERIFIED"
                frame_manifest["reason"] = "missing_candidate_mp4_or_pts_target"
            write_json(reobs_dir / "target.json", pending_reobserve)
            write_json(reobs_dir / "frame_manifest.json", frame_manifest)
            write_json(
                reobs_dir / "status.json",
                {
                    "reobserve_is_not_json_only": True,
                    "new_evidence_extracted": frame_manifest["new_evidence_extracted"],
                    "status": frame_manifest["status"],
                    "note": (
                        "Directed reobserve bound to one pending candidate. "
                        "Without new verified observation, do not unlock identical PTS retry."
                    ),
                },
            )
            round_rec["directed_reobserve"] = frame_manifest
            if frame_manifest["status"] == "STOP_UNVERIFIED":
                transition = {
                    **transition,
                    "next_action": "STOP_NO_ACTION",
                    "stop_reason": "STOP_UNVERIFIED",
                    "continue_allowed": False,
                    "reason_codes": list(transition.get("reason_codes") or [])
                    + ["reobserve_without_new_evidence"],
                }
                write_json(round_dir / "phase8_transition.json", transition)
                loop_state["stop_reason"] = "STOP_UNVERIFIED"
                pending_reobserve = None
        elif next_action in ("REPLAN_FROM_BEST", "STOP_SAFETY", "STOP_NO_ACTION", "STOP_BUDGET"):
            bid = str(loop_state.get("best_verified_version_id") or "v0")
            working_edl = [dict(r) for r in (version_edl.get(bid) or best_edl)]
            working_mp4 = version_mp4.get(bid) or best_mp4
            pending_reobserve = None

        write_loop_state(loop_state, out / "phase8_loop_state.json")
        write_loop_state(loop_state, round_dir / "phase8_loop_state.json")
        audit["phase8_loop_state"] = loop_state
        audit["phase8_feedback_memory"] = feedback_store.to_dict()
        round_rec["phase8_transition"] = transition
        round_rec["phase8_verdict"] = phase8_verdict
        round_rec["parent_version_id"] = parent_version_id
        round_rec["candidate_version_id"] = cand_version_id
        round_rec["working_version_id"] = loop_state.get("working_version_id")
        round_rec["best_verified_version_id"] = loop_state.get("best_verified_version_id")

        write_json(round_dir / "parent_working_edl.json", parent_edl_snapshot)
        if edl_changed and candidate_mp4 and candidate_mp4.is_file() and gates.get("candidate_rendered"):
            last_candidate_bundle = {
                "round": round_idx,
                "round_dir": str(round_dir),
                "baseline_mp4": str(parent_mp4_snapshot),
                "baseline_edl": str(round_dir / "parent_working_edl.json"),
                "parent_version_id": parent_version_id,
                "candidate_version_id": cand_version_id,
                "initial_baseline_mp4": str(initial_dir / "story_clean.mp4"),
                "initial_baseline_edl": str(initial_dir / "candidate_edl.json"),
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
                "phase8_verdict": phase8_verdict,
                "phase8_transition": transition,
                "revision_status": rev_status,
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
            "phase8_verdict": phase8_verdict,
            "compared_parent_version_id": parent_version_id,
            "version_id": cand_version_id,
        }
        audit["last_diagnosis_issues"] = list(diag.get("issues") or [])
        audit["edl_changed_any"] = bool(audit.get("edl_changed_any")) or bool(edl_changed)

        # Stop only for reasoned policy / budget — never solely because accept=False.
        continue_allowed = bool(transition.get("continue_allowed", True))
        if next_action.startswith("STOP") or transition.get("stop_reason") == "STOP_BUDGET":
            loop_state["stop_reason"] = transition.get("stop_reason") or next_action
            loop_state["delivery_version_id"] = loop_state.get("best_verified_version_id")
            write_loop_state(loop_state, out / "phase8_loop_state.json")
            break
        if not continue_allowed:
            loop_state["stop_reason"] = transition.get("stop_reason") or "STOP_NO_FURTHER_ROUNDS"
            loop_state["delivery_version_id"] = loop_state.get("best_verified_version_id")
            write_loop_state(loop_state, out / "phase8_loop_state.json")
            break
        if final_decision in ("KEEP", "UNRESOLVED") and not edl_changed:
            if next_action in ("CONTINUE_WORKING", "REOBSERVE", "PROMOTE_BEST"):
                pass
            else:
                loop_state["stop_reason"] = (
                    transition.get("stop_reason")
                    or ("STOP_NO_ACTION_KEEP" if final_decision == "KEEP" else "STOP_NO_ACTION")
                )
                loop_state["delivery_version_id"] = loop_state.get("best_verified_version_id")
                write_loop_state(loop_state, out / "phase8_loop_state.json")
                break

    # Final delivery staging — selected best_verified version only.
    delivery_vid = str(
        loop_state.get("delivery_version_id")
        or loop_state.get("best_verified_version_id")
        or "v0"
    )
    if delivery_vid in version_edl:
        best_edl = [dict(r) for r in version_edl[delivery_vid]]
    if delivery_vid in version_mp4 and Path(version_mp4[delivery_vid]).is_file():
        best_mp4 = Path(version_mp4[delivery_vid])
    loop_state["delivery_version_id"] = delivery_vid
    if not loop_state.get("stop_reason"):
        loop_state["stop_reason"] = "LOOP_COMPLETED"
    write_loop_state(loop_state, out / "phase8_loop_state.json")
    feedback_store.write_json(out / "phase8_feedback_memory.json")
    audit["phase8_loop_state"] = loop_state
    audit["phase8_feedback_memory"] = feedback_store.to_dict()
    audit["phase8_delivery_version_id"] = delivery_vid

    final_dir = out / "99_final"
    final_dir.mkdir(parents=True, exist_ok=True)
    final_mp4 = final_dir / "story_final.mp4"
    _copy_or_link(best_mp4, final_mp4)
    write_json(final_dir / "final_edl.json", best_edl)
    write_json(
        final_dir / "delivery_version_ref.json",
        {
            "delivery_version_id": delivery_vid,
            "best_verified_version_id": loop_state.get("best_verified_version_id"),
            "best_verification_tier": loop_state.get("best_verification_tier"),
            "stop_reason": loop_state.get("stop_reason"),
            "mp4": str(best_mp4),
            "formal_improved": loop_state.get("best_verification_tier") == "VERIFIED_BETTER"
            and (loop_state.get("versions") or {}).get(delivery_vid, {}).get("source")
            not in ("FIXTURE", "OFFLINE_FIXTURE", "PHASE7_HISTORICAL_ARTIFACT"),
        },
    )
    write_json(final_dir / "story_timeline.json", build_story_timeline(best_edl))
    align = timeline_mp4_aligned(edl=best_edl, mp4=final_mp4, tolerance_sec=2.0)
    write_json(final_dir / "timeline_mp4_alignment.json", align)

    gates["final_mp4_exists"] = final_mp4.is_file()
    gates["workflow_completed"] = True

    last_v = audit.get("last_verifier") or {}
    # P0-5: release ONLY from selected delivery_version snapshot — never last_* gates.
    delivery_snap = dict(version_snapshots.get(delivery_vid) or {})
    delivery_meta = (loop_state.get("versions") or {}).get(delivery_vid) or {}
    delivery_gates = dict(delivery_snap.get("gates") or {})
    if delivery_vid == "v0" or loop_state.get("best_verification_tier") == "BASELINE_UNVERIFIED":
        release_accepted = False
        release_decision = "KEEP"
        release_edl_changed = False
        release_vetoes: List[Any] = []
        release_goals_intact = True
        release_diag = []
        release_gates_for_auth = {
            **gates,
            "candidate_rendered": False,
            "semantic_verification_passed": False,
        }
    else:
        release_accepted = (
            str(delivery_snap.get("quality") or "").upper() == "BETTER"
            and str(delivery_snap.get("verdict_provenance") or "") == "REAL_VLM"
            and bool(delivery_snap.get("semantic_verification_passed"))
            and bool(delivery_snap.get("compared_against_best"))
        )
        release_decision = "REVISE" if release_accepted else "KEEP"
        release_edl_changed = True
        release_vetoes = list(delivery_snap.get("hard_vetoes") or [])
        release_goals_intact = bool(delivery_snap.get("goal_protection_intact", True))
        release_diag = list(delivery_snap.get("diagnosis_issues") or [])
        release_gates_for_auth = {
            **gates,
            "candidate_rendered": bool(delivery_gates.get("candidate_rendered")),
            "semantic_verification_passed": bool(
                delivery_gates.get("semantic_verification_passed")
            ),
            "revision_applied": bool(delivery_gates.get("revision_applied", True)),
        }
    release = compute_release_authorization(
        gates=release_gates_for_auth,
        decision=release_decision,
        edl_changed=bool(release_edl_changed),
        candidate_accepted=bool(release_accepted),
        goal_anchors_intact=bool(release_goals_intact),
        hard_vetoes=release_vetoes,
        final_mp4=final_mp4,
        final_edl=best_edl,
        diagnosis_issues=release_diag,
        timeline_aligned=bool(align.get("aligned")),
        unresolved_critical=False,
    )
    release["delivery_version_id"] = delivery_vid
    release["delivery_snapshot"] = {
        k: delivery_snap.get(k)
        for k in (
            "version_id",
            "parent_version_id",
            "safety",
            "quality",
            "verdict_provenance",
            "semantic_verification_passed",
            "candidate_rendered",
            "compared_against_best",
            "mp4_path",
            "edl_path",
        )
    }
    release["delivery_source"] = delivery_snap.get("verdict_provenance") or delivery_meta.get(
        "source"
    )
    release["last_round_ignored_for_release"] = True
    release["last_verifier_version_id"] = last_v.get("version_id")
    release["note_phase8"] = (
        "Release authorization is version-specific from delivery snapshot; "
        "a later rejected/uncertain round does not revoke or grant release of selected best."
    )
    prov = str(delivery_snap.get("verdict_provenance") or delivery_meta.get("source") or "").upper()
    if prov in ("FIXTURE", "OFFLINE_FIXTURE", "PHASE7_HISTORICAL_ARTIFACT", "OFFLINE_RULE"):
        release["release_authorized"] = False
        release.setdefault("reasons", []).append("fixture_or_offline_source_not_releasable")
    # P1-F: verify immutable digests still match delivery bytes at release time.
    digest_check = {
        "source_sha256_expected": delivery_snap.get("source_sha256"),
        "edl_sha256_expected": delivery_snap.get("edl_sha256"),
        "mp4_sha256_expected": delivery_snap.get("mp4_sha256"),
        "edl_sha256_now": None,
        "mp4_sha256_now": None,
        "ok": True,
        "reasons": [],
    }
    try:
        digest_check["edl_sha256_now"] = hashlib.sha256(
            json.dumps(best_edl, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        if delivery_snap.get("edl_sha256") and digest_check["edl_sha256_now"] != delivery_snap.get("edl_sha256"):
            digest_check["ok"] = False
            digest_check["reasons"].append("edl_digest_mismatch_at_release")
    except Exception as exc:  # noqa: BLE001
        digest_check["ok"] = False
        digest_check["reasons"].append(f"edl_digest_error:{type(exc).__name__}")
    if best_mp4.is_file():
        digest_check["mp4_sha256_now"] = sha256_file(best_mp4)
        if delivery_snap.get("mp4_sha256") and digest_check["mp4_sha256_now"] != delivery_snap.get("mp4_sha256"):
            digest_check["ok"] = False
            digest_check["reasons"].append("mp4_digest_mismatch_at_release")
    release["delivery_digest_check"] = digest_check
    if not digest_check["ok"]:
        release["release_authorized"] = False
        release.setdefault("reasons", []).extend(digest_check["reasons"])
    if delivery_snap.get("best_comparison_status") == "PENDING_OR_SKIPPED":
        release.setdefault("reasons", []).append("working_variant_not_compared_against_best")
        release["review_pending_vs_best"] = True
    gates["release_authorized"] = bool(release.get("release_authorized"))
    write_json(final_dir / "release_gate.json", release)
    write_json(out / "phase8_version_snapshots.json", version_snapshots)

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

    events_for_fl = resolve_events_json_for_agent(
        events_json=inp.events_json,
        phase5_dir=inp.phase5_dir,
        out_dir=out,
    )

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
        "n_strict_complete": lineage.get("n_strict_complete"),
        "n_inferred": lineage.get("n_inferred"),
        "n_unresolved": lineage.get("n_unresolved"),
        "n_structurally_traced_to_mp4": lineage.get("n_structurally_traced_to_mp4"),
        "duplicate_segment_ids": lineage.get("duplicate_segment_ids"),
        "prior_source_trust": evidence_pack.get("prior_source_trust"),
        "candidate_delivery_binding": evidence_pack.get("candidate_delivery_binding"),
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
