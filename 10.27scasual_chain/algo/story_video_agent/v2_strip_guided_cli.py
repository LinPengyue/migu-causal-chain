"""Strip-Guided CLI — MP4 + events.json + predicted strips (or generate via chain6)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from story_video_agent.api_provider import (
    ApiConfigError,
    ApiProvider,
    api_enabled,
    load_endpoint_configs,
    smoke_enabled,
)
from story_video_agent.v2_event_adapter import INPUT_SOURCES
from story_video_agent.v2_strip_guided_runner import run_strip_guided


def _git_sha() -> str:
    here = Path(__file__).resolve().parent
    for root in [here, *here.parents]:
        if (root / ".git").exists():
            try:
                return subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=str(root), text=True, stderr=subprocess.DEVNULL
                ).strip()
            except Exception:  # noqa: BLE001
                break
    return "unknown"


def _make_api(*, real: bool, max_calls: int, max_cost: float, max_completion_tokens: int) -> ApiProvider:
    if real:
        if not api_enabled():
            raise ApiConfigError("STORY_API_ENABLE=1 required")
        if not smoke_enabled():
            raise ApiConfigError("STORY_API_SMOKE=1 required")
        configs = load_endpoint_configs()
        for role in ("planner", "vision"):
            if not configs[role].configured():
                raise ApiConfigError(f"{role} incomplete")
        return ApiProvider(
            configs=configs,
            require_real=True,
            force_mock=False,
            max_calls=max_calls,
            max_cost_usd=max_cost,
            max_completion_tokens=max_completion_tokens,
        )
    return ApiProvider(
        force_mock=True,
        require_real=False,
        max_calls=max_calls,
        max_cost_usd=max_cost,
        max_completion_tokens=max_completion_tokens,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="V2 Strip-Guided Story Agent Round 1")
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--events", type=Path, required=True)
    p.add_argument("--strip-json", type=Path, required=True, help="8.31 predicted strip.json")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--input-source", choices=list(INPUT_SOURCES), default="human_corrected")
    p.add_argument("--real", action="store_true")
    p.add_argument("--max-steps", type=int, default=14)
    p.add_argument("--frame-budget", type=int, default=48)
    p.add_argument("--max-api-calls", type=int, default=24)
    p.add_argument("--max-cost-usd", type=float, default=1.5)
    p.add_argument("--max-completion-tokens", type=int, default=8192)
    p.add_argument("--no-llm-planner", action="store_true")
    p.add_argument("--no-export-clips", action="store_true")
    p.add_argument(
        "--offline-goal-centers",
        type=str,
        default="",
        help="comma-separated seconds for offline coverage only (never agent input)",
    )
    args = p.parse_args(argv)

    if not args.video.is_file() or not args.events.is_file() or not args.strip_json.is_file():
        print("missing video/events/strip-json", file=sys.stderr)
        return 2
    if "causal" in args.events.name.lower() or "gold" in args.strip_json.name.lower():
        print("REFUSE: do not pass causal/gold as primary inputs", file=sys.stderr)
        return 2

    os.environ.setdefault("STORY_PLANNER_REQUEST_PROFILE", "video_rsi")
    os.environ.setdefault("STORY_VLM_REQUEST_PROFILE", "video_rsi")

    centers = [float(x) for x in args.offline_goal_centers.split(",") if x.strip()] or None

    try:
        api = _make_api(
            real=args.real,
            max_calls=args.max_api_calls,
            max_cost=args.max_cost_usd,
            max_completion_tokens=args.max_completion_tokens,
        )
        result = run_strip_guided(
            video=args.video,
            events_path=args.events,
            strip_path=args.strip_json,
            out_dir=args.out_dir,
            api=api,
            input_source=args.input_source,
            max_steps=args.max_steps,
            frame_budget=args.frame_budget,
            use_llm_planner=not args.no_llm_planner,
            export_review_clips=not args.no_export_clips,
            weak_goal_centers_offline=centers,
        )
    except ApiConfigError as exc:
        print(f"CONFIG: {exc}", file=sys.stderr)
        return 3

    report = {
        "schema": "v2_strip_guided_cli_report_v1",
        "commit_sha": _git_sha(),
        "mode": "strip_guided",
        "story_mode": "strip_guided",
        "video": str(args.video),
        "events": str(args.events),
        "strip_json": str(args.strip_json),
        "input_source": args.input_source,
        "out_dir": str(args.out_dir),
        "real": bool(args.real),
        "discovery_status": (result.get("story_candidates") or {}).get("discovery_status"),
        "n_predicted_strips": (result.get("strip_bundle_meta") or {}).get("n_adapted"),
        "category_counts": (result.get("strip_bundle_meta") or {}).get("category_counts"),
        "n_verified_strips": (result.get("story_candidates") or {}).get("n_verified_strips"),
        "n_localized_clips": len((result.get("localized_story_clips") or {}).get("clips") or []),
        "n_relations": len((result.get("story_relations") or {}).get("relations") or []),
        "offline_coverage": result.get("offline_coverage"),
        "elapsed_sec": (result.get("story_agent_trace") or {}).get("elapsed_sec"),
        "frames_used": (result.get("story_agent_trace") or {}).get("frames_used"),
        "api_stats": (result.get("story_agent_trace") or {}).get("api_stats"),
        "render_ready": False,
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "cli_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
