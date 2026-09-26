# Phase1 拆条回归（P3）

结果：**FAIL**

- profile: `production`
- report: `reports/report_stream_strip_rule.json`
- baseline: `reports/baseline_phase1_frozen.json`

## offline → B → A

| 层 | 当前 |
|----|-----:|
| offline | 100.0% |
| B oracle | None% |
| A stream | None% |

gaps: offline−B = None pp； B−A = None pp

## vs 冻结基线

| metric | baseline | current | Δ | pass |
|--------|---------:|--------:|--:|:----:|
| offline_strict | 90.62 | 100.0 | 9.38 | ✗ |
| B_strict | 81.46 | None | None | ✗ |
| A_strict | 76.66 | None | None | ✗ |
| A_precision | 74.28 | None | None | ✗ |
| n_tracks | 451 | None | None | ✗ |
| n_matched_gold | 335 | None | None | ✗ |

## 不变量

- `sliding_merge_mode` expect=none current=none ✓
- `sliding_post_nms` expect=off current=off ✓
- `stream_source` expect=gold_events current=gold_events ✓
- `match_mode` expect=bipartite_max_weight_one_to_one current=bipartite_max_weight_one_to_one ✓
- `one_to_one` expect=matched_gold == unique_matched_tracks current={'one_to_one_ok': None, 'n_matched_gold': None, 'n_unique_matched_tracks': None} ✗

