#!/usr/bin/env python3
"""A-match V3-A diagnosis: read-only provenance + optional ONE real Planner call.

Default: NO HTTP. With both --one-call and --i-approve-one-call: exactly one
HTTP attempt at most (no retries), no VLM, no full-match reprocessing/render.
Does not modify the previous experiment, frozen branches or existing outputs.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "10.27scasual_chain" / "algo"))

from story_video_agent_v3.fresh_e2e_cli import (  # noqa: E402
    edl_diff, edl_rows, file_record, read_json, write_json,
)

DEFAULT_RUN = Path(
    "/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_A_uae_oman/"
    "fresh_e2e_A_real_20261105_183136"
)
DEFAULT_HISTORY = DEFAULT_RUN.parent


def _optional_json(path: Path) -> Any:
    return read_json(path) if path.is_file() else None


def provenance(run: Path, history: Path) -> dict[str, Any]:
    """Compare files only; matching bytes do NOT prove which code path produced them."""
    edls = {
        "fresh_v3r": run / "01_to_04_fresh_v3r/04_phase5/candidate_edl.json",
        "fresh_v3a": run / "05_v3a/best_candidate_edl.json",
        "historical_raw": history / "04_phase5/candidate_edl.json",
        "historical_p1": history / "04_phase5_p1_polish/candidate_edl.json",
    }
    videos = {
        "fresh_v3r": run / "01_to_04_fresh_v3r/04_phase5/story_clean.mp4",
        "fresh_v3a": run / "06_candidate_render/story_clean.mp4",
        "historical_raw": history / "04_phase5/story_clean.mp4",
        "historical_p1": history / "04_phase5_p1_polish/story_clean.mp4",
    }
    files = {"edl": {k: file_record(v) for k, v in edls.items()},
             "video": {k: file_record(v) for k, v in videos.items()}}
    rows = {k: edl_rows(read_json(v)) for k, v in edls.items() if v.is_file()}
    comparisons = {
        f"fresh_v3r_vs_{name}": edl_diff(rows["fresh_v3r"], rows[name])
        for name in ("fresh_v3a", "historical_raw", "historical_p1")
        if "fresh_v3r" in rows and name in rows
    }
    return {
        "read_only": True,
        "history_used_as_pipeline_input": False,
        "files": files,
        "edl_comparisons": comparisons,
        "fresh_input_manifest": _optional_json(run / "00_input_manifest.json"),
        "fresh_phase5_manifest": _optional_json(
            run / "01_to_04_fresh_v3r/04_phase5/phase5_manifest.json"
        ),
        "historical_raw_phase5_manifest": _optional_json(
            history / "04_phase5/phase5_manifest.json"
        ),
        "interpretation_limit": (
            "EDL/video hash equality establishes identical bytes only. "
            "Inspect input SHA, algorithm versions, and actual read paths to distinguish "
            "reproducible current behavior from any historical dependency."
        ),
    }


def configure_and_preflight() -> tuple[Any, dict[str, Any]]:
    """Set thinking=disabled for Planner; construct and audit request WITHOUT HTTP."""
    from story_video_agent.api_provider import ApiProvider

    os.environ["STORY_API_ENABLE"] = "1"
    os.environ["STORY_PLANNER_THINKING_OBJECT_DISABLED"] = "1"
    os.environ.pop("STORY_PLANNER_SEND_THINKING", None)
    os.environ.pop("STORY_PLANNER_ENABLE_THINKING", None)
    os.environ.pop("STORY_PLANNER_THINKING_BUDGET", None)

    provider = ApiProvider(
        require_real=True, force_mock=False,
        max_calls=1, max_cost_usd=0.03, max_completion_tokens=2048,
        required_roles=["planner"],
    )
    cfg = provider.configs["planner"]
    cfg.max_retries = 0
    body, audit = provider.build_chat_request_body(
        cfg, messages=[{"role": "user", "content": "config check only"}],
        temperature=0.1,
    )
    assert body.get("thinking") == {"type": "disabled"}, "Planner thinking NOT disabled"
    assert "enable_thinking" not in body and "thinking_budget" not in body
    assert provider.max_calls == 1 and cfg.max_retries == 0
    assert audit.get("thinking_object_disabled_sent") is True
    return provider, {
        "configured": cfg.configured(),
        "model": cfg.model,
        "thinking_object_disabled": cfg.thinking_object_disabled,
        "request_thinking_sent": audit.get("thinking_object_disabled_sent"),
        "token_param_sent": audit.get("token_param_sent"),
        "token_limit_sent": audit.get("token_limit_sent"),
        "timeout_sec": cfg.timeout_sec,
        "max_retries": cfg.max_retries,
        "max_http_attempts": provider.max_calls,
        "max_cost_usd_estimate": provider.max_cost_usd,
        "note": "No HTTP sent during preflight. Estimated cost is not a billing hard cap.",
    }


def one_planner_call(provider: Any, context_file: Path) -> dict[str, Any]:
    """Reuse fresh R1 context; do not use prior Planner output or historical P1 EDL."""
    from story_video_agent.api_provider import failure_status_from_exc
    from story_video_agent_v3.self_revise_agent import call_llm_planner

    ctx = read_json(context_file)
    if not isinstance(ctx, dict) or not ctx.get("trusted_anchors"):
        raise ValueError("Fresh R1 planner context missing trusted_anchors")
    try:
        result = call_llm_planner(provider, ctx)
        valid = result.get("validated") if isinstance(result.get("validated"), dict) else {}
        tool_requests = valid.get("video_tool_requests") or []
        passed = bool(result.get("ok") and result.get("provider_mode") == "real" and tool_requests)
        return {
            "gate": "PLANNER_READY_FOR_VLM" if passed else "PLANNER_NOT_READY",
            "provider_mode": result.get("provider_mode"),
            "planner_ok": bool(result.get("ok")),
            "validated_tool_requests": len(tool_requests),
            "tool_requests": tool_requests[:4],
            "diagnoses_count": len(valid.get("diagnoses") or []),
            "revision_intents_count": len(valid.get("revision_intents") or []),
            "error": str(result.get("error") or "")[:500],
            "model": result.get("model"),
            "usage": result.get("usage"),
            "est_cost_usd": result.get("est_cost_usd"),
            "raw_excerpt": str(result.get("raw_excerpt") or "")[:2000],
        }
    except Exception as exc:  # diagnostic must preserve failure without retry
        return {
            "gate": "PLANNER_NOT_READY",
            "planner_ok": False,
            "exception_type": type(exc).__name__,
            "failure_status": failure_status_from_exc(exc),
            "note": "Single HTTP attempt at most; no automatic retry.",
        }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    p.add_argument("--history-root", type=Path, default=DEFAULT_HISTORY)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--one-call", action="store_true", help="Allow at most ONE real Planner HTTP attempt")
    p.add_argument("--i-approve-one-call", action="store_true", help="Explicit one-call approval")
    args = p.parse_args()
    if args.one_call != args.i_approve_one_call:
        p.error("Real API requires BOTH --one-call and --i-approve-one-call")
    run, history, out = args.run_dir.resolve(), args.history_root.resolve(), args.out_dir.resolve()
    if not run.is_dir():
        p.error(f"Previous fresh run missing: {run}")
    if out.exists():
        p.error(f"Output must not already exist: {out}")
    if out == run or out == history or run in out.parents:
        p.error("Diagnostics must not be written inside previous experiment or history")
    out.mkdir(parents=True)
    report: dict[str, Any] = {
        "schema": "v3a_A_planner_diagnostic_v1",
        "previous_run": str(run),
        "history_root": str(history),
        "real_http_authorized": bool(args.one_call),
        "real_http_executed": False,
        "full_pipeline_rerun": False,
        "vision_calls": 0,
        "status": "started",
    }
    try:
        report["provenance"] = provenance(run, history)
        write_json(out / "provenance_audit.json", report["provenance"])
        provider, preflight = configure_and_preflight()
        report["planner_preflight"] = preflight
        write_json(out / "planner_preflight.json", preflight)
        if args.one_call:
            context = run / "05_v3a/round_01/planner_context.json"
            if not context.is_file():
                raise FileNotFoundError(f"Fresh planner context missing: {context}")
            report["planner_smoke"] = one_planner_call(provider, context)
            report["real_http_executed"] = provider.status()["http_attempts"] > 0
            report["api_usage"] = provider.status()["usage"]
            report["status"] = report["planner_smoke"]["gate"]
            write_json(out / "planner_smoke.json", report["planner_smoke"])
        else:
            report["status"] = "PREFLIGHT_ONLY_NO_HTTP"
    except Exception as exc:
        report["status"] = "DIAGNOSTIC_FAILED"
        report["error_type"] = type(exc).__name__
        report["error"] = str(exc)[:350] if isinstance(exc, (ValueError, FileNotFoundError)) else "See error_type; no credentials recorded"
    finally:
        write_json(out / "diagnostic_summary.json", report)
    print(json.dumps({
        "status": report["status"],
        "output": str(out),
        "http_executed": report["real_http_executed"],
        "planner_gate": (report.get("planner_smoke") or {}).get("gate"),
    }, ensure_ascii=False))
    return 0 if report["status"] in ("PREFLIGHT_ONLY_NO_HTTP", "PLANNER_READY_FOR_VLM") else 1


if __name__ == "__main__":
    raise SystemExit(main())
