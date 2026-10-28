"""CLI: video-only P1+P2 — MP4 → score_timeline + T01 discovery + evidence tasks."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def _git_sha() -> str:
    here = Path(__file__).resolve().parent
    for root in [here, *here.parents]:
        if (root / ".git").exists():
            try:
                return subprocess.check_output(
                    ["git", "rev-parse", "HEAD"],
                    cwd=str(root),
                    stderr=subprocess.DEVNULL,
                    text=True,
                ).strip()
            except Exception:  # noqa: BLE001
                break
    return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Video-driven P1+P2 (score index + T01 discovery)")
    parser.add_argument("--video", type=str, default="", help="Full match MP4")
    parser.add_argument("--out-dir", type=str, required=True, help="Output directory")
    parser.add_argument("--coarse-step", type=float, default=45.0)
    parser.add_argument("--max-coarse-frames", type=int, default=80)
    parser.add_argument("--max-dense-extra", type=int, default=40)
    parser.add_argument("--confirm-hits", type=int, default=3)
    parser.add_argument("--establish-hits", type=int, default=3)
    parser.add_argument("--frame-width", type=int, default=0, help="0=native resolution")
    parser.add_argument("--save-roi-evidence", action="store_true", default=True)
    parser.add_argument("--no-roi-evidence", action="store_true")
    parser.add_argument("--timeline-json", type=str, default="")
    parser.add_argument("--synthetic-obs", type=str, default="")
    args = parser.parse_args(argv)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    sha = _git_sha()

    for forbidden in ("EVENTS_JSON", "CAUSAL_JSON", "DELIVERY_JSON"):
        if os.environ.get(forbidden):
            print(f"REFUSE: unset {forbidden}; video-only path must not use delivery JSON", file=sys.stderr)
            return 2

    from story_video_agent.global_video_index import (
        build_global_video_index,
        build_index_from_synthetic_observations,
    )
    from story_video_agent.story_discovery_video import discover_and_write

    if args.synthetic_obs:
        obs = json.loads(Path(args.synthetic_obs).read_text(encoding="utf-8"))
        timeline = build_index_from_synthetic_observations(
            obs, confirm_hits=args.confirm_hits, establish_hits=max(2, args.establish_hits - 1)
        )
        (out / "score_timeline.json").write_text(
            json.dumps(timeline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        index = {"schema": "synthetic", "score_timeline": timeline, "elapsed_sec": 0, "commit_sha": sha}
    elif args.timeline_json:
        timeline = json.loads(Path(args.timeline_json).read_text(encoding="utf-8"))
        index = {"score_timeline": timeline, "elapsed_sec": 0, "commit_sha": sha}
    else:
        if not args.video:
            print("--video required unless --timeline-json / --synthetic-obs", file=sys.stderr)
            return 2
        index = build_global_video_index(
            args.video,
            out_dir=out,
            coarse_step_sec=args.coarse_step,
            max_coarse_frames=args.max_coarse_frames,
            max_dense_extra=args.max_dense_extra,
            confirm_hits=args.confirm_hits,
            establish_hits=args.establish_hits,
            frame_width=args.frame_width,
            save_roi_evidence=not args.no_roi_evidence,
            commit_sha=sha,
        )
        timeline = index["score_timeline"]

    result = discover_and_write(timeline, out, teams_hypothesis=index.get("teams_hypothesis"))
    report = {
        "schema": "video_driven_p1p2_run_report_v2",
        "commit_sha": sha,
        "out_dir": str(out),
        "video": args.video or None,
        "params": {
            "coarse_step": args.coarse_step,
            "max_coarse_frames": args.max_coarse_frames,
            "max_dense_extra": args.max_dense_extra,
            "confirm_hits": args.confirm_hits,
            "establish_hits": args.establish_hits,
            "frame_width": args.frame_width,
        },
        "elapsed_sec": round(time.time() - t0, 3),
        "p1_elapsed_sec": index.get("elapsed_sec"),
        "degraded": bool(timeline.get("degraded")),
        "degrade_reasons": timeline.get("degrade_reasons"),
        "n_score_nodes": len(timeline.get("nodes") or []),
        "discovery_grade": result["discovery"]["grade"],
        "n_evidence_tasks": len(result["evidence_tasks"]["tasks"]),
        "perception_quality": timeline.get("perception_quality") or index.get("perception_quality"),
        "sampling_coverage": timeline.get("sampling_coverage"),
        "semantic_verified": False,
        "render_ready": False,
        "gates": {"no_events_json": True, "no_causal_json": True, "no_paid_api": True},
    }
    (out / "p1p2_run_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
