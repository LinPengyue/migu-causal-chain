"""真实 API 最小 smoke 入口（默认不执行计费请求）。

显式开启：
  STORY_API_ENABLE=1 STORY_API_SMOKE=1 \\
  STORY_LLM_BASE_URL=... STORY_LLM_API_KEY=... STORY_LLM_MODEL=... \\
  STORY_VLM_MODEL=... STORY_API_MAX_CALLS=3 STORY_API_MAX_COST_USD=0.05 \\
  python -m story_video_agent.smoke_api --video-path /path/to.mp4

未配置密钥或未开开关时立即退出，不发起网络请求。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from story_video_agent.api_provider import ApiConfigError, api_enabled, smoke_enabled
from story_video_agent.runner import run_story_json
from story_video_agent.state import FRANCE_PERCEPTION_FOCUS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Story Video Agent real-API smoke (explicit only)")
    parser.add_argument("--story-json", type=Path, required=True)
    parser.add_argument("--video-path", type=str, required=True)
    parser.add_argument("--france-focus", action="store_true", default=True)
    parser.add_argument("--croatia-setup-focus", action="store_true")
    parser.add_argument("--frame-budget", type=int, default=6)
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    if not smoke_enabled():
        print("REFUSE: set STORY_API_SMOKE=1 to run billed smoke", file=sys.stderr)
        return 2
    if not api_enabled():
        print("REFUSE: set STORY_API_ENABLE=1", file=sys.stderr)
        return 2

    focus = None
    if args.croatia_setup_focus:
        focus = ["missing_setup_visual"]
    elif args.france_focus:
        focus = list(FRANCE_PERCEPTION_FOCUS)

    try:
        result = run_story_json(
            str(args.story_json),
            video_path=args.video_path,
            dry_run=False,
            perception=True,
            force_mock_vlm=False,
            require_real_api=True,
            use_llm_planner=True,
            focus_gap_ids=focus,
            frame_budget=args.frame_budget,
            max_steps=args.max_steps,
            frame_dir=str(Path("reports") / "story_video_agent_frames_smoke"),
            manifest_path=str(Path("reports") / "story_video_agent_smoke_manifest.json"),
        )
    except ApiConfigError as exc:
        print(f"REFUSE config: {exc}", file=sys.stderr)
        return 3

    text = json.dumps(
        {
            "status": result.get("status"),
            "verification_complete": result.get("verification_complete"),
            "diagnostics": result.get("diagnostics"),
            "evidence_tasks": [
                {
                    "gap_id": t.get("gap_id"),
                    "status": t.get("status"),
                    "provider_mode": (t.get("visual_evidence") or {}).get("provider_mode"),
                    "frame_ids": (t.get("visual_evidence") or {}).get("frame_ids"),
                    "normalized_ok": (t.get("visual_evidence") or {}).get("normalized_ok"),
                }
                for t in result.get("evidence_tasks") or []
            ],
            "memory_raw_vlm": (result.get("memory") or {}).get("raw_vlm_responses"),
            "planner_modes": (result.get("diagnostics") or {}).get("planner_modes"),
        },
        ensure_ascii=False,
        indent=2,
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(args.out)
    else:
        print(text)
    return 0 if result.get("structure_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
