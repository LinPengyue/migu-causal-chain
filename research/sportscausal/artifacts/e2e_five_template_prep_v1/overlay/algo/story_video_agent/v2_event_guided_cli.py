"""Event-Guided CLI Round 2 — modes: agent | rule | fixed."""

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
    p = argparse.ArgumentParser(description="V2 Event-Guided Round 2")
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--events", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--input-source", choices=list(INPUT_SOURCES), default="human_corrected")
    p.add_argument(
        "--planner-mode",
        choices=["agent", "rule", "fixed"],
        default="agent",
        help="agent=DeepSeek mid-loop; rule=Event-Rule baseline; fixed=no VLM search",
    )
    p.add_argument("--gold-story-graph", type=Path, default=None)
    p.add_argument("--gold-edl", type=Path, default=None)
    p.add_argument("--causal-offline", type=Path, default=None)
    p.add_argument("--focus-event-ids", type=str, default="", help="comma-separated for targeted runs")
    p.add_argument("--real", action="store_true")
    p.add_argument("--max-steps", type=int, default=16)
    p.add_argument("--frame-budget", type=int, default=64)
    p.add_argument("--max-api-calls", type=int, default=28)
    p.add_argument("--max-cost-usd", type=float, default=1.5)
    p.add_argument("--max-completion-tokens", type=int, default=8192)
    p.add_argument("--no-llm-planner", action="store_true")
    p.add_argument("--no-export-clips", action="store_true")
    args = p.parse_args(argv)

    if not args.video.is_file():
        print(f"missing video {args.video}", file=sys.stderr)
        return 2
    if not args.events.is_file():
        print(f"missing events {args.events}", file=sys.stderr)
        return 2
    if "causal" in args.events.name.lower():
        print("REFUSE: do not pass causal.json as --events", file=sys.stderr)
        return 2

    os.environ.setdefault("STORY_PLANNER_REQUEST_PROFILE", "video_rsi")
    os.environ.setdefault("STORY_VLM_REQUEST_PROFILE", "video_rsi")

    focus = [x.strip() for x in args.focus_event_ids.split(",") if x.strip()] or None

    try:
        # fixed mode needs no real API
        real = bool(args.real) and args.planner_mode != "fixed"
        api = _make_api(
            real=real,
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
            planner_mode=args.planner_mode,
            max_steps=args.max_steps,
            frame_budget=args.frame_budget,
            use_llm_planner=not args.no_llm_planner,
            gold_story_graph=args.gold_story_graph,
            gold_edl=args.gold_edl,
            causal_path_offline=args.causal_offline,
            export_review_clips=not args.no_export_clips,
            focus_event_ids=focus,
        )
    except ApiConfigError as exc:
        print(f"CONFIG: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        raise

    weak = (
        ((result.get("offline_eval") or {}).get("action_localization_eval") or {}).get(
            "weak_reference_goals"
        )
        or {}
    )
    report = {
        "schema": "v2_event_guided_cli_report_v2",
        "commit_sha": _git_sha(),
        "mode": f"event_{args.planner_mode}",
        "planner_mode": args.planner_mode,
        "video": str(args.video),
        "events": str(args.events),
        "input_source": args.input_source,
        "out_dir": str(args.out_dir),
        "real": bool(args.real) and args.planner_mode != "fixed",
        "discovery_status": (result.get("discovery") or {}).get("discovery_status"),
        "n_localized": (result.get("discovery") or {}).get("n_localized"),
        "grade_counts": (result.get("evidence") or {}).get("grade_counts"),
        "strict_localization_recall_weak_ref": weak.get("strict_localization_recall"),
        "loose_candidate_recall_weak_ref": weak.get("loose_candidate_recall"),
        "strict_action_gold_n": (
            ((result.get("offline_eval") or {}).get("action_localization_eval") or {})
            .get("strict_action_gold")
            or {}
        ).get("n_refs"),
        "relation_verification": {
            "n_accepted": (result.get("relation_verification") or {}).get("n_accepted"),
            "n_rejected": (result.get("relation_verification") or {}).get("n_rejected"),
            "n_downgraded": (result.get("relation_verification") or {}).get("n_downgraded"),
        },
        "n_llm_mid_loop": (result.get("autonomous_search_trace") or {}).get("n_llm_mid_loop"),
        "elapsed_sec": (result.get("agent_trace") or {}).get("elapsed_sec"),
        "frames_used": (result.get("agent_trace") or {}).get("frames_used"),
        "api_stats": (result.get("agent_trace") or {}).get("api_stats"),
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
