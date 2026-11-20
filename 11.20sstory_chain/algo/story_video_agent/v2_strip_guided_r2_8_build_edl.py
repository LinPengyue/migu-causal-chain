"""R2.8 EDL: trim g21 past source band glitch; keep g31 evidence but mark BLOCK; natural 4:1 ending."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def build_r28_edl() -> Dict[str, Any]:
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
                "story_facing_title": True,
                "omit_from_clean": False,
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

    add_title("title_open", "setup", "克罗地亚 vs 加拿大 — 逆风翻盘", 2.5)
    add_media(
        "edl_g01",
        "goal",
        "setup",
        975.8,
        988.0,
        source_node_ids=["ke_r28_0_1"],
        shot_sec=982.063,
        result_sec=982.063,
        score_after=[0, 1],
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
        3055.0,
        3082.0,
        source_node_ids=["ke_r28_1_1"],
        shot_sec=3064.5,
        result_sec=3069.3,
        score_before=[0, 1],
        score_after=[1, 1],
        why="equalizer_first_live",
    )
    # R2.8: skip source band/macroblock at ~3515.85–3516.65 (story 58.2–59.0 in R2.7).
    # 3517.0 is clean wide live; shot 3524 / net 3527.7 / celeb→3533 retained.
    add_media(
        "edl_g21",
        "goal",
        "climax",
        3517.0,
        3533.0,
        source_node_ids=["ke_r28_2_1"],
        shot_sec=3524.0,
        result_sec=3527.7,
        score_before=[1, 1],
        score_after=[2, 1],
        why="go_ahead_first_live_trimmed_past_source_band_glitch",
        r28_trim_note="media_in raised 3515→3517 to exclude source corruption; gray@3535 still excluded",
        source_corruption_trimmed=[{"src_start": 3515.85, "src_end": 3516.65, "kind": "band_macroblock"}],
    )
    # g31: live shot window contains irrecoverable source band glitch ~6315–6316.
    # Keep true first-live evidence; do NOT replace with replay / AI / neighbor frames.
    add_media(
        "edl_g31",
        "goal",
        "climax",
        6305.0,
        6332.0,
        source_node_ids=["ke_r28_3_1"],
        shot_sec=6314.0,
        result_sec=6320.0,
        score_before=[2, 1],
        score_after=[3, 1],
        why="lead_extend_first_live_before_6408_confirm",
        source_corruption_during_live_shot=True,
        source_corruption_windows=[{"src_start": 6315.0, "src_end": 6316.75, "kind": "band_macroblock"}],
        delivery_gate="BLOCKED_SOURCE_CORRUPTION",
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
        residual_note="mild bottom-right source fragment ~6408.1–6408.6 (P1)",
    )
    add_media(
        "edl_g41",
        "goal",
        "resolution",
        7740.0,
        7760.0,
        source_node_ids=["ke_r28_4_1"],
        shot_sec=7746.78,
        result_sec=7748.1,
        score_before=[3, 1],
        score_after=[4, 1],
        why="final_goal_first_live",
    )
    add_media(
        "edl_score_4_1",
        "scoreboard_anchor",
        "resolution",
        7857.37,
        7860.87,
        source_node_ids=["event_000154"],
        why="LIVE_4_1_board_confirm",
        shot_kind="scoreboard_anchor",
    )
    # Natural ending: late stoppage → live bench/staff reaction (not studio, not other match).
    # 7908 still late live play (~96:05); 7914+ dugout celebration; avoid 7950+ (other match/studio).
    add_media(
        "edl_final_live_reaction",
        "resolution_ending",
        "resolution",
        7908.0,
        7922.0,
        source_node_ids=["r28_live_final_reaction"],
        why="first_live_late_stoppage_to_bench_reaction_4_1",
        shot_kind="natural_ending",
        authenticity_note="Same continuous LIVE source; scoreboard 4:1 visible early; dugout reaction after ~7914; not claimed as exact whistle PTS without audio confirmation",
    )

    return {
        "schema": "v2_r28_final_edl_v1",
        "playout_policy": "first_live_goals_only_no_replay_no_tech_endcard_natural_ending",
        "n_segments": len(segments),
        "n_goal_segments": sum(1 for s in segments if s.get("role") == "goal"),
        "n_non_goal_strip_segments": sum(1 for s in segments if s.get("role") == "strip_context"),
        "total_duration_sec": round(play, 3),
        "segments": segments,
        "gates": {
            "live_only": True,
            "all_five_goals_verified_first_live": True,
            "final_mp4_visual_pass": False,
            "visual_qc_pass": False,
            "blocked_source_corruption": True,
            "blocked_reason": "g31_source_band_glitch_during_live_shot_irrecoverable_without_clean_source_or_user_exception",
            "story_complete_candidate": False,
            "candidate_ready_for_human_review": True,
            "render_ready": False,
        },
        "render_ready": False,
        "user_choices_required": [
            "provide_clean_same_first_live_source_copy_for_3_1_window",
            "or_explicit_user_exception_to_ship_with_known_source_corruption",
        ],
        "note": "R2.8: g21 trimmed past 58s source band; g31 kept + BLOCKED_SOURCE_CORRUPTION; natural live ending; render_ready=false",
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    edl = build_r28_edl()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(edl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(args.out),
                "n_goals": edl["n_goal_segments"],
                "duration": edl["total_duration_sec"],
                "blocked_source_corruption": edl["gates"]["blocked_source_corruption"],
                "render_ready": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
