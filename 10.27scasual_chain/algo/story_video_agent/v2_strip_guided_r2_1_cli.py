"""Strip-Guided Round 2.1 CLI — VLM preflight + single missing-goal recovery."""

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
from story_video_agent.v2_api_preflight import PreflightError, run_preflight
from story_video_agent.v2_event_adapter import INPUT_SOURCES
from story_video_agent.v2_goal_recovery_runner import run_goal_recovery

DEFAULT_ALGO = Path("/data2/lpy1/causal-chain2/8.31causal_chain")
# Prefer go-ahead 1:1→2:1: confirmation lands on a Shot event with prior score time.
DEFAULT_CANDIDATE = "mg_trans_2"


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
    p = argparse.ArgumentParser(description="V2 Strip-Guided Round 2.1 — single goal recovery")
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--events", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--strip-a", type=Path, default=None)
    p.add_argument("--algo-root", type=Path, default=DEFAULT_ALGO)
    p.add_argument("--candidate-id", type=str, default=DEFAULT_CANDIDATE)
    p.add_argument("--input-source", choices=list(INPUT_SOURCES), default="human_corrected")
    p.add_argument("--real", action="store_true")
    p.add_argument("--preflight-only", action="store_true")
    p.add_argument("--skip-video", action="store_true")
    p.add_argument("--max-steps", type=int, default=8)
    p.add_argument("--frame-budget", type=int, default=24)
    p.add_argument("--max-api-calls", type=int, default=12)
    p.add_argument("--max-cost-usd", type=float, default=0.5)
    p.add_argument("--max-completion-tokens", type=int, default=4096)
    p.add_argument("--no-llm-planner", action="store_true", default=True)
    p.add_argument("--use-llm-planner", action="store_true", help="Also preflight/use planner")
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Always write a standalone preflight artifact first for real mode.
    if args.real and not args.skip_video:
        configs = load_endpoint_configs()
        roles = ("planner", "vision") if args.use_llm_planner else ("vision",)
        pf = run_preflight(configs=configs, image_path=None, require_roles=roles)
        (out_dir / "api_preflight.json").write_text(
            json.dumps(pf, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps({"preflight_passed": pf.get("passed"), "failure_summary": pf.get("failure_summary")}, ensure_ascii=False, indent=2))
        if args.preflight_only:
            return 0 if pf.get("passed") else 2
        if not pf.get("passed"):
            (out_dir / "cli_report.json").write_text(
                json.dumps(
                    {
                        "schema": "v2_strip_guided_r2_1_report_v1",
                        "status": "aborted_preflight",
                        "candidate_id": args.candidate_id,
                        "api_preflight": pf,
                        "n_inferred_verified_goals": 0,
                        "render_ready": False,
                        "git_sha": _git_sha(),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            return 2

    api = _make_api(
        real=bool(args.real),
        max_calls=args.max_api_calls,
        max_cost=args.max_cost_usd,
        max_completion_tokens=args.max_completion_tokens,
    )
    use_llm = bool(args.use_llm_planner)
    try:
        report = run_goal_recovery(
            video=args.video,
            events_path=args.events,
            out_dir=out_dir,
            api=api,
            algo_root=args.algo_root,
            strip_a_path=args.strip_a,
            input_source=args.input_source,
            max_steps=args.max_steps,
            frame_budget=args.frame_budget,
            use_llm_planner=use_llm,
            skip_video=bool(args.skip_video),
            candidate_ids=[args.candidate_id],
            require_preflight_check=bool(args.real) and not args.skip_video,
        )
    except PreflightError as exc:
        report = {
            "schema": "v2_strip_guided_r2_1_report_v1",
            "status": "aborted_preflight",
            "candidate_id": args.candidate_id,
            "error": str(exc),
            "api_preflight": exc.report,
            "n_inferred_verified_goals": 0,
            "render_ready": False,
        }
        (out_dir / "cli_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    report["schema"] = "v2_strip_guided_r2_1_report_v1"
    report["candidate_id"] = args.candidate_id
    report["git_sha"] = _git_sha()
    report["cli"] = "v2_strip_guided_r2_1_cli"
    (out_dir / "cli_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: report.get(k)
                for k in (
                    "match_id",
                    "candidate_id",
                    "n_missing_goal_candidates",
                    "n_inferred_verified_goals",
                    "stop_reason",
                    "strip_A_chains",
                    "strip_B_chains",
                    "git_sha",
                    "render_ready",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if int(report.get("n_inferred_verified_goals") or 0) > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
