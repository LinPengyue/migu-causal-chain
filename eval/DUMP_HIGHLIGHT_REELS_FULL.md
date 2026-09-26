# 交付用完整集锦导出（新增，不改原 reels_dump）

## 为什么要这个

原 `dump_highlight_reels.py` → `reports/reels_dump` 为对齐 **评测 no_t2**，会丢掉规则四补上的 T2，很多场只剩 0/1 条，观感上不像集锦。

本脚本面向 **交付/展示**：先跑完整 PDF 选片（保留 T2），再按 `min_clips` 保底补片。

## 上传服务器只需

- `eval/dump_highlight_reels_full.py`
- 本说明（可选）

## 用法

```bash
cd 8.31causal_chain
export PYTHONPATH="$PWD/algo:$PWD/eval"

# 默认保底 4 条，输出 reports/reels_dump_full/
python eval/dump_highlight_reels_full.py

# 更接近 PDF「约 6 段」
python eval/dump_highlight_reels_full.py --min-clips 6

# 试跑
python eval/dump_highlight_reels_full.py --limit-matches 3 --min-clips 4
```

## 输出

| 路径 | 说明 |
|------|------|
| `reports/reels_dump_full/<safe_id>.json` | 完整 reel |
| `reports/reels_dump_full/_manifest.json` | 含 `n_clips_raw`→`n_clips`、`presentation_fill`、`under_min_clips` |

原 `reports/reels_dump/` **不改不动**（仍给 no_t2 评测对照）。
