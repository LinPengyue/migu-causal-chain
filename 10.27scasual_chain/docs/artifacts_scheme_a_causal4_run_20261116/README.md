# artifacts_scheme_a_causal4_run_20261116

Server root: `/tmp/lpy1_scheme_a_causal4_run_20261116/`
Code: `48191ea` (adapter fix on Causal-4).

1. `01_generate_max5/` — 1× DeepSeek-V4.1-Flash generate, max_hypotheses=5 → accepted **5**
2. `03_score_real/` — 1× four-axis Causal Scorer
3. `budgets/` — tokenizer-measured input token budgets
4. `CAUSAL4_SUMMARY.json` — machine-readable summary

No VLM. No EDL/Planner changes.
