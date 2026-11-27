"""V2 Phase A CLI — dual-model story evidence prototype.

Default is MOCK (no billing). Real calls require:
  STORY_API_ENABLE=1 STORY_API_SMOKE=1  and --real
plus configured STORY_LLM_* / STORY_VLM_* (see phase4a playbook).
"""

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
from story_video_agent.v2_phase_a_runner import compare_paths, run_fixed_frame, run_multi_round


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


def _make_api(
    *, real: bool, max_calls: int, max_cost: float, max_completion_tokens: int
) -> ApiProvider:
    if real:
        if not api_enabled():
            raise ApiConfigError("STORY_API_ENABLE=1 required for --real")
        if not smoke_enabled():
            raise ApiConfigError("STORY_API_SMOKE=1 required for --real (explicit billed entry)")
        configs = load_endpoint_configs()
        for role in ("planner", "vision"):
            if not configs[role].configured():
                raise ApiConfigError(f"{role} endpoint incomplete (base/model/key)")
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
    p = argparse.ArgumentParser(description="V2 Phase A DeepSeek+Qwen story evidence prototype")
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument(
        "--mode",
        choices=("multi", "fixed", "compare"),
        default="compare",
        help="multi-round planner | fixed-frame | both",
    )
    p.add_argument("--real", action="store_true", help="Billable API (requires SMOKE+ENABLE)")
    p.add_argument("--max-steps", type=int, default=4)
    p.add_argument("--frame-budget", type=int, default=16)
    p.add_argument("--fixed-frames", type=int, default=8)
    p.add_argument("--max-api-calls", type=int, default=8)
    p.add_argument("--max-cost-usd", type=float, default=0.15)
    p.add_argument(
        "--max-completion-tokens",
        type=int,
        default=4096,
        help="Provider output token cap (raise for reasoning models)",
    )
    p.add_argument("--no-llm-planner", action="store_true", help="Rule-only planner (still uses VLM if real)")
    args = p.parse_args(argv)

    if not args.video.is_file():
        print(f"video missing: {args.video}", file=sys.stderr)
        return 2

    sha = _git_sha()
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    def factory() -> ApiProvider:
        return _make_api(
            real=args.real,
            max_calls=args.max_api_calls,
            max_cost=args.max_cost_usd,
            max_completion_tokens=args.max_completion_tokens,
        )

    try:
        if args.mode == "fixed":
            result = run_fixed_frame(
                video=args.video,
                out_dir=out / "path_a_fixed",
                api=factory(),
                frame_count=args.fixed_frames,
                frame_budget=args.fixed_frames,
            )
            summary = {"mode": "fixed", "result_dir": result["out_dir"]}
        elif args.mode == "multi":
            result = run_multi_round(
                video=args.video,
                out_dir=out / "path_b_multi",
                api=factory(),
                max_steps=args.max_steps,
                frame_budget=args.frame_budget,
                use_llm_planner=not args.no_llm_planner,
            )
            summary = {"mode": "multi", "result_dir": result["out_dir"]}
        else:
            summary = compare_paths(
                video=args.video,
                out_dir=out,
                api_factory=factory,
                max_steps=args.max_steps,
                frame_budget_multi=args.frame_budget,
                frame_count_fixed=args.fixed_frames,
                use_llm_planner=not args.no_llm_planner,
            )
    except ApiConfigError as exc:
        print(f"CONFIG: {exc}", file=sys.stderr)
        return 3

    report = {
        "schema": "v2_phase_a_cli_report_v1",
        "commit_sha": sha,
        "video": str(args.video),
        "out_dir": str(out),
        "real": bool(args.real),
        "mock": not bool(args.real),
        "mode": args.mode,
        "params": {
            "max_steps": args.max_steps,
            "frame_budget": args.frame_budget,
            "fixed_frames": args.fixed_frames,
            "max_api_calls": args.max_api_calls,
            "max_cost_usd": args.max_cost_usd,
            "max_completion_tokens": args.max_completion_tokens,
            "use_llm_planner": not args.no_llm_planner,
        },
        "summary": summary,
        "render_ready": False,
        "gates": {
            "no_events_json": True,
            "no_causal_json": True,
            "explicit_smoke_gate": True,
        },
    }
    (out / "phase_a_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
