# P17.2 B native-video preflight — STOPPED (0 paid HTTP)

- Branch / HEAD: `story-va-v3a-p17-native-broadcast-observer` @ `a513e70`
- Decision: **STOP_NO_PAID_CALL**

## Preflight passed (zero HTTP)

- Source SHA `a66147f7…da9c` match
- Qwen3.7 archived anchors revalidated: shot **6447.88** / net **6450.6** (exact bytes+PTS)
- Unique binding: **`goal_coverage_01_to_11`**
- Continuous reencode `[6429.88, 6474.6]` ≈2.36 MB, under 12 MB cap (local only; MP4 not committed)

## Blockers (no real Qwen call)

1. `story_e2e` + `--enable-real-api` always runs VLM Critic **before** native observation; `--max-calls 1` cannot guarantee the single native call.
2. Paratera/`video_url` data-URI acceptance is **unproven** on this path.

## Not claimed

FIRST_LIVE / EDL repair / BEST change / model answer — none.
