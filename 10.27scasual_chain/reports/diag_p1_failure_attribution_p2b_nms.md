# P1 流式拆条失败归因（rule-only + gold_events）

只读诊断；未改 strip / 参数 / 评测指标 / Qwen。

Baseline：offline 90.62% · B 81.46% · A 64.76% · precision 87.08% · matched 283/325 tracks。

## 1. A/B 四象限

| 象限 | 数量 |
|------|-----:|
| A_ok_B_ok | 310 |
| A_ok_B_fail | 10 |
| A_fail_B_ok | 46 |
| A_fail_B_fail | 71 |

### 按四大类

| category | A✓B✓ | A✓B✗ | A✗B✓ | A✗B✗ |
|----------|-----:|-----:|-----:|-----:|
| outcome | 112 | 3 | 23 | 22 |
| correction | 0 | 0 | 0 | 11 |
| danger | 189 | 1 | 21 | 7 |
| special | 9 | 6 | 2 | 31 |

**注意：存在 A✓B✗ = 10**：prefix 场景形成了严格链，但 oracle slice 上 strip 未严格成功。样例见 JSON `samples.a_ok_b_fail`。

## 2. A 失败 primary reason（互斥）

合计 A✗ = **117**（期望 ~154）

| reason | n | % |
|--------|--:|--:|
| F3_track_exists_category_wrong | 57 | 48.72 |
| F7_one_to_one_conflict | 24 | 20.51 |
| F4_track_exists_first_wrong | 16 | 13.68 |
| F1_no_candidate_generated | 8 | 6.84 |
| F5_track_exists_last_wrong | 5 | 4.27 |
| F2_candidate_generated_but_no_track | 5 | 4.27 |
| F6_track_exists_both_boundary_wrong | 2 | 1.71 |

## 3. B✓ A✗ 专项

合计 **46**

| B✓A✗ 原因 | 数量 | 占比 |
|-----------|-----:|-----:|
| track_merges_multi_gold | 17 | 36.96% |
| one_to_one_conflict | 12 | 26.09% |
| category_unstable | 9 | 19.57% |
| boundary_expands_merge | 5 | 10.87% |
| last_not_closed | 2 | 4.35% |
| no_candidate_in_prefix | 1 | 2.17% |

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

观测 tracks=413, matched=320, unmatched=**93**

| FP 类型 | n | % |
|--------|--:|--:|
| P4_wrong_category | 43 | 46.24 |
| P3_boundary_shift | 26 | 27.96 |
| P2_merged_multi_gold | 23 | 24.73 |
| P1_duplicate_like | 1 | 1.08 |

## 6. 四大类 + 模板

### 四大类

| category | gold | A strict | A% | B strict | B% | A-B gap(pp) | 主要 A 失败 |
|----------|-----:|---------:|---:|---------:|---:|------------:|------------|
| outcome | 160 | 115 | 71.88 | 135 | 84.38 | 12.5 | F3_track_exists_category_wrong |
| correction | 11 | 0 | 0.0 | 0 | 0.0 | 0.0 | F3_track_exists_category_wrong |
| danger | 218 | 190 | 87.16 | 210 | 96.33 | 9.17 | F3_track_exists_category_wrong |
| special | 48 | 15 | 31.25 | 11 | 22.92 | -8.33 | F3_track_exists_category_wrong |

### 模板（按 A 失败数排序）

| template | gold | A% | B% | A-B gap | 主要失败 |
|----------|-----:|---:|---:|--------:|----------|
| shot_save_chain | 151 | 86.09 | 96.03 | 9.94 | F3_track_exists_category_wrong |
| outcome_other | 48 | 64.58 | 79.17 | 14.59 | F3_track_exists_category_wrong |
| throw_in_build_up_chain | 31 | 45.16 | 25.81 | -19.35 | F7_one_to_one_conflict |
| team_buildup_goal | 53 | 75.47 | 88.68 | 13.21 | F3_track_exists_category_wrong |
| goal_line_extreme_save_chain | 60 | 85.0 | 91.67 | 6.67 | F3_track_exists_category_wrong |
| var_penalty_cancelled_chain | 6 | 0.0 | 0.0 | 0.0 | F3_track_exists_category_wrong |
| turnover_counter_goal | 22 | 77.27 | 90.91 | 13.64 | F3_track_exists_category_wrong |
| corner_coop_goal | 16 | 68.75 | 87.5 | 18.75 | F3_track_exists_category_wrong |
| shot_post_bar_chain | 13 | 61.54 | 53.85 | -7.69 | F3_track_exists_category_wrong |
| red_card_decision_chain | 5 | 0.0 | 0.0 | 0.0 | F2_candidate_generated_but_no_track |
| individual_breakthrough_goal | 10 | 60.0 | 60.0 | 0.0 | F3_track_exists_category_wrong |
| quick_restart_set_piece_chain | 4 | 25.0 | 75.0 | 50.0 | F3_track_exists_category_wrong |
| goal_disallowed_chain | 3 | 0.0 | 0.0 | 0.0 | F2_candidate_generated_but_no_track |
| second_phase_after_frame_chain | 5 | 60.0 | 60.0 | 0.0 | F3_track_exists_category_wrong |
| rebound_follow_up_goal | 4 | 50.0 | 100.0 | 50.0 | F4_track_exists_first_wrong |
| penalty_scored_chain | 5 | 100.0 | 100.0 | 0.0 |  |
| corner_cross_goal | 1 | 100.0 | 100.0 | 0.0 |  |

## 7. 样例

详见 `diag_p1_failure_attribution.json` → `samples`。


---
P1 结束；待确认后再进入 P2。
