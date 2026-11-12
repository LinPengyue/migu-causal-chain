"""Blinded, zero-paid V3-A repair challenge using real failed story cuts.

This is an evaluation harness, NOT an automatic goal-repair algorithm.
Correct EDL is used only by the test constructor / independent scorer.
The Agent receives an isolated failed EDL, its matching failed MP4, the
allowed events JSON, and the source MP4. No golden cut is passed to V3-A.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "v3a_blind_story_repair_challenge_v1"


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(path: Path) -> list[dict[str, Any]]:
    obj = _read(path)
    if isinstance(obj, list):
        rows = obj
    elif isinstance(obj, dict):
        rows = next((obj[k] for k in ("segments", "edl", "rows") if isinstance(obj.get(k), list)), None)
    else:
        rows = None
    if not isinstance(rows, list) or not all(isinstance(x, dict) for x in rows):
        raise ValueError("EDL must contain a list of segment objects")
    return [dict(x) for x in rows]


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _protect_input_paths(case_dir: Path, sources: Sequence[Path]) -> None:
    output = (case_dir / "agent_input").resolve()
    for source in sources:
        source = Path(source).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        # Never overwrite or use a historical reference inside our staging area.
        if source == output or output in source.parents:
            raise ValueError("input_source_inside_agent_staging_dir")


def prepare_controlled(
    *,
    complete_edl: Path,
    story_plan: Path,
    source_mp4: Path,
    events_json: Path,
    case_dir: Path,
    omitted_role: str,
    input_mode: str = "HUMAN_ATOM_ENRICHED_DEV",
    renderer=None,
) -> dict[str, Any]:
    """Deliberately omit one active goal action, and render a *matching* MP4.

    A-case: P14 upstream may still contain an annotated goal; this tests only
    EDL-level recovery. The target's reference row is private, never included
    in the input EDL, run arguments or V3-A prompts.
    """
    if input_mode not in ("HUMAN_ATOM_ENRICHED_DEV", "RAW_EVENTS_ONLY"):
        raise ValueError("unsupported_input_mode")
    case_dir = Path(case_dir)
    if case_dir.exists() and any(case_dir.iterdir()):
        raise FileExistsError("case_dir_must_be_new_and_empty")
    _protect_input_paths(case_dir, [complete_edl, story_plan, source_mp4, events_json])
    complete = _rows(complete_edl)
    targets = [
        r for r in complete if r.get("include_in_cut", True)
        and str(r.get("role") or "") == omitted_role
        and "goal_action" in omitted_role
    ]
    if len(targets) != 1:
        raise ValueError("expected_exactly_one_active_goal_action_target")
    target = targets[0]
    if target.get("media_in") is None or target.get("media_out") is None:
        raise ValueError("target_goal_action_lacks_media_window")
    broken = [
        r for r in complete if str(r.get("segment_id")) != str(target["segment_id"])
    ]
    if len(broken) != len(complete) - 1:
        raise ValueError("target_segment_id_is_ambiguous")

    phase5 = case_dir / "agent_input" / "04_phase5"
    phase5.mkdir(parents=True, exist_ok=True)
    _write(phase5 / "candidate_edl.json", broken)
    shutil.copy2(story_plan, phase5 / "story_plan.json")
    shutil.copy2(events_json, case_dir / "agent_input" / "events.json")
    if renderer is None:
        from .story_e2e_agent import _render_edl
        renderer = _render_edl
    result = renderer(
        plan=_read(story_plan), video=source_mp4, edl=broken,
        out_dir=phase5 / "render_scratch",
    )
    output_mp4 = Path(str(result.get("story_clean") or ""))
    if not result.get("ok") or not output_mp4.is_file():
        raise RuntimeError("failed_to_render_omitted_goal_story_mp4")
    shutil.move(str(output_mp4), str(phase5 / "story_clean.mp4"))

    # Private grader only. The Agent cannot see this via its fixed inputs.
    truth = {
        "schema": SCHEMA,
        "variant": "CONTROLLED_EDL_OMISSION",
        "reference_edl_sha256": _digest(complete),
        "broken_edl_sha256": _digest(broken),
        "reference_action": target,
        "input_mode": input_mode,
        "note": "Private to scorer. Never pass private_eval to the Agent.",
    }
    _write(case_dir / "private_eval" / "truth.json", truth)
    manifest = {
        "schema": SCHEMA,
        "variant": "CONTROLLED_EDL_OMISSION",
        "input_mode": input_mode,
        "phase5_dir": str(phase5),
        "events_json": str(case_dir / "agent_input" / "events.json"),
        "source_mp4": str(Path(source_mp4).resolve()),
        "reference_not_available_to_agent": True,
        "no_paid_http": True,
        "upstream_plan_may_contain_goal_information": True,
        "goal_omission_evaluation_scope": "EDL_REPAIR_ONLY_NOT_RAW_VIDEO_DISCOVERY",
    }
    _write(case_dir / "run_manifest.json", manifest)
    return manifest


def prepare_clean_control(
    *,
    complete_edl: Path,
    story_plan: Path,
    baseline_mp4: Path,
    source_mp4: Path,
    events_json: Path,
    case_dir: Path,
) -> dict[str, Any]:
    """No-defect negative control: the Agent should not invent repairs."""
    case_dir = Path(case_dir)
    if case_dir.exists() and any(case_dir.iterdir()):
        raise FileExistsError("case_dir_must_be_new_and_empty")
    _protect_input_paths(
        case_dir, [complete_edl, story_plan, baseline_mp4, source_mp4, events_json]
    )
    phase5 = case_dir / "agent_input" / "04_phase5"
    phase5.mkdir(parents=True, exist_ok=True)
    shutil.copy2(complete_edl, phase5 / "candidate_edl.json")
    shutil.copy2(story_plan, phase5 / "story_plan.json")
    shutil.copy2(baseline_mp4, phase5 / "story_clean.mp4")
    shutil.copy2(events_json, case_dir / "agent_input" / "events.json")
    manifest = {
        "schema": SCHEMA, "variant": "CLEAN_NO_DEFECT_CONTROL",
        "input_mode": "HUMAN_ATOM_ENRICHED_DEV",
        "phase5_dir": str(phase5),
        "events_json": str(case_dir / "agent_input" / "events.json"),
        "source_mp4": str(Path(source_mp4).resolve()),
        "reference_not_available_to_agent": True,
        "no_paid_http": True,
    }
    _write(case_dir / "run_manifest.json", manifest)
    return manifest


def prepare_historical(
    *,
    failed_phase5: Path,
    source_mp4: Path,
    raw_events_json: Path,
    case_dir: Path,
) -> dict[str, Any]:
    """Copy a genuine P11/P12/P13 failed EDL and MP4; no P14 artefacts read.

    Historical case is an upstream-input-loss test. The independent reference
    must be supplied to the scorer AFTER the Agent has produced its output.
    """
    case_dir = Path(case_dir)
    if case_dir.exists() and any(case_dir.iterdir()):
        raise FileExistsError("case_dir_must_be_new_and_empty")
    phase5 = Path(failed_phase5)
    paths = [phase5 / x for x in ("candidate_edl.json", "story_plan.json", "story_clean.mp4")]
    _protect_input_paths(case_dir, paths + [source_mp4, raw_events_json])
    target = case_dir / "agent_input" / "04_phase5"
    target.mkdir(parents=True, exist_ok=True)
    for p in paths:
        shutil.copy2(p, target / p.name)
    shutil.copy2(raw_events_json, case_dir / "agent_input" / "events.json")
    manifest = {
        "schema": SCHEMA,
        "variant": "HISTORICAL_RAW_ONLY",
        "input_mode": "RAW_EVENTS_ONLY",
        "phase5_dir": str(target),
        "events_json": str(case_dir / "agent_input" / "events.json"),
        "source_mp4": str(Path(source_mp4).resolve()),
        "reference_not_available_to_agent": True,
        "no_paid_http": True,
    }
    _write(case_dir / "run_manifest.json", manifest)
    return manifest


def _run_dir(case_dir: Path, run_id: str | None = None) -> Path:
    """Isolate reruns of the same frozen A/B/C challenge input."""
    if run_id is None:
        return Path(case_dir) / "agent_run"
    token = str(run_id)
    if (
        not (1 <= len(token) <= 48)
        or not all(ch.isascii() and (ch.isalnum() or ch in "_-") for ch in token)
    ):
        raise ValueError("invalid_run_id_use_ascii_alnum_dash_underscore")
    return Path(case_dir) / ("agent_run_" + token)


def run_offline(case_dir: Path, *, run_id: str | None = None) -> dict[str, Any]:
    """Run the REAL V3-A main chain. No model fixture, oracle or paid HTTP."""
    from .story_e2e_agent import StoryE2EInputs, run_story_e2e

    case_dir = Path(case_dir)
    manifest = _read(case_dir / "run_manifest.json")
    if manifest.get("schema") != SCHEMA:
        raise ValueError("invalid_challenge_manifest")
    phase5 = Path(manifest["phase5_dir"])
    input_root = (case_dir / "agent_input").resolve()
    for p in (phase5, Path(manifest["events_json"])):
        if input_root != p.resolve() and input_root not in p.resolve().parents:
            raise ValueError("agent_input_escapes_isolated_case")
    out = _run_dir(case_dir, run_id)
    if out.exists():
        raise FileExistsError("agent_run_already_exists_refuse_overwrite")
    return run_story_e2e(StoryE2EInputs(
        match_json=Path(manifest["events_json"]),
        events_json=Path(manifest["events_json"]),
        source_mp4=Path(manifest["source_mp4"]),
        phase5_dir=phase5,
        out_dir=out,
        skip_vlm=True,
        enable_real_api=False,
        i_approve_budget=False,
        smoke_render=False,
        max_rounds=1,
    ))


def score_case(
    case_dir: Path, *, external_reference_edl: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Read-only evaluator. Reference may not live under agent_input/agent_run."""
    case_dir = Path(case_dir)
    manifest = _read(case_dir / "run_manifest.json")
    input_root = (case_dir / "agent_input").resolve()
    run_root = _run_dir(case_dir, run_id).resolve()
    if external_reference_edl:
        reference = Path(external_reference_edl).resolve()
        if input_root in reference.parents or run_root in reference.parents:
            raise ValueError("reference_edl_not_private")
        ref_rows = _rows(reference)
        truth = None
    elif manifest.get("variant") == "CLEAN_NO_DEFECT_CONTROL":
        ref_rows = _rows(Path(manifest["phase5_dir"]) / "candidate_edl.json")
        truth = None
    else:
        private = case_dir / "private_eval" / "truth.json"
        if not private.is_file():
            raise FileNotFoundError("historical_case_requires_external_reference_edl")
        truth = _read(private)
        ref_rows = [truth["reference_action"]]

    target_roles = {
        str(x.get("role") or ""): x for x in ref_rows
        if "goal_action" in str(x.get("role") or "") and x.get("include_in_cut", True)
    }
    before = _rows(Path(manifest["phase5_dir"]) / "candidate_edl.json")
    before_roles = {
        str(x.get("role") or "") for x in before
        if x.get("include_in_cut", True)
    }
    missing = {
        role: row for role, row in target_roles.items() if role not in before_roles
    }
    output = run_root / "99_final" / "final_edl.json"
    audit_path = run_root / "story_e2e_audit.json"
    diag_path = run_root / "02_round_01" / "story_diagnosis.json"
    if not output.is_file():
        run_audit = _read(audit_path) if audit_path.is_file() else {}
        return {
            "schema": SCHEMA,
            "status": "BLOCKED_NO_FINAL_EDL" if audit_path.is_file() else "NOT_RUN",
            "missing_goal_count": len(missing),
            "run_audit_exists": audit_path.is_file(),
            "run_error": run_audit.get("error"),
            "no_quality_or_first_live_claim": True,
        }
    after = _rows(output)
    after_roles = {
        str(x.get("role") or "") for x in after
        if x.get("include_in_cut", True)
    }
    recovered = {}
    for role, reference in missing.items():
        candidates = [
            r for r in after
            if r.get("include_in_cut", True) and str(r.get("role") or "") == role
            and r.get("media_in") is not None and r.get("media_out") is not None
        ]
        lo, hi = float(reference["media_in"]), float(reference["media_out"])
        matches = []
        for row in candidates:
            a, b = float(row["media_in"]), float(row["media_out"])
            intersection = max(0.0, min(b, hi) - max(a, lo))
            union = max(1e-9, max(b, hi) - min(a, lo))
            matches.append({
                "segment_id": row.get("segment_id"),
                "source_window_iou": round(intersection / union, 4),
                "is_replay_flag": row.get("is_replay"),
                "has_video_first_live_proof": False,
            })
        recovered[role] = {
            "role_restored": role in after_roles,
            "matching_windows": matches,
            "source_window_overlap": any(x["source_window_iou"] > 0.0 for x in matches),
        }
    diag = _read(diag_path) if diag_path.is_file() else {}
    audit = _read(audit_path) if audit_path.is_file() else {}
    search_path = run_root / "02_round_01" / "evidence_search.json"
    plan_path = run_root / "02_round_01" / "revision_plan.json"
    render_path = run_root / "02_round_01" / "candidate_render.json"
    search = _read(search_path) if search_path.is_file() else {}
    revision = _read(plan_path) if plan_path.is_file() else {}
    rendering = _read(render_path) if render_path.is_file() else {}
    # These are OBSERVED pipeline gates, not inferred causal explanations.
    # A generic source-PTS jump is not an explicit missing-goal diagnosis.
    goal_issue_found = any(
        i.get("category") in ("goal_coverage", "missing_goal", "goal_omission")
        for i in diag.get("issues") or [] if isinstance(i, dict)
    )
    search_candidates = len(search.get("verified_candidates") or [])
    revision_actions = [
        str(i.get("action") or "") for i in revision.get("revision_intents") or []
        if isinstance(i, dict)
    ]
    mutating_revision = any(
        x not in ("keep", "mark_unresolved", "unresolved") for x in revision_actions
    )
    candidate_rendered = bool(
        rendering.get("story_clean") or (
            rendering.get("ok") and not rendering.get("skipped")
        )
    )
    edl_recovered = bool(missing) and all(
        x["source_window_overlap"] for x in recovered.values()
    )
    preserved_goal_roles = {
        str(x.get("role") or "") for x in before
        if x.get("include_in_cut", True)
        and "goal_action" in str(x.get("role") or "")
    }
    missing_preexisting_goals = sorted(preserved_goal_roles - after_roles)
    from .story_edl_safety import check_source_pts_monotonic
    source_pts_safe = bool(check_source_pts_monotonic(after).get("ok"))
    final_video = run_root / "99_final" / "story_final.mp4"
    is_clean_control = manifest.get("variant") == "CLEAN_NO_DEFECT_CONTROL"
    if is_clean_control:
        status = "NO_UNNECESSARY_EDL_EDIT" if after == before else "UNNECESSARY_EDL_EDIT"
    elif not edl_recovered:
        status = "NOT_REPAIRED"
    elif missing_preexisting_goals:
        status = "REPAIR_REGRESSION_GOAL_LOSS"
    elif not source_pts_safe:
        status = "EDL_RESTORED_PTS_INVALID"
    elif not final_video.is_file():
        status = "EDL_WINDOW_RESTORED_NO_MP4"
    else:
        status = "EDL_WINDOW_RESTORED_UNVERIFIED"
    out = {
        "schema": SCHEMA,
        "variant": manifest.get("variant"),
        "input_mode": manifest.get("input_mode"),
        "status": status,
        "missing_goal_roles_evaluator_only": list(missing),
        "diagnosed_issues": [
            {"issue_id": i.get("issue_id"), "category": i.get("category")}
            for i in diag.get("issues") or [] if isinstance(i, dict)
        ],
        "stage_observations": {
            "explicit_goal_omission_diagnosed": goal_issue_found,
            "generic_temporal_jump_not_counted_as_goal_detection": True,
            "search_candidates_in_main_chain": search_candidates,
            "revision_decision": revision.get("decision"),
            "revision_actions": revision_actions,
            "mutating_revision_requested": mutating_revision,
            "candidate_rendered": candidate_rendered,
            "final_mp4_exists": final_video.is_file(),
            "preexisting_goal_roles_lost": missing_preexisting_goals,
            "source_pts_monotonic_ok": source_pts_safe,
            "offline_without_semantic_vlm": True,
        },
        "recovery": recovered,
        "final_edl_exists": True,
        "agent_decision": audit.get("decision"),
        "release_authorized": bool((audit.get("delivery") or {}).get("release_authorized")),
        "first_live_video_verified": False,
        "story_quality_improved": "UNVERIFIED",
        "formal_benchmark": False,
        "reference_not_given_to_agent": True,
    }
    _write(case_dir / "private_eval" / "score.json", out)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="V3-A blinded historic goal-omission challenge")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("controlled")
    a.add_argument("--complete-edl", required=True, type=Path)
    a.add_argument("--story-plan", required=True, type=Path)
    a.add_argument("--source-mp4", required=True, type=Path)
    a.add_argument("--events-json", required=True, type=Path)
    a.add_argument("--case-dir", required=True, type=Path)
    a.add_argument("--omit-role", default="equalizer_goal_action")
    a.add_argument("--input-mode", choices=["HUMAN_ATOM_ENRICHED_DEV", "RAW_EVENTS_ONLY"],
                   default="HUMAN_ATOM_ENRICHED_DEV")
    e = sub.add_parser("clean-control")
    e.add_argument("--complete-edl", required=True, type=Path)
    e.add_argument("--story-plan", required=True, type=Path)
    e.add_argument("--baseline-mp4", required=True, type=Path)
    e.add_argument("--source-mp4", required=True, type=Path)
    e.add_argument("--events-json", required=True, type=Path)
    e.add_argument("--case-dir", required=True, type=Path)
    b = sub.add_parser("historical")
    b.add_argument("--failed-phase5", required=True, type=Path)
    b.add_argument("--source-mp4", required=True, type=Path)
    b.add_argument("--raw-events-json", required=True, type=Path)
    b.add_argument("--case-dir", required=True, type=Path)
    c = sub.add_parser("run-offline")
    c.add_argument("--case-dir", required=True, type=Path)
    c.add_argument("--run-id", default=None)
    d = sub.add_parser("score")
    d.add_argument("--case-dir", required=True, type=Path)
    d.add_argument("--run-id", default=None)
    d.add_argument("--external-reference-edl", type=Path, default=None)
    args = p.parse_args(argv)
    if args.cmd == "controlled":
        result = prepare_controlled(
            complete_edl=args.complete_edl, story_plan=args.story_plan,
            source_mp4=args.source_mp4, events_json=args.events_json,
            case_dir=args.case_dir, omitted_role=args.omit_role, input_mode=args.input_mode,
        )
    elif args.cmd == "clean-control":
        result = prepare_clean_control(
            complete_edl=args.complete_edl, story_plan=args.story_plan,
            baseline_mp4=args.baseline_mp4, source_mp4=args.source_mp4,
            events_json=args.events_json, case_dir=args.case_dir,
        )
    elif args.cmd == "historical":
        result = prepare_historical(
            failed_phase5=args.failed_phase5, source_mp4=args.source_mp4,
            raw_events_json=args.raw_events_json, case_dir=args.case_dir,
        )
    elif args.cmd == "run-offline":
        result = run_offline(args.case_dir, run_id=args.run_id)
    else:
        result = score_case(
            args.case_dir, external_reference_edl=args.external_reference_edl,
            run_id=args.run_id,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
