# Story-First Stage-1 Run02 — engineering facts (2026-11-14)

Code: `c4068d32b54ee49fdf024ae3b12d23b58ff85ed2`  
Out: `/tmp/lpy1_story_first_v2_deepseek_run02_20261114`  
Protocol: `STAGE1_COMPACT_SKELETON_V1`  
No VLM / no EDL edit / no video render / 1 HTTP / 0 retries.

## Preflight (zero-paid)

| Item | Result |
|------|--------|
| pytest | **26 passed** |
| prepared-only `--max-hypotheses 2` | HTTP=0; inventory **530**; detail **240**; omitted **0** |
| gateway model | `DeepSeek-V4.1-Flash` present; thinking `{"type":"disabled"}` |
| context | **1000000** |
| remeasured input tokens | **64206** (≠ Run01 64108) |
| worst-case cost @ 3200 out | ~$0.012–$0.022 ≪ $0.10 |
| session env | `STORY_API_MAX_COMPLETION_TOKENS=3200` (override secrets 512) |

## Paid call

| Metric | Value |
|--------|------:|
| http_attempts | **1** |
| prompt_tokens | **64206** |
| completion_tokens | **398** |
| reasoning_tokens | **0** |
| finish_reason | **stop** |
| est_cost_usd_real | **0.00987** |
| accepted / rejected | **0 / 2** |
| status | `NO_VALID_HYPOTHESES` |
| raw_response_saved | true |

Validator fact (not a quality claim): both model items rejected with `missing_evidence_or_test` because `parse_hypotheses` requires `falsification_conditions` as a **non-empty list**; model returned a **string**. `observation_plan.targets` = 0 (no accepted hypotheses). Probe pool still has 381 searchable probes; model query targets match probes `event:event_000635` and `event:event_000598`.

## Artifacts (also under `docs/ARTIFACT_run02_*`)

- `story_hypotheses.json` — accepted empty; rejected indices 0,1
- `ARTIFACT_run02_model_hypotheses_as_returned.json` / `llm_raw_response.txt` — model body as returned
- `hypothesis_generation_audit.json`
- `observation_plan.json`
- `ARTIFACT_run02_cited_events_metadata.json`
