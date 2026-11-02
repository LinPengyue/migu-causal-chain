"""Offline V1 input parity: 8.31→V1 auto causal vs human causal (compare only).

Human `*_causal.json` is loaded ONLY for offline comparison after V1 runs.
It is never passed into the adapter / strip generation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from story_chain.end_to_end import run_paths

from .pipeline import dump
from .v1_causal_adapter import build_from_paths


def _story_summary(story: Dict[str, Any]) -> Dict[str, Any]:
    evs = story.get("events") or []
    types = [e.get("type") for e in evs]
    goals = [e for e in evs if e.get("type") in {"进球", "乌龙球", "头球破门"}]
    return {
        "has_story": bool(story.get("has_story")),
        "is_candidate": bool(story.get("is_candidate")),
        "n_story_events": len(evs),
        "n_goal_events": len(goals),
        "goal_t_ms": [e.get("t_ms") for e in goals],
        "goal_event_ids": [e.get("event_id") for e in goals],
        "event_types_head": types[:40],
        "roles": sorted({e.get("role") for e in evs if e.get("role")}),
        "score_path_len": len(story.get("score_path") or story.get("score_nodes") or []),
        "missing": story.get("missing") or story.get("gaps") or story.get("unresolved"),
        "story_keys": sorted(story.keys())[:40],
    }


def _compare(human: Dict[str, Any], auto: Dict[str, Any], adapter_meta: Dict[str, Any]) -> Dict[str, Any]:
    h_goals = set(human.get("goal_t_ms") or [])
    a_goals = set(auto.get("goal_t_ms") or [])
    return {
        "human_has_story": human.get("has_story"),
        "auto_has_story": auto.get("has_story"),
        "human_n_goals": human.get("n_goal_events"),
        "auto_n_goals": auto.get("n_goal_events"),
        "human_goal_t_ms": human.get("goal_t_ms"),
        "auto_goal_t_ms": auto.get("goal_t_ms"),
        "goals_only_in_human": sorted(h_goals - a_goals),
        "goals_only_in_auto": sorted(a_goals - h_goals),
        "adapter_event_coverage": adapter_meta.get("event_id_coverage"),
        "adapter_n_outcome": adapter_meta.get("n_outcome_chains_en"),
        "adapter_n_goal_terminals": adapter_meta.get("n_goal_terminals_in_adapted_chains"),
        "adapter_unresolved_goal_actions": adapter_meta.get("n_unresolved_goal_actions"),
        "bottleneck_verdict": (
            "8.31_and_raw_events_lack_Goal_terminals; "
            "V1_requires_Chinese_Goal_t_ms_near_scoreboard; "
            "not_a_V1_planner_bug"
        ),
        "render_ready": False,
    }


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="V3→V1 causal parity (no paid API, no gold in adapter)")
    p.add_argument("--events", type=Path, required=True)
    p.add_argument("--strip", type=Path, required=True, help="Frozen 8.31 reinfer strip JSON")
    p.add_argument("--human-causal", type=Path, required=True, help="Offline compare ONLY")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--match-id", required=True)
    p.add_argument("--video-name", required=True)
    p.add_argument("--team-1-name", default="")
    p.add_argument("--team-2-name", default="")
    args = p.parse_args(argv)

    dest = Path(args.out_dir)
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"Refusing nonempty out dir: {dest}")
    dest.mkdir(parents=True, exist_ok=True)

    auto_path = dest / "auto_v1_compatible_causal.json"
    doc = build_from_paths(
        strip_path=args.strip,
        events_path=args.events,
        out_path=auto_path,
        match_id=args.match_id,
        video_name=args.video_name,
        team_1_name=args.team_1_name,
        team_2_name=args.team_2_name,
    )
    meta = doc.get("v3_adapter") or {}
    dump(dest / "adapter_meta.json", meta)

    # Stock V1 on AUTO causal (generation path)
    auto_story = run_paths(args.events, auto_path)
    dump(dest / "v1_story_from_auto_causal.json", auto_story)
    auto_sum = _story_summary(auto_story)
    dump(dest / "v1_story_summary_auto.json", auto_sum)

    # Stock V1 on HUMAN causal (offline compare only — not fed to adapter)
    human_story = run_paths(args.events, args.human_causal)
    dump(dest / "v1_story_from_human_causal_COMPARE_only.json", human_story)
    human_sum = _story_summary(human_story)
    dump(dest / "v1_story_summary_human_compare_only.json", human_sum)

    cmp_ = _compare(human_sum, auto_sum, meta)
    dump(dest / "parity_compare.json", cmp_)

    log = {
        "schema": "v3_v1_input_parity_run_v1",
        "match_id": args.match_id,
        "strip": str(args.strip),
        "events": str(args.events),
        "auto_causal": str(auto_path),
        "human_causal_compare_only": str(args.human_causal),
        "human_causal_used_in_adapter": False,
        "paid_api_calls": 0,
        "compare": cmp_,
        "auto_summary": auto_sum,
        "human_summary_compare_only": human_sum,
        "render_ready": False,
    }
    dump(dest / "parity_run_log.json", log)
    print(json.dumps({
        "status": "ok",
        "auto_n_goals": auto_sum.get("n_goal_events"),
        "human_n_goals": human_sum.get("n_goal_events"),
        "auto_has_story": auto_sum.get("has_story"),
        "human_has_story": human_sum.get("has_story"),
        "event_coverage": meta.get("event_id_coverage"),
        "unresolved_goal_actions": meta.get("n_unresolved_goal_actions"),
        "out_dir": str(dest),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
