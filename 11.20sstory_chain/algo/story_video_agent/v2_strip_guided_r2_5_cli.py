"""Strip-Guided Round 2.5 fix — live-only hard gates + final MP4 visual audit."""

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
from story_video_agent.v2_strip_guided_r2_5_event_replay_audit import (
    audit_event_replay_fields,
    event_labels_overlapping,
)
from story_video_agent.v2_strip_guided_r2_5_final_mp4_audit import audit_final_mp4_goals
from story_video_agent.v2_strip_guided_r2_5_live_only import (
    audit_goal_clip_live,
    audit_strip_live,
    build_live_only_edl,
    diagnose_r24_ke3,
    goal_live_core_window,
    goal_search_neighborhood,
)
from story_video_agent.vision_provider import VisionProvider

DEFAULT_R24 = Path("/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_4_20261029_192839")
DEFAULT_EVENTS = Path(
    "/data2/lpy1/causal-chain2/8.31causal_chain/data/交付_out/2022-11-28 克罗地亚vs加拿大.json"
)
DEFAULT_R25_PRIOR = Path(
    "/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_5_20261029_211351"
)


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
    return ApiProvider(
        force_mock=True,
        require_real=False,
        max_calls=max_calls,
        max_cost_usd=max_cost,
        max_completion_tokens=max_tokens,
    )


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="V2 Strip-Guided Round 2.5 live-only acceptance fix")
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--r24-dir", type=Path, default=DEFAULT_R24)
    p.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    p.add_argument("--prior-r25-dir", type=Path, default=DEFAULT_R25_PRIOR)
    p.add_argument("--real", action="store_true")
    p.add_argument("--skip-render", action="store_true")
    p.add_argument("--skip-final-mp4-audit", action="store_true")
    p.add_argument("--max-api-calls", type=int, default=96)
    p.add_argument("--max-cost-usd", type=float, default=6.0)
    p.add_argument("--max-completion-tokens", type=int, default=4096)
    p.add_argument("--frame-budget", type=int, default=280)
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    r24 = Path(args.r24_dir)
    t0 = time.time()

    ke_doc = json.loads((r24 / "full_match_key_events.json").read_text(encoding="utf-8"))
    edl24 = json.loads((r24 / "candidate_edl.json").read_text(encoding="utf-8"))
    _write(out_dir / "full_match_key_events.json", ke_doc)

    diag = diagnose_r24_ke3(r24)
    _write(out_dir / "ke3_2_1_diagnosis.json", diag)

    # --- Task 1: event replay field audit against R2.4 EDL spans + goal neighborhoods ---
    edl_spans: List[Dict[str, Any]] = []
    for s in edl24.get("segments") or []:
        if s.get("media_in") is None:
            continue
        edl_spans.append(
            {
                "segment_id": s.get("segment_id"),
                "role": s.get("role"),
                "media_in": s.get("media_in"),
                "media_out": s.get("media_out"),
                "node_id": (s.get("source_node_ids") or [None])[0],
            }
        )
    for ke in ke_doc.get("key_events") or []:
        nb = goal_search_neighborhood(ke)
        if nb.get("ok"):
            edl_spans.append(
                {
                    "segment_id": f"neigh_{ke.get('key_event_id')}",
                    "role": "goal_search_neighborhood",
                    "media_in": nb["media_in"],
                    "media_out": nb["media_out"],
                    "key_event_id": ke.get("key_event_id"),
                }
            )
    event_audit = audit_event_replay_fields(events_path=Path(args.events), edl_spans=edl_spans)
    _write(out_dir / "event_replay_field_audit.json", event_audit)

    api = _make_api(
        real=bool(args.real),
        max_calls=args.max_api_calls,
        max_cost=args.max_cost_usd,
        max_tokens=args.max_completion_tokens,
    )

    media = probe_video(args.video)
    frames_dir = out_dir / "frames_r25_fix"
    store = FrameStore(media, out_dir=frames_dir, budget=FrameBudget(max_frames=args.frame_budget))
    vision = VisionProvider(api=api, force_mock=bool(api.force_mock))
    tools = V2PhaseC1Toolbox(
        duration=media.duration_sec,
        store=store,
        vision=vision,
        task_note=(
            "LIVE-ONLY HARD GATE. The persistent 直播/Live corner badge is NOT proof the current "
            "picture is live action. In notes MUST include exactly one of: "
            "broadcast_state=live_action OR broadcast_state=replay OR broadcast_state=transition OR "
            "broadcast_state=unknown. Prefer wide/main-camera continuity, match clock advancing, "
            "and natural real-time motion. For goals: explicitly report shot/strike AND ball into "
            "net if visible. Do not invent."
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
            _write(
                out_dir / "cli_report.json",
                {"status": "aborted_preflight", "api_preflight": pf, "render_ready": False},
            )
            return 2

    # --- Goal audits with broadcast timeline ---
    goal_audits: List[Dict[str, Any]] = []
    timeline_bundle: Dict[str, Any] = {
        "schema": "v2_r25_broadcast_timeline_v1",
        "goals": [],
        "strips": [],
        "render_ready": False,
    }
    for ke in ke_doc.get("key_events") or []:
        nb = goal_search_neighborhood(ke)
        overlaps = []
        if nb.get("ok"):
            overlaps = event_labels_overlapping(
                event_audit, float(nb["media_in"]), float(nb["media_out"])
            )
        if store.budget.remaining < 10 or not args.real:
            core = goal_live_core_window(ke)
            goal_audits.append(
                {
                    "key_event_id": ke.get("key_event_id"),
                    "score_before": ke.get("score_before"),
                    "score_after": ke.get("score_after"),
                    "verified_shot_sec": (ke.get("shot_action") or {}).get("media_sec"),
                    "verified_result_sec": (ke.get("goal_result") or {}).get("media_sec"),
                    "core_window": core,
                    "pass": False,
                    "fail_reasons": ["skipped_no_vision_budget_or_mock"],
                    "accepted_media_in": None,
                    "accepted_media_out": None,
                    "unresolved": True,
                    "note": "Mock/budget path must not auto-pass live-only hard gate",
                }
            )
        else:
            row = audit_goal_clip_live(
                ke=ke,
                tools=tools,
                evidence_prefix="r25f_goal",
                event_replay_overlaps=overlaps,
            )
            goal_audits.append(row)
            timeline_bundle["goals"].append(
                {
                    "key_event_id": ke.get("key_event_id"),
                    "score_after": ke.get("score_after"),
                    "broadcast_timeline": row.get("broadcast_timeline"),
                    "located_window": row.get("located_window"),
                    "pass": row.get("pass"),
                    "fail_reasons": row.get("fail_reasons"),
                }
            )

    goal_live_window_audit = {
        "schema": "v2_r25_goal_live_window_audit_v1",
        "goals": goal_audits,
        "n_pass": sum(1 for g in goal_audits if g.get("pass")),
        "n_unresolved": sum(1 for g in goal_audits if g.get("unresolved")),
        "all_five_pass": len(goal_audits) == 5 and all(g.get("pass") for g in goal_audits),
        "policy": "No badge-only live; no timestamp autofill for shot/net; unknown/replay/mixed fail",
        "render_ready": False,
    }
    _write(out_dir / "goal_live_window_audit.json", goal_live_window_audit)

    # --- Strip audits ---
    strip_audits: List[Dict[str, Any]] = []
    replay_rows: List[Dict[str, Any]] = []
    for s in edl24.get("segments") or []:
        if s.get("role") != "strip_context":
            continue
        nid = (s.get("source_node_ids") or [None])[0]
        tin, tout = s.get("media_in"), s.get("media_out")
        if nid is None or tin is None:
            continue
        overlaps = event_labels_overlapping(event_audit, float(tin), float(tout or tin))
        if store.budget.remaining < 6 or not args.real:
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
            evidence_prefix="r25f_strip",
            event_replay_overlaps=overlaps,
        )
        strip_audits.append(row)
        timeline_bundle["strips"].append(
            {
                "node_id": nid,
                "broadcast_timeline": row.get("broadcast_timeline"),
                "pass_live_only": row.get("pass_live_only"),
                "fail_reasons": row.get("fail_reasons"),
            }
        )
        replay_rows.append(
            {
                "node_id": nid,
                "kind": "strip",
                "pass_live_only": row.get("pass_live_only"),
                "fail_reasons": row.get("fail_reasons"),
                "window": {
                    "media_in": row.get("accepted_media_in"),
                    "media_out": row.get("accepted_media_out"),
                },
            }
        )

    for g in goal_audits:
        replay_rows.append(
            {
                "node_id": g.get("key_event_id"),
                "kind": "goal",
                "live_or_replay": g.get("live_or_replay"),
                "pass_live_only": g.get("pass"),
                "fail_reasons": g.get("fail_reasons"),
                "window": {
                    "media_in": g.get("accepted_media_in"),
                    "media_out": g.get("accepted_media_out"),
                },
            }
        )

    _write(out_dir / "broadcast_timeline.json", timeline_bundle)
    _write(
        out_dir / "replay_segment_audit.json",
        {
            "schema": "v2_r25_replay_segment_audit_v1",
            "rows": replay_rows,
            "n_replay_or_fail": sum(1 for r in replay_rows if not r.get("pass_live_only")),
            "render_ready": False,
        },
    )

    edl_live = build_live_only_edl(
        goal_audits=goal_audits,
        strip_audits=strip_audits,
        r24_segments=edl24.get("segments") or [],
    )
    _write(out_dir / "edl_live_only.json", edl_live)
    _write(out_dir / "candidate_edl.json", edl_live)

    story_complete_pre = bool(edl_live.get("gates", {}).get("story_complete_candidate"))
    render_manifest = None
    out_clean = out_dir / "story_clean_live_only.mp4"
    out_qc = out_dir / "story_qc_live_only.mp4"

    if not args.skip_render and edl_live.get("n_goal_segments", 0) > 0:
        render_manifest = render_r23_candidates(video=args.video, edl=edl_live, out_dir=out_dir)
        src_c = out_dir / "story_clean_candidate.mp4"
        src_q = out_dir / "story_qc_candidate.mp4"
        if src_c.exists():
            src_c.replace(out_clean)
        if src_q.exists():
            src_q.replace(out_qc)

    # --- Final MP4 visual audit (mandatory for acceptance) ---
    final_audit: Dict[str, Any] = {
        "schema": "v2_r25_final_mp4_visual_audit_v1",
        "skipped": True,
        "all_five_goals_visual_pass": False,
        "acceptance_failed": True,
        "render_ready": False,
    }
    if (
        not args.skip_final_mp4_audit
        and args.real
        and out_clean.is_file()
        and edl_live.get("n_goal_segments", 0) > 0
    ):
        final_audit = audit_final_mp4_goals(
            story_mp4=out_clean,
            edl=edl_live,
            goal_audits=goal_audits,
            vision=vision,
            frames_dir=out_dir / "frames_final_mp4",
            # Independent budget — never depend on exhausted source-video frame store.
            max_frames=80,
        )
    _write(out_dir / "final_mp4_visual_audit.json", final_audit)

    # Integrity doc merges window + final visual
    playback_map = []
    play_t = 0.0
    for s in edl_live.get("segments") or []:
        dur = float(s.get("duration_sec") or 0)
        if s.get("role") == "goal":
            kid = (s.get("source_node_ids") or [None])[0]
            vis = next((x for x in final_audit.get("goals") or [] if x.get("key_event_id") == kid), {})
            playback_map.append(
                {
                    "key_event_id": kid,
                    "score_label": next(
                        (
                            f"{g.get('score_before')}->{g.get('score_after')}"
                            for g in goal_audits
                            if g.get("key_event_id") == kid
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
                    "window_pass": next(
                        (g.get("pass") for g in goal_audits if g.get("key_event_id") == kid), False
                    ),
                    "final_mp4_pass": vis.get("pass"),
                    "final_mp4_fail_reasons": vis.get("fail_reasons"),
                    "integrity_pass": bool(
                        next((g.get("pass") for g in goal_audits if g.get("key_event_id") == kid), False)
                    )
                    and bool(vis.get("pass")),
                }
            )
        play_t += dur

    visual_all = bool(final_audit.get("all_five_goals_visual_pass"))
    story_complete = story_complete_pre and visual_all
    if not visual_all:
        edl_live.setdefault("gates", {})["story_complete_candidate"] = False
        edl_live.setdefault("gates", {})["all_five_goals_pass"] = False
        edl_live.setdefault("gates", {})["final_mp4_visual_pass"] = False
        edl_live["story_complete_blocked_reason"] = "final_mp4_visual_audit_failed"
        _write(out_dir / "edl_live_only.json", edl_live)

    goal_doc = {
        "schema": "v2_r25_goal_clip_integrity_audit_v1",
        "n_goals": len(goal_audits),
        "n_pass_window": sum(1 for g in goal_audits if g.get("pass")),
        "n_pass_final_mp4": sum(1 for g in (final_audit.get("goals") or []) if g.get("pass")),
        "goals": goal_audits,
        "playback_map": playback_map,
        "ke3_diagnosis": diag,
        "all_five_pass": story_complete,
        "story_complete_candidate": story_complete,
        "final_mp4_visual_audit_ref": str(out_dir / "final_mp4_visual_audit.json"),
        "render_ready": False,
    }
    _write(out_dir / "goal_clip_integrity_audit.json", goal_doc)

    # Before/after comparison vs prior R2.5
    prior = Path(args.prior_r25_dir)
    comparison = {
        "schema": "v2_r25_fix_before_after_v1",
        "prior_dir": str(prior),
        "prior_issues": [
            "all_five_goals_pass=true without final MP4 visual gate",
            "直播 badge treated as live evidence",
            "verified PTS could autofill missing shot/net observation",
            "unknown status could pass",
            "0:1 window started near net — missing pre-shot approach",
            "2:1 story 31–39s dominated by goal-line multi-angle; post-goal replay risk",
            "4:1 truncated early before full result/celebration",
        ],
        "fix_changes": [
            "event_replay_field_audit on real events.json",
            "broadcast_timeline multi-slice live/replay/transition/unknown",
            "hard fail for replay/mixed/unknown; no badge-only; no PTS autofill",
            "final_mp4_visual_audit required for story_complete_candidate",
        ],
        "prior_edl_exists": (prior / "edl_live_only.json").is_file(),
        "new_edl": str(out_dir / "edl_live_only.json"),
        "new_clean": str(out_clean),
        "render_ready": False,
    }
    if (prior / "edl_live_only.json").is_file():
        old = json.loads((prior / "edl_live_only.json").read_text(encoding="utf-8"))
        comparison["prior_goal_windows"] = [
            {
                "nid": (s.get("source_node_ids") or [None])[0],
                "media_in": s.get("media_in"),
                "media_out": s.get("media_out"),
            }
            for s in old.get("segments") or []
            if s.get("role") == "goal"
        ]
        comparison["new_goal_windows"] = [
            {
                "nid": (s.get("source_node_ids") or [None])[0],
                "media_in": s.get("media_in"),
                "media_out": s.get("media_out"),
            }
            for s in edl_live.get("segments") or []
            if s.get("role") == "goal"
        ]
    _write(out_dir / "before_after_video_issues.json", comparison)

    report = {
        "schema": "v2_strip_guided_r2_5_fix_report_v1",
        "git_sha": _git_sha(),
        "elapsed_sec": round(time.time() - t0, 3),
        "r24_dir": str(r24),
        "events_path": str(args.events),
        "event_replay_field_summary": {
            "n_events": event_audit.get("n_events"),
            "is_replay_counts": event_audit.get("is_replay_counts"),
            "broadcast_phase_counts": event_audit.get("broadcast_phase_counts"),
            "is_slow_motion_counts": event_audit.get("is_slow_motion_counts"),
            "n_edl_spans_uncovered": event_audit.get("n_edl_spans_uncovered"),
            "incomplete_notes": event_audit.get("incomplete_notes"),
        },
        "n_goals_window_pass": goal_live_window_audit.get("n_pass"),
        "n_goals_final_mp4_pass": goal_doc.get("n_pass_final_mp4"),
        "all_five_goals_pass": story_complete,
        "story_complete_candidate": story_complete,
        "n_strips_kept": edl_live.get("n_non_goal_strip_segments"),
        "n_strips_dropped": len(edl_live.get("dropped_segments") or []),
        "api_stats": api.stats.summary(),
        "artifacts": {
            "event_replay_field_audit": str(out_dir / "event_replay_field_audit.json"),
            "broadcast_timeline": str(out_dir / "broadcast_timeline.json"),
            "goal_live_window_audit": str(out_dir / "goal_live_window_audit.json"),
            "final_mp4_visual_audit": str(out_dir / "final_mp4_visual_audit.json"),
            "goal_clip_integrity_audit": str(out_dir / "goal_clip_integrity_audit.json"),
            "replay_segment_audit": str(out_dir / "replay_segment_audit.json"),
            "edl_live_only": str(out_dir / "edl_live_only.json"),
            "before_after_video_issues": str(out_dir / "before_after_video_issues.json"),
            "story_clean_live_only": str(out_clean),
            "story_qc_live_only": str(out_qc),
        },
        "render_manifest": render_manifest,
        "render_ready": False,
        "acceptance": {
            "go_ahead_2_1_present": any(
                (g.get("score_after") or []) == [2, 1] and g.get("pass") for g in goal_audits
            )
            and any(
                (x.get("score_after") or []) == [2, 1] and x.get("pass")
                for x in (final_audit.get("goals") or [])
            ),
            "five_goals_live_complete": story_complete,
            "final_mp4_visual_pass": visual_all,
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
                    "n_goals_window_pass",
                    "n_goals_final_mp4_pass",
                    "all_five_goals_pass",
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
