# P1 流式拆条失败归因（rule-only + gold_events）

只读诊断；未改 strip / 参数 / 评测指标 / Qwen。

Baseline：offline 90.62% · B 81.46% · A 64.76% · precision 87.08% · matched 283/325 tracks。

## 1. A/B 四象限

| 象限 | 数量 |
|------|-----:|
| A_ok_B_ok | 321 |
| A_ok_B_fail | 14 |
| A_fail_B_ok | 35 |
| A_fail_B_fail | 67 |

### 按四大类

| category | A✓B✓ | A✓B✗ | A✗B✓ | A✗B✗ |
|----------|-----:|-----:|-----:|-----:|
| outcome | 115 | 3 | 20 | 22 |
| correction | 0 | 0 | 0 | 11 |
| danger | 197 | 1 | 13 | 7 |
| special | 9 | 10 | 2 | 27 |

**注意：存在 A✓B✗ = 14**：prefix 场景形成了严格链，但 oracle slice 上 strip 未严格成功。样例见 JSON `samples.a_ok_b_fail`。

## 2. A 失败 primary reason（互斥）

合计 A✗ = **102**（期望 ~154）

| reason | n | % |
|--------|--:|--:|
| F3_track_exists_category_wrong | 52 | 50.98 |
| F7_one_to_one_conflict | 25 | 24.51 |
| F4_track_exists_first_wrong | 13 | 12.75 |
| F1_no_candidate_generated | 8 | 7.84 |
| F6_track_exists_both_boundary_wrong | 3 | 2.94 |
| F2_candidate_generated_but_no_track | 1 | 0.98 |

## 3. B✓ A✗ 专项

合计 **35**

| B✓A✗ 原因 | 数量 | 占比 |
|-----------|-----:|-----:|
| track_merges_multi_gold | 15 | 42.86% |
| one_to_one_conflict | 15 | 42.86% |
| boundary_expands_merge | 5 | 14.29% |

## 4. B 失败 strip 内部

合计 B✗ = **81**

| reason | n |
|--------|--:|
| no_geom_candidate | 40 |
| strip_out_category_wrong | 25 |
| geom_scored_but_filtered | 11 |
| strip_out_last_wrong | 3 |
| strip_out_first_wrong | 2 |

## 5. Unmatched tracks（FP）

观测 tracks=451, matched=335, unmatched=**116**

| FP 类型 | n | % |
|--------|--:|--:|
| P3_boundary_shift | 53 | 45.69 |
| P4_wrong_category | 40 | 34.48 |
| P2_merged_multi_gold | 22 | 18.97 |
| P1_duplicate_like | 1 | 0.86 |

## 6. 四大类 + 模板

### 四大类

| category | gold | A strict | A% | B strict | B% | A-B gap(pp) | 主要 A 失败 |
|----------|-----:|---------:|---:|---------:|---:|------------:|------------|
| outcome | 160 | 118 | 73.75 | 135 | 84.38 | 10.63 | F3_track_exists_category_wrong |
| correction | 11 | 0 | 0.0 | 0 | 0.0 | 0.0 | F3_track_exists_category_wrong |
| danger | 218 | 198 | 90.83 | 210 | 96.33 | 5.5 | F3_track_exists_category_wrong |
| special | 48 | 19 | 39.58 | 11 | 22.92 | -16.66 | F3_track_exists_category_wrong |

### 模板（按 A 失败数排序）

| template | gold | A% | B% | A-B gap | 主要失败 |
|----------|-----:|---:|---:|--------:|----------|
| outcome_other | 48 | 58.33 | 79.17 | 20.84 | F3_track_exists_category_wrong |
| shot_save_chain | 151 | 90.07 | 96.03 | 5.96 | F3_track_exists_category_wrong |
| throw_in_build_up_chain | 31 | 58.06 | 25.81 | -32.25 | F7_one_to_one_conflict |
| team_buildup_goal | 53 | 81.13 | 88.68 | 7.55 | F3_track_exists_category_wrong |
| goal_line_extreme_save_chain | 60 | 88.33 | 91.67 | 3.34 | F3_track_exists_category_wrong |
| var_penalty_cancelled_chain | 6 | 0.0 | 0.0 | 0.0 | F3_track_exists_category_wrong |
| shot_post_bar_chain | 13 | 61.54 | 53.85 | -7.69 | F3_track_exists_category_wrong |
| red_card_decision_chain | 5 | 0.0 | 0.0 | 0.0 | F3_track_exists_category_wrong |
| turnover_counter_goal | 22 | 81.82 | 90.91 | 9.09 | F3_track_exists_category_wrong |
| individual_breakthrough_goal | 10 | 60.0 | 60.0 | 0.0 | F3_track_exists_category_wrong |
| corner_coop_goal | 16 | 81.25 | 87.5 | 6.25 | F3_track_exists_category_wrong |
| quick_restart_set_piece_chain | 4 | 25.0 | 75.0 | 50.0 | F3_track_exists_category_wrong |
| goal_disallowed_chain | 3 | 0.0 | 0.0 | 0.0 | F3_track_exists_category_wrong |
| second_phase_after_frame_chain | 5 | 60.0 | 60.0 | 0.0 | F3_track_exists_category_wrong |
| rebound_follow_up_goal | 4 | 50.0 | 100.0 | 50.0 | F4_track_exists_first_wrong |
| penalty_scored_chain | 5 | 100.0 | 100.0 | 0.0 |  |
| corner_cross_goal | 1 | 100.0 | 100.0 | 0.0 |  |

## 7. 样例

详见 `diag_p1_failure_attribution.json` → `samples`。


---
P1 结束；待确认后再进入 P2。
