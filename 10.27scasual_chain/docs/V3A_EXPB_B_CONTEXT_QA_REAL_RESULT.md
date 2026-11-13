# Exp B — real Qwen context Visual QA result

- Branch: `story-va-v3a-p17-native-broadcast-observer`
- Run base HEAD: `9bc5ede`
- Out: `/tmp/lpy1_v3a_expb_context_visual_qa_real_20261113`
- Paid HTTP: **1** (no retry)
- Model: **Qwen3.7-Plus** (`provider_mode=real`)
- Est. cost: **$0.004442** (estimate; not invoice hard cap)
- Tokens (role): **28079**; `output_budget_exceeded=**True**`
- Official verdict: **`INSUFFICIENT_EVIDENCE`**
- `first_live_verified=false`, `edl_modified=false`, `best_modified=false`

## Pre-run checks

- Pytest: 47 passed
- Source SHA `a66147f7…` rematch
- Stage3 Qwen3.7 anchors revalidated; issue `goal_coverage_01_to_11`
- 13 JPEGs; SHA/PTS matched prior preflight
- Provider: `max_calls=1`, vision `max_retries=0`, image_url path
- Env `STORY_API_MAX_COMPLETION_TOKENS=512` (caused truncation)

## Raw response

- Path: `/tmp/lpy1_v3a_expb_context_visual_qa_real_20261113/original_model_response.txt`
- SHA256: `6e22b82ef07a414335b9e0c2a09a4a799bbdada8590a33921ac9b27ba6cba9d7`
- Truncated mid-JSON (does not end with closing `}`); CLI reason: `EvidenceNormalizationError:invalid JSON object`

## Partial citations (best-effort extract; NOT validator-accepted)

| phase | frame_id | claimed PTS | exists | PTS match | timing |
|---|---|---:|---|---|---|
| ACTIVE_PLAY_BEFORE | `f_0003_6444880` | 6444.88 | True | True | ok |
| GOAL_SHOT_NET | `f_0005_6447880` | 6447.88 | True | True | ok |
| IMMEDIATE_CELEBRATION | `f_0006_6450600` | 6450.6 | True | True | post_phase_not_after_net |
| IMMEDIATE_CELEBRATION | `f_0010_6463600` | 6463.6 | True | True | ok |
| LATER_SAME_ACTION_REPLAY | `f_0012_6488600` | 6488.6 | True | True | ok |


Duplicate phases in partial text: `['IMMEDIATE_CELEBRATION']`

## What this adds vs Stage3–7

- **Added:** one multi-image (13) source-PTS context attempt after Stage3; partial (unvalidated) pre-play / shot-net / celebration / later-replay claims.
- **Not added:** validated LIVE/REPLAY status, earlier-occurrence exclusion, FIRST_LIVE, continuous video proof.
- Does **not** overturn Stage4 UNKNOWN / Stage5 OCR insufficient / Stage6 pHash-negative / Stage7 cuts-only.

## Gates

No FIRST_LIVE unlock. No EDL/BEST change. No automatic retry (completion-token increase would need new authorization).

See `docs/V3A_EXPB_B_CONTEXT_QA_REAL_AUDIT.json`.
