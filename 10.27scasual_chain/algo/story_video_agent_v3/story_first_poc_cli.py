"""Isolated Story-First v2 CLI. Offline by default; never modifies EDL.

Example:
PYTHONPATH=algo python -m story_video_agent_v3.story_first_poc_cli \
 --edl /path/candidate_edl.json --events /path/events_enriched.json \
 --out-dir /tmp/story_first_prepared

Real API: --enable-real-api --i-approve-budget AND STORY_API_ENABLE=1.
Reuse the existing Story API credentials/server (as V4 Pro and Qwen VL do).
Provider-specific Flash model ID is supplied by STORY_FIRST_LLM_MODEL;
never silently default to the older V4 Pro model. No thinking.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from .story_evidence_search import load_match_events
from .story_first_hypotheses import (
    SCHEMA, baseline_candidates, build_observation_plan, evidence_matrix,
    model_messages, parse_hypotheses, prepare_story_input,
)

MODEL_LABEL = "DeepSeek-V4.1-Flash"
DEFAULT_MODEL_AUDIT = "UNCONFIGURED_FLASH_PROVIDER_MODEL_ID"


def configured_flash_model_id() -> str:
    """Provider-specific model alias; never reuse V4 Pro/Qwen by accident."""
    model_id = (os.environ.get("STORY_FIRST_LLM_MODEL") or "").strip()
    if not model_id:
        raise ValueError("STORY_FIRST_LLM_MODEL_required_for_shared_gateway")
    lowered = model_id.lower()
    if "deepseek" not in lowered or "flash" not in lowered:
        raise ValueError("expected_deepseek_flash_provider_model_id")
    return model_id


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


def build_shared_story_first_provider(
    *, max_cost_usd: float, max_completion_tokens: int,
    disable_thinking_style: str = "thinking_object",
):
    """Reuse existing Story planner gateway, credentials, retry controls.

    The model ID is an explicit provider-side alias. Never assume that the
    official direct-API model name works on the existing shared gateway.
    Both supported request styles explicitly DISABLE thinking.
    """
    from story_video_agent.api_provider import ApiProvider, load_endpoint_configs

    model_id = configured_flash_model_id()
    original = load_endpoint_configs()["planner"]
    if not original.configured():
        raise ValueError("existing_STORY_LLM_gateway_configuration_missing")
    if disable_thinking_style not in ("thinking_object", "enable_thinking_false"):
        raise ValueError("unsupported_non_thinking_format")
    token_param = (
        os.environ.get("STORY_FIRST_TOKEN_PARAM") or original.token_param
    ).strip()
    if token_param not in ("max_tokens", "max_completion_tokens"):
        raise ValueError("invalid_or_uncapped_story_first_token_parameter")
    cfg = replace(
        original,
        model=model_id, max_retries=0,
        max_completion_tokens=max_completion_tokens,
        token_param=token_param, request_profile="default",
        default_temperature=0.0, stream=False,
        thinking_object_disabled=(disable_thinking_style == "thinking_object"),
        send_thinking_params=(disable_thinking_style == "enable_thinking_false"),
        enable_thinking=(
            False if disable_thinking_style == "enable_thinking_false" else None
        ),
        thinking_budget=None,
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
    expected_thinking = (
        req.get("thinking") == {"type": "disabled"}
        and "enable_thinking" not in req
        and "thinking_budget" not in req
        if disable_thinking_style == "thinking_object"
        else req.get("enable_thinking") is False
        and "thinking" not in req
        and "thinking_budget" not in req
    )
    if (req.get("model") != model_id or not expected_thinking
        or req.get("stream") is not False
        or sum(k in req for k in ("max_tokens", "max_completion_tokens")) != 1
        or req.get(token_param) != api.effective_output_token_limit(cfg)
        or req.get(token_param) > max_completion_tokens):
        raise ValueError("shared_flash_non_thinking_request_preflight_failed")
    return api, {
        "model": model_id,
        "model_label": MODEL_LABEL,
        "gateway": "existing_story_planner_service",
        "gateway_configured": True,
        "request_thinking": (
            req.get("thinking") if disable_thinking_style == "thinking_object"
            else {"enable_thinking": req.get("enable_thinking")}
        ),
        "thinking_disable_style": disable_thinking_style,
        "token_param": token_param, "request_audit": request_audit,
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
    p.add_argument("--check-provider-config-only", action="store_true",
                   help="Offline-only request preflight against existing Story gateway; no HTTP")
    p.add_argument("--disable-thinking-style",
                   choices=("thinking_object", "enable_thinking_false"),
                   default="thinking_object",
                   help="Use only the explicit nonthinking format supported by the gateway")
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
    if args.check_provider_config_only and (args.enable_real_api or args.fixture_model_json):
        print("REFUSED: offline preflight cannot be combined with paid API or fixture",
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
        "model": os.environ.get("STORY_FIRST_LLM_MODEL") or DEFAULT_MODEL_AUDIT,
        "model_label": MODEL_LABEL,
        "thinking_required_disabled": True,
        "thinking_disable_style": args.disable_thinking_style, "http_attempts": 0,
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
        prompt_text = "\n".join(str(m.get("content") or "") for m in messages)
        audit["prompt_coverage"] = {
            "full_inventory_events": len(prepared.get("event_inventory") or []),
            "rich_detail_events": len(prepared["events"]),
            "events_entirely_omitted": prepared["counts"].get(
                "events_omitted_entirely_from_prompt"
            ),
            "prompt_characters": len(prompt_text),
            "prompt_utf8_bytes": len(prompt_text.encode("utf-8")),
            "model_input_token_count_measured": False,
            "contains_unverified_hypotheses_only": True,
        }
        write_json(args.out_dir / "llm_input.json", {
            "model": audit["model"],
            "thinking_disable_style": args.disable_thinking_style,
            "thinking_must_be_disabled": True,
            "messages": messages, "data_tier": "HUMAN_ATOM_ENRICHED_DEV",
        })
        write_json(args.out_dir / "event_only_baseline.json",
                   baseline_candidates(prepared))
        if args.fixture_model_json:
            content = args.fixture_model_json.read_text(encoding="utf-8")
            mode = "OFFLINE_FIXTURE_NOT_REAL_MODEL_RESULT"
        elif args.enable_real_api:
            api, preflight = build_shared_story_first_provider(
                max_cost_usd=args.max_cost_usd,
                max_completion_tokens=args.max_completion_tokens,
                disable_thinking_style=args.disable_thinking_style,
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
            mode = "SHARED_GATEWAY_FLASH_REAL_API_UNVERIFIED"
        elif args.check_provider_config_only:
            api, preflight = build_shared_story_first_provider(
                max_cost_usd=args.max_cost_usd,
                max_completion_tokens=args.max_completion_tokens,
                disable_thinking_style=args.disable_thinking_style,
            )
            audit["api_preflight"] = preflight
            audit["model"] = preflight["model"]
            audit["http_attempts"] = api.stats.summary()["http_attempts"]
            content = ""
            mode = "SHARED_GATEWAY_PREFLIGHT_ONLY_ZERO_HTTP"
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
