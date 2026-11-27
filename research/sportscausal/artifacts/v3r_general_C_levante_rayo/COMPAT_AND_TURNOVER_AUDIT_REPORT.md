# Fresh V3-R compatibility + C turnover zero-candidate re-audit

- Merge tip `91bd2ea` while retaining `d62b7bf` (no force reset). Parent merge: see git log.
- `http_calls=0`. No enrich/strip/render/Story Agent. No operator/threshold edits. No C full rerun.

## Task 1 — historical compatibility regression

### Commands / tests

```text
test_causal_atom_fill_full_pipeline (test_run_fresh_v3r_general.FreshEntryTests) ... ok
test_failure_is_not_complete (test_run_fresh_v3r_general.FreshEntryTests) ... ok
test_independent_atom_fill_filtered_output (test_run_fresh_v3r_general.FreshEntryTests) ... ok
test_mapping_reversed_and_native_conflict (test_run_fresh_v3r_general.FreshEntryTests) ... ok
test_no_synthetic_score (test_run_fresh_v3r_general.FreshEntryTests) ... ok
test_raw_full_pipeline (test_run_fresh_v3r_general.FreshEntryTests) ... ok
test_reject_reference_and_duplicates (test_run_fresh_v3r_general.FreshEntryTests) ... ok

----------------------------------------------------------------------
Ran 7 tests in 0.050s

OK
```

```bash
python -m py_compile run_fresh_v3r_general.py audit_fresh_v3r_compatibility.py
python audit_fresh_v3r_compatibility.py \
  --a-events /data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_A_uae_oman/01_enrich/events_enriched.json \
  --b-events /data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_B_osasuna_celta/01_enrich/events_enriched.json \
  --out-dir artifacts/fresh_v3r_compatibility_v1
# exit 1 due to full score-row metadata diffs only (see below)
```

### Headline

| case | status | checks pass/fail | score_status |
|---|---|---|---|
| A | DIFFERENCES | 43/1 | CHECKED |
| B | DIFFERENCES | 36/1 | CHECKED |

**Only failing check on both sides:** `regenerated_full_score_rows`.  
**`regenerated_score_signature` PASS** (score / t_sec / opening / delta_side / carrier_event_id identical).  
Diff is additive `previous_score_observed_t_sec` on non-opening rows from the current score extractor vs frozen T01-prepared JSON lacking that field.

### Focused acceptances

- **阿曼门将 keeper_rescue:2** (6 anchors / 6 EDL segs / dur≈70.53): all compared artifacts PASS (`initial_edl`, `story_graph`, materials, tasks, …); EDL byte-equal to frozen.
- **A/B comeback Legacy Seed 89.0s**: `legacy_seed_bytes` PASS; duration_sec=89.0; sha A=`dec28e8e…`, B=`5ba76074…`; agent_seed file remains `legacy_seed.json`.
- **R2a.4 role graph equivalence**: all compared keys PASS (`atoms`, `edges`, `rejected_edges`, `unresolved_relations`, `inferred_roles`, `goal_bindings`, `outcome_context_edges`, `observation_tasks`) + episode_bundle + r2a/r2bc candidate equality.
- Fresh normalization vs frozen r2a2 semantics: PASS.

Artifacts: `artifacts/fresh_v3r_compatibility_v1/{A,B,summary.json}`.

## Task 2 — C turnover_to_goal zero-candidate (corrected)

Relation Path uses `turnover_actor` on LIVE `Defensive_action` notes (not `turnover_recovery` episode projection). Re-read `fresh_general_v1` only.

### pred_0057 (`turnover_counter_goal`, PARTIAL)

- Members 17; unavailable/nonlive: event_000347 + 5 replay atom_fills (`annotated_nonlive`).
- **Start recognized:** `event_000342` → `turnover_actor=team_1` (notes「1队23号球员截获球权」).
- **Primary exclusion:** sole next predicted edge `342→343` Δt=**22.760s** > `max_edge_gap_sec=15` → **no adjacency out-edge**; path search never expands.
- Additional hard fails if gap waived: span to LIVE goal **84.805s** > `max_span_sec=45`; mid path hits `Foul_Being_fouled` (STOP) + `Substitution` (RESTART).
- LIVE goal `atom_fill_0096_Goal_5690415`: `score_beneficiary=team_2`, `role_conflict=false`, `attacking_team=null` → beneficiary ≠ start actor `team_1` (endpoint reject).

### pred_0060 (`turnover_counter_goal`, PARTIAL)

- Members 8; available only `event_000358/359/360`; all later Goal/Assist/… **REPLAY** → Evidence `annotated_nonlive`.
- Starts: `358→team_1`, `359→team_2`. `360` notes have 截获 but `turnover_actor=None` (pattern cannot cross intervening「2队」 token).
- **Primary exclusion:** **no LIVE goal endpoint** in evidence atoms → cannot close `scoring_outcome`.
- Secondary: `358→359` Δt=19.190s > 15s gap bound.

Official `relation_candidates` count remains **0**. JSON: `artifacts/v3r_general_C_levante_rayo/turnover_zero_candidate_audit.json`.
