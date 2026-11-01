# STORY_VA_V2 G1 — Match A Dry Run（阿联酋 vs 阿曼）

**Status:** `ok_structure_dry_run` (Gate 1 PASS for structure migration)  
**Not claimed:** video-verified goals, visual QC, or deliverable story MP4.

## Inputs (absolute)

| Item | Path |
|------|------|
| MP4 | `/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4` |
| Events (raw) | `/tmp/migu-va2c/10.27scasual_chain/data/交付_out/10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语.json` |
| match_id | `10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语` |
| Algo root (readonly) | `/data2/lpy1/causal-chain2/8.31causal_chain` |
| Out dir | `/data2/lpy1/_story_va_outputs/v2/cross_match_g1/A_uae_oman/` |

**Forbidden inputs:** no `*_causal.json`, no `strip_gold` / `highlight_gold`, no Croatia R22/verify cache, no Phase5 packages.

## Provenance (from `provenance.json`)

| Field | Value |
|-------|-------|
| video_sha256 | `a66147f79609c8fbf831…` (full in artifact) |
| events_sha256 | `ddae99b21cbfcd1c75dd…` |
| strip prediction_mode | `reinfer_A_original` (raw-events → AlgoStripAdapter; **not** gold_clips dump) |
| n predicted strips | **79** (`special` 43 / `danger` 34 / `correction` 2) |
| api_calls / cost | **0 / $0** |
| forbidden_inputs_used | `[]` |

## Results

| Check | Result |
|-------|--------|
| score_path | `(0,0)→(0,1)→(1,1)→(2,1)` |
| selected_arc | **left / 阿联酋** · deficit `[0,1]` @1410.43 → eq `[1,1]` @6535.62 → go_ahead `[2,1]` @6957.12 |
| goal_action_sec | all `null` (board confirmation only) |
| missing_goal_candidates | **3**, all `verification_status=unresolved` |
| n_video_verified_goals | **0** |
| candidate_edl | `level=structure_only`, `verified_first_live=false`, roles opening_deficit/equalizer/go_ahead placeholders |
| croatia EDL builders | refused (`croatia_edl_refused=true`) |
| render_ready | **false** |
| elapsed | ~13–28s (after video hash cache) |

## Artifacts

`cli_report.json`, `score_path.json`, `selected_arc.json`, `missing_goal_candidates.json`, `predicted_strip_chains.json`, `story_graph.json`, `candidate_edl.json`, `provenance.json`, `strip_reinfer/`, `croatia_edl_guard.json`.

## STOP conditions (none hit)

No gold/causal load, no match_id mismatch, no paid API, no crash on N=3.
