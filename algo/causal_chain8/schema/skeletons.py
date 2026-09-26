"""
causal_chain8 业务侧因果链骨架（与 causal_chain2.chain_rules 独立）。

设计目标：贴近标注导出（causal(2)）与业务文档：
- 允许组织进攻前缀（控球→pass、防守动作→successful_tackle）
- 「其他」细分为个人突破 / 团队配合 / 角球配合
- 明确每类建议长度区间（min_len / max_len）
"""

from __future__ import annotations

from typing import Any, Dict, List, TypedDict


class SkeletonDef(TypedDict):
    category: str
    label_zh: str
    description: str
    min_len: int
    max_len: int
    # 典型完整路径（英文 type，已映射后）
    sequences: List[List[str]]
    # 允许出现在链中的事件（白名单）；空=不额外限制
    event_whitelist: List[str]
    # 允许的结局事件（至少命中其一）
    terminal_events: List[str]
    # 关键节点（命中则加分）；可为空
    key_events: List[str]


# ---------------------------------------------------------------------------
# 组织进攻常用前缀事件（映射后）
# ---------------------------------------------------------------------------
BUILDUP = ["pass", "dribble_past", "successful_tackle", "assist", "aerial_won", "cross"]
BUILDUP_SHORT = ["pass", "dribble_past", "successful_tackle"]


def _with_prefixes(cores: List[List[str]], prefixes: List[List[str]]) -> List[List[str]]:
    """核心骨架 + 若干前缀变体，去重。"""
    out: List[List[str]] = []
    seen = set()
    for core in cores:
        cands = [core] + [p + core for p in prefixes]
        for seq in cands:
            key = tuple(seq)
            if key not in seen:
                seen.add(key)
                out.append(seq)
    return out


_PASS_PREFIXES = [
    [],
    ["pass"],
    ["pass", "pass"],
    ["pass", "pass", "pass"],
    ["dribble_past"],
    ["pass", "dribble_past"],
    ["dribble_past", "pass"],
    ["successful_tackle"],
    ["successful_tackle", "pass"],
    ["successful_tackle", "dribble_past"],
    ["successful_tackle", "pass", "dribble_past"],
    ["pass", "successful_tackle"],
    ["cross"],
    ["pass", "cross"],
]


CHAIN4_SKELETONS: Dict[str, SkeletonDef] = {
    # ========== 结果链 ==========
    "individual_breakthrough_goal": {
        "category": "outcome",
        "label_zh": "个人突破后射门进球链",
        "description": "以过人为关键的个人突破后射门进球（业务「其他」子类一）",
        "min_len": 3,
        "max_len": 8,
        "sequences": _with_prefixes(
            [
                ["dribble_past", "shot", "goal"],
                ["dribble_past", "assist", "shot", "goal"],
                ["pass", "dribble_past", "shot", "goal"],
                ["pass", "dribble_past", "assist", "shot", "goal"],
                ["dribble_past", "pass", "shot", "goal"],
                ["successful_tackle", "dribble_past", "shot", "goal"],
                ["successful_tackle", "pass", "dribble_past", "shot", "goal"],
            ],
            [["pass"], ["pass", "pass"], []],
        ),
        "event_whitelist": BUILDUP + ["shot", "goal", "header_shot", "header_goal"],
        "terminal_events": ["goal", "header_goal"],
        "key_events": ["dribble_past"],
    },
    "team_buildup_goal": {
        "category": "outcome",
        "label_zh": "团队配合射门进球链",
        "description": "多人传球/争顶组织后射门进球（业务「其他」子类二）",
        "min_len": 3,
        "max_len": 10,
        "sequences": [
            ["pass", "shot", "goal"],
            ["pass", "pass", "shot", "goal"],
            ["pass", "pass", "pass", "shot", "goal"],
            ["pass", "pass", "pass", "pass", "shot", "goal"],
            ["pass", "dribble_past", "pass", "shot", "goal"],
            ["pass", "pass", "dribble_past", "shot", "goal"],
            ["pass", "pass", "pass", "pass", "dribble_past", "shot", "goal"],
            ["pass", "aerial_won", "shot", "goal"],
            ["pass", "dribble_past", "pass", "aerial_won", "shot", "goal"],
            ["pass", "dribble_past", "aerial_won", "shot", "goal"],
            ["successful_tackle", "pass", "shot", "goal"],
            ["successful_tackle", "pass", "pass", "shot", "goal"],
            ["successful_tackle", "pass", "aerial_won", "shot", "goal"],
            ["successful_tackle", "dribble_past", "pass", "aerial_won", "shot", "goal"],
            ["pass", "assist", "shot", "goal"],
            ["dribble_past", "pass", "shot", "goal"],
        ],
        "event_whitelist": BUILDUP + ["shot", "goal", "header_shot", "header_goal"],
        "terminal_events": ["goal", "header_goal"],
        "key_events": ["pass", "aerial_won"],
    },
    "corner_coop_goal": {
        "category": "outcome",
        "label_zh": "角球配合进球链",
        "description": "角球发动的配合进球，可不含传中（业务「其他」子类三）",
        "min_len": 3,
        "max_len": 9,
        "sequences": [
            ["corner", "shot", "goal"],
            ["corner", "pass", "shot", "goal"],
            ["corner", "successful_tackle", "pass", "shot", "goal"],
            ["corner", "successful_tackle", "dribble_past", "pass", "shot", "goal"],
            ["corner", "successful_tackle", "pass", "dribble_past", "shot", "goal"],
            ["corner", "dribble_past", "pass", "shot", "goal"],
            ["corner", "aerial_won", "shot", "goal"],
            ["corner", "pass", "aerial_won", "shot", "goal"],
            ["corner", "successful_tackle", "shot", "goal"],
            ["corner", "cross", "shot", "goal"],
            ["corner", "cross", "header_shot", "goal"],
            ["corner", "cross", "header_goal"],
            ["corner", "pass", "cross", "shot", "goal"],
        ],
        "event_whitelist": ["corner"] + BUILDUP + ["shot", "goal", "header_shot", "header_goal"],
        "terminal_events": ["goal", "header_goal"],
        "key_events": ["corner"],
    },
    "corner_cross_goal": {
        "category": "outcome",
        "label_zh": "角球传中进球链",
        "description": "角球→传中→头球/射门→进球（强调传中）",
        "min_len": 3,
        "max_len": 8,
        "sequences": [
            ["corner", "cross", "header_goal"],
            ["corner", "cross", "header_shot", "goal"],
            ["corner", "cross", "shot", "goal"],
            ["corner", "pass", "cross", "shot", "goal"],
            ["corner", "pass", "cross", "header_shot", "goal"],
            ["corner", "successful_tackle", "cross", "shot", "goal"],
            ["corner", "successful_tackle", "shot", "goal"],
            ["throw_in", "corner", "cross", "header_shot", "goal"],
        ],
        "event_whitelist": ["corner", "throw_in", "cross"] + BUILDUP + ["shot", "goal", "header_shot", "header_goal"],
        "terminal_events": ["goal", "header_goal"],
        "key_events": ["corner", "cross"],
    },
    "rebound_follow_up_goal": {
        "category": "outcome",
        "label_zh": "射门被挡后补射进球链",
        "description": "扑救/挡出后补射进球",
        "min_len": 3,
        "max_len": 8,
        "sequences": [
            ["shot", "keeper_save", "shot", "goal"],
            ["pass", "shot", "keeper_save", "shot", "goal"],
            ["cross", "shot", "keeper_save", "shot", "goal"],
            ["shot", "shot", "goal"],
            ["pass", "shot", "shot", "goal"],
        ],
        "event_whitelist": BUILDUP + ["shot", "keeper_save", "goal", "header_shot"],
        "terminal_events": ["goal"],
        "key_events": ["keeper_save", "shot"],
    },
    "turnover_counter_goal": {
        "category": "outcome",
        "label_zh": "抢断/反击/失误造成进球链",
        "description": "抢断/拦截/丢球后由守转攻进球",
        "min_len": 3,
        "max_len": 9,
        "sequences": [
            ["successful_tackle", "pass", "shot", "goal"],
            ["successful_tackle", "pass", "dribble_past", "shot", "goal"],
            ["successful_tackle", "dribble_past", "shot", "goal"],
            ["successful_tackle", "shot", "goal"],
            ["interception", "pass", "cross", "goal"],
            ["interception", "pass", "shot", "goal"],
            ["interception", "pass", "dribble_past", "assist", "shot", "goal"],
            ["interception", "pass", "dribble_past", "shot", "goal"],
            ["shot", "goal_line_clearance", "interception", "pass", "assist", "shot", "goal"],
            ["possession_lost", "successful_tackle", "shot", "goal"],
            ["successful_tackle", "pass", "cross", "shot", "goal"],
            ["successful_tackle", "pass", "dribble_past", "assist", "shot", "goal"],
        ],
        "event_whitelist": BUILDUP + ["interception", "possession_lost", "shot", "goal", "header_shot", "dribble_breakthrough", "goal_line_clearance"],
        "terminal_events": ["goal", "header_goal"],
        "key_events": ["successful_tackle", "interception", "possession_lost"],
    },
    "penalty_scored_chain": {
        "category": "outcome",
        "label_zh": "点球命中链",
        "description": "点球判罚后命中",
        "min_len": 2,
        "max_len": 6,
        "sequences": [
            ["penalty", "goal"],
            ["foul", "penalty", "goal"],
            ["foul", "var", "penalty", "goal"],
            ["var", "penalty", "goal"],
        ],
        "event_whitelist": ["foul", "var", "penalty", "goal", "controversy"],
        "terminal_events": ["goal"],
        "key_events": ["penalty"],
    },
    "red_card_decision_chain": {
        "category": "outcome",
        "label_zh": "红牌判罚链",
        "description": "犯规/争议后直红或两黄变一红",
        "min_len": 2,
        "max_len": 6,
        "sequences": [
            ["foul", "red_card"],
            ["foul", "controversy", "var", "red_card"],
            ["foul", "yellow_card", "foul", "second_yellow_red"],
            ["foul", "var", "red_card"],
        ],
        "event_whitelist": ["foul", "controversy", "var", "red_card", "yellow_card", "second_yellow_red"],
        "terminal_events": ["red_card", "second_yellow_red"],
        "key_events": ["red_card", "second_yellow_red"],
    },
    "outcome_other": {
        "category": "outcome",
        "label_zh": "其他",
        "description": "无法归入个人突破/团队配合/角球配合/反击等时的兜底进球链",
        "min_len": 2,
        "max_len": 10,
        "sequences": [
            ["shot", "goal"],
            ["pass", "shot", "goal"],
            ["dribble_past", "shot", "goal"],
            ["pass", "pass", "shot", "goal"],
            ["assist", "shot", "goal"],
        ],
        "event_whitelist": BUILDUP + ["shot", "goal", "header_shot", "header_goal"],
        "terminal_events": ["goal", "header_goal"],
        "key_events": ["goal"],
    },
    # ========== 改判链 ==========
    "goal_disallowed_chain": {
        "category": "correction",
        "label_zh": "进球无效链",
        "description": "进球后经 VAR/裁判改判无效",
        "min_len": 2,
        "max_len": 7,
        "sequences": [
            ["goal", "var", "disallowed_goal"],
            ["shot", "goal", "var", "disallowed_goal"],
            ["goal", "controversy", "var", "disallowed_goal"],
            ["pass", "shot", "goal", "var", "disallowed_goal"],
        ],
        "event_whitelist": BUILDUP + ["shot", "goal", "controversy", "var", "disallowed_goal"],
        "terminal_events": ["disallowed_goal"],
        "key_events": ["var", "disallowed_goal"],
    },
    "var_penalty_cancelled_chain": {
        "category": "correction",
        "label_zh": "VAR 取消点球链",
        "description": "VAR 介入后取消点球",
        "min_len": 2,
        "max_len": 7,
        "sequences": [
            ["penalty", "var", "free_kick"],
            ["foul", "var", "penalty", "var", "free_kick"],
            ["foul", "penalty", "var", "free_kick"],
        ],
        "event_whitelist": ["foul", "var", "penalty", "free_kick", "controversy"],
        "terminal_events": ["free_kick"],
        "key_events": ["var", "penalty"],
    },
    "var_overturn_chain": {
        "category": "correction",
        "label_zh": "VAR 改判链",
        "description": "VAR 改判关键事件（非典型进球无效/取消点球）",
        "min_len": 2,
        "max_len": 6,
        "sequences": [
            ["goal", "var", "disallowed_goal"],
            ["foul", "var", "offside"],
            ["foul", "var", "foul"],
            ["shot", "goal", "var", "offside"],
        ],
        "event_whitelist": ["foul", "var", "goal", "disallowed_goal", "offside", "controversy", "shot"],
        "terminal_events": ["disallowed_goal", "offside", "foul", "free_kick"],
        "key_events": ["var"],
    },
    # ========== 险情链 ==========
    "shot_save_chain": {
        "category": "danger",
        "label_zh": "射门扑救链",
        "description": "威胁射门被门将化解；允许组织进攻前缀（贴近标注长链）",
        "min_len": 2,
        "max_len": 10,
        "sequences": _with_prefixes(
            [
                ["shot", "keeper_save"],
                ["pass", "shot", "keeper_save"],
                ["throw_in", "pass", "shot", "keeper_save"],
                ["throw_in", "pass", "shot", "keeper_save", "pass"],
                ["cross", "shot", "keeper_save"],
                ["cross", "header_shot", "keeper_save"],
                ["dribble_past", "shot", "keeper_save"],
                ["pass", "dribble_past", "shot", "keeper_save"],
                ["successful_tackle", "shot", "keeper_save"],
                ["successful_tackle", "pass", "shot", "keeper_save"],
                ["successful_tackle", "dribble_past", "pass", "shot", "keeper_save"],
                ["pass", "pass", "shot", "keeper_save"],
                ["pass", "pass", "pass", "shot", "keeper_save"],
                ["cross", "pass", "pass", "shot", "keeper_save"],
                ["pass", "successful_tackle", "pass", "pass", "shot", "keeper_save"],
                ["pass", "successful_tackle", "cross", "dribble_past", "shot", "keeper_save"],
                ["corner", "successful_tackle", "dribble_past", "pass", "shot", "keeper_save"],
                ["shot", "keeper_save", "shot", "keeper_save"],
                ["pass", "shot", "keeper_save", "shot", "shot", "keeper_save"],
                ["dribble_past", "pass", "keeper_save"],
                ["pass", "shot", "successful_tackle", "keeper_save"],
            ],
            [["pass"], ["pass", "pass"], ["dribble_past"], ["pass", "dribble_past"], []],
        ),
        "event_whitelist": BUILDUP + ["corner", "throw_in", "shot", "header_shot", "keeper_save"],
        "terminal_events": ["keeper_save"],
        "key_events": ["shot", "keeper_save"],
    },
    "shot_post_bar_chain": {
        "category": "danger",
        "label_zh": "射门门柱/横梁链",
        "description": "射门击中门框未进（用连续 shot 近似门柱叙事）",
        "min_len": 2,
        "max_len": 6,
        "sequences": [
            ["shot", "shot"],
            ["pass", "shot", "shot"],
            ["free_kick", "shot", "shot"],
            ["cross", "header_shot", "shot"],
        ],
        "event_whitelist": BUILDUP + ["free_kick", "shot", "header_shot"],
        "terminal_events": ["shot", "header_shot"],
        "key_events": ["shot"],
    },
    "second_phase_after_frame_chain": {
        "category": "danger",
        "label_zh": "门框后二次进攻链",
        "description": "门框相关后的二次进攻",
        "min_len": 3,
        "max_len": 8,
        "sequences": [
            ["shot", "shot", "corner"],
            ["cross", "shot", "shot", "cross"],
            ["shot", "keeper_save", "shot", "corner"],
            ["pass", "shot", "shot", "pass", "shot"],
        ],
        "event_whitelist": BUILDUP + ["shot", "keeper_save", "corner", "header_shot"],
        "terminal_events": ["corner", "shot", "cross", "keeper_save"],
        "key_events": ["shot"],
    },
    "goal_line_extreme_save_chain": {
        "category": "danger",
        "label_zh": "门线极限救险链",
        "description": "门线救险；允许任意球/传球前缀与少量后续防守",
        "min_len": 2,
        "max_len": 10,
        "sequences": [
            ["shot", "goal_line_clearance"],
            ["pass", "shot", "goal_line_clearance"],
            ["free_kick", "pass", "shot", "goal_line_clearance"],
            ["corner", "header_shot", "goal_line_clearance"],
            ["cross", "header_shot", "goal_line_clearance"],
            ["free_kick", "pass", "shot", "goal_line_clearance", "dribble_past", "successful_tackle"],
            ["pass", "shot", "goal_line_clearance", "dribble_past", "successful_tackle"],
            [
                "free_kick",
                "pass",
                "shot",
                "goal_line_clearance",
                "dribble_past",
                "successful_tackle",
                "pass",
                "shot",
                "goal_line_clearance",
            ],
        ],
        "event_whitelist": BUILDUP + ["free_kick", "corner", "shot", "header_shot", "goal_line_clearance"],
        "terminal_events": ["goal_line_clearance", "successful_tackle", "shot"],
        "key_events": ["goal_line_clearance"],
    },
    # ========== 特殊链 ==========
    "throw_in_build_up_chain": {
        "category": "special",
        "label_zh": "手抛球发动进攻链",
        "description": "界外球发动推进；宜止于射门/犯规/进攻中断，进球应改标结果链",
        "min_len": 2,
        "max_len": 8,
        "sequences": [
            ["throw_in", "pass", "shot"],
            ["throw_in", "pass", "cross", "shot"],
            ["throw_in", "dribble_past", "shot"],
            ["throw_in", "pass", "dribble_past", "shot"],
            ["throw_in", "dribble_past", "foul"],
            ["throw_in", "pass", "dribble_past"],
            ["throw_in", "successful_tackle", "pass", "pass", "dribble_past"],
            ["throw_in", "pass", "dribble_past", "assist", "shot"],
            ["throw_in", "aerial_won"],
            ["throw_in", "aerial_won", "aerial_won"],
            ["throw_in", "pass", "shot", "successful_tackle"],
            ["throw_in", "pass", "dribble_past", "assist", "shot", "goal"],
            ["throw_in", "pass", "cross", "header_shot", "goal"],
            ["throw_in", "pass", "cross", "shot", "goal"],
            ["throw_in", "pass", "shot", "goal"],
        ],
        "event_whitelist": ["throw_in"] + BUILDUP + ["shot", "foul", "goal", "keeper_save", "header_shot", "offside", "cross"],
        "terminal_events": ["shot", "foul", "dribble_past", "aerial_won", "goal", "keeper_save", "successful_tackle"],
        "key_events": ["throw_in"],
    },
    "own_goal_causal_chain": {
        "category": "special",
        "label_zh": "乌龙球致因链",
        "description": "导致乌龙的压力事件序列",
        "min_len": 2,
        "max_len": 7,
        "sequences": [
            ["cross", "header_shot", "goal"],
            ["possession_lost", "shot", "goal"],
            ["cross", "shot", "goal"],
            ["pass", "cross", "goal"],
        ],
        "event_whitelist": BUILDUP + ["shot", "goal", "header_shot", "possession_lost"],
        "terminal_events": ["goal"],
        "key_events": ["goal"],
    },
    "keeper_spill_danger_chain": {
        "category": "special",
        "label_zh": "门将脱手致险链",
        "description": "扑救后仍形成二次射门威胁",
        "min_len": 3,
        "max_len": 8,
        "sequences": [
            ["shot", "keeper_save", "shot"],
            ["cross", "header_shot", "keeper_save", "shot"],
            ["pass", "shot", "keeper_save", "shot"],
            ["shot", "keeper_save", "shot", "keeper_save"],
        ],
        "event_whitelist": BUILDUP + ["shot", "header_shot", "keeper_save"],
        "terminal_events": ["shot", "keeper_save"],
        "key_events": ["keeper_save", "shot"],
    },
    "deflection_goal_chain": {
        "category": "special",
        "label_zh": "折射/变线入网链",
        "description": "极简射门进球或变线入网",
        "min_len": 2,
        "max_len": 5,
        "sequences": [
            ["shot", "goal"],
            ["cross", "shot", "goal"],
            ["pass", "shot", "goal"],
        ],
        "event_whitelist": ["pass", "cross", "shot", "goal", "header_shot"],
        "terminal_events": ["goal"],
        "key_events": ["shot", "goal"],
    },
    "quick_restart_set_piece_chain": {
        "category": "special",
        "label_zh": "快发定位球链",
        "description": "快发任意球/界外球后的发展",
        "min_len": 2,
        "max_len": 7,
        "sequences": [
            ["free_kick", "pass", "shot"],
            ["free_kick", "shot"],
            ["throw_in", "pass", "cross"],
            ["throw_in", "pass", "shot"],
            ["free_kick", "pass", "cross", "shot"],
        ],
        "event_whitelist": ["free_kick", "throw_in"] + BUILDUP + ["shot"],
        "terminal_events": ["shot", "cross", "pass"],
        "key_events": ["free_kick", "throw_in"],
    },
}


# 长度建议摘要（供文档 / prompt）
LENGTH_GUIDE: Dict[str, Dict[str, int]] = {
    tid: {"min_len": meta["min_len"], "max_len": meta["max_len"]}
    for tid, meta in CHAIN4_SKELETONS.items()
}


def skeleton_as_templates() -> Dict[str, Dict[str, Any]]:
    """转为与 CHAIN_TEMPLATES 兼容的元数据表。"""
    return {
        tid: {
            "category": meta["category"],
            "label_zh": meta["label_zh"],
            "description": meta["description"],
            "min_len": meta["min_len"],
            "max_len": meta["max_len"],
        }
        for tid, meta in CHAIN4_SKELETONS.items()
    }


def canonical_sequences_map() -> Dict[str, List[List[str]]]:
    return {tid: [list(s) for s in meta["sequences"]] for tid, meta in CHAIN4_SKELETONS.items()}


def all_chain4_template_ids() -> List[str]:
    return list(CHAIN4_SKELETONS.keys())
