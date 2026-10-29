"""Strip-Guided Round 2.3 — full-match story planner + candidate story videos."""

from __future__ import annotations

import argparse
import json
import subprocess
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
from story_video_agent.frames import FrameBudget, FrameStore
from story_video_agent.media import probe_video
from story_video_agent.v2_api_preflight import run_preflight
from story_video_agent.v2_event_adapter import INPUT_SOURCES, load_events_json, planner_event_digest
from story_video_agent.v2_phase_c1_toolbox import V2PhaseC1Toolbox
from story_video_agent.v2_strip_guided_r2_3_edl import build_r23_candidate_edl
from story_video_agent.v2_strip_guided_r2_3_graph import build_full_story_graph
from story_video_agent.v2_strip_guided_r2_3_key_events import (
    build_full_match_key_events,
    finalize_original_goal_from_verifications,
    find_unverified_original_goals,
    load_r22_verified_goals,
    verify_original_goal_with_video,
)
from story_video_agent.v2_strip_guided_r2_3_memory import V2R23StoryMemory
from story_video_agent.v2_strip_guided_r2_3_planner import (
    V2R23StoryPlanner,
    apply_planner_decision,
    ensure_verified_goals_selected,
    finalize_relations,
    summarize_strips_for_planner,
)
from story_video_agent.v2_strip_guided_r2_3_render import render_r23_candidates
from story_video_agent.vision_provider import VisionProvider

DEFAULT_R22 = Path(
    "/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_2_20261029_162833_unified"
)
DEFAULT_ALGO = Path("/data2/lpy1/causal-chain2/8.31causal_chain")


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


def _make_api(*, real: bool, max_calls: int, max_cost: float, max_tokens: int) -> ApiProvider:
    if real:
        if not api_enabled() or not smoke_enabled():
            raise ApiConfigError("STORY_API_ENABLE=1 and STORY_API_SMOKE=1 required")
        configs = load_endpoint_configs()
        return ApiProvider(
            configs=configs,
            require_real=True,
            force_mock=False,
            max_calls=max_calls,
            max_cost_usd=max_cost,
            max_completion_tokens=max_tokens,
        )
    return ApiProvider(
        force_mock=True,
        require_real=False,
        max_calls=max_calls,
        max_cost_usd=max_cost,
        max_completion_tokens=max_tokens,
    )


def _nearest_strip(chains: List[Dict[str, Any]], t: float) -> Optional[Dict[str, Any]]:
    best = None
    best_d = 1e18
    for c in chains:
        t0 = float(c.get("t0_sec") or 0)
        t1 = float(c.get("t1_sec") or 0)
        d = abs(0.5 * (t0 + t1) - t)
        if t0 - 20 <= t <= t1 + 20:
            d *= 0.3
        if (c.get("last_event") == "goal") or (c.get("predicted_category") == "outcome"):
            d -= 50
        if d < best_d:
            best_d = d
            best = c
    return best


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="V2 Strip-Guided Round 2.3 full-match story")
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--events", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--r22-dir", type=Path, default=DEFAULT_R22)
    p.add_argument("--algo-root", type=Path, default=DEFAULT_ALGO)
    p.add_argument("--input-source", choices=list(INPUT_SOURCES), default="human_corrected")
    p.add_argument("--real", action="store_true")
    p.add_argument("--use-llm-planner", action="store_true", help="Use DeepSeek planner (default on with --real)")
    p.add_argument("--no-llm-planner", action="store_true", help="Force rule-only planner")
    p.add_argument("--skip-fourth-goal-verify", action="store_true")
    p.add_argument(
        "--reuse-verify-cache",
        type=Path,
        default=None,
        help="Reuse cached original_goal_verify.json under verify_<event_id>/ (no new VLM)",
    )
    p.add_argument("--skip-render", action="store_true")
    p.add_argument("--max-planner-steps", type=int, default=16)
    p.add_argument("--max-api-calls", type=int, default=30)
    p.add_argument("--max-cost-usd", type=float, default=2.0)
    p.add_argument("--max-completion-tokens", type=int, default=4096)
    p.add_argument("--frame-budget-verify", type=int, default=28)
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    # Prefer LLM when real unless explicitly disabled.
    use_llm = (bool(args.real) or bool(args.use_llm_planner)) and not bool(args.no_llm_planner)

    event_bundle = load_events_json(args.events, input_source=args.input_source)
    digest = planner_event_digest(event_bundle)
    _write(out_dir / "event_digest.json", digest)
    match_id = str(event_bundle.get("match_id") or args.events.stem)

    # Load R2.2 strip B + verified goals (no re-VLM for those)
    r22 = Path(args.r22_dir)
    verified = load_r22_verified_goals(r22)
    strip_b = json.loads((r22 / "predicted_strip_chains_B.json").read_text(encoding="utf-8"))
    chains = list(strip_b.get("chains") or [])

    unverified = find_unverified_original_goals(
        events=event_bundle.get("events") or [],
        verified_goals=verified,
        score_anchors=digest.get("score_anchors") or [],
    )
    _write(out_dir / "unverified_original_goals.json", {"items": unverified, "n": len(unverified)})

    newly: List[Dict[str, Any]] = []
    unresolved_original: List[Dict[str, Any]] = []
    verify_report = None
    api = _make_api(
        real=bool(args.real),
        max_calls=args.max_api_calls,
        max_cost=args.max_cost_usd,
        max_tokens=args.max_completion_tokens,
    )

    if args.reuse_verify_cache and unverified:
        cache_root = Path(args.reuse_verify_cache)
        for ug in unverified:
            eid = str(ug.get("event_id"))
            cached = cache_root / f"verify_{eid}" / "original_goal_verify.json"
            vdir = out_dir / f"verify_{eid}"
            if cached.is_file():
                prev = json.loads(cached.read_text(encoding="utf-8"))
                verify_report = finalize_original_goal_from_verifications(
                    original_goal=ug,
                    verifications=prev.get("verifications") or [],
                    out_dir=vdir,
                    api_stats=prev.get("api_stats") or {},
                    frames_used=prev.get("frames_used"),
                )
                if verify_report.get("verified") and verify_report.get("inferred_event"):
                    newly.append(verify_report["inferred_event"])
                else:
                    unresolved_original.append(
                        {
                            **ug,
                            "search_status": "unresolved",
                            "verify_path": str(vdir),
                            "note": "Cached VLM windows reprocessed; still not frame-bound verified",
                        }
                    )
            else:
                unresolved_original.append(
                    {**ug, "search_status": "unresolved_missing_cache", "verify_path": str(cached)}
                )
    elif args.real and not args.skip_fourth_goal_verify and unverified:
        # Preflight vision (and planner if LLM)
        roles = ("vision", "planner") if use_llm else ("vision",)
        configs = load_endpoint_configs()
        probe = Path("/tmp/croatia_vlm_probe/f.jpg")
        pf = run_preflight(
            configs=configs,
            image_path=probe if probe.is_file() else None,
            require_roles=roles,
        )
        _write(out_dir / "api_preflight.json", pf)
        if not pf.get("passed"):
            _write(
                out_dir / "cli_report.json",
                {"status": "aborted_preflight", "api_preflight": pf, "render_ready": False},
            )
            return 2

        for ug in unverified:
            hint = _nearest_strip(chains, float(ug["event_time_sec"]))
            vdir = out_dir / f"verify_{ug.get('event_id')}"
            verify_report = verify_original_goal_with_video(
                video=args.video,
                original_goal=ug,
                api=api,
                out_dir=vdir,
                frame_budget=args.frame_budget_verify,
                strip_hint=hint,
            )
            if verify_report.get("verified") and verify_report.get("inferred_event"):
                newly.append(verify_report["inferred_event"])
            else:
                unresolved_original.append({**ug, "search_status": "unresolved", "verify_path": str(vdir)})
    elif unverified:
        unresolved_original = [{**u, "search_status": "skipped_no_real_api"} for u in unverified]

    key_events = build_full_match_key_events(
        verified_goals=verified,
        events=event_bundle.get("events") or [],
        score_anchors=digest.get("score_anchors") or [],
        strip_chains=chains,
        newly_verified=newly,
        unresolved_original_goals=unresolved_original,
    )
    _write(out_dir / "full_match_key_events.json", key_events)

    # --- Story planner loop ---
    memory = V2R23StoryMemory()
    memory.score_path = []
    for a in digest.get("score_anchors") or []:
        if a.get("kind") == "initial_score" and a.get("score_pair"):
            memory.score_path.append(tuple(a["score_pair"]))
        if a.get("kind") == "score_change" and a.get("score_after"):
            memory.score_path.append(tuple(a["score_after"]))
    memory.key_events = list(key_events.get("key_events") or [])
    key_times = [float(k.get("media_time_sec") or 0) for k in memory.key_events]
    memory.strip_summaries = summarize_strips_for_planner(chains, key_event_times=key_times, max_n=24)
    memory.budget = {
        "max_planner_steps": args.max_planner_steps,
        "api_max_calls": args.max_api_calls,
        "frames_verify_budget": args.frame_budget_verify,
    }

    planner = V2R23StoryPlanner(api=api, use_llm=use_llm and bool(args.real))
    trace: List[Dict[str, Any]] = []
    stop_reason = "max_steps"

    # Optional toolbox for video checks requested by planner
    media = probe_video(args.video)
    frames_dir = out_dir / "frames_planner"
    store = FrameStore(media, out_dir=frames_dir, budget=FrameBudget(max_frames=16))
    vision = VisionProvider(api=api, force_mock=bool(api.force_mock))
    tools = V2PhaseC1Toolbox(
        duration=media.duration_sec,
        store=store,
        vision=vision,
        task_note="Story planner supplemental check only; do not invent unobserved actions.",
    )

    for step in range(args.max_planner_steps):
        decision = planner.decide(memory, step, args.max_planner_steps)
        obs = apply_planner_decision(memory, decision)
        row: Dict[str, Any] = {"step": step, "decision": decision, "observation": obs}

        # Execute queued video check (at most one per step)
        if decision.get("tool") == "request_video_check" and args.real and store.budget.remaining > 0:
            req = obs.get("queued_video_check") or {}
            start = float(req.get("start") or 0)
            end = float(req.get("end") or (start + 20))
            purpose = str(req.get("purpose") or "coarse")
            tool = "dense_action_inspect" if purpose == "dense" else "coarse_search"
            if end - start > 90:
                start = end - 90
            raw = tools.execute(tool, {"start": start, "end": end, "task_id": str(req.get("node_id"))})
            check = {
                "node_id": req.get("node_id"),
                "window": {"start": start, "end": end},
                "actions": (raw.get("perception") or {}).get("observed_actions")
                or raw.get("observed_actions"),
                "notes": (raw.get("perception") or {}).get("notes"),
                "why": req.get("why"),
            }
            memory.video_check_results.append(check)
            memory.pending_video_checks = [x for x in memory.pending_video_checks if x != req]
            row["video_check"] = check

        trace.append(row)
        if decision.get("tool") == "finish_story":
            stop_reason = str((decision.get("arguments") or {}).get("reason") or "finish")
            break

    # DeepSeek may finish with strips only — always attach verified goals + basic relations.
    ensure_actions = ensure_verified_goals_selected(memory)
    if ensure_actions:
        trace.append(
            {
                "step": "ensure_verified_goals",
                "actions": ensure_actions,
                "note": "Post-LLM guarantee: select all video-verified ke_ goals and temporal/narrative spine",
            }
        )

    rel_doc = finalize_relations(memory)
    _write(out_dir / "story_relations.json", rel_doc)
    _write(
        out_dir / "story_planner_trace.json",
        {
            "schema": "v2_r23_story_planner_trace_v1",
            "elapsed_sec": round(time.time() - t0, 3),
            "stop_reason": stop_reason,
            "planner_mode_log": planner.planner_mode_log,
            "steps": trace,
            "ensure_verified_goals": ensure_actions,
            "memory_snapshot": memory.snapshot(),
            "api_stats": api.stats.summary(),
            "render_ready": False,
        },
    )

    story_graph = build_full_story_graph(
        memory=memory,
        relations_doc=rel_doc,
        score_anchors=digest.get("score_anchors") or [],
        strip_chains=chains,
    )
    _write(out_dir / "story_graph.json", story_graph)
    _write(
        out_dir / "story_beats.json",
        {"schema": "v2_r23_story_beats_v1", "beats": story_graph.get("beats"), "render_ready": False},
    )
    _write(
        out_dir / "story_candidates.json",
        {
            "schema": "v2_r23_story_candidates_v1",
            "discovery_status": memory.discovery_status,
            "candidates": [
                {
                    "story_id": "T01_full_match",
                    "score_path": memory.score_path,
                    "selected_node_ids": memory.selected_node_ids,
                    "selection_reasons": memory.selection_reasons,
                    "exclusion_reasons": memory.exclusion_reasons,
                    "n_verified_goals": key_events.get("n_verified_goals"),
                    "n_non_goal_strips": sum(1 for n in memory.selected_node_ids if n.startswith("strip_")),
                }
            ],
            "render_ready": False,
        },
    )

    edl = build_r23_candidate_edl(story_graph=story_graph)
    _write(out_dir / "candidate_edl.json", edl)

    render_manifest = None
    if not args.skip_render:
        render_manifest = render_r23_candidates(video=args.video, edl=edl, out_dir=out_dir)

    report = {
        "schema": "v2_strip_guided_r2_3_report_v1",
        "match_id": match_id,
        "git_sha": _git_sha(),
        "elapsed_sec": round(time.time() - t0, 3),
        "r22_dir": str(r22),
        "n_verified_goals": key_events.get("n_verified_goals"),
        "n_unresolved_original_goals": key_events.get("n_unresolved_original_goals"),
        "score_coverage": key_events.get("score_coverage"),
        "discovery_status": memory.discovery_status,
        "selected_node_ids": memory.selected_node_ids,
        "selection_reasons": memory.selection_reasons,
        "exclusion_reasons": memory.exclusion_reasons,
        "n_global_relations": len(rel_doc.get("relations") or []),
        "n_edl_segments": edl.get("n_segments"),
        "n_non_goal_strip_segments": edl.get("n_non_goal_strip_segments"),
        "api_stats": api.stats.summary(),
        "planner_mode_log": planner.planner_mode_log,
        "artifacts": {
            "full_match_key_events": str(out_dir / "full_match_key_events.json"),
            "story_planner_trace": str(out_dir / "story_planner_trace.json"),
            "story_graph": str(out_dir / "story_graph.json"),
            "candidate_edl": str(out_dir / "candidate_edl.json"),
            "story_clean": str(out_dir / "story_clean_candidate.mp4"),
            "story_qc": str(out_dir / "story_qc_candidate.mp4"),
        },
        "render_manifest": render_manifest,
        "render_ready": False,
        "forbidden": ["gold_causal", "strip_gold", "v1_times", "production_param_retune"],
    }
    _write(out_dir / "cli_report.json", report)
    print(
        json.dumps(
            {
                k: report.get(k)
                for k in (
                    "match_id",
                    "n_verified_goals",
                    "n_unresolved_original_goals",
                    "discovery_status",
                    "n_non_goal_strip_segments",
                    "n_edl_segments",
                    "render_ready",
                    "git_sha",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if int(key_events.get("n_verified_goals") or 0) >= 4 else 1


if __name__ == "__main__":
    raise SystemExit(main())
