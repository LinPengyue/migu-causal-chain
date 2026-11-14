# Story-First Run01 raw-response recovery (zero-paid)

Code: `e511b7edbdb558ba9e65623e532aa8188f1e0ede`  
Run01 out: `/tmp/lpy1_story_first_v2_deepseek_run01_20261114`

## Pytest

`tests/test_v3a_story_first_poc.py`: **21 passed** (includes `test_paid_length_response_saved_before_rejection`)

## Recovery verdict

**`RAW_RESPONSE_UNAVAILABLE`**

Searched and confirmed absent:

- `$OUT/llm_raw_response.txt`
- `$OUT/story_hypotheses.json` / `hypothesis_evidence_matrix.json` / `observation_plan.json`
- Independent HTTP dump / redacted request-response log for this call
- `ApiProvider` disk cache (in-memory only; process exited)
- stdout tee: only `Story-First POC failed: model_output_not_complete_or_filtered` (62 bytes)

Run01 directory contents only:

1. `hypothesis_generation_audit.json`
2. `llm_input.json`
3. `prepared_story_input.json`
4. `event_only_baseline.json`

Old CLI raised on `finish_reason=length` before writing raw content. Fix in `666d051` / test in `e511b7e` applies to **future** runs only; cannot resurrect Run01 body.

## Diagnosable without body

| Field | Value |
|-------|------:|
| finish_reason | length |
| prompt_tokens | 64108 |
| completion_tokens | 3200 (hit cap) |
| reasoning_tokens | 0 |
| http_attempts | 1 |
| est_cost_usd_real | 0.011536 |
| status | FAILED_NO_PROMOTION |

Cannot analyze repetition, JSON verbosity, hypothesis count, or truncation locus without the raw text. No API re-call; no fabricated output.
