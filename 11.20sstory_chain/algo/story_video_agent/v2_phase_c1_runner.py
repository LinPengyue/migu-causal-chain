"""Phase C-1 runner: reuse Phase B evidence → localize goal actions."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from story_video_agent.api_provider import COST_DISCLAIMER, ApiProvider
from story_video_agent.frames import FrameBudget, FrameStore
from story_video_agent.media import probe_video
from story_video_agent.vision_provider import VisionProvider
from story_video_agent.v2_coverage import SearchCoverage
from story_video_agent.v2_phase_c1_agent import V2PhaseC1Agent
from story_video_agent.v2_phase_c1_tasks import TaskBoard, seed_tasks_from_score_analysis
from story_video_agent.v2_phase_c1_toolbox import V2PhaseC1Toolbox
from story_video_agent.v2_phase_c1_verifier import build_localized_event_record, grade_localization
from story_video_agent.v2_score_transitions import independent_discovery_check, unique_score_timeline


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_phase_b(phase_b_dir: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {"dir": str(phase_b_dir)}
    for name in (
        "story_evidence.json",
        "story_discovery.json",
        "search_coverage.json",
        "agent_trace.json",
    ):
        p = phase_b_dir / name
        if p.is_file():
            out[name] = json.loads(p.read_text(encoding="utf-8"))
    return out


def _observations_from_phase_b(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    ev = bundle.get("story_evidence.json") or {}
    rows = []
    for o in ev.get("video_evidence") or []:
        rows.append(o)
    for it in ev.get("evidence_items") or []:
        rows.append(
            {
                "notes": it.get("notes"),
                "observed_actions": it.get("supporting_observations") or it.get("raw_actions"),
                "media_start_sec": it.get("media_start"),
                "media_end_sec": it.get("media_end"),
                "tool": it.get("source_tool"),
            }
        )
    return rows


def run_localization(
    *,
    video: Path,
    out_dir: Path,
    api: ApiProvider,
    phase_b_dir: Optional[Path] = None,
    max_steps: int = 8,
    frame_budget: int = 40,
    use_llm_planner: bool = True,
    media_offset_sec: float = 0.0,
) -> Dict[str, Any]:
    """media_offset_sec: if video is a subclip, absolute = local + offset (for eval only)."""
    t0 = time.time()
    media = probe_video(video)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = out_dir / "frames_c1"
    store = FrameStore(media, out_dir=frames_dir, budget=FrameBudget(max_frames=frame_budget))
    vision = VisionProvider(api=api, force_mock=bool(api.force_mock))
    tools = V2PhaseC1Toolbox(duration=media.duration_sec, store=store, vision=vision)
    coverage = SearchCoverage(duration_sec=media.duration_sec, partition_sec=300.0)

    phase_b = _load_phase_b(phase_b_dir) if phase_b_dir else {}
    obs_b = _observations_from_phase_b(phase_b) if phase_b else []
    # If Phase B times are absolute and we run on a subclip, shift into local.
    if media_offset_sec and obs_b:
        shifted = []
        for o in obs_b:
            s = o.get("media_start_sec")
            e = o.get("media_end_sec")
            if s is None:
                shifted.append(o)
                continue
            s2, e2 = float(s) - media_offset_sec, float(e) - media_offset_sec if e is not None else None
            if e2 is not None and e2 <= 0 or s2 >= media.duration_sec:
                continue
            no = dict(o)
            no["media_start_sec"] = max(0.0, s2)
            no["media_end_sec"] = min(media.duration_sec, max(0.0, e2 if e2 is not None else s2))
            shifted.append(no)
        obs_b = shifted

    check = independent_discovery_check(
        llm_status=str((phase_b.get("story_discovery.json") or {}).get("discovery_status") or "unresolved"),
        observations=obs_b,
    )
    analysis = check["analysis"]
    board = TaskBoard(seed_tasks_from_score_analysis(analysis))
    # Clamp candidate windows to this video duration
    for t in board.tasks:
        cw = t.get("candidate_window")
        if not cw:
            continue
        t["candidate_window"] = {
            "start": max(0.0, float(cw["start"])),
            "end": min(media.duration_sec, float(cw["end"])),
        }

    agent = V2PhaseC1Agent(
        duration=media.duration_sec, tools=tools, api=api, use_llm_planner=use_llm_planner
    )
    localized: List[Dict[str, Any]] = []
    evidence_items: List[Dict[str, Any]] = []
    trace: List[Dict[str, Any]] = []
    stop_reason = "max_steps"
    evidence_counter = 0

    def facts() -> Dict[str, Any]:
        return {
            "discovery_check": {
                "final_status": check["final_status"],
                "demoted": check["demoted"],
                "score_suggested_status": check["score_suggested_status"],
            },
            "score_events": analysis.get("events"),
            "open_tasks": board.open_tasks(),
            "all_tasks": board.tasks,
            "localized_tail": localized[-5:],
            "n_localized": len(localized),
            "phase_b_reused": bool(phase_b),
        }

    for step in range(max_steps):
        decision = agent.decide(facts(), step, max_steps)
        step_row: Dict[str, Any] = {
            "step": step,
            "decision": decision,
            "decision_attempts": agent.decision_attempts,
            "planner_mode": agent.planner_mode_log[-1] if agent.planner_mode_log else None,
        }
        if decision["type"] == "answer":
            stop_reason = str(decision.get("reason") or decision.get("answer"))
            step_row["observation"] = {"terminal": True}
            trace.append(step_row)
            break
        tid = (decision.get("arguments") or {}).get("task_id")
        if tid:
            board.mark_searching(str(tid))
        try:
            observation = tools.execute(decision["tool"], decision.get("arguments") or {})
        except Exception as exc:  # noqa: BLE001
            observation = {"error": type(exc).__name__, "message": str(exc)[:240]}
        coverage.add(
            tool=str(decision.get("tool")),
            requested_start=observation.get("media_start_sec"),
            requested_end=observation.get("media_end_sec"),
            sampled_times=observation.get("sampled_media_times") or [],
            observed="error" not in observation
            and bool((observation.get("perception") or {}).get("normalized_ok")),
            failed="error" in observation,
            frame_ids=(observation.get("perception") or {}).get("frame_ids") or [],
            error=observation.get("error"),
        )
        task = board.get(str(tid)) if tid else None
        expected = None
        if task and task.get("expected_score_after"):
            expected = tuple(task["expected_score_after"])  # type: ignore[arg-type]
        grade_info = grade_localization(
            observation=observation,
            task_role=str((task or {}).get("narrative_need") or "unknown"),
            expected_score_after=expected,
            window_span_sec=(
                float(observation["media_end_sec"]) - float(observation["media_start_sec"])
                if observation.get("media_start_sec") is not None
                else None
            ),
        )
        evidence_counter += 1
        eid = f"c1_ev_{evidence_counter:03d}"
        if task:
            board.update_from_grade(
                task["task_id"],
                grade=str(grade_info["grade"]),
                evidence_id=eid,
                frame_ids=(observation.get("perception") or {}).get("frame_ids") or [],
                refined_window={
                    "start": observation.get("media_start_sec"),
                    "end": observation.get("media_end_sec"),
                }
                if observation.get("media_start_sec") is not None
                else None,
                notes=str(grade_info.get("reasons") or ""),
            )
            loc = build_localized_event_record(
                task=task, observation=observation, grade_info=grade_info
            )
            loc["evidence_id"] = eid
            loc["absolute_media_offset_sec"] = media_offset_sec
            localized.append(loc)
            evidence_items.append(
                {
                    "evidence_id": eid,
                    "task_id": task["task_id"],
                    "localization_grade": grade_info["grade"],
                    "media_start": observation.get("media_start_sec"),
                    "media_end": observation.get("media_end_sec"),
                    "frame_ids": (observation.get("perception") or {}).get("frame_ids"),
                    "verification_status": (
                        "corroborated"
                        if grade_info["grade"] == "action_corroborated"
                        else "unverified"
                    ),
                    "observation_status": grade_info["grade"],
                }
            )
        step_row["observation"] = {
            "purpose": observation.get("purpose"),
            "task_id": tid,
            "media_start_sec": observation.get("media_start_sec"),
            "media_end_sec": observation.get("media_end_sec"),
            "sampled_media_times": observation.get("sampled_media_times"),
            "error": observation.get("error"),
            "grade": grade_info,
            "perception_excerpt": {
                "provider_mode": (observation.get("perception") or {}).get("provider_mode"),
                "observed_actions": (observation.get("perception") or {}).get("observed_actions"),
                "frame_ids": (observation.get("perception") or {}).get("frame_ids"),
                "notes": str((observation.get("perception") or {}).get("notes") or "")[:500],
            },
        }
        trace.append(step_row)
        if store.budget.remaining <= 0:
            stop_reason = "frame_budget_exhausted"
            break
        if not board.open_tasks():
            stop_reason = "all_tasks_closed"
            break
    else:
        stop_reason = "max_steps"

    api_stats = api.stats.summary() if hasattr(api.stats, "summary") else {}
    story_evidence = {
        "schema": "v2_story_evidence_phase_c1_v1",
        "video": str(video),
        "media_offset_sec": media_offset_sec,
        "phase_b_dir": str(phase_b_dir) if phase_b_dir else None,
        "discovery_check": check,
        "evidence_items": evidence_items,
        "localized_event_refs": [x.get("evidence_id") for x in localized],
        "stop_reason": stop_reason,
        "budget": {
            "max_steps": max_steps,
            "frame_budget": frame_budget,
            "frames_used": store.budget.used,
            "api": api_stats,
            "cost_disclaimer": COST_DISCLAIMER,
        },
        "semantic_verified": False,
        "render_ready": False,
    }
    agent_trace = {
        "schema": "v2_agent_trace_phase_c1_v1",
        "path": "localization",
        "video": str(video),
        "duration_sec": media.duration_sec,
        "planner_mode_log": agent.planner_mode_log,
        "trace": trace,
        "stop_reason": stop_reason,
        "elapsed_sec": round(time.time() - t0, 3),
        "api_stats": api_stats,
        "frames_used": store.budget.used,
    }
    store.write_manifest(frames_dir / "manifest.json")
    _write(out_dir / "story_evidence_tasks.json", board.to_json())
    _write(out_dir / "localized_events.json", {"schema": "v2_localized_events_v1", "events": localized, "render_ready": False})
    _write(out_dir / "story_evidence.json", story_evidence)
    _write(out_dir / "agent_trace.json", agent_trace)
    _write(out_dir / "search_coverage.json", coverage.summary())
    _write(
        out_dir / "run_manifest.json",
        {
            "schema": "v2_phase_c1_run_manifest_v1",
            "video": str(video),
            "phase_b_dir": str(phase_b_dir) if phase_b_dir else None,
            "stop_reason": stop_reason,
            "elapsed_sec": agent_trace["elapsed_sec"],
            "frames_used": store.budget.used,
            "discovery_final_status": check["final_status"],
            "task_counts": board.to_json()["counts"],
            "api_stats": api_stats,
            "render_ready": False,
            "gates": {"no_events_json": True, "no_causal_json": True, "no_match_hardcode": True},
        },
    )
    # Keyframe export list for human review (paths only)
    review = []
    for ev in localized:
        for fr in ev.get("frames") or []:
            if fr.get("path"):
                review.append(
                    {
                        "task_id": ev.get("task_id"),
                        "grade": ev.get("localization_grade"),
                        "frame_id": fr.get("frame_id"),
                        "media_sec": fr.get("requested_media_sec"),
                        "path": fr.get("path"),
                    }
                )
    _write(out_dir / "review_frames.json", {"schema": "v2_c1_review_frames_v1", "frames": review})
    return {
        "out_dir": str(out_dir),
        "agent_trace": agent_trace,
        "localized": localized,
        "tasks": board.to_json(),
        "discovery_check": check,
    }
