# C_levante_rayo — fresh unified V3-R entry (`fresh_general_v1`)

- Sync: merge `d03f522` while retaining intake `b5a7baa` (no force reset). HEAD: `0e83213f2850d3e2cddc0b8291c197c9a83ef425`
- Protocol: `V3R_GENERAL_FRESH_ENTRY.md`
- Mode: `--causal-atoms-json` + `--allow-dev` (`HUMAN_ATOM_ENRICHED_DEV`)
- Paid HTTP / Story Agent / A·B rerun / operator·threshold edits: **none**
- `http_calls=0`, `status=COMPLETE`, gates all false

## 1. Special tests

```text
test_causal_atom_fill_full_pipeline (test_run_fresh_v3r_general.FreshEntryTests) ... ok
test_failure_is_not_complete (test_run_fresh_v3r_general.FreshEntryTests) ... ok
test_independent_atom_fill_filtered_output (test_run_fresh_v3r_general.FreshEntryTests) ... ok
test_mapping_reversed_and_native_conflict (test_run_fresh_v3r_general.FreshEntryTests) ... ok
test_no_synthetic_score (test_run_fresh_v3r_general.FreshEntryTests) ... ok
test_raw_full_pipeline (test_run_fresh_v3r_general.FreshEntryTests) ... ok
test_reject_reference_and_duplicates (test_run_fresh_v3r_general.FreshEntryTests) ... ok

----------------------------------------------------------------------
Ran 7 tests in 0.051s

OK
```

`python -m py_compile run_fresh_v3r_general.py test_run_fresh_v3r_general.py` → OK.

## 2. Exact command

See `fresh_general_v1_COMMAND.sh`. Summary:

```bash
cd research/sportscausal
python run_fresh_v3r_general.py \
  --match-json .../交付_out/10月20日_25-26赛季西甲第9轮_莱万特VS巴列卡诺_国语.json \
  --causal-atoms-json .../同名_causal.json --allow-dev \
  --source-mp4 "/mnt/data4/migu/10月20日 25-26赛季西甲第9轮 莱万特VS巴列卡诺 国语.mp4" \
  --expected-source-sha256 5ab8ee77...1d4d73 \
  --expected-events-sha256 cffe1f86...f2e9c6 \
  --expected-atom-source-sha256 e88ce072...cfdbd1 \
  --score-left-team team_1 \
  --score-mapping-provenance "independently_cross_checked_intake_FH-35DA83FD..." \
  --video-id "10月20日 25-26赛季西甲第9轮 莱万特VS巴列卡诺 国语" \
  --out-dir artifacts/v3r_general_C_levante_rayo/fresh_general_v1
```

## 3. Input hashes

| input | sha256 |
|---|---|
| match_json | `cffe1f86aa386e668b6ad3ce8a654113a814783b9343db4ce63bb6ebb5f2e9c6` |
| causal_atoms_json | `e88ce072fcd22c2a723abd3374b9c29f6ef5584fe8ac0bd6431e4c84decfdbd1` |
| source_mp4 | `5ab8ee77ed0d0cb56f020348d4c73b4c27c738f6285db941e1797f87bb1d4d73` |

## 4. 01_enrich

- mode `HUMAN_ATOM_ENRICHED_DEV`: raw 443 + injected **124** → enriched 567
- injected_by_type: `{"Pass": 18, "Defensive_action": 8, "Corner_kick": 4, "Goal": 37, "Shot": 22, "Assist": 10, "Dribble_past": 4, "Win_an_aerial_duel": 7, "Save": 11, "Referees_decision": 1, "Substitution": 2}`
- Goal injected: 37 (live 4 / replay 33)

## 5. 02_strip831

- `reinfer_atom_enriched`, use_llm=False, n_events=567, **n_chains=78**
- category_counts: `{"special": 39, "outcome": 15, "danger": 22, "correction": 2}`
- template_counts: `{"throw_in_build_up_chain": 34, "shot_save_chain": 15, "outcome_other": 7, "quick_restart_set_piece_chain": 5, "goal_line_extreme_save_chain": 4, "second_phase_after_frame_chain": 3, "rebound_follow_up_goal": 3, "corner_coop_goal": 2, "turnover_counter_goal": 2, "individual_breakthrough_goal": 1, "goal_disallowed_chain": 1, "var_overturn_chain": 1}`

## 6. Goal Recovery / adapt

- adapted chains: **80**; source `causal_chain6_predicted_on_atom_enriched_events+v3_goal_recovery`
- category_counts_zh: `{"结果链": 17, "险情链": 22, "修正链": 2, "特殊链": 39, "其他": 0}`
- recovery: n_candidates=13, n_single_goal=6, with_action=2, unresolved_single=4, paid=0
- recovered actions: `[{"before": [0, 0], "after": [0, 1], "goal_action_sec": 1281.007}, {"before": [0, 1], "after": [0, 2], "goal_action_sec": 2080.397}]`
- unresolved single-goal count: 4

## 7. Auto score path

| t_sec | score | delta_side | carrier |
|---:|---|---|---|
| 614.01 | 0:0 | None | event_000005 |
| 1359.22 | 0:1 | right | event_000135 |
| 2163.38 | 0:2 | right | event_000171 |
| 5789.37 | 0:3 | right | event_000349 |

mapping `{'left': 'team_1', 'right': 'team_2'}` — matches intake `0:0→0:1→0:2→0:3`.

Evidence atoms=409, chain states=`{'FULL': 22, 'PARTIAL': 52, 'NONLIVE_CHAIN': 6}`

## 8. Eight templates (+ mixed)

| template | n_candidates | R3 stories |
|---|---:|---:|
| keeper_rescue | 0 | 0 |
| alternating_threats | 0 | 0 |
| alternating_threats_score_context | 0 | 0 |
| comeback | 0 | 0 |
| equalization | 0 | 0 |
| lead_preservation | 1 | 1 |
| set_piece_breakthrough | 0 | 0 |
| turnover_to_goal | 0 | 0 |
| threat_phase_change | 0 | 0 |

Materialized: lead_preservation:1 (team_2, 3 segs, ~6.383s, complete).

## 9. turnover_to_goal

**0 candidates** — no Initial EDL / no render.

Reason: R2bc relation_path requires start_predicate=turnover_recovery -> end_predicate=scoring_outcome; R2a4 episode predicates={'scoring_outcome': 3, 'attacking_attempt': 4, 'goalkeeper_action': 1, 'goalkeeper_rescue': 1} (no turnover_recovery). Strip emitted 2x turnover_counter_goal but they did not project to turnover_recovery under frozen operators; no retune.

## 10. Artifacts

`fresh_general_v1/{01_enrich…08_r3,run_manifest.json,ffprobe.json}` plus `FRESH_GENERAL_V1_REPORT.md`, `unittest_fresh_entry.txt`, `fresh_general_v1_COMMAND.sh`.
Prior intake `b5a7baa` media/inputs retained; earlier RAW_EVENTS_ONLY probe dirs left untouched.
