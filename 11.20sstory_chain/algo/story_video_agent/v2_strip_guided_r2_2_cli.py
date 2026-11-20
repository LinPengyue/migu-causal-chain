"""Strip-Guided Round 2.2 — unify verified Goals, strip A/B, T01 story, candidate EDL."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from story_video_agent.api_provider import (
    ApiConfigError,
    ApiProvider,
    api_enabled,
    load_endpoint_configs,
    smoke_enabled,
)
from story_video_agent.v2_api_preflight import PreflightError, run_preflight
from story_video_agent.v2_event_adapter import INPUT_SOURCES, load_events_json, planner_event_digest
from story_video_agent.v2_event_guided_clip_export import export_candidate_review_pack
from story_video_agent.v2_goal_recovery_runner import run_goal_recovery
from story_video_agent.v2_missing_goal_detector import detect_missing_goals
from story_video_agent.v2_strip_adapter import adapt_strip_bundle
from story_video_agent.v2_strip_guided_r2_2_edl import build_candidate_edl
from story_video_agent.v2_strip_guided_r2_2_merge import merge_and_audit_goals
from story_video_agent.v2_strip_guided_r2_2_story import build_t01_story_graph
from story_video_agent.v2_strip_reinfer import (
    analyze_inferred_in_strip_b,
    compare_strip_ab,
    events_to_timeline,
    load_or_run_baseline_A,
    run_strip_predict,
)

DEFAULT_ALGO = Path("/data2/lpy1/causal-chain2/8.31causal_chain")
DEFAULT_CACHED = [
    Path("/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_1_20261029_160443/mg_trans_1"),
    Path("/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_1_20261029_160209/mg_trans_2"),
    Path("/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_1_20261029_161123/mg_trans_3"),
]
DEFAULT_DEFICIT = Path(
    "/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_2_20261029_161952/mg_initial_deficit_0"
)


def _git_sha() -> str:
    here = Path(__file__).resolve().parent
    for root in [here, *here.parents]:
        if (root / ".git").exists():
            try:
                return subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=str(root), text=True, stderr=subprocess.DEVNULL
                ).strip()
            except Exception:  # noqa: BLE001
                break
    return "unknown"


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _make_api(*, real: bool, max_calls: int, max_cost: float, max_completion_tokens: int) -> ApiProvider:
    if real:
        if not api_enabled():
            raise ApiConfigError("STORY_API_ENABLE=1 required")
        if not smoke_enabled():
            raise ApiConfigError("STORY_API_SMOKE=1 required")
        configs = load_endpoint_configs()
        for role in ("vision",):
            if not configs[role].configured():
                raise ApiConfigError(f"{role} incomplete")
        return ApiProvider(
            configs=configs,
            require_real=True,
            force_mock=False,
            max_calls=max_calls,
            max_cost_usd=max_cost,
            max_completion_tokens=max_completion_tokens,
        )
    return ApiProvider(
        force_mock=True,
        require_real=False,
        max_calls=max_calls,
        max_cost_usd=max_cost,
        max_completion_tokens=max_completion_tokens,
    )


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="V2 Strip-Guided Round 2.2 unified story build")
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--events", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--algo-root", type=Path, default=DEFAULT_ALGO)
    p.add_argument("--input-source", choices=list(INPUT_SOURCES), default="human_corrected")
    p.add_argument("--cached-goal-dir", type=Path, action="append", default=None)
    p.add_argument("--deficit-dir", type=Path, default=DEFAULT_DEFICIT)
    p.add_argument("--recover-deficit", action="store_true", help="Run video recovery for mg_initial_deficit_0")
    p.add_argument("--skip-deficit-recover", action="store_true", help="Reuse --deficit-dir only")
    p.add_argument("--strip-a", type=Path, default=None, help="Reuse existing strip A JSON (62 chains)")
    p.add_argument("--real", action="store_true")
    p.add_argument("--export-review-clips", action="store_true")
    p.add_argument("--max-steps", type=int, default=12)
    p.add_argument("--frame-budget", type=int, default=56)
    p.add_argument("--max-api-calls", type=int, default=24)
    p.add_argument("--max-cost-usd", type=float, default=1.5)
    p.add_argument("--max-completion-tokens", type=int, default=4096)
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    cached = list(args.cached_goal_dir) if args.cached_goal_dir else list(DEFAULT_CACHED)
    fresh_dirs: List[Path] = []

    # --- optional deficit recovery (only if missing / requested) ---
    deficit_dir = Path(args.deficit_dir) if args.deficit_dir else None
    need_recover = bool(args.recover_deficit)
    if not args.skip_deficit_recover:
        if deficit_dir is None or not (deficit_dir / "enhanced" / "inferred_goal_events.json").is_file():
            need_recover = True
    if need_recover and args.real:
        preflight_image = Path("/tmp/croatia_vlm_probe/f.jpg")
        configs = load_endpoint_configs()
        pf = run_preflight(configs=configs, image_path=preflight_image if preflight_image.is_file() else None, require_roles=("vision",))
        _write(out_dir / "api_preflight.json", pf)
        if not pf.get("passed"):
            _write(
                out_dir / "cli_report.json",
                {
                    "schema": "v2_strip_guided_r2_2_report_v1",
                    "status": "aborted_preflight",
                    "api_preflight": pf,
                    "render_ready": False,
                    "git_sha": _git_sha(),
                },
            )
            return 2
        api = _make_api(
            real=True,
            max_calls=args.max_api_calls,
            max_cost=args.max_cost_usd,
            max_completion_tokens=args.max_completion_tokens,
        )
        deficit_out = out_dir / "mg_initial_deficit_0"
        try:
            run_goal_recovery(
                video=args.video,
                events_path=args.events,
                out_dir=deficit_out,
                api=api,
                algo_root=args.algo_root,
                strip_a_path=args.strip_a,
                input_source=args.input_source,
                max_steps=args.max_steps,
                frame_budget=args.frame_budget,
                use_llm_planner=False,
                skip_video=False,
                candidate_ids=["mg_initial_deficit_0"],
                require_preflight_check=True,
                preflight_image=preflight_image if preflight_image.is_file() else None,
            )
        except PreflightError as exc:
            _write(
                out_dir / "cli_report.json",
                {
                    "schema": "v2_strip_guided_r2_2_report_v1",
                    "status": "aborted_preflight",
                    "error": str(exc),
                    "render_ready": False,
                },
            )
            return 2
        fresh_dirs.append(deficit_out)
        deficit_dir = deficit_out
    elif deficit_dir and deficit_dir.is_dir():
        fresh_dirs.append(deficit_dir)

    # --- merge cached + deficit (no re-VLM for mg_trans_*) ---
    event_bundle = load_events_json(args.events, input_source=args.input_source)
    match_id = str(event_bundle.get("match_id") or args.events.stem)
    digest = planner_event_digest(event_bundle)
    _write(out_dir / "event_digest.json", digest)
    merge = merge_and_audit_goals(
        cached_dirs=cached,
        fresh_dirs=fresh_dirs,
        original_events_path=args.events,
        out_dir=out_dir,
        match_id=match_id,
    )
    verified = merge["verified_goals"]
    _write(out_dir / "unified_inferred_goals.json", {"events": verified, "n": len(verified), "render_ready": False})

    # --- unified strip A (baseline 62) / B (all inferred) ---
    ab_dir = out_dir / "strip_ab"
    ab_dir.mkdir(parents=True, exist_ok=True)
    # Prefer a known 62-chain A if provided; else run once from plain events
    strip_a = load_or_run_baseline_A(
        events_path=args.events,
        out_dir=ab_dir,
        algo_root=args.algo_root,
        match_id=match_id,
        existing_strip_a=args.strip_a,
    )
    strip_a_adapted = adapt_strip_bundle(
        ab_dir / "strip_A_original.json",
        events_path=args.events,
        match_id=match_id,
    )
    _write(out_dir / "predicted_strip_chains_A.json", strip_a_adapted)

    timeline_b = events_to_timeline(merge["bundle"].get("merged_events_for_strip") or [])
    _write(ab_dir / "timeline_B.json", {"n": len(timeline_b), "events": timeline_b})
    strip_b = run_strip_predict(
        timeline_events=timeline_b,
        match_id=match_id,
        algo_root=args.algo_root,
        label="B_enhanced_unified",
    )
    strip_b["source_enhanced"] = str(out_dir / "enhanced" / "enhanced_events_for_strip.json")
    strip_b["n_inferred_merged"] = merge["bundle"].get("n_inferred_verified_merged")
    _write(ab_dir / "strip_B_enhanced.json", strip_b)
    strip_b_adapted = adapt_strip_bundle(
        ab_dir / "strip_B_enhanced.json",
        events_path=out_dir / "enhanced" / "enhanced_events_for_strip.json",
        match_id=match_id,
    )
    _write(out_dir / "predicted_strip_chains_B.json", strip_b_adapted)

    detector = detect_missing_goals(
        events=event_bundle.get("events") or [],
        predicted_strips=strip_a_adapted.get("chains") or [],
        match_id=match_id,
    )
    _write(out_dir / "missing_goal_candidates.json", detector)

    ab = compare_strip_ab(
        strip_a=strip_a,
        strip_b=strip_b,
        missing_candidates=detector.get("missing_goal_candidates") or [],
    )
    ab["baseline_note"] = "A = single plain-events production reinfer (expect ~62); B = unified enhanced once"
    _write(out_dir / "strip_ab_compare.json", ab)
    impact = analyze_inferred_in_strip_b(
        strip_b=strip_b, inferred_events=verified, timeline_b=timeline_b
    )
    _write(out_dir / "inferred_goal_strip_impact.json", impact)

    # --- Story graph / beats ---
    evid_ids = [str(v.get("evidence_id")) for v in merge.get("all_verifications") or [] if v.get("evidence_id")]
    story = build_t01_story_graph(
        verified_goals=verified,
        strip_b_bundle=strip_b_adapted,
        event_digest=digest,
        evidence_ids=evid_ids,
    )
    _write(out_dir / "story_graph.json", story)
    _write(
        out_dir / "story_beats.json",
        {"schema": "v2_strip_r2_2_story_beats_v1", "beats": story.get("beats"), "render_ready": False},
    )
    _write(
        out_dir / "story_relations.json",
        {
            "schema": "v2_strip_r2_2_story_relations_v1",
            "relations": story.get("relations"),
            "review": story.get("relation_review"),
            "render_ready": False,
        },
    )
    _write(
        out_dir / "story_candidates.json",
        {
            "schema": "v2_strip_r2_2_story_candidates_v1",
            "discovery_status": story.get("discovery_status"),
            "candidates": [
                {
                    "story_id": "T01_score_path",
                    "score_path": story.get("score_path"),
                    "n_verified_goal_nodes": story.get("n_verified_goal_nodes"),
                }
            ],
            "render_ready": False,
        },
    )

    # --- Candidate EDL ---
    edl = build_candidate_edl(story_graph=story)
    _write(out_dir / "candidate_edl.json", edl)

    # Optional internal review clips (still render_ready=false)
    review_manifest = None
    if args.export_review_clips and verified:
        frames_dirs = []
        for d in list(cached) + list(fresh_dirs):
            fd = Path(d) / "frames_r2"
            if fd.is_dir():
                frames_dirs.append(fd)
        frames_dir = frames_dirs[0] if frames_dirs else None
        review_manifest = export_candidate_review_pack(
            video=args.video,
            records=[
                {
                    "candidate_event_id": g.get("inferred_event_id"),
                    "localized_media_in": (g.get("edit_window") or {}).get("media_in"),
                    "localized_media_out": (g.get("edit_window") or {}).get("media_out"),
                    "supporting_frame_ids": g.get("supporting_frame_ids") or [],
                    "verification_status": g.get("verification_status"),
                    "grade": "action_localized",
                }
                for g in verified
            ],
            frames_dir=frames_dir,
            out_dir=out_dir / "review_pack",
        )

    report = {
        "schema": "v2_strip_guided_r2_2_report_v1",
        "match_id": match_id,
        "git_sha": _git_sha(),
        "elapsed_sec": round(time.time() - t0, 3),
        "n_verified_goals": len(verified),
        "verified_goal_times": [
            {
                "id": g.get("inferred_event_id"),
                "shot": (g.get("shot_action") or {}).get("media_sec"),
                "result": (g.get("goal_result") or {}).get("media_sec"),
                "score": g.get("related_score_transition"),
                "audit": (g.get("live_replay_audit") or {}).get("status"),
            }
            for g in verified
        ],
        "merge_sources": merge.get("sources"),
        "n_unresolved_after_audit": len(merge.get("unresolved_goals") or []),
        "strip_A_chains": ab.get("n_chains_A"),
        "strip_B_chains": ab.get("n_chains_B"),
        "strip_ab_compare": {
            "n_outcome_or_goal_A": ab.get("n_outcome_or_goal_A"),
            "n_outcome_or_goal_B": ab.get("n_outcome_or_goal_B"),
            "n_only_in_B": ab.get("n_only_in_B"),
        },
        "story_discovery_status": story.get("discovery_status"),
        "n_story_nodes": story.get("n_verified_goal_nodes"),
        "edl_n_segments": edl.get("n_segments"),
        "edl_gates": edl.get("gates"),
        "review_pack": review_manifest.get("n_exported") if review_manifest else None,
        "artifacts": {
            "enhanced": str(out_dir / "enhanced"),
            "strip_ab": str(ab_dir),
            "story_graph": str(out_dir / "story_graph.json"),
            "candidate_edl": str(out_dir / "candidate_edl.json"),
            "goal_merge_audit": merge["paths"].get("audit"),
            "evidence_inventory": merge["paths"].get("evidence"),
        },
        "forbidden": ["gold_causal", "strip_gold", "v1_times", "production_param_retune"],
        "render_ready": False,
    }
    _write(out_dir / "cli_report.json", report)
    print(json.dumps({k: report[k] for k in (
        "match_id", "n_verified_goals", "strip_A_chains", "strip_B_chains",
        "story_discovery_status", "edl_n_segments", "render_ready", "git_sha",
    )}, ensure_ascii=False, indent=2))
    return 0 if len(verified) >= 3 else 1


if __name__ == "__main__":
    # late import guard for detect_missing_goals signature
    raise SystemExit(main())
