"""方案 C 智能体各步 prompt。"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from causal_chain2.event_io import compact_event
from causal_chain2.prompts_classify import (
    DECISION_TREE,
    FEW_SHOT_SHOT_GOAL,
    FEW_SHOT_VAR,
    build_category_table,
)

SYSTEM_AGENT = """你是足球因果链分类智能体。每步只输出合法 JSON，不要 Markdown 围栏。"""


def _compact_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [compact_event(e, order=i) for i, e in enumerate(events)]


def _types_chain(events: List[Dict[str, Any]]) -> str:
    return " → ".join(e["type"] for e in _compact_events(events))


def prompt_planner(events: List[Dict[str, Any]]) -> str:
    ej = json.dumps(_compact_events(events), ensure_ascii=False, indent=2)
    return f"""## 角色：Planner
判断事件链所属 **chain_category**（四选一）。

## 事件 JSON
{ej}

## 类型链
{_types_chain(events)}

## 可选大类
{build_category_table()}

{DECISION_TREE}

## 输出
{{"chain_category":"outcome|correction|danger|special","confidence":0.0,"rationale":"一句话"}}
只输出 JSON。"""


def prompt_classifier_top3(
    events: List[Dict[str, Any]],
    category: str,
    tool_context: str,
) -> str:
    ej = json.dumps(_compact_events(events), ensure_ascii=False, indent=2)
    extra = FEW_SHOT_VAR if category == "correction" else ""
    if category == "outcome":
        extra += FEW_SHOT_SHOT_GOAL
    return f"""## 角色：Classifier
在 chain_category={category} 内给出 **top-3** chain_template_id 及置信度。
必须参考下方 Tool 检索结果（尤其转移合法候选与 CANONICAL 匹配）。

## 事件 JSON
{ej}

## 类型链
{_types_chain(events)}

{tool_context}

{DECISION_TREE}
{extra}

## 输出
{{
  "candidates": [
    {{"chain_template_id":"id","confidence":0.0,"rationale":"一句话"}},
    ...
  ]
}}
candidates 恰好 3 个，按 confidence 降序，id 必须属于大类 {category}。只输出 JSON。"""


def prompt_critic(
    events: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
    tool_checks: List[Dict[str, Any]],
) -> str:
    ej = json.dumps(_compact_events(events), ensure_ascii=False, indent=2)
    cand_j = json.dumps(candidates, ensure_ascii=False, indent=2)
    chk_j = json.dumps(tool_checks, ensure_ascii=False, indent=2)
    return f"""## 角色：Critic
审查 Classifier 的 top-3：结合 Tool 转移校验，给出修订排序。

## 事件 JSON
{ej}

## Classifier top-3
{cand_j}

## Tool 转移/CANONICAL 校验
{chk_j}

规则：
- transitions_ok=false 的候选应大幅降权，除非无合法候选；
- exact_canonical_match=true 应优先；
- VAR 三类、shot→goal 边界按 few-shot 区分。

## 输出
{{
  "ranked": [
    {{"chain_template_id":"id","confidence":0.0,"accept":true,"rationale":"一句话"}},
    ...
  ]
}}
ranked 最多 3 个，accept 表示是否推荐为最终答案。只输出 JSON。"""


def prompt_final(
    events: List[Dict[str, Any]],
    ranked: List[Dict[str, Any]],
) -> str:
    ej = json.dumps(_compact_events(events), ensure_ascii=False, indent=2)
    rk = json.dumps(ranked, ensure_ascii=False, indent=2)
    return f"""## 角色：Final
从 Critic 排序中选出唯一最终 chain_template_id。

## 事件 JSON
{ej}

## Critic ranked
{rk}

## 输出
{{
  "chain_template_id":"最终 id",
  "confidence":0.0,
  "rationale":"综合理由",
  "alternatives":[{{"chain_template_id":"次选","confidence":0.0}}]
}}
alternatives 最多 2 个。只输出 JSON。"""
