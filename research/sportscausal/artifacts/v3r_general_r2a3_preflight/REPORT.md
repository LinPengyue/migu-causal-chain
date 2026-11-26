# V3-R-General R2a.3 zero-cost preflight

- Code: `3fd44a8`
- Inputs: Stage 1.2 full evidence + R2a.2 `normalized_semantics.json` + verified `inputs_prepared/*_score_path_from_t01.json` (`score_side_mapping` left=team_1, right=team_2)
- Arms: `full` / `without_chains` / `without_score`
- HTTP / LLM / render / manual candidate edits: **none**
- Unittest: **38/38 OK** (`unittest.txt`)

## Focus audits

### Dual-view delivery↔keeper (correct)
| pair | edge | dual projections (threat attacker + rescue keeper) |
|---|---|---|
| A416→417 | `delivery_keeper` | team_1 threat + team_2 rescue/action — **yes** (also without_chains) |
| A476→477 | `delivery_keeper` | same — **yes** |
| B259→260 | `delivery_keeper` | team_1 threat + team_2 rescue — **yes** |

### A398→399→400 continuous path
- full: one component `398-399-400` via `delivery_keeper` + `keeper_deflection_followup` (chain-supported)
- without_chains: only `398→399` atomic delivery; `400` stays separate shot attempt
- Continuous three-event path **needs chain support** for the deflection follow-up

### B586→587 context rescue
- Edge `keeper_deflection_followup` / basis `explicit_recovery_reference` (notes: 1队球员…将2队守门员扑出的球控下)
- Promotes `goalkeeper_rescue` on 586 (`deflection_and_opponent_followup`) + `attacking_threat` on 587
- Holds in without_chains (atomic explicit recovery) — **not score-dependent**

### A640→641 subtype independence
- Linked as `shot_save` with chain support subtypes **`outcome_other`** (pred_0063/0065)
- No longer blocked by non-SAVE_CHAINS subtype filter — **yes**

### A420→421 conflict
- Still **rejected** `actor_conflict` (notes 2队传中 vs 1队传中球) — unchanged correct refuse

### B625 player conflict
- Still team EXPLICIT team_2 + **player CONFLICT** (3号 vs attr 13); action-only, not rescue

### Duplicate counting
- Same-predicate event reuse across episodes: **A=0, B=0**

### B alternating vs R2a.2
- R2a.2: **0** candidates (1 threat episode)
- R2a.3 full: **1** candidate, 7 anchors, 6 runs — includes score-bound goal threats + 586 deflection path
- without_score: **0** candidates again — score path is necessary for this candidate surface
- Honest read: recovery is real relative to R2a.2 threat scarcity, but inflated by score→goal→threat projections on empty fills; **do not equate candidate count with story quality**

## Own-goal special note (A first 0:1) — NOT patched

Independent match fact: opening `0:0→0:1` (`delta_side=right` → score beneficiary **阿曼 team_2**) involves an **own goal**.

System behavior (left unchanged):
1. Binds LIVE Goal `atom_fill_0004_Goal_1337123` with `actor=team_2` (= score beneficiary).
2. Infers empty Shot `atom_fill_0003_Shot_1335974` shooter as **team_2** via `shot_goal` + score binding.

**Risk:** score beneficiary ≠ ball-striking / execution side on an own goal. Empty notes provide no execution claim; inference currently copies beneficiary onto the preceding empty Shot. Recorded for GPT review; **candidates not manually corrected**.

Other A goals (1:1, 2:1) similarly bind beneficiary team_1 with inferred empty-shot shooters; no own-goal flag raised for those by the user.

## Empty Shot/Save recovery

| | empty LIVE Shot | inferred shooter | empty LIVE Save | inferred keeper |
|---|---|---|---|---|
| A | 6 | **3** (all via score-bound Goal+chain shot_goal) | 3 | **0** |
| B | 12 | **4** (same pattern) | 8 | **0** |

Remaining empty fills stay conditional/unresolved — no forced both-unknown completion without score+chain support.

## Independent contributions

| source | A | B |
|---|---|---|
| Atomic relations (`without_chains` links) | 6 delivery/shot_save | 2 delivery + deflection followup |
| Atomic role inferences | 0 | 0 |
| Chain-only link delta (full−without_chains) | +4 | +4 |
| Score-bound goals | 3 | 4 (1 unresolved) |
| Role inferences needing score∩chain | 3 | 4 |
| Pattern surface without score | keeper same; alternate shrinks (B alternate→0) | |

Atomic layer alone already yields dual-view for key delivery/saves and B586 rescue. Chains add multi-hop deflection/shot_goal membership. Score adds goal anchors and empty-shot actor hypotheses (including the own-goal mis-attribution risk above).

## Artifacts

Per match `A|B/{full,without_chains,without_score}/`: `relation_graph.json`, `causal_episodes.json`, `keeper_rescue.json`, `alternating_threats.json`; plus `diff_*.json`, `summary.json`. Pack: `unittest.txt`, `REPORT.md`, `PACK_SUMMARY.json`, `inputs_prepared/`.

`quality_verified=false`, `release_authorized=false`.
