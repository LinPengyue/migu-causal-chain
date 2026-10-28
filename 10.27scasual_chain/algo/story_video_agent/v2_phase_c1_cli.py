"""Phase C-1 CLI — goal action localization (budget-gated real API)."""

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
from story_video_agent.v2_phase_c1_runner import run_localization


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
    p = argparse.ArgumentParser(description="V2 Phase C-1 goal localization")
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--phase-b-dir", type=Path, default=None, help="Reuse Phase B path_* outputs")
    p.add_argument("--media-offset-sec", type=float, default=0.0)
    p.add_argument("--real", action="store_true")
    p.add_argument("--max-steps", type=int, default=8)
    p.add_argument("--frame-budget", type=int, default=40)
    p.add_argument("--max-api-calls", type=int, default=16)
    p.add_argument("--max-cost-usd", type=float, default=0.5)
    p.add_argument("--max-completion-tokens", type=int, default=8192)
    p.add_argument("--no-llm-planner", action="store_true")
    args = p.parse_args(argv)

    if not args.video.is_file():
        print(f"missing video {args.video}", file=sys.stderr)
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
        result = run_localization(
            video=args.video,
            out_dir=args.out_dir,
            api=api,
            phase_b_dir=args.phase_b_dir,
            max_steps=args.max_steps,
            frame_budget=args.frame_budget,
            use_llm_planner=not args.no_llm_planner,
            media_offset_sec=args.media_offset_sec,
        )
    except ApiConfigError as exc:
        print(f"CONFIG: {exc}", file=sys.stderr)
        return 3

    report = {
        "schema": "v2_phase_c1_cli_report_v1",
        "commit_sha": _git_sha(),
        "video": str(args.video),
        "out_dir": str(args.out_dir),
        "phase_b_dir": str(args.phase_b_dir) if args.phase_b_dir else None,
        "real": bool(args.real),
        "mock": not bool(args.real),
        "discovery_check": result.get("discovery_check"),
        "task_counts": (result.get("tasks") or {}).get("counts"),
        "n_localized_events": len(result.get("localized") or []),
        "elapsed_sec": (result.get("agent_trace") or {}).get("elapsed_sec"),
        "frames_used": (result.get("agent_trace") or {}).get("frames_used"),
        "api_stats": (result.get("agent_trace") or {}).get("api_stats"),
        "render_ready": False,
    }
    (args.out_dir / "phase_c1_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
