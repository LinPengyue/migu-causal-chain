# Story VA V2 — Round 2.5 Live-Only Acceptance Fix Report

## Verdict

R2.5 **acceptance-fix** for Croatia–Canada: five verified goals now pass **window + final-MP4 visual** gates. `story_complete_candidate=true`, `render_ready=false`.

Artifacts:

`/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_5_fix_20261030_094019/`

Prior failing candidate (badge/PTS autofill):  
`/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_5_20261029_211351/`

## Task 1 — Original `events.json` replay fields

Source: `/data2/lpy1/causal-chain2/8.31causal_chain/data/交付_out/2022-11-28 克罗地亚vs加拿大.json`

From `event_replay_field_audit.json` (real file counts, not schema inference):

| Field | Result |
|---|---|
| `video_context` | 159 / 159 |
| `is_replay` | False 145, True 14 |
| `broadcast_phase` | LIVE 145, REPLAY 14 |
| `is_slow_motion` | False 159 (likely underlabeled — **not** treated as proof of no slow-mo) |
| EDL span coverage | **7 spans uncovered** (incl. most goal neighborhoods) |

Policy: overlapping REPLAY labels feed the broadcast timeline; uncovered spans require video observation and **must not** default `is_replay=false`.

## Task 2 — Live-only gate fixes

Removed acceptance loopholes in `v2_strip_guided_r2_5_live_only.py`:

1. Persistent **直播 badge ≠ live action**.
2. Verified PTS **never** auto-fill missing shot/net observation.
3. `unknown` / `replay` / `mixed` cannot hard-pass without dense live confirmation.
4. Replay classifier uses **positive** cues only (`replay package`, `replay angle`, `broadcast_state=replay`, …) and strips negations (`not a replay`, `lack of slow-motion artifacts`).
5. Multi-slice `broadcast_timeline` + tight dense core (`shot−6 … result+2.2`), trimmed by event REPLAY overlaps.

## Task 3 — Relocated live goal windows

| Goal | Accepted media (sec) | Notes |
|---|---|---|
| →0:1 | 976.063–985.563 | Approach + shot + net (was truncated near net) |
| 0:1→1:1 | 3103.88–3108.72 | Tight live core before trailing replay wording |
| **1:1→2:1** | **3557.32–3569.64** | Includes approach through net; PTS 3562.32 / 3566.64 unchanged as anchors |
| 2:1→3:1 | 6452.1–6464.08 | Trimmed before event_000119 REPLAY @6467.64 |
| 3:1→4:1 | 7740.78–7751.6 | Extended enough for net + short live celebration |

## Task 4 — Final MP4 visual audit (mandatory)

`final_mp4_visual_audit.json` observes the **rendered** `story_clean_live_only.mp4` (not EDL alone).

All five goals: `pass=true` with frame evidence for approach / shot / net (celebration where visible). Story play mapping for QC is in the audit + EDL.

Acceptance from `cli_report.json`:

- `go_ahead_2_1_present`: true  
- `five_goals_live_complete`: true  
- `final_mp4_visual_pass`: true  

## Outputs

- `story_clean_live_only.mp4` / `story_qc_live_only.mp4`
- `event_replay_field_audit.json`
- `broadcast_timeline.json`
- `goal_live_window_audit.json`
- `final_mp4_visual_audit.json`
- `edl_live_only.json`
- `before_after_video_issues.json`
- `replay_segment_audit.json`
- this report

Non-goal strips kept: 3 (live-confirmed from R2.4 selection after timeline).

## Constraints

No gold / strip_gold / V1 times; no 8.31 or V1 edits; `render_ready=false`.

## Before → after (failed R2.5 → fix)

| Issue | Before | After |
|---|---|---|
| Pass without final MP4 audit | `all_five_goals_pass=true` on EDL/Qwen keywords | Final MP4 visual gate required |
| 直播 badge as live proof | Allowed | Rejected unless live-action evidence |
| PTS autofill shot/net | Allowed | Forbidden |
| 0:1 missing approach | ~980.5–984.5 | 976.1–985.6 |
| 2:1 multi-angle / unclear live | Tight core only, badge pass | 3557–3569 + final MP4 pass |
| 4:1 early truncate | ~7745–7750 | 7740.8–7751.6 |

## Tests

`python -m unittest story_video_agent.test_v2_strip_guided_r2_5`

## Git

Delivery commit SHA: `2af37c4b6a55c902c9a9e8a1ebfa831f206a43c9`
