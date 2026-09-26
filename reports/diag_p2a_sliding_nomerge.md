# P2-A：sliding anti-merge（`sliding_merge_mode=none`）

只改 `segment_sliding_geom` 的 overlap 合并；window/step/anchor/threshold/matcher/Qwen 未动。

- legacy：`production`（`sliding_merge_mode=legacy`）
- 实验：`production_p2a_nomerge`（`sliding_merge_mode=none`）
- 评测：rule-only + gold_events + one-to-one matcher

## 主指标

| 指标 | legacy | none | Δ |
|------|-------:|-----:|--:|
| offline strict | 90.62% | 90.62% | 0 |
| B strict | 81.46% | 81.46% | 0 |
| A streaming strict | **64.76%** | **76.66%** | **+11.90** |
| streaming precision | **87.08%** | **74.28%** | **-12.80** |
| tracks | 325 | 451 | +126 |
| matched gold (= unique tracks) | 283 | 335 | +52 |

## P1 关键失败项

| 项 | legacy | none | Δ |
|----|-------:|-----:|--:|
| F7 one_to_one_conflict | 42 | 25 | **-17** |
| F4 first_wrong | 37 | 13 | **-24** |
| F3 category_wrong | 54 | 52 | -2 |
| A✗ 合计 | 154 | 102 | -52 |
| B✓A✗ track_merges_multi_gold | 50 | 15 | **-35** |
| B✓A✗ one_to_one_conflict | 27 | 15 | **-12** |
| B✓A✗ 合计 | 80 | 35 | -45 |

## Sliding segment 几何统计（gold_events 流）

| | legacy | none |
|--|-------:|-----:|
| segment 数 | 281 | 601 |
| duration P50 (ms) | 9180 | 8537 |
| duration P90 (ms) | 113477 | 90322 |
| duration max (ms) | **977623** | **179316** |
| 覆盖 ≥2 gold 的 segment 数 | 62 | 120 |

说明：max 被压到 ≈window(180s)；但 raw 窗更多，几何层 multi-gold 计数上升（分子变多）。真正收益在后续出现了**短的单 gold track**，与长窗并存。

## 样例抽查（结论）

原 multi-gold / `shot_save` 冲突样例在 `none` 下普遍多出一条短 track（`n_golds=1`），例如：

- 乌迪内斯：legacy 仅 `dur=125s n_golds=2`；none 额外 `pass→successful_tackle dur≈5s n_golds=1`
- 奥维耶多 ann_0003：额外 `successful_tackle→goal_line_clearance dur≈11s n_golds=1`
- 曼城利物浦 shot_save：额外 `dur≈2.8s n_golds=1`

长合并窗仍常在（anchor 或未过滤的宽 sliding），但不再是唯一候选 → F7 / merge 下降、A 上升。

## 相对保留标准的判断

标准：A↑ 且 merge/F7↓，且 B、precision 无明显退化。

| 条件 | 结果 |
|------|------|
| A strict 上升 | ✓ +11.9pp |
| multi-gold / F7 明显下降 | ✓ |
| B 无明显退化 | ✓ 持平 |
| precision 无明显退化 | **✗ −12.8pp**（tracks 325→451，unmatched FP 42→116） |

**结论：不完全满足“直接保留为默认”的标准。**  
建议：`none` 作为可切换实验配置保留（`production_p2a_nomerge`），默认 `production` 仍为 `legacy`；下一步若要用 none，需配合更强 dedupe/NMS 压 FP，而不是先做 boundary/Qwen。

## 产物

- `algo/causal_chain2/segmentation_geom.py`（`merge_mode`）
- `algo/causal_chain6/config/production.json`（`sliding_merge_mode=legacy`）
- `algo/causal_chain6/config/production_p2a_nomerge.json`
- `reports/report_stream_strip_rule_gold_events_p2a_nomerge.json`
- `reports/diag_p1_failure_attribution_p2a_nomerge.json`
- `reports/diag_p2a_sliding_nomerge.json`
