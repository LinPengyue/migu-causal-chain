# 导出每场完整集锦（新增文件，不改原评测）

上传到服务器时只需同步：

- `eval/dump_highlight_reels.py`
- `scripts/dump_highlight_reels.sh`（可选）

## 用法

在 `8.31causal_chain` 根目录：

```bash
export PYTHONPATH="$PWD/algo:$PWD/eval"

# 全量（rule-only，与 offline highlight 同源流水线）
python eval/dump_highlight_reels.py

# 或
bash scripts/dump_highlight_reels.sh

# 前 2 场试跑
python eval/dump_highlight_reels.py --limit-matches 2

# 指定输出目录
python eval/dump_highlight_reels.py --out-dir reports/reels_dump

# 可选 Qwen
python eval/dump_highlight_reels.py --use-llm --model-path /path/to/Qwen2.5-VL
```

## 输出

| 路径 | 内容 |
|------|------|
| `reports/reels_dump/<safe_id>.json` | 该场完整集锦（`reel.clips[]`：时间窗、类别、事件、模板等） |
| `reports/reels_dump/_manifest.json` | 场次清单与 clips 数 |

默认按 `highlight_gold_no_t2` 自动 `drop_t2`；若要保留 T2：`--keep-t2`。
