"""真实 API 联调入口（Phase 2C.1）— 默认不发起计费请求。

模式：
  vlm-only           规则策略选克罗地亚单窗口 → 仅真实 VLM
  planner-vlm-loop   在 VLM 结果上再测 LLM Planner 下一步（继续/细化/停止）

显式开启：
  STORY_API_ENABLE=1 STORY_API_SMOKE=1 \\
  STORY_LLM_BASE_URL=... STORY_LLM_API_KEY=... STORY_VLM_MODEL=... \\
  STORY_API_MAX_CALLS=3 STORY_API_MAX_COST_USD=0.05 \\
  STORY_API_MAX_COMPLETION_TOKENS=512 \\
  python -m story_video_agent.smoke_api --mode vlm-only \\
    --story-json ... --video-path ...

禁止用 mock 结果冒充真实成功。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from story_video_agent.agent import Agent
from story_video_agent.api_provider import (
    COST_DISCLAIMER,
    ApiConfigError,
    ApiProvider,
    api_enabled,
    load_endpoint_configs,
    smoke_enabled,
)
from story_video_agent.frames import FrameBudget, FrameStore, allocate_gap_caps
from story_video_agent.media import probe_video
from story_video_agent.memory import Memory
from story_video_agent.state import build_agent_item, detect_gaps, load_t01_story
from story_video_agent.tools import ToolBox
from story_video_agent.vision_provider import VisionProvider

DEFAULT_CROATIA_GAP = "missing_setup_visual"
MODES = ("vlm-only", "planner-vlm-loop")


class SmokePreflightError(RuntimeError):
    """联调前检查失败。"""


def preflight(
    *,
    mode: str,
    story_json: Path,
    video_path: Path,
    require_cost_caps: bool = True,
) -> Dict[str, Any]:
    problems: List[str] = []
    if mode not in MODES:
        problems.append(f"unknown mode {mode}; expected {MODES}")
    if not smoke_enabled():
        problems.append("STORY_API_SMOKE not set to 1")
    if not api_enabled():
        problems.append("STORY_API_ENABLE not set to 1")
    if not story_json.is_file():
        problems.append(f"story json missing: {story_json}")
    if not video_path.is_file():
        problems.append(f"video missing: {video_path}")

    configs = load_endpoint_configs()
    roles = ["vision"] if mode == "vlm-only" else ["vision", "planner"]
    for role in roles:
        cfg = configs[role]
        if not cfg.base_url:
            problems.append(f"{role}: missing BASE_URL")
        if not cfg.model:
            problems.append(f"{role}: missing MODEL")
        if not cfg.api_key:
            problems.append(f"{role}: missing API_KEY")

    max_calls = (os.environ.get("STORY_API_MAX_CALLS") or "").strip()
    max_cost = (os.environ.get("STORY_API_MAX_COST_USD") or "").strip()
    if require_cost_caps:
        if not max_calls:
            problems.append("STORY_API_MAX_CALLS required for real smoke")
        if not max_cost:
            problems.append(
                "STORY_API_MAX_COST_USD required (estimate soft-cap, not invoice limit)"
            )

    report = {
        "ok": not problems,
        "mode": mode,
        "roles": roles,
        "story_json": str(story_json),
        "video_path": str(video_path),
        "max_calls": max_calls or None,
        "max_cost_usd": max_cost or None,
        "max_completion_tokens": os.environ.get("STORY_API_MAX_COMPLETION_TOKENS") or None,
        "cost_disclaimer": COST_DISCLAIMER,
        "problems": problems,
        "endpoints": {r: configs[r].to_dict() for r in roles},
    }
    if problems:
        raise SmokePreflightError("; ".join(problems))
    return report


def _select_gap_id(gaps: Sequence[Dict[str, Any]], focus: Optional[str]) -> str:
    if focus:
        for g in gaps:
            if g.get("gap_id") == focus and g.get("registerable", True):
                return focus
        raise SmokePreflightError(f"focus gap not registerable: {focus}")
    for g in gaps:
        if g.get("gap_id") == DEFAULT_CROATIA_GAP and g.get("registerable", True):
            return DEFAULT_CROATIA_GAP
    for g in gaps:
        if g.get("registerable", True):
            return str(g["gap_id"])
    raise SmokePreflightError("no registerable gaps")


def _assert_real_not_mock(provider_mode: str, *, context: str) -> None:
    if provider_mode in ("mock", ""):
        raise RuntimeError(
            f"REFUSE: {context} returned provider_mode={provider_mode!r}; "
            "mock results must not be reported as real API success"
        )
    if provider_mode not in ("real", "cache", "degraded"):
        raise RuntimeError(f"unexpected provider_mode={provider_mode!r} in {context}")


def _make_store(media: Any, *, out_dir: Path, frame_budget: int, gap_id: str) -> FrameStore:
    caps = allocate_gap_caps([gap_id], global_budget=max(1, frame_budget))
    return FrameStore(
        media,
        out_dir=out_dir,
        budget=FrameBudget(max_frames=max(1, frame_budget), per_gap_caps=caps),
    )


def run_vlm_only(
    *,
    story_json: Path,
    video_path: Path,
    gap_id: Optional[str] = None,
    frame_dir: Optional[Path] = None,
    frame_budget: int = 4,
) -> Dict[str, Any]:
    pf = preflight(mode="vlm-only", story_json=story_json, video_path=video_path)
    story = load_t01_story(str(story_json))
    media = probe_video(str(video_path))
    item = build_agent_item(
        story, video_path=str(video_path), duration_sec=float(media.duration_sec)
    )
    gaps = item.get("gaps") or detect_gaps(story, duration_sec=float(media.duration_sec))
    chosen = _select_gap_id(gaps, gap_id)

    out_dir = frame_dir or Path("reports") / "story_video_agent_frames_smoke_vlm"
    out_dir.mkdir(parents=True, exist_ok=True)
    store = _make_store(media, out_dir=out_dir, frame_budget=frame_budget, gap_id=chosen)
    api = ApiProvider(force_mock=False, require_real=True, required_roles=["vision"])
    if api.status()["mode"] != "real":
        raise RuntimeError("REFUSE: ApiProvider not in real mode for vlm-only")
    vision = VisionProvider(api, force_mock=False)
    tools = ToolBox(
        item,
        dry_run=False,
        perception=True,
        frame_store=store,
        media_info=media,
        vision=vision,
        focus_gap_ids=[chosen],
    )

    t0 = time.perf_counter()
    tools.execute("probe_video_media", {})
    tools.execute("list_story_gaps", {})
    tools.execute("register_evidence_task", {"gap_id": chosen})
    sample = tools.execute("sample_next_evidence", {"gap_id": chosen})
    frames = list(sample.get("frames") or [])
    if not frames:
        return {
            "mode": "vlm-only",
            "preflight": pf,
            "status": "failed",
            "failure_status": "no_frames",
            "gap_id": chosen,
            "sample": sample,
            "api": api.status(),
            "elapsed_sec": round(time.perf_counter() - t0, 4),
            "cost_disclaimer": COST_DISCLAIMER,
        }

    frame_ids = [str(f["frame_id"]) for f in frames]
    inspect = tools.execute(
        "inspect_visual_evidence",
        {"gap_id": chosen, "frame_ids": frame_ids},
    )
    evidence = (inspect or {}).get("visual_evidence") or {}
    mode = str(evidence.get("provider_mode") or "")
    _assert_real_not_mock(mode, context="vlm-only inspect")

    elapsed = round(time.perf_counter() - t0, 4)
    usage = api.stats.summary()
    return {
        "mode": "vlm-only",
        "preflight": pf,
        "status": "ok" if evidence.get("normalized_ok") else "failed",
        "failure_status": evidence.get("failure_status"),
        "gap_id": chosen,
        "window": sample.get("window"),
        "sampled_frame_ids": frame_ids,
        "vlm": {
            "provider_mode": mode,
            "model": evidence.get("model"),
            "normalized_ok": evidence.get("normalized_ok"),
            "frame_ids": evidence.get("frame_ids"),
            "observed_actions": evidence.get("observed_actions"),
            "story_relation": evidence.get("story_relation"),
            "confidence": evidence.get("confidence"),
            "notes": evidence.get("notes"),
            "raw_response_excerpt": evidence.get("raw_response_excerpt"),
            "usage": evidence.get("usage"),
            "est_cost_usd": evidence.get("est_cost_usd"),
            "message": evidence.get("message"),
            "error": evidence.get("error"),
        },
        "http_attempts": usage.get("http_attempts"),
        "cached_hits": usage.get("cached_hits"),
        "elapsed_sec": elapsed,
        "est_cost_usd_real": usage.get("est_cost_usd_real"),
        "cost_disclaimer": COST_DISCLAIMER,
        "api": api.status(),
    }


def run_planner_vlm_loop(
    *,
    story_json: Path,
    video_path: Path,
    gap_id: Optional[str] = None,
    frame_dir: Optional[Path] = None,
    frame_budget: int = 4,
) -> Dict[str, Any]:
    pf = preflight(mode="planner-vlm-loop", story_json=story_json, video_path=video_path)
    story = load_t01_story(str(story_json))
    media = probe_video(str(video_path))
    item = build_agent_item(
        story, video_path=str(video_path), duration_sec=float(media.duration_sec)
    )
    gaps = item.get("gaps") or detect_gaps(story, duration_sec=float(media.duration_sec))
    chosen = _select_gap_id(gaps, gap_id)

    out_dir = frame_dir or Path("reports") / "story_video_agent_frames_smoke_loop"
    out_dir.mkdir(parents=True, exist_ok=True)
    store = _make_store(media, out_dir=out_dir, frame_budget=frame_budget, gap_id=chosen)
    api = ApiProvider(
        force_mock=False,
        require_real=True,
        required_roles=["vision", "planner"],
    )
    if api.status()["mode"] != "real":
        raise RuntimeError("REFUSE: ApiProvider not in real mode for planner-vlm-loop")
    vision = VisionProvider(api, force_mock=False)
    tools = ToolBox(
        item,
        dry_run=False,
        perception=True,
        frame_store=store,
        media_info=media,
        vision=vision,
        focus_gap_ids=[chosen],
    )
    memory = Memory()
    agent = Agent(item, tools, api=api, use_llm_planner=True)

    t0 = time.perf_counter()
    tools.execute("probe_video_media", {})
    tools.execute("list_story_gaps", {})
    tools.execute("register_evidence_task", {"gap_id": chosen})
    agent._registered.add(chosen)
    sample = tools.execute("sample_next_evidence", {"gap_id": chosen})
    frames = list(sample.get("frames") or [])
    window = sample.get("window") or {}
    if window.get("start") is not None:
        memory.add_checked_interval(
            chosen, float(window["start"]), float(window["end"])
        )
    frame_ids = [str(f["frame_id"]) for f in frames]
    agent._task_frames[chosen] = list(frame_ids)
    agent._sampled_done.add(chosen)
    memory.mark_sampled(chosen)

    evidence: Dict[str, Any] = {}
    if frame_ids:
        inspect = tools.execute(
            "inspect_visual_evidence",
            {"gap_id": chosen, "frame_ids": frame_ids},
        )
        evidence = (inspect or {}).get("visual_evidence") or {}
        _assert_real_not_mock(
            str(evidence.get("provider_mode") or ""), context="planner-vlm-loop VLM"
        )
        memory.add_raw_vlm(
            chosen, str(evidence.get("raw_response_excerpt") or ""), evidence
        )
        if evidence.get("normalized_ok"):
            memory.mark_observed(chosen, evidence)
        else:
            memory.mark_unresolved(
                chosen,
                str(
                    evidence.get("message")
                    or evidence.get("failure_status")
                    or "vlm_failed"
                ),
                doubt={"failure_status": evidence.get("failure_status")},
            )
            if evidence.get("conflict"):
                memory.add_conflict(evidence["conflict"])

    fallback = {
        "type": "answer",
        "answer": "finish_evidence_plan",
        "reason": "fallback_after_vlm",
    }
    planner_raw = agent._propose_llm(memory, remaining=5, fallback=fallback)
    planner_api_mode = None
    for rec in reversed(api.stats.calls):
        if rec.role == "planner":
            planner_api_mode = rec.mode
            break
    if planner_api_mode == "mock":
        raise RuntimeError(
            "REFUSE: planner returned mock; cannot claim real planner-vlm-loop success"
        )

    elapsed = round(time.perf_counter() - t0, 4)
    usage = api.stats.summary()
    return {
        "mode": "planner-vlm-loop",
        "preflight": pf,
        "status": "ok"
        if evidence.get("normalized_ok") and planner_api_mode in ("real", "cache")
        else "partial_or_failed",
        "gap_id": chosen,
        "vlm": {
            "provider_mode": evidence.get("provider_mode"),
            "normalized_ok": evidence.get("normalized_ok"),
            "failure_status": evidence.get("failure_status"),
            "frame_ids": evidence.get("frame_ids"),
            "observed_actions": evidence.get("observed_actions"),
            "story_relation": evidence.get("story_relation"),
            "raw_response_excerpt": evidence.get("raw_response_excerpt"),
            "usage": evidence.get("usage"),
            "est_cost_usd": evidence.get("est_cost_usd"),
        },
        "planner": {
            "provider_mode": planner_api_mode,
            "decision": planner_raw,
            "interprets_as": _interpret_planner(planner_raw),
        },
        "http_attempts": usage.get("http_attempts"),
        "cached_hits": usage.get("cached_hits"),
        "elapsed_sec": elapsed,
        "est_cost_usd_real": usage.get("est_cost_usd_real"),
        "cost_disclaimer": COST_DISCLAIMER,
        "api": api.status(),
        "planner_facts_fed": memory.planner_facts(),
    }


def _interpret_planner(decision: Dict[str, Any]) -> str:
    if not isinstance(decision, dict):
        return "invalid"
    if decision.get("type") == "answer":
        return "stop"
    if decision.get("type") == "tool":
        tool = decision.get("tool")
        if tool == "refine_search_window":
            mode = (decision.get("arguments") or {}).get("mode")
            return f"refine:{mode}"
        if tool in (
            "sample_next_evidence",
            "coarse_search_interval",
            "inspect_story_window",
        ):
            return "continue_search"
        if tool == "inspect_visual_evidence":
            return "inspect"
        return f"tool:{tool}"
    return "unknown"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Story Video Agent real-API smoke 2C.1 (explicit only)"
    )
    parser.add_argument(
        "--mode",
        choices=MODES,
        default="vlm-only",
        help="vlm-only | planner-vlm-loop",
    )
    parser.add_argument("--story-json", type=Path, required=True)
    parser.add_argument("--video-path", type=Path, required=True)
    parser.add_argument("--gap-id", type=str, default=DEFAULT_CROATIA_GAP)
    parser.add_argument("--frame-budget", type=int, default=4)
    parser.add_argument("--frame-dir", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--dry-check",
        action="store_true",
        help="Only run preflight (no HTTP). Still requires smoke flags.",
    )
    args = parser.parse_args(argv)

    if not smoke_enabled():
        print("REFUSE: set STORY_API_SMOKE=1 to run billed smoke", file=sys.stderr)
        return 2
    if not api_enabled():
        print("REFUSE: set STORY_API_ENABLE=1", file=sys.stderr)
        return 2

    try:
        if args.dry_check:
            report = preflight(
                mode=args.mode,
                story_json=args.story_json,
                video_path=args.video_path,
            )
            report["dry_check"] = True
            report["note"] = "preflight only; no HTTP performed"
        elif args.mode == "vlm-only":
            report = run_vlm_only(
                story_json=args.story_json,
                video_path=args.video_path,
                gap_id=args.gap_id,
                frame_dir=args.frame_dir,
                frame_budget=args.frame_budget,
            )
        else:
            report = run_planner_vlm_loop(
                story_json=args.story_json,
                video_path=args.video_path,
                gap_id=args.gap_id,
                frame_dir=args.frame_dir,
                frame_budget=args.frame_budget,
            )
    except (SmokePreflightError, ApiConfigError) as exc:
        print(f"REFUSE preflight/config: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(args.out)
    else:
        print(text)
    if report.get("dry_check"):
        return 0
    return 0 if report.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
