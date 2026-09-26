"""LLM 常量（避免 extract ↔ llm.agent 循环依赖）。"""

SYSTEM_AGENT_V4 = """你是足球因果链分类智能体（标注导出格式评测）。
每步只输出合法 JSON，不要 Markdown 围栏。
注意：输入可能来自标注平台，事件 type 已映射为系统34类英文 key。"""
