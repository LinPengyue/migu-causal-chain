# causal_chain8 常用命令

`PDF 选片 (层 A)` → `因果链分类/抽取 (层 B)`。

- 选片唯一决定谁进集锦；因果链分数不反向改选片
- 短窗：T0 前 12s/后 4s；T1 前 8s/后 5s；T2 前 6s/后 4s

在包根目录 `8.31causal_chain/` 下执行：

```bash
cd 8.31causal_chain
export PYTHONPATH=$PWD/algo:$PWD/eval

# 只跑选片（无 GPU）
python -m causal_chain8.build_highlights \
  --timeline-json datasets/matches/<match>/timeline.json \
  --out reports/select_only.json \
  --select-only

# 选片 + 规则分类建链
python -m causal_chain8.build_highlights \
  --timeline-json datasets/matches/<match>/timeline.json \
  --out reports/highlight_rule.json \
  --rule-only \
  --no-llm-narrative

# 选片 + Qwen（权重路径自备）
CUDA_VISIBLE_DEVICES=0 python -m causal_chain8.build_highlights \
  --timeline-json datasets/matches/<match>/timeline.json \
  --model-path ./models/Qwen2.5-VL \
  --device cuda \
  --profile production \
  --out reports/highlight_llm.json \
  --no-llm-narrative
```
