"""chain4 增强 prompt（含标注 metadata / 映射警告）。"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from causal_chain2.event_io import compact_event
from causal_chain2.prompts_classify import DECISION_TREE, build_category_table

from causal_chain6.io.eval_record import EvalRecord


from causal_chain6.llm.constants import SYSTEM_AGENT_V4


def _event_block(events: List[Dict[str, Any]], rec: EvalRecord) -> str:
    compact = [compact_event(e, order=i) for i, e in enumerate(events)]
    lines = [json.dumps(compact, ensure_ascii=False, indent=2)]
    lines.append("类型链: " + " → ".join(e["type"] for e in compact))
    if rec.mapping_warnings:
        lines.append("映射警告: " + "; ".join(rec.mapping_warnings))
    return "\n".join(lines)


def _meta_block(rec: EvalRecord) -> str:
    m = rec.meta
    parts = [
        f"match_id={rec.match_id}",
        f"annotation_id={rec.annotation_id}",
    ]
    for key in ("segment_time_sketch", "segment_time_video", "is_replay", "video_name"):
        if m.get(key):
            parts.append(f"{key}={m[key]}")
    return "\n".join(parts)


def prompt_classifier_v4(
    rec: EvalRecord,
    events: List[Dict[str, Any]],
    category: str,
    tool_context: str,
    fewshot_block: str = "",
) -> str:
    extra = f"\n{fewshot_block}\n" if fewshot_block else ""
    return f"""## 角色：Classifier（chain6）
在 chain_category={category} 内给出 top-3 chain_template_id。
必须参考 Tool 结果；以当前事件终局+规则为准，示范仅作形态参考。

## 场次/片段元数据
{_meta_block(rec)}

## 事件 JSON
{_event_block(events, rec)}

{tool_context}
{extra}
{DECISION_TREE}

## 输出
{{
  "candidates": [
    {{"chain_template_id":"id","confidence":0.0,"rationale":"一句话"}},
    ...
  ],
  "annotation_conflict": "none|possible|likely",
  "annotation_conflict_note": "若结构冲突，简要说明"
}}
candidates 恰好 3 个。只输出 JSON。"""


def prompt_planner_v4(rec: EvalRecord, events: List[Dict[str, Any]]) -> str:
    return f"""## 角色：Planner（chain4）
判断 chain_category（四选一）。

## 元数据
{_meta_block(rec)}

## 事件
{_event_block(events, rec)}

## 可选大类
{build_category_table()}

{DECISION_TREE}

## 输出
{{"chain_category":"outcome|correction|danger|special","confidence":0.0,"rationale":"一句话"}}
只输出 JSON。"""


def prompt_vlm_supplement(rec: EvalRecord, rule_top3: List[str]) -> str:
    return f"""## 角色：VLM 补充分析
结合视频片段与下方事件 JSON，判断最可能的因果链模版。

## 元数据
{_meta_block(rec)}

## 规则 top 候选
{", ".join(rule_top3)}

## 事件
{_event_block(rec.events_extracted or rec.events_normalized, rec)}

## 输出
{{
  "suggested_template_id": "id",
  "confidence": 0.0,
  "visible_outcome": "一句话描述画面结果",
  "conflict_with_annotation": true,
  "note": "与标注模版的差异说明"
}}
只输出 JSON。"""
