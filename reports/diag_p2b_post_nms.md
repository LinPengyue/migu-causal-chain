# P2-B：none + post-score NMS

## 快速诊断（none 下 116 unmatched）

| 类型 | n |
|------|--:|
| boundary_shift (P3) | 53 |
| wrong_category (P4) | 40 |
| merged_multi_gold (P2) | 22 |
| duplicate_like (P1) | 1 |
| genuine_spurious (P5) | 0 |

重叠/边界类为主 → 做 post-score NMS；错类 40 条 NMS 帮不上。

## 主指标（rule-only + gold_events + one-to-one）

| metric | legacy | none | none+nms (v2) |
|--------|-------:|-----:|--------------:|
| A strict | 64.76% | **76.66%** | **73.23%** |
| precision | 87.08% | 74.28% | **77.48%** |
| tracks | 325 | 451 | 413 |
| B | 81.46% | 81.46% | 81.46% |

v1 过杀（A 49.89% / prec 58.92%）已弃用；当前默认 NMS = 同 template + IoU≥0.65，分数接近优先更紧窗。

## P1 关键项

| 项 | legacy | none | none+nms v2 |
|----|-------:|-----:|------------:|
| F7 | 42 | 25 | 24 |
| F4 | 37 | 13 | 16 |
| B✓A✗ track_merges_multi_gold | 50 | 15 | 17 |
| unmatched tracks | 42 | 116 | 93 |

### unmatched 类型

- none: {'P3_boundary_shift': 53, 'P4_wrong_category': 40, 'P2_merged_multi_gold': 22, 'P1_duplicate_like': 1}
- none+nms: {'P4_wrong_category': 43, 'P3_boundary_shift': 26, 'P2_merged_multi_gold': 23, 'P1_duplicate_like': 1}

## 判断

相对 none：A −3.43pp，precision +3.20pp，tracks −38。
**未达到「基本保住 76.66% 且 precision 明显拉回」**：precision 回升有限，且仍远低于 legacy 87%。
错类 FP 仍是大头。建议 none 继续作为召回配置；NMS 可保留为 `sliding_post_nms=on` 可选项，但不够作为单独银弹。

配置：`production_p2b_nomerge_nms.json`（none + on）。
