# P1 流式拆条失败归因（rule-only + gold_events）

只读诊断；未改 strip / 参数 / 评测指标 / Qwen。

Baseline：offline 90.62% · B 81.46% · A 64.76% · precision 87.08% · matched 283/325 tracks。

## 1. A/B 四象限

| 象限 | 数量 |
|------|-----:|
| A_ok_B_ok | 276 |
| A_ok_B_fail | 7 |
| A_fail_B_ok | 80 |
| A_fail_B_fail | 74 |

合计 437；A✗=154；B✗=81。

### 按四大类

| category | A✓B✓ | A✓B✗ | A✗B✓ | A✗B✗ |
|----------|-----:|-----:|-----:|-----:|
| outcome | 104 | 2 | 31 | 23 |
| correction | 0 | 0 | 0 | 11 |
| danger | 167 | 1 | 43 | 7 |
| special | 5 | 4 | 6 | 33 |

**存在 A✓B✗ = 7**：prefix 能严格成功而 oracle slice 失败。样例见 JSON `samples.a_ok_b_fail`。

## 2. A 失败 primary reason（互斥，n=154）

| reason | n | % |
|--------|--:|--:|
| F3_track_exists_category_wrong | 54 | 35.06 |
| F7_one_to_one_conflict | 42 | 27.27 |
| F4_track_exists_first_wrong | 37 | 24.03 |
| F6_track_exists_both_boundary_wrong | 10 | 6.49 |
| F1_no_candidate_generated | 8 | 5.19 |
| F2_candidate_generated_but_no_track | 2 | 1.3 |
| F5_track_exists_last_wrong | 1 | 0.65 |

解读要点：F7（一对一冲突）42 条说明过宽 track 覆盖多 gold；F3/F4 合计 91 条是边界/类别问题；F1 无候选仅 8 条。

## 3. B✓ A✗ 专项（n=80）

| B✓A✗ 原因 | 数量 | 占比 |
|-----------|-----:|-----:|
| track_merges_multi_gold | 50 | 62.5% |
| one_to_one_conflict | 27 | 33.75% |
| boundary_expands_merge | 2 | 2.5% |
| no_candidate_in_prefix | 1 | 1.25% |

主因是 **track 合并多条 gold（62.5%）** 与 **one-to-one 冲突（33.75%）** —— 指向链合并/边界过宽，而非「完全没有发现」。

## 4. B 失败 strip 内部（n=81）

| reason | n |
|--------|--:|
| no_geom_candidate | 40 |
| strip_out_category_wrong | 25 |
| geom_scored_but_filtered | 11 |
| strip_out_last_wrong | 3 |
| strip_out_first_wrong | 2 |

原 `strip_empty` 已下钻：无 geom 40 + margin 过滤 11；有输出后类别错 25、首/尾错 5。

## 5. Unmatched tracks FP（n=42）

| FP 类型 | n | % |
|--------|--:|--:|
| P4_wrong_category | 23 | 54.76 |
| P2_merged_multi_gold | 10 | 23.81 |
| P3_boundary_shift | 8 | 19.05 |
| P1_duplicate_like | 1 | 2.38 |

87.08% precision 剩余 42 个 FP：**真误报(P5)为 0**；主要是错类(P4)、多 gold 合并(P2)、边界偏移(P3)。

## 6. 四大类 + 模板

### 四大类

| category | gold | A% | B% | A-B gap(pp) | 主要 A 失败 |
|----------|-----:|---:|---:|------------:|------------|
| outcome | 160 | 66.25 | 84.38 | 18.13 | F3_track_exists_category_wrong |
| correction | 11 | 0.0 | 0.0 | 0.0 | F3_track_exists_category_wrong |
| danger | 218 | 77.06 | 96.33 | 19.27 | F4_track_exists_first_wrong |
| special | 48 | 18.75 | 22.92 | 4.17 | F3_track_exists_category_wrong |

- **danger** A 77% / B 96%，并不低于 outcome（A 66% / B 84%）。

- **special** 两端都低（A 18.75% / B 22.92%），主要是分类/模板问题，不只是 sliding。

- **correction** 11 条 A/B 全 0，类别错为主。


### 模板（A 失败拖累前部）

| template | gold | A% | B% | gap | 主要失败 |
|----------|-----:|---:|---:|----:|----------|
| shot_save_chain | 151 | 77.48 | 96.03 | 18.55 | F7_one_to_one_conflict |
| outcome_other | 48 | 47.92 | 79.17 | 31.25 | F7_one_to_one_conflict |
| throw_in_build_up_chain | 31 | 25.81 | 25.81 | 0.0 | F7_one_to_one_conflict |
| goal_line_extreme_save_chain | 60 | 71.67 | 91.67 | 20.0 | F4_track_exists_first_wrong |
| team_buildup_goal | 53 | 77.36 | 88.68 | 11.32 | F3_track_exists_category_wrong |
| corner_coop_goal | 16 | 62.5 | 87.5 | 25.0 | F3_track_exists_category_wrong |
| shot_post_bar_chain | 13 | 53.85 | 53.85 | 0.0 | F3_track_exists_category_wrong |
| individual_breakthrough_goal | 10 | 40.0 | 60.0 | 20.0 | F3_track_exists_category_wrong |
| var_penalty_cancelled_chain | 6 | 0.0 | 0.0 | 0.0 | F3_track_exists_category_wrong |
| red_card_decision_chain | 5 | 0.0 | 0.0 | 0.0 | F3_track_exists_category_wrong |
| turnover_counter_goal | 22 | 86.36 | 90.91 | 4.55 | F3_track_exists_category_wrong |
| second_phase_after_frame_chain | 5 | 40.0 | 60.0 | 20.0 | F7_one_to_one_conflict |
| quick_restart_set_piece_chain | 4 | 25.0 | 75.0 | 50.0 | F3_track_exists_category_wrong |
| goal_disallowed_chain | 3 | 0.0 | 0.0 | 0.0 | F3_track_exists_category_wrong |
| rebound_follow_up_goal | 4 | 50.0 | 100.0 | 50.0 | F4_track_exists_first_wrong |
| penalty_scored_chain | 5 | 100.0 | 100.0 | 0.0 |  |
| corner_cross_goal | 1 | 100.0 | 100.0 | 0.0 |  |

## 7. 样例

每个主要原因 3~5 条，见 `diag_p1_failure_attribution.json` → `samples`。


### A✓B✗ 全部 7 条摘要

- `05_2_4月19日_25-26赛季英超第33轮_切尔西VS曼联_4K国语__converted` / `ann_0011` cat=danger tpl=goal_line_extreme_save_chain b_reason=no_geom_candidate
- `09_2_9月14日_25-26赛季意甲第3轮_尤文图斯VS国际米兰_4K国语__convert` / `ann_0003` cat=special tpl=throw_in_build_up_chain b_reason=no_geom_candidate
- `09_2_9月14日_25-26赛季意甲第3轮_尤文图斯VS国际米兰_4K国语__convert` / `ann_0019` cat=outcome tpl=team_buildup_goal b_reason=strip_out_last_wrong
- `09_2_9月14日_25-26赛季意甲第3轮_尤文图斯VS国际米兰_4K国语__convert` / `ann_0024` cat=special tpl=throw_in_build_up_chain b_reason=no_geom_candidate
- `09_2_9月14日_25-26赛季意甲第3轮_尤文图斯VS国际米兰_4K国语__convert` / `ann_0031` cat=special tpl=throw_in_build_up_chain b_reason=no_geom_candidate
- `09_2_9月14日_25-26赛季意甲第3轮_尤文图斯VS国际米兰_4K国语__convert` / `ann_0047` cat=special tpl=throw_in_build_up_chain b_reason=no_geom_candidate
- `10月10日_2025世预赛欧洲区_奥地利VS圣马力诺_国语` / `ann_0004` cat=outcome tpl=shot_save_chain b_reason=strip_out_category_wrong

---
P1 结束；待确认后再进入 P2（优先边界/合并，而非先改分类器）。
