# R4/R5.3b — A keeper_rescue:2 Story-First Flash config + real multi-round attempt

- Frozen prior pack: `67e49c4` (`artifacts/v3r_original_agent_A_keeper_rescue_20261126_r4r5_3`)
- Code entry unchanged: `run_r3_original_agent.py` / original `run_story_e2e`
- **No** algo / P1–P3 / Outer / Verifier edits; **no** R1–R3 regen; **no** cf397a7; **one** paid attempt; **no** auto-retry
- V0 via `--prepared-dir` (no re-render)

## 1. Flash model recovery + zero-HTTP preflight

Historical successful Story-First runs used provider model **`DeepSeek-V4.1-Flash`** (not `DeepSeek-V4-Pro-0813`).

```bash
source /home/lpy1/.config/migu-secrets/paratera.env
export STORY_API_ENABLE=1
export STORY_FIRST_LLM_MODEL=DeepSeek-V4.1-Flash
```

Zero-HTTP `configured_flash_model_id()` + `build_shared_story_first_provider()`:

| check | result |
|---|---|
| model id | `DeepSeek-V4.1-Flash` |
| ≠ STORY_LLM_MODEL (Pro) | true (`DeepSeek-V4-Pro-0813` remains planner-only) |
| gateway | existing_story_planner_service |
| token_param | `max_tokens` |
| thinking | `{"type":"disabled"}` |
| http | 0 |

See `flash_model_preflight.json` (no API keys).

## 2. Prepared V0

- `--prepared-dir artifacts/v3r_original_agent_A_keeper_rescue_20261126_r4r5_3`
- `render_manifest.reused_prepared_seed` set
- sha256 **`338e842499cb2d60df0de42d68e2fa05b9e2948f7a8350a3baa30c62eac4ff91`** (unchanged)
- V0 not re-rendered

## 3. Command (single run)

```bash
python run_r3_original_agent.py \
  --pack artifacts/v3r_critic_adapter_preflight/A_keeper_rescue \
  --evidence "$A_EV" --events "$A_EVENTS" \
  --match-json "$A_ORIGINAL_MATCH_JSON" --source "$A_ORIGINAL_MP4" \
  --source-manifest "$A_SOURCE_MANIFEST" \
  --original-algo ../../11.20sstory_chain/algo --allow-dev \
  --prepared-dir artifacts/v3r_original_agent_A_keeper_rescue_20261126_r4r5_3 \
  --out-dir artifacts/v3r_original_agent_A_keeper_rescue_20261126_r4r5_3b \
  --enable-real-api --approve-budget \
  --outer-rounds 3 --max-calls 23 --max-cost-usd 0.0988
```

## 4. Actual P1 Generator

All five intervals called **`DeepSeek-V4.1-Flash`** (`logical_role=story_first_generator`).

| interval | model | hyp status | n hyp | est_cost |
|---|---|---|---:|---:|
| interval_01 | `DeepSeek-V4.1-Flash` | UNVERIFIED_HYPOTHESES | 5 | 0.004126 |
| interval_02 | `DeepSeek-V4.1-Flash` | UNVERIFIED_HYPOTHESES | 5 | 0.001587 |
| interval_03 | `DeepSeek-V4.1-Flash` | NO_VALID_HYPOTHESES | 0 | 0.000961 |
| interval_04 | `DeepSeek-V4.1-Flash` | UNVERIFIED_HYPOTHESES | 5 | 0.003009 |
| interval_05 | `DeepSeek-V4.1-Flash` | UNVERIFIED_HYPOTHESES | 4 | 0.006034 |

Total proposals in pool: **19** (interval_03 produced no valid hypotheses).

### Hypotheses (summaries)

- `interval_01:H1`: 阿曼门将两次化险之间，阿联酋多次通过定位球与传中制造连续威胁。 · events=['event_000285', 'event_000311', 'event_000370', 'event_000395']
- `interval_01:H2`: 阿联酋多次射门被挡后，阿曼防线以解围结束威胁，形成重复化险节奏。 · events=['event_000313', 'event_000340', 'event_000374', 'event_000397']
- `interval_01:H3`: 阿联酋多次被犯规获得任意球，随后形成射门，构成定位球威胁链。 · events=['event_000334', 'event_000337', 'event_000363', 'event_000366']
- `interval_01:H4`: 阿曼换人后，阿联酋仍连续射门，显示换人未阻断对方进攻节奏。 · events=['event_000357', 'event_000374', 'event_000375']
- `interval_01:H5`: 阿曼多次赢得空中对抗后完成解围，形成从争顶到解围的防守模式。 · events=['event_000371', 'event_000381', 'event_000396', 'event_000397']
- `interval_02:H1`: 禁区内连续出现两次一对一射门尝试，可能构成同一波威胁的重复冲击。 · events=['event_000411', 'event_000412', 'event_000413']
- `interval_02:H2`: 短传与带球突破铺垫后出现一对一射门，可能形成由组织到终结的对比。 · events=['event_000408', 'event_000410', 'event_000411']
- `interval_02:H3`: 多次抢断与带球突破交替出现，可能反映中场反复争夺的防守链条。 · events=['event_000404', 'event_000405', 'event_000407']
- `interval_02:H4`: 射门后出现控球事件，可能显示威胁被化解后球权重新稳定。 · events=['event_000411', 'event_000413', 'event_000414']
- `interval_02:H5`: 界外球后经短传与突破发展至射门，可能构成一次完整进攻段落。 · events=['event_000406', 'event_000408', 'event_000411']
- `interval_04:H1`: 阿曼门将先经长传与争顶组织推进，随后一段连续射门扑救画面或构成威胁片段。 · events=['event_000423', 'event_000424', 'event_000472', 'event_000473']
- `interval_04:H2`: 换人后阿曼出现后场传递与争顶，随后形成射门与扑救，或为一次阶段转换。 · events=['event_000458', 'event_000459', 'event_000460', 'event_000472']
- `interval_04:H3`: 阿曼连续长传与争顶后出现一次凌空射门，或显示同一推进链条的延续。 · events=['event_000464', 'event_000465', 'event_000467', 'event_000472']
- `interval_04:H4`: 阿曼出现带球突破与被抢断交替，随后形成射门，或为攻防拉锯的片段。 · events=['event_000468', 'event_000469', 'event_000470', 'event_000472']
- `interval_04:H5`: 阿曼后场回传与争顶后出现凌空射门，或为从后向前的推进片段。 · events=['event_000472', 'event_000473', 'event_000474']
- `interval_05:H1`: 禁区内多次倒地申诉后，VAR介入判定点球被取消，威胁未转化为进球。 · events=['event_000617', 'event_000622', 'event_000627', 'event_000634']
- `interval_05:H2`: 多次射门被扑出，门将连续化解威胁，进攻未能转化为进球。 · events=['atom_fill_0049_Shot_5175752', 'atom_fill_0050_Save_5177072', 'atom_fill_0059_Shot_5360612', 'atom_fill_0060_Save_5361641']
- `interval_05:H3`: 多次犯规导致黄牌和任意球，比赛对抗强度上升。 · events=['event_000547', 'event_000548', 'event_000552', 'event_000565']
- `interval_05:H4`: 换人调整后防守动作增多，可能改变比赛节奏。 · events=['event_000563', 'event_000564', 'event_000569', 'event_000570']

## 5. Planner selection

Selected **`interval_05:H2`**:

- Events: `atom_fill_0049_Shot_5175752`, `atom_fill_0050_Save_5177072`, `atom_fill_0059_Shot_5360612`, `atom_fill_0060_Save_5361641`
- Relation: Shot→Save causal hypothesis（射门后门将扑救可能阻止进球）
- Rationale: aligns with template goal「同队门将多次化险」; insert probe between seg:5 and seg:6

Revision-planner model for decision call: `DeepSeek-V4-Pro-0813` (separate from Flash P1).

## 6. P2 source review (actual)

Status: **`NEEDS_REVISION`**

- Window2 (`Shot_5360612`/`Save_5361641`): **`REPLAY_CONFIRMED`** (`window_overlaps_replay_or_slowmo_annotation`; replay atoms `0061`/`0062`)
- Native replay trim recorded (`retained_source_windows_sec` [5352.612, 5369.167])
- Surviving window1 (`Shot_5175752`/`Save_5177072`): `NO_ANNOTATED_REPLAY_OVERLAP` but **`executable_safe_revision=false`**, reason **`no_first_live_evidence_pack_for_window`**, `first_live_status=NOT_VERIFIED`, `preview_only=true`

No safe insert applied to working EDL.

## 7. P3 / Outer / versions

| item | actual |
|---|---|
| P3 caption/local trim | **not executed** |
| requested outer rounds | 3 |
| completed outer rounds | **0** |
| `story_first_outer_comparison.json` | **absent** |
| v0 | reused prepared seed only |
| outer v1/v2/v3 MP4/EDL | **not produced** |
| main-loop decision | `UNRESOLVED` (no revision intents; no FIRST_LIVE / REVIEW_SUPPORTED candidate) |
| phase8 | `STOP_NO_ACTION` / `no_executable_revision_or_valid_source` |

### First failure blocking outer continuation

After P1+selection, P2 left trial in **`NEEDS_REVISION`** with **no executable safe revision** (missing first-live evidence pack). Main loop therefore did not render a story-first trial cut or enter `continue_story_first` outer iterations. Failure evidence preserved under `02_round_01/story_first_trial.json` + `story_first_feedback.json`. Algorithm not bypassed.

## 8. API / cost

| metric | this run (3b) | + prior 3 (`67e49c4`) |
|---|---:|---:|
| http_calls | **6** (5 Flash + 1 Pro planner) | **7** / 24 |
| est_cost_usd | **0.018484** | **0.019664** / 0.10 |
| caps | 23 / 0.0988 | original experiment ceiling |

## Non-claims

No FIRST_LIVE certification, no ACCEPTED_PREVIEW quality claim, no formal release. Research preview seed only.
