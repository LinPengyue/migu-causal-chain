"""Continue Story-First from a P3-accepted preview, independently of formal delivery."""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from .final_goal_evidence import sha256_file
from .fresh_e2e_cli import read_json, write_json
from .self_revise_agent import apply_candidate_revision
from .story_edl_safety import check_source_pts_monotonic
from .story_first_p3 import MAX_P3_ROUNDS, _request, run_p3_revision
from .story_first_revision import bind_story_first_trial, review_story_first_trial
from .story_first_search import discover_story_first, story_first_calls_left
from .story_paid_eval import provider_usage
from .story_timeline import _num, active_cut_rows
from .story_video_verifier import timeline_mp4_aligned

OUTER_CALL_RESERVE = 4  # One P1 generation, outer plan, P2 verification and P3 Caption.


def _preview(edl, mp4, output):
    alignment = timeline_mp4_aligned(edl=edl, mp4=mp4)
    if not alignment["aligned"]:
        raise ValueError("outer_preview_edl_and_video_do_not_align")
    write_json(output, edl)
    return {
        "edl": str(output), "mp4": str(mp4), "mp4_sha256": sha256_file(mp4),
        "duration_sec": alignment["mp4_duration_sec"],
    }


def _source_windows(trial):
    return [(w["source_pts_start"], w["source_pts_end"])
            for w in trial["windows"] if not w.get("existing_segment_id")]


def _p3_feedback(report, edl, review):
    added = {intent["new_segment_id"] for intent in review["intents"]}
    return {
        "p3_stop_reason": report["stop_reason"],
        "local_trims": report["completed_edits"],
        "accepted_source_windows_sec": [
            [row["media_in"], row["media_out"]]
            for row in active_cut_rows(edl) if row.get("segment_id") in added
        ],
        "local_decisions": [
            {"action": row["action"], "rationale": row.get("rationale")}
            for row in report["rounds"] if row.get("action")
        ],
    }


def _select(api, *, story_plan, current_edl, proposals, history, out):
    context = {
        "story_template": {k: story_plan[k] for k in (
            "template_id", "template", "template_name", "title", "beats", "story_beats"
        ) if k in story_plan},
        "accepted_cut": active_cut_rows(current_edl),
        "fresh_p1_candidates": proposals,
        "prior_round_feedback": history,
    }
    write_json(out / "planner_input.json", context)
    prompt = (
        "You are the Story-First Revision Planner for the next outer round. "
        "The accepted cut is the parent and all its footage must be preserved. "
        "Choose at most one additional local story that contributes to the existing template. "
        "Use only IDs from the fresh P1 pool and select only uncovered, non-replay events for new "
        "footage. Prior accepted and rejected event IDs and source windows are recorded in feedback. "
        "Keep relations hypothetical unless the supplied evidence supports them. "
        "If all viable footage is exhausted, return a null selection. "
        'Return JSON {"selection":{"selections":[{"proposal_id":"...","event_ids":["..."],'
        '"relation_ids":[]}],"rationale":"..."}}, or {"selection":null}.\n'
        + json.dumps(context, ensure_ascii=False)
    )
    response = _request(api, "planner", "planner", prompt, out, stats_prefix="story_first_p35")
    if response["parsed"] is None:
        raise ValueError(response["error"] or "no_structured_outer_plan")
    selection = response["parsed"].get("selection")
    if selection is not None and not isinstance(selection, Mapping):
        raise ValueError("invalid_outer_selection")
    return selection


def continue_story_first(
    *, baseline_edl, baseline_mp4, first_p3_dir, first_p3, first_review, story_plan,
    source_mp4, source_sha, events, teams, first_live_store, api, render, out_dir,
    max_outer_rounds, data_tier,
):
    """Report V3-R and round 1, then run new search/verification on the accepted parent."""
    if not 1 <= max_outer_rounds <= 3:
        raise ValueError("story_first_outer_round_count_out_of_range")
    if first_p3.get("preview_accepted") is not True or first_p3.get("release_authorized") is not False:
        raise ValueError("first_outer_round_requires_an_accepted_p3_preview")
    edl = read_json(first_p3_dir / "selected_preview_edl.json")
    mp4 = Path(first_p3["selected_preview_mp4"])
    if sha256_file(mp4) != first_p3["selected_preview_mp4_sha256"]:
        raise ValueError("first_outer_preview_video_mismatch")
    out_dir.mkdir(parents=True)
    comparison = [
        {"outer_rounds": 0, "status": "V3_R", "accepted_changes": 0,
         **_preview(baseline_edl, baseline_mp4, out_dir / "v0_edl.json")},
        {"outer_rounds": 1, "status": "ACCEPTED_PREVIEW", "accepted_changes": 1,
         "local_trims": first_p3["completed_edits"], "p3_stop_reason": first_p3["stop_reason"],
         **_preview(edl, mp4, out_dir / "v1_edl.json")},
    ]
    tried, windows, events_seen = set(), set(), set()
    for intent in first_review["intents"]:
        span = intent["bound_source_window"]
        windows.add((span["start"], span["end"]))
        events_seen.update(intent["event_ids"])
        tried.add(intent["story_first_trial_id"])
    history = [{
        "round": 1, "status": "ACCEPTED_PREVIEW",
        "source_advisory": first_review.get("advisory") or [],
        **_p3_feedback(first_p3, edl, first_review),
    }]
    before = int(provider_usage(api)["http_attempts"] or 0) if api is not None else 0
    attempted = accepted = 1
    for index in range(2, max_outer_rounds + 1):
        folder = out_dir / f"round_{index:02d}"
        folder.mkdir()
        rec = {"round": index, "parent_mp4_sha256": comparison[-1]["mp4_sha256"]}
        attempted += 1
        context = {
            "previous_rounds": history, "tried_source_windows_sec": sorted(windows),
            "tried_event_ids": sorted(events_seen),
            "instruction": "Propose new story footage. Covered and tried events may provide "
                           "context, but every story must include an untried uncovered event.",
        }
        accepted_now = False
        write_json(folder / "parent_edl.json", edl)
        reserve_later = OUTER_CALL_RESERVE * (max_outer_rounds - index)
        try:
            pool = discover_story_first(
                edl=edl, story_plan=story_plan, events=events, source_sha=source_sha,
                out_dir=folder / "p1", api=api, reserve_calls=3 + reserve_later,
                data_tier=data_tier, revision_context=context,
            )
            covered = [(lo, hi) for r in active_cut_rows(edl)
                       if (lo := _num(r.get("media_in"))) is not None
                       and (hi := _num(r.get("media_out"))) is not None]
            proposals = [
                p for p in pool["proposals"] if any(
                    e["event_id"] not in events_seen and not e["known_replay_or_slowmo"]
                    and not any(lo <= e["source_pts_sec"] < hi for lo, hi in covered)
                    for e in p["events"]
                )
            ]
            rec["p1_proposals"] = len(pool["proposals"])
            rec["new_proposals"] = len(proposals)
            if not proposals:
                rec["status"] = (
                    "P1_BUDGET_EXHAUSTED" if any(i["status"] == "DEFERRED_FOR_BUDGET"
                                                 for i in pool["intervals"]) else
                    "P1_UNAVAILABLE" if any(i["status"] in (
                        "PREPARED_ONLY", "MODEL_CONFIG_MISSING", "GENERATION_FAILED"
                    ) for i in pool["intervals"]) else "NO_NEW_CANDIDATE"
                )
            elif story_first_calls_left(api) <= reserve_later + 1:
                rec["status"] = "API_BUDGET"
            else:
                selection = _select(
                    api, story_plan=story_plan, current_edl=edl, proposals=proposals,
                    history=context, out=folder,
                )
                if selection is None:
                    rec["status"] = "NO_SELECTION"
                else:
                    trial = bind_story_first_trial(selection, proposals, edl, tried)
                    new_windows = _source_windows(trial)
                    new_events = {eid for w in trial["windows"] if not w.get("existing_segment_id")
                                  for eid in w["event_ids"]}
                    if new_events & events_seen or any(
                        any(lo <= start < end <= hi for lo, hi in windows)
                        for start, end in new_windows
                    ):
                        raise ValueError("already_tried_story_first_events_or_windows")
                    tried.add(trial["trial_id"])
                    windows.update(new_windows)
                    events_seen.update(new_events)
                    rec.update(trial_id=trial["trial_id"], source_windows_sec=new_windows,
                               event_ids=sorted(new_events))
                    review = review_story_first_trial(
                        trial, api=api if story_first_calls_left(api) >= reserve_later + 2 else None,
                        source_mp4=source_mp4, source_sha=source_sha, out_dir=folder / "p2",
                        first_live_store=first_live_store, source_events=events, teams=teams,
                    )
                    write_json(folder / "p2_review.json", {"trial": trial, "review": review})
                    rec.update(status=review["status"], source_feedback=review["feedback"],
                               source_advisory=review.get("advisory") or [])
                    if review["status"] == "READY_FOR_TRIAL" and review["intents"]:
                        intents = [{**i, "story_first_preview_only": True} for i in review["intents"]]
                        trial_edl, applied = apply_candidate_revision(edl, intents, observations=[])
                        if (applied["rejected"] or applied["evidence_bound_count"] != len(intents)
                                or not check_source_pts_monotonic(trial_edl)["ok"]):
                            raise ValueError("outer_source_intents_failed_edl_checks")
                        write_json(folder / "trial_edl.json", trial_edl)
                        trial_mp4 = render(trial_edl, folder / "trial_render")
                        if not trial_mp4 or not Path(trial_mp4).is_file():
                            raise ValueError("outer_trial_render_missing")
                        p3_dir = folder / "p3"
                        p3 = run_p3_revision(
                            baseline_edl=edl, baseline_mp4=mp4, trial_edl=trial_edl,
                            trial_mp4=Path(trial_mp4), review=review, proposals=proposals,
                            story_plan=story_plan, out_dir=p3_dir, api=api, render=render,
                            prior_feedback=history, max_local_trims=MAX_P3_ROUNDS,
                            reserve_calls=reserve_later,
                        )
                        edl = read_json(p3_dir / "selected_preview_edl.json")
                        mp4 = Path(p3["selected_preview_mp4"])
                        rec.update(status="ACCEPTED_PREVIEW", **_p3_feedback(p3, edl, review))
                        accepted += 1
                        accepted_now = True
        except (ValueError, OSError, RuntimeError) as exc:
            rec.update(status="ROUND_NOT_APPLIED", error=str(exc))
        history.append(rec)
        write_json(folder / "round_result.json", rec)
        comparison.append({
            "outer_rounds": index, "status": rec["status"], "accepted_changes": accepted,
            "changed_from_previous_round": accepted_now,
            **_preview(edl, mp4, out_dir / f"v{index}_edl.json"),
        })
    usage = provider_usage(api) if api is not None else {}
    report = {
        "schema": "story_first_outer_comparison_v1", "preview_only": True,
        "release_authorized": False, "requested_outer_rounds": max_outer_rounds,
        "attempted_outer_rounds": attempted, "accepted_changes": accepted,
        "http_calls_added_by_continuation": int(usage.get("http_attempts") or 0) - before,
        "api_usage": usage, "round_history": history, "comparison": comparison,
        "selected_preview": comparison[-1],
    }
    write_json(out_dir / "story_first_outer_comparison.json", report)
    return report
