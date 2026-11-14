"""Isolated Story-First v2 CLI. Offline by default; never modifies EDL.

Example:
PYTHONPATH=algo python -m story_video_agent_v3.story_first_poc_cli \
 --edl /path/candidate_edl.json --events /path/events_enriched.json \
 --out-dir /tmp/story_first_prepared

Real API: --enable-real-api --i-approve-budget AND STORY_API_ENABLE=1
AND DEEPSEEK_API_KEY. Exact official model ID: deepseek-flash.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from .story_evidence_search import load_match_events
from .story_first_hypotheses import (
    SCHEMA, baseline_candidates, build_observation_plan, evidence_matrix,
    model_messages, parse_hypotheses, prepare_story_input,
)

MODEL_ID = "deepseek-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_model_json(text: str) -> Mapping[str, Any]:
    content = str(text or "").strip()
    fence = chr(96) * 3
    if content.startswith(fence):
        content = content.split("\n", 1)[-1].rsplit(fence, 1)[0].strip()
    raw = json.loads(content)
    if not isinstance(raw, dict):
        raise ValueError("model_response_must_be_json_object")
    return raw


def build_deepseek_provider(*, max_cost_usd: float, max_completion_tokens: int):
    """One text planner; separate explicit DeepSeek credentials; no fallback."""
    from story_video_agent.api_provider import ApiProvider, EndpointConfig

    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        raise ValueError("DEEPSEEK_API_KEY_missing")
    base = (os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    if not (base.startswith("https://") or (
        os.environ.get("STORY_FIRST_ALLOW_LOCAL_HTTP") == "1"
        and base.startswith("http://127.0.0.1"))):
        raise ValueError("provider_base_url_must_be_https")
    cfg = EndpointConfig(
        role="planner", base_url=base, api_key=key, model=MODEL_ID,
        timeout_sec=90.0, max_retries=0, rpm=20.0, token_param="max_tokens",
        max_completion_tokens=max_completion_tokens,
        send_thinking_params=False, enable_thinking=None, thinking_budget=None,
        request_profile="default", default_temperature=0.0,
        thinking_object_disabled=True, stream=False,
    )
    api = ApiProvider(
        configs={"planner": cfg}, required_roles=("planner",),
        force_mock=False, require_real=True,
        max_calls=1, max_cost_usd=max_cost_usd,
        max_completion_tokens=max_completion_tokens,
    )
    req, request_audit = api.build_chat_request_body(
        cfg, messages=[{"role": "user", "content": "preflight"}],
        temperature=0.0,
    )
    if (req.get("model") != MODEL_ID or
        req.get("thinking") != {"type": "disabled"} or
        req.get("stream") is not False or
        any(k in req for k in
            ("enable_thinking", "thinking_budget", "max_completion_tokens"))):
        raise ValueError("deepseek_non_thinking_request_preflight_failed")
    return api, {
        "model": MODEL_ID, "base_url": base,
        "request_thinking": req["thinking"], "request_audit": request_audit,
        "api_key_logged": False, "http_attempt_cap": 1, "retry_cap": 0,
        "cost_cap_is_estimate_not_invoice_guarantee": True,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Story-First V3-A v2 isolated POC")
    p.add_argument("--edl", required=True, type=Path)
    p.add_argument("--events", required=True, type=Path)
    p.add_argument("--story-plan", type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--from-segment-id")
    p.add_argument("--to-segment-id")
    p.add_argument("--max-events", type=int, default=240)
    p.add_argument("--max-hypotheses", type=int, default=5)
    p.add_argument("--gap-threshold-sec", type=float, default=120)
    p.add_argument("--fixture-model-json", type=Path)
    p.add_argument("--enable-real-api", action="store_true")
    p.add_argument("--i-approve-budget", action="store_true")
    p.add_argument("--max-cost-usd", type=float, default=0.10)
    p.add_argument("--max-completion-tokens", type=int, default=3200)
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.enable_real_api and not (
        args.i_approve_budget and os.environ.get("STORY_API_ENABLE") == "1"
    ):
        print("REFUSED: paid mode requires --i-approve-budget and STORY_API_ENABLE=1",
              file=sys.stderr)
        return 2
    if args.fixture_model_json is not None and args.enable_real_api:
        print("REFUSED: fixture and real API cannot be combined", file=sys.stderr)
        return 2
    if not (1 <= args.max_hypotheses <= 5 and
            128 <= args.max_completion_tokens <= 6000 and
            0 < args.max_cost_usd <= 0.10):
        print("REFUSED: unsafe hypothesis/token/cost limits", file=sys.stderr)
        return 2
    sources = [args.edl, args.events] + (
        [args.story_plan] if args.story_plan else []
    ) + ([args.fixture_model_json] if args.fixture_model_json else [])
    if any(not path.is_file() for path in sources):
        print("REFUSED: one or more input files missing", file=sys.stderr)
        return 2
    if args.out_dir.exists():
        if not args.out_dir.is_dir() or any(args.out_dir.iterdir()):
            print("REFUSED: output directory already populated", file=sys.stderr)
            return 2
    args.out_dir.mkdir(parents=True, exist_ok=True)
    audit: Dict[str, Any] = {
        "schema": SCHEMA, "data_tier": "HUMAN_ATOM_ENRICHED_DEV",
        "model": MODEL_ID, "model_label": "DeepSeek-V4.1-Flash",
        "thinking": {"type": "disabled"}, "http_attempts": 0,
        "paid_http_authorized": bool(args.enable_real_api),
        "edl_modified": False, "candidate_rendered": False,
        "first_live_certified": False, "story_quality_improved_verified": False,
        "input_sha256": {str(path): sha256_file(path) for path in sources},
        "max_cost_usd": args.max_cost_usd,
        "cost_guard_is_estimate_not_invoice_cap": True,
    }
    try:
        edl = json.loads(args.edl.read_text(encoding="utf-8"))
        events = load_match_events(events_json=args.events)
        if not events:
            raise ValueError("empty_or_unsupported_events_json")
        plan = (json.loads(args.story_plan.read_text(encoding="utf-8"))
                if args.story_plan else None)
        prepared = prepare_story_input(
            edl, events, story_plan=plan,
            from_segment_id=args.from_segment_id,
            to_segment_id=args.to_segment_id,
            gap_threshold_sec=args.gap_threshold_sec,
            max_events=args.max_events,
        )
        audit["input_counts"] = prepared["counts"]
        write_json(args.out_dir / "prepared_story_input.json", prepared)
        messages = model_messages(prepared, args.max_hypotheses)
        write_json(args.out_dir / "llm_input.json", {
            "model": MODEL_ID, "thinking": {"type": "disabled"},
            "messages": messages, "data_tier": "HUMAN_ATOM_ENRICHED_DEV",
        })
        write_json(args.out_dir / "event_only_baseline.json",
                   baseline_candidates(prepared))
        if args.fixture_model_json:
            content = args.fixture_model_json.read_text(encoding="utf-8")
            mode = "OFFLINE_FIXTURE_NOT_REAL_MODEL_RESULT"
        elif args.enable_real_api:
            api, preflight = build_deepseek_provider(
                max_cost_usd=args.max_cost_usd,
                max_completion_tokens=args.max_completion_tokens,
            )
            audit["api_preflight"] = preflight
            try:
                response = api.chat(
                    role="planner", messages=messages, temperature=0.0,
                    allow_degraded_fallback=False,
                )
            finally:
                usage = api.stats.summary()
                audit["http_attempts"] = usage.get("http_attempts", 0)
                audit["api_usage"] = {
                    "http_attempts": usage.get("http_attempts"),
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "est_cost_usd_real": usage.get("est_cost_usd_real"),
                }
            if response.get("provider_mode") != "real":
                raise ValueError("not_real_api_response")
            audit["returned_model"] = response.get("model")
            audit["finish_reason"] = response.get("finish_reason")
            audit["provider_usage_reported"] = response.get("usage")
            if str(response.get("finish_reason") or "").lower() in ("length", "content_filter"):
                raise ValueError("model_output_not_complete_or_filtered")
            content = str(response.get("content") or "")
            mode = "DEEPSEEK_REAL_API_UNVERIFIED"
        else:
            content = ""
            mode = "PREPARED_ONLY_ZERO_HTTP"
        audit["source_mode"] = mode
        if content:
            (args.out_dir / "llm_raw_response.txt").write_text(
                content, encoding="utf-8"
            )
            validated = parse_hypotheses(
                parse_model_json(content), prepared,
                max_hypotheses=args.max_hypotheses,
            )
        else:
            validated = {
                "schema": SCHEMA, "hypotheses": [], "rejected": [],
                "status": "AWAITING_LLM", "insufficient_evidence_reason": "",
                "edl_modified": False, "first_live_certified": False,
            }
        write_json(args.out_dir / "story_hypotheses.json", validated)
        write_json(args.out_dir / "hypothesis_evidence_matrix.json",
                   evidence_matrix(prepared, validated))
        write_json(args.out_dir / "observation_plan.json",
                   build_observation_plan(prepared, validated))
        audit["accepted_hypotheses"] = len(validated["hypotheses"])
        audit["rejected_hypotheses"] = len(validated.get("rejected") or [])
        audit["status"] = (
            mode if validated["status"] == "AWAITING_LLM" else validated["status"]
        )
        write_json(args.out_dir / "hypothesis_generation_audit.json", audit)
        print(json.dumps({
            "status": audit["status"],
            "events": audit["input_counts"]["events_in_llm_context"],
            "hypotheses": audit["accepted_hypotheses"],
            "http_attempts": audit["http_attempts"],
            "out_dir": str(args.out_dir),
        }, ensure_ascii=False))
        return 0
    except Exception as exc:
        audit["status"] = "FAILED_NO_PROMOTION"
        audit["error_type"] = type(exc).__name__
        audit["error"] = str(exc)[:500]
        write_json(args.out_dir / "hypothesis_generation_audit.json", audit)
        print("Story-First POC failed: %s" % str(exc)[:250], file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
