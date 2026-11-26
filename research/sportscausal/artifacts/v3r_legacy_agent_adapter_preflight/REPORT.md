# R4/R5.1 original Story Agent adapter preflight

- Code: `03c67e8` (`research/sportscausal-template-generalization`)
- Frozen R3: `539c421`
- Route: **original** P1/P2/P3 + double loop + Verifier unchanged
- Explicitly **not executed**: cf397a7 single-layer `general_story_agent` / `test_general_story_agent`
- Zero-cost: http_calls=0; no video decode/render; no R1–R3/history rerun; algo tree git-clean

## Commands

```bash
cd research/sportscausal
python -m unittest -v test_r3_legacy_agent_adapter
# -> 8/8 OK

ALGO=../../11.20sstory_chain/algo
A_EVENTS=/data2/lpy1/_story_va_outputs/v3/plan2/full_e2e_A_strict_lin_20261108_095704/01_to_04_fresh_v3r/01_enrich/events_enriched.json
B_EVENTS=/data2/lpy1/_story_va_outputs/v3/plan2/full_e2e_B_strict_lin_20261108_095704/01_to_04_fresh_v3r/01_enrich/events_enriched.json

python r3_legacy_agent_adapter.py \
  --story-dir artifacts/v3r_general_r3_preflight/A/comeback__1 \
  --evidence artifacts/stage1_2_evidence_preflight_20261125/A_uae_oman/keeper_rescue/evidence.json \
  --events "$A_EVENTS" --algo-dir "$ALGO" --allow-dev \
  --out-dir artifacts/v3r_legacy_agent_adapter_preflight/A_comeback

# A/keeper_rescue__2 -> A_keeper_rescue (same A evidence/events)
# A/turnover_to_goal__1 -> A_turnover_to_goal
# B/equalization__1 -> B_equalization with B evidence + B_EVENTS
```

Events source = Stage1.2-native enriched docs (A 879 / B 834 rows, including annotated non-LIVE). All frozen evidence LIVE atoms match native PTS/windows.

## Input hashes (sha256)

| input | sha256 |
|---|---|
| `A_evidence` | `9322933a9c3ef15a990c9377ed498e97b73cb20350bbfe279114bf2f3b4043fc` |
| `B_evidence` | `a673769fe1b81f93a34f9c987302af49f8988cbf02c429ad97b1317bf7b33292` |
| `A_events` | `33958b106f3daddd8830e8735f7583527b3aa3f39ca4b6a805b6b3cfe0fb0299` |
| `B_events` | `c47015ccc7009c1a5869174709ce76e73454a6c6fa4b34bc3a34cd8812e19b6e` |
| `A_comeback_story` | `24ee0c469c950a95d5009f9326f391a72ac48cb6e99e77533bb67689098b47b4` |
| `A_keeper_story` | `9742e9395c835d478879480bc93bf11e1bece9ab2420b2696dbdd3532977251a` |
| `A_turnover_story` | `8a026218d409eceb694a6a839d4440c3d0626a4bfd050cefbec8423699493c23` |
| `B_eq_story` | `f072887bb676893a4359e1e2180d4ebf91e58393af62f4cb18e689b5f0072431` |
| `A_legacy_seed` | `dec28e8e9d82825167e1ef0ac56f068a0b84578a7116f683e17b625d9f4a9274` |
| `algo_story_first_search` | `f7270f3d4fb83f260e4736faee453140cbcd295a881aebfdba637a8ae1c8f433` |

## Unit tests

`test_r3_legacy_agent_adapter`: **8/8 OK**. `test_general_story_agent` not run.

## Algo integrity

- `11.20sstory_chain/algo` git status: clean (unmodified).
- Every story `original_p1.p1_function == story_first_search.discover_story_first` with `api=None`, `http_calls=0`, `proposals=0`.

## Story results (structure only)

| story | seed_basis | segs | dur_s | anchors | P1 pairs | P1 intervals | notes |
|---|---|---:|---:|---:|---:|---:|---|
| A comeback:1 | legacy_action_candidates | 4 | 78.0 | 3 | 2 | 2 | action seed; legacy 89s file independent |
| A keeper_rescue:2 | r3_anchor_materials | 6 | 70.530 | 6 | 5 | 5 | roles=`goalkeeper_rescue` (not fake goals) |
| A turnover_to_goal:1 | r3_anchor_materials | 5 | 23.542 | 2 | 1 | 1 | all 7 atom IDs retained |
| B equalization:1 | r3_anchor_materials | 1 | 3.840 | 1 | 0 | 0 | missing score:2 + observe:5 retained |

### Semantic anchor bindings

- **A comeback**: score:1→`seg_opponent_opening_goal_action`; score:2→`seg_equalizer_goal_action`; score:3→`seg_go_ahead_goal_action` (+ buildup context seg, not an anchor).
- **A keeper**: 6 anchors ↔ seg:1..6, predicate/role `goalkeeper_rescue`.
- **A turnover**: start→seg:1 (`turnover_recovery`); outcome→seg:5 (`scoring_goal_action`); intermediates as `story_context`.
- **B equalization**: score:1→seg:1 only; score:2 has **no** media row.

### A comeback 78s vs 89s legacy independence

- Adapter action seed EDL: **4 segs / 78.0s** (`legacy_action_candidates`; scoreboard-confirmation windows excluded).
- Frozen R3 `legacy_seed.json` (`story_plan.json` timed edl): still **7 segs / 89.0s**, sha256 `dec28e8e9d82825167e1ef0ac56f068a0b84578a7116f683e17b625d9f4a9274` unchanged; not overwritten; remains independent Agent seed.
- New adapter `candidate_edl.json` is a separate file under this preflight pack.

### A turnover 7 events

EDL event_ids (order): `event_000668`, `event_000669`, `Pass_0100`, `aerial_0101`, `Assist_0102`, `Shot_0103`, `Goal_0104` — **all 7 preserved**.

### B missing score:2 / observe:5

- `missing_nodes_not_p1_anchors=["score:2"]`; `localization_status=missing_action`.
- `observe:5` (`missing_goal_localization`, search `[2480.82,2675.82]`) retained in bundle + plan `missing_evidence`.
- No adjacent P1 pair / no invented equalizer clip. Original Goal Recovery connection remains pending.

## P1 interval scopes and event coverage

All intervals status=`PREPARED_ONLY`, score_status=`OFFLINE_RESEARCH_ONLY`. No INVALID_INTERVAL / INSUFFICIENT_EVENTS in this run (actual result).

| story | interval | source_interval_sec | timed_events_in_scope | llm_context | known_replay_or_slowmo flags |
|---|---|---|---:|---:|---:|
| A comeback | 01 | [1347.123, 6436.924] | 530 | 240 (cap drops 290) | present in inventory |
| A comeback | 02 | [6458.924, 6829.456] | 58 | 58 | present |
| A keeper | 01 | [1966.45, 3338.39] | 120 | 120 | present |
| A keeper | 02 | [3351.3, 3504.14] | 15 | 15 | present |
| A keeper | 03 | [3515.83, 3543.01] | 2 | 2 | present |
| A keeper | 04 | [3553.57, 4755.79] | 78 | 78 | present |
| A keeper | 05 | [4769.62, 6552.01] | 205 | 205 | present |
| A turnover | 01 | [6824.07, 6841.456] | 3 | 3 | 0 flags in this narrow gap |
| B equalization | — | none | — | — | no P1 interval |

`annotated_nonlive_overlaps` on adapter reports: **[]** (no silent trim). Replay/slow-mo remain inventory flags inside prepared requests — reported, not certified LIVE.

## Generator request template / narrative semantics

Prepared `frozen_story_plan` / plan `template` carried into requests:

| story | template_id | name | category / subtype | narrative_goal |
|---|---|---|---|---|
| A comeback | comeback | 逆风翻盘 | 战局故事链 / 逆风翻盘 | 落后→追平→反超；后续首次直播动作支撑 |
| A keeper | keeper_rescue | 同队门将多次化险 | 人物故事链 / 同队门将多次化险 | 同队门将反复化解威胁 |
| A turnover | turnover_to_goal | 攻守转换与关键破门 | 关键转折故事链 / 攻守转换与关键破门 | 球权夺回到比分结果的关系路径候选 |
| B equalization | equalization | 落后追平 | 战局故事链 / 落后追平 | 落后到追平的阶段性战局变化 |

System prompt remains original falsifiable long-range hypothesis instructions; user payload includes `story_scope`, frozen plan reference, and full event inventory. **No HTTP call executed** (proposals=0).

## Limitations

This preflight only adapts R3 → native plan/EDL and prepares original P1 requests. It is not an end-to-end Story Agent run, not FIRST_LIVE, and not delivery quality. Renderer/Critic/Goal-Recovery wiring remains next work per `R3_LEGACY_AGENT_ADAPTER.md`.

## Artifacts

`artifacts/v3r_legacy_agent_adapter_preflight/{A_comeback,A_keeper_rescue,A_turnover_to_goal,B_equalization}/{story_plan,candidate_edl,adapter_bundle,report}.json` + `original_p1/**`, plus `unittest.txt`, `PACK_SUMMARY.json`, this `REPORT.md`.
