"""Unified CLI for V3-A story-level E2E (match JSON + source MP4).

Examples:
  # Oman regression offline dry-run (reuse frozen V3-R Phase5)
  python -m story_video_agent_v3.story_e2e_cli \\
    --match-json /path/to/match.json \\
    --source-mp4 /path/to/match.mp4 \\
    --phase5-dir .../04_phase5 \\
    --out-dir /data2/lpy1/_story_va_outputs/v3/plan2/A_story_e2e_<ts> \\
    --offline

Never sends paid HTTP unless --enable-real-api AND --i-approve-budget AND
STORY_API_ENABLE=1 (and even then this pass stops before calling until authorized).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .story_e2e_agent import StoryE2EInputs, run_story_e2e


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="V3-A story-level end-to-end agent")
    p.add_argument("--match-json", type=Path, required=True)
    p.add_argument("--source-mp4", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument(
        "--phase5-dir",
        type=Path,
        default=None,
        help="Reuse frozen V3-R Phase5 (EDL/plan/story_clean) for regression",
    )
    p.add_argument("--baseline-edl", type=Path, default=None)
    p.add_argument("--story-plan", type=Path, default=None)
    p.add_argument("--initial-story-mp4", type=Path, default=None)
    p.add_argument("--t01-story", type=Path, default=None)
    p.add_argument("--events-json", type=Path, default=None,
                   help="Raw events for fresh V3-R (required with --run-fresh-v3r)")
    p.add_argument("--causal-atoms-json", type=Path, default=None,
                   help="Human causal atoms for fresh V3-R")
    p.add_argument("--match-id", type=str, default=None)
    p.add_argument("--algo-root", type=Path, default=None)
    p.add_argument("--run-fresh-v3r", action="store_true", default=False,
                   help="Generate Phase5 from events+causal+video (not JSON alone)")
    p.add_argument("--offline", action="store_true", default=True)
    p.add_argument("--enable-real-api", action="store_true", default=False)
    p.add_argument("--i-approve-budget", action="store_true", default=False)
    p.add_argument("--force-render-initial", action="store_true", default=False)
    p.add_argument("--force-render-candidate", action="store_true", default=False)
    p.add_argument("--no-smoke-render", action="store_true", default=False)
    p.add_argument("--max-rounds", type=int, default=3)
    p.add_argument("--max-calls", type=int, default=5)
    p.add_argument("--max-cost-usd", type=float, default=0.10)
    p.add_argument("--fixture-revision", type=Path, default=None)
    p.add_argument("--fixture-verifier", type=Path, default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.match_json.is_file():
        print(f"ERROR: match json not found: {args.match_json}", file=sys.stderr)
        return 2
    if not args.source_mp4.is_file():
        print(f"ERROR: source mp4 not found: {args.source_mp4}", file=sys.stderr)
        return 2

    fixture_revision = None
    fixture_verifier = None
    if args.fixture_revision and args.fixture_revision.is_file():
        fixture_revision = json.loads(args.fixture_revision.read_text(encoding="utf-8"))
    if args.fixture_verifier and args.fixture_verifier.is_file():
        fixture_verifier = json.loads(args.fixture_verifier.read_text(encoding="utf-8"))

    # Default out timestamp if user passed a parent pattern — keep exact path.
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    inp = StoryE2EInputs(
        match_json=args.match_json.resolve(),
        source_mp4=args.source_mp4.resolve(),
        out_dir=out_dir.resolve(),
        phase5_dir=args.phase5_dir.resolve() if args.phase5_dir else None,
        initial_story_mp4=args.initial_story_mp4.resolve() if args.initial_story_mp4 else None,
        baseline_edl=args.baseline_edl.resolve() if args.baseline_edl else None,
        story_plan=args.story_plan.resolve() if args.story_plan else None,
        t01_story=args.t01_story.resolve() if args.t01_story else None,
        events_json=args.events_json.resolve() if args.events_json else None,
        causal_atoms_json=args.causal_atoms_json.resolve() if args.causal_atoms_json else None,
        match_id=args.match_id,
        algo_root=args.algo_root.resolve() if args.algo_root else None,
        run_fresh_v3r=bool(args.run_fresh_v3r),
        skip_vlm=True if args.offline or not args.enable_real_api else False,
        enable_real_api=bool(args.enable_real_api),
        i_approve_budget=bool(args.i_approve_budget),
        force_render_initial=bool(args.force_render_initial),
        force_render_candidate=bool(args.force_render_candidate),
        smoke_render=not bool(args.no_smoke_render),
        fixture_revision=fixture_revision,
        fixture_verifier=fixture_verifier,
        max_rounds=int(args.max_rounds),
        max_calls=int(args.max_calls),
        max_cost_usd=float(args.max_cost_usd),
        max_retries=0,
    )
    t0 = time.time()
    audit = run_story_e2e(inp)
    elapsed = time.time() - t0
    gates = audit.get("status_gates") or {}
    delivery = audit.get("delivery") or {}
    print(
        json.dumps(
            {
                "ok": audit.get("ok"),
                "unified_main_chain": audit.get("unified_main_chain"),
                "revision_status_totals": audit.get("revision_status_totals"),
                "out_dir": str(out_dir),
                "elapsed_sec": round(elapsed, 3),
                "decision": delivery.get("decision"),
                "delivery_label": delivery.get("delivery_label"),
                "status_gates": gates,
                "http_calls": audit.get("http_calls"),
                "est_cost_usd": audit.get("est_cost_usd"),
                "final_mp4": delivery.get("final_mp4"),
                "error": audit.get("error"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if audit.get("error") and not gates.get("workflow_completed"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
