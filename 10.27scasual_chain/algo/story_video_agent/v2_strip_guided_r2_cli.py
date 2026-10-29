"""Strip-Guided Round 2 CLI — missing-goal recovery + enhanced strip A/B."""

from __future__ import annotations

import argparse
import json
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
from story_video_agent.v2_goal_recovery_runner import run_goal_recovery

DEFAULT_ALGO = Path("/data2/lpy1/causal-chain2/8.31causal_chain")


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
    p = argparse.ArgumentParser(description="V2 Strip-Guided Round 2 — goal recovery")
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--events", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--strip-a", type=Path, default=None, help="Existing original strip.json (A)")
    p.add_argument("--algo-root", type=Path, default=DEFAULT_ALGO)
    p.add_argument("--input-source", choices=list(INPUT_SOURCES), default="human_corrected")
    p.add_argument("--real", action="store_true")
    p.add_argument("--skip-video", action="store_true", help="Detector+strip only (no VLM)")
    p.add_argument("--max-steps", type=int, default=16)
    p.add_argument("--frame-budget", type=int, default=56)
    p.add_argument("--max-api-calls", type=int, default=28)
    p.add_argument("--max-cost-usd", type=float, default=1.5)
    p.add_argument("--max-completion-tokens", type=int, default=8192)
    p.add_argument("--no-llm-planner", action="store_true")
    args = p.parse_args(argv)

    if not args.algo_root.is_dir():
        print(f"algo-root missing: {args.algo_root}", file=sys.stderr)
        return 2

    api = _make_api(
        real=bool(args.real),
        max_calls=args.max_api_calls,
        max_cost=args.max_cost_usd,
        max_completion_tokens=args.max_completion_tokens,
    )
    report = run_goal_recovery(
        video=args.video,
        events_path=args.events,
        out_dir=args.out_dir,
        api=api,
        algo_root=args.algo_root,
        strip_a_path=args.strip_a,
        input_source=args.input_source,
        max_steps=args.max_steps,
        frame_budget=args.frame_budget,
        use_llm_planner=not args.no_llm_planner,
        skip_video=bool(args.skip_video),
    )
    report["git_sha"] = _git_sha()
    report["cli"] = "v2_strip_guided_r2_cli"
    (Path(args.out_dir) / "cli_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: report[k] for k in (
        "match_id",
        "n_missing_goal_candidates",
        "n_inferred_verified_goals",
        "strip_A_chains",
        "strip_B_chains",
        "discovery_status",
        "stop_reason",
        "elapsed_sec",
        "git_sha",
        "render_ready",
    ) if k in report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
