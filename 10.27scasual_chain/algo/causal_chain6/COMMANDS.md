# causal_chain6 常用命令

`causal_chain6` = 拆条因果链（规则 + 可选 Qwen）。

在包根目录 `8.31causal_chain/` 下执行：

```bash
cd 8.31causal_chain
export PYTHONPATH=$PWD/algo:$PWD/eval

# 分类（rule-only）
python -m causal_chain6.classify \
  --data datasets/... \
  --profile production \
  --out-predictions reports/preds.jsonl

# 启用 Qwen（权重路径自备，可用相对路径）
CUDA_VISIBLE_DEVICES=0 python -m causal_chain6.classify \
  --data datasets/... \
  --profile production \
  --model-path ./models/Qwen2.5-VL \
  --device cuda \
  --out-predictions reports/preds_llm.jsonl
```

无 GPU / 不传 `--model-path` 时仅跑规则路径。
