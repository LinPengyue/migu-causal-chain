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
    # Optional frozen V3-R baseline for regression (Oman etc.)
    phase5_dir: Optional[Path] = None
    initial_story_mp4: Optional[Path] = None
    baseline_edl: Optional[Path] = None
    story_plan: Optional[Path] = None
    t01_story: Optional[Path] = None
    skip_vlm: bool = True
    enable_real_api: bool = False
    i_approve_budget: bool = False
    force_render_initial: bool = False
    force_render_candidate: bool = False
    smoke_render: bool = True
    fixture_revision: Optional[Mapping[str, Any]] = None
    fixture_verifier: Optional[Mapping[str, Any]] = None
    max_rounds: int = MAX_ROUNDS


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
    """Locate or stage V3-R baseline artifacts under out_dir/00_baseline."""
    base_dir = inp.out_dir / "00_baseline"
    base_dir.mkdir(parents=True, exist_ok=True)
    phase5 = inp.phase5_dir
    edl_path = inp.baseline_edl
    plan_path = inp.story_plan
    mp4_path = inp.initial_story_mp4
    t01_path = inp.t01_story

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
        "reuse_frozen_v3r": bool(phase5 and not missing),
        "paths": {},
    }

    if missing:
        staged["ok"] = False
        staged["note"] = (
            "Fresh V3-R generation from match JSON is not invoked in offline dry-run; "
            "provide --phase5-dir or explicit baseline paths. Full fresh V3-R remains "
            "available via fresh_e2e_cli / closed_loop when authorized."
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
        "inputs": {
            "match_json": str(inp.match_json),
            "source_mp4": str(inp.source_mp4),
            "phase5_dir": str(inp.phase5_dir) if inp.phase5_dir else None,
            "skip_vlm": inp.skip_vlm,
            "enable_real_api": inp.enable_real_api,
            "i_approve_budget": inp.i_approve_budget,
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
    if inp.enable_real_api:
        audit["error"] = (
            "real_api_not_invoked_in_this_build_pass; complete offline path first "
            "and obtain fresh budget authorization"
        )
        # Continue offline rather than calling paid APIs.
        inp = StoryE2EInputs(**{**inp.__dict__, "enable_real_api": False, "skip_vlm": True})

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
        # Observe
        obs = observe_layers(
            story_mp4=best_mp4,
            source_mp4=inp.source_mp4,
            edl=best_edl,
            work_dir=round_dir / "observe",
            diagnosis_issues=diag.get("issues") or [],
            skip_vlm=True if not inp.enable_real_api else inp.skip_vlm,
        )
        diag = merge_observation_into_diagnosis(diag, obs)
        write_diagnosis(round_dir / "story_diagnosis.json", diag)
        gates["story_diagnosis_valid"] = bool(diag.get("story_diagnosis_valid"))
        round_rec["diagnosis_issue_count"] = len(diag.get("issues") or [])
        round_rec["semantic_observation_claimed"] = diag.get("semantic_observation_claimed")

        # Revision plan
        fixture_intents = None
        if inp.fixture_revision:
            fixture_intents = inp.fixture_revision.get("revision_intents")
            if inp.fixture_revision.get("decision"):
                # allow fixture to force decision path via intents
                pass
        rev = plan_from_diagnosis(
            diag,
            observations=obs,
            offline=not inp.enable_real_api,
            fixture_intents=fixture_intents,
        )
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

        # Verifier
        vfix = verify_story_revision(
            story=story or plan,
            plan=plan,
            baseline_edl=best_edl,
            candidate_edl=candidate_edl,
            baseline_mp4=best_mp4,
            candidate_mp4=candidate_mp4,
            decision=final_decision,
            fixture=inp.fixture_verifier,
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
