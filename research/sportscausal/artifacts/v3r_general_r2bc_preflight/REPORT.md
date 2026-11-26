# V3-R-General R2b/R2c combined preflight

- Code: `b59fa2d` (`research/sportscausal-template-generalization`)
- Frozen R2a.4 baseline: `0bba8b7` (artifacts reused, not regenerated)
- Protocol: `V3R_GENERAL_R2BC.md`
- Zero-cost: http_calls=0; no paid HTTP; no video; **no R2a history rerun**; no manual candidate edits; no benchmark labels
- `quality_verified=false`, `first_live_verified=false`, `release_authorized=false`

## Commands

```bash
cd research/sportscausal
python -m unittest -v test_r2bc_patterns
# -> 20/20 OK (unittest.txt)

python r2bc_patterns.py \
  --evidence artifacts/stage1_2_evidence_preflight_20261125/A_uae_oman/keeper_rescue/evidence.json \
  --r2a4-dir artifacts/v3r_general_r2a4_preflight/A \
  --score-path artifacts/v3r_general_r2a3_preflight/inputs_prepared/A_score_path_from_t01.json \
  --allow-dev --out-dir artifacts/v3r_general_r2bc_preflight/A

python r2bc_patterns.py \
  --evidence artifacts/stage1_2_evidence_preflight_20261125/B_osasuna_celta/keeper_rescue/evidence.json \
  --r2a4-dir artifacts/v3r_general_r2a4_preflight/B \
  --score-path artifacts/v3r_general_r2a3_preflight/inputs_prepared/B_score_path_from_t01.json \
  --allow-dev --out-dir artifacts/v3r_general_r2bc_preflight/B
```

## Input hashes (sha256)

| input | sha256 |
|---|---|
| A_evidence (`artifacts/stage1_2_evidence_preflight_20261125/A_uae_oman/keeper_rescue/evidence.json`) | `9322933a9c3ef15a990c9377ed498e97b73cb20350bbfe279114bf2f3b4043fc` |
| B_evidence (`artifacts/stage1_2_evidence_preflight_20261125/B_osasuna_celta/keeper_rescue/evidence.json`) | `a673769fe1b81f93a34f9c987302af49f8988cbf02c429ad97b1317bf7b33292` |
| A_r2a4_graph (`artifacts/v3r_general_r2a4_preflight/A/relation_graph.json`) | `05dd0cfcc61556d2e0b9aeb8f89d52b2c4bdc80f8cca15f59423b7b7e925f05d` |
| A_r2a4_episodes (`artifacts/v3r_general_r2a4_preflight/A/causal_episodes.json`) | `9f54e404a18c0c4d95f5b9ffd2fcd3af193f9784d5aa003f6e48d7cdf1bd3b62` |
| A_r2a4_tasks (`artifacts/v3r_general_r2a4_preflight/A/observation_tasks.json`) | `fbda183c33d5a7b2e3a44fb800e5f6706e0c0ff55917a6846cb382c0555b80a4` |
| B_r2a4_graph (`artifacts/v3r_general_r2a4_preflight/B/relation_graph.json`) | `71baf210706ea081002f6c27b61592e964daa61df1f5fd1aeec53bd75c3e56c8` |
| B_r2a4_episodes (`artifacts/v3r_general_r2a4_preflight/B/causal_episodes.json`) | `91610d0cd3517f399dd4a5e5287444c7d77c4b46d4ff806db44d4716ba824d40` |
| B_r2a4_tasks (`artifacts/v3r_general_r2a4_preflight/B/observation_tasks.json`) | `14b022a883f4c4a5d9d62899b11778a342522762dc211861716fbff6564d5e0e` |
| A_score (`artifacts/v3r_general_r2a3_preflight/inputs_prepared/A_score_path_from_t01.json`) | `0c55b3a03dabda4ec14eeed150bf6ef22342f14503a82c5ef369770d2b5782ac` |
| B_score (`artifacts/v3r_general_r2a3_preflight/inputs_prepared/B_score_path_from_t01.json`) | `fef9d22228d34f5348bc771b752470cd96da5a1c7ff5c2baf146284cfc6fb635` |

## Unit tests

`test_r2bc_patterns`: **20/20 OK**.

## Candidate counts (not quality)

| template | operator | A | B |
|---|---|---:|---:|
| comeback | state_transition | 1 | 1 |
| equalization | state_transition | 1 | 2 |
| lead_preservation | state_transition | 1 | 1 |
| set_piece_breakthrough | relation_path | 0 | 0 |
| turnover_to_goal | relation_path | 1 | 0 |
| threat_phase_change | phase_change | 1 | 0 |

Zero-candidate results are retained as-is (no parameter retune).

## Observation tasks

| | R2a.4 preserved | R2bc appended | total |
|---|---:|---:|---:|
| A | 6 (unchanged IDs/content) | 2 (`relation_path_verification`, `phase_switch_verification`) | 8 |
| B | 12 (unchanged IDs/content) | 0 (no path/phase cand) | 12 |
| **A+B** | **18** | **2** | **20** |

R2a.4 artifact tree git-clean (untouched). No video observer executed.

---

## 1. State transitions

State `actor` = template **state_subject** (comeback/equalization/lead side).  
`score_beneficiary` is reported separately; **`goal_executor` / `attacking_team` remain null** on all bound goals (no beneficiary→executor propagation).

### A comeback — subject `team_1` (signs -1,0,1)

| node | score | path | state_sign | beneficiary | executor | localization | action / media | confirm_t | tasks |
|---|---|---:|---:|---|---|---|---|---:|---|
| score:1 | 0:1 | 1 | -1 | team_2 | null | localized | 1337.123 / [1337.123,1339.123] | 1410.43 | observe:1 |
| score:2 | 1:1 | 2 | 0 | team_1 | null | localized | 6449.644 / [6449.644,6451.644] | 6535.62 | observe:2 |
| score:3 | 2:1 | 3 | 1 | team_1 | null | localized | 6843.088 / [6843.088,6845.088] | 6957.12 | observe:3 |

- Opening node: state_subject=`team_1` ≠ beneficiary=`team_2` (own-goal audit fact remains external).
- Interval context: score1→2 certain_interior [1337.123,6449.644] includes dual-view 276/277 threat+rescue (~1912–1922); also many other threats omitted here but listed in JSON. score2→3 [6449.644,6843.088] includes 640/641 shot_save dual-view.
- Post-last: team_2 threat `event_000681` (~7134–7145) — weak/late context, not a verified final whistle (`terminal_basis=last_confirmed_score_not_independent_final_whistle`).

### A equalization — subject `team_1` (-1,0)

Nodes score:1→score:2 as above. Interval same as comeback first leg.

### A lead_preservation — subject `team_1` (signs 0,1)

Nodes score:2 (1:1) → score:3 (2:1). This matches the declarative signature “level→lead”, **not** independent proof of defensive lead holding.
- Interval material: team_1 `attacking_threat` 640/641 + team_2 `goalkeeper_rescue` same windows — offensive dual-view after leveling, **not** dedicated “lead-protecting defense” evidence.
- Protocol reminder: lead signature ≠ successful defensive preservation.

### B comeback — subject `team_2` (-1,0,1) from path_index 3

| node | score | path | benef | executor | localization | action/media | tasks |
|---|---|---:|---|---|---|---|---|
| score:3 | 2:1 | 3 | team_1 | null | localized | 3133.968 / [3133.968,3135.968] | observe:2 |
| score:4 | 2:2 | 4 | team_2 | null | localized | 5657.621 / [5657.621,5659.621] | observe:3 |
| score:5 | 2:3 | 5 | team_2 | null | localized | 6791.882 / [6791.882,6793.882] | observe:4 |

- Interval score3→4 [3133.968,5657.621]: **empty** context_candidates (long sparse gap; no certain interior attack/rescue from R2a.4 bundle).
- Interval score4→5: B586→587 keeper_rescue / attacking_threat dual-view.
- Post-last: empty.

### B equalization

1. **`equalization:1` subject team_1**: score:1 (0:1 localized, observe:1) → score:2 **1:1 missing_action**  
   - `event_ids=[]`, `media_windows=[]`, `action_time_interval=[2480.82,2675.82]`, `observation_task_ids=[observe:5]` (`missing_goal_localization` preserved).  
   - `unlocalized_state_indices=[2]`. No fabricated clip.
2. **`equalization:2` subject team_2**: 2:1→2:2 (paths 3→4), both localized.

### B lead_preservation — subject `team_2`

2:2→2:3 (paths 4→5). Interval includes B586/587 dual-view before final goal. Same caveat: signature ≠ verified defensive preservation.

---

## 2. Relation paths

### A `turnover_to_goal:1` (only positive path candidate)

| field | value |
|---|---|
| start | `event_000668` Defensive_action, actor_role=`ball_recovery_team` team_1 |
| end | `atom_fill_0104_Goal_6843088` score_beneficiary=team_1, **executor=null**, shooter on context=null |
| intermediates | `event_000669`, Pass_0100, aerial_0101, Assist_0102, Shot_0103 |
| chains | `pred_0067` PARTIAL `outcome_other`; `pred_0068` PARTIAL `rebound_follow_up_goal` |
| span | ≈22.5s (t_end−t_start); max_span_sec=45, max_edge_gap_sec=15 |
| typed local | only Shot→Goal as `shot_goal_context` (not attack causal edge); other links `ordered_predicted_members` |
| conflicts | no actor_conflict on path links; beneficiary aligns with start actor |
| tasks | observe:3 + `observe:r2bc:turnover_to_goal:1` (path verification; media_windows=[] on task — search via path alt windows) |

PARTIAL: contiguous available members only; does not bridge missing predicted members. Hypothesis only (`causal_verified=false`).

### Zero-candidate path templates (honest reasons; no retune)

| side | template | starts found | why empty |
|---|---|---:|---|
| A | set_piece_breakthrough | 19 Corner/Free/Penalty | No common-chain path from set-piece start to same-side `score_beneficiary` goal within 45s span / 15s edge gap; near-misses hit span_exceeded / shot_mismatch / no 15s out-edge |
| B | set_piece_breakthrough | 15 | Same class of failures; no OK endpoint |
| B | turnover_to_goal | 43 recovery starts | Expansions die on replaced_by_new_start / span_exceeded / shot_mismatch; **0** beneficiary-aligned goal paths |

---

## 3. Phase change

### A `threat_phase_change:1`

| phase | actor | n episodes | observed_interval (anchor_t) | members |
|---|---|---:|---|---|
| 1 | team_2 | 2 | [1054.41, 1916.42] | 096/097; 276/277 |
| 2 | team_1 | 7 | [1961.46, 6557.14] | 282; 398–400; 416/417; 421; 472; 476/477; 640/641 |

- Switch search interval: **[1922.55, 1955.54]** (task `observe:r2bc:threat_phase_change:1`; media_windows=[]).
- Score-only outcomes **excluded** from phase episodes (`actor_role=attacking_team` only).
- Sparsity: intra-phase gaps up to ~851s (phase1) and ~1782s (phase2). This is an **observed run-label change**, not possession/dominance (`phase_semantics=observed_sustained_threat_run_change_not_dominance`). Candidate is sparse — do not treat as established sustained control.

### B `threat_phase_change` — 0 candidates

Only **3** `attacking_threat` episodes, **all team_1** (050; 259/260; 586/587). No opposite-side run with `min_episodes_per_phase=2`. Real zero; not tuned away.

---

## 4. Cross-checks

- Beneficiary never copied onto `goal_executor` / empty Shot shooter in any R2bc node.
- A420–421 actor_conflict and B625 player CONFLICT remain in frozen R2a.4 graph (untouched).
- State interval “material between nodes” is R2a.4 attack/rescue episodes with windows strictly inside action-time interiors — dual-view pairs have narrative dual-role value; empty interiors (B comeback first leg) reported as empty, not invented.

## Limitations

Provisional path bounds (45/15) and phase min=2 are preflight defaults, not fitted thresholds. Paths/phases/states are hypotheses for R3 Story Graph — not EDL, not first-live proof, not quality gains from candidate counts.

## Artifacts

`artifacts/v3r_general_r2bc_preflight/{A,B}/{comeback,equalization,lead_preservation,set_piece_breakthrough,turnover_to_goal,threat_phase_change,anchor_pack,observation_tasks,summary}.json` plus `unittest.txt`, `PACK_SUMMARY.json`, this `REPORT.md`.
