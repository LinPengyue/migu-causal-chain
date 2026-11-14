# E2E v2 Story-First POC — full-index prepare (2026-11-14)

Code: `090ceed2cb893d5d2b03a2005a0a522de3f87a62`  
Branch: `story-va-e2e-v2-story-first-20261114`  
Out: `/tmp/lpy1_story_first_v2_fullindex_20261114`  
Mode: `STORY_API_ENABLE=0` → `PREPARED_ONLY_ZERO_HTTP` (`http_attempts=0`)

## Pytest

`tests/test_v3a_story_first_poc.py`: **19 passed** (0.09s)

## Inputs (unchanged P14)

| Asset | Path | sha256 |
|-------|------|--------|
| events | `…/01_enrich/events_enriched.json` | `33958b10…` |
| EDL | `…/01_initial_story/candidate_edl.json` | `b38434b9…` |
| plan | `…/01_initial_story/story_plan.json` | `ba64c215…` |

`edl_modified=false`. Prior out `/tmp/lpy1_story_first_v2_prepared_20261114` left intact.

## Inventory / context / probes

| Metric | Value |
|--------|------:|
| timed / distinct in scope | 530 |
| `event_inventory` / full inventory | **530** |
| rich detail / LLM context | **240** |
| dropped by context cap (not rich detail) | 290 |
| entirely omitted from prompt | **0** |
| observation_probes | **381** |
| gap_probes | 3 |
| supplied event rows | 879 |

## `prompt_coverage` (`hypothesis_generation_audit.json`)

```json
{
  "contains_unverified_hypotheses_only": true,
  "events_entirely_omitted": 0,
  "full_inventory_events": 530,
  "model_input_token_count_measured": false,
  "prompt_characters": 203243,
  "prompt_utf8_bytes": 203560,
  "rich_detail_events": 240
}
```

## `llm_input.json`

- File size: **226202** bytes (~220.9 KiB)
- Messages content UTF-8: **203559** bytes (~198.8 KiB; aligns with `prompt_utf8_bytes`)
- Token count: not measured
- Length judgment: large for tiny context windows; rough size still well under typical 128k-token budgets if tokenizer ≈ chars/3–4. Not a quality claim—size only.

### Event type distribution (full inventory n=530)

| type | n |
|------|--:|
| Defensive_action | 123 |
| Pass | 120 |
| Ball_possession | 65 |
| Shot | 49 |
| Win_an_aerial_duel | 40 |
| Foul_Being_fouled | 39 |
| Save | 25 |
| Throw_in | 16 |
| Dribble_past | 16 |
| Goal | 14 |
| Corner_kick | 8 |
| Free_kick | 6 |
| Substitution | 4 |
| Video_Assistant_Referee | 3 |
| Players_enter_the_pitch | 1 |
| Receive_a_card | 1 |

## Non-claims

No paid LLM/VLM. No FIRST_LIVE. No EDL/BEST/v1 edits. Hypotheses empty (`hypotheses=0`).
