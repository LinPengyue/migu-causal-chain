"""Plan source-bound trials for unverified Story-First hypotheses."""
from __future__ import annotations

import hashlib
import json
from typing import Mapping

from .first_live_window_evidence import build_broadcast_timeline_review
from .story_evidence_search import _annotate_first_live_tier, _live_credibility, event_media_span
from .self_revise_agent import MAX_BOUND_SPAN, MIN_BOUND_SPAN
from .story_narrative_fit import SUPPORTED, validate_narrative_fit_review
from .story_timeline import _num, active_cut_rows
from .story_first_hypotheses import _RELATIONS


def bind_story_first_trial(selection, proposals, edl, tried):
    """Resolve one Planner selection into exact, chronological source windows."""
    by_id = {p["proposal_id"]: p for p in proposals}
    entries = selection.get("selections")
    if not isinstance(entries, list) or not entries:
        raise ValueError("missing_story_first_selections")
    active = active_cut_rows(edl)
    rows = [r for r in active if _num(r.get("media_in")) is not None
            and _num(r.get("media_out")) is not None]
    seen_proposals = set()
    events, claims, windows = {}, [], []
    story_context = []
    existing_ids = {str(row.get("segment_id") or "") for row in edl}
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ValueError("invalid_story_first_selection")
        pid = str(entry.get("proposal_id") or "")
        p = by_id.get(pid)
        if p is None or pid in seen_proposals:
            raise ValueError("unknown_or_duplicate_story_first_proposal:" + pid)
        seen_proposals.add(pid)
        story_context.append({
            "proposal_id": pid, "summary": p["summary"],
            "expected_story_contribution": p["expected_story_contribution"],
            "falsification_conditions": p["falsification_conditions"],
            "causal_mechanism": p["causal_mechanism"],
            "major_uncertainty": p["major_uncertainty"],
        })
        ids, relation_ids = entry.get("event_ids"), entry.get("relation_ids", [])
        if (not isinstance(ids, list) or not ids or not all(isinstance(x, str) for x in ids)
                or not isinstance(relation_ids, list)
                or not all(isinstance(x, str) for x in relation_ids)):
            raise ValueError("invalid_story_first_event_or_relation_ids:" + pid)
        allowed = {e["event_id"]: e for e in p["events"]}
        if not set(ids) <= allowed.keys() or len(ids) != len(set(ids)):
            raise ValueError("unknown_or_duplicate_story_first_event_id:" + pid)
        relations = {r["relation_id"]: r for r in p["relations"]}
        if not set(relation_ids) <= relations.keys() or len(set(relation_ids)) != len(relation_ids):
            raise ValueError("unknown_or_duplicate_story_first_relation_id:" + pid)
        for rid in relation_ids:
            rel = relations[rid]
            if not {rel["source_event_id"], rel["target_event_id"]} <= set(ids):
                raise ValueError(f"unselected_relation_endpoint:{pid}:{rid}")
            claims.append({**rel, "relation_id": f"{pid}:{rid}"})
        lo, hi = p["scope"]["source_interval_sec"]
        for eid in ids:
            e = allowed[eid]
            events[eid] = e
            if e["known_replay_or_slowmo"]:
                raise ValueError("event_is_annotated_replay_or_slowmo:" + eid)
            t = e["source_pts_sec"]
            containing = next(
                (r for r in rows if float(r["media_in"]) <= t < float(r["media_out"])), None,
            )
            if containing is not None:
                if containing.get("is_replay") or containing.get("is_slow_motion"):
                    raise ValueError("selected_event_in_existing_replay:" + eid)
                windows.append({"source_pts_start": float(containing["media_in"]),
                                "source_pts_end": float(containing["media_out"]),
                                "event_ids": [eid], "existing_segment_id": containing["segment_id"]})
                continue
            for before, after in zip(rows, rows[1:]):
                start = round(max(float(before["media_out"]), lo, t - 8), 3)
                end = round(min(float(after["media_in"]), hi, t + 8), 3)
                if start <= t <= end and end - start >= MIN_BOUND_SPAN:
                    windows.append({
                        "event_ids": [eid], "source_pts_start": start, "source_pts_end": end,
                        "insert_after_segment_id": before["segment_id"],
                        "before_segment_id": after["segment_id"],
                    })
                    break
            else:
                raise ValueError("no_chronological_insert_window_for_event:" + eid)

    additional = selection.get("revised_relations", [])
    if not isinstance(additional, list):
        raise ValueError("invalid_revised_story_relations")
    for i, relation in enumerate(additional, 1):
        if not isinstance(relation, Mapping):
            raise ValueError("invalid_revised_story_relation")
        left = str(relation.get("source_event_id") or "")
        right = str(relation.get("target_event_id") or "")
        kind = str(relation.get("relation_type") or "")
        claim = str(relation.get("claim") or "").strip()[:300]
        if (left == right or left not in events or right not in events
                or kind not in _RELATIONS or not claim):
            raise ValueError("revised_story_relation_not_bound_to_selected_events")
        if kind in ("direct_action", "state_transition", "causal_hypothesis") and (
            events[left]["source_pts_sec"] >= events[right]["source_pts_sec"]
        ):
            raise ValueError("revised_story_causal_relation_reverses_source_pts")
        claims.append({
            "relation_id": f"revised:{i}", "source_event_id": left, "target_event_id": right,
            "relation_type": kind, "claim": claim,
            "evidence_status": "UNVERIFIED_MODEL_HYPOTHESIS",
        })

    # A Planner can repeat an original relation in revised_relations.
    # Keep the original ID for feedback and review the identical claim once.
    unique_claims = {}
    for claim in claims:
        identity = tuple(claim[field] for field in (
            "source_event_id", "target_event_id", "relation_type", "claim",
        ))
        unique_claims.setdefault(identity, claim)
    claims = list(unique_claims.values())

    windows.sort(key=lambda x: (x["source_pts_start"], x["source_pts_end"]))
    merged = []
    for window in windows:
        previous = merged[-1] if merged else None
        if previous and window["source_pts_start"] < previous["source_pts_end"]:
            if any(previous.get(k) != window.get(k) for k in (
                "insert_after_segment_id", "before_segment_id", "existing_segment_id"
            )):
                raise ValueError("overlapping_story_first_windows")
            previous["source_pts_end"] = max(previous["source_pts_end"], window["source_pts_end"])
            previous["event_ids"] = sorted(set(previous["event_ids"] + window["event_ids"]))
            if not previous.get("existing_segment_id") and (
                previous["source_pts_end"] - previous["source_pts_start"] > MAX_BOUND_SPAN
            ):
                raise ValueError("overlapping_events_exceed_one_clip_window")
        else:
            merged.append(window)
    if all(w.get("existing_segment_id") for w in merged):
        raise ValueError("selected_story_adds_no_source_window")
    # Same events, relation topology and bound windows constitute the same trial.
    key_payload = [merged, sorted(set(
        (r["source_event_id"], r["target_event_id"], r["relation_type"])
        for r in claims
    ))]
    key = hashlib.sha256(json.dumps(key_payload, sort_keys=True).encode()).hexdigest()[:24]
    if key in tried:
        raise ValueError("story_first_trial_already_observed:" + key)
    for i, w in enumerate(merged, 1):
        w["candidate_id"] = f"story_first_{key}_{i:02d}"
        w["issue_id"] = f"story_first:{key}"
        if "seg_" + w["candidate_id"] in existing_ids:
            raise ValueError("story_first_segment_id_already_exists:" + w["candidate_id"])
    return {
        "trial_id": key, "proposal_ids": sorted(seen_proposals),
        "events": sorted(events.values(), key=lambda e: (e["source_pts_sec"], e["event_id"])),
        "relations": claims, "story_context": story_context,
        "windows": merged, "narrative_purpose": str(selection.get("rationale") or "")[:600],
    }


def review_story_first_trial(trial, *, api, edl, source_mp4, source_sha, out_dir,
                             first_live_store, source_events=(), make_live_packs=False):
    """Use one visual call for selected events, relations and contextual clip fit."""
    from .story_first_video_review import observe_story_first_trial

    observed = observe_story_first_trial(
        api, trial=trial, edl=edl, source_mp4=source_mp4,
        source_sha=source_sha, out_dir=out_dir,
    )
    feedback = list(observed["feedback"])
    replay_events = [
        (event.get("event_id"), span)
        for event in source_events
        if ((live := _live_credibility(event))["is_replay"] or live["is_slow_motion"]
            or live["broadcast_phase"] in ("REPLAY", "SLOWMO", "SLOW_MOTION"))
        and (span := event_media_span(event)) is not None
    ]
    candidates = []
    for w in trial["windows"]:
        if w.get("existing_segment_id"):
            continue
        replay_ids = [
            eid for eid, (start, _, end) in replay_events
            if start < w["source_pts_end"] and end > w["source_pts_start"]
        ]
        if replay_ids:
            feedback.append({
                "window_id": w["candidate_id"], "event_ids": w["event_ids"],
                "status": "REPLAY_CONFIRMED", "reason": "window_overlaps_replay_or_slowmo_annotation",
                "replay_event_ids": replay_ids,
            })
            continue
        c = _annotate_first_live_tier(
            w, evidence_store=first_live_store, source_sha=source_sha, allow_non_goal_action=True,
        )
        if not c["executable_safe_revision"]:
            feedback.append({
                "window_id": w["candidate_id"], "event_ids": w["event_ids"],
                "status": c["first_live_status"], "reason": c["reject_or_defer_reason"],
            })
            if make_live_packs and source_sha:
                from .first_live_window_evidence import build_local_first_live_evidence_pack
                pack = build_local_first_live_evidence_pack(
                    source_mp4=source_mp4, source_sha=source_sha,
                    pts_start=w["source_pts_start"], pts_end=w["source_pts_end"],
                    out_dir=out_dir / w["candidate_id"], segment_id=w["candidate_id"],
                )
                if pack.get("ok"):
                    directory = out_dir / w["candidate_id"]
                    timeline = build_broadcast_timeline_review(
                        source_sha=source_sha, source_mp4=source_mp4, events=source_events,
                        pts_start=w["source_pts_start"], pts_end=w["source_pts_end"],
                        out_dir=directory, binding_record=pack,
                    )
                    feedback[-1]["local_frame_pack_dir"] = str(directory)
                    feedback[-1]["timeline_status"] = timeline["outcome"]
        fit = validate_narrative_fit_review(
            observed["fit_records"].get(w["candidate_id"]),
            candidate=c, source_sha=source_sha, edl=edl, require_files_exist=True,
        )
        if fit["status"] != SUPPORTED:
            feedback.append({
                "window_id": w["candidate_id"], "event_ids": w["event_ids"],
                "status": fit["status"], "reason": fit["reason"],
                "edit_context": {
                    k: value for k, value in (
                        ("before_to_candidate", fit.get("before_to_candidate")),
                        ("candidate_to_after", fit.get("candidate_to_after")),
                    ) if value
                },
            })
        candidates.append({
            **c, "story_first_trial_id": trial["trial_id"],
            "narrative_fit_supports_insert": fit["status"] == SUPPORTED,
            "narrative_fit_status": fit["status"], "narrative_fit": fit,
        })
    if feedback:
        return {"status": "NEEDS_REVISION", "feedback": feedback, "candidates": candidates,
                "intents": []}
    intents = [
        {
            "intent_id": c["candidate_id"], "action": "search_add",
            "role": "buildup_bridge_action", "issue_id": c["issue_id"],
            "story_first_trial_id": trial["trial_id"],
            "anchor_id": "search:" + c["candidate_id"],
            "new_segment_id": "seg_" + c["candidate_id"],
            "insert_after_segment_id": c["insert_after_segment_id"],
            "before_segment_id": c["before_segment_id"],
            "bound_source_window": {"start": c["source_pts_start"], "end": c["source_pts_end"]},
            "event_ids": c["event_ids"], "narrative_purpose": trial["narrative_purpose"],
            "video_observation_evidence": c["narrative_fit"]["new_story_information"],
            "expected_improvement": c["narrative_fit"]["new_story_information"],
            "expected_observable_improvement": c["narrative_fit"]["falsifiable_gain"],
            "falsification_evidence": (
                "Added footage does not convey the expected story information, "
                "duplicates an existing beat, or breaks the continuity of the full cut."
            ),
            "evidence_refs": [{"kind": "story_first_source_review", "ref": c["candidate_id"]}],
        }
        # The shared EDL applier inserts directly after an existing segment.
        # Within the same gap, apply later windows first to preserve source order.
        for c in reversed(candidates)
    ]
    return {"status": "READY_FOR_TRIAL", "feedback": [], "candidates": candidates,
            "intents": intents}
