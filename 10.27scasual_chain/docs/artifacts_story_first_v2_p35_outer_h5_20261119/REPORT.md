# Story-First P3.5 outer H5 — round-2 real footage

Code: `9bfd931`. Preview only; `release_authorized=false`. Formal EDL untouched.

## Three-way comparison

| outer_rounds | status | duration_sec | mp4_sha256 (16) | notes |
|---:|---|---:|---|---|
| 0 | V3_R | 94.877 | `7764010f0aa1f412` | baseline original |
| 1 | ACCEPTED_PREVIEW | 101.147 | `b8ea196564440dd4` | H5 trim `6403.81–6410.07`; local_trims=1 |
| 2 | ACCEPTED_PREVIEW | 129.243 | `6b6f2c0f5a518282` | new window `4671.11–4699.2`; local_trims=0 |

## Round 2 facts

- P1 proposals: **10** new / 10 total (`2` intervals)
- Planner select: `interval_01:H5` → events `event_000467`, `event_000469`
- Bound source window: **4671.11–4699.2** (insert after `seg_setup_deficit`, before `seg_buildup_event_000472`)
- P2: `READY_FOR_TRIAL`; both events SUPPORTED; no veto; `NO_ANNOTATED_REPLAY_OVERLAP`
- P3: `CAPTION_UNAVAILABLE` → accept current trial (0 local TRIM)
- HTTP added by continuation: **5**; est cost ≈ **$0.02087** (cap $0.05 / 12 calls)

## Paths

See `VIDEO_PATHS.txt`. Full run dir: `/tmp/story_first_outer_h5_20261119_150623`.
