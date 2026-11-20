"""R2.9 targeted EDL: trim g11 celebration glitch + g21 prelude source glitch; keep 3:1 BLOCKED."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from story_video_agent.v2_strip_guided_r2_8_build_edl import build_r28_edl


def build_r29_edl() -> dict:
    edl = build_r28_edl()
    edl["schema"] = "v2_r29_final_edl_v1"
    # Rebuild play clocks after mutating media windows.
    segs = edl["segments"]
    by = {s["segment_id"]: s for s in segs}

    # 51s: post-1:1 crowd close-up — source/work clean at PTS but R2.8 final showed
    # green macroblock salad; celebration is not required for shot/net. Trim end.
    g11 = by["edl_g11"]
    g11["media_out"] = 3074.5
    g11["duration_sec"] = round(float(g11["media_out"]) - float(g11["media_in"]), 3)
    g11["why"] = "equalizer_first_live_trim_post_net_crowd_closeup_glitch"
    g11["r29_trim_note"] = (
        "media_out 3082→3074.5 to drop ~3075.5–3076 crowd close-up that corrupted in R2.8 final; "
        "shot 3064.5 / net 3069.3 retained; verdict=decode_or_render_error_on_final (source clean)"
    )
    g11["r29_defect"] = {
        "story_t": 51.0,
        "source_pts": 3075.65,
        "verdict": "decode_or_render_error",
        "fix": "trim_nonessential_celebration_tail",
    }

    # 60.5s: g21 attack prelude — source/work/final agree on local gray/white macroblock
    # around source 3520.15. Advance start while keeping shot/net.
    g21 = by["edl_g21"]
    g21["media_in"] = 3521.0
    g21["duration_sec"] = round(float(g21["media_out"]) - float(g21["media_in"]), 3)
    g21["why"] = "go_ahead_first_live_trimmed_past_r28_and_r29_prelude_glitches"
    g21["r29_trim_note"] = (
        "media_in 3517→3521 to skip source_corruption ~3520.15–3520.4; "
        "prior R2.8 trim 3515→3517 retained; shot 3524 / net 3527.7 / celeb→3533 kept"
    )
    g21["r29_defect"] = {
        "story_t_r28": 60.5,
        "source_pts": 3520.15,
        "verdict": "source_corruption",
        "fix": "raise_media_in_same_live_attack",
    }
    trimmed = list(g21.get("source_corruption_trimmed") or [])
    trimmed.append({"src_start": 3520.05, "src_end": 3520.4, "kind": "local_macroblock", "round": "r29"})
    g21["source_corruption_trimmed"] = trimmed

    # Recompute story_play clocks
    play = 0.0
    for s in segs:
        if s.get("media_in") is not None and s.get("media_out") is not None:
            s["duration_sec"] = round(float(s["media_out"]) - float(s["media_in"]), 3)
        dur = float(s["duration_sec"])
        s["story_play_in"] = round(play, 3)
        s["story_play_out"] = round(play + dur, 3)
        play += dur

    edl["total_duration_sec"] = round(play, 3)
    edl["n_segments"] = len(segs)
    edl["gates"]["render_ready"] = False
    edl["gates"]["visual_qc_pass"] = False
    edl["gates"]["blocked_source_corruption"] = True
    edl["gates"]["blocked_reason"] = (
        "g31_source_band_glitch_during_live_shot_irrecoverable_without_clean_source_or_user_exception"
    )
    edl["gates"]["candidate_ready_for_human_review"] = True
    edl["render_ready"] = False
    edl["note"] = (
        "R2.9: g11 trim celebration close-up (51s final glitch); "
        "g21 start 3521 (60.5s source glitch); g31 still BLOCKED_SOURCE_CORRUPTION; render_ready=false"
    )
    return edl


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    edl = build_r29_edl()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(edl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(args.out),
                "duration": edl["total_duration_sec"],
                "g11": [by["media_in"] for by in edl["segments"] if by["segment_id"] == "edl_g11"][0],
                "g11_out": [by["media_out"] for by in edl["segments"] if by["segment_id"] == "edl_g11"][0],
                "g21_in": [by["media_in"] for by in edl["segments"] if by["segment_id"] == "edl_g21"][0],
                "blocked_source_corruption": True,
                "render_ready": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
