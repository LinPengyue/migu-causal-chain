# V3-R-General R1.1 / R2a.1 / R2a.2 zero-cost preflight

- Code: `c698ad6`
- Baseline artifacts (not re-run): `40c8db4` → `artifacts/v3r_general_r1_r2a_preflight/`
- Evidence: full Stage 1.2 `evidence.json` (A/B keeper_rescue copy ≡ alternating_threats sha); **not** Stage 2 `planner_messages.json`
- HTTP / LLM / VLM / render / manual candidate edits: **none**

## 1. Unit tests

```
python -m unittest -v test_v3r_general test_causal_episodes
→ Ran 24 tests in ~0.09s — OK
```

Full log: `unittest.log`.

## 2. Produced artifacts

Per match `A/` and `B/`:

| file | present |
|---|---|
| normalized_semantics.json | yes |
| with_chains/causal_episodes.json | yes |
| without_chains/causal_episodes.json | yes |
| with_chains/keeper_rescue.json | yes |
| without_chains/keeper_rescue.json | yes |
| with_chains/alternating_threats.json | yes |
| without_chains/alternating_threats.json | yes |
| ablation_diff.json | yes |
| summary.json | yes |

## 3. Focus audits

### 3.1 A374 / B615 attack-subject miss — **FIXED (R1.1 notes, not chains)**

| id | old 40c8db4 | new c698ad6 |
|---|---|---|
| A `event_000374` Shot notes=`2队球员看到进攻机会，选择打门` | shooter UNRESOLVED, predicates {} | `attacking_attempt` **team_2 EXPLICIT** (`annotated_shot`) |
| B `event_000615` Shot notes=`1队球员在禁区，起脚射门…` | shooter UNRESOLVED, predicates {} | `attacking_attempt` **team_1 EXPLICIT** (`annotated_shot`) |

No chain role inference involved (`n_inferred_roles=0` both matches).

### 3.2 A282 / 417 / 641 — **still correct 阿曼(team_2)**

| id | type | keeper | rescue? | notes basis |
|---|---|---|---|---|
| 282 | Save | team_2 EXPLICIT | yes | `2队守门员扑住了1队队员的打门` |
| 417 | Save | team_2 EXPLICIT | yes | `2队守门员扑救` |
| 641 | Defensive_action | team_2 EXPLICIT | yes | `2队守门员出击拦截` + Defender=`2队守门员` |

All remain in `keeper_rescue:2` (阿曼) under both with/without chains.

### 3.3 B625 — **team EXPLICIT + player CONFLICT retained**

- notes: `2队3号守门员在禁区将球解围踢走`
- attrs Defender: `team_2_player_13` → **player_status=CONFLICT**, team_status=EXPLICIT team_2
- predicates: **only** `goalkeeper_action` (not `goalkeeper_rescue`) — clearance without qualifying threat-backed rescue evidence

### 3.4 Ordinary keeper action vs threat-backed rescue

**A action-only (no rescue):** `399`（门将用手打出 / Goal_line_Incident — no rescue projection）

**B action-only:** `244,298,504,586,625,629`（抱住/顶出/解围等，无显式威胁化险谓词）

**Both action+rescue:** A `097,277,282,417,421,477,641`; B only `050,260`

This is intentional tightening vs 40c8db4 (which counted many bare Saves as rescue).

## 4. Local links & inferred subjects (exhaustive)

**Inferred roles: A=0, B=0.** No empty Shot/Save subjects restored by one-hop transfer.

### A local links (3) — all `delivery_keeper`, roles already explicit

| pair | Δt | notes | attrs | chains | judgment |
|---|---|---|---|---|---|
| 276→277 | 1.99s | 2队发角球 → 角球被1队守门员接住 | RP=2队球员; Defender=1队守门员 Attacker=2队球员 | pred_0015 PARTIAL goal_line; pred_0016 PARTIAL shot_save | Valid local assoc; rescue already on 277 from notes; chain **adds 276 into episode membership only** |
| 416→417 | 2.10s | 1队开角球 → 2队守门员扑救 | RP=1队球员 | pred_0032 PARTIAL shot_save | Same: membership merge only |
| 476→477 | 2.06s | 1队2号传中 → 2队守门员扑救 | BallController team_1_player_2 | pred_0042/0043 PARTIAL shot_save | Same |

### B local links (1)

| pair | Δt | notes | chains | judgment |
|---|---|---|---|---|
| 259→260 | 0.69s | 1队21号禁区传中 → 2队13号守门员扑住 | pred_0014/0015 PARTIAL shot_save | Membership merge only; 260 already rescue via annotated Save |

### Rejected (no silent accept)

- A `420→421` **actor_conflict** (twice): 420 notes `2队球员传中` vs 421 threat `1队球员的传中球` — **correctly rejected** (annotation inconsistency; no error propagation).
- A/B multiple `atom_fill_Shot→atom_fill_Save` **both_roles_missing** — empty fill atoms remain unbound (no hallucinated teams).
- B action_gap / unbound_non_save rejects as logged in `causal_episodes.json`.

## 5. Recovered Shot/Save subjects?

| class | result |
|---|---|
| Annotated notes like A374/B615 | **Recovered by R1.1 parser** |
| Empty `atom_fill_*` Shot/Save | **Still UNRESOLVED** (A: 6 Shot + 3 Save; B: 12 Shot + 8 Save) |
| Chain one-hop inference | **None applied** |

No evidence of wrong team propagation onto empty fills.

## 6. Episode double-count / bad merges

- Accepted links are exclusive endpoints; competing pairs rejected.
- Unlinked same-side overlapping windows may merge; **accepted shot/outcome pairs are never cross-merged**.
- with_chains multi-event episodes = the 3A+1B delivery pairs above; media window = union of members **without filling temporal gaps**.
- Distinct Oman rescues 282 / 417 / 421 / 477 / 641 remain **separate episodes** (no false merge).

## 7. Ablation: with_chains vs without_chains

For every pattern, **subjects, run structure, media windows, anchor_t identical**; only episode `event_ids` gain the preceding delivery when chains are on.

| match/pattern | with cand | without cand | membership delta |
|---|---|---|---|
| A keeper_rescue | 2 (UAE×2, Oman×5) | 2 (same) | +276,+416,+476 |
| A alternating | 1 (7 anchors, 3 runs) | 1 (same windows) | +276 on one node |
| B keeper_rescue | 1 (Celta×2) | 1 | +259 |
| B alternating | **0** | **0** | none |

**Honest chain value:** useful for attaching delivery context into the same episode clip window; **does not** create new story candidates, **does not** fix missing subjects, **does not** raise alternate-run counts.

## 8. vs 40c8db4 baseline (artifact compare only)

| item | 40c8db4 | this run | reading |
|---|---|---|---|
| A keeper cand | 2 (Oman 6 eps incl. 399) | 2 (Oman 5; **399 demoted** to action-only) | stricter rescue ≠ more candidates |
| B keeper cand | 1 (7 eps incl. bare Saves/clearances) | 1 (**2** threat-backed only) | large drop in episode count is filtering, not loss of team ID |
| A alternate | 1 / 15 anchors / 5 runs | 1 / 7 anchors / 3 runs | threat predicate tightened |
| B alternate | 1 / 12 anchors | **0 candidates** (only 1 threat episode < min 3 runs) | **capability surface shrink** for alternate under new definition — report as-is |
| A374/B615 | miss | fixed | real R1.1 gain |

**Do not treat candidate-count changes as improvement.** Net narrative-pattern yield is mixed: ownership fixes + action/rescue split are real; chain ablation is membership-only; B alternating candidate disappears under stricter threat evidence.

## 9. Constraints respected

No LLM/VLM, no atom regen, no manual candidate edits, no benchmark labels, no A/B-specialized rules, no video render. main / 11.20 delivery / Stage 2 LLM artifacts untouched.

`quality_verified=false`, `release_authorized=false`. DEV A/B only.
