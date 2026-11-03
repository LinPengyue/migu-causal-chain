# A/B 成片逐片段 QC

**付费 API:** 0  
**硬编码进球时间:** 无  
**success_claimed / render_ready:** false  

抽帧目录：`/data2/lpy1/_story_va_outputs/v3/plan2/video_qc_ab/{A,B}/`  
成片：  
- A: `.../closed_loop_A_uae_oman/04_phase5_live_goals/story_clean.mp4`  
- B（去重后）: `.../closed_loop_B_osasuna_celta/04_phase5_qc_fix/story_clean.mp4`

判定：`PASS` = 该段职责内合格；`FAIL` = 有明确证据的问题；`UNRESOLVED` = 证据不足或不在本段职责内。

---

## A 阿联酋–阿曼

| # | segment / role | media 窗 | 进球动作/破门 | LIVE/REPLAY | 与 8.31/故事一致 | 其他剪辑问题 | 判定 | 证据 |
|---|----------------|----------|---------------|-------------|------------------|--------------|------|------|
| 0 | title_open | — | n/a | n/a | n/a | 标题卡 | PASS | 包装段 |
| 1 | **opponent_opening_goal_action** | **1325–1347** (锚 **1337**) | 有：t≈8–14s 射门→球进网 | **首次 LIVE**（时钟走动 11:26→11:32，无 REPLAY 水印） | 8.31 outcome 链含该 LIVE Goal；V1 作「率先失球」对齐最后落后弧起点 | 窗尾有门将特写，可接受 | **PASS** | `A/opening/open_t{8,12,14}.jpg`；atom LIVE |
| 2 | deficit_scoreboard | 1409–1413 | 不要求破门 | LIVE 板面确认 0:1 | 与 score_path 一致 | 短锚点 | PASS | 职责=记分牌 |
| 3 | buildup corner `event_000276` | 1912–1924 | 无破门（角球布置） | LIVE | 在落后–扳平之间 | 以球员特写起幅，角球进攻方为阿曼，**弱蓄力** | **UNRESOLVED** | `A/buildup_corner/*`；`A/extra/src_1916.jpg`（OCR 曾误读 0:2，以 0:1 为准仍待多帧确认） |
| 4 | buildup shot `event_000472` | 4706–4718 | 无破门；阿联酋禁区进攻 | LIVE 0:1 @~46:57 | 时间落在弧内 | 可作蓄力候选 | PASS（弱） | `A/extra/src_4710.jpg` |
| 5 | **equalizer_goal_action** | **6437–6460** (锚 **6449**) | 有：传中→头/射→球进网 | **LIVE**（75:54→75:56） | 8.31 outcome；V1 转折 | 板面仍 0:1（滞后）属预期 | **PASS** | `A/equalizer/eq_t{10,12}.jpg` |
| 6 | equalizer_scoreboard | 6534–6538 | n/a | LIVE 1:1 确认 | score_path | — | PASS | 职责=记分牌 |
| 7 | **go_ahead_goal_action** | **6831–6853** (锚 **6843**) | 有：突破射门→球进网 | **LIVE**（82:28→82:30） | 8.31 outcome；V1 高潮 | 板面仍 1:1 滞后 | **PASS** | `A/goahead/ga_t{10,12}.jpg`；对齐先前 P6≈6843 |
| 8 | go_ahead_scoreboard | 6956–6960 | n/a | LIVE 2:1 | score_path | — | PASS | |
| 9 | title_close | — | n/a | n/a | n/a | 收尾卡 | PASS | |

**A 汇总：** 三颗关键进球片段 **PASS**。无发现 REPLAY 冒充。蓄力角球段偏弱 → UNRESOLVED。未宣称整片验收通过。

---

## B 奥萨苏纳–塞尔塔

| # | segment / role | media 窗 | 进球动作/破门 | LIVE/REPLAY | 与 8.31/故事一致 | 其他剪辑问题 | 判定 | 证据 |
|---|----------------|----------|---------------|-------------|------------------|--------------|------|------|
| 0 | title_open | — | n/a | n/a | n/a | | PASS | |
| 1 | arc_background_title | — | n/a | n/a | T01 弧前摘要 | | PASS | scope.background_plan |
| 2–3 | arc_background boards | 2070 / 2659 | **非进球**（仅板面） | LIVE 板 | 故意省略动作；首球 **1979** LIVE Goal 在 8.31 有链但未进 EDL | 弧前只用记分牌 | **UNRESOLVED**（设计取舍，非本段伪 LIVE） | story_scope.prior_*；strip clip17/18 @1979 |
| 4 | **opponent_opening_goal_action** | **3122–3144** (锚 **3133**) | 有：球进网 | **LIVE** | 8.31 outcome/corner_coop；对应最后落后弧「2:1 失球」 | 角色名像「开场失球」，实为**弧内**对手进球（非全场第一球） | **PASS**（内容）/ 命名易误解 | `B/opening/open_t12.jpg` |
| 5 | deficit_scoreboard | 3198–3202 | n/a | 板 2:1 | score_path | | PASS | |
| 6 | buildup `event_000458` | 3204–3217 | 射偏类，无破门 | LIVE | 弧内 | 尚可 | PASS（弱） | `B/extra/src_3208.jpg` |
| — | ~~buildup Shot@5657~~ | ~~5653–5665~~ | 与扳平窗 **>50% 重叠** | — | — | **重复镜头** | **FAIL→已修** | 旧 EDL；`resolve_delivery_window_conflicts` Pass3 已丢弃；新片无此段 |
| 7 | **equalizer_goal_action** | **5645–5668** (锚 **5657**) | 有：禁区混战/近门线 | **LIVE** | 8.31 corner_coop outcome | 去重后保留 | **PASS** | `B/equalizer/eq_t12.jpg` |
| 8 | equalizer_scoreboard | 5711–5715 | n/a | 2:2 板 | score_path | | PASS | |
| 9 | **go_ahead_goal_action** | **6780–6802** (锚 **6791**) | 有：球进网 | **LIVE** | 8.31 team_buildup | QC 叠字「反超 57′」与比赛钟不符（包装） | **PASS**（画面）/ 叠字 **UNRESOLVED** | `B/goahead/ga_t12.jpg` |
| 10 | go_ahead_scoreboard | 6881–6884 | n/a | 2:3 板 | score_path | | PASS | |
| 11 | title_close | — | n/a | n/a | n/a | | PASS | |

**B 汇总：** 3133 / 5657 / 6791 进球窗 **PASS（LIVE+破门）**。明确 FAIL 仅「蓄力与扳平重复」——已用通用重叠规则修复并重渲。全场第一球 1979 未进故事主片 → UNRESOLVED（T01 最后落后弧策略）。

---

## 8.31 ↔ V1 故事选择一致性

| 场 | 8.31 | V1 选择 | 一致？ |
|----|------|---------|--------|
| A | LIVE Goal@1337/6449/6843 均落入 outcome 链 | T01 最后落后弧：失球动作→扳平→反超，锚到上述三球 | **一致**（动作用 Goal 原子，板面用 score_path） |
| B | LIVE Goal@1979,3133,5657,6791 均有 outcome | 主弧从 **2:1@3199** 起；1979/2660 仅背景板 | **部分一致**：弧内三球一致；1979 有预测链但故事未选动作 |

---

## 已落地修复（有证据、非硬编码时间）

`phase5_delivery.resolve_delivery_window_conflicts` 增加 Pass3：若 `buildup*` 与任一 `*goal_action*` 时间窗重叠 ≥50%（或起点差 ≤1s），丢弃蓄力段。  
B 重渲：`.../04_phase5_qc_fix/story_clean.mp4`（已无 5653 重复蓄力）。

---

## 总判定

| 场 | 关键进球片段 | 整片验收 |
|----|--------------|----------|
| A | 1337 / 6449 / 6843 → **PASS** | **不通过终验**（候选成片；蓄力弱段 UNRESOLVED） |
| B | 3133 / 5657 / 6791 → **PASS**；重复蓄力 **已修** | **不通过终验**（1979 未进主片；叠字分钟 UNRESOLVED） |
