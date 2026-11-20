"""Strip-Guided Round 2: missing-goal recovery → enhanced events → strip A/B → story rebuild."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from story_video_agent.api_provider import COST_DISCLAIMER, ApiProvider
from story_video_agent.frames import FrameBudget, FrameStore
from story_video_agent.media import probe_video
from story_video_agent.vision_provider import VisionProvider
from story_video_agent.v2_api_preflight import (
    PreflightError,
    is_fatal_api_failure,
    require_preflight,
    run_preflight,
)
from story_video_agent.v2_enhanced_events import (
    make_inferred_goal_event,
    merge_enhanced_events_payload,
    should_emit_inferred_goal,
    write_enhanced_bundle,
)
from story_video_agent.v2_event_adapter import load_events_json, planner_event_digest
from story_video_agent.v2_event_guided_evidence import (
    grade_with_frame_evidence,
    merge_action_evidence_windows,
)
from story_video_agent.v2_event_guided_relation import review_relations
from story_video_agent.v2_goal_recovery_agent import V2GoalRecoveryAgent
from story_video_agent.v2_missing_goal_detector import detect_missing_goals
from story_video_agent.v2_phase_c1_toolbox import V2PhaseC1Toolbox
from story_video_agent.v2_strip_adapter import adapt_strip_bundle
from story_video_agent.v2_strip_reinfer import (
    analyze_inferred_in_strip_b,
    compare_strip_ab,
    events_to_timeline,
    load_or_run_baseline_A,
    run_strip_predict,
)

PURPOSE_MAP = {
    "coarse": "coarse_search",
    "dense": "dense_action_inspect",
    "live_replay": "verify_live_replay",
    "scoreboard": "read_scoreboard_window",
    "refine": "refine_window",
}


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _build_story_from_recovery(
    *,
    event_digest: Dict[str, Any],
    detector: Dict[str, Any],
    inferred: List[Dict[str, Any]],
    strip_b_bundle: Dict[str, Any],
    verifications: List[Dict[str, Any]],
    localized: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Assemble beats/relations with provenance tags — no auto-causal from score order."""
    anchors = event_digest.get("score_anchors") or []
    chains = strip_b_bundle.get("chains") or []
    verified_ids = {str(v.get("linked_candidate_id")) for v in verifications if v.get("grade") == "action_localized"}
    inferred_ids = [e["event_id"] for e in inferred if e.get("verification_status") == "verified_action"]

    # Priority strips: outcome/goal endpoints + near inferred times
    priority = []
    for c in chains:
        if c.get("predicted_category") == "outcome" or c.get("last_event") == "goal":
            priority.append(c)
    if not priority:
        priority = sorted(chains, key=lambda c: float(c.get("t0_sec") or 0))[:5]

    def _beat(name: str, strip: Optional[Dict[str, Any]], note: str) -> Dict[str, Any]:
        if not strip:
            return {
                "strip_chain_ids": [],
                "event_ids": [],
                "media_in": None,
                "media_out": None,
                "note": note,
                "provenance": "unresolved",
            }
        return {
            "strip_chain_ids": [strip.get("strip_chain_id") or strip.get("clip_id")],
            "event_ids": list(strip.get("source_event_ids") or [])[:8],
            "media_in": strip.get("t0_sec"),
            "media_out": strip.get("t1_sec"),
            "note": note,
            "provenance": "strip_predicted+score_path",
        }

    beats = {
        "setup": _beat("setup", priority[0] if priority else None, "early context / deficit"),
        "buildup": _beat("buildup", priority[1] if len(priority) > 1 else None, "buildup"),
        "turning": _beat("turning", priority[2] if len(priority) > 2 else None, "turning"),
        "climax": _beat("climax", priority[-2] if len(priority) > 3 else (priority[-1] if priority else None), "climax"),
        "resolution": _beat("resolution", priority[-1] if priority else None, "resolution"),
    }
    # Attach verified inferred goals into climax/turning notes when present
    if inferred_ids:
        beats["climax"]["event_ids"] = list(dict.fromkeys((beats["climax"].get("event_ids") or []) + inferred_ids[-2:]))
        beats["climax"]["provenance"] = "video_verified_inferred_goal+strip"

    relations = []
    # Temporal along priority strips
    for i in range(len(priority) - 1):
        a, b = priority[i], priority[i + 1]
        relations.append(
            {
                "source_chain_id": a.get("strip_chain_id") or a.get("clip_id"),
                "target_chain_id": b.get("strip_chain_id") or b.get("clip_id"),
                "relation_type": "temporal",
                "explanation": "Ordered by predicted strip time",
                "supporting_event_ids": [],
                "supporting_evidence_ids": [],
                "verification_status": "rule_temporal",
                "provenance": "rule",
            }
        )
    # Narrative only if score path shows deficit→lead AND we have ≥1 verified recovery or outcome strip
    score_pairs = []
    for a in anchors:
        if a.get("kind") == "initial_score" and a.get("score_pair"):
            score_pairs.append(tuple(a["score_pair"]))
        if a.get("kind") == "score_change" and a.get("score_after"):
            score_pairs.append(tuple(a["score_after"]))
    flipped = False
    if len(score_pairs) >= 2:
        first, later = score_pairs[0], score_pairs[-1]
        flipped = (first[0] < first[1] and later[0] > later[1]) or (
            first[1] < first[0] and later[1] > later[0]
        )
    if flipped and len(priority) >= 2:
        relations.append(
            {
                "source_chain_id": priority[0].get("strip_chain_id") or priority[0].get("clip_id"),
                "target_chain_id": priority[-1].get("strip_chain_id") or priority[-1].get("clip_id"),
                "relation_type": "narrative",
                "explanation": "Score path deficit→lead; narrative link (NOT direct causal)",
                "supporting_event_ids": inferred_ids,
                "supporting_evidence_ids": [v.get("evidence_id") for v in verifications if v.get("grade") == "action_localized"],
                "verification_status": "score_path_narrative",
                "provenance": "rule_score_path" + ("+video" if verified_ids else ""),
            }
        )
    # Do NOT emit causal from score order alone
    evid_ids = {str(v.get("evidence_id")) for v in verifications if v.get("evidence_id")}
    rel_in = [
        {
            "from_event_id": r["source_chain_id"],
            "to_event_id": r["target_chain_id"],
            "relation_type": r["relation_type"],
            "explanation": r["explanation"],
            "supporting_evidence_ids": r.get("supporting_evidence_ids") or [],
            "verification_status": r.get("verification_status"),
        }
        for r in relations
    ]
    reviewed = review_relations(
        rel_in,
        evidence_ids=evid_ids,
        verified_event_ids=set(inferred_ids),
    )
    final_rels = []
    for r, src in zip(reviewed.get("relations") or relations, relations):
        if isinstance(r, dict) and "from_event_id" in r:
            final_rels.append(
                {
                    "source_chain_id": r.get("from_event_id"),
                    "target_chain_id": r.get("to_event_id"),
                    "relation_type": r.get("relation_type"),
                    "explanation": r.get("explanation"),
                    "supporting_event_ids": src.get("supporting_event_ids") or [],
                    "supporting_evidence_ids": r.get("supporting_evidence_ids") or [],
                    "verification_status": r.get("verification_status"),
                    "provenance": src.get("provenance"),
                    "review_reasons": r.get("review_reasons"),
                }
            )
        else:
            final_rels.append(src)

    discovery = "story_candidate" if flipped else ("partial_story" if score_pairs else "unresolved")
    return {
        "story_candidates": {
            "schema": "v2_strip_r2_story_candidates_v1",
            "discovery_status": discovery,
            "candidates": [
                {
                    "story_id": "T01_score_path",
                    "score_path": score_pairs,
                    "n_missing_goal_candidates": detector.get("n_missing"),
                    "n_inferred_verified_goals": len(inferred_ids),
                    "n_verified_video": len(verified_ids),
                }
            ],
            "render_ready": False,
        },
        "story_beats": {"schema": "v2_strip_r2_story_beats_v1", "beats": beats, "render_ready": False},
        "story_relations": {
            "schema": "v2_strip_r2_story_relations_v1",
            "relations": final_rels,
            "review": {
                "n_accepted": reviewed.get("n_accepted"),
                "n_downgraded": reviewed.get("n_downgraded"),
                "n_rejected": reviewed.get("n_rejected"),
            },
            "provenance_note": "temporal=rule; narrative=score_path±video; causal never from score order alone",
            "render_ready": False,
        },
        "localized_story_clips": {
            "schema": "v2_strip_r2_localized_clips_v1",
            "clips": localized,
            "render_ready": False,
        },
    }


def run_goal_recovery(
    *,
    video: Path,
    events_path: Path,
    out_dir: Path,
    api: ApiProvider,
    algo_root: Path,
    strip_a_path: Optional[Path] = None,
    input_source: str = "human_corrected",
    max_steps: int = 16,
    frame_budget: int = 56,
    use_llm_planner: bool = True,
    skip_video: bool = False,
    candidate_ids: Optional[List[str]] = None,
    require_preflight_check: bool = True,
    preflight_image: Optional[Path] = None,
) -> Dict[str, Any]:
    t0 = time.time()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ab_dir = out_dir / "strip_ab"
    enh_dir = out_dir / "enhanced"
    frames_dir = out_dir / "frames_r2"

    preflight_report = None
    if require_preflight_check and not skip_video and not api.force_mock:
        # Vision-only roles if planner is rule-only
        roles = ("vision",) if not use_llm_planner else ("planner", "vision")
        preflight_report = run_preflight(
            configs=api.configs,
            image_path=preflight_image,
            require_roles=roles,
        )
        _write(out_dir / "api_preflight.json", preflight_report)
        if not preflight_report.get("passed"):
            raise PreflightError(
                preflight_report.get("failure_summary") or "preflight failed",
                report=preflight_report,
            )

    event_bundle = load_events_json(Path(events_path), input_source=input_source)
    event_digest = planner_event_digest(event_bundle)
    _write(out_dir / "event_digest.json", event_digest)

    # --- A: original strip ---
    strip_a = load_or_run_baseline_A(
        events_path=Path(events_path),
        out_dir=ab_dir,
        algo_root=Path(algo_root),
        match_id=str(event_bundle.get("match_id") or "match"),
        existing_strip_a=strip_a_path,
    )
    strip_a_adapted = adapt_strip_bundle(
        ab_dir / "strip_A_original.json",
        events_path=Path(events_path),
        match_id=event_bundle.get("match_id"),
    )
    _write(out_dir / "predicted_strip_chains_A.json", strip_a_adapted)

    detector = detect_missing_goals(
        events=event_bundle.get("events") or [],
        predicted_strips=strip_a_adapted.get("chains") or [],
        match_id=event_bundle.get("match_id"),
    )
    if candidate_ids:
        allow = set(candidate_ids)
        detector["missing_goal_candidates"] = [
            c for c in (detector.get("missing_goal_candidates") or []) if c.get("candidate_id") in allow
        ]
        detector["n_missing"] = len(detector["missing_goal_candidates"])
        detector["filtered_to_candidate_ids"] = list(allow)
    _write(out_dir / "missing_goal_candidates.json", detector)

    # Working state for candidates
    cand_state: Dict[str, Dict[str, Any]] = {}
    for c in detector.get("missing_goal_candidates") or []:
        cand_state[c["candidate_id"]] = {
            **c,
            "n_observations": 0,
            "last_grade": None,
            "last_window": None,
            "last_score_pairs": [],
            "board_after_seen": False,
            "board_after_window": None,
            "evidence_rows": [],
            "search_status": c.get("search_status") or "pending_video",
        }

    verifications: List[Dict[str, Any]] = []
    localized: List[Dict[str, Any]] = []
    inferred: List[Dict[str, Any]] = []
    trace: List[Dict[str, Any]] = []
    evid_i = 0

    media = probe_video(video)
    store = FrameStore(media, out_dir=frames_dir, budget=FrameBudget(max_frames=frame_budget))
    vision = VisionProvider(api=api, force_mock=bool(api.force_mock))
    tools = V2PhaseC1Toolbox(
        duration=media.duration_sec,
        store=store,
        vision=vision,
        task_note=(
            "Recover missing goals: require shot AND net with frame cites. "
            "Scoreboard/celebration alone insufficient. Separate live vs replay."
        ),
    )
    agent = V2GoalRecoveryAgent(api=api, use_llm_planner=use_llm_planner and not skip_video)
    stop_reason = "max_steps"

    if skip_video:
        stop_reason = "skip_video"
        for cid, c in cand_state.items():
            c["search_status"] = "skipped_no_video"
            c["verification_status"] = "unresolved"
    else:
        for step in range(max_steps):
            open_cands = [
                c
                for c in cand_state.values()
                if c.get("search_status") not in {"resolved_verified", "unresolved_closed", "skipped_no_video"}
            ]
            state = {
                "open_candidates": [
                    {
                        "candidate_id": c["candidate_id"],
                        "kind": c.get("kind"),
                        "score_before": c.get("score_before"),
                        "score_after": c.get("score_after"),
                        "score_confirmation_time": c.get("score_confirmation_time"),
                        "previous_score_observation_time": c.get("previous_score_observation_time"),
                        "search_region": c.get("search_region"),
                        "n_observations": c.get("n_observations"),
                        "last_grade": c.get("last_grade"),
                        "last_window": c.get("last_window"),
                        "last_score_pairs": c.get("last_score_pairs"),
                        "board_after_seen": c.get("board_after_seen"),
                        "board_after_window": c.get("board_after_window"),
                        "last_shot_action": c.get("last_shot_action"),
                        "last_goal_result": c.get("last_goal_result"),
                        "last_has_net": c.get("last_has_net"),
                        "tried_dense_around_shot": c.get("tried_dense_around_shot"),
                        "tried_dense_around_result": c.get("tried_dense_around_result"),
                        "same_window_streak": c.get("same_window_streak"),
                        "nearby_predicted_strip_ids": c.get("nearby_predicted_strip_ids"),
                    }
                    for c in open_cands
                ],
                "recent_observations": verifications[-4:],
                "frames_remaining": store.budget.remaining,
            }
            decision = agent.decide(state, step, max_steps)
            row: Dict[str, Any] = {"step": step, "decision": decision}
            tool = decision.get("tool")
            args = decision.get("arguments") or {}

            if tool == "finish":
                stop_reason = str(decision.get("reason") or "finish")
                row["observation"] = {"terminal": True}
                trace.append(row)
                break

            if tool == "mark_unresolved":
                cid = str(args.get("candidate_id") or "")
                if cid in cand_state:
                    cand_state[cid]["search_status"] = "unresolved_closed"
                    cand_state[cid]["verification_status"] = "unresolved"
                    cand_state[cid]["close_reason"] = str(args.get("why") or "")
                row["observation"] = {"marked_unresolved": cid}
                trace.append(row)
                continue

            # observe_phase / refine
            cid = str(args.get("candidate_id") or "")
            c = cand_state.get(cid)
            if not c:
                row["observation"] = {"error": "unknown_candidate"}
                trace.append(row)
                continue

            purpose = str(args.get("purpose") or "coarse")
            c1 = PURPOSE_MAP.get(purpose, "coarse_search")
            if tool == "observe_phase":
                phases = list((c.get("search_region") or {}).get("phases") or [])
                idx = int(args.get("phase_index") or 0)
                idx = max(0, min(idx, len(phases) - 1)) if phases else 0
                if not phases:
                    c["search_status"] = "unresolved_closed"
                    row["observation"] = {"error": "no_phases"}
                    trace.append(row)
                    continue
                start = float(phases[idx]["start_sec"])
                end = float(phases[idx]["end_sec"])
                # Cap coarse tool spans
                if end - start > 120:
                    # take the last 120s of the phase (nearer confirmation)
                    start = end - 120.0
            else:  # refine
                start = float(args.get("start"))
                end = float(args.get("end"))
                c1 = PURPOSE_MAP.get(purpose, "refine_window")
                if purpose == "dense":
                    c1 = "dense_action_inspect"

            start = max(0.0, min(start, media.duration_sec - 1.0))
            end = max(start + 0.6, min(end, media.duration_sec))
            raw_obs = tools.execute(c1, {"start": start, "end": end, "task_id": cid})
            perc = raw_obs.get("perception") or {}
            # Fail fast on non-retryable provider errors (invalid model / auth).
            if perc.get("error") or perc.get("provider_mode") == "degraded":
                fatal_meta = {
                    "http_status": 400 if "HTTP 400" in str(perc.get("message") or "") else 0,
                    "failure_status": perc.get("failure_status"),
                    "message": perc.get("message") or perc.get("error"),
                }
                # parse HTTP code from message when present
                msg = str(perc.get("message") or "")
                for code in (400, 401, 403):
                    if f"HTTP {code}" in msg:
                        fatal_meta["http_status"] = code
                if is_fatal_api_failure(fatal_meta) or is_fatal_api_failure(
                    {"failure_status": perc.get("failure_status"), "message": msg}
                ):
                    stop_reason = f"fatal_api:{perc.get('failure_status') or perc.get('error')}"
                    row["observation"] = {
                        "candidate_id": cid,
                        "fatal_api": True,
                        "perception_error": perc.get("error"),
                        "message": msg[:300],
                        "failure_status": perc.get("failure_status"),
                    }
                    trace.append(row)
                    break

            span = float(raw_obs.get("media_end_sec") or end) - float(raw_obs.get("media_start_sec") or start)
            evidence = grade_with_frame_evidence(observation=raw_obs, window_span_sec=span)
            evid_i += 1
            eid = f"rcv_{evid_i}_{cid}"
            vrow = {
                "evidence_id": eid,
                "linked_candidate_id": cid,
                "linked_strip_chain_ids": c.get("nearby_predicted_strip_ids") or [],
                "linked_event_ids": c.get("candidate_event_ids") or [],
                "observed_media_in": raw_obs.get("media_start_sec"),
                "observed_media_out": raw_obs.get("media_end_sec"),
                "observation_window": evidence.get("observation_window"),
                "shot_action": evidence.get("shot_action"),
                "goal_result": evidence.get("goal_result"),
                "edit_window": evidence.get("edit_window"),
                "action_time_resolved": evidence.get("action_time_resolved"),
                "supporting_frame_ids": evidence.get("supporting_frame_ids"),
                "observed_actions": evidence.get("observed_action_sequence"),
                "is_live": evidence.get("live_or_replay") in ("live", "mixed"),
                "is_replay": evidence.get("live_or_replay") == "replay",
                "live_or_replay": evidence.get("live_or_replay"),
                "action_completeness": (
                    "shot_and_result"
                    if evidence.get("action_time_resolved")
                    else "partial"
                ),
                "visual_consistency": evidence.get("grade"),
                "verification_status": evidence.get("verification_status"),
                "uncertainty": evidence.get("uncertainty"),
                "grade": evidence.get("grade"),
                "evidence": evidence,
                "related_score_transition": {
                    "score_before": c.get("score_before"),
                    "score_after": c.get("score_after"),
                    "score_confirmation_time": c.get("score_confirmation_time"),
                },
                "search_window": {"start": start, "end": end, "tool": c1},
                "frames": raw_obs.get("frames"),
                "render_ready": False,
            }
            verifications.append(vrow)
            c.setdefault("evidence_rows", []).append(vrow)
            c["n_observations"] = int(c.get("n_observations") or 0) + 1
            c["last_grade"] = evidence.get("grade")
            c["last_window"] = {"start": start, "end": end}
            # Score pairs seen in this window — used by rule planner to walk earlier
            # when the board already shows score_after (action predates confirmation).
            pairs: List[List[int]] = []
            for a in evidence.get("observed_action_sequence") or []:
                if isinstance(a, dict) and a.get("kind") == "score_change" and a.get("score_after"):
                    pairs.append(list(a["score_after"]))
            for sp in evidence.get("score_pairs") or []:
                if isinstance(sp, (list, tuple)) and len(sp) == 2:
                    pairs.append([int(sp[0]), int(sp[1])])
            c["last_score_pairs"] = pairs
            after = c.get("score_after")
            if after and any(tuple(p) == tuple(after) for p in pairs):
                c["board_after_seen"] = True
                baw = c.get("board_after_window")
                # Keep the earliest window that still shows score_after as the
                # back-search ceiling (action must be before this).
                if not baw or float(start) < float(baw.get("start") or start) + 1e-6:
                    c["board_after_window"] = {"start": start, "end": end}
            # Surface partial shot/result localization for the rule planner.
            if evidence.get("shot_action") and not c.get("tried_dense_around_shot"):
                c["last_shot_action"] = evidence.get("shot_action")
            if evidence.get("goal_result") and not c.get("tried_dense_around_result"):
                c["last_goal_result"] = evidence.get("goal_result")
            c["last_has_net"] = bool(evidence.get("goal_result_evidence") or evidence.get("has_net_keyword"))
            c["same_window_streak"] = (
                int(c.get("same_window_streak") or 0) + 1
                if c.get("prev_window") == c.get("last_window")
                else 1
            )
            c["prev_window"] = dict(c["last_window"])
            # Detect densify-around-shot tool usage via tight window about prior shot.
            prev_shot = c.get("last_shot_action") or {}
            if prev_shot.get("media_sec") is not None and abs(
                0.5 * (start + end) - float(prev_shot["media_sec"])
            ) < 6.0 and (end - start) <= 14.0:
                c["tried_dense_around_shot"] = True
                c["last_shot_action"] = None
            prev_res = c.get("last_goal_result") or {}
            if prev_res.get("media_sec") is not None and abs(
                0.5 * (start + end) - float(prev_res["media_sec"])
            ) < 6.0 and (end - start) <= 14.0:
                c["tried_dense_around_result"] = True
                c["last_goal_result"] = None

            # Aggregate across adjacent non-replay windows for this candidate.
            agg = merge_action_evidence_windows(c.get("evidence_rows") or [])
            emit_ev = dict(evidence)
            if agg.get("action_time_resolved"):
                emit_ev["shot_action"] = agg["shot_action"]
                emit_ev["goal_result"] = agg["goal_result"]
                emit_ev["edit_window"] = agg["edit_window"]
                emit_ev["action_time_resolved"] = True
                emit_ev["grade"] = "action_localized"
                emit_ev["verification_status"] = "verified_action"
                emit_ev["shooting_action_evidence"] = True
                emit_ev["goal_result_evidence"] = True
                if evidence.get("live_or_replay") != "replay":
                    emit_ev["live_or_replay"] = evidence.get("live_or_replay") or "live"

            # Attach score transition so emit gate can enforce result < confirmation.
            emit_ev["related_score_transition"] = vrow.get("related_score_transition")
            emit_ev["score_confirmation_time"] = c.get("score_confirmation_time")
            if c.get("confirmation_is_replay"):
                emit_ev["confirmation_is_replay"] = True
            if should_emit_inferred_goal(emit_ev):
                shot = emit_ev["shot_action"]
                result = emit_ev["goal_result"]
                edit = emit_ev.get("edit_window") or {}
                # Goal event time = result frame time (not observation midpoint).
                action_t = float(result["media_sec"])
                inf_id = f"inferred_goal_{cid}"
                if not any(x.get("inferred_event_id") == inf_id for x in inferred):
                    ge = make_inferred_goal_event(
                        inferred_event_id=inf_id,
                        media_time_sec=action_t,
                        media_start_sec=float(edit.get("media_in") or shot["media_sec"]),
                        media_end_sec=float(edit.get("media_out") or result["media_sec"]),
                        related_score_transition=vrow["related_score_transition"],
                        supporting_frame_ids=list(
                            dict.fromkeys(
                                [shot.get("frame_id"), result.get("frame_id")]
                                + list(vrow.get("supporting_frame_ids") or [])
                            )
                        ),
                        supporting_video_windows=[
                            r.get("search_window")
                            for r in (c.get("evidence_rows") or [])
                            if r.get("search_window")
                        ],
                        observation_windows=[
                            {
                                "media_in": r.get("observed_media_in"),
                                "media_out": r.get("observed_media_out"),
                                "evidence_id": r.get("evidence_id"),
                            }
                            for r in (c.get("evidence_rows") or [])
                        ],
                        shot_action=shot,
                        goal_result=result,
                        edit_window=edit,
                        verification_status="verified_action",
                        confidence=max(0.0, 1.0 - float(emit_ev.get("uncertainty") or 0.5)),
                        uncertainty=float(emit_ev.get("uncertainty") or 0.25),
                        live_or_replay=str(emit_ev.get("live_or_replay") or "unknown"),
                        notes="event_time=goal_result.media_sec; edit_window from shot/result frames",
                    )
                    inferred.append(ge)
                    localized.append(
                        {
                            "clip_id": f"loc_{inf_id}",
                            "linked_inferred_event_id": inf_id,
                            "linked_candidate_id": cid,
                            "media_in": ge["edit_window"]["media_in"],
                            "media_out": ge["edit_window"]["media_out"],
                            "shot_action_media_sec": shot.get("media_sec"),
                            "goal_result_media_sec": result.get("media_sec"),
                            "supporting_frame_ids": ge["supporting_frame_ids"],
                            "verification_status": "verified_action",
                            "usable_for_edit_candidate": True,
                            "as_story_node_candidate": True,
                            "render_ready": False,
                        }
                    )
                c["search_status"] = "resolved_verified"
                c["verification_status"] = "verified_action"
                c["inferred_event_id"] = inf_id
            else:
                c["search_status"] = "pending_video"
                c["verification_status"] = evidence.get("verification_status") or "unresolved"

            row["observation"] = {
                "candidate_id": cid,
                "grade": evidence.get("grade"),
                "verification_status": evidence.get("verification_status"),
                "action_time_resolved": evidence.get("action_time_resolved"),
                "shot_action": evidence.get("shot_action"),
                "goal_result": evidence.get("goal_result"),
                "window": {"start": start, "end": end},
                "emitted_inferred": c.get("search_status") == "resolved_verified",
            }
            trace.append(row)

            if c.get("search_status") == "resolved_verified" and candidate_ids and len(candidate_ids) == 1:
                stop_reason = "single_candidate_verified"
                break

            if store.budget.remaining <= 0:
                stop_reason = "frame_budget_exhausted"
                break

    # Close still-open candidates as unresolved
    for c in cand_state.values():
        if c.get("search_status") not in {"resolved_verified", "unresolved_closed", "skipped_no_video"}:
            c["search_status"] = "unresolved_closed"
            c["verification_status"] = "unresolved"
            c["close_reason"] = c.get("close_reason") or stop_reason

    # Update detector export with statuses
    for c in detector.get("missing_goal_candidates") or []:
        st = cand_state.get(c["candidate_id"]) or {}
        c["search_status"] = st.get("search_status")
        c["verification_status"] = st.get("verification_status")
        c["inferred_event_id"] = st.get("inferred_event_id")
        c["n_observations"] = st.get("n_observations")
        c["close_reason"] = st.get("close_reason")
    _write(out_dir / "missing_goal_candidates.json", detector)

    # Enhanced events
    enh_bundle = merge_enhanced_events_payload(
        original_events_path=Path(events_path),
        inferred_goals=inferred,
        match_id=event_bundle.get("match_id"),
    )
    write_enhanced_bundle(enh_dir, enh_bundle)
    _write(out_dir / "video_verifications.json", {"verifications": verifications, "render_ready": False})

    # --- B: strip on enhanced ---
    timeline_b = events_to_timeline(enh_bundle.get("merged_events_for_strip") or [])
    _write(ab_dir / "timeline_B.json", {"n": len(timeline_b), "events": timeline_b})
    strip_b = run_strip_predict(
        timeline_events=timeline_b,
        match_id=str(event_bundle.get("match_id") or "match"),
        algo_root=Path(algo_root),
        label="B_enhanced",
    )
    strip_b["source_enhanced"] = str(enh_dir / "enhanced_events_for_strip.json")
    strip_b["n_inferred_merged"] = enh_bundle.get("n_inferred_verified_merged")
    _write(ab_dir / "strip_B_enhanced.json", strip_b)

    # Adapt B using a temp events path that includes inferred (merged envelope)
    strip_b_adapted = adapt_strip_bundle(
        ab_dir / "strip_B_enhanced.json",
        events_path=enh_dir / "enhanced_events_for_strip.json",
        match_id=event_bundle.get("match_id"),
    )
    _write(out_dir / "predicted_strip_chains_B.json", strip_b_adapted)

    ab = compare_strip_ab(
        strip_a=strip_a,
        strip_b=strip_b,
        missing_candidates=detector.get("missing_goal_candidates") or [],
    )
    _write(out_dir / "strip_ab_compare.json", ab)
    impact = analyze_inferred_in_strip_b(
        strip_b=strip_b, inferred_events=inferred, timeline_b=timeline_b
    )
    _write(out_dir / "inferred_goal_strip_impact.json", impact)

    story = _build_story_from_recovery(
        event_digest=event_digest,
        detector=detector,
        inferred=inferred,
        strip_b_bundle=strip_b_adapted,
        verifications=verifications,
        localized=localized,
    )
    _write(out_dir / "story_candidates.json", story["story_candidates"])
    _write(out_dir / "story_beats.json", story["story_beats"])
    _write(out_dir / "story_relations.json", story["story_relations"])
    _write(out_dir / "localized_story_clips.json", story["localized_story_clips"])

    api_stats = api.stats.summary()
    agent_trace = {
        "schema": "v2_strip_r2_agent_trace_v1",
        "mode": "strip_guided_r2_goal_recovery",
        "elapsed_sec": round(time.time() - t0, 3),
        "stop_reason": stop_reason,
        "max_steps": max_steps,
        "steps": trace,
        "planner_mode_log": agent.planner_mode_log,
        "frames_used": store.budget.used,
        "frame_budget": frame_budget,
        "api_stats": api_stats,
        "cost_disclaimer": COST_DISCLAIMER,
        "n_missing_candidates": detector.get("n_missing"),
        "n_inferred_verified": len([e for e in inferred if e.get("verification_status") == "verified_action"]),
        "strip_ab_summary": {
            "n_A": ab.get("n_chains_A"),
            "n_B": ab.get("n_chains_B"),
            "outcome_A": ab.get("n_outcome_or_goal_A"),
            "outcome_B": ab.get("n_outcome_or_goal_B"),
        },
        "render_ready": False,
    }
    _write(out_dir / "story_agent_trace.json", agent_trace)

    report = {
        "schema": "v2_strip_guided_r2_report_v1",
        "match_id": event_bundle.get("match_id"),
        "events_path": str(events_path),
        "video": str(video),
        "algo_root": str(algo_root),
        "n_missing_goal_candidates": detector.get("n_missing"),
        "n_inferred_verified_goals": agent_trace["n_inferred_verified"],
        "n_verifications": len(verifications),
        "n_localized_clips": len(localized),
        "strip_A_chains": strip_a.get("n_chains"),
        "strip_B_chains": strip_b.get("n_chains"),
        "strip_ab_compare": ab,
        "inferred_goal_strip_impact": impact,
        "api_preflight": preflight_report,
        "discovery_status": story["story_candidates"].get("discovery_status"),
        "elapsed_sec": agent_trace["elapsed_sec"],
        "api_stats": api_stats,
        "stop_reason": stop_reason,
        "candidate_ids_filter": candidate_ids,
        "render_ready": False,
        "artifacts": {
            "missing_goal_candidates": str(out_dir / "missing_goal_candidates.json"),
            "inferred_events": str(enh_dir / "inferred_goal_events.json"),
            "strip_A": str(ab_dir / "strip_A_original.json"),
            "strip_B": str(ab_dir / "strip_B_enhanced.json"),
            "strip_ab_compare": str(out_dir / "strip_ab_compare.json"),
            "inferred_goal_strip_impact": str(out_dir / "inferred_goal_strip_impact.json"),
            "story_agent_trace": str(out_dir / "story_agent_trace.json"),
            "api_preflight": str(out_dir / "api_preflight.json") if preflight_report else None,
        },
    }
    _write(out_dir / "cli_report.json", report)
    return report
