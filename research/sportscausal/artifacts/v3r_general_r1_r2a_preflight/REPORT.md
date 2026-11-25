# V3-R-General R1/R2a zero-cost preflight

- Code: `4a9857a`
- Unittest `test_v3r_general.py`: **7/7 OK**
- Paid HTTP / LLM / VLM / render: **none**
- Evidence: Stage 1.2 A/B (HUMAN_ATOM_ENRICHED_DEV, `--allow-dev`)
- Patterns: `patterns/keeper_rescue.json`, `patterns/alternating_threats.json` (4 runs)

## 1. Unit tests
All 7 RTests passed (actor binding, possessive/passive, conflicts, alternation runs, chain context non-causal, multi-subject overlap).

## 2–3. Outputs per run
Each of `A_uae_oman__*`, `B_osasuna_celta__*` contains:
- `normalized_semantics.json`
- `anchor_candidates.json`

## 4. Keeper ownership (A/B)

### A 阿联酋(team_1) vs 阿曼(team_2)
| event | type | keeper | status | basis | notes |
|---|---|---|---|---|---|
| 097 | Goal_line_clearance | team_1 阿联酋 | EXPLICIT | attr Related_Player=1队守门员17号 | 被守门员用手解出 |
| 277 | Defensive_action | team_1 | EXPLICIT | notes+Defender 1队守门员 | 1队守门员接住 |
| **282** | Save | **team_2 阿曼** | EXPLICIT | notes 2队守门员扑住 | ✅ |
| 399 | Defensive_action | team_2 | EXPLICIT | notes 2队守门员…打出 | |
| **417** | Save | **team_2** | EXPLICIT | notes 2队守门员扑救 | ✅ |
| 421 | Save | team_2 | EXPLICIT | notes 2队守门员给扑飞 | |
| 477 | Save | team_2 | EXPLICIT | notes 2队守门员扑救 | |
| **641** | Defensive_action | **team_2** | EXPLICIT | notes+Defender 2队守门员出击拦截 | ✅ |

Team conflicts on rescue predicates: **0**. Player mostly UNRESOLVED (team-level).

### B 奥萨苏纳(team_1) vs 塞尔塔(team_2)
- 7× team_2 Celta rescues → candidate; 1× team_1 (`event_000244`) → no candidate (repeat min=2).
- **Player CONFLICT** `event_000625`: notes `2队3号守门员` vs attr `team_2_player_13` (team still EXPLICIT team_2).
- Team conflicts: **0**.

## 5. Story candidates (subject / core events / window / chains / episode count)
See `SUMMARY.json` and each `anchor_candidates.json`. Highlights:
- A keeper_rescue: **2** candidates (阿联酋×2 eps, 阿曼×6 eps)
- B keeper_rescue: **1** candidate (塞尔塔×7 eps)
- A/B alternating_threats: **1** each

## 6. Alternating subject sequences
- A: 阿曼 → 阿联酋×5 → 阿曼 → 阿联酋×4 → 阿曼×4 (5 runs, 15 anchors)
- B: 奥萨苏纳×4 → 塞尔塔×2 → 奥萨苏纳 → 塞尔塔 → 奥萨苏纳 → 塞尔塔 → 奥萨苏纳×2 (7 runs, 12 anchors)

## 7. Focus 282 / 417 / 641
All three **CORRECTLY** assigned to 阿曼(team_2) and present in `keeper_rescue:2`.

## 8. False matches & misses (not just counts)
**Misses (conservative):** A 3 / B 8 LIVE `atom_fill_*_Save_*` with **empty notes/attrs** → UNRESOLVED, no predicate. Not silent drops of annotated keepers; chain-fill atoms lack role text.
**Weak/edge:** A `097` team from attribute not note-local subject; B `625` player-number conflict (3 vs 13) while team OK — possible numbered-identity noise inside Celta candidate.
**No suspicious predicate without keeper token** in notes for either match.
**Not false:** non-Save Defensive/Goal_line with explicit 守门员+rescue verb (277/399/641/050/625/629) correctly included.

`quality_verified=false`, `release_authorized=false`. DEV only; not FanEdit scores. No algo edits this round.
