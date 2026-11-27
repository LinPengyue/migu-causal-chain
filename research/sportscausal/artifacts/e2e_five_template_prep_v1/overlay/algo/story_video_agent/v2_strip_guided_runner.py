"""Strip-Guided runner: MP4 + events.json + predicted strips → story structure."""

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
from story_video_agent.v2_event_guided_clip_export import export_candidate_review_pack
from story_video_agent.v2_event_guided_evidence import grade_with_frame_evidence
from story_video_agent.v2_event_guided_relation import review_relations
from story_video_agent.v2_phase_c1_toolbox import V2PhaseC1Toolbox
from story_video_agent.v2_strip_adapter import (
    adapt_strip_bundle,
    offline_key_goal_coverage,
    planner_strip_digest,
)
from story_video_agent.v2_strip_guided_agent import V2StripGuidedAgent
from story_video_agent.v2_strip_guided_memory import StripGuidedMemory

PURPOSE_TO_C1 = {
    "dense": "dense_action_inspect",
    "coarse": "coarse_search",
    "live_replay": "verify_live_replay",
    "scoreboard": "read_scoreboard_window",
}


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _apply_score_override(answer: Dict[str, Any], event_digest: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(answer)
    pairs = []
    for a in event_digest.get("score_anchors") or []:
        if a.get("kind") == "initial_score" and a.get("score_pair"):
            pairs.append(tuple(a["score_pair"]))
        if a.get("kind") == "score_change" and a.get("score_after"):
            pairs.append(tuple(a["score_after"]))
    if len(pairs) < 2:
        return out
    first, later = pairs[0], pairs[-1]
    flipped = (first[0] < first[1] and later[0] > later[1]) or (
        first[1] < first[0] and later[1] > later[0]
    )
    ans = str(out.get("answer") or "")
    if flipped and ans in {"no_comeback", "unresolved", "partial_story"}:
        out["answer"] = "story_candidate"
        out["override"] = {"from": ans, "to": "story_candidate", "rule": "score_anchor_deficit_to_lead"}
        out["reason"] = f"override:{ans}->story_candidate; " + str(out.get("reason") or "")
    return out


def run_strip_guided(
    *,
    video: Path,
    events_path: Path,
    strip_path: Path,
    out_dir: Path,
    api: ApiProvider,
    input_source: str = "human_corrected",
    max_steps: int = 14,
    frame_budget: int = 48,
    use_llm_planner: bool = True,
    export_review_clips: bool = True,
    weak_goal_centers_offline: Optional[List[float]] = None,
) -> Dict[str, Any]:
    t0 = time.time()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Events (whitelist only) + strips (predicted only)
    event_bundle = load_events_json(Path(events_path), input_source=input_source)
    event_digest = planner_event_digest(event_bundle)
    strip_bundle = adapt_strip_bundle(
        Path(strip_path), events_path=Path(events_path), match_id=event_bundle.get("match_id")
    )
    strip_digest = planner_strip_digest(strip_bundle)
    _write(out_dir / "predicted_strip_chains.json", strip_bundle)
    _write(out_dir / "strip_digest.json", strip_digest)
    _write(out_dir / "event_digest.json", event_digest)

    coverage = None
    if weak_goal_centers_offline:
        coverage = offline_key_goal_coverage(
            strip_bundle, weak_goal_centers_sec=weak_goal_centers_offline
        )
        _write(out_dir / "offline_strip_goal_coverage.json", coverage)

    media = probe_video(video)
    frames_dir = out_dir / "frames_sg"
    store = FrameStore(media, out_dir=frames_dir, budget=FrameBudget(max_frames=frame_budget))
    vision = VisionProvider(api=api, force_mock=bool(api.force_mock))
    tools = V2PhaseC1Toolbox(
        duration=media.duration_sec,
        store=store,
        vision=vision,
        task_note=(
            "Strip-guided verify: cite frame_ids for shot/net. "
            "Predicted strip labels are hypotheses. Separate live vs replay."
        ),
    )
    memory = StripGuidedMemory(
        duration=media.duration_sec, strip_digest=strip_digest, event_digest=event_digest
    )
    # Keep full adapted chain metadata on states
    for c in strip_bundle.get("chains") or []:
        sid = c["strip_chain_id"]
        if sid in memory.chain_states:
            memory.chain_states[sid].update(c)

    agent = V2StripGuidedAgent(
        duration=media.duration_sec,
        tools=tools,
        api=api,
        use_llm_planner=use_llm_planner,
    )

    trace: List[Dict[str, Any]] = []
    stop_reason = "max_steps"
    final: Dict[str, Any] = {}
    evid_counter = 0

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
            final = _apply_score_override(decision, event_digest)
            evid_ids = {
                str(v.get("evidence_id") or v.get("linked_strip_chain_id"))
                for v in memory.verifications
            }
            verified_chains = {
                sid for sid, c in memory.chain_states.items() if c.get("status") == "verified"
            }
            # Map strip relations into event-guided reviewer shape
            rel_in = []
            for r in final.get("relations") or []:
                rel_in.append(
                    {
                        "from_event_id": r.get("source_chain_id"),
                        "to_event_id": r.get("target_chain_id"),
                        "relation_type": r.get("relation_type"),
                        "explanation": r.get("explanation"),
                        "supporting_evidence_ids": r.get("supporting_evidence_ids") or [],
                        "verification_status": r.get("verification_status"),
                    }
                )
            rel_ver = review_relations(
                rel_in, evidence_ids=evid_ids, verified_event_ids=verified_chains
            )
            # remap keys back
            final_rels = []
            for r in rel_ver.get("relations") or []:
                final_rels.append(
                    {
                        "source_chain_id": r.get("from_event_id"),
                        "target_chain_id": r.get("to_event_id"),
                        "relation_type": r.get("relation_type"),
                        "explanation": r.get("explanation"),
                        "supporting_event_ids": [],
                        "supporting_evidence_ids": r.get("supporting_evidence_ids") or [],
                        "verification_status": r.get("verification_status"),
                        "review_reasons": r.get("review_reasons"),
                    }
                )
            memory.discovery_status = str(final.get("answer"))
            memory.discovery_reason = str(final.get("reason") or stop_reason)
            memory.story_candidates = final.get("story_candidates") or []
            memory.beats = final.get("beats") or {}
            memory.relations = final_rels
            step_row["observation"] = {"terminal": True, "override": final.get("override")}
            step_row["relation_verification"] = {
                "n_accepted": rel_ver.get("n_accepted"),
                "n_downgraded": rel_ver.get("n_downgraded"),
                "n_rejected": rel_ver.get("n_rejected"),
            }
            trace.append(step_row)
            break

        tool = decision["tool"]
        args = decision.get("arguments") or {}
        obs: Dict[str, Any] = {"tool": tool}

        if tool == "list_strips":
            obs["result"] = memory.facts_for_planner(remaining=99)["open_strips"]
        elif tool == "select_strip":
            sid = str(args.get("strip_chain_id") or "")
            if sid in memory.chain_states:
                memory.chain_states[sid]["status"] = "selected"
                obs["result"] = {"ok": True, "strip_chain_id": sid}
            else:
                obs["result"] = {"ok": False, "error": "unknown_strip"}
        elif tool == "reject_strip":
            sid = str(args.get("strip_chain_id") or "")
            if sid in memory.chain_states:
                memory.chain_states[sid]["status"] = "rejected"
                memory.chain_states[sid]["reject_reason"] = str(args.get("reason") or "rejected")
                obs["result"] = {"ok": True}
            else:
                obs["result"] = {"ok": False, "error": "unknown_strip"}
        elif tool == "observe_strip":
            sid = str(args.get("strip_chain_id") or "")
            purpose = str(args.get("purpose") or "dense")
            c1 = PURPOSE_TO_C1.get(purpose, "dense_action_inspect")
            # default window from strip if missing
            st = memory.chain_states.get(sid) or {}
            start = args.get("start")
            end = args.get("end")
            if start is None or end is None:
                mid = 0.5 * (float(st.get("t0_sec") or 0) + float(st.get("t1_sec") or 1))
                start = max(0.0, mid - 5.0)
                end = min(media.duration_sec, start + 10.0)
            raw_obs = tools.execute(
                c1, {"start": start, "end": end, "task_id": sid}
            )
            span = None
            if raw_obs.get("media_start_sec") is not None:
                span = float(raw_obs["media_end_sec"]) - float(raw_obs["media_start_sec"])
            evidence = grade_with_frame_evidence(observation=raw_obs, window_span_sec=span)
            evid_counter += 1
            eid = f"sev_{evid_counter}_{sid}"
            row = {
                "evidence_id": eid,
                "linked_strip_chain_id": sid,
                "linked_event_ids": st.get("source_event_ids") or [],
                "predicted_window": {"t0_sec": st.get("t0_sec"), "t1_sec": st.get("t1_sec")},
                "observed_media_in": raw_obs.get("media_start_sec"),
                "observed_media_out": raw_obs.get("media_end_sec"),
                "supporting_frame_ids": evidence.get("supporting_frame_ids"),
                "observed_actions": evidence.get("observed_action_sequence"),
                "is_live": evidence.get("live_or_replay") in ("live", "mixed"),
                "is_replay": evidence.get("live_or_replay") == "replay",
                "live_or_replay": evidence.get("live_or_replay"),
                "action_completeness": (
                    "shot_and_result"
                    if evidence.get("shooting_action_evidence") and evidence.get("goal_result_evidence")
                    else "partial"
                    if evidence.get("shooting_action_evidence") or evidence.get("goal_result_evidence")
                    else "insufficient"
                ),
                "visual_consistency": evidence.get("grade"),
                "verification_status": evidence.get("verification_status"),
                "uncertainty": evidence.get("uncertainty"),
                "grade": evidence.get("grade"),
                "evidence": evidence,
                "perception": raw_obs.get("perception"),
                "frames": raw_obs.get("frames"),
                "error": raw_obs.get("error"),
                "render_ready": False,
            }
            memory.verifications.append(row)
            if sid in memory.chain_states:
                memory.chain_states[sid].setdefault("verifications", []).append(row)
                memory.chain_states[sid]["status"] = "observing"
                if evidence.get("grade") == "action_localized":
                    memory.chain_states[sid]["status"] = "verified"
                    memory.chain_states[sid]["refined_media_in"] = row["observed_media_in"]
                    memory.chain_states[sid]["refined_media_out"] = row["observed_media_out"]
                    memory.chain_states[sid]["evidence"] = evidence
                    memory.chain_states[sid]["verification_status"] = "verified_action"
                    memory.localized_clips.append(
                        {
                            "clip_id": f"loc_{sid}",
                            "linked_strip_chain_id": sid,
                            "linked_event_ids": st.get("source_event_ids") or [],
                            "media_in": row["observed_media_in"],
                            "media_out": row["observed_media_out"],
                            "predicted_t0_sec": st.get("t0_sec"),
                            "predicted_t1_sec": st.get("t1_sec"),
                            "supporting_frame_ids": row["supporting_frame_ids"],
                            "action_completeness": row["action_completeness"],
                            "is_live": row["is_live"],
                            "is_replay": row["is_replay"],
                            "verification_status": "verified_action",
                            "usable_for_edit_candidate": True,
                            "render_ready": False,
                        }
                    )
            obs = {
                "linked_strip_chain_id": sid,
                "grade": evidence.get("grade"),
                "verification_status": evidence.get("verification_status"),
                "observed_media_in": row["observed_media_in"],
                "observed_media_out": row["observed_media_out"],
                "shooting_action_evidence": evidence.get("shooting_action_evidence"),
                "goal_result_evidence": evidence.get("goal_result_evidence"),
                "error": row.get("error"),
            }
        else:
            obs = {"error": f"unhandled:{tool}"}

        step_row["observation"] = obs
        trace.append(step_row)
        if store.budget.remaining <= 0:
            stop_reason = "frame_budget_exhausted"
            final = _apply_score_override(
                agent.finish_from_memory(memory, reason=stop_reason), event_digest
            )
            memory.discovery_status = str(final.get("answer"))
            memory.discovery_reason = stop_reason
            memory.story_candidates = final.get("story_candidates") or []
            memory.beats = final.get("beats") or {}
            memory.relations = final.get("relations") or []
            break

    if not memory.discovery_status:
        final = _apply_score_override(
            agent.finish_from_memory(memory, reason=stop_reason), event_digest
        )
        memory.discovery_status = str(final.get("answer"))
        memory.discovery_reason = str(final.get("reason") or stop_reason)
        memory.story_candidates = final.get("story_candidates") or []
        memory.beats = final.get("beats") or {}
        # still run relation review
        rel_in = [
            {
                "from_event_id": r.get("source_chain_id"),
                "to_event_id": r.get("target_chain_id"),
                "relation_type": r.get("relation_type"),
                "explanation": r.get("explanation"),
                "supporting_evidence_ids": r.get("supporting_evidence_ids") or [],
            }
            for r in (final.get("relations") or [])
        ]
        rel_ver = review_relations(
            rel_in,
            evidence_ids={str(v.get("evidence_id")) for v in memory.verifications},
            verified_event_ids={
                sid for sid, c in memory.chain_states.items() if c.get("status") == "verified"
            },
        )
        memory.relations = [
            {
                "source_chain_id": r.get("from_event_id"),
                "target_chain_id": r.get("to_event_id"),
                "relation_type": r.get("relation_type"),
                "explanation": r.get("explanation"),
                "supporting_event_ids": [],
                "supporting_evidence_ids": r.get("supporting_evidence_ids") or [],
                "verification_status": r.get("verification_status"),
                "review_reasons": r.get("review_reasons"),
            }
            for r in (rel_ver.get("relations") or [])
        ]
    else:
        rel_ver = {
            "n_accepted": len(memory.relations),
            "n_downgraded": 0,
            "n_rejected": 0,
            "relations": memory.relations,
        }

    api_stats = api.stats.summary()
    story_candidates = {
        "schema": "v2_strip_story_candidates_v1",
        "discovery_status": memory.discovery_status,
        "candidates": memory.story_candidates,
        "n_predicted_strips": strip_bundle.get("n_adapted"),
        "n_verified_strips": sum(
            1 for c in memory.chain_states.values() if c.get("status") == "verified"
        ),
        "render_ready": False,
    }
    story_beats = {
        "schema": "v2_strip_story_beats_v1",
        "beats": memory.beats,
        "render_ready": False,
    }
    story_relations = {
        "schema": "v2_strip_story_relations_v1",
        "relations": memory.relations,
        "review": {
            "n_accepted": rel_ver.get("n_accepted"),
            "n_downgraded": rel_ver.get("n_downgraded"),
            "n_rejected": rel_ver.get("n_rejected"),
        },
        "render_ready": False,
    }
    localized = {
        "schema": "v2_strip_localized_clips_v1",
        "clips": memory.localized_clips,
        "n_verifications": len(memory.verifications),
        "render_ready": False,
    }
    agent_trace = {
        "schema": "v2_strip_story_agent_trace_v1",
        "mode": "strip_guided",
        "elapsed_sec": round(time.time() - t0, 3),
        "stop_reason": stop_reason,
        "max_steps": max_steps,
        "steps": trace,
        "planner_mode_log": agent.planner_mode_log,
        "frames_used": store.budget.used,
        "frame_budget": frame_budget,
        "api_stats": api_stats,
        "cost_disclaimer": COST_DISCLAIMER,
        "offline_strip_goal_coverage": coverage,
        "render_ready": False,
    }

    _write(out_dir / "story_candidates.json", story_candidates)
    _write(out_dir / "story_beats.json", story_beats)
    _write(out_dir / "story_relations.json", story_relations)
    _write(out_dir / "localized_story_clips.json", localized)
    _write(out_dir / "story_agent_trace.json", agent_trace)
    _write(out_dir / "memory_snapshot.json", memory.snapshot())
    _write(out_dir / "relation_verification.json", rel_ver)

    if export_review_clips and memory.localized_clips:
        export_candidate_review_pack(
            video=video,
            records=[
                {
                    "candidate_event_id": c["linked_strip_chain_id"],
                    "localized_media_in": c["media_in"],
                    "localized_media_out": c["media_out"],
                    "supporting_frame_ids": c.get("supporting_frame_ids") or [],
                    "verification_status": c.get("verification_status"),
                    "grade": "action_localized",
                }
                for c in memory.localized_clips
            ],
            frames_dir=frames_dir,
            out_dir=out_dir / "review_pack",
        )

    return {
        "story_candidates": story_candidates,
        "story_beats": story_beats,
        "story_relations": story_relations,
        "localized_story_clips": localized,
        "story_agent_trace": agent_trace,
        "strip_bundle_meta": {
            "n_adapted": strip_bundle.get("n_adapted"),
            "category_counts": strip_bundle.get("category_counts"),
            "prediction_source": strip_bundle.get("prediction_source"),
        },
        "offline_coverage": coverage,
        "render_ready": False,
    }
