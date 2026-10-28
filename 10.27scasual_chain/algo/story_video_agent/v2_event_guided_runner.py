"""Event-Guided runner: MP4 + events.json → discovery + action verification."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from story_video_agent.api_provider import COST_DISCLAIMER, ApiProvider
from story_video_agent.frames import FrameBudget, FrameStore
from story_video_agent.media import probe_video
from story_video_agent.vision_provider import VisionProvider
from story_video_agent.v2_event_adapter import (
    candidate_events_near_anchors,
    load_events_json,
    planner_event_digest,
    score_transition_anchors,
)
from story_video_agent.v2_event_guided_agent import V2EventGuidedAgent
from story_video_agent.v2_event_guided_eval import (
    eval_action_windows,
    eval_inferred_relations_vs_causal,
    load_action_gold_from_story_graph,
)
from story_video_agent.v2_event_guided_memory import EventGuidedMemory
from story_video_agent.v2_phase_c1_toolbox import V2PhaseC1Toolbox
from story_video_agent.v2_phase_c1_verifier import grade_localization


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _score_pairs_from_anchors(anchors: List[Dict[str, Any]]) -> List[tuple]:
    pairs: List[tuple] = []
    for a in anchors:
        if a.get("kind") == "initial_score" and a.get("score_pair"):
            pairs.append(tuple(a["score_pair"]))
        if a.get("kind") == "score_change" and a.get("score_after"):
            pairs.append(tuple(a["score_after"]))
    return pairs


def _apply_score_anchor_override(
    decision: Dict[str, Any], anchors: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Independent T01 check from Score_Recognition timeline — demote false no_comeback."""
    out = dict(decision)
    pairs = _score_pairs_from_anchors(anchors)
    if len(pairs) < 2:
        return out
    first, later = pairs[0], pairs[-1]
    flipped = (first[0] < first[1] and later[0] > later[1]) or (
        first[1] < first[0] and later[1] > later[0]
    )
    ans = str(out.get("answer") or "")
    if flipped and ans in {"no_comeback", "unresolved"}:
        out["answer"] = "story_candidate"
        out["override"] = {
            "from": ans,
            "to": "story_candidate",
            "rule": "score_anchor_deficit_to_lead",
            "pairs": [list(p) for p in pairs],
        }
        out["reason"] = (
            f"override:{ans}->story_candidate; deficit_to_lead_on_score_anchors; "
            + str(out.get("reason") or "")
        )
    elif flipped and ans == "partial_story":
        out["answer"] = "story_candidate"
        out["override"] = {
            "from": ans,
            "to": "story_candidate",
            "rule": "score_anchor_deficit_to_lead",
            "pairs": [list(p) for p in pairs],
        }
    return out


def run_event_guided(
    *,
    video: Path,
    events_path: Path,
    out_dir: Path,
    api: ApiProvider,
    input_source: str = "human_corrected",
    max_steps: int = 12,
    frame_budget: int = 48,
    use_llm_planner: bool = True,
    gold_story_graph: Optional[Path] = None,
    causal_path_offline: Optional[Path] = None,
) -> Dict[str, Any]:
    t0 = time.time()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    bundle = load_events_json(Path(events_path), input_source=input_source)
    anchors = score_transition_anchors(bundle["events"])
    # Ensure digest uses refreshed anchors
    digest = planner_event_digest(bundle)
    digest["score_anchors"] = anchors
    candidates = candidate_events_near_anchors(bundle["events"], anchors)

    _write(out_dir / "event_bundle_sanitized.json", bundle)
    _write(out_dir / "event_digest.json", digest)
    _write(
        out_dir / "event_candidates.json",
        {"schema": "v2_event_candidates_v1", "candidates": candidates},
    )

    media = probe_video(video)
    frames_dir = out_dir / "frames_eg"
    store = FrameStore(media, out_dir=frames_dir, budget=FrameBudget(max_frames=frame_budget))
    vision = VisionProvider(api=api, force_mock=bool(api.force_mock))
    tools = V2PhaseC1Toolbox(
        duration=media.duration_sec,
        store=store,
        vision=vision,
        task_note=(
            "Event-Guided verification: confirm real goal/shot actions near event "
            "time anchors. Separate live vs replay. Do not invent unobserved contacts."
        ),
    )
    memory = EventGuidedMemory(duration=media.duration_sec, event_digest=digest)
    agent = V2EventGuidedAgent(
        duration=media.duration_sec,
        tools=tools,
        api=api,
        use_llm_planner=use_llm_planner,
    )

    trace: List[Dict[str, Any]] = []
    stop_reason = "max_steps"
    final_answer: Dict[str, Any] = {}

    for step in range(max_steps):
        decision = agent.decide(memory, step, max_steps)
        step_row: Dict[str, Any] = {
            "step": step,
            "decision": decision,
            "decision_attempts": agent.decision_attempts,
            "planner_mode": agent.planner_mode_log[-1] if agent.planner_mode_log else None,
        }
        if decision["type"] == "answer":
            stop_reason = str(decision.get("reason") or decision.get("answer"))
            final_answer = _apply_score_anchor_override(decision, anchors)
            memory.discovery_status = str(final_answer.get("answer"))
            memory.discovery_reason = str(final_answer.get("reason") or stop_reason)
            memory.inferred_beats = final_answer.get("beats") or {}
            memory.inferred_relations = final_answer.get("relations") or []
            step_row["observation"] = {"terminal": True, "override": final_answer.get("override")}
            step_row["decision_final"] = final_answer
            trace.append(step_row)
            break

        obs = tools.execute(decision["tool"], decision.get("arguments") or {})
        span = None
        if obs.get("media_start_sec") is not None and obs.get("media_end_sec") is not None:
            span = float(obs["media_end_sec"]) - float(obs["media_start_sec"])
        grade = grade_localization(
            observation=obs,
            task_role="event_guided_verify",
            window_span_sec=span,
        )
        row = {
            "task_id": obs.get("task_id") or (decision.get("arguments") or {}).get("task_id"),
            "tool": decision["tool"],
            "media_start_sec": obs.get("media_start_sec"),
            "media_end_sec": obs.get("media_end_sec"),
            "perception": obs.get("perception"),
            "grade": grade,
            "error": obs.get("error"),
            "fact_verified": False,
            "observation_only": True,
        }
        memory.add_verification(row)
        memory.add_search(
            {
                "tool": decision["tool"],
                "arguments": decision.get("arguments"),
                "task_id": row["task_id"],
            }
        )
        step_row["observation"] = {
            "task_id": row["task_id"],
            "grade": grade.get("grade"),
            "media_start_sec": row["media_start_sec"],
            "media_end_sec": row["media_end_sec"],
            "error": row.get("error"),
        }
        trace.append(step_row)

        if store.budget.remaining <= 0:
            stop_reason = "frame_budget_exhausted"
            final_answer = _apply_score_anchor_override(
                agent.finish_from_memory(memory, reason=stop_reason), anchors
            )
            memory.discovery_status = str(final_answer.get("answer"))
            memory.discovery_reason = str(final_answer.get("reason") or stop_reason)
            memory.inferred_beats = final_answer.get("beats") or {}
            memory.inferred_relations = final_answer.get("relations") or []
            break

    if not memory.discovery_status:
        stop_reason = stop_reason if stop_reason != "max_steps" else "max_steps_synthesize"
        final_answer = _apply_score_anchor_override(
            agent.finish_from_memory(memory, reason=stop_reason), anchors
        )
        memory.discovery_status = str(final_answer.get("answer"))
        memory.discovery_reason = str(final_answer.get("reason") or stop_reason)
        memory.inferred_beats = final_answer.get("beats") or {}
        memory.inferred_relations = final_answer.get("relations") or []

    api_stats = api.stats.summary()
    discovery = {
        "schema": "v2_event_guided_discovery_v1",
        "mode": "event_guided",
        "input_source": input_source,
        "discovery_status": memory.discovery_status or final_answer.get("answer"),
        "reason": memory.discovery_reason or final_answer.get("reason"),
        "beats": memory.inferred_beats,
        "relations": memory.inferred_relations,
        "score_anchors": anchors,
        "n_score_changes": sum(1 for a in anchors if a.get("kind") == "score_change"),
        "forbidden_inputs_not_used": bundle.get("forbidden_as_model_input"),
        "render_ready": False,
    }

    evidence = {
        "schema": "v2_event_guided_evidence_v1",
        "input_source": input_source,
        "verifications": memory.verifications,
        "grade_counts": {},
        "render_ready": False,
    }
    for v in memory.verifications:
        g = (v.get("grade") or {}).get("grade") if isinstance(v.get("grade"), dict) else None
        if g:
            evidence["grade_counts"][g] = evidence["grade_counts"].get(g, 0) + 1

    # Offline eval only
    offline_eval: Dict[str, Any] = {
        "schema": "v2_event_guided_offline_eval_v1",
        "action_eval": None,
        "relation_eval": eval_inferred_relations_vs_causal(
            relations=memory.inferred_relations,
            causal_path=causal_path_offline,
        ),
        "note": "Gold/causal used only after inference",
    }
    if gold_story_graph and Path(gold_story_graph).is_file():
        gold = load_action_gold_from_story_graph(Path(gold_story_graph))
        offline_eval["action_eval"] = eval_action_windows(
            verified=memory.verifications, gold=gold
        )

    agent_trace = {
        "schema": "v2_event_guided_trace_v1",
        "elapsed_sec": round(time.time() - t0, 3),
        "stop_reason": stop_reason,
        "max_steps": max_steps,
        "steps": trace,
        "frames_used": store.budget.used,
        "frame_budget": frame_budget,
        "api_stats": api_stats,
        "cost_disclaimer": COST_DISCLAIMER,
        "planner_mode_log": agent.planner_mode_log,
        "render_ready": False,
    }

    _write(out_dir / "story_discovery.json", discovery)
    _write(out_dir / "story_evidence.json", evidence)
    _write(out_dir / "agent_trace.json", agent_trace)
    _write(out_dir / "memory_snapshot.json", memory.snapshot())
    _write(out_dir / "offline_eval.json", offline_eval)

    return {
        "discovery": discovery,
        "evidence": evidence,
        "agent_trace": agent_trace,
        "offline_eval": offline_eval,
        "event_bundle_meta": {
            "n_raw": bundle.get("n_raw"),
            "n_kept": bundle.get("n_kept"),
            "n_dropped": bundle.get("n_dropped"),
            "input_source": input_source,
        },
        "render_ready": False,
    }
