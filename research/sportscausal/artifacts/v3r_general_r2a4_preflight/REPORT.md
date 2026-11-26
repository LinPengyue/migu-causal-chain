# V3-R-General R2a.4 preflight (role-safe score / attack)

- Code: `7f47f24` (`research/sportscausal-template-generalization`)
- Baseline artifacts: `cbc11f1` (R2a.3 A/B pack)
- Protocol: `V3R_GENERAL_R2A4.md`
- Zero-cost: http_calls=0; no paid LLM/VLM; no video render; **no R2a.3 ablation rerun**; no manual candidate edits; no benchmark labels

## Commands

```bash
cd research/sportscausal
python -m unittest -v test_r2a4_roles
# -> 19/19 OK (see unittest.txt)

python r2a4_patterns.py \
  --evidence artifacts/stage1_2_evidence_preflight_20261125/A_uae_oman/keeper_rescue/evidence.json \
  --semantics artifacts/v3r_general_r2a2_preflight/A/normalized_semantics.json \
  --score-path artifacts/v3r_general_r2a3_preflight/inputs_prepared/A_score_path_from_t01.json \
  --base-graph artifacts/v3r_general_r2a3_preflight/A/without_score/relation_graph.json \
  --allow-dev --out-dir artifacts/v3r_general_r2a4_preflight/A

# B: identical with B_* paths / B_osasuna_celta evidence
```

## Input hashes (sha256)

| input | sha256 |
|---|---|
| A evidence | `9322933a9c3ef15a990c9377ed498e97b73cb20350bbfe279114bf2f3b4043fc` |
| A semantics | `d9ef5ec2f99d6d85bb3750b849b69bbf9f91378ffcf27ccbdd16daedd7c1136f` |
| A score_path | `0c55b3a03dabda4ec14eeed150bf6ef22342f14503a82c5ef369770d2b5782ac` |
| A without_score graph | `fc69ad6961c636c1156ef76bb739f5bc05088365973f2c0b6f9c06a20ab08bd4` |
| B evidence | `a673769fe1b81f93a34f9c987302af49f8988cbf02c429ad97b1317bf7b33292` |
| B semantics | `f1e8c222e6faeba704eb90b94e2f0470f2101f4c40c84b9132e33dcc7aaaa439` |
| B score_path | `fef9d22228d34f5348bc771b752470cd96da5a1c7ff5c2baf146284cfc6fb635` |
| B without_score graph | `534dbe460b15756f179cf1a43466dd32f9b2927fdd03e8e42d4de77081fe33c7` |

## Cache reuse

- A `reused_without_score_graph=True`
- B `reused_without_score_graph=True`
- Edge keys identical to saved without_score graphs (A:7, B:2). Rejected/unresolved sets byte-equal to without_score caches.
- **Did not** substitute R2a.3 score-contaminated `full/` graphs.

## Unit tests

`test_r2a4_roles`: **19/19 OK** (log: `unittest.txt`).

## Headline counts

| | A | B |
|---|---:|---:|
| attack/save links | 7 | 2 |
| score-bound goals | 3 | 4 |
| goal context edges (Shot→Goal membership) | 3 | 4 |
| role inferences | 0 | 0 |
| score-derived executor/shooter inferences | 0 | 0 |
| observation tasks | 6 ({'goal_execution_roles': 3, 'shot_save_roles': 3}) | 12 ({'goal_execution_roles': 4, 'missing_goal_localization': 1, 'shot_save_roles': 7}) |
| strict alternating_threats episodes / cands | 10 / 1 | 3 / 0 |
| mixed score_context episodes / cands / eligible | 13 / 1 / False | 7 / 1 / False |
| keeper_rescue episodes | 8 | 3 |

## Acceptance audits

### 1. A opening 0:1 (known own-goal audit fact; not used as a rule)

- Binding retained: `atom_fill_0004_Goal_1337123`, path_index=1, score `0:0→0:1`, beneficiary=`team_2`, action_t=1337.123, media_window=[1337.123, 1339.123] (≠ carrier confirmation_t=1410.43).
- `goal_executor=null`, `attacking_team=null`, `execution_status=UNRESOLVED`, `goal_kind=untyped_goal`.
- Shot context `atom_fill_0003_Shot_1335974` kept via `outcome_context_edges` with `shooter=null` (not an attack causal edge; not score-propagated).
- Observation task `goal_execution_roles` asks for ball-striking team / attack team / ordinary-vs-own-goal / first-live — **not** auto-filled from beneficiary.

### 2. Prior 7 score-derived shooter inferences — all removed

R2a.3 `cbc11f1` full graphs inferred shooters from score∩chain (A3+B4=7):

| side | shot event | inferred actor | path_index |
|---|---|---|---:|
| A | `atom_fill_0003_Shot_1335974` | team_2 | 1 |
| A | `atom_fill_0074_Shot_6448924` | team_1 | 2 |
| A | `atom_fill_0103_Shot_6841456` | team_1 | 3 |
| B | `atom_fill_0036_Shot_1977587` | team_2 | 1 |
| B | `atom_fill_0071_Shot_3132270` | team_1 | 3 |
| B | `atom_fill_0115_Shot_5657158` | team_2 | 4 |
| B | `atom_fill_0158_Shot_6790743` | team_2 | 5 |

R2a.4: `inferred_roles=[]` on both sides; summary `n_score_derived_executor_or_shooter_inferences=0`.
Per-event check: each of the 7 shots has `attacking_team.team=null` / `execution_actor.team=null`; each paired Goal has `goal_executor=null` with only `score_beneficiary` set; each `outcome_context_edges[*].shooter=null`.

### 3. Goal bindings / windows / short-chain context retained

- Localized bindings: **A 3 / B 4** (same counts as R2a.3 full). B path_index=2 (`0:1→1:1`) remains unresolved — see §6.
- All 7 localized goals keep `media_window` / `action_t_sec` distinct from scoreboard carrier times.
- All 7 keep Shot→Goal `outcome_context_edges` with predicted-chain membership (`chain_support`), marked `causal_verified=false`.

### 4. Non-goal relations preserved (vs without_score / cbc11f1)

| path | status |
|---|---|
| A398→399 `delivery_keeper` + 399→400 `keeper_deflection_followup` | retained |
| A640→641 `shot_save` (outcome_other chains) | retained |
| A416→417 / A476→477 dual-view delivery_keeper | retained |
| B586→587 `keeper_deflection_followup` (`explicit_recovery_reference`) | retained |
| B259→260 delivery_keeper | retained |
| keeper_rescue candidate membership | **identical** to without_score for A and B |

### 5. Conflict evidence retained

- A420→421: still in `rejected_edges` with `reason=actor_conflict` (delivery team_2 vs keeper/attack notes on 421).
- B625: `keeper.team_status=EXPLICIT` (team_2) with `player_status=CONFLICT` (notes player 3 vs attributes Defender 13) — unchanged vs R2a.2/R2a.3.

### 6. B missing 1:1 → structured observation task

- `missing_goal_localization` task: score_path_index=2, `0:1→1:1`, beneficiary=`team_1`, `search_interval=[2480.82, 2675.82]`, `event_ids=[]`, `media_windows=[]`, `resolved=false`.
- No fabricated Goal clip / no score-derived executor.

### 7. Unresolved Shot/Save observation tasks

- A: 3 `shot_save_roles` tasks covering all 3 `unresolved_relations` Shot/Save pairs; plus 3 `goal_execution_roles` for score-bound goals (include empty Shot context).
- B: 7 `shot_save_roles` covering all 7 unresolved Shot/Save pairs; 4 `goal_execution_roles`; 1 missing localization.
- Tasks carry `actor_hypotheses`, `context_clues`, `chain_support`, `media_windows` — handoff only; no video model run.

### 8. Strict alternating vs score-context (separate metrics)

- Strict `alternating_threats`: attack/rescue predicates only. A: 10 episodes / 1 candidate. B: 3 episodes / **0 candidates** (no strict alternate recognition).
- Mixed `alternating_threats_score_context`: `strict_threat_metric_eligible=false`. A: 13 mixed episodes (10 attack + 3 score_beneficiary nodes). B: 7 mixed episodes (3 attack + 4 score nodes) / 1 hypothesis candidate.
- **Do not** count mixed candidates as strict alternating-threat quality gain. Mixed `actor` on score nodes is the beneficiary role, not attacking_team proof.
- Duplicate goal/attack: `related_score_outcomes` links on attacking_threat episodes = 0 for both sides in this run (no overlapping attack membership with localized goals); score outcomes appear as distinct `score_beneficiary` nodes in the mixed view only. `unassigned_score_outcomes=0`, `score_only_sequence_count=0` (pure scoreboard sequences are not promoted to mixed attack stories).

## Honest limitations

- Score path still cannot prove execution, attack side, own-goal identity, or first-live footage.
- Untyped goals remain unresolved execution; observation tasks are requests only.
- Mixed role timeline ≠ strict attacking_threat template.
- `quality_verified=false`, `first_live_verified=false` on all outputs.

## Artifacts

`artifacts/v3r_general_r2a4_preflight/{A,B}/{relation_graph,causal_episodes,observation_tasks,scoring_outcomes,keeper_rescue,alternating_threats,alternating_threats_score_context,summary}.json` plus `unittest.txt`, `PACK_SUMMARY.json`, this `REPORT.md`.
