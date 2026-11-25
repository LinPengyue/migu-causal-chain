# Stage 2 Initial Story Graph Planner

Based on 53fa787 Stage 1.2 outputs. New research-only entry point; delivery and previous modules unchanged. Generates one template-conditioned story candidate per call (or a justified no-candidate result). No automatic template selection or multiple stories of the same template yet.

The LLM receives full compact eligible event table, predicted-chain context, team header and template, and outputs selected event/chain IDs plus narrative hypotheses. Code binds actual windows through Stage 1.2; missing required slots remain explicit, no semantic verification or automatic release. A completed candidate is not a verified story.

Run new unit tests only:
```bash
cd research/sportscausal
python -m unittest -v test_story_graph_planner.py
python story_graph_planner.py --template templates/keeper_rescue.json \
  --evidence artifacts/stage1_2_evidence_preflight_20261125/A_uae_oman/keeper_rescue/evidence.json \
  --allow-dev --out-dir /new/prepared
```

Offline preparation writes exact messages and character/byte counts. Optional --response-json tests parsing and binding without HTTP; never report fixture as real inference. Check configured model context length, provider prices and budget before any real call. Prompt is large; no assumed token count. No reference story or causal label input beyond existing explicitly marked historical DEV provenance. The real endpoint reuses the delivery provider and its one-attempt cap, no retries, no fallback. Its USD cap is an estimate checked by the existing provider, not a guaranteed invoice limit or pre-call upper bound.

When explicitly authorized by the user, use the same inputs, a fresh output dir, STORY_API_ENABLE=1, --enable-real-api --i-approve-budget --max-cost-usd APPROVED_ESTIMATE, --max-completion-tokens 4096 (or approved limit). Reuse existing configured LLM environment, never commit keys. Pilot only A keeper_rescue first; no batch across templates, no rendering. Inspect raw response, run_meta, graph and EDL, actual tokens/finish/cost. If context or estimated cost is unsuitable, stop and report, don't silently drop events or switch model.

Known limits: single source chronological assembly; same-team attribution and narrative usefulness are hypotheses until verified; upstream lineage not independently proven by input-tier label; P3/outer reflection not yet wired. Formal FanEdit runs need independent allowed event inputs and newly predicted chains. Tests authored but not executed by GPT.
