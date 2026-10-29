# Story VA V2 — Round 2.5 Live-Only Report

## Verdict

Round 2.5 **passes** live-only acceptance for Croatia–Canada:

- 2:1 go-ahead goal retained with **tight live core** covering shot `3562.32` and result `3566.64` (PTS unchanged).
- All **five** verified goals pass integrity (shot + net + not replay).
- Clean/QC live-only candidates generated; `render_ready=false`.

Artifacts:

`/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_5_20261029_211351/`

## Task 1 — Root cause of “missing” 2:1

R2.4 EDL/FFmpeg **did include** `ke_3` at `3556.32–3571.64`, which already covered the verified strike and net.

Root cause was **over-padding in Story Graph clip construction** (`shot - 6s` and `edit_out + 2s`), expanding beyond verified `edit_window` `3560.32–3569.64`. Extra head/tail angles make the live goal harder to read and can feel “overwritten” when reviewing the story cut. Verified PTS were **not** wrong; window construction was.

R2.5 fix: `goal_live_core_window` clamps to a tight live core around verified shot→result (**does not use shot−6**). Final 2:1 window: **`3560.82–3569.14`**.

Diagnosis JSON: `ke3_2_1_diagnosis.json`.

## Task 2 — Live-only constraint

Qwen audits classify live/replay via 直播 / 回放 / slow-mo cues. Segments that are replay, mixed, or **live-unconfirmed** are excluded from Clean EDL.

`replay_segment_audit.json` records per-segment outcomes. Unconfirmed strip `strip_clip58` was dropped when vision frame budget was exhausted (cannot enter Clean without live confirmation).

## Task 3 — Five-goal checklist

From `goal_clip_integrity_audit.json` (playback map in story time):

| Goal | Shot | Result | Live window | Story play | Pass |
|---|---|---|---|---|---|
| →0:1 | 982.063 | 982.063 | 980.563–984.563 | 2.5–6.5 | yes |
| 0:1→1:1 | 3105.08 | 3107.72 | 3103.58–3110.22 | 24.5–31.14 | yes |
| **1:1→2:1** | **3562.32** | **3566.64** | **3560.82–3569.14** | **31.14–39.46** | **yes** |
| 2:1→3:1 | 6457.1 | 6461.08 | 6455.6–6463.58 | 75.46–83.44 | yes |
| 3:1→4:1 | 7746.78 | 7748.1 | 7745.28–7750.6 | 83.44–88.76 | yes |

## Task 4 — Outputs

- `story_clean_live_only.mp4`
- `story_qc_live_only.mp4`
- `goal_clip_integrity_audit.json`
- `replay_segment_audit.json`
- `edl_live_only.json`
- this report

Kept 3 live-confirmed non-goal strips (24/45/46) from R2.4 selection; dropped unconfirmed `clip58`.

## Constraints

No gold/V1 times; no 8.31 production edits; five verified goal times reused; `render_ready=false`.

## Git

Commit SHA: `a5d8c030093a77bba734580584e7b325f0a40ac5`
