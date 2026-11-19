"""Resume the shared P3 loop from an archived Story-First trial and its source review."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

from .final_goal_evidence import sha256_file
from .first_live_window_evidence import load_evidence_store
from .fresh_e2e_cli import edl_rows, read_json
from .story_e2e_agent import _render_edl
from .story_evidence_search import load_match_events
from .story_first_p3 import MAX_P3_ROUNDS, p3_replacement_review, run_p3_revision
from .story_paid_eval import build_capped_provider


def load_trim_checkpoint(directory, mp4, baseline_edl, baseline_mp4, trial_edl, trial_mp4):
    """Continue from one archived applied trim using the original P2-reviewed trial."""
    report = read_json(directory / "p3_revision.json")
    rounds = report["rounds"]
    edits = [r for r in rounds if r.get("next_preview_mp4")]
    if (len(edits) != 1 or edits[0].get("action") != "TRIM"
            or report.get("preview_only") is not True or report.get("release_authorized") is not False
            or report.get("stop_reason") != "PLANNER_KEEP"
            or edits[0]["next_preview_mp4"] != report.get("selected_preview_mp4")):
        raise ValueError("resume_requires_one_archived_selected_trim")
    first = directory / f"round_{edits[0]['round']:02d}"
    edit_name = Path(edits[0]["revision_intents"]).parent.name
    if not edit_name.startswith("edit_") or not edit_name[5:].isdigit():
        raise ValueError("invalid_archived_edit_directory")
    edit = first / edit_name
    expected = edl_rows(read_json(directory / "selected_preview_edl.json"))
    intents = read_json(edit / "revision_intents.json")["intents"]
    if (len(intents) != 1 or intents[0].get("action") != "trim"
            or edl_rows(read_json(edit / "next_preview_edl.json")) != expected
            or edl_rows(read_json(directory / "baseline_edl.json")) != baseline_edl
            or edl_rows(read_json(first / "working_edl.json")) != trial_edl
            or sha256_file(baseline_mp4) != report["baseline_mp4_sha256"]
            or sha256_file(trial_mp4) != read_json(first / "caption_input.json")["render_mp4_sha256"]):
        raise ValueError("archived_trim_does_not_match_input_preview")
    return {"intent": intents[0], "edl": expected, "mp4": mp4,
            "sha256": report["selected_preview_mp4_sha256"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("trial-artifacts", "source-review", "pool", "baseline-mp4", "trial-mp4", "out-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--source-mp4", type=Path)
    parser.add_argument("--events-json", type=Path)
    parser.add_argument("--first-live-evidence-dir", type=Path)
    parser.add_argument("--history", type=Path, action="append", default=[])
    parser.add_argument("--resume-trim-artifacts", type=Path)
    parser.add_argument("--resume-mp4", type=Path)
    parser.add_argument("--max-rounds", type=int, default=1, choices=range(1, MAX_P3_ROUNDS + 1))
    parser.add_argument("--max-local-trims", type=int, choices=range(MAX_P3_ROUNDS + 1),
                        help="Default-accept P3 mode with up to this many applied trims")
    parser.add_argument("--outer-rounds", type=int, choices=range(1, 4),
                        help="Compare V3-R and the requested Story-First rounds from the archived first cut")
    parser.add_argument("--max-calls", type=int, default=2)
    parser.add_argument("--max-cost-usd", type=float, default=0.05)
    parser.add_argument("--enable-real-api", action="store_true")
    parser.add_argument("--i-approve-budget", action="store_true")
    args = parser.parse_args(argv)
    if bool(args.resume_trim_artifacts) != bool(args.resume_mp4):
        parser.error("--resume-trim-artifacts and --resume-mp4 must be supplied together")
    if args.outer_rounds is not None and not args.resume_trim_artifacts:
        parser.error("--outer-rounds requires the selected trim checkpoint")
    if args.outer_rounds and args.outer_rounds > 1 and not (args.source_mp4 and args.events_json):
        parser.error("continued rounds require the original source video and enriched events")

    api, render, review_replacement = None, None, None
    max_calls = (24 if args.outer_rounds else
                 2 * args.max_local_trims + 1 if args.max_local_trims is not None else
                 3 * args.max_rounds)
    if args.enable_real_api and (
        not args.i_approve_budget or os.environ.get("STORY_API_ENABLE") != "1"
        or not 1 <= args.max_calls <= max_calls
        or not math.isfinite(args.max_cost_usd) or args.max_cost_usd <= 0
        or not args.source_mp4 or not args.events_json
    ):
        parser.error("real P3 requires approval, STORY_API_ENABLE=1, a valid budget and source inputs")

    try:
        artifacts = args.trial_artifacts
        baseline = edl_rows(read_json(artifacts / "baseline" / "formal_edl_snapshot.json"))
        trial = edl_rows(read_json(artifacts / "trial" / "temp_edl.json"))
        plan = read_json(artifacts / "baseline" / "story_plan.json")
        pool = read_json(args.pool)
        review = read_json(args.source_review)
        archived_intent = read_json(artifacts / "trial" / "intent_used.json")
        if archived_intent not in review.get("intents", []):
            raise ValueError("archived_trial_intent_not_present_in_source_review")
        digest = hashlib.sha256(json.dumps(baseline, sort_keys=True, ensure_ascii=False).encode())
        if digest.hexdigest() != pool.get("initial_edl_sha256"):
            raise ValueError("search_pool_does_not_match_baseline_edl")
        resume_trim = None
        if args.resume_trim_artifacts is not None:
            resume_trim = load_trim_checkpoint(
                args.resume_trim_artifacts, args.resume_mp4, baseline, args.baseline_mp4,
                trial, args.trial_mp4,
            )
        source_sha, events, teams, first_live_store = pool["source_sha256"], [], None, {}
        if args.source_mp4 and args.events_json:
            source_sha = sha256_file(args.source_mp4)
            if not source_sha or source_sha != pool.get("source_sha256"):
                raise ValueError("source_video_does_not_match_search_pool")
            document = read_json(args.events_json)
            events = load_match_events(match_json=None, events_json=args.events_json)
            teams = document.get("teams") if isinstance(document, dict) else None
            first_live_store = load_evidence_store(args.first_live_evidence_dir)
        if args.enable_real_api:
            api = build_capped_provider(max_calls=args.max_calls, max_cost_usd=args.max_cost_usd)

            def render(edl, out_dir):
                return _render_edl(plan=plan, video=args.source_mp4, edl=edl,
                                   out_dir=out_dir).get("story_clean")

            if args.max_local_trims is None and args.outer_rounds is None:
                review_replacement = p3_replacement_review(
                    api=api, source_mp4=args.source_mp4, source_sha=source_sha,
                    source_events=events, teams=teams, first_live_store=first_live_store,
                    audit_dir=args.out_dir / "replacement_source_reviews",
                )
        report = run_p3_revision(
            baseline_edl=baseline, baseline_mp4=args.baseline_mp4,
            trial_edl=trial, trial_mp4=args.trial_mp4, review=review,
            proposals=pool["proposals"], story_plan=plan, out_dir=args.out_dir,
            api=api if args.outer_rounds is None else None,
            render=render, review_replacement=review_replacement,
            prior_feedback=[read_json(path) for path in args.history], max_rounds=args.max_rounds,
            resume_trim=resume_trim,
            max_local_trims=MAX_P3_ROUNDS if args.outer_rounds else args.max_local_trims,
        )
        if args.outer_rounds is not None:
            from .story_first_outer import continue_story_first

            outer = continue_story_first(
                baseline_edl=baseline, baseline_mp4=args.baseline_mp4, first_p3_dir=args.out_dir,
                first_p3=report, first_review=review, story_plan=plan,
                source_mp4=args.source_mp4, source_sha=source_sha, events=events, teams=teams,
                first_live_store=first_live_store, api=api, render=render,
                max_outer_rounds=args.outer_rounds, out_dir=args.out_dir / "outer",
                data_tier="EVENT_DERIVED_FROM_PERMITTED_INPUT",
            )
            print(json.dumps(outer, ensure_ascii=False, indent=2))
            return 0
    except (KeyError, TypeError, ValueError, OSError, RuntimeError) as exc:
        parser.exit(2, f"P3 setup failed: {exc}\n")
    print(json.dumps({k: report[k] for k in (
        "stop_reason", "selected_preview_mp4", "http_calls", "release_authorized", "completed_edits"
    )}, ensure_ascii=False))
    return 2 if report["stop_reason"] == "CAPTION_INPUT_PREPARATION_FAILED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
