# Scheme A simplified Stage-2 (2026-11-15)

Code base: `69cd162` (+ this docs commit).  
Server root: `/tmp/lpy1_scheme_a_stage2_simple_20261115/`

## Calls
1. `01_generate_max5/` — 1× DeepSeek-V4.1-Flash generate, max_hypotheses=5 → accepted **3** (H1–H3)
2. `03_score_real/` — 1× independent Scheme-A score → `REAL_MODEL_PRIOR_NOT_VIDEO_VERIFIED`

No VLM, no EDL edit, no Planner. Historical Run02 H1/H2 kept under `HISTORICAL_*` for reference only.

## Costs (project estimator)
- Gen: ~$0.009994 (64258 in / 593 out)
- Score: ~$0.002576 (measured in 13895; provider usage token fields null in audit)
- Total est: ~$0.01257
