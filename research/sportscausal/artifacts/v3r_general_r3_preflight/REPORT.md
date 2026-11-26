# V3-R-General R3 preflight (Story Graph + initial EDL)

- Code: `15646d3`
- Frozen R2bc: `73078bb`; Frozen R2a.4: `0bba8b7`
- Protocol: `V3R_GENERAL_R3.md`
- Zero-cost: http_calls=0; no paid HTTP; no video render; **no historical algorithm rerun**; no manual candidate edits; no benchmark labels
- All `quality_verified` / `first_live_verified` / `release_authorized` remain **false**

## Commands

```bash
cd research/sportscausal
python -m unittest -v test_r3_story_pipeline
# -> 12/12 OK (unittest.txt)

python r3_story_pipeline.py \
  --evidence artifacts/stage1_2_evidence_preflight_20261125/A_uae_oman/keeper_rescue/evidence.json \
  --r2a4-dir artifacts/v3r_general_r2a4_preflight/A \
  --r2bc-dir artifacts/v3r_general_r2bc_preflight/A \
  --legacy-seed-manifest artifacts/v3r_general_r3_preflight/inputs_prepared/A_legacy_seed_manifest.json \
  --allow-dev --out-dir artifacts/v3r_general_r3_preflight/A

python r3_story_pipeline.py \
  --evidence artifacts/stage1_2_evidence_preflight_20261125/B_osasuna_celta/keeper_rescue/evidence.json \
  --r2a4-dir artifacts/v3r_general_r2a4_preflight/B \
  --r2bc-dir artifacts/v3r_general_r2bc_preflight/B \
  --legacy-seed-manifest artifacts/v3r_general_r3_preflight/inputs_prepared/B_legacy_seed_manifest.json \
  --allow-dev --out-dir artifacts/v3r_general_r3_preflight/B
```

## Input hashes (sha256)

| input | sha256 |
|---|---|
| `A_evidence` | `9322933a9c3ef15a990c9377ed498e97b73cb20350bbfe279114bf2f3b4043fc` |
| `B_evidence` | `a673769fe1b81f93a34f9c987302af49f8988cbf02c429ad97b1317bf7b33292` |
| `A_r2a4_relation_graph` | `05dd0cfcc61556d2e0b9aeb8f89d52b2c4bdc80f8cca15f59423b7b7e925f05d` |
| `A_r2a4_causal_episodes` | `9f54e404a18c0c4d95f5b9ffd2fcd3af193f9784d5aa003f6e48d7cdf1bd3b62` |
| `B_r2a4_relation_graph` | `71baf210706ea081002f6c27b61592e964daa61df1f5fd1aeec53bd75c3e56c8` |
| `B_r2a4_causal_episodes` | `91610d0cd3517f399dd4a5e5287444c7d77c4b46d4ff806db44d4716ba824d40` |
| `A_r2bc_anchor` | `4169cddf1415781eefd620a0a69b52a2a1d0983377cd8360501d3c228dcfadb6` |
| `B_r2bc_anchor` | `21206d0cfb1be2afffac656aa4db13948b26c0b539d940584a5c9ab59b58d004` |
| `A_legacy_manifest` | `4d32a3e3ed557fd64f18d660dadc5c8029f85ed87f97d59dcc838ab2d3c5ecb4` |
| `B_legacy_manifest` | `6a9fe3d5aaafd682fbe4b04bae2df717dffee1f9ef8864f11a3ec31886f7500e` |
| `A_legacy_story_plan` | `dec28e8e9d82825167e1ef0ac56f068a0b84578a7116f683e17b625d9f4a9274` |
| `B_legacy_story_plan` | `5ba76074c2d08727c4eb800251775b50dfd8e0b3925895809e935ecde11c14e4` |
| `A_legacy_candidate_edl` | `c2d65e50163751711912c788e049e0ad78a0bec649fab4cb06a9f17305036151` |
| `B_legacy_candidate_edl` | `90212f3c97d1371e3a491b665b5627e04bc79147be49bc1662baff2f6a6db406` |

## Unit tests

`test_r3_story_pipeline`: **12/12 OK**.

## Story inventory (not quality)

Expected frozen inputs: **13** original-type candidates + **2** mixed score-context hypotheses. Actual: **13 + 2**.

| side | story_id | segs | dur_sec | structurally_complete | context_pool | legacy | strict_threat_eligible |
|---|---|---:|---:|---|---:|---|---|
| A | `keeper_rescue:1` | 2 | 21.160 | True | 0 | not_applicable | True |
| A | `keeper_rescue:2` | 6 | 70.530 | True | 0 | not_applicable | True |
| A | `alternating_threats:1` | 10 | 115.260 | True | 0 | not_applicable | True |
| A | `alternating_threats_score_context:1` | 13 | 124.761 | True | 0 | not_applicable | False |
| A | `comeback:1` | 3 | 9.501 | True | 9 | preserved_legacy_seed | True |
| A | `equalization:1` | 2 | 5.869 | True | 9 | not_applicable | True |
| A | `lead_preservation:1` | 2 | 6.352 | True | 2 | not_applicable | True |
| A | `turnover_to_goal:1` | 5 | 23.542 | True | 0 | not_applicable | True |
| A | `threat_phase_change:1` | 9 | 103.840 | True | 0 | not_applicable | True |
| B | `keeper_rescue:1` | 3 | 30.340 | True | 0 | not_applicable | True |
| B | `alternating_threats_score_context:1` | 7 | 43.480 | True | 0 | not_applicable | False |
| B | `comeback:1` | 3 | 9.300 | True | 1 | preserved_legacy_seed | True |
| B | `equalization:1` | 1 | 3.840 | False | 1 | not_applicable | True |
| B | `equalization:2` | 2 | 6.161 | True | 1 | not_applicable | True |
| B | `lead_preservation:1` | 2 | 5.602 | True | 1 | not_applicable | True |

Mixed hypotheses keep `strict_threat_metric_eligible=false`. Candidate counts are structure tallies only — not narrative quality.

## Legacy V3-R EDL recovery

Located on server (not regenerated):

| | A (subject `team_1` / 阿联酋) | B (subject `team_2` / 塞尔塔维戈) |
|---|---|---|
| Run | `full_e2e_A_strict_lin_20261108_095704/01_to_04_fresh_v3r/04_phase5` | `full_e2e_B_strict_lin_20261108_095704/01_to_04_fresh_v3r/04_phase5` |
| Seed file used | `story_plan.json` (`edl_key=edl`) | same pattern |
| Seed sha256 | `dec28e8e9d82825167e1ef0ac56f068a0b84578a7116f683e17b625d9f4a9274` | `5ba76074c2d08727c4eb800251775b50dfd8e0b3925895809e935ecde11c14e4` |
| Timed segments / duration | 7 / 89.0s | 7 / 89.0s |
| Chronological nonoverlap | True | True |
| Sibling `candidate_edl.json` sha256 | `c2d65e50163751711912c788e049e0ad78a0bec649fab4cb06a9f17305036151` | `90212f3c97d1371e3a491b665b5627e04bc79147be49bc1662baff2f6a6db406` |

**Loader note:** sibling `candidate_edl.json` includes placeholder title segments with `media_in/out=null`. R3 requires numeric windows on every seed segment, so the manifest uses the **same-run** `story_plan.json` timed `edl` list (7 segments). No newly generated EDL was invented as a substitute. `legacy_seed.json` is a byte-for-byte copy of that story_plan file. Status=`preserved_legacy_seed`. First-live is **not** inherited.

### Legacy seed vs new anchor-only draft (`comeback:1`)

| | A legacy | A new `initial_edl` | B legacy | B new `initial_edl` |
|---|---:|---:|---:|---:|
| segments | 7 | 3 | 7 | 3 |
| duration_sec | 89.0 | 9.501 | 89.0 | 9.300 |

New draft is **anchor-first** (3 localized goal Shot∪Goal unions). Legacy remains an independent Agent seed for comparison — not replaced, not claimed equivalent.

## Focused audits

### A `turnover_to_goal:1`

- All **7** path event IDs retained (start + 5 intermediates + goal); all LIVE.
- Materialized as **5** EDL segments via overlapping/touching window union (668∪669; Pass; aerial; Assist; Shot∪Goal). **No gap fill.**
- Exact unions: `[6810.16,6824.07]`, `[6829.01,6831.01]`, `[6831.837,6833.837]`, `[6836.608,6838.608]`, `[6841.456,6845.088]`.
- Total duration **23.542s**. Unselected source gaps are diagnostics only (not fabricated footage).

### B `equalization:1`

- `score:2` remains `missing_action` / missing required node; **no material, no EDL segment**.
- Linked `observe:5`; `structurally_complete=False`; `missing_required_nodes=['score:2']`.
- Only score:1 Shot∪Goal in EDL (`[1977.587,1981.427]`). No invented 1:1 goal clip.

### A `threat_phase_change:1` phase switch

- Node `phase_switch` keeps search interval **`[1922.55, 1955.54]`** with empty `event_ids`.
- Interval is **not** emitted as an EDL clip (switch node absent from all segment `story_node_ids`).

### EDL integrity (all stories)

Across every `initial_edl`: no duplicate events within a story, no chronological overlaps, no out-of-bounds windows, no non-LIVE annotated atoms, no unbound media windows. **Issues: none.**

### Dual-view context pool

- A comeback pool: 9 candidates; multiple entries merge attack+rescue perspectives on the **same** `event_ids`/`media_windows` (shared physical membership, not duplicated cuts). All `selected=false`; **none auto-inserted** into EDL.
- B comeback pool: 1 dual-view entry (586/587); not inserted.
- Lead-preservation diagnostics retain weak signature / non-final whistle context only (`A` kinds=['terminal_score_not_final_whistle', 'lead_signature_requires_post_lead_defensive_evidence', 'unselected_source_gap']; `B` kinds=['terminal_score_not_final_whistle', 'lead_signature_requires_post_lead_defensive_evidence', 'unselected_source_gap']) — not verified defensive evidence.

### Observation tasks

- Global tasks: A8 + B12 = **20**, content-identical to frozen R2bc packs.
- Per-story files attach direct + contextual refs only; **no observer executed**.

## Honest limitations

R3 proves structural compilation and source-bound draft materialization only. It does **not** prove narrative quality, first-live identity, or releasable highlights. A/B remain `HUMAN_ATOM_ENRICHED_DEV`. Legacy seed comparison is pending independent video review.

## Artifacts

`artifacts/v3r_general_r3_preflight/{A,B}/<story_folder>/{story_graph,materials,initial_edl,context_pool,observation_tasks,story_diagnostics,legacy_seed_metadata}.json` (+ `legacy_seed.json` for comeback), plus side `summary.json` / global `observation_tasks.json`, `inputs_prepared/*_legacy_seed_manifest.json`, `unittest.txt`, `PACK_SUMMARY.json`, this `REPORT.md`.
