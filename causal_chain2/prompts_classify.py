"""大模型因果链分类提示词：典型骨架 + 决策树 + few-shot + 两阶段。"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from causal_chain2.event_io import compact_event
from causal_chain2.chain_rules import CANONICAL_SEQUENCES
from causal_chain2.chain_schema import ALL_TEMPLATE_IDS, CHAIN_TEMPLATES, EVENT_TYPES

CATEGORIES = ("outcome", "correction", "danger", "special")

SYSTEM_PROMPT_CLASSIFY = """你是足球比赛因果链分类助手。
根据事件序列（按时间排序）做分类；只输出合法 JSON，不要 Markdown 围栏，不要额外解释。"""

DECISION_TREE = """## 短决策树（按顺序执行）
1. **看结局（最后 1～2 个关键事件）**
   - 以 `disallowed_goal` 收束 → 优先 **correction**（再分 VAR 子类）
   - 含 `red_card` / `second_yellow_red` 收束 → **outcome** 下 `red_card_decision_chain`
   - 以 `goal` 收束且之后无改判 → **outcome** 进球类
   - 以 `keeper_save` 收束、且无有效 `goal` → **danger** 下 `shot_save_chain`
   - 以 `goal_line_clearance` 收束 → **danger** 下 `goal_line_extreme_save_chain`
   - 无进球、有持续威胁（门柱/二攻/脱手）→ **danger** 或 **special**
2. **看关键节点**
   - 有 `penalty`：若最终 `goal` → outcome/`penalty_scored_chain`；若 `var` 后改 `free_kick` → correction/`var_penalty_cancelled_chain`
   - 有 `var`：结合结局区分 `goal_disallowed_chain` / `var_overturn_chain` / `var_penalty_cancelled_chain`
   - 有 `corner`+`cross` 且进球 → outcome/`corner_cross_goal`
   - 有 `goal_line_clearance` → danger/`goal_line_extreme_save_chain`
3. **在已定大类内选最贴近典型骨架的 template_id**（见下方 CANONICAL）。"""

FEW_SHOT_VAR = """
## few-shot：VAR 三类边界
| 事件序列（type） | chain_template_id | 理由 |
|---|---|---|
| goal → var → disallowed_goal | goal_disallowed_chain | 已进球后被 VAR 判无效 |
| shot → goal → var → disallowed_goal | goal_disallowed_chain | 进球庆祝后改判无效 |
| foul → var → offside | var_overturn_chain | VAR 改判越位等，非进球无效 |
| goal → var → disallowed_goal（无前置进球庆祝语义时若仅有 var 改判） | var_overturn_chain | 改判关键事件但不强调「进球无效链」叙事时用 overturn |
| penalty → var → free_kick | var_penalty_cancelled_chain | VAR 取消点球改任意球 |
| foul → var → penalty → var → free_kick | var_penalty_cancelled_chain | 点球复核后取消 |
"""

FEW_SHOT_SHOT_GOAL = """
## few-shot：(shot,goal) 与相近进球链
| 事件序列（type） | chain_template_id | 理由 |
|---|---|---|
| shot → goal（仅 2 事件、无铺垫） | deflection_goal_chain | 数据集约定：极简射门进球视为折射/变线 |
| pass → shot → goal | outcome_other | 常规推进进球 |
| dribble_breakthrough → shot → goal | outcome_other | 个人突破后进球 |
| shot → keeper_save → shot → goal | rebound_follow_up_goal | 补射进球 |
| successful_tackle → pass → shot → goal | turnover_counter_goal | 抢断反击进球 |
| cross → header_shot → goal | own_goal_causal_chain | 传中/header 压力导致乌龙类进球 |
| possession_lost → shot → goal | own_goal_causal_chain | 失误压力下的进球 |
"""


def build_canonical_table() -> str:
    lines = []
    for tid in ALL_TEMPLATE_IDS:
        seqs = CANONICAL_SEQUENCES.get(tid, [])
        seq_str = " | ".join("→".join(s) for s in seqs[:2])
        if len(seqs) > 2:
            seq_str += f" | …共{len(seqs)}条"
        lines.append(f"- `{tid}`: {seq_str}")
    return "\n".join(lines)


def build_template_table(category: str | None = None) -> str:
    lines = []
    for tid in ALL_TEMPLATE_IDS:
        meta = CHAIN_TEMPLATES[tid]
        if category is not None and meta["category"] != category:
            continue
        lines.append(
            f"- `{tid}` ({meta['category']}): {meta['label_zh']} — {meta['description']}"
        )
    return "\n".join(lines)


def build_category_table() -> str:
    lines = [
        "- `outcome`: 进球/红牌等结果性叙事",
        "- `correction`: VAR/改判/进球无效/点球取消",
        "- `danger`: 威胁但未进球（扑救、门柱、门线、二攻）",
        "- `special`: 界外球推进、乌龙致因、脱手、快发定位球、折射进球等",
    ]
    return "\n".join(lines)


def _compact_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [compact_event(e, order=i) for i, e in enumerate(events)]


def user_prompt_category(events: List[Dict[str, Any]]) -> str:
    events_json = json.dumps(_compact_events(events), ensure_ascii=False, indent=2)
    types_str = " → ".join(e["type"] for e in _compact_events(events))
    return f"""**阶段 1/2：链大类 chain_category 分类**

## 事件序列（JSON）
{events_json}

## 事件类型链（便于阅读）
{types_str}

## 可选 chain_category（四选一）
{build_category_table()}

{DECISION_TREE}

## 输出 JSON
{{
  "chain_category": "outcome|correction|danger|special",
  "confidence": 0.0到1.0,
  "rationale": "一句话中文理由"
}}
只输出 JSON。"""


def user_prompt_template(
    events: List[Dict[str, Any]],
    category: str,
) -> str:
    events_json = json.dumps(_compact_events(events), ensure_ascii=False, indent=2)
    types_str = " → ".join(e["type"] for e in _compact_events(events))
    extra = ""
    if category == "correction":
        extra = FEW_SHOT_VAR
    elif category == "outcome":
        extra = FEW_SHOT_SHOT_GOAL

    return f"""**阶段 2/2：在 chain_category={category} 内选 chain_template_id**

## 事件序列（JSON）
{events_json}

## 事件类型链
{types_str}

## 典型骨架 CANONICAL（优先匹配最接近的一条）
{build_canonical_table()}

## 本大类内可选 chain_template_id（必须从中选一）
{build_template_table(category)}

{DECISION_TREE}
{extra}

## 输出 JSON
{{
  "chain_template_id": "上述英文 id 之一",
  "confidence": 0.0到1.0,
  "rationale": "一句话中文理由",
  "alternatives": [
    {{"chain_template_id": "次选 id", "confidence": 0.0到1.0}}
  ]
}}
alternatives 最多 2 条。只输出 JSON。"""


def templates_in_category(category: str) -> List[str]:
    return [
        tid
        for tid in ALL_TEMPLATE_IDS
        if CHAIN_TEMPLATES[tid]["category"] == category
    ]


def user_prompt_classify_single_stage(events: List[Dict[str, Any]]) -> str:
    """单阶段 18 类（兼容旧路径）。"""
    events_json = json.dumps(_compact_events(events), ensure_ascii=False, indent=2)
    types_str = " → ".join(e["type"] for e in _compact_events(events))
    return f"""请对下列足球事件序列做**因果链模板分类**（18 类闭集）。

## 事件序列（JSON）
{events_json}

## 事件类型链
{types_str}

## 典型骨架 CANONICAL
{build_canonical_table()}

## 可选 chain_template_id
{build_template_table()}

{DECISION_TREE}
{FEW_SHOT_VAR}
{FEW_SHOT_SHOT_GOAL}

## 输出 JSON
{{
  "chain_template_id": "上述英文 id 之一",
  "confidence": 0.0到1.0,
  "rationale": "一句话中文理由",
  "alternatives": [{{"chain_template_id": "次选", "confidence": 0.0}}]
}}
只输出 JSON。"""
