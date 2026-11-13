# Stage6 B — server verify (zero HTTP)

Base code: `150481f` + Python 3.9 `bit_count` compat shim (distance only).
Pytest: **21 passed**. No paid API. No EDL edit.

## `video_broadcast_audit.json`

- status: **NO_EARLIER_PHASH_MATCH_WITHIN_SCANNED_WINDOW**
- goal_action_pts: shot=6447.2, net=6450.6
- earlier_scan_pts: [6258.62, 6438.62]
- attempted/decoded: 180/180 (coverage=1.0)
- hamming_threshold: 8
- near_duplicate_matches: 0
- same_action_replay_confirmed: **false**
- first_live_verified: **false**
- edl_repaired: **false**
- ocr_required: false

## Interpretation

Bounded negative pHash retrieval ≠ FIRST_LIVE. Matches would also need
action-identity / broadcast-phase checks before any replay claim.
Do not unlock EDL.

Out: `/tmp/lpy1_v3a_stage6_B_video_first_20261113`
