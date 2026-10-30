# Story VA V2 — R2.6 Final Report

Generated: 2026-10-30T04:21:58.400093+00:00
Branch: `story-va-video-driven`
Workspace HEAD at report write: 

## 1. What was fixed

1. Confirmed R2.5 rootcause fixes are active (`scores.score_recognition`, LIVE 3:1 @6408.70, score-order, no mixed/cross-stitch pass).
2. Independently re-localized five first-live goals using score trajectory + events + cached observations + scene cuts (**no paid API; V1 not used as search input**).
3. Rebuilt EDL rejecting R2.5 late packages for 1:1 / 2:1 / 3:1.
4. Re-rendered `story_clean_live_only.mp4` and produced source↔render mapping + QC frames/clips.

## 2. Five goals (V2 independent)

| Score | action window | shot | net | confirm | status |
|---|---:|---:|---:|---:|---|
| None→[0, 1] | 975.8-988.0 | 982.063 | 982.063 | 1079.06 | verified_first_live |
| [0, 1]→[1, 1] | 3055.0-3082.0 | 3064.500 | 3069.300 | 3145.98 | verified_first_live |
| [1, 1]→[2, 1] | 3515.0-3538.0 | 3524.000 | 3527.700 | 3697.35 | verified_first_live |
| [2, 1]→[3, 1] | 6305.0-6332.0 | 6314.000 | 6320.000 | 6408.70 | verified_first_live |
| [3, 1]→[4, 1] | 7740.0-7755.0 | 7746.780 | 7748.100 | 7858.37 | verified_first_live |

## 3. Remaining risks / human review needed

- **2:1** selected by Pass+scene-cut cluster (3515–3538); cached VLM shot/net was only at the rejected late package (3562). Please visually confirm complete shot→net in `qc_goal_playback_clips/edl_g21_playback.mp4`.
- Automatic QC **cannot** certify first-live vs alternate-angle replay; `final_mp4_visual_pass=false` by policy.
- Non-goal strips reduced; no new Story Planner run.

## 4. Actual MP4 checks performed

- Re-rendered from source MP4 via ffmpeg segment cut + concat.
- Duration match EDL: True (probe 128.141s vs EDL 127.85s)
- Audio track: True (aac)
- blackdetect hits: 0
- Extracted per-goal mid/early/late frames + seam frames + playback clips
- **Did not** claim human-watch complete; status=`candidate_ready_for_human_review`

## 5. API usage

- Paid DeepSeek/Qwen calls this round: **0**
- Token usage: **0**

## 6. Tests run

`TestEventAdapter` + `TestFinalMp4AcceptanceGates` + `TestReplayClassify` + `TestActionTiming` → OK (22 tests)

## 7. Output paths

- Watch: `/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_6_live_verified/story_clean_live_only.mp4`
- Summary: `/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_6_live_verified/story_summary.md`
- Goal audit: `/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_6_live_verified/live_goal_vs_replay_audit.json`
- EDL: `/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_6_live_verified/final_edl.json`
- Graph: `/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_6_live_verified/story_graph.json`
- Mapping: `/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_6_live_verified/goal_source_to_render_mapping.json`
- QC: `/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_6_live_verified/full_video_replay_qc.json`
- Comparison: `/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_6_live_verified/r2_5_vs_r2_6_comparison.md`
- Playback clips: `/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_6_live_verified/qc_goal_playback_clips/`
- Negative replay refs: `/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_6_live_verified/clips/g11_late_rejected.mp4`, `g21_late_rejected.mp4`, `g31_late_rejected.mp4`

## 8. Policy

`render_ready=false` until explicit human approval.

## Delivery commit


