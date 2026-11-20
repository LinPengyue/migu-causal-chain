"""Strip-Guided Round 2.4 — observation feedback story quality optimization."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from story_video_agent.api_provider import ApiConfigError, ApiProvider, api_enabled, load_endpoint_configs, smoke_enabled
from story_video_agent.frames import FrameBudget, FrameStore
from story_video_agent.media import probe_video
from story_video_agent.v2_api_preflight import run_preflight
from story_video_agent.v2_event_adapter import INPUT_SOURCES, load_events_json, planner_event_digest
from story_video_agent.v2_phase_c1_toolbox import V2PhaseC1Toolbox
from story_video_agent.v2_strip_guided_r2_3_graph import build_full_story_graph
from story_video_agent.v2_strip_guided_r2_3_key_events import load_r22_verified_goals
from story_video_agent.v2_strip_guided_r2_3_render import render_r23_candidates
from story_video_agent.v2_strip_guided_r2_4_edl import build_r24_candidate_edl
from story_video_agent.v2_strip_guided_r2_4_memory import V2R24StoryMemory
from story_video_agent.v2_strip_guided_r2_4_planner import (
    V2R24StoryPlanner,
    apply_r24_decision,
    apply_review_observations,
    ensure_verified_goals_selected,
    finalize_relations,
    seed_from_r23,
    summarize_strips_for_planner,
)
from story_video_agent.v2_strip_guided_r2_4_review import audit_r23_strips, grade_strip_observation
from story_video_agent.vision_provider import VisionProvider

DEFAULT_R23 = Path(
    "/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_3_20261029_181050_fixed"
)
DEFAULT_R22 = Path(
    "/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_2_20261029_162833_unified"
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


def _make_api(*, real: bool, max_calls: int, max_cost: float, max_tokens: int) -> ApiProvider:
    if real:
        if not api_enabled() or not smoke_enabled():
            raise ApiConfigError("STORY_API_ENABLE=1 and STORY_API_SMOKE=1 required")
        return ApiProvider(
            configs=load_endpoint_configs(),
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


def _load_r23_baseline(r23_dir: Path) -> Dict[str, Any]:
    cand = json.loads((r23_dir / "story_candidates.json").read_text(encoding="utf-8"))["candidates"][0]
    beats = json.loads((r23_dir / "story_beats.json").read_text(encoding="utf-8")).get("beats") or {}
    key_events = json.loads((r23_dir / "full_match_key_events.json").read_text(encoding="utf-8"))
    return {"candidate": cand, "beats": beats, "key_events": key_events}


def _strip_metas_for_ids(chains: List[Dict[str, Any]], node_ids: List[str]) -> List[Dict[str, Any]]:
    by = {str(c.get("strip_chain_id") or c.get("clip_id")): c for c in chains}
    out = []
    for nid in node_ids:
        if not nid.startswith("strip_"):
            continue
        sid = nid.replace("strip_", "", 1)
        c = by.get(sid)
        if not c:
            continue
        out.append(
            {
                "node_id": nid,
                "strip_chain_id": sid,
                "t0_sec": c.get("t0_sec"),
                "t1_sec": c.get("t1_sec"),
                "category": c.get("predicted_category") or c.get("chain_category"),
                "first_event": c.get("first_event"),
                "last_event": c.get("last_event"),
                "event_sequence": (c.get("event_sequence") or [])[:8],
            }
        )
    return out


def _selection_changes(r23_ids: List[str], r24_ids: List[str], memory: V2R24StoryMemory) -> Dict[str, Any]:
    s23, s24 = set(r23_ids), set(r24_ids)
    return {
        "schema": "v2_r24_story_selection_changes_v1",
        "r23_selected": r23_ids,
        "r24_selected": r24_ids,
        "kept": sorted(s23 & s24),
        "removed": sorted(s23 - s24),
        "added": sorted(s24 - s23),
        "change_log": memory.selection_change_log,
        "observation_driven_unselects": [
            x for x in memory.selection_change_log if x.get("action") == "unselect"
        ],
        "render_ready": False,
    }


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="V2 Strip-Guided Round 2.4 quality optimization")
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--events", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--r23-dir", type=Path, default=DEFAULT_R23)
    p.add_argument("--r22-dir", type=Path, default=DEFAULT_R22)
    p.add_argument("--input-source", choices=list(INPUT_SOURCES), default="human_corrected")
    p.add_argument("--real", action="store_true")
    p.add_argument("--no-llm-planner", action="store_true")
    p.add_argument("--skip-render", action="store_true")
    p.add_argument("--skip-strip-review", action="store_true")
    p.add_argument("--reuse-strip-review", type=Path, default=None)
    p.add_argument("--max-planner-steps", type=int, default=20)
    p.add_argument("--max-api-calls", type=int, default=40)
    p.add_argument("--max-cost-usd", type=float, default=2.5)
    p.add_argument("--max-completion-tokens", type=int, default=4096)
    p.add_argument("--frame-budget-review", type=int, default=56)
    p.add_argument(
        "--playout-policy",
        choices=["prefer_match_timeline", "planner_narrative"],
        default="prefer_match_timeline",
    )
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    use_llm = bool(args.real) and not bool(args.no_llm_planner)

    event_bundle = load_events_json(args.events, input_source=args.input_source)
    digest = planner_event_digest(event_bundle)
    _write(out_dir / "event_digest.json", digest)
    match_id = str(event_bundle.get("match_id") or args.events.stem)

    r23 = _load_r23_baseline(Path(args.r23_dir))
    # Reuse R2.3 key events document (verified goals) — do not re-verify
    key_events = r23["key_events"]
    _write(out_dir / "full_match_key_events.json", key_events)

    strip_b = json.loads((Path(args.r22_dir) / "predicted_strip_chains_B.json").read_text(encoding="utf-8"))
    chains = list(strip_b.get("chains") or [])

    r23_sel = list(r23["candidate"].get("selected_node_ids") or [])
    r23_reasons = dict(r23["candidate"].get("selection_reasons") or {})
    r23_beats = {}
    for bname, b in (r23.get("beats") or {}).items():
        r23_beats[bname] = [m.get("node_id") for m in (b.get("members") or []) if m.get("node_id")]

    api = _make_api(
        real=bool(args.real),
        max_calls=args.max_api_calls,
        max_cost=args.max_cost_usd,
        max_tokens=args.max_completion_tokens,
    )

    # --- Task 1: audit eight non-goal strips ---
    strip_ids = [n for n in r23_sel if n.startswith("strip_")]
    metas = _strip_metas_for_ids(chains, strip_ids)
    review_doc: Dict[str, Any]
    if args.reuse_strip_review and Path(args.reuse_strip_review).is_file():
        review_doc = json.loads(Path(args.reuse_strip_review).read_text(encoding="utf-8"))
        _write(out_dir / "strip_video_review.json", review_doc)
    elif args.skip_strip_review:
        review_doc = {"schema": "v2_r24_strip_video_review_v1", "reviews": [], "n_reviewed": 0}
        _write(out_dir / "strip_video_review.json", review_doc)
    else:
        if args.real:
            configs = load_endpoint_configs()
            probe = Path("/tmp/croatia_vlm_probe/f.jpg")
            pf = run_preflight(
                configs=configs,
                image_path=probe if probe.is_file() else None,
                require_roles=("vision", "planner") if use_llm else ("vision",),
            )
            _write(out_dir / "api_preflight.json", pf)
            if not pf.get("passed"):
                _write(out_dir / "cli_report.json", {"status": "aborted_preflight", "api_preflight": pf})
                return 2
        review_doc = audit_r23_strips(
            video=args.video,
            strip_metas=metas,
            selection_reasons=r23_reasons,
            api=api,
            out_dir=out_dir,
            frame_budget=args.frame_budget_review,
        )

    # --- Task 2/3: observation-aware planner ---
    memory = V2R24StoryMemory()
    memory.playout_policy = args.playout_policy
    for a in digest.get("score_anchors") or []:
        if a.get("kind") == "initial_score" and a.get("score_pair"):
            memory.score_path.append(tuple(a["score_pair"]))
        if a.get("kind") == "score_change" and a.get("score_after"):
            memory.score_path.append(tuple(a["score_after"]))
    memory.key_events = list(key_events.get("key_events") or [])
    key_times = [float(k.get("media_time_sec") or 0) for k in memory.key_events]
    memory.strip_summaries = summarize_strips_for_planner(chains, key_event_times=key_times, max_n=28)
    memory.budget = {
        "max_planner_steps": args.max_planner_steps,
        "api_max_calls": args.max_api_calls,
        "frames_review_budget": args.frame_budget_review,
    }

    seed_from_r23(
        memory,
        r23_selected=strip_ids,
        selection_reasons=r23_reasons,
        beat_assignments=r23_beats,
    )
    apply_review_observations(memory, review_doc)
    # Ensure goals present before LLM loop
    ensure_actions = ensure_verified_goals_selected(memory)

    planner = V2R24StoryPlanner(api=api, use_llm=use_llm)
    media = probe_video(args.video)
    frames_dir = out_dir / "frames_planner"
    store = FrameStore(media, out_dir=frames_dir, budget=FrameBudget(max_frames=20))
    vision = VisionProvider(api=api, force_mock=bool(api.force_mock))
    tools = V2PhaseC1Toolbox(
        duration=media.duration_sec,
        store=store,
        vision=vision,
        task_note="R2.4 supplemental strip check; live vs replay; no invented goals.",
    )

    trace: List[Dict[str, Any]] = [
        {"step": "seed_r23_strips", "selected_strips": strip_ids},
        {"step": "ensure_verified_goals", "actions": ensure_actions},
        {"step": "ingest_strip_review", "n": review_doc.get("n_reviewed")},
    ]
    stop_reason = "max_steps"

    for step in range(args.max_planner_steps):
        decision = planner.decide(memory, step, args.max_planner_steps)
        obs = apply_r24_decision(memory, decision)
        row: Dict[str, Any] = {"step": step, "decision": decision, "observation": obs}

        if decision.get("tool") == "request_video_check" and args.real and store.budget.remaining > 0:
            req = obs.get("queued_video_check") or decision.get("arguments") or {}
            nid = str(req.get("node_id") or "")
            start = float(req.get("start") or 0)
            end = float(req.get("end") or (start + 30))
            if end - start > 90:
                start = end - 90
            tool = "dense_action_inspect" if req.get("purpose") == "dense" else "coarse_search"
            raw = tools.execute(tool, {"start": start, "end": end, "task_id": f"live_{nid}_{step}"})
            meta = next((s for s in memory.strip_summaries if s.get("node_id") == nid), {"node_id": nid})
            graded = grade_strip_observation(
                node_id=nid,
                strip_meta=meta,
                prior_why=memory.selection_reasons.get(nid) or "",
                raw=raw,
                evidence_id=f"r24_live_{step}_{nid}",
            )
            memory.record_observation(graded)
            row["video_check"] = graded
            # Immediate conflict flag for next planner_view
            if graded.get("recommendation") in {"drop", "replace"}:
                memory.narrative_conflicts.append(
                    {
                        "node_id": nid,
                        "conflict": "live_check_vs_selection",
                        "recommendation": graded.get("recommendation"),
                        "summary": graded.get("summary"),
                    }
                )

        trace.append(row)
        if decision.get("tool") == "finish_story":
            pending_drops = [
                nid
                for nid, o in memory.strip_observations.items()
                if nid in memory.selected_node_ids
                and o.get("recommendation") in {"drop", "replace"}
            ]
            if pending_drops and step + 1 < args.max_planner_steps:
                # Observation must change selection before finish is accepted
                nid = pending_drops[0]
                o = memory.strip_observations[nid]
                forced = {
                    "type": "tool",
                    "tool": "unselect_node",
                    "arguments": {
                        "node_id": nid,
                        "why": f"finish_blocked_force_unselect:{o.get('summary')}",
                    },
                    "reason": "observation_feedback_gate",
                }
                fobs = apply_r24_decision(memory, forced)
                trace[-1]["finish_blocked_pending_drops"] = pending_drops
                trace.append({"step": f"{step}_forced_unselect", "decision": forced, "observation": fobs})
                continue
            stop_reason = str((decision.get("arguments") or {}).get("reason") or "finish")
            break

    # Final ensure goals + drop any remaining drop-recommended strips (safety)
    ensure_verified_goals_selected(memory)
    for nid, o in list(memory.strip_observations.items()):
        if nid in memory.selected_node_ids and o.get("recommendation") in {"drop", "replace"}:
            memory.unselect_node(
                nid,
                why=f"final_safety_{o.get('recommendation')}:{o.get('summary')}",
                evidence_id=o.get("evidence_id"),
            )

    rel_doc = finalize_relations(memory)
    _write(out_dir / "story_relations.json", rel_doc)
    _write(
        out_dir / "story_planner_trace.json",
        {
            "schema": "v2_r24_story_planner_trace_v1",
            "elapsed_sec": round(time.time() - t0, 3),
            "stop_reason": stop_reason,
            "planner_mode_log": planner.planner_mode_log,
            "steps": trace,
            "memory_snapshot": memory.snapshot(),
            "api_stats": api.stats.summary(),
            "render_ready": False,
        },
    )

    changes = _selection_changes(r23_sel, memory.selected_node_ids, memory)
    _write(out_dir / "story_selection_changes.json", changes)

    story_graph = build_full_story_graph(
        memory=memory,
        relations_doc=rel_doc,
        score_anchors=digest.get("score_anchors") or [],
        strip_chains=chains,
    )
    _write(out_dir / "story_graph.json", story_graph)
    _write(
        out_dir / "story_beats.json",
        {"schema": "v2_r24_story_beats_v1", "beats": story_graph.get("beats"), "render_ready": False},
    )
    _write(
        out_dir / "story_candidates.json",
        {
            "schema": "v2_r24_story_candidates_v1",
            "discovery_status": memory.discovery_status,
            "candidates": [
                {
                    "story_id": "T01_full_match_r24",
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

    edl = build_r24_candidate_edl(story_graph=story_graph, playout_policy=args.playout_policy)
    _write(out_dir / "candidate_edl.json", edl)

    render_manifest = None
    if not args.skip_render:
        render_manifest = render_r23_candidates(video=args.video, edl=edl, out_dir=out_dir)

    # Quality comparison stub filled by report writer fields
    comparison = {
        "schema": "v2_r24_vs_r23_comparison_v1",
        "r23_dir": str(args.r23_dir),
        "r24_dir": str(out_dir),
        "r23_n_strips": sum(1 for n in r23_sel if n.startswith("strip_")),
        "r24_n_strips": sum(1 for n in memory.selected_node_ids if n.startswith("strip_")),
        "removed_strips": changes["removed"],
        "added_strips": changes["added"],
        "observation_driven_unselects": changes["observation_driven_unselects"],
        "n_relations_r24": len(rel_doc.get("relations") or []),
        "playout_policy": args.playout_policy,
        "render_ready": False,
    }
    _write(out_dir / "story_quality_comparison.json", comparison)

    report = {
        "schema": "v2_strip_guided_r2_4_report_v1",
        "match_id": match_id,
        "git_sha": _git_sha(),
        "elapsed_sec": round(time.time() - t0, 3),
        "r23_dir": str(args.r23_dir),
        "n_verified_goals": key_events.get("n_verified_goals"),
        "n_strips_reviewed": review_doc.get("n_reviewed"),
        "n_strips_selected_r24": sum(1 for n in memory.selected_node_ids if n.startswith("strip_")),
        "selection_changes": {k: changes[k] for k in ("kept", "removed", "added")},
        "n_observation_unselects": len(changes["observation_driven_unselects"]),
        "discovery_status": memory.discovery_status,
        "api_stats": api.stats.summary(),
        "planner_mode_log": planner.planner_mode_log,
        "artifacts": {
            "strip_video_review": str(out_dir / "strip_video_review.json"),
            "story_planner_trace": str(out_dir / "story_planner_trace.json"),
            "story_selection_changes": str(out_dir / "story_selection_changes.json"),
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
                    "n_strips_reviewed",
                    "n_strips_selected_r24",
                    "n_observation_unselects",
                    "selection_changes",
                    "render_ready",
                    "git_sha",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
