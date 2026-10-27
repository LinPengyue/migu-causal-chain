# 评测对齐说明（Qwen）

## 拆条
- 内核：`causal_chain6.llm.agent.classify_record_v4`（与 `python -m causal_chain6.classify` 同路径）
- 启用 Qwen：`--use-llm --model-path ./models/Qwen2.5-VL`

## 集锦
- 入口：`causal_chain8.build_highlights.run_build_highlights`
- 对齐：`python -m causal_chain8.build_highlights ... --no-llm-narrative`
- 启用 Qwen；叙事可关

## 运行

在包根目录：

```bash
cd 8.31causal_chain
export PYTHONPATH=$PWD/algo:$PWD/eval
CUDA_VISIBLE_DEVICES=0 python -u eval/run_eval.py \
  --model-path ./models/Qwen2.5-VL --device cuda --use-llm
```

日志：`reports/run_llm_full.log`  
中途结果：`reports/report_llm_partial.json`  
完成后：`reports/report_llm.json` / `table_row_causal_chain.json`
