# 法国场 V3 零样本验证 QC（规则基线）

**冻结 Commit:** `2d1ec9c`（algo 与 HEAD 文档提交相对无算法 diff）  
**付费 API / 新 Agent 模式:** 0 / 未启用  
**success_claimed / render_ready:** false  
**人工因果链结构进 8.31/V1:** false（仅原子 type/t_ms/LIVE·REPLAY）

## 1. 比赛身份与输入

| 项 | 值 |
|----|----|
| match_id | `2022年11月23日 法国vs澳大利亚` |
| 球队 | team_1 法国 / team_2 澳大利亚 |
| 视频 | `/mnt/data4/migu/2022年11月23日 法国vs澳大利亚.mp4` sha256 `67462dba…e978` |
| 原始事件 | `data/交付_out/2022年11月23日 法国vs澳大利亚.json`（302 events）sha256 `8756bb82…7d3f` |
| 原子来源 | 同目录 `*_causal.json`（15 chains / 73 唯一原子）sha256 `86c19aec…2390` |
| 输出根 | `/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_FR_france_australia_zeroshot/` |
| MP4 | `.../04_phase5/story_clean.mp4` |

## 2. 缓存隔离

见 `_run_meta/ISOLATION_AND_IDENTITY.json`。未读取：
- `reports/phase5/france_australia_first_run/**`
- `story_compose_phase3a*_france_*.json`
- `datasets/matches/.../highlight_gold*.json` / `strip_gold.json`
- 任何历史人工 EDL / 视频定位结果

**运行备注：** attempt1 因 `--algo-root` 误指到 `.../algo` 导致找不到 `eval/strip_adapter`（环境路径问题，**未改代码**）；attempt2 使用与 A/B 一致的 `.../10.27scasual_chain` 作为 algo_root，保存为首次成功零样本产物。失败日志：`_run_meta/console_attempt1_strip_path_fail.log`。

## 3. 原子补全统计与覆盖限制

| 指标 | 值 |
|------|----|
| n_raw_events | 302 |
| n_causal_atoms_unique | 73 |
| n_injected | 73（skipped_dup 0） |
| Goal 注入 | 24（LIVE 5 / REPLAY 19） |
| 注入类型 | Dribble_past1 Pass8 Assist11 Shot25 Goal24 Corner1 … |

**覆盖限制（明确）：** 补充原子 **仅来自** `*_causal.json` 里已被人工选入因果链的事件（本场 73 个 `event_id` 全集 = 注入 `source_event_ids` 全集，`subset=true`）。  
未进入人工因果链的检测事件 **不会** 被补全；因此本输入 **不是** 全场自动检测覆盖。`enrichment.provenance=causal_atom_fill`。

## 4. 8.31 / V1 统计

| 阶段 | 统计 |
|------|------|
| 8.31 strip | n_events=375, n_chains=68, cats danger24 / special28 / outcome14 / correction2 |
| predicted_causal | 68 chains, goal_terminals(raw adapt)=49 |
| live_goals filter 后 audit | live_candidate=11, replay_detected=0（phase5 输入已丢 replay Goal） |
| T01 | protagonist=**left 法国**, template=T01_comeback, tier=story |
| 标题 | 法国 逆转 澳大利亚 |

## 5. 故事规划与 EDL

score_path：0:0 → **0:1@1535.65** → **1:1@2513.29** → **2:1@2904.31** → **3:1@5594.3** → **4:1@5820.46**

| # | role | media | 锚点 | 判定 | 证据 |
|---|------|-------|------|------|------|
| — | （缺）opponent_opening_goal_action | — | LIVE Goal@1351 存在但未进 EDL | **FAIL**（弧起点失球动作缺失） | EDL 无该 role；见下 |
| 2 | deficit_scoreboard | 1534–1538 | 板 0:1 GOODWIN 9′ | **PASS** | `board_1535/t1535.jpg` |
| 3 | equalizer_goal_action | 2398–2420 | @2410 | **PASS** LIVE 射门入网过程（板仍 0:1） | `equalizer_2410/t2410.jpg` |
| 4 | equalizer_scoreboard | 2512–2516 | 1:1 | PASS | score_path |
| 5 | go_ahead_goal_action | 2714–2736 | @2726 | **PASS** LIVE 攻门→庆祝（板 1:1 滞后） | `goahead_2726/t2726.jpg` `t2732.jpg` |
| 6 | go_ahead_scoreboard | 2903–2907 | 2:1 | PASS | |
| 7 | lead_extend_1_goal_action | 5422–5445 | @5434 | **PASS** LIVE 禁区头球攻门 | `extend_5434/t5434.jpg` |
| 8 | lead_extend_1_scoreboard | 5593–5597 | 3:1 | PASS | |
| 9 | lead_extend_2_goal_action | 5650–5672 | @5662 | **PASS** LIVE 球进网（板 3:1→将成 4:1） | `extend_5662/t5662.jpg` |
| 10 | lead_extend_2_scoreboard | 5819–5823 | 4:1 | PASS | |

### 原子 Goal@1351（澳队首球候选）单独核验

| 项 | 结果 |
|----|------|
| enrich 标记 | LIVE |
| 画面 t1351 | 08:23 **仍 0:0**，法队攻澳禁区，**未见破门** |
| t1365 | 08:37 法 21 号倒地，仍 0:0 |
| 与记分牌 | 真实 0:1 确认在 ~1535（GOODWIN 9′） |
| 判定 | **FAIL**（该 LIVE Goal 原子时间/内容不对齐真实开场失球） |

## 6. 整体故事 QC

| 检查 | 判定 |
|------|------|
| 主角归属 | **PASS**（法国 left） |
| 比分节点顺序 | **PASS**（与 score_path 一致） |
| 扳平/反超/扩大 LIVE 动作 | **PASS**（4 段关键动作） |
| 开场失球 LIVE 动作 | **FAIL**（EDL 缺失；可用原子 1351 视觉失败） |
| REPLAY 冒充关键球 | 未见（关键窗为直播远景/庆祝） |
| 因果链合理性 | **UNRESOLVED/弱**（大量 Goal 原子为 REPLAY 时间戳；8.31 outcome 有 14 条但混杂） |
| 输入覆盖 | **UNRESOLVED 限制**（仅人工链内事件） |
| 终验 render_ready | **不通过** |

## 7. 总判定

- **可复现零样本跑通**冻结流程并出片。  
- 逆转主弧（扳平→反超→两记扩大）视觉 **PASS**。  
- **开场失球动作 FAIL** + 原子覆盖非全自动 → **整场不宣称验收通过**。
