# 已由两个正式入口替代

| 场景 | 请用 |
|------|------|
| 只有上游事件 | `eval/run_e2e_infer.py` |
| 有 causal 标注 | `eval/run_e2e_eval.py` |

数据目录与字段说明：**`eval/DATA_IO.md`**

本文件对应的 `run_linked_pipeline.py` 仍被 `run_e2e_eval` 内部调用（评测核心），一般不必单独跑。
