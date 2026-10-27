"""CLI：dry-run / media-only / perception。

  python -m story_video_agent --story-json ... --dry-run
  python -m story_video_agent --story-json ... --media-only --video-path ...
  python -m story_video_agent --story-json ... --perception --video-path ... --france-focus
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from story_video_agent.runner import run_story_json


def main() -> None:
    parser = argparse.ArgumentParser(description="T01 Story Video Agent Phase 2B")
    parser.add_argument("--story-json", type=Path, required=True)
    parser.add_argument("--video-path", type=str, default="")
    parser.add_argument("--duration-sec", type=float, default=None)
    parser.add_argument("--max-steps", type=int, default=32)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--media-only", action="store_true")
    mode.add_argument("--perception", action="store_true")
    parser.add_argument("--frame-budget", type=int, default=24)
    parser.add_argument("--frame-dir", type=Path, default=None)
    parser.add_argument("--manifest-out", type=Path, default=None)
    parser.add_argument("--france-focus", action="store_true")
    parser.add_argument("--croatia-setup-focus", action="store_true")
    parser.add_argument("--force-mock-vlm", action="store_true")
    parser.add_argument("--require-real-api", action="store_true")
    parser.add_argument("--use-llm-planner", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    if args.perception:
        dry_run, media_only, perception = False, False, True
    elif args.media_only:
        dry_run, media_only, perception = False, True, False
    else:
        dry_run, media_only, perception = True, False, False

    focus = None
    if args.croatia_setup_focus:
        focus = ["missing_setup_visual"]

    result = run_story_json(
        str(args.story_json),
        video_path=args.video_path or None,
        duration_sec=args.duration_sec,
        max_steps=args.max_steps,
        dry_run=dry_run,
        media_only=media_only,
        perception=perception,
        frame_budget=args.frame_budget,
        frame_dir=str(args.frame_dir) if args.frame_dir else None,
        manifest_path=str(args.manifest_out) if args.manifest_out else None,
        france_focus=bool(args.france_focus),
        focus_gap_ids=focus,
        force_mock_vlm=bool(args.force_mock_vlm),
        use_llm_planner=True if args.use_llm_planner else None,
        require_real_api=bool(args.require_real_api),
    )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(args.out)
    diag = result.get("diagnostics") or {}
    print(
        "status",
        result["status"],
        "tasks",
        len(result.get("evidence_tasks") or []),
        "frames",
        diag.get("frame_count"),
        "observed",
        diag.get("observed_count"),
        "vlm_calls",
        (diag.get("vision") or {}).get("calls"),
        "elapsed",
        diag.get("elapsed_sec"),
        "verification_complete",
        result.get("verification_complete"),
        "structure_ok",
        result.get("structure_ok"),
    )


if __name__ == "__main__":
    main()
