"""Phase B runner: hierarchical multi-round discovery + matched-budget fixed baseline."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from story_video_agent.api_provider import COST_DISCLAIMER, ApiProvider
from story_video_agent.frames import FrameBudget, FrameStore
from story_video_agent.media import probe_video
from story_video_agent.vision_provider import VisionProvider
from story_video_agent.v2_phase_b_agent import V2PhaseBAgent
from story_video_agent.v2_phase_b_memory import V2PhaseBMemory
from story_video_agent.v2_phase_b_toolbox import V2PhaseBToolbox


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _budget_block(api: ApiProvider, *, frames_used: int, frame_budget: int, extra: Dict[str, Any]) -> Dict[str, Any]:
    api_stats = api.stats.summary() if hasattr(api.stats, "summary") else {}
    return {
        **extra,
        "frame_budget": frame_budget,
        "frames_used": frames_used,
        "api": api_stats,
        "cost_disclaimer": COST_DISCLAIMER,
        "accounting_note": (
            "Compare paths using frames_used and api.total_tokens / est_cost_usd_real; "
            "do not treat candidate counts as quality."
        ),
    }


def run_multi_discovery(
    *,
    video: Path,
    out_dir: Path,
    api: ApiProvider,
    max_steps: int = 6,
    frame_budget: int = 32,
    partition_sec: float = 600.0,
    overview_frames: int = 8,
    partition_frames: int = 4,
    use_llm_planner: bool = True,
) -> Dict[str, Any]:
    t0 = time.time()
    media = probe_video(video)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = out_dir / "frames_multi"
    store = FrameStore(media, out_dir=frames_dir, budget=FrameBudget(max_frames=frame_budget))
    vision = VisionProvider(api=api, force_mock=bool(api.force_mock))
    tools = V2PhaseBToolbox(
        duration=media.duration_sec,
        store=store,
        vision=vision,
        overview_frames=overview_frames,
        partition_frames=partition_frames,
    )
    memory = V2PhaseBMemory(duration_sec=media.duration_sec, partition_sec=partition_sec)
    agent = V2PhaseBAgent(
        duration=media.duration_sec,
        tools=tools,
        api=api,
        use_llm_planner=use_llm_planner,
    )
    trace: list = []
    stop_reason = "max_steps"

    for step in range(max_steps):
        try:
            decision = agent.decide(memory, step, max_steps)
        except ValueError as exc:
            trace.append({"step": step, "error": str(exc), "decision_attempts": agent.decision_attempts})
            stop_reason = "invalid_decision"
            break
        step_row: Dict[str, Any] = {
            "step": step,
            "decision": decision,
            "decision_attempts": agent.decision_attempts,
            "planner_mode": agent.planner_mode_log[-1] if agent.planner_mode_log else None,
        }
        if decision["type"] == "answer":
            stop_reason = str(decision.get("reason") or decision.get("answer") or "planner_finish")
            hyp = dict(decision.get("hypothesis") or {})
            hyp.setdefault("discovery_status", decision.get("answer"))
            memory.set_hypothesis(hyp)
            step_row["observation"] = {"terminal": True, "answer": decision.get("answer")}
            trace.append(step_row)
            break
        if agent.argument_error is not None:
            observation = dict(agent.argument_error)
        else:
            try:
                observation = tools.execute(decision["tool"], decision.get("arguments") or {})
            except Exception as exc:  # noqa: BLE001
                observation = {"error": type(exc).__name__, "message": str(exc)[:240]}
        memory.add_tool_result(decision, observation)
        perc = observation.get("perception") if isinstance(observation.get("perception"), dict) else {}
        step_row["observation"] = {
            "purpose": observation.get("purpose"),
            "layer": observation.get("layer"),
            "media_start_sec": observation.get("media_start_sec"),
            "media_end_sec": observation.get("media_end_sec"),
            "sampled_media_times": observation.get("sampled_media_times"),
            "error": observation.get("error"),
            "perception_excerpt": {
                "provider_mode": perc.get("provider_mode"),
                "observed_actions": perc.get("observed_actions"),
                "frame_ids": perc.get("frame_ids"),
                "confidence": perc.get("confidence"),
                "notes": str(perc.get("notes") or "")[:500],
            }
            if perc
            else None,
        }
        trace.append(step_row)
        if store.budget.remaining <= 0:
            stop_reason = "frame_budget_exhausted"
            break
    else:
        stop_reason = "max_steps"

    budget = _budget_block(
        api,
        frames_used=store.budget.used,
        frame_budget=frame_budget,
        extra={"max_steps": max_steps, "path": "multi_hierarchical"},
    )
    evidence = memory.to_story_evidence(video=str(video), stop_reason=stop_reason, budget=budget)
    discovery = memory.to_story_discovery(video=str(video), stop_reason=stop_reason)
    tasks = memory.to_evidence_tasks()
    coverage = memory.coverage.summary()
    agent_trace = {
        "schema": "v2_agent_trace_phase_b_v1",
        "path": "multi_hierarchical",
        "video": str(video),
        "duration_sec": media.duration_sec,
        "use_llm_planner": use_llm_planner,
        "planner_mode_log": agent.planner_mode_log,
        "trace": trace,
        "stop_reason": stop_reason,
        "elapsed_sec": round(time.time() - t0, 3),
        "api_stats": budget["api"],
        "frames_used": store.budget.used,
    }
    manifest = {
        "schema": "v2_phase_b_run_manifest_v1",
        "path": "multi_hierarchical",
        "video": str(video),
        "out_dir": str(out_dir),
        "stop_reason": stop_reason,
        "discovery_status": memory.discovery_status,
        "elapsed_sec": agent_trace["elapsed_sec"],
        "frames_used": store.budget.used,
        "frame_budget": frame_budget,
        "api_stats": budget["api"],
        "render_ready": False,
        "gates": {"no_events_json": True, "no_causal_json": True},
    }
    store.write_manifest(frames_dir / "manifest.json")
    _write(out_dir / "story_evidence.json", evidence)
    _write(out_dir / "story_discovery.json", discovery)
    _write(out_dir / "story_evidence_tasks.json", tasks)
    _write(out_dir / "search_coverage.json", coverage)
    _write(out_dir / "agent_trace.json", agent_trace)
    _write(out_dir / "run_manifest.json", manifest)
    return {
        "evidence": evidence,
        "discovery": discovery,
        "agent_trace": agent_trace,
        "coverage": coverage,
        "out_dir": str(out_dir),
    }


def run_fixed_matched_budget(
    *,
    video: Path,
    out_dir: Path,
    api: ApiProvider,
    frame_count: int,
    frame_budget: Optional[int] = None,
) -> Dict[str, Any]:
    """Non-active baseline: one sparse uniform sample with SAME frame count as multi used/planned."""
    t0 = time.time()
    media = probe_video(video)
    out_dir.mkdir(parents=True, exist_ok=True)
    fb = int(frame_budget or frame_count)
    frames_dir = out_dir / "frames_fixed"
    store = FrameStore(media, out_dir=frames_dir, budget=FrameBudget(max_frames=fb))
    vision = VisionProvider(api=api, force_mock=bool(api.force_mock))
    tools = V2PhaseBToolbox(duration=media.duration_sec, store=store, vision=vision)
    observation = tools._visual(
        0.0, media.duration_sec, count=min(frame_count, fb), purpose="global_overview", layer=1
    )
    memory = V2PhaseBMemory(duration_sec=media.duration_sec)
    memory.add_tool_result({"tool": "global_overview", "arguments": {}}, observation)
    memory.set_hypothesis(
        {
            "discovery_status": "unresolved",
            "status": "fixed_matched_budget_single_pass",
            "note": "No DeepSeek multi-round search; matched visual frame budget only",
        }
    )
    budget = _budget_block(
        api,
        frames_used=store.budget.used,
        frame_budget=fb,
        extra={"path": "fixed_matched_budget", "frame_count": frame_count},
    )
    evidence = memory.to_story_evidence(video=str(video), stop_reason="single_pass", budget=budget)
    discovery = memory.to_story_discovery(video=str(video), stop_reason="single_pass")
    coverage = memory.coverage.summary()
    agent_trace = {
        "schema": "v2_agent_trace_phase_b_v1",
        "path": "fixed_matched_budget",
        "video": str(video),
        "duration_sec": media.duration_sec,
        "trace": [
            {
                "step": 0,
                "decision": {"type": "tool", "tool": "global_overview", "arguments": {}},
                "observation": {
                    "media_start_sec": 0.0,
                    "media_end_sec": media.duration_sec,
                    "sampled_media_times": observation.get("sampled_media_times"),
                    "perception_excerpt": {
                        "provider_mode": (observation.get("perception") or {}).get("provider_mode"),
                        "observed_actions": (observation.get("perception") or {}).get("observed_actions"),
                        "frame_ids": (observation.get("perception") or {}).get("frame_ids"),
                        "notes": str((observation.get("perception") or {}).get("notes") or "")[:500],
                    },
                },
            }
        ],
        "stop_reason": "single_pass",
        "elapsed_sec": round(time.time() - t0, 3),
        "api_stats": budget["api"],
        "frames_used": store.budget.used,
    }
    store.write_manifest(frames_dir / "manifest.json")
    _write(out_dir / "story_evidence.json", evidence)
    _write(out_dir / "story_discovery.json", discovery)
    _write(out_dir / "story_evidence_tasks.json", memory.to_evidence_tasks())
    _write(out_dir / "search_coverage.json", coverage)
    _write(out_dir / "agent_trace.json", agent_trace)
    _write(
        out_dir / "run_manifest.json",
        {
            "schema": "v2_phase_b_run_manifest_v1",
            "path": "fixed_matched_budget",
            "video": str(video),
            "elapsed_sec": agent_trace["elapsed_sec"],
            "frames_used": store.budget.used,
            "frame_budget": fb,
            "api_stats": budget["api"],
            "render_ready": False,
        },
    )
    return {
        "evidence": evidence,
        "discovery": discovery,
        "agent_trace": agent_trace,
        "coverage": coverage,
        "out_dir": str(out_dir),
    }


def compare_paths(
    *,
    video: Path,
    out_dir: Path,
    api_factory,
    max_steps: int = 6,
    frame_budget_multi: int = 32,
    partition_sec: float = 600.0,
    use_llm_planner: bool = True,
    match_fixed_to_multi_frames: bool = True,
) -> Dict[str, Any]:
    """Run multi first, then fixed with matched frames_used (fairer than Phase A 4 vs 12)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    api_b = api_factory()
    multi = run_multi_discovery(
        video=video,
        out_dir=out_dir / "path_b_multi",
        api=api_b,
        max_steps=max_steps,
        frame_budget=frame_budget_multi,
        partition_sec=partition_sec,
        use_llm_planner=use_llm_planner,
    )
    frames_multi = int(multi["agent_trace"].get("frames_used") or frame_budget_multi)
    fixed_n = frames_multi if match_fixed_to_multi_frames else min(8, frame_budget_multi)
    api_a = api_factory()
    fixed = run_fixed_matched_budget(
        video=video,
        out_dir=out_dir / "path_a_fixed_matched",
        api=api_a,
        frame_count=max(4, fixed_n),
        frame_budget=max(4, fixed_n),
    )

    def _stats(bundle: Dict[str, Any], label: str) -> Dict[str, Any]:
        tr = bundle["agent_trace"]
        ev = bundle["evidence"]
        cov = bundle["coverage"]
        return {
            "path": label,
            "elapsed_sec": tr.get("elapsed_sec"),
            "frames_used": tr.get("frames_used"),
            "n_trace_steps": len(tr.get("trace") or []),
            "n_evidence_items_deduped": len(ev.get("evidence_items") or []),
            "evidence_status_counts": ev.get("evidence_status_counts"),
            "discovery_status": (bundle.get("discovery") or {}).get("discovery_status"),
            "stop_reason": tr.get("stop_reason"),
            "api_stats": tr.get("api_stats"),
            "planner_modes": tr.get("planner_mode_log"),
            "coverage_fraction_observed": cov.get("fraction_partitions_with_observation"),
            "partitions_untouched": cov.get("partitions_untouched"),
        }

    comparison = {
        "schema": "v2_phase_b_compare_v1",
        "video": str(video),
        "match_fixed_to_multi_frames": match_fixed_to_multi_frames,
        "path_a_fixed_matched": _stats(fixed, "fixed_matched_budget"),
        "path_b_multi": _stats(multi, "multi_hierarchical"),
        "notes": [
            "Fixed baseline uses the same visual frame count as multi after multi completes",
            "Multi still spends extra DeepSeek planner tokens — report separately",
            "Do not use raw evidence_item counts as correctness",
        ],
        "render_ready": False,
    }
    _write(out_dir / "compare_summary.json", comparison)
    return comparison
