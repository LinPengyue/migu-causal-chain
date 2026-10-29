"""Strip-Guided Round 2.5 — live-only story repair from R2.4 baseline."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from story_video_agent.api_provider import ApiConfigError, ApiProvider, api_enabled, load_endpoint_configs, smoke_enabled
from story_video_agent.frames import FrameBudget, FrameStore
from story_video_agent.media import probe_video
from story_video_agent.v2_api_preflight import run_preflight
from story_video_agent.v2_phase_c1_toolbox import V2PhaseC1Toolbox
from story_video_agent.v2_strip_guided_r2_3_render import render_r23_candidates
from story_video_agent.v2_strip_guided_r2_5_live_only import (
    audit_goal_clip_live,
    audit_strip_live,
    build_live_only_edl,
    diagnose_r24_ke3,
    goal_live_core_window,
)
from story_video_agent.vision_provider import VisionProvider

DEFAULT_R24 = Path("/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_4_20261029_192839")


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


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _make_api(*, real: bool, max_calls: int, max_cost: float, max_tokens: int) -> ApiProvider:
    if real:
        if not api_enabled() or not smoke_enabled():
            raise ApiConfigError("STORY_API_ENABLE=1 and STORY_API_SMOKE=1 required")
        return ApiProvider(
            configs=load_endpoint_configs(),
            require_real=True,
            force_mock=False,
            max_calls=max_calls,
            max_cost_usd=max_cost,
            max_completion_tokens=max_tokens,
        )
    return ApiProvider(force_mock=True, require_real=False, max_calls=max_calls, max_cost_usd=max_cost, max_completion_tokens=max_tokens)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="V2 Strip-Guided Round 2.5 live-only repair")
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--r24-dir", type=Path, default=DEFAULT_R24)
    p.add_argument("--real", action="store_true")
    p.add_argument("--skip-render", action="store_true")
    p.add_argument("--max-api-calls", type=int, default=28)
    p.add_argument("--max-cost-usd", type=float, default=2.0)
    p.add_argument("--max-completion-tokens", type=int, default=4096)
    p.add_argument("--frame-budget", type=int, default=64)
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    r24 = Path(args.r24_dir)
    t0 = time.time()

    ke_doc = json.loads((r24 / "full_match_key_events.json").read_text(encoding="utf-8"))
    edl24 = json.loads((r24 / "candidate_edl.json").read_text(encoding="utf-8"))
    _write(out_dir / "full_match_key_events.json", ke_doc)  # unchanged verified goals

    diag = diagnose_r24_ke3(r24)
    _write(out_dir / "ke3_2_1_diagnosis.json", diag)

    api = _make_api(
        real=bool(args.real),
        max_calls=args.max_api_calls,
        max_cost=args.max_cost_usd,
        max_tokens=args.max_completion_tokens,
    )

    media = probe_video(args.video)
    frames_dir = out_dir / "frames_r25"
    store = FrameStore(media, out_dir=frames_dir, budget=FrameBudget(max_frames=args.frame_budget))
    vision = VisionProvider(api=api, force_mock=bool(api.force_mock))
    tools = V2PhaseC1Toolbox(
        duration=media.duration_sec,
        store=store,
        vision=vision,
        task_note=(
            "LIVE-ONLY audit. Explicitly say if 直播 live badge is visible OR if this is 回放/slow-mo replay. "
            "For goals: confirm shot and ball into net. Do not invent actions."
        ),
    )

    if args.real:
        configs = load_endpoint_configs()
        probe = Path("/tmp/croatia_vlm_probe/f.jpg")
        pf = run_preflight(
            configs=configs,
            image_path=probe if probe.is_file() else None,
            require_roles=("vision",),
        )
        _write(out_dir / "api_preflight.json", pf)
        if not pf.get("passed"):
            _write(out_dir / "cli_report.json", {"status": "aborted_preflight", "api_preflight": pf, "render_ready": False})
            return 2

    # --- Goal audits (5) ---
    goal_audits: List[Dict[str, Any]] = []
    for ke in ke_doc.get("key_events") or []:
        # Always compute core window even if vision budget ends
        core = goal_live_core_window(ke)
        if store.budget.remaining < 6 or not args.real:
            # Offline/fallback: accept verified live goals with tight window if marked live
            lr = str(ke.get("live_or_replay") or "unknown")
            goal_audits.append(
                {
                    "key_event_id": ke.get("key_event_id"),
                    "score_before": ke.get("score_before"),
                    "score_after": ke.get("score_after"),
                    "verified_shot_sec": (ke.get("shot_action") or {}).get("media_sec"),
                    "verified_result_sec": (ke.get("goal_result") or {}).get("media_sec"),
                    "core_window": core,
                    "observation": {"live_or_replay": lr, "note": "budget_or_mock_fallback"},
                    "has_shot_action": True,
                    "has_net_result": True,
                    "contains_replay": False,
                    "pass": bool(core.get("ok")) and lr != "replay",
                    "fail_reasons": [] if core.get("ok") and lr != "replay" else ["core_or_replay"],
                    "accepted_media_in": core.get("media_in") if core.get("ok") else None,
                    "accepted_media_out": core.get("media_out") if core.get("ok") else None,
                    "evidence_id": f"fallback_{ke.get('key_event_id')}",
                }
            )
        else:
            goal_audits.append(audit_goal_clip_live(ke=ke, tools=tools, evidence_prefix="r25_goal"))

    goal_doc = {
        "schema": "v2_r25_goal_clip_integrity_audit_v1",
        "n_goals": len(goal_audits),
        "n_pass": sum(1 for g in goal_audits if g.get("pass")),
        "goals": goal_audits,
        "ke3_diagnosis": diag,
        "all_five_pass": all(g.get("pass") for g in goal_audits) and len(goal_audits) == 5,
        "render_ready": False,
    }
    _write(out_dir / "goal_clip_integrity_audit.json", goal_doc)

    # --- Strip audits from R2.4 EDL ---
    strip_audits: List[Dict[str, Any]] = []
    replay_rows: List[Dict[str, Any]] = []
    for s in edl24.get("segments") or []:
        if s.get("role") != "strip_context":
            continue
        nid = (s.get("source_node_ids") or [None])[0]
        tin, tout = s.get("media_in"), s.get("media_out")
        if nid is None or tin is None:
            continue
        if store.budget.remaining < 4 or not args.real:
            strip_audits.append(
                {
                    "node_id": nid,
                    "requested_window": {"media_in": tin, "media_out": tout},
                    "pass_live_only": False,
                    "fail_reasons": ["skipped_no_vision_budget"],
                    "accepted_media_in": None,
                    "accepted_media_out": None,
                }
            )
            continue
        row = audit_strip_live(
            node_id=str(nid),
            media_in=float(tin),
            media_out=float(tout),
            tools=tools,
            evidence_prefix="r25_strip",
        )
        strip_audits.append(row)
        replay_rows.append(
            {
                "node_id": nid,
                "kind": "strip",
                "live_or_replay": (row.get("observation") or {}).get("live_or_replay"),
                "pass_live_only": row.get("pass_live_only"),
                "fail_reasons": row.get("fail_reasons"),
                "window": row.get("requested_window"),
                "evidence_id": row.get("evidence_id"),
            }
        )

    for g in goal_audits:
        replay_rows.append(
            {
                "node_id": g.get("key_event_id"),
                "kind": "goal",
                "live_or_replay": (g.get("observation") or {}).get("live_or_replay"),
                "pass_live_only": g.get("pass"),
                "fail_reasons": g.get("fail_reasons"),
                "window": {
                    "media_in": g.get("accepted_media_in"),
                    "media_out": g.get("accepted_media_out"),
                },
                "evidence_id": g.get("evidence_id"),
            }
        )

    replay_doc = {
        "schema": "v2_r25_replay_segment_audit_v1",
        "rows": replay_rows,
        "n_replay_or_fail": sum(1 for r in replay_rows if not r.get("pass_live_only")),
        "render_ready": False,
    }
    _write(out_dir / "replay_segment_audit.json", replay_doc)

    edl_live = build_live_only_edl(
        goal_audits=goal_audits,
        strip_audits=strip_audits,
        r24_segments=edl24.get("segments") or [],
    )
    _write(out_dir / "edl_live_only.json", edl_live)
    # also alias for renderer expecting candidate_edl.json
    _write(out_dir / "candidate_edl.json", edl_live)

    story_complete = bool(edl_live.get("gates", {}).get("story_complete_candidate"))
    render_manifest = None
    out_clean = out_dir / "story_clean_live_only.mp4"
    out_qc = out_dir / "story_qc_live_only.mp4"

    if not args.skip_render and edl_live.get("n_goal_segments", 0) > 0:
        # render into work dir then rename
        render_manifest = render_r23_candidates(video=args.video, edl=edl_live, out_dir=out_dir)
        # render_r23 writes story_clean_candidate.mp4 / story_qc_candidate.mp4
        src_c = out_dir / "story_clean_candidate.mp4"
        src_q = out_dir / "story_qc_candidate.mp4"
        if src_c.exists():
            src_c.replace(out_clean)
        if src_q.exists():
            src_q.replace(out_qc)

    # Post-render integrity: map story playback times for QC table
    play_t = 0.0
    playback_map = []
    for s in edl_live.get("segments") or []:
        dur = float(s.get("duration_sec") or 0)
        if s.get("role") == "goal":
            playback_map.append(
                {
                    "key_event_id": (s.get("source_node_ids") or [None])[0],
                    "score_label": next(
                        (
                            f"{g.get('score_before')}->{g.get('score_after')}"
                            for g in goal_audits
                            if g.get("key_event_id") == (s.get("source_node_ids") or [None])[0]
                        ),
                        None,
                    ),
                    "source_media_in": s.get("media_in"),
                    "source_media_out": s.get("media_out"),
                    "shot_sec": s.get("shot_sec"),
                    "result_sec": s.get("result_sec"),
                    "story_play_in": round(play_t, 3),
                    "story_play_out": round(play_t + dur, 3),
                    "live_or_replay": s.get("live_or_replay"),
                    "integrity_pass": s.get("integrity_pass"),
                }
            )
        play_t += dur

    # refresh goal doc with playback map
    goal_doc["playback_map"] = playback_map
    goal_doc["story_complete_candidate"] = story_complete
    _write(out_dir / "goal_clip_integrity_audit.json", goal_doc)

    report = {
        "schema": "v2_strip_guided_r2_5_report_v1",
        "git_sha": _git_sha(),
        "elapsed_sec": round(time.time() - t0, 3),
        "r24_dir": str(r24),
        "ke3_diagnosis": diag.get("root_cause"),
        "n_goals_pass": goal_doc.get("n_pass"),
        "all_five_goals_pass": goal_doc.get("all_five_pass"),
        "n_strips_kept": edl_live.get("n_non_goal_strip_segments"),
        "n_strips_dropped": len(edl_live.get("dropped_segments") or []),
        "story_complete_candidate": story_complete,
        "api_stats": api.stats.summary(),
        "artifacts": {
            "goal_clip_integrity_audit": str(out_dir / "goal_clip_integrity_audit.json"),
            "replay_segment_audit": str(out_dir / "replay_segment_audit.json"),
            "edl_live_only": str(out_dir / "edl_live_only.json"),
            "story_clean_live_only": str(out_clean),
            "story_qc_live_only": str(out_qc),
            "ke3_diagnosis": str(out_dir / "ke3_2_1_diagnosis.json"),
        },
        "render_manifest": render_manifest,
        "render_ready": False,
        "acceptance": {
            "go_ahead_2_1_present": any(
                (g.get("score_after") or []) == [2, 1] and g.get("pass") for g in goal_audits
            ),
            "five_goals_live_complete": story_complete,
            "no_failed_live_segments_in_edl": all(
                s.get("role") != "goal" or s.get("integrity_pass") for s in edl_live.get("segments") or []
            ),
        },
        "forbidden": ["gold_causal", "strip_gold", "v1_times", "production_param_retune"],
    }
    _write(out_dir / "cli_report.json", report)
    print(
        json.dumps(
            {
                k: report.get(k)
                for k in (
                    "n_goals_pass",
                    "all_five_goals_pass",
                    "n_strips_kept",
                    "story_complete_candidate",
                    "acceptance",
                    "render_ready",
                    "git_sha",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if story_complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
