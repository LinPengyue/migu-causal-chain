"""V2 Phase A runner: multi-round RSI loop + fixed-frame baseline."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from story_video_agent.api_provider import ApiProvider, COST_DISCLAIMER
from story_video_agent.frames import FrameBudget, FrameStore
from story_video_agent.media import probe_video
from story_video_agent.vision_provider import VisionProvider
from story_video_agent.v2_phase_a_agent import V2PhaseAAgent
from story_video_agent.v2_rsi_toolbox import V2RSIToolbox
from story_video_agent.v2_story_memory import V2StoryMemory


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_multi_round(
    *,
    video: Path,
    out_dir: Path,
    api: ApiProvider,
    max_steps: int = 4,
    frame_budget: int = 16,
    use_llm_planner: bool = True,
    task_brief: str = "",
) -> Dict[str, Any]:
    t0 = time.time()
    media = probe_video(video)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = out_dir / "frames_multi"
    store = FrameStore(media, out_dir=frames_dir, budget=FrameBudget(max_frames=frame_budget))
    vision = VisionProvider(api=api, force_mock=bool(api.force_mock))
    tools = V2RSIToolbox(duration=media.duration_sec, store=store, vision=vision, task_note=task_brief)
    memory = V2StoryMemory()
    agent = V2PhaseAAgent(
        duration=media.duration_sec,
        tools=tools,
        api=api,
        use_llm_planner=use_llm_planner,
        task_brief=task_brief,
    )
    trace: list = []
    stop_reason = "max_steps"
    final_hypothesis: Dict[str, Any] = {}

    for step in range(max_steps):
        try:
            decision = agent.decide(memory, step, max_steps)
        except ValueError as exc:
            trace.append(
                {
                    "step": step,
                    "error": str(exc),
                    "decision_attempts": agent.decision_attempts,
                    "planner_mode": list(agent.planner_mode_log),
                }
            )
            stop_reason = "invalid_decision"
            break
        step_row: Dict[str, Any] = {
            "step": step,
            "decision": decision,
            "decision_attempts": agent.decision_attempts,
            "planner_mode": agent.planner_mode_log[-1] if agent.planner_mode_log else None,
        }
        if decision["type"] == "answer":
            stop_reason = str(decision.get("reason") or "planner_finish")
            final_hypothesis = dict(decision.get("hypothesis") or {})
            if final_hypothesis:
                memory.set_hypothesis(final_hypothesis)
            step_row["observation"] = {"terminal": True}
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
        step_row["observation"] = {
            "purpose": observation.get("purpose"),
            "media_start_sec": observation.get("media_start_sec"),
            "media_end_sec": observation.get("media_end_sec"),
            "error": observation.get("error"),
            "perception_excerpt": {
                "provider_mode": (observation.get("perception") or {}).get("provider_mode"),
                "observed_actions": (observation.get("perception") or {}).get("observed_actions"),
                "frame_ids": (observation.get("perception") or {}).get("frame_ids"),
                "confidence": (observation.get("perception") or {}).get("confidence"),
                "notes": str((observation.get("perception") or {}).get("notes") or "")[:400],
            }
            if isinstance(observation.get("perception"), dict)
            else None,
        }
        trace.append(step_row)
        if store.budget.remaining <= 0:
            stop_reason = "frame_budget_exhausted"
            break
    else:
        stop_reason = "max_steps"

    api_stats = api.stats.summary() if hasattr(api.stats, "summary") else {}
    budget_info = {
        "max_steps": max_steps,
        "frame_budget": frame_budget,
        "frames_used": store.budget.used,
        "api": api_stats,
        "cost_disclaimer": COST_DISCLAIMER,
    }
    evidence = memory.to_story_evidence(
        video=str(video), stop_reason=stop_reason, budget=budget_info
    )
    agent_trace = {
        "schema": "v2_agent_trace_phase_a_v1",
        "path": "multi_round_planner",
        "video": str(video),
        "duration_sec": media.duration_sec,
        "use_llm_planner": use_llm_planner,
        "planner_mode_log": agent.planner_mode_log,
        "trace": trace,
        "stop_reason": stop_reason,
        "elapsed_sec": round(time.time() - t0, 3),
        "api_stats": api_stats,
        "frame_manifest_ref": "frames_multi/manifest.json",
    }
    store.write_manifest(frames_dir / "manifest.json")
    _write(out_dir / "story_evidence.json", evidence)
    _write(out_dir / "agent_trace.json", agent_trace)
    _write(
        out_dir / "run_manifest.json",
        {
            "schema": "v2_phase_a_run_manifest_v1",
            "path": "multi_round",
            "video": str(video),
            "out_dir": str(out_dir),
            "stop_reason": stop_reason,
            "elapsed_sec": agent_trace["elapsed_sec"],
            "frames_used": store.budget.used,
            "api_stats": api_stats,
            "render_ready": False,
            "gates": {"no_events_json": True, "no_causal_json": True},
        },
    )
    return {"evidence": evidence, "agent_trace": agent_trace, "out_dir": str(out_dir)}


def run_fixed_frame(
    *,
    video: Path,
    out_dir: Path,
    api: ApiProvider,
    frame_count: int = 8,
    frame_budget: int = 8,
) -> Dict[str, Any]:
    """Path A: single fixed uniform sample + one Qwen call (no DeepSeek loop)."""
    t0 = time.time()
    media = probe_video(video)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = out_dir / "frames_fixed"
    store = FrameStore(media, out_dir=frames_dir, budget=FrameBudget(max_frames=frame_budget))
    vision = VisionProvider(api=api, force_mock=bool(api.force_mock))
    tools = V2RSIToolbox(duration=media.duration_sec, store=store, vision=vision)
    # one overview-equivalent call
    observation = tools._visual(0.0, media.duration_sec, count=min(frame_count, frame_budget), purpose="overview")
    memory = V2StoryMemory()
    memory.add_tool_result({"tool": "overview", "arguments": {}}, observation)
    memory.set_hypothesis(
        {
            "story_type": "T01_comeback",
            "status": "fixed_frame_single_pass",
            "note": "No DeepSeek multi-round search",
        }
    )
    api_stats = api.stats.summary() if hasattr(api.stats, "summary") else {}
    budget_info = {
        "path": "fixed_frame",
        "frame_count": frame_count,
        "frames_used": store.budget.used,
        "api": api_stats,
        "cost_disclaimer": COST_DISCLAIMER,
    }
    evidence = memory.to_story_evidence(
        video=str(video), stop_reason="single_pass", budget=budget_info
    )
    agent_trace = {
        "schema": "v2_agent_trace_phase_a_v1",
        "path": "fixed_frame",
        "video": str(video),
        "duration_sec": media.duration_sec,
        "trace": [
            {
                "step": 0,
                "decision": {"type": "tool", "tool": "overview", "arguments": {}},
                "observation": {
                    "media_start_sec": 0.0,
                    "media_end_sec": media.duration_sec,
                    "perception_excerpt": {
                        "provider_mode": (observation.get("perception") or {}).get("provider_mode"),
                        "observed_actions": (observation.get("perception") or {}).get("observed_actions"),
                        "frame_ids": (observation.get("perception") or {}).get("frame_ids"),
                    },
                },
            }
        ],
        "stop_reason": "single_pass",
        "elapsed_sec": round(time.time() - t0, 3),
        "api_stats": api_stats,
    }
    store.write_manifest(frames_dir / "manifest.json")
    _write(out_dir / "story_evidence.json", evidence)
    _write(out_dir / "agent_trace.json", agent_trace)
    _write(
        out_dir / "run_manifest.json",
        {
            "schema": "v2_phase_a_run_manifest_v1",
            "path": "fixed_frame",
            "video": str(video),
            "elapsed_sec": agent_trace["elapsed_sec"],
            "frames_used": store.budget.used,
            "api_stats": api_stats,
            "render_ready": False,
        },
    )
    return {"evidence": evidence, "agent_trace": agent_trace, "out_dir": str(out_dir)}


def compare_paths(
    *,
    video: Path,
    out_dir: Path,
    api_factory,
    max_steps: int = 4,
    frame_budget_multi: int = 16,
    frame_count_fixed: int = 8,
    use_llm_planner: bool = True,
) -> Dict[str, Any]:
    """Run A then B with separate ApiProvider instances for clean stats."""
    out_dir.mkdir(parents=True, exist_ok=True)
    api_a = api_factory()
    fixed = run_fixed_frame(
        video=video,
        out_dir=out_dir / "path_a_fixed",
        api=api_a,
        frame_count=frame_count_fixed,
        frame_budget=frame_count_fixed,
    )
    api_b = api_factory()
    multi = run_multi_round(
        video=video,
        out_dir=out_dir / "path_b_multi",
        api=api_b,
        max_steps=max_steps,
        frame_budget=frame_budget_multi,
        use_llm_planner=use_llm_planner,
    )

    def _stats(bundle: Dict[str, Any]) -> Dict[str, Any]:
        tr = bundle["agent_trace"]
        ev = bundle["evidence"]
        return {
            "path": tr.get("path"),
            "elapsed_sec": tr.get("elapsed_sec"),
            "n_trace_steps": len(tr.get("trace") or []),
            "n_observations": len(ev.get("video_evidence") or []),
            "n_candidates": len(ev.get("candidate_events") or []),
            "stop_reason": tr.get("stop_reason") or ev.get("stop_reason"),
            "api_stats": tr.get("api_stats"),
            "planner_modes": tr.get("planner_mode_log"),
        }

    comparison = {
        "schema": "v2_phase_a_compare_v1",
        "video": str(video),
        "path_a_fixed": _stats(fixed),
        "path_b_multi": _stats(multi),
        "notes": [
            "Same clip and separate API counters",
            "Higher candidate count alone is not proof of better quality",
            "Manual review of agent_trace required for hallucination / live-replay errors",
        ],
        "render_ready": False,
    }
    _write(out_dir / "compare_summary.json", comparison)
    return comparison
