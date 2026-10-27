# 导出每场拆条因果链（新增，不改原评测）

三种模式，算法都是 **causal_chain6**：

| `--mode` | 口径 | 对齐评测 | 默认输出目录 |
|----------|------|----------|--------------|
| `gold_clips`（默认） | 已切 clip → strip | 离线 **82.15%** | `reports/strip_dump` |
| `online` | 事件流 → OnlineStripEngine | 在线 **71.62%** | `reports/strip_dump_online` |
| `timeline` | 整场自切 | 不对齐正式数字 | `reports/strip_dump_timeline` |

## 上传

- `eval/dump_strip_chains.py`（必传）

## 用法

```bash
cd 8.31causal_chain
export PYTHONPATH="$PWD/algo:$PWD/eval"

# 离线（默认）
python eval/dump_strip_chains.py

# 在线（与 eval_online_strip 同源）
python eval/dump_strip_chains.py --mode online

# 试跑
python eval/dump_strip_chains.py --mode online --limit-matches 2
```

`_manifest.json` 里的 `logic_complete_rate`：
- `gold_clips` ≈ 82.15%
- `online` ≈ 71.62%
