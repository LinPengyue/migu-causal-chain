# causal-chain2

咪咕视频因果链：**GNN 图级链模板分类** + **时间线集锦选段**（`timeline_highlights`）。

本仓库为**最小可运行子集**，仅包含以下两条命令所需的代码与数据：

## 环境

```bash
cd causal-chain2
pip install -r requirements.txt
```

需 Python 3.9+；GPU 推理/测试将 `--device cuda`。

## 1）GNN 评估（test）

```bash
python -m causal_chain2.test \
  --data eval/eval_a3.jsonl \
  --ckpt causal_chain2/_checkpoints/gnn.pt \
  --device cuda \
  --filter-tier strict,relaxed
```

## 2）时间线 → 集锦片段 + 可视化（timeline_highlights）

```bash
python -m causal_chain2.timeline_highlights \
  --timeline-json causal_chain/examples/external_task2_timeline.json \
  --ckpt causal_chain2/_checkpoints/gnn.pt \
  --device cuda \
  --out out/highlights.json \
  --min-margin 0.08 \
  --min-prob-top1 0.0 \
  --iou-dedupe 0.5 \
  --iou-recall 0.45 \
  --max-events 12 \
  --viz-dir out/highlights_viz
```

输出：

- `out/highlights.json`：最终 clips + 全量 proposals 与 GNN 概率
- `out/highlights_viz/`：时间轴与逐段概率 PNG（需 `--viz-dir`）

## 目录说明

| 路径 | 说明 |
|------|------|
| `causal_chain2/` | 核心 Python 包（test / timeline_highlights / model / graph） |
| `causal_chain2/_checkpoints/gnn.pt` | 预训练 LiteGCN 权重 |
| `eval/eval_a3.jsonl` | 评估集（800 条 A3 仿真链） |
| `causal_chain/examples/external_task2_timeline.json` | 示例拆条时间线 |

## 未纳入本仓库的内容

训练数据生成（Qwen LLM）、`train.py`、PPT 脚本等仍在完整工程 `mllms_know` 主仓；本仓仅保证上述 **test** 与 **timeline_highlights** 可独立运行。

## 推送到 GitHub（[LinPengyue](https://github.com/LinPengyue)）

本地仓库路径：`/data2/lpy1/causal-chain2`（已 `git init` 并完成首次 commit）。

1. 在 GitHub 新建空仓库（建议名 **`causal-chain2`**，不要勾选 README）。
2. 推送：

```bash
cd /data2/lpy1/causal-chain2
git remote set-url origin https://github.com/LinPengyue/causal-chain2.git
git push -u origin main
```

若使用 SSH：`git remote set-url origin git@github.com:LinPengyue/causal-chain2.git`

纳入文件清单见 `MANIFEST.txt`（共 19 个文件，约 1.2MB）。
