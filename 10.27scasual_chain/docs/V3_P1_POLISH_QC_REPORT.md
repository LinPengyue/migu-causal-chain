# A/B P1 质量收尾 QC

**付费 API:** 0  
**硬编码进球时间:** 无  
**success_claimed / render_ready:** false  
**成片:**
- A: `/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_A_uae_oman/04_phase5_p1_polish/story_clean.mp4`
- B: `/data2/lpy1/_story_va_outputs/v3/plan2/closed_loop_B_osasuna_celta/04_phase5_p1_polish/story_clean.mp4`

## P1 修复落地

| 项 | 处理 | 证据 |
|----|------|------|
| B 反超「57′」叠字 | 不烧录不可靠分钟；clean 叠字改到底部；顶左仅保留转播记分牌。先前「57′」实为转播钟 **86:57** 秒位与顶左「反超」碰撞的误读 | `p1_polish/B/goahead/ga_t12_top.jpg` 显示 86:57；`ga_t12_bottom.jpg` 仅「高潮」「反超」 |
| A 蓄力角球 event_000276 | 删除。T01 角球无球队归属；Related_Player 在交付事件为 2队（对手），叙事证据不足 | `missing_evidence` 含 `buildup_dropped_unattributed_setpiece:event_000276`；EDL 无 000276 |
| B 首球 1979 | **不进入**主弧动作 EDL。T01 最后落后弧自 2:1@3199 起；1979 属弧前，仅背景板 0:1/1:1 | `story_scope.json` prior + background_plan |
| B 重复蓄力 | 保持 Pass3 重叠规则（上一轮已修） | EDL 无 5653 蓄力 |

## A 全片检查

| # | role | media | 进球/LIVE | 比分/归属/顺序 | 判定 |
|---|------|-------|-----------|----------------|------|
| 1 | opponent_opening_goal_action | 1325–1347 @1337 | LIVE 破门 | 弧起点失球；主角 left 阿联酋 | **PASS** |
| 2 | deficit_scoreboard | 1409–1413 | 板 0:1 | 与 score_path 一致 | PASS |
| 3 | buildup Shot 000472 | 4706–4718 | LIVE 禁区射门，无破门职责 | 弧内蓄力 | PASS（弱） |
| — | ~~corner 000276~~ | — | — | 已删 | **PASS（已删）** |
| 4 | equalizer_goal_action | 6437–6460 @6449 | LIVE 破门 | 1:1 转折 | **PASS** |
| 5 | equalizer_scoreboard | 6534–6538 | 1:1 板 | 顺序正确 | PASS |
| 6 | go_ahead_goal_action | 6831–6853 @6843 | LIVE 破门 | 2:1 高潮 | **PASS** |
| 7 | go_ahead_scoreboard | 6956–6960 | 2:1 板 | 顺序正确 | PASS |

叙事衔接：失球→落后板→蓄力射门→扳平→反超，无 REPLAY 冒充关键球。整片仍 **candidate_only**。

## B 全片检查

| # | role | media | 进球/LIVE | 比分/归属/顺序 | 判定 |
|---|------|-------|-----------|----------------|------|
| bg | arc boards 2070/2659 | 板 | 弧前 0:1 / 1:1 | 非 1979 动作 | PASS（设计） |
| 1 | opponent_opening_goal_action | 3122–3144 @3133 | LIVE 破门 | 弧内失球→2:1（非全场首球） | **PASS** |
| 2 | deficit_scoreboard | 3198–3202 | 2:1 | | PASS |
| 3 | buildup 000458 | 3204–3217 | LIVE 弱 | | PASS（弱） |
| 4 | equalizer_goal_action | 5645–5668 @5657 | LIVE 破门 | 2:2 | **PASS** |
| 5 | equalizer_scoreboard | 5711–5715 | 2:2 | | PASS |
| 6 | go_ahead_goal_action | 6780–6802 @6791 | LIVE 破门；叠字无分钟 | 转播钟约 86:57，板仍 2:2 滞后 | **PASS** |
| 7 | go_ahead_scoreboard | 6881–6884 | 2:3 | 主角 right 塞尔塔 | PASS |

1979：**UNRESOLVED/by-design omit**（T01 最后落后弧，不强行添加）。

## 总判定

| 场 | 关键进球 | P1 项 | 终验 |
|----|----------|-------|------|
| A | PASS | 角球已删 | 仍不宣称 render_ready |
| B | PASS | 分钟叠字已消；1979 按 T01 省略 | 仍不宣称 render_ready |
