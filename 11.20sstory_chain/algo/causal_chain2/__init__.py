"""causal_chain2：Qwen+A3 仿真 → JSON/张量 → GNN 训练（链模板分类 + 边辅助）。

入口脚本（均在包根目录执行 ``python -m causal_chain2.<mod>``）：

- ``generate``：A3 / 1.0-min jsonl；``--mode llm`` 使用 Qwen2.5-VL。
- ``convert_a3_jsonl`` / ``convert_min_jsonl`` / ``min_to_a3_jsonl``：转为 ``.pt`` 或 A3。
- ``focal_loss`` / ``analyze_confusion``：focal 训练与混淆分析。
- ``timeline_highlights``：时间线集锦选段（锚点 + GNN + margin）。
- ``run_pipeline``：一键生成 → 训练 → 测试；``--export-pt`` 导出张量包。

详见同目录 ``README.md``。
"""

__version__ = "0.2.0"
