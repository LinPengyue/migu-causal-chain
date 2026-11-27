"""B1 human-assisted historical-goal repair: run the EXISTING V3-A loop.

This is an experiment launcher, not a new goal detector or an authorization bypass.
An attestation alone never satisfies the source-bound first-live validator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Sequence

from .story_e2e_agent import StoryE2EInputs, run_story_e2e


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--match-json", required=True, type=Path)
    p.add_argument("--source-mp4", required=True, type=Path)
    p.add_argument("--baseline-edl", required=True, type=Path)
    p.add_argument("--story-plan", type=Path)
    p.add_argument("--initial-story-mp4", type=Path)
    p.add_argument("--events-json", type=Path)
    p.add_argument("--goal-repair-evidence-dir", type=Path)
    p.add_argument("--human-first-live-attestation", type=Path,
                   help="Existing human confirmation; preview only, never autonomous")
    p.add_argument("--preview-media-in", type=float,
                   help="Proposed candidate window start, NOT a human-approved cut")
    p.add_argument("--preview-media-out", type=float,
                   help="Proposed candidate window end, NOT a human-approved cut")
    p.add_argument("--first-live-evidence-dir", type=Path)
    p.add_argument("--narrative-fit-evidence-dir", type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--max-rounds", type=int, default=1)
    return p


def preflight(args: argparse.Namespace) -> dict:
    required = [args.match_json, args.source_mp4, args.baseline_edl]
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        raise ValueError("Missing inputs: " + ", ".join(missing))
    preview = getattr(args, "human_first_live_attestation", None)
    review_dir = args.goal_repair_evidence_dir
    if review_dir is not None and not review_dir.is_dir():
        raise ValueError("Missing independent goal-review directory")
    reviews = sorted(review_dir.glob("*.json")) if review_dir else []
    if preview is None and not reviews:
        raise ValueError("No goal-review JSON; a human statement alone is insufficient")
    if preview is not None:
        if not Path(preview).is_file():
            raise ValueError("Human attestation file missing")
        if getattr(args, "preview_media_in", None) is None or getattr(args, "preview_media_out", None) is None:
            raise ValueError("Human preview requires explicit candidate window in/out")
        if args.max_rounds != 1:
            raise ValueError("Human preview must run exactly one round")
    if args.first_live_evidence_dir and not args.first_live_evidence_dir.exists():
        raise ValueError("Missing first-live evidence store")
    if args.narrative_fit_evidence_dir and not args.narrative_fit_evidence_dir.exists():
        raise ValueError("Missing narrative-fit evidence store")
    if not 1 <= args.max_rounds <= 3:
        raise ValueError("max-rounds must be 1..3")
    baseline = json.loads(args.baseline_edl.read_text(encoding="utf-8"))
    from .story_timeline import edl_rows
    rows = edl_rows(baseline)
    if not rows:
        raise ValueError("Baseline EDL has no segments")
    return {
        "schema": "v3a_b1_human_assisted_preflight_v1",
        "mode": "HUMAN_ASSISTED_DEV_NOT_AUTONOMOUS_NOT_BENCHMARK",
        "source_sha256": _sha(args.source_mp4),
        "baseline_edl_sha256": _sha(args.baseline_edl),
        "baseline_segment_count": len(rows),
        "review_files": [{"path": str(p), "sha256": _sha(p)} for p in reviews],
        "human_attestation_sha256": _sha(preview) if preview else None,
        "preview_window_proposed_not_human_approved": (
            [args.preview_media_in, args.preview_media_out] if preview else None
        ),
        "paid_http_authorized": False,
        "release_authorized": False,
        "note": "The existing source-frame and FIRST_LIVE validators decide whether any repair is legal.",
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    record = preflight(args)
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "b1_preflight.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    inp = StoryE2EInputs(
        match_json=args.match_json.resolve(),
        source_mp4=args.source_mp4.resolve(),
        out_dir=out,
        baseline_edl=args.baseline_edl.resolve(),
        story_plan=args.story_plan.resolve() if args.story_plan else None,
        initial_story_mp4=args.initial_story_mp4.resolve() if args.initial_story_mp4 else None,
        events_json=args.events_json.resolve() if args.events_json else None,
        goal_repair_evidence_dir=(
            args.goal_repair_evidence_dir.resolve() if args.goal_repair_evidence_dir else None
        ),
        human_assisted_first_live_attestation=(
            args.human_first_live_attestation.resolve()
            if args.human_first_live_attestation else None
        ),
        human_preview_media_in=args.preview_media_in,
        human_preview_media_out=args.preview_media_out,
        first_live_evidence_dir=args.first_live_evidence_dir.resolve() if args.first_live_evidence_dir else None,
        narrative_fit_evidence_dir=args.narrative_fit_evidence_dir.resolve() if args.narrative_fit_evidence_dir else None,
        enable_real_api=False,
        i_approve_budget=False,
        skip_vlm=True,
        run_fresh_v3r=False,
        max_rounds=args.max_rounds,
        force_render_candidate=True,
    )
    result = run_story_e2e(inp)
    (out / "b1_runner_result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    # Execution success is NOT an EDL-repair, quality, or release PASS.
    # Review the rendered candidate manually before accepting any clip boundaries.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
