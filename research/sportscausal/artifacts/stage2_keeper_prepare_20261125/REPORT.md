# SportsCausal Stage 2 keeper_rescue prepare (zero-cost)

- Code: `bba30aa`
- Unittest `test_story_graph_planner.py`: **6/6 OK**
- Mode: **PREPARE_ONLY** (no HTTP yet)
- Evidence: Stage 1.2 `A_uae_oman/keeper_rescue/evidence.json` (`HUMAN_ATOM_ENRICHED_DEV`, `--allow-dev`)
- Events in prompt: **663** (full inventory retained; no truncation; model not changed)

## Existing LLM config
- Model: **DeepSeek-V4-Pro-0813** via `https://llmapi.paratera.com/v1`
- Planned real call: **1×**, temperature 0, `max_completion_tokens=4096`, **no automatic retry**

## Size / tokens
- Prompt: **368349** chars / **392330** UTF-8 bytes
- Input token heuristic: low **98082**, mid **130776**, high **245566**
- Provider context window is **not hard-coded** in-repo — confirm DeepSeek-V4-Pro-0813 can host the mid/high estimate before paying

## Local cost estimate (STORY_LLM_PRICE_*; not invoice)
- $0.15/MTok prompt + $0.6/MTok completion
- Est. USD (completion=4096): low **$0.01717**, mid **$0.022074**, high **$0.039292**
- Suggested `--max-cost-usd` for the single call: **0.06**

## Await GPT/user budget confirmation
Then one real call only:
`STORY_API_ENABLE=1 python story_graph_planner.py ... --allow-dev --enable-real-api --i-approve-budget --max-cost-usd <cap>`

Historical A/B = DEV only, not FanEdit formal performance.
