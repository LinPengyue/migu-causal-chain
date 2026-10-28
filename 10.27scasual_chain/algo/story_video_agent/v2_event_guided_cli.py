"""Event-Guided CLI — MP4 + events.json story discovery (preserves A/B/C-1)."""

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
from story_video_agent.v2_event_guided_runner import run_event_guided


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
    p = argparse.ArgumentParser(
        description="V2 Event-Guided Multimodal Story Agent (MP4 + events.json)"
    )
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--events", type=Path, required=True, help="events.json (no causal.json)")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument(
        "--input-source",
        choices=list(INPUT_SOURCES),
        default="human_corrected",
        help="human_corrected (dev) or upstream_detected (prod adapter tag)",
    )
    p.add_argument(
        "--gold-story-graph",
        type=Path,
        default=None,
        help="Offline action gold ONLY (never model input)",
    )
    p.add_argument(
        "--causal-offline",
        type=Path,
        default=None,
        help="causal.json for post-hoc relation report ONLY",
    )
    p.add_argument("--real", action="store_true")
    p.add_argument("--max-steps", type=int, default=12)
    p.add_argument("--frame-budget", type=int, default=48)
    p.add_argument("--max-api-calls", type=int, default=24)
    p.add_argument("--max-cost-usd", type=float, default=1.0)
    p.add_argument("--max-completion-tokens", type=int, default=8192)
    p.add_argument("--no-llm-planner", action="store_true")
    args = p.parse_args(argv)

    if not args.video.is_file():
        print(f"missing video {args.video}", file=sys.stderr)
        return 2
    if not args.events.is_file():
        print(f"missing events {args.events}", file=sys.stderr)
        return 2
    # Hard refuse if user passes causal as events
    name = args.events.name.lower()
    if "causal" in name:
        print("REFUSE: do not pass causal.json as --events", file=sys.stderr)
        return 2

    os.environ.setdefault("STORY_PLANNER_REQUEST_PROFILE", "video_rsi")
    os.environ.setdefault("STORY_VLM_REQUEST_PROFILE", "video_rsi")

    try:
        api = _make_api(
            real=args.real,
            max_calls=args.max_api_calls,
            max_cost=args.max_cost_usd,
            max_completion_tokens=args.max_completion_tokens,
        )
        result = run_event_guided(
            video=args.video,
            events_path=args.events,
            out_dir=args.out_dir,
            api=api,
            input_source=args.input_source,
            max_steps=args.max_steps,
            frame_budget=args.frame_budget,
            use_llm_planner=not args.no_llm_planner,
            gold_story_graph=args.gold_story_graph,
            causal_path_offline=args.causal_offline,
        )
    except ApiConfigError as exc:
        print(f"CONFIG: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    report = {
        "schema": "v2_event_guided_cli_report_v1",
        "commit_sha": _git_sha(),
        "mode": "event_guided",
        "video": str(args.video),
        "events": str(args.events),
        "input_source": args.input_source,
        "out_dir": str(args.out_dir),
        "real": bool(args.real),
        "mock": not bool(args.real),
        "discovery_status": (result.get("discovery") or {}).get("discovery_status"),
        "n_score_changes": (result.get("discovery") or {}).get("n_score_changes"),
        "grade_counts": (result.get("evidence") or {}).get("grade_counts"),
        "action_recall": ((result.get("offline_eval") or {}).get("action_eval") or {}).get(
            "recall"
        ),
        "elapsed_sec": (result.get("agent_trace") or {}).get("elapsed_sec"),
        "frames_used": (result.get("agent_trace") or {}).get("frames_used"),
        "api_stats": (result.get("agent_trace") or {}).get("api_stats"),
        "event_bundle_meta": result.get("event_bundle_meta"),
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
