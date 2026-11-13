"""Unified CLI for V3-A story-level E2E (match JSON + source MP4).

Examples:
  # Oman regression offline dry-run (reuse frozen V3-R Phase5)
  python -m story_video_agent_v3.story_e2e_cli \\
    --match-json /path/to/match.json \\
    --source-mp4 /path/to/match.mp4 \\
    --phase5-dir .../04_phase5 \\
    --out-dir /data2/lpy1/_story_va_outputs/v3/plan2/A_story_e2e_<ts>

  # Authorized paid multi-round (requires budget flags + env)
  python -m story_video_agent_v3.story_e2e_cli ... \\
    --enable-real-api --i-approve-budget --phase8-paid-multi-round \\
    --first-live-evidence-dir /path/to/evidence_store

Never sends paid HTTP unless --enable-real-api AND --i-approve-budget AND
STORY_API_ENABLE=1 (provider layer).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Tuple

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
                   help="Events JSON (prefer V3-R events_enriched.json for Search)")
    p.add_argument("--causal-atoms-json", type=Path, default=None,
                   help="Human causal atoms for fresh V3-R")
    p.add_argument("--match-id", type=str, default=None)
    p.add_argument("--algo-root", type=Path, default=None)
    p.add_argument("--run-fresh-v3r", action="store_true", default=False,
                   help="Generate Phase5 from events+causal+video (not JSON alone)")
    # IMPORTANT: default=False so --enable-real-api can actually leave offline mode.
    # Without --enable-real-api, resolve_cli_mode still forces skip_vlm=True.
    p.add_argument(
        "--offline",
        action="store_true",
        default=False,
        help="Force offline / skip VLM (implied when --enable-real-api is absent)",
    )
    p.add_argument("--enable-real-api", action="store_true", default=False)
    p.add_argument("--i-approve-budget", action="store_true", default=False)
    p.add_argument(
        "--enable-native-broadcast-observation",
        action="store_true", default=False,
        help=(
            "Extra explicit paid opt-in: send one native source MP4 context plus "
            "source-PTS anchors to shared real VLM; observation ONLY, not FIRST_LIVE"
        ),
    )
    p.add_argument(
        "--phase8-paid-multi-round",
        action="store_true",
        default=False,
        help="Explicit opt-in for max_rounds>1 with real API (default off)",
    )
    p.add_argument(
        "--first-live-evidence-dir",
        type=Path,
        default=None,
        help="Directory/JSON of validated first-LIVE evidence packs (source SHA+PTS)",
    )
    p.add_argument(
        "--narrative-fit-evidence-dir",
        type=Path,
        default=None,
        help="Optional validated before/candidate/after video-triplet review store JSON/dir",
    )
    p.add_argument(
        "--goal-repair-evidence-dir",
        type=Path,
        default=None,
        help=(
            "Optional independently reviewed missing-goal SOURCE-video evidence "
            "(one <goal_coverage_issue_id>.json per issue); no Gold EDL."
        ),
    )
    p.add_argument(
        "--build-local-first-live-evidence",
        action="store_true",
        default=False,
        help="Zero-HTTP: build local frame-binding packs for new EDL windows",
    )
    p.add_argument("--force-render-initial", action="store_true", default=False)
    p.add_argument("--force-render-candidate", action="store_true", default=False)
    p.add_argument(
        "--phase10-explore", action="store_true", default=False,
        help="Opt in to ONE isolated exploratory fullcut pair; never promote BEST",
    )
    p.add_argument(
        "--phase10-explore-fixture", type=Path, default=None,
        help="Offline development-only hypothesis JSON; incompatible with real API",
    )
    p.add_argument("--no-smoke-render", action="store_true", default=False)
    p.add_argument("--max-rounds", type=int, default=3)
    p.add_argument("--max-calls", type=int, default=5)
    p.add_argument("--max-cost-usd", type=float, default=0.10)
    p.add_argument("--fixture-revision", type=Path, default=None)
    p.add_argument("--fixture-verifier", type=Path, default=None)
    return p


def resolve_cli_mode(args: argparse.Namespace) -> Tuple[bool, bool, Dict[str, Any]]:
    """Resolve offline vs real-API mode.

    Rules:
    - --enable-real-api implies not offline (skip_vlm=False), even if --offline
      was also passed (emit conflict note; real-api wins for paid path wiring).
    - Without --enable-real-api, skip_vlm=True (safe default / offline).
    """
    enable_real = bool(args.enable_real_api)
    offline_flag = bool(args.offline)
    notes: Dict[str, Any] = {
        "offline_flag": offline_flag,
        "enable_real_api": enable_real,
    }
    if enable_real and offline_flag:
        notes["conflict"] = "enable_real_api_overrides_offline_flag"
        offline_effective = False
    elif enable_real:
        offline_effective = False
    else:
        offline_effective = True
    skip_vlm = bool(offline_effective) or (not enable_real)
    # When real API is requested, skip_vlm must be False so VLM path is live.
    if enable_real:
        skip_vlm = False
    notes["offline_effective"] = offline_effective
    notes["skip_vlm"] = skip_vlm
    return skip_vlm, enable_real, notes


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.match_json.is_file():
        print(f"ERROR: match json not found: {args.match_json}", file=sys.stderr)
        return 2
    if not args.source_mp4.is_file():
        print(f"ERROR: source mp4 not found: {args.source_mp4}", file=sys.stderr)
        return 2
    if args.enable_native_broadcast_observation and not (
        args.enable_real_api and args.i_approve_budget
    ):
        print(
            "ERROR: native broadcast observation needs --enable-real-api "
            "AND --i-approve-budget",
            file=sys.stderr,
        )
        return 2
    if args.phase10_explore_fixture is not None:
        if not args.phase10_explore:
            print("ERROR: --phase10-explore-fixture requires --phase10-explore", file=sys.stderr)
            return 2
        if args.enable_real_api:
            print("ERROR: exploratory fixture cannot be combined with real API", file=sys.stderr)
            return 2
        if not args.phase10_explore_fixture.is_file():
            print("ERROR: exploratory fixture JSON missing", file=sys.stderr)
            return 2
    if args.first_live_evidence_dir is not None and not (
        args.first_live_evidence_dir.is_dir() or args.first_live_evidence_dir.is_file()
    ):
        print(
            f"ERROR: first-live evidence path missing: {args.first_live_evidence_dir}",
            file=sys.stderr,
        )
        return 2

    if args.narrative_fit_evidence_dir is not None and not (
        args.narrative_fit_evidence_dir.is_dir() or args.narrative_fit_evidence_dir.is_file()
    ):
        print(
            f"ERROR: narrative-fit review path missing: {args.narrative_fit_evidence_dir}",
            file=sys.stderr,
        )
        return 2

    if args.goal_repair_evidence_dir is not None and not args.goal_repair_evidence_dir.is_dir():
        print(
            "ERROR: --goal-repair-evidence-dir must be an existing directory",
            file=sys.stderr,
        )
        return 2

    fixture_revision = None
    fixture_verifier = None
    phase10_explore_fixture = None
    if args.phase10_explore_fixture:
        try:
            phase10_explore_fixture = json.loads(
                args.phase10_explore_fixture.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            print(f"ERROR: invalid exploratory fixture: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            return 2
        if not isinstance(phase10_explore_fixture, dict):
            print("ERROR: exploratory fixture must be a JSON object", file=sys.stderr)
            return 2
    if args.fixture_revision and args.fixture_revision.is_file():
        fixture_revision = json.loads(args.fixture_revision.read_text(encoding="utf-8"))
    if args.fixture_verifier and args.fixture_verifier.is_file():
        fixture_verifier = json.loads(args.fixture_verifier.read_text(encoding="utf-8"))

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    skip_vlm, enable_real, mode_notes = resolve_cli_mode(args)
    (out_dir / "cli_mode_resolution.json").write_text(
        json.dumps(mode_notes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

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
        skip_vlm=bool(skip_vlm),
        enable_real_api=bool(enable_real),
        i_approve_budget=bool(args.i_approve_budget),
        enable_native_broadcast_observation=bool(
            args.enable_native_broadcast_observation
        ),
        force_render_initial=bool(args.force_render_initial),
        force_render_candidate=bool(args.force_render_candidate),
        phase10_explore=bool(args.phase10_explore),
        phase10_explore_fixture=phase10_explore_fixture,
        smoke_render=not bool(args.no_smoke_render),
        fixture_revision=fixture_revision,
        fixture_verifier=fixture_verifier,
        first_live_evidence_dir=(
            args.first_live_evidence_dir.resolve() if args.first_live_evidence_dir else None
        ),
        narrative_fit_evidence_dir=(
            args.narrative_fit_evidence_dir.resolve()
            if args.narrative_fit_evidence_dir else None
        ),
        goal_repair_evidence_dir=(
            args.goal_repair_evidence_dir.resolve() if args.goal_repair_evidence_dir else None
        ),
        build_local_first_live_evidence=bool(args.build_local_first_live_evidence),
        max_rounds=int(args.max_rounds),
        max_calls=int(args.max_calls),
        max_cost_usd=float(args.max_cost_usd),
        max_retries=0,
        phase8_paid_multi_round=bool(args.phase8_paid_multi_round),
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
                "cli_mode": mode_notes,
                "phase8_paid_multi_round": bool(args.phase8_paid_multi_round),
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
