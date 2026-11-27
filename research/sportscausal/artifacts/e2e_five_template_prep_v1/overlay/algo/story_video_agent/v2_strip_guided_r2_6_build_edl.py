"""R2.6: build first-live EDL from an offline live_goal_vs_replay_audit.json (no API)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def build_edl_from_goal_audit(audit: Dict[str, Any]) -> Dict[str, Any]:
    goals = list(audit.get("goals") or [])
    if len(goals) != 5:
        raise ValueError(f"expected 5 goals, got {len(goals)}")
    for g in goals:
        if g.get("verification_status") != "verified_first_live":
            raise ValueError(f"blocked goal {g.get('goal_id')}: {g.get('verification_status')}")
        order = g.get("score_order_check") or {}
        if order and not order.get("ok", True):
            raise ValueError(f"score_order fail {g.get('goal_id')}")

    segments: List[Dict[str, Any]] = []
    play = 0.0

    def add_title(sid: str, beat: str, text: str, dur: float) -> None:
        nonlocal play
        segments.append(
            {
                "segment_id": sid,
                "role": "title_card",
                "beat": beat,
                "duration_sec": dur,
                "story_play_in": round(play, 3),
                "story_play_out": round(play + dur, 3),
                "render_eligibility": "placeholder_title",
                "title_text": text,
                "source_node_ids": [],
                "live_or_replay": "n/a",
                "render_ready": False,
            }
        )
        play += dur

    def add_media(sid: str, role: str, beat: str, tin: float, tout: float, **extra: Any) -> None:
        nonlocal play
        dur = float(tout) - float(tin)
        segments.append(
            {
                "segment_id": sid,
                "role": role,
                "beat": beat,
                "media_in": round(float(tin), 3),
                "media_out": round(float(tout), 3),
                "duration_sec": round(dur, 3),
                "story_play_in": round(play, 3),
                "story_play_out": round(play + dur, 3),
                "render_eligibility": "candidate",
                "live_or_replay": "live",
                "render_ready": False,
                **extra,
            }
        )
        play += dur

    g01, g11, g21, g31, g41 = goals
    add_title("title_open", "setup", "克罗地亚 vs 加拿大 — 逆风翻盘", 2.5)
    add_media(
        "edl_g01",
        "goal",
        "setup",
        g01["accepted_media_in"],
        g01["accepted_media_out"],
        source_node_ids=[g01["key_event_id"]],
        shot_sec=g01["shot_time"],
        result_sec=g01["net_time"],
        score_before=g01["score_before"],
        score_after=g01["score_after"],
        why="opening_deficit_first_live",
    )
    add_media(
        "edl_score_0_1",
        "scoreboard_anchor",
        "setup",
        1078.06,
        1081.56,
        source_node_ids=["event_000004"],
        why="first_LIVE_0_1_board",
        shot_kind="scoreboard_anchor",
    )
    add_media(
        "edl_build_corner_1_1",
        "strip_context",
        "buildup",
        3042.85,
        3055.0,
        source_node_ids=["strip_clip24_trim"],
        why="corner_approach_before_equalizer",
    )
    add_media(
        "edl_g11",
        "goal",
        "turning",
        g11["accepted_media_in"],
        g11["accepted_media_out"],
        source_node_ids=[g11["key_event_id"]],
        shot_sec=g11["shot_time"],
        result_sec=g11["net_time"],
        score_before=g11["score_before"],
        score_after=g11["score_after"],
        why="equalizer_first_live_pre_celebration",
    )
    add_media(
        "edl_g21",
        "goal",
        "climax",
        g21["accepted_media_in"],
        g21["accepted_media_out"],
        source_node_ids=[g21["key_event_id"]],
        shot_sec=g21["shot_time"],
        result_sec=g21["net_time"],
        score_before=g21["score_before"],
        score_after=g21["score_after"],
        why="go_ahead_first_live_scene_cut_cluster",
    )
    add_media(
        "edl_g31",
        "goal",
        "climax",
        g31["accepted_media_in"],
        g31["accepted_media_out"],
        source_node_ids=[g31["key_event_id"]],
        shot_sec=g31["shot_time"],
        result_sec=g31["net_time"],
        score_before=g31["score_before"],
        score_after=g31["score_after"],
        why="lead_extend_first_live_before_6408_confirm",
    )
    add_media(
        "edl_score_3_1",
        "scoreboard_anchor",
        "climax",
        6407.7,
        6411.2,
        source_node_ids=["event_000118"],
        why="LIVE_3_1_board_confirm_not_replay",
        shot_kind="scoreboard_anchor",
    )
    add_media(
        "edl_g41",
        "goal",
        "resolution",
        g41["accepted_media_in"],
        g41["accepted_media_out"],
        source_node_ids=[g41["key_event_id"]],
        shot_sec=g41["shot_time"],
        result_sec=g41["net_time"],
        score_before=g41["score_before"],
        score_after=g41["score_after"],
        why="final_goal_event_000153_first_live",
    )
    add_title(
        "title_close",
        "resolution",
        "End — candidate_ready_for_human_review — render_ready=false",
        2.0,
    )

    return {
        "schema": "v2_r26_final_edl_v1",
        "playout_policy": "first_live_goals_only_no_replay",
        "n_segments": len(segments),
        "n_goal_segments": sum(1 for s in segments if s.get("role") == "goal"),
        "n_non_goal_strip_segments": sum(1 for s in segments if s.get("role") == "strip_context"),
        "total_duration_sec": round(play, 3),
        "segments": segments,
        "gates": {
            "live_only": True,
            "all_five_goals_verified_first_live": True,
            "final_mp4_visual_pass": False,
            "story_complete_candidate": False,
            "candidate_ready_for_human_review": True,
            "render_ready": False,
        },
        "render_ready": False,
        "note": "Built from offline first-live audit; V1 unused as search input; render_ready=false",
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--audit", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    edl = build_edl_from_goal_audit(audit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(edl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "n_goals": edl["n_goal_segments"], "duration": edl["total_duration_sec"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
