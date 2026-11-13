# Stage4 B — server verify (zero HTTP)

Code: `b07d096` on `story-va-v3a-stage4-first-live-review`.
Reused Stage3 new-key Qwen3.6/3.7 observation logs. **No paid API.**

## Automated module

- `timeline_review_status`: **UNKNOWN**
- `method`: `insufficient_timeline_context`
- `first_live_verified`: **false**
- `edl_repaired`: **false**
- context clip: `/tmp/lpy1_v3a_stage4_B_first_live_review_20261113/broadcast_context/context_clip.mp4`
  - PTS [6428.62, 6468.62]
  - sha256 `3bb647d7e5550dfc0be30e14d13969b054ca60f499c48bb61f51d7ed58b2b6fb`
  - continuous_source=true, accurate_decode=true

## Independent server visual check (assistive only)

Sampled frames from context clip (hashes in JSON):

- ~6447.2s shot (UAE white) while board still 0-1
- ~6450.6s ball in net / celebration start (board lag)
- ~6459s board updates to **1-1**

Raw events: **no event inside** [6440.62, 6465.62]; score flips from 0:1@6410 to 1:1@6535. Later REPLAY events @6566+ are a **different** shot outside Stage4 pad window.

## Gate decision

**Do not unlock FIRST_LIVE / do not repair EDL yet.**

Stage4 correctly refuses to promote from VLM `live` + empty in-window replay_hits.
Needs SHA+PTS-bound authenticated/human review before any `repair_goal_coverage_from_video_reviews`.

Out: `/tmp/lpy1_v3a_stage4_B_first_live_review_20261113`
