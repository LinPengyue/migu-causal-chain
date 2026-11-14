# E2E v2 Story-First — first paid DeepSeek-V4.1-Flash run (2026-11-14)

Code HEAD: `a92f8ce8ccadbb6b57d092df58392b607348199d`  
Branch: `story-va-e2e-v2-story-first-20261114`  
Out: `/tmp/lpy1_story_first_v2_deepseek_run01_20261114`  
Status: **`FAILED_NO_PROMOTION`** — `finish_reason=length` (no auto-retry)

## Phase 0/1 — zero-paid checks

| Check | Result |
|-------|--------|
| pytest `tests/test_v3a_story_first_poc.py` | **20 passed** |
| Gateway model id | `DeepSeek-V4.1-Flash` present on `llmapi.paratera.com/v1/models` |
| Context window | **1,000,000** (Paratera card on ai.360.com for `deepseek/deepseek-v4.1-flash`; `/v1/models` has no context field) |
| Tokenizer | Official `deepseek-ai/DeepSeek-V4.1-Flash` `tokenizer.json` + `encoding/encoding.py` via hf-mirror |
| Measurement | `encode_messages(..., thinking_mode="chat")` then `tokenizers.Tokenizer.encode` |
| Measured input tokens | **64108** (API later reported the same) |
| Input+output budget | 64108+3200=67308 ≤ 1e6 |
| Cost worst-case @ full 3200 out | project $0.0115; Paratera ¥2/¥8 ≈ **$0.022** ≪ $0.10 |
| Thinking style | `thinking_object` → `{"type":"disabled"}` |
| Env note | session overrode secrets `STORY_API_MAX_COMPLETION_TOKENS=512` → **3200** so CLI cap is not silently clamped |

P14 inputs unchanged (EDL `b38434b9…`, plan `ba64c215…`, events `33958b10…`).

## Phase 2 — one real HTTP

Command contract: `STORY_API_ENABLE=1`, `--enable-real-api --i-approve-budget`, `--max-hypotheses 3`, `--max-completion-tokens 3200`, `--max-cost-usd 0.10`, `--verified-context-window-tokens 1000000`, `--measured-input-tokens 64108`, `--disable-thinking-style thinking_object`.

| Metric | Value |
|--------|------:|
| http_attempts | **1** |
| prompt_tokens (provider) | **64108** |
| completion_tokens | **3200** |
| reasoning_tokens | **0** |
| finish_reason | **length** |
| est_cost_usd_real (project prices) | **0.011536** |
| returned_model | DeepSeek-V4.1-Flash |
| edl_modified | false |

CLI raised `ValueError: model_output_not_complete_or_filtered` **before** writing `llm_raw_response.txt` / hypotheses artifacts. Per contract: **no second HTTP** for truncation.

## Phase 3 — artifacts

Present:

- `hypothesis_generation_audit.json` (full failure audit)
- `prepared_story_input.json`, `llm_input.json`, `event_only_baseline.json`

**Missing (not written on length failure path):**

- `story_hypotheses.json`
- `hypothesis_evidence_matrix.json`
- `observation_plan.json`
- `llm_raw_response.txt`

Accepted/rejected hypotheses: **N/A** (parse never ran). No VLM, no video, no EDL/BEST/v1 edits.

## Stop

Hand off to ChatGPT: output hit `max_tokens=3200` with `finish_reason=length`; truncated body was not persisted by current CLI exception path.
