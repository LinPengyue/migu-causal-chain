#!/usr/bin/env python3
"""One-shot real Qwen VLM observation using a prior successful A-match Planner request.

Default: offline-only preflight; no HTTP. A real call requires BOTH --one-call
and --i-approve-one-call. Never invokes Planner, Verifier, revision, or renderer.
Never reads historical P1 EDL. Always creates a new output directory.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "10.27scasual_chain" / "algo"))

from story_video_agent_v3.fresh_e2e_cli import read_json, write_json  # noqa: E402

DEFAULT_RUN = Path(
    "/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_A_uae_oman/"
    "fresh_e2e_A_real_20261105_183136"
)
DEFAULT_PLANNER_SMOKE = Path(
    "/data2/lpy1/_story_va_outputs/v3/plan2/"
    "A_planner_smoke_20261105_202431/planner_smoke.json"
)
ALLOWED_TOOLS = {"vlm_observe", "extract_frames", "widen_search"}


def select_goal_request(
    smoke: Mapping[str, Any],
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """Select one Planner-validated goal request, not an arbitrary buildup request."""
    if smoke.get("gate") != "PLANNER_READY_FOR_VLM" or not smoke.get("planner_ok"):
        raise ValueError("Planner smoke did not pass PLANNER_READY_FOR_VLM")
    if smoke.get("provider_mode") != "real":
        raise ValueError("Planner smoke must be a real API result")
    tools = smoke.get("tool_requests")
    anchors = {
        str(a.get("anchor_id")): a
        for a in (context.get("trusted_anchors") or [])
        if isinstance(a, dict) and a.get("anchor_id")
    }
    if not isinstance(tools, list) or not tools:
        raise ValueError("No Planner-validated video tool requests")
    duration = context.get("video_duration_sec")
    duration = float(duration) if duration is not None else None
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for index, tr in enumerate(tools):
        if not isinstance(tr, dict) or tr.get("tool") not in ALLOWED_TOOLS:
            continue
        aid = str(tr.get("anchor_id") or "")
        anchor = anchors.get(aid)
        if not anchor:
            continue
        windows = tr.get("search_windows") or []
        if not isinstance(windows, list) or not windows:
            continue
        clean_windows = []
        for w in windows:
            if not isinstance(w, dict):
                continue
            try:
                s, e = float(w["start"]), float(w["end"])
            except (TypeError, ValueError, KeyError):
                continue
            if s < 0 or e <= s or e - s > 90.0 or (duration is not None and e > duration + 0.01):
                continue
            clean_windows.append({"start": s, "end": e})
        if not clean_windows:
            continue
        # Prefer goal-action EDL anchor, then equalizer/go-ahead score node.
        # A score node is only a search anchor, never a goal-action timestamp.
        blob = " ".join(str(x or "") for x in (
            aid, anchor.get("role"), anchor.get("arc_key"),
            tr.get("question"), tr.get("issue_id"),
        )).lower()
        if "buildup" in blob or "蓄力" in blob:
            continue
        goal_words = ("goal", "equalizer", "go_ahead", "behind_start", "进球", "扳平", "反超", "落后")
        if not any(w in blob for w in goal_words):
            continue
        priority = (
            0 if anchor.get("kind") == "existing_edl_segment" and "goal_action" in blob
            else 1 if "equalizer" in blob or "go_ahead" in blob or "扳平" in blob or "反超" in blob
            else 2
        )
        chosen = dict(tr)
        chosen["search_windows"] = clean_windows
        candidates.append((priority, index, chosen))
    if not candidates:
        raise ValueError("No valid goal-related Planner tool with a fresh trusted anchor")
    _, index, selected = min(candidates, key=lambda x: (x[0], x[1]))
    return {
        "planner_tool_index": index,
        "request": selected,
        "selected_window": selected["search_windows"][0],
        "anchor": anchors[selected["anchor_id"]],
        "note": "First trusted window only; no followup search; scoreboard anchor is not goal-action proof.",
    }


def configure_vision() -> tuple[Any, dict[str, Any]]:
    """Build audited Qwen request with one HTTP attempt, zero retries, no network."""
    from story_video_agent.api_provider import ApiProvider

    # Fail closed: vision must explicitly select Qwen, not silently inherit
    # the DeepSeek Planner model via load_endpoint_configs() fallback.
    explicit_vision_model = (os.environ.get("STORY_VLM_MODEL") or "").strip()
    if not explicit_vision_model or "qwen" not in explicit_vision_model.lower():
        raise ValueError("Explicit STORY_VLM_MODEL identifying Qwen is required")
    os.environ["STORY_API_ENABLE"] = "1"
    # Existing shell caps may be stricter (256 tokens); set explicit one-shot limits
    # in this process only, never modify the server env file.
    os.environ["STORY_API_MAX_CALLS"] = "1"
    os.environ["STORY_API_MAX_COST_USD"] = "0.03"
    os.environ["STORY_API_MAX_COMPLETION_TOKENS"] = "2048"
    os.environ["STORY_VLM_MAX_COMPLETION_TOKENS"] = "2048"
    os.environ["STORY_VLM_REQUEST_PROFILE"] = "video_rsi"
    os.environ["STORY_VLM_THINKING_OBJECT_DISABLED"] = "1"
    os.environ["STORY_VLM_TOKEN_PARAM"] = "max_tokens"
    os.environ.pop("STORY_VLM_SEND_THINKING", None)
    os.environ.pop("STORY_VLM_ENABLE_THINKING", None)
    os.environ.pop("STORY_VLM_THINKING_BUDGET", None)

    api = ApiProvider(
        require_real=True, force_mock=False, required_roles=("vision",),
        max_calls=1, max_cost_usd=0.03, max_completion_tokens=2048,
    )
    cfg = api.configs["vision"]
    cfg.max_retries = 0
    body, audit = api.build_chat_request_body(
        cfg, messages=[{"role": "user", "content": "offline request shape audit only"}],
        temperature=0.0,
    )
    if not cfg.configured():
        raise ValueError("Qwen vision endpoint not configured")
    if not (
        api.max_calls == 1 and cfg.max_retries == 0
        and api.effective_output_token_limit(cfg) == 2048
        and body.get("thinking") == {"type": "disabled"}
        and body.get("max_tokens") == 2048
        and body.get("stream") is False
        and "enable_thinking" not in body and "thinking_budget" not in body
    ):
        raise ValueError("VLM single-call request contract failed")
    return api, {
        "configured": True,
        "model": cfg.model,
        "max_http_attempts": api.max_calls,
        "max_retries": cfg.max_retries,
        "timeout_sec": cfg.timeout_sec,
        "max_cost_usd_estimate": api.max_cost_usd,
        "max_completion_tokens": api.effective_output_token_limit(cfg),
        "thinking_object_disabled_sent": audit.get("thinking_object_disabled_sent"),
        "stream_sent": audit.get("stream_sent"),
        "token_param_sent": audit.get("token_param_sent"),
        "token_limit_sent": audit.get("token_limit_sent"),
        "http_attempts": api.status()["http_attempts"],
        "cost_note": "Estimate only, not an absolute billing cap.",
    }


def evaluate_observation(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Evidence quality is independent of model confidence and goal/replay claims."""
    frames = observation.get("frames") or []
    vlm = observation.get("vlm") if isinstance(observation.get("vlm"), dict) else {}
    allowed = {str(f.get("frame_id")): f for f in frames if f.get("frame_id")}
    cited = vlm.get("cited_frame_ids")
    if cited is None:
        cited = vlm.get("frame_ids")
    cited = cited if isinstance(cited, list) else []
    valid_cites = bool(cited) and all(isinstance(x, str) and x in allowed for x in cited)
    cited_pts = [
        {"frame_id": fid, "actual_media_sec": allowed[fid].get("actual_media_sec"),
         "pts_status": allowed[fid].get("pts_status")}
        for fid in cited if isinstance(fid, str) and fid in allowed
    ]
    all_real_pts = valid_cites and all(
        p["actual_media_sec"] is not None and p["pts_status"] != "requested_only"
        for p in cited_pts
    )
    semantics = bool(str(vlm.get("visible_content") or vlm.get("story_relation") or "").strip())
    real = bool(observation.get("ok") and observation.get("provider_mode") == "real")
    if real and valid_cites and all_real_pts and semantics:
        gate = "VLM_OBSERVATION_WITH_PTS"
    elif real:
        gate = "VLM_REAL_BUT_EVIDENCE_INCOMPLETE"
    else:
        gate = "VLM_NOT_READY"
    return {
        "gate": gate,
        "real_provider": real,
        "valid_frame_citations": valid_cites,
        "cited_frame_count": len(cited),
        "cited_pts": cited_pts,
        "all_cited_have_actual_pts": bool(all_real_pts),
        "nonempty_visual_semantics": semantics,
        "observed_shot": vlm.get("observed_shot"),
        "observed_net": vlm.get("observed_net"),
        "live_or_replay": vlm.get("live_or_replay", "unknown"),
        "scoreboard_only": vlm.get("scoreboard_only"),
        "confidence": vlm.get("confidence"),
        "first_live_verified": False,
        "fact_verified": False,
        "observation_only": True,
        "note": "One VLM observation cannot certify first LIVE or authorize an EDL change.",
    }


def run_one_window(api: Any, video: Path, selected: Mapping[str, Any], work_dir: Path) -> dict[str, Any]:
    """Directly call ONE existing observer, avoiding automatic followup loops."""
    from story_video_agent.frames import FrameBudget, FrameStore
    from story_video_agent.media import probe_video
    from story_video_agent_v3.self_revise_agent import _observe_one_window

    media = probe_video(video)
    store = FrameStore(media, out_dir=work_dir / "frames", budget=FrameBudget(max_frames=4))
    tr = selected["request"]
    return _observe_one_window(
        api, store=store, tr=tr,
        win=selected["selected_window"],
        allowed_windows=tr["search_windows"],
        request_id=str(tr.get("request_id") or "goal") + "_single_window",
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    p.add_argument("--planner-smoke", type=Path, default=DEFAULT_PLANNER_SMOKE)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--one-call", action="store_true")
    p.add_argument("--i-approve-one-call", action="store_true")
    args = p.parse_args()
    if args.one_call != args.i_approve_one_call:
        p.error("Real VLM requires BOTH --one-call and --i-approve-one-call")
    run = args.run_dir.resolve()
    smoke_path = args.planner_smoke.resolve()
    out = args.out_dir.resolve()
    if not run.is_dir() or not smoke_path.is_file():
        p.error("Fresh run or Planner smoke JSON missing")
    if out.exists():
        p.error("Output directory must be new; never overwrite existing experiment")
    if out == run or run in out.parents or out == smoke_path.parent or smoke_path.parent in out.parents:
        p.error("Output directory cannot be inside previous experiment")
    report: dict[str, Any] = {
        "schema": "v3a_A_vlm_one_call_v1",
        "status": "started",
        "run": str(run),
        "planner_smoke": str(smoke_path),
        "real_http_authorized": bool(args.one_call),
        "real_http_attempts": 0,
        "planner_calls": 0, "verifier_calls": 0, "vlm_calls": 0,
        "edl_modified": False, "rendered": False,
        "render_ready": False, "release_decision": "NOT_AUTHORIZED",
    }
    out.mkdir(parents=True)
    api = None
    try:
        smoke = read_json(smoke_path)
        ctx = read_json(run / "05_v3a/round_01/planner_context.json")
        manifest = read_json(run / "00_input_manifest.json")
        video = Path(manifest["sources"]["video"]["path"]).resolve()
        if not video.is_file():
            raise FileNotFoundError(f"Original video missing: {video}")
        expected_size = manifest["sources"]["video"].get("size_bytes")
        if expected_size is not None and video.stat().st_size != int(expected_size):
            raise ValueError("Original video size differs from fresh run manifest")
        phase5 = read_json(run / "01_to_04_fresh_v3r/04_phase5/phase5_manifest.json")
        if Path(phase5["inputs"]["video"]).resolve() != video:
            raise ValueError("Video path not the original fresh V3-R input")
        selected = select_goal_request(smoke, ctx)
        report["selected_tool"] = selected
        report["video"] = {"path": str(video), "size_bytes": video.stat().st_size,
                           "sha256_from_prior_manifest": manifest["sources"]["video"].get("sha256")}
        api, preflight = configure_vision()
        report["preflight"] = preflight
        write_json(out / "preflight.json", report)
        if args.one_call:
            started = time.perf_counter()
            observation = run_one_window(api, video, selected, out)
            elapsed = time.perf_counter() - started
            report["elapsed_sec_including_frame_extraction"] = round(elapsed, 3)
            report["vlm_calls"] = api.status()["http_attempts"]
            report["real_http_attempts"] = api.status()["http_attempts"]
            report["api_usage"] = api.status()["usage"]
            report["observation"] = observation
            report["evidence"] = evaluate_observation(observation)
            report["status"] = report["evidence"]["gate"]
            write_json(out / "observation.json", observation)
            write_json(out / "evidence_assessment.json", report["evidence"])
        else:
            report["status"] = "PREFLIGHT_ONLY_NO_HTTP"
    except Exception as exc:
        report["status"] = "VLM_DIAGNOSTIC_FAILED"
        report["error_type"] = type(exc).__name__
        # Do not print or persist raw provider errors that might contain sensitive URLs.
        report["error_note"] = "Inspect local sanitized provider logs; no automatic retry."
    finally:
        if api is not None:
            report["real_http_attempts"] = api.status()["http_attempts"]
            report["vlm_calls"] = api.status()["http_attempts"]
            report["api_usage"] = api.status()["usage"]
        write_json(out / "vlm_smoke_summary.json", report)
    print(json.dumps({
        "status": report["status"],
        "output": str(out),
        "http_attempts": report["real_http_attempts"],
        "planner_calls": 0, "verifier_calls": 0,
    }, ensure_ascii=False))
    return 0 if report["status"] in ("PREFLIGHT_ONLY_NO_HTTP", "VLM_OBSERVATION_WITH_PTS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
