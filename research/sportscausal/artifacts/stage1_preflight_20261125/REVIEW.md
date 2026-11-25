# SportsCausal Stage 1 zero-cost preflight review pack

- Worktree: `/data2/lpy1/worktrees/migu-sportscausal-template-gen` @ `6373f7c`
- Branch: `research/sportscausal-template-generalization` (detached worktree branch `...-wt`)
- Unittest: `cd research/sportscausal && python -m unittest -v test_template_graph.py` → 6/6 OK
- Paid API: no; selection/render/algo edits: no

## Inputs (reused)
- A: `.../closed_loop_A_uae_oman/01_enrich/events_enriched.json`
- A: `.../closed_loop_A_uae_oman/03_v1_adapt/predicted_causal.json`
- Source: `/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4` (8149.48s)
- B sample: closed_loop_B_osasuna_celta enrich + predicted_causal

## Outputs
- `A_uae_oman/{keeper_rescue,set_piece_breakthrough,alternating_threats}/{inventory,planner_request}.json`
- `B_osasuna_celta/keeper_rescue/{inventory,planner_request}.json`
- `AUDIT_REPORT.json`, `RUN_META.json`

## Checks (all pass)
1. Event/chain ID binding
2. Windows within source duration
3. Annotated replay/slow-mo excluded from materials
4. No gold/reference story leakage in planner_request
5. Repeated slot roles → unique `slot:index` node instances (offline instantiate only)

## GitHub
Committed on `research/sportscausal-template-generalization` for external GPT review. Subsequent Cursor audit packs should be committed the same way.
