"""CLI: video-only P1+P2 — MP4 → score_timeline + T01 discovery + evidence tasks.

Never reads events.json / causal.json. No paid API. render_ready stays false.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Video-driven P1+P2 (score index + T01 discovery)")
    parser.add_argument("--video", type=str, default="", help="Full match MP4")
    parser.add_argument("--out-dir", type=str, required=True, help="Output directory")
    parser.add_argument("--coarse-step", type=float, default=45.0)
    parser.add_argument("--max-coarse-frames", type=int, default=80)
    parser.add_argument("--max-dense-extra", type=int, default=40)
    parser.add_argument("--confirm-hits", type=int, default=2)
    parser.add_argument(
        "--timeline-json",
        type=str,
        default="",
        help="Skip video OCR; load existing score_timeline.json (tests / resume)",
    )
    parser.add_argument("--synthetic-obs", type=str, default="", help="JSON list of OCR observations")
    args = parser.parse_args(argv)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # Hard gate: refuse if caller tries to pass events/causal paths via env leftovers
    for forbidden in ("EVENTS_JSON", "CAUSAL_JSON", "DELIVERY_JSON"):
        import os

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
        timeline = build_index_from_synthetic_observations(obs)
        (out / "score_timeline.json").write_text(
            json.dumps(timeline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        index = {"schema": "synthetic", "score_timeline": timeline, "elapsed_sec": 0}
    elif args.timeline_json:
        timeline = json.loads(Path(args.timeline_json).read_text(encoding="utf-8"))
        index = {"score_timeline": timeline, "elapsed_sec": 0}
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
        )
        timeline = index["score_timeline"]

    result = discover_and_write(timeline, out, teams_hypothesis=(index.get("teams_hypothesis")))
    report = {
        "schema": "video_driven_p1p2_run_report_v1",
        "out_dir": str(out),
        "video": args.video or None,
        "elapsed_sec": round(time.time() - t0, 3),
        "p1_elapsed_sec": index.get("elapsed_sec"),
        "degraded": bool(timeline.get("degraded")),
        "n_score_nodes": len(timeline.get("nodes") or []),
        "discovery_grade": result["discovery"]["grade"],
        "n_evidence_tasks": len(result["evidence_tasks"]["tasks"]),
        "semantic_verified": False,
        "render_ready": False,
        "gates": {
            "no_events_json": True,
            "no_causal_json": True,
            "no_paid_api": True,
        },
    }
    (out / "p1p2_run_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
