# P2-C category rule（未保留）

基线：`sliding_merge_mode=none`, `post_nms=off`

| metric | baseline | P2-C | Δ |
|--------|---------:|-----:|--:|
| A strict | **76.66%** | 76.20% | −0.46 |
| precision | 74.28% | 73.84% | −0.44 |
| B | 81.46% | 81.24% | −0.22 |
| offline | 90.62% | 92.68% | +2.06 |
| tracks | 451 | 451 | 0 |

| confusion | before | after |
|-----------|-------:|------:|
| special→danger | 12 | 13 |
| outcome→danger | 10 | 8 |
| outcome→special | 8 | 8 |
| correction→outcome | 7 | 6 |

**结论：A 未提升 → 不保留；已回滚 `rules/robust.py`。** 基线仍为 none / post_nms=off（A=76.66%）。
