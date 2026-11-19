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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("trial-artifacts", "source-review", "pool", "baseline-mp4", "trial-mp4", "out-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--source-mp4", type=Path)
    parser.add_argument("--events-json", type=Path)
    parser.add_argument("--first-live-evidence-dir", type=Path)
    parser.add_argument("--history", type=Path, action="append", default=[])
    parser.add_argument("--max-rounds", type=int, default=1, choices=range(1, MAX_P3_ROUNDS + 1))
    parser.add_argument("--max-calls", type=int, default=2)
    parser.add_argument("--max-cost-usd", type=float, default=0.05)
    parser.add_argument("--enable-real-api", action="store_true")
    parser.add_argument("--i-approve-budget", action="store_true")
    args = parser.parse_args(argv)

    api, render, review_replacement = None, None, None
    if args.enable_real_api and (
        not args.i_approve_budget or os.environ.get("STORY_API_ENABLE") != "1"
        or not 2 <= args.max_calls <= 3 * args.max_rounds
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
        if args.enable_real_api:
            source_sha = sha256_file(args.source_mp4)
            if not source_sha or source_sha != pool.get("source_sha256"):
                raise ValueError("source_video_does_not_match_search_pool")
            document = read_json(args.events_json)
            events = load_match_events(match_json=None, events_json=args.events_json)
            api = build_capped_provider(max_calls=args.max_calls, max_cost_usd=args.max_cost_usd)

            def render(edl, out_dir):
                return _render_edl(plan=plan, video=args.source_mp4, edl=edl,
                                   out_dir=out_dir).get("story_clean")

            review_replacement = p3_replacement_review(
                api=api, source_mp4=args.source_mp4, source_sha=source_sha,
                source_events=events, teams=document.get("teams") if isinstance(document, dict) else None,
                first_live_store=load_evidence_store(args.first_live_evidence_dir),
                audit_dir=args.out_dir / "replacement_source_reviews",
            )
        report = run_p3_revision(
            baseline_edl=baseline, baseline_mp4=args.baseline_mp4,
            trial_edl=trial, trial_mp4=args.trial_mp4, review=review,
            proposals=pool["proposals"], story_plan=plan, out_dir=args.out_dir,
            api=api, render=render, review_replacement=review_replacement,
            prior_feedback=[read_json(path) for path in args.history], max_rounds=args.max_rounds,
        )
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(2, f"P3 setup failed: {exc}\n")
    print(json.dumps({k: report[k] for k in (
        "stop_reason", "selected_preview_mp4", "http_calls", "release_authorized"
    )}, ensure_ascii=False))
    return 2 if report["stop_reason"] == "CAPTION_INPUT_PREPARATION_FAILED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
