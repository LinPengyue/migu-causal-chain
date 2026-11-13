# Exp B — story-level insert audit (0 HTTP, proposal only)

- Base docs HEAD: `68d58c2`
- Baseline EDL: `/tmp/lpy1_v3a_blind_repair_B_historical_20261112/agent_input/04_phase5/candidate_edl.json`
- SHA256: `4afc619b6a961e9d5fa6ade37af0218a3654ba6e3a6687510c04726b87489075`
- `api_calls=0`, formal EDL/BEST **not modified**, no render

## 1. Full baseline EDL (active export)

| # | segment_id | role | beat | media_in | media_out | event_ids | first_live_status |
|--:|---|---|---|---:|---:|---|---|
| 0 | `seg_title_open` | story_title | 铺垫 | None | None | [] | None |
| 1 | `seg_opponent_opening_goal_action` | opponent_opening_goal_action | 铺垫 | 1293.71 | 1315.71 | ['v3_goal_goalcand_00_00_to_01'] | None |
| 2 | `seg_setup_deficit` | deficit_scoreboard_anchor | 铺垫 | 1409.43 | 1412.93 | [] | None |
| 3 | `seg_buildup_event_000411` | buildup_action | 蓄力 | 3442.75 | 3454.75 | ['event_000411'] | None |
| 4 | `seg_equalizer_scoreboard` | equalizer_scoreboard_anchor | 转折 | 6534.62 | 6538.12 | [] | None |
| 5 | `seg_go_ahead_goal_action` | go_ahead_goal_action | 高潮 | 6801.28 | 6823.28 | ['v3_goal_goalcand_04_11_to_21'] | None |
| 6 | `seg_go_ahead_scoreboard` | go_ahead_scoreboard_anchor | 高潮 | 6956.12 | 6959.62 | [] | None |
| 7 | `seg_title_close` | story_wrap_title | 收尾 | None | None | [] | None |

### Role map
- **进球动作**: `seg_opponent_opening_goal_action` (1293.71–1315.71), `seg_go_ahead_goal_action` (6801.28–6823.28)
- **比分确认**: deficit 1409.43–1412.93; **equalizer scoreboard** 6534.62–6538.12; go-ahead board 6956.12–6959.62
- **铺垫**: title + opening goal + deficit
- **蓄力**: `seg_buildup_event_000411` 3442.75–3454.75
- **转折**: equalizer scoreboard only (**缺少 equalizer_goal_action**)
- **高潮/收尾**: go-ahead goal+board; wrap title

### B 扳平是否重复表达？
- 已有扳平**记分牌**，**没有**扳平**进球动作**片段。
- 新增 `equalizer_goal_action` @6441.88–6459.60 是补缺，不是重复进球动作。
- **受保护锚点**（不得删除/替换）: opening goal action、go-ahead goal action。

## 2. Schemes A / B / C

Candidate insert (hypothesis boundaries): **[6441.88, 6459.60]** after `seg_buildup_event_000411`, before `seg_equalizer_scoreboard`.

| 方案 | 做法 | 事实源序 | 重叠 | 保护进球锚点 | 主要风险 | 评价 |
|---|---|---|---|---|---|---|
| **A** | 新增进球，**保留**扳平记分牌 | OK | 无 | 保留 | 蓄力→进球源跳跃 ~2987s；窗内回放未完全排除；边界未锁定 | **推荐** |
| **B** | 新增进球，**裁切排除**扳平记分牌 | OK | 无 | 保留（未动进球动作锚点） | 比分确认更依赖窗内记分牌（可能偏弱）；同上跳跃/回放 | 仅当连续审片确认窗内 1-1 足够清晰时考虑；更稳妥用缩短而非排除 |
| **B′ 缩短记分牌** | 新增进球，记分牌缩至 1.5s | OK | 无 | 保留 | 同 A，略减转折冗余 | A 的温和变体 |
| **C** | 调整故事位置但不破坏比赛事实序 | 与 A 同槽 | 无 | 保留 | 当前 EDL **没有**其他合法插入点；放到记分牌后/蓄力前会破坏源序 | **坍缩为 A**；除非另写桥接段 |

### 检查摘要
- **进球身份**: 补的是扳平进球动作；不触及 opening/go-ahead 受保护动作。
- **故事顺序**: A/B/C 均保持源 PTS 非降序。
- **源 PTS 跳跃**: buildup→goal ≈2987s（故事跳跃大，需叙事接受或另补桥）。
- **比分逻辑**: A 保留 6534 记分牌确认最稳；B 削弱显式确认。
- **角色覆盖**: A/B/C 均覆盖缺失的 `equalizer_goal_action`。
- **回放风险**: 窗内静帧未见明确回放角标；Stage7 入网后切镜≠回放；**未**裁定窗内无回放。

## 3. 建议

**采用方案 A（提案级）**：插入扳平进球动作并保留 `seg_equalizer_scoreboard`；不删除任何受保护进球锚点；不自动应用/渲染。

后续仍需：人工锁定精确 in/out、连续片回放审查、是否接受大跨度故事跳跃或另加桥接。

## 产物
- `docs/V3A_EXPB_STORY_INSERT_COMPARISON.json`
- `docs/V3A_EXPB_BASELINE_EDL_FULL.json`
- `docs/V3A_EXPB_SCHEME_A_CANDIDATE_EDL.json`
- `docs/V3A_EXPB_SCHEME_B_CANDIDATE_EDL.json`
- `docs/V3A_EXPB_SCHEME_C_CANDIDATE_EDL.json`
