# Exp B — offline evidence review (0 HTTP)

- Branch HEAD tested: `6b756ce`
- Pytest: **13 passed** (`test_v3a_expb_offline_evidence_review` + `test_v3a_expb_context_visual_qa`)
- Out: `/tmp/lpy1_v3a_expb_offline_evidence_review_20261113`
- Status: `PARTIAL_MODEL_CITATIONS_NOT_VISUAL_VERIFICATION`
- `api_calls=0`, `first_live_verified=False`, `edl_modified=False`
- Raw response SHA: `6e22b82ef07a414335b9e0c2a09a4a799bbdada8590a33921ac9b27ba6cba9d7` (matches expected)
- Source SHA: `a66147f79609c8fbf831a8bd29de4c6d7f746b314b2b18a88ffb1fc5f319da9c`
- Complete observations: **4**
- Duplicate phases preserved: `['IMMEDIATE_CELEBRATION']`
- Trailing incomplete `LATER_SAME_ACTION_REPLAY` ignored: `True`
- Contact sheet SHA: `19122af15664209bb2f9e12736cfcbac3178d37234496ab22a165c66c86b47df`
- Frames: **13** (all on-disk SHA matched)

## Complete citations retained

| phase | frame_id | pts |
|---|---|---:|
| ACTIVE_PLAY_BEFORE | `f_0003_6444880` | None |
| GOAL_SHOT_NET | `f_0005_6447880` | None |
| IMMEDIATE_CELEBRATION | `f_0006_6450600` | None |
| IMMEDIATE_CELEBRATION | `f_0010_6463600` | None |

## Checks

1. Complete JSON objects extracted: **4** (no auto-completion of truncated tail).
2. Two `IMMEDIATE_CELEBRATION` rows retained (6447.88+net reaction @6450.6 and huddle @6463.6).
3. Truncated `LATER_SAME_ACTION_REPLAY` **excluded**.
4. All 13 source JPEG SHA256 matched the real-call report paths.
5. Contact sheet ordered by actual PTS (see `docs/V3A_EXPB_B_OFFLINE_CONTACT_SHEET.jpg`).
6. No model HTTP; FIRST_LIVE/EDL/BEST unchanged.

`replay_identity`: UNVERIFIED_REQUIRES_VISUAL_COMPARISON
