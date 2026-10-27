"""Dry-run CLI。

在 algo 目录执行：

  python -m story_video_agent --story-json ../reports/story_t01/2022年11月23日\\ 法国vs澳大利亚.json --dry-run
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from story_video_agent.runner import run_story_json


def main() -> None:
    parser = argparse.ArgumentParser(description="T01 Story Video Agent dry-run")
    parser.add_argument("--story-json", type=Path, required=True, help="T01 故事链 JSON")
    parser.add_argument("--video-path", type=str, default="", help="可选视频路径（仅写入元数据）")
    parser.add_argument("--duration-sec", type=float, default=None)
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    result = run_story_json(
        str(args.story_json),
        video_path=args.video_path or None,
        duration_sec=args.duration_sec,
        max_steps=args.max_steps,
        dry_run=True,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(args.out)
    print(
        "status",
        result["status"],
        "tier",
        result.get("story_tier"),
        "tasks",
        len(result.get("evidence_tasks") or []),
        "structure_ok",
        result.get("structure_ok"),
    )


if __name__ == "__main__":
    main()
