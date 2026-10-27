"""CLI：dry-run 或 media-only（本地 FFmpeg 抽帧，无 VLM）。

在 algo 目录执行：

  python -m story_video_agent --story-json ../reports/story_t01/...json --dry-run
  python -m story_video_agent --story-json ... --media-only --video-path /path/to.mp4
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from story_video_agent.runner import run_story_json


def main() -> None:
    parser = argparse.ArgumentParser(description="T01 Story Video Agent Phase 2A")
    parser.add_argument("--story-json", type=Path, required=True, help="T01 故事链 JSON")
    parser.add_argument("--video-path", type=str, default="", help="本地视频路径")
    parser.add_argument("--duration-sec", type=float, default=None)
    parser.add_argument("--max-steps", type=int, default=24)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="纯规划 stub（默认）")
    mode.add_argument("--media-only", action="store_true", help="仅本地抽帧，不验证")
    parser.add_argument("--frame-budget", type=int, default=24)
    parser.add_argument("--frame-dir", type=Path, default=None)
    parser.add_argument("--manifest-out", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    dry_run = not args.media_only
    result = run_story_json(
        str(args.story_json),
        video_path=args.video_path or None,
        duration_sec=args.duration_sec,
        max_steps=args.max_steps,
        dry_run=dry_run,
        media_only=bool(args.media_only),
        frame_budget=args.frame_budget,
        frame_dir=str(args.frame_dir) if args.frame_dir else None,
        manifest_path=str(args.manifest_out) if args.manifest_out else None,
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
        "tier",
        result.get("story_tier"),
        "tasks",
        len(result.get("evidence_tasks") or []),
        "frames",
        diag.get("frame_count"),
        "elapsed",
        diag.get("elapsed_sec"),
        "structure_ok",
        result.get("structure_ok"),
        "verification_complete",
        result.get("verification_complete"),
    )


if __name__ == "__main__":
    main()
