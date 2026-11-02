"""P5: Goal recovery → V1-compatible causal → stock V1 story/compose (no paid API)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from story_chain.end_to_end import run_paths
from story_video_agent.narrative_composer import compose_from_paths

from .goal_recovery import (
    build_b_opening_p3_overlay,
    default_g22_overlay_paths,
    recover_match_goals,
)
from .pipeline import dump
from .v1_causal_adapter import build_from_paths


def _story_goal_summary(story: Dict[str, Any]) -> Dict[str, Any]:
    goals = [
        e for e in (story.get("events") or [])
        if e.get("type") in {"进球", "乌龙球", "头球破门"}
    ]
    return {
        "has_story": bool(story.get("has_story")),
        "n_story_events": len(story.get("events") or []),
        "n_goal_events": len(goals),
        "goals": [
            {
                "event_id": g.get("event_id"),
                "t_ms": g.get("t_ms"),
                "t_sec": (float(g["t_ms"]) / 1000.0) if g.get("t_ms") is not None else None,
                "story_role": g.get("story_role"),
                "is_replay": g.get("is_replay"),
                "score_context": g.get("score_context"),
                "source_annotation_id": g.get("source_annotation_id"),
            }
            for g in goals
        ],
    }


def _compose_windows(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    acc: List[Dict[str, Any]] = []

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            if "media_in" in o or "role" in o:
                role = o.get("role")
                if role or o.get("media_in") is not None:
                    acc.append({
                        "media_in": o.get("media_in"),
                        "media_out": o.get("media_out"),
                        "role": role,
                        "beat": o.get("beat"),
                        "is_replay": o.get("is_replay"),
                    })
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(plan)
    # dedupe by role+media
    seen = set()
    out = []
    for w in acc:
        key = (w.get("role"), w.get("media_in"), w.get("media_out"))
        if key in seen:
            continue
        seen.add(key)
        out.append(w)
    return out


def _filter_v3_final_edl(windows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """V3 final EDL: drop replay supplements; keep live goal_action / anchors / buildup."""
    kept = []
    dropped = []
    for w in windows:
        role = str(w.get("role") or "")
        if w.get("is_replay") or role.endswith("replay_supplement") or "replay" in role:
            dropped.append(w)
            continue
        kept.append(w)
    goal_actions = [w for w in kept if str(w.get("role") or "").endswith("goal_action")]
    missing_goal = [w for w in goal_actions if w.get("media_in") is None]
    return {
        "n_kept": len(kept),
        "n_dropped_replay": len(dropped),
        "kept": kept,
        "dropped_replay": dropped,
        "n_live_goal_action_with_pts": sum(1 for w in goal_actions if w.get("media_in") is not None),
        "n_goal_action_missing_pts": len(missing_goal),
        "render_ready": False,
        "note": "Replay excluded for V3 final EDL view; render_ready stays false without full QC",
    }


def run_match(
    *,
    tag: str,
    events: Path,
    strip: Path,
    human_causal_compare_only: Path,
    out_dir: Path,
    match_id: str,
    video_name: str,
    team_1: str,
    team_2: str,
    g22_tag: str,
    include_b_opening_overlay: bool,
) -> Dict[str, Any]:
    dest = Path(out_dir)
    if dest.exists() and any(dest.iterdir()):
        raise RuntimeError(f"Refusing nonempty out dir: {dest}")
    dest.mkdir(parents=True, exist_ok=True)

    overlays = default_g22_overlay_paths(g22_tag)
    extra = [build_b_opening_p3_overlay()] if include_b_opening_overlay else []
    recovery = recover_match_goals(
        events_path=events,
        strip_path=strip,
        overlay_paths=overlays,
        extra_overlays=extra,
        out_path=dest / "goal_recovery.json",
    )
    dump(dest / "overlay_paths_used.json", {
        "g22": [str(p) for p in overlays],
        "extra": [e.get("source") for e in extra],
        "human_causal_used": False,
    })

    auto_causal = build_from_paths(
        strip_path=strip,
        events_path=events,
        out_path=dest / "auto_v1_compatible_causal.json",
        match_id=match_id,
        video_name=video_name,
        team_1_name=team_1,
        team_2_name=team_2,
        recovered_goals=recovery.get("candidates") or [],
    )

    # BEFORE snapshot: strip-only causal (no recovered goals)
    before_causal = build_from_paths(
        strip_path=strip,
        events_path=events,
        out_path=dest / "auto_v1_compatible_causal_BEFORE_goal_recovery.json",
        match_id=match_id,
        video_name=video_name,
        team_1_name=team_1,
        team_2_name=team_2,
        recovered_goals=[],
    )

    story_before = run_paths(events, dest / "auto_v1_compatible_causal_BEFORE_goal_recovery.json")
    story_after = run_paths(events, dest / "auto_v1_compatible_causal.json")
    story_human = run_paths(events, human_causal_compare_only)
    dump(dest / "v1_story_BEFORE.json", story_before)
    dump(dest / "v1_story_AFTER.json", story_after)
    dump(dest / "v1_story_HUMAN_compare_only.json", story_human)

    sum_before = _story_goal_summary(story_before)
    sum_after = _story_goal_summary(story_after)
    sum_human = _story_goal_summary(story_human)
    dump(dest / "story_summary_BEFORE.json", sum_before)
    dump(dest / "story_summary_AFTER.json", sum_after)
    dump(dest / "story_summary_HUMAN_compare_only.json", sum_human)

    plan_after = compose_from_paths(
        str(dest / "v1_story_AFTER.json"),
        causal_path=str(dest / "auto_v1_compatible_causal.json"),
        use_llm=False,
        out_json=str(dest / "compose_AFTER" / "story_plan.json"),
    )
    (dest / "compose_AFTER").mkdir(parents=True, exist_ok=True)
    windows_after = _compose_windows(plan_after)
    dump(dest / "compose_AFTER" / "windows.json", windows_after)
    v3_edl = _filter_v3_final_edl(windows_after)
    dump(dest / "compose_AFTER" / "v3_final_edl_replay_filtered.json", v3_edl)

    plan_before = compose_from_paths(
        str(dest / "v1_story_BEFORE.json"),
        causal_path=str(dest / "auto_v1_compatible_causal_BEFORE_goal_recovery.json"),
        use_llm=False,
        out_json=str(dest / "compose_BEFORE" / "story_plan.json"),
    )
    (dest / "compose_BEFORE").mkdir(parents=True, exist_ok=True)
    windows_before = _compose_windows(plan_before)
    dump(dest / "compose_BEFORE" / "windows.json", windows_before)

    plan_human = compose_from_paths(
        str(dest / "v1_story_HUMAN_compare_only.json"),
        causal_path=str(human_causal_compare_only),
        use_llm=False,
        out_json=str(dest / "compose_HUMAN_compare_only" / "story_plan.json"),
    )
    (dest / "compose_HUMAN_compare_only").mkdir(parents=True, exist_ok=True)
    windows_human = _compose_windows(plan_human)
    dump(dest / "compose_HUMAN_compare_only" / "windows.json", windows_human)

    report = {
        "schema": "v3_p5_match_run_v1",
        "tag": tag,
        "match_id": match_id,
        "goal_recovery": {
            "n_candidates": recovery.get("n_candidates"),
            "n_single_goal": recovery.get("n_single_goal"),
            "n_with_goal_action_sec": recovery.get("n_with_goal_action_sec"),
            "candidates": recovery.get("candidates"),
        },
        "v1_adapter": auto_causal.get("v3_adapter"),
        "story_BEFORE": sum_before,
        "story_AFTER": sum_after,
        "story_HUMAN_compare_only": sum_human,
        "compose_BEFORE_goal_actions": [
            w for w in windows_before if str(w.get("role") or "").endswith("goal_action")
        ],
        "compose_AFTER_goal_actions": [
            w for w in windows_after if str(w.get("role") or "").endswith("goal_action")
        ],
        "compose_HUMAN_goal_actions": [
            w for w in windows_human if str(w.get("role") or "").endswith("goal_action")
        ],
        "v3_final_edl_replay_filtered": v3_edl,
        "paid_api_calls": 0,
        "human_causal_used_in_generation": False,
        "render_ready": False,
    }
    dump(dest / "p5_run_report.json", report)
    return report


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tag", required=True)
    p.add_argument("--events", type=Path, required=True)
    p.add_argument("--strip", type=Path, required=True)
    p.add_argument("--human-causal-compare-only", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--match-id", required=True)
    p.add_argument("--video-name", required=True)
    p.add_argument("--team-1", default="")
    p.add_argument("--team-2", default="")
    p.add_argument("--g22-tag", required=True)
    p.add_argument("--b-opening-overlay", action="store_true")
    args = p.parse_args(argv)
    rep = run_match(
        tag=args.tag,
        events=args.events,
        strip=args.strip,
        human_causal_compare_only=args.human_causal_compare_only,
        out_dir=args.out_dir,
        match_id=args.match_id,
        video_name=args.video_name,
        team_1=args.team_1,
        team_2=args.team_2,
        g22_tag=args.g22_tag,
        include_b_opening_overlay=bool(args.b_opening_overlay),
    )
    print(json.dumps({
        "tag": args.tag,
        "n_goals_before": rep["story_BEFORE"]["n_goal_events"],
        "n_goals_after": rep["story_AFTER"]["n_goal_events"],
        "n_goals_human": rep["story_HUMAN_compare_only"]["n_goal_events"],
        "after_goal_actions": rep["compose_AFTER_goal_actions"],
        "recovery_with_action": rep["goal_recovery"]["n_with_goal_action_sec"],
        "out_dir": str(args.out_dir),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
