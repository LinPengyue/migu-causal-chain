"""Event-Guided runner Round 2: fixed | rule | agent modes."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from story_video_agent.api_provider import COST_DISCLAIMER, ApiProvider
from story_video_agent.frames import FrameBudget, FrameStore
from story_video_agent.media import probe_video
from story_video_agent.vision_provider import VisionProvider
from story_video_agent.v2_event_adapter import load_events_json, planner_event_digest
from story_video_agent.v2_event_guided_agent import V2EventGuidedAgent
from story_video_agent.v2_event_guided_candidate_board import CandidateBoard
from story_video_agent.v2_event_guided_clip_export import export_candidate_review_pack
from story_video_agent.v2_event_guided_evidence import (
    build_goal_candidate_record,
    grade_with_frame_evidence,
)
from story_video_agent.v2_event_guided_eval import (
    eval_action_windows,
    load_action_gold_from_story_graph,
)
from story_video_agent.v2_event_guided_memory import EventGuidedMemory
from story_video_agent.v2_event_guided_r2_audit import (
    evaluate_localization_against_refs,
    load_v1_reference_nodes,
)
from story_video_agent.v2_event_guided_relation import review_relations
from story_video_agent.v2_phase_c1_toolbox import V2PhaseC1Toolbox

PURPOSE_TO_C1 = {
    "dense": "dense_action_inspect",
    "coarse": "coarse_search",
    "live_replay": "verify_live_replay",
    "scoreboard": "read_scoreboard_window",
}


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
    out = dict(decision)
    pairs = _score_pairs_from_anchors(anchors)
    if len(pairs) < 2:
        return out
    first, later = pairs[0], pairs[-1]
    flipped = (first[0] < first[1] and later[0] > later[1]) or (
        first[1] < first[0] and later[1] > later[0]
    )
    ans = str(out.get("answer") or "")
    if flipped and ans in {"no_comeback", "unresolved", "partial_story"}:
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
    return out


def _run_fixed_baseline(
    *,
    bundle: Dict[str, Any],
    board: CandidateBoard,
    out_dir: Path,
    video: Path,
) -> Dict[str, Any]:
    """Event-Fixed: cut fixed windows at event times — no DeepSeek/Qwen search."""
    records = []
    for c in board.list_candidates():
        t = c.get("event_time_sec")
        if t is None:
            continue
        # Only score-change anchor events / nearby Goal|Shot
        if c.get("event_type") not in {"Goal", "Shot", "Save"} and not c.get("anchor"):
            continue
        start = max(0.0, float(t) - 8.0)
        end = float(t) + 4.0
        rec = {
            "schema": "v2_goal_candidate_evidence_v1",
            "candidate_event_id": c["candidate_event_id"],
            "event_time_sec": t,
            "localized_media_in": start,
            "localized_media_out": end,
            "supporting_frame_ids": [],
            "observed_action_sequence": [],
            "shooting_action_evidence": False,
            "goal_result_evidence": False,
            "live_or_replay": "unknown",
            "verification_status": "fixed_window_unverified",
            "uncertainty": 0.9,
            "grade": "unresolved",
            "mode": "event_fixed",
            "render_ready": False,
        }
        records.append(rec)
        board.confirm_localization(
            c["candidate_event_id"],
            media_in=start,
            media_out=end,
            evidence_record=rec,
        )
    return {
        "mode": "event_fixed",
        "evidence_records": records,
        "discovery_status": "partial_story",
        "reason": "fixed_windows_no_vlm",
        "api_stats": {"real_ok": 0, "est_cost_usd_real": 0.0, "calls": 0},
        "frames_used": 0,
    }


def run_event_guided(
    *,
    video: Path,
    events_path: Path,
    out_dir: Path,
    api: ApiProvider,
    input_source: str = "human_corrected",
    planner_mode: str = "agent",  # agent | rule | fixed
    max_steps: int = 16,
    frame_budget: int = 64,
    use_llm_planner: bool = True,
    gold_story_graph: Optional[Path] = None,
    gold_edl: Optional[Path] = None,
    causal_path_offline: Optional[Path] = None,
    export_review_clips: bool = True,
    focus_event_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    t0 = time.time()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    bundle = load_events_json(Path(events_path), input_source=input_source)
    digest = planner_event_digest(bundle)
    board = CandidateBoard(bundle["events"], pad_sec=120.0)
    # Optional focus: keep only candidates near focus ids / times for targeted smoke
    if focus_event_ids:
        keep = set(focus_event_ids)
        # Resolve focus event times from full bundle so lag probes / nearby events survive
        focus_times = []
        for e in bundle["events"]:
            if e.get("event_id") in keep and e.get("event_time_sec") is not None:
                focus_times.append(float(e["event_time_sec"]))
        for a in board.list_anchors():
            if a.get("event_id") in keep and a.get("event_time_sec") is not None:
                focus_times.append(float(a["event_time_sec"]))
        for cid, c in list(board.candidates.items()):
            aid = (c.get("anchor") or {}).get("anchor_event_id")
            t = c.get("event_time_sec")
            near = bool(
                t is not None
                and focus_times
                and any(abs(float(t) - ft) <= 200.0 for ft in focus_times)
            )
            if cid in keep or aid in keep or near or c.get("virtual"):
                # keep virtual probes tied to focused anchors only
                if c.get("virtual") and aid not in keep and cid not in keep:
                    # keep if probe center near focus times
                    if not near:
                        board.candidates.pop(cid, None)
                continue
            board.candidates.pop(cid, None)

    digest["score_anchors"] = board.list_anchors()
    _write(out_dir / "event_bundle_sanitized.json", bundle)
    _write(out_dir / "event_digest.json", digest)
    _write(out_dir / "event_candidates.json", board.snapshot())

    if planner_mode == "fixed":
        fixed = _run_fixed_baseline(bundle=bundle, board=board, out_dir=out_dir, video=video)
        discovery = {
            "schema": "v2_event_guided_discovery_v2",
            "mode": "event_fixed",
            "input_source": input_source,
            "discovery_status": fixed["discovery_status"],
            "reason": fixed["reason"],
            "beats": {},
            "relations": [],
            "score_anchors": board.list_anchors(),
            "render_ready": False,
        }
        evidence = {
            "schema": "v2_event_guided_evidence_v2",
            "mode": "event_fixed",
            "evidence_records": fixed["evidence_records"],
            "verifications": [],
            "grade_counts": {},
            "render_ready": False,
        }
        rel_ver = review_relations([])
        agent_trace = {
            "schema": "v2_event_guided_trace_v2",
            "mode": "event_fixed",
            "elapsed_sec": round(time.time() - t0, 3),
            "steps": [],
            "frames_used": 0,
            "api_stats": fixed["api_stats"],
            "cost_disclaimer": COST_DISCLAIMER,
            "autonomous_search_trace": [],
            "render_ready": False,
        }
        _write(out_dir / "story_discovery.json", discovery)
        _write(out_dir / "story_evidence.json", evidence)
        _write(out_dir / "agent_trace.json", agent_trace)
        _write(out_dir / "relation_verification.json", rel_ver)
        _write(out_dir / "autonomous_search_trace.json", {"mode": "event_fixed", "steps": []})
        offline = _offline_pack(
            evidence_records=fixed["evidence_records"],
            gold_story_graph=gold_story_graph,
            gold_edl=gold_edl,
            relations=[],
            rel_ver=rel_ver,
            causal_path_offline=causal_path_offline,
        )
        _write(out_dir / "offline_eval.json", offline)
        _write(out_dir / "action_localization_eval.json", offline.get("action_localization_eval"))
        if export_review_clips:
            export_candidate_review_pack(
                video=video,
                records=fixed["evidence_records"],
                frames_dir=None,
                out_dir=out_dir / "review_pack",
            )
        return {
            "discovery": discovery,
            "evidence": evidence,
            "agent_trace": agent_trace,
            "offline_eval": offline,
            "relation_verification": rel_ver,
            "render_ready": False,
        }

    media = probe_video(video)
    frames_dir = out_dir / "frames_eg"
    store = FrameStore(media, out_dir=frames_dir, budget=FrameBudget(max_frames=frame_budget))
    vision = VisionProvider(api=api, force_mock=bool(api.force_mock))
    tools = V2PhaseC1Toolbox(
        duration=media.duration_sec,
        store=store,
        vision=vision,
        task_note=(
            "Cite frame_ids when claiming shot or ball-in-net. "
            "Celebration or scoreboard alone is not a localized goal action."
        ),
    )
    memory = EventGuidedMemory(
        duration=media.duration_sec,
        event_digest=digest,
        board=board,
        planner_mode=planner_mode,
    )
    agent = V2EventGuidedAgent(
        duration=media.duration_sec,
        tools=tools,
        api=api,
        planner_mode=planner_mode,
        use_llm_planner=use_llm_planner and planner_mode == "agent",
    )

    trace: List[Dict[str, Any]] = []
    stop_reason = "max_steps"
    final_answer: Dict[str, Any] = {}
    evidence_counter = 0

    for step in range(max_steps):
        decision = agent.decide(memory, step, max_steps)
        step_row: Dict[str, Any] = {
            "step": step,
            "decision": decision,
            "decision_attempts": agent.decision_attempts,
            "planner_mode_step": agent.planner_mode_log[-1] if agent.planner_mode_log else None,
        }

        if decision["type"] == "answer":
            stop_reason = str(decision.get("reason") or decision.get("answer"))
            final_answer = _apply_score_anchor_override(decision, board.list_anchors())
            # relation review
            evid_ids = {
                f"ev_{i}_{r.get('candidate_event_id')}"
                for i, r in enumerate(memory.evidence_records)
            }
            evid_ids |= {str(r.get("candidate_event_id")) for r in memory.evidence_records}
            verified = {
                c["candidate_event_id"]
                for c in board.localized()
                if (c.get("evidence_record") or {}).get("verification_status")
                == "verified_action"
            }
            rel_ver = review_relations(
                final_answer.get("relations") or [],
                evidence_ids=evid_ids,
                verified_event_ids=verified,
            )
            final_answer["relations"] = rel_ver["relations"]
            memory.discovery_status = str(final_answer.get("answer"))
            memory.discovery_reason = str(final_answer.get("reason") or stop_reason)
            memory.inferred_beats = final_answer.get("beats") or {}
            memory.inferred_relations = final_answer.get("relations") or []
            step_row["observation"] = {"terminal": True, "override": final_answer.get("override")}
            step_row["decision_final"] = final_answer
            step_row["relation_verification"] = {
                "n_accepted": rel_ver["n_accepted"],
                "n_rejected": rel_ver["n_rejected"],
                "n_downgraded": rel_ver["n_downgraded"],
            }
            trace.append(step_row)
            break

        tool = decision["tool"]
        args = decision.get("arguments") or {}
        obs_out: Dict[str, Any] = {"tool": tool}

        if tool == "list_candidates":
            obs_out["result"] = board.list_candidates(status=args.get("status"))
        elif tool == "list_anchors":
            obs_out["result"] = board.list_anchors()
        elif tool == "select_candidate":
            obs_out["result"] = board.select(str(args.get("candidate_event_id") or args.get("event_id")))
        elif tool == "reject_candidate":
            obs_out["result"] = board.reject(
                str(args.get("candidate_event_id") or args.get("event_id")),
                str(args.get("reason") or "rejected_by_planner"),
            )
        elif tool == "shift_search":
            obs_out["result"] = board.shift_search(
                str(args.get("candidate_event_id") or args.get("event_id")),
                float(args.get("delta_sec") or -30.0),
            )
        elif tool == "confirm_localization":
            eid = str(args.get("candidate_event_id") or args.get("event_id"))
            matching = [
                v
                for v in memory.verifications
                if v.get("candidate_event_id") == eid and isinstance(v.get("evidence"), dict)
            ]
            last = matching[-1] if matching else {}
            ev = last.get("evidence") or {}
            try:
                mi = float(args["media_in"]) if args.get("media_in") is not None else float(last["media_start_sec"])
                mo = float(args["media_out"]) if args.get("media_out") is not None else float(last["media_end_sec"])
            except (KeyError, TypeError, ValueError):
                obs_out["result"] = {
                    "ok": False,
                    "error": "confirm_missing_media_window",
                    "args": args,
                }
                mi = mo = None
            if mi is not None and (
                not ev.get("shooting_action_evidence") or not ev.get("goal_result_evidence")
            ):
                obs_out["result"] = {
                    "ok": False,
                    "error": "confirm_denied_missing_frame_bound_shot_or_net",
                    "evidence": {
                        "grade": ev.get("grade"),
                        "shooting_action_evidence": ev.get("shooting_action_evidence"),
                        "goal_result_evidence": ev.get("goal_result_evidence"),
                        "verification_status": ev.get("verification_status"),
                    },
                    "hint": "Call observe_window or shift_search next; do not repeat confirm_localization",
                }
                memory.log_autonomy(
                    {
                        "step": step,
                        "tool": "confirm_localization",
                        "denied": True,
                        "candidate_event_id": eid,
                    }
                )
            elif mi is not None:
                evidence_counter += 1
                rec = build_goal_candidate_record(
                    candidate_event_id=eid,
                    event_time_sec=(board.get(eid) or {}).get("event_time_sec"),
                    observation={
                        "media_start_sec": mi,
                        "media_end_sec": mo,
                        "frames": last.get("frames") or [],
                        "perception": last.get("perception") or {},
                    },
                    evidence=ev,
                    localized_media_in=mi,
                    localized_media_out=mo,
                )
                rec["evidence_id"] = f"ev_{evidence_counter}_{eid}"
                memory.add_evidence(rec)
                obs_out["result"] = board.confirm_localization(
                    eid, media_in=mi, media_out=mo, evidence_record=rec
                )
        elif tool == "observe_window":
            purpose = str(args.get("purpose") or "dense")
            c1 = PURPOSE_TO_C1.get(purpose, "dense_action_inspect")
            eid = str(args.get("candidate_event_id") or "unknown")
            c1_args = {
                "start": args.get("start"),
                "end": args.get("end"),
                "task_id": eid,
            }
            raw_obs = tools.execute(c1, c1_args)
            span = None
            if raw_obs.get("media_start_sec") is not None:
                span = float(raw_obs["media_end_sec"]) - float(raw_obs["media_start_sec"])
            evidence = grade_with_frame_evidence(observation=raw_obs, window_span_sec=span)
            row = {
                "candidate_event_id": eid,
                "tool": c1,
                "purpose": purpose,
                "media_start_sec": raw_obs.get("media_start_sec"),
                "media_end_sec": raw_obs.get("media_end_sec"),
                "perception": raw_obs.get("perception"),
                "frames": raw_obs.get("frames"),
                "evidence": evidence,
                "grade": evidence.get("grade"),
                "error": raw_obs.get("error"),
            }
            memory.add_verification(row)
            board.add_observation(
                eid,
                {
                    "purpose": purpose,
                    "window": [row["media_start_sec"], row["media_end_sec"]],
                    "grade": evidence.get("grade"),
                    "verification_status": evidence.get("verification_status"),
                },
                evidence,
            )
            # Auto-promote strong evidence to localized record (agent may also confirm)
            if evidence.get("grade") == "action_localized" and eid in board.candidates:
                evidence_counter += 1
                rec = build_goal_candidate_record(
                    candidate_event_id=eid,
                    event_time_sec=(board.get(eid) or {}).get("event_time_sec"),
                    observation=raw_obs,
                    evidence=evidence,
                )
                rec["evidence_id"] = f"ev_{evidence_counter}_{eid}"
                memory.add_evidence(rec)
                board.confirm_localization(
                    eid,
                    media_in=float(raw_obs["media_start_sec"]),
                    media_out=float(raw_obs["media_end_sec"]),
                    evidence_record=rec,
                )
            obs_out = {
                "candidate_event_id": eid,
                "grade": evidence.get("grade"),
                "verification_status": evidence.get("verification_status"),
                "shooting_action_evidence": evidence.get("shooting_action_evidence"),
                "goal_result_evidence": evidence.get("goal_result_evidence"),
                "live_or_replay": evidence.get("live_or_replay"),
                "supporting_frame_ids": evidence.get("supporting_frame_ids"),
                "media_start_sec": row["media_start_sec"],
                "media_end_sec": row["media_end_sec"],
                "error": row.get("error"),
            }
        else:
            obs_out = {"error": f"unhandled_tool:{tool}"}

        memory.add_search({"tool": tool, "arguments": args, "ok": "error" not in obs_out})
        step_row["observation"] = obs_out
        trace.append(step_row)

        if store.budget.remaining <= 0:
            stop_reason = "frame_budget_exhausted"
            final_answer = _apply_score_anchor_override(
                agent.finish_from_memory(memory, reason=stop_reason), board.list_anchors()
            )
            evid_ids = {str(r.get("candidate_event_id")) for r in memory.evidence_records}
            rel_ver = review_relations(
                final_answer.get("relations") or [],
                evidence_ids=evid_ids,
                verified_event_ids=evid_ids,
            )
            final_answer["relations"] = rel_ver["relations"]
            memory.discovery_status = str(final_answer.get("answer"))
            memory.discovery_reason = str(final_answer.get("reason") or stop_reason)
            memory.inferred_beats = final_answer.get("beats") or {}
            memory.inferred_relations = final_answer.get("relations") or []
            break

    if not memory.discovery_status:
        stop_reason = "max_steps_synthesize" if stop_reason == "max_steps" else stop_reason
        final_answer = _apply_score_anchor_override(
            agent.finish_from_memory(memory, reason=stop_reason), board.list_anchors()
        )
        evid_ids = {str(r.get("candidate_event_id")) for r in memory.evidence_records}
        rel_ver = review_relations(
            final_answer.get("relations") or [],
            evidence_ids=evid_ids,
            verified_event_ids=evid_ids,
        )
        final_answer["relations"] = rel_ver["relations"]
        memory.discovery_status = str(final_answer.get("answer"))
        memory.discovery_reason = str(final_answer.get("reason") or stop_reason)
        memory.inferred_beats = final_answer.get("beats") or {}
        memory.inferred_relations = final_answer.get("relations") or []
    else:
        # rel_ver may already exist from answer branch
        rel_ver = review_relations(
            memory.inferred_relations,
            evidence_ids={str(r.get("candidate_event_id")) for r in memory.evidence_records},
            verified_event_ids={
                c["candidate_event_id"]
                for c in board.localized()
                if (c.get("evidence_record") or {}).get("grade") == "action_localized"
            },
        )

    api_stats = api.stats.summary()
    discovery = {
        "schema": "v2_event_guided_discovery_v2",
        "mode": f"event_{planner_mode}",
        "input_source": input_source,
        "discovery_status": memory.discovery_status,
        "reason": memory.discovery_reason,
        "beats": memory.inferred_beats,
        "relations": memory.inferred_relations,
        "score_anchors": board.list_anchors(),
        "n_localized": len(board.localized()),
        "forbidden_inputs_not_used": bundle.get("forbidden_as_model_input"),
        "render_ready": False,
    }
    grade_counts: Dict[str, int] = {}
    for v in memory.verifications:
        g = v.get("grade")
        if g:
            grade_counts[g] = grade_counts.get(g, 0) + 1
    evidence = {
        "schema": "v2_event_guided_evidence_v2",
        "mode": f"event_{planner_mode}",
        "input_source": input_source,
        "verifications": memory.verifications,
        "evidence_records": memory.evidence_records,
        "grade_counts": grade_counts,
        "render_ready": False,
    }
    auto_trace = {
        "schema": "v2_autonomous_search_trace_v1",
        "mode": planner_mode,
        "planner_mode_log": agent.planner_mode_log,
        "autonomous_decisions": memory.autonomous_decisions,
        "n_llm_mid_loop": sum(1 for x in agent.planner_mode_log if x == "llm_mid"),
        "n_rule_baseline": sum(1 for x in agent.planner_mode_log if x == "rule_baseline"),
        "steps": [
            {
                "step": s["step"],
                "planner_mode_step": s.get("planner_mode_step"),
                "tool": (s.get("decision") or {}).get("tool"),
                "type": (s.get("decision") or {}).get("type"),
                "observation_summary": {
                    k: (s.get("observation") or {}).get(k)
                    for k in (
                        "candidate_event_id",
                        "grade",
                        "verification_status",
                        "media_start_sec",
                        "media_end_sec",
                        "tool",
                    )
                    if (s.get("observation") or {}).get(k) is not None
                },
            }
            for s in trace
        ],
        "render_ready": False,
    }
    agent_trace = {
        "schema": "v2_event_guided_trace_v2",
        "mode": planner_mode,
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

    offline = _offline_pack(
        evidence_records=memory.evidence_records or [
            {
                "candidate_event_id": v.get("candidate_event_id"),
                "localized_media_in": v.get("media_start_sec"),
                "localized_media_out": v.get("media_end_sec"),
                "grade": v.get("grade"),
                "verification_status": (v.get("evidence") or {}).get("verification_status"),
            }
            for v in memory.verifications
        ],
        gold_story_graph=gold_story_graph,
        gold_edl=gold_edl,
        relations=memory.inferred_relations,
        rel_ver=rel_ver,
        causal_path_offline=causal_path_offline,
        verifications=memory.verifications,
    )

    _write(out_dir / "story_discovery.json", discovery)
    _write(out_dir / "story_evidence.json", evidence)
    _write(out_dir / "agent_trace.json", agent_trace)
    _write(out_dir / "memory_snapshot.json", memory.snapshot())
    _write(out_dir / "autonomous_search_trace.json", auto_trace)
    _write(out_dir / "relation_verification.json", rel_ver)
    _write(out_dir / "offline_eval.json", offline)
    _write(out_dir / "action_localization_eval.json", offline.get("action_localization_eval"))

    if export_review_clips and memory.evidence_records:
        export_candidate_review_pack(
            video=video,
            records=memory.evidence_records,
            frames_dir=frames_dir,
            out_dir=out_dir / "review_pack",
        )

    return {
        "discovery": discovery,
        "evidence": evidence,
        "agent_trace": agent_trace,
        "offline_eval": offline,
        "relation_verification": rel_ver,
        "autonomous_search_trace": auto_trace,
        "event_bundle_meta": {
            "n_raw": bundle.get("n_raw"),
            "n_kept": bundle.get("n_kept"),
            "input_source": input_source,
            "planner_mode": planner_mode,
        },
        "render_ready": False,
    }


def _offline_pack(
    *,
    evidence_records: List[Dict[str, Any]],
    gold_story_graph: Optional[Path],
    gold_edl: Optional[Path],
    relations: List[Dict[str, Any]],
    rel_ver: Dict[str, Any],
    causal_path_offline: Optional[Path],
    verifications: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    preds = []
    for r in evidence_records:
        s, e = r.get("localized_media_in"), r.get("localized_media_out")
        if s is None or e is None:
            continue
        # Fixed windows are proximity baselines only — not verified action localization.
        if r.get("verification_status") == "fixed_window_unverified" or r.get("mode") == "event_fixed":
            continue
        preds.append(
            {
                "task_id": r.get("candidate_event_id"),
                "window": (float(s), float(e)),
                "grade_keyword": r.get("grade"),
                "live_or_replay_keyword": r.get("live_or_replay"),
                "observed_actions": r.get("observed_action_sequence") or [],
                "notes": "",
                "has_frame_cite": bool(r.get("supporting_frame_ids")),
            }
        )
    # Separate proximity metric for Event-Fixed
    fixed_prox = []
    for r in evidence_records:
        if not (
            r.get("verification_status") == "fixed_window_unverified" or r.get("mode") == "event_fixed"
        ):
            continue
        s, e = r.get("localized_media_in"), r.get("localized_media_out")
        if s is None or e is None:
            continue
        fixed_prox.append(
            {
                "task_id": r.get("candidate_event_id"),
                "window": (float(s), float(e)),
                "grade_keyword": "unresolved",
                "live_or_replay_keyword": "unknown",
                "observed_actions": [],
                "notes": "fixed_window_unverified",
                "has_frame_cite": False,
            }
        )
    # Also score observed windows that were never confirm_localization'd —
    # early lag probes often hold the true action before a wrong late confirm.
    for v in verifications or []:
        s, e = v.get("media_start_sec"), v.get("media_end_sec")
        if s is None or e is None:
            continue
        ev = v.get("evidence") if isinstance(v.get("evidence"), dict) else {}
        grade = ev.get("grade") or v.get("grade")
        if grade not in ("action_localized", "goal_candidate", "action_corroborated"):
            continue
        if not (
            ev.get("shooting_action_evidence")
            or ev.get("goal_result_evidence")
            or grade == "action_localized"
        ):
            continue
        preds.append(
            {
                "task_id": f"obs:{v.get('candidate_event_id')}",
                "window": (float(s), float(e)),
                "grade_keyword": grade,
                "live_or_replay_keyword": ev.get("live_or_replay"),
                "observed_actions": ev.get("observed_action_sequence") or [],
                "notes": "",
                "has_frame_cite": bool(ev.get("supporting_frame_ids")),
            }
        )
    action_loc = None
    if gold_story_graph and Path(gold_story_graph).is_file():
        refs = load_v1_reference_nodes(Path(gold_story_graph), Path(gold_edl) if gold_edl else None)
        action_loc = {
            "schema": "v2_r2_action_localization_eval_bundle_v1",
            "strict_action_gold": evaluate_localization_against_refs(
                preds=preds, refs=refs["strict_action_gold"]
            ),
            "weak_reference_goals": evaluate_localization_against_refs(
                preds=preds, refs=refs["weak_action_references"]
            ),
            "prelude_before_goal": evaluate_localization_against_refs(
                preds=preds, refs=refs["prelude_references"]
            ),
            "fixed_event_time_proximity_only": (
                evaluate_localization_against_refs(
                    preds=fixed_prox, refs=refs["weak_action_references"]
                )
                if fixed_prox
                else None
            ),
            "policy": {
                "do_not_use_pm90s_as_action_recall": True,
                "strict_gold_excludes_weak_and_prelude": True,
                "fixed_windows_are_not_verified_actions": True,
            },
        }
    # legacy proximity metric kept but not primary
    legacy = None
    if gold_story_graph and Path(gold_story_graph).is_file():
        gold = load_action_gold_from_story_graph(Path(gold_story_graph))
        legacy = eval_action_windows(
            verified=[
                {
                    "task_id": r.get("candidate_event_id"),
                    "media_start_sec": r.get("localized_media_in"),
                    "media_end_sec": r.get("localized_media_out"),
                    "grade": {"grade": r.get("grade")},
                }
                for r in evidence_records
            ],
            gold=[g for g in gold if "approach" not in str(g.get("role"))],
            center_pad_sec=45.0,
        )
    return {
        "schema": "v2_event_guided_offline_eval_v2",
        "action_localization_eval": action_loc,
        "legacy_loose45_eval": legacy,
        "relation_verification": rel_ver,
        "causal_offline_note": "causal.json not loaded into agent; optional path unused in-loop",
        "causal_path_offline": str(causal_path_offline) if causal_path_offline else None,
        "render_ready": False,
    }
