# causal_chain4 常用命令

在仓库根目录 `causal-chain2/` 下执行（需 `export PYTHONPATH=.`）。

## 1）拆条（时间线 → 集锦片段）

对齐 `causal_chain2.timeline_highlights`：

```bash
cd /data2/lpy1/causal-chain2
export PYTHONPATH=.

CUDA_VISIBLE_DEVICES=0 python -m causal_chain4.strip \
  --timeline-json causal_chain/examples/external_task2_timeline.json \
  --model-path /data2/lpy1/Qwen2.5-VL \
  --device cuda \
  --profile production \
  --out out/chain4_highlights.json \
  --min-margin 0.08 \
  --max-events 12 \
  --viz-dir out/chain4_viz
```

输出：`out/chain4_highlights.json`，可视化目录 `out/chain4_viz/`。

## 2）因果链分类（标注导出 causal JSON）

默认后端为业务骨架 `chain4_agent`（`oct10_causal2` profile）：

```bash
cd /data2/lpy1/causal-chain2
export PYTHONPATH=.

CUDA_VISIBLE_DEVICES=0 python -m causal_chain4.classify \
  --data causal_chain/examples/10月10日_2025世预赛欧洲区_哈萨克斯坦VS列支敦士登_英语_causal\(2\).json \
  --profile oct10_causal2 \
  --model-path /data2/lpy1/Qwen2.5-VL \
  --device cuda \
  --out-predictions eval/oct10_kz_preds.jsonl
```

输出：`eval/oct10_kz_preds.jsonl`。

---

无 GPU 时将 `--device cuda` 改为 `--device cpu`（分类可不加 `--model-path`，仅跑规则骨架）。
