# Story VA V2 — R2.7 Final Report

Generated: 2026-10-30T06:37:18.461728+00:00
Branch: `story-va-video-driven`
Pre-commit HEAD: `884ba01df12dec6595a3123e70c6229fafc6bdb5`

## 1. Branch / work

Pulled latest `story-va-video-driven`, read `STORY_VA_V2_R2_7_CURSOR_INSTRUCTIONS.md`, diagnosed R2.6 final MP4 against source, fixed EDL/render, re-rendered.

## 2. Corruption rootcause (verified)

### 77.8–78.6s (edl_g21 → source 3535.45–3536.25)
- **Cause:** `source_content_gray_dropout` (~0.75s near-uniform gray in original MP4; all seek modes agree; already in work clip).
- **Fix:** Trim g21 to `3515.0–3533.0` (after celebration, before gray/static).

### 90.4–92.0s (edl_g31 → source 6315.05–6316.65)
- **Cause:** `source_band_glitch_during_live_shot` (live 2-1 @69:32 with horizontal artifact band already in source; HQ recut reproduces).
- **Fix:** Keep continuous first-live shot→net; filter-concat re-encode; **do not** replace with replay. Residual source glitch may still be visible — human must judge.

Evidence: `/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_7_visual_fix/visual_corruption_rootcause.md`, `diag/`, `frames_src/`, `frames_r26/`.

## 3. Five-goal source↔story maps

### 2:1
- Source: pre 3515 → shot 3524 → net 3527.7 → celeb end 3533 (gray 3535.25–3536 excluded)
- Story play: {"segment_id": "edl_g21", "pre_shot_start": 57.35, "shot": 66.35, "net": 70.05, "celebration_end": 75.35}

### 3:1
- Source: pre 6305 → shot 6314 → net 6320 → celeb 6332 (glitch band ~6315.5–6316.5)
- Story play: {"segment_id": "edl_g31", "pre_shot_start": 75.35, "shot": 84.35, "net": 90.35, "celebration_end": 102.35, "glitch_band_story": [85.85, 86.85]}

Other goals unchanged from R2.6 first-live windows (0:1/1:1/4:1); 4:1 celebration extended to 7760 + LIVE board 7857.37–7860.87.

## 4. Visual QC coverage
- Final MP4 duration ~129.523s; audio=aac
- 1s full scan + dense seams/goals/former problem zones: **422 samples**, **0 gray anomalies**
- `final_mp4_visual_pass=false` (policy); `candidate_ready_for_human_review=true` iff gray-clean
- Replay: no mixed cross-stitch acceptance changes; no new VLM calls

## 5. Paths
- Watch: `/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_7_visual_fix/story_clean_live_only.mp4`
- Rootcause: `/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_7_visual_fix/visual_corruption_rootcause.md`
- QC: `/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_7_visual_fix/full_video_visual_qc.json`
- Mapping: `/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_7_visual_fix/goal_source_to_render_mapping.json`
- Compare: `/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_7_visual_fix/r2_6_vs_r2_7_comparison.md`

## 6. API / tokens
**0 / 0**

## 7. Remaining uncertainty
- 3:1 source glitch band may still look mosaic-like in the re-render — confirm shot→net completeness by eye.
- First-live vs alternate-angle still needs human judgment (auto tools insufficient).

`render_ready=false`

## Delivery commit

`1eb5a92` (`1eb5a92e900e52894c524ef355a572761a8b6945`)
