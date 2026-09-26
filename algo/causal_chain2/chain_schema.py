"""链模板与事件类型枚举（从 causal_chain/schema.py 迁入，供 timeline_highlights 等自包含调用）。"""

from typing import Dict, List, TypedDict


class ChainTemplateDef(TypedDict):
    category: str
    label_zh: str
    description: str


EVENT_TYPES: Dict[str, str] = {
    "goal": "进球",
    "penalty": "点球",
    "shot": "射门",
    "free_kick": "任意球",
    "red_card": "红牌",
    "second_yellow_red": "两黄变一红",
    "header_shot": "头球射门",
    "header_clearance": "头球解围",
    "header_goal": "头球破门",
    "goal_line_clearance": "门线救险",
    "yellow_card": "黄牌",
    "dribble_breakthrough": "盘带突破",
    "successful_tackle": "抢断成功",
    "interception": "拦截",
    "corner": "角球",
    "foul": "犯规",
    "injury_time": "伤停补时",
    "aerial_won": "争顶成功",
    "fouled": "被犯规",
    "offside": "越位",
    "assist": "助攻",
    "controversy": "争议",
    "var": "VAR",
    "match_start": "比赛开始（开球）",
    "match_end": "比赛结束",
    "player_entrance": "队员入场",
    "throw_in": "界外球",
    "substitution": "换人",
    "disallowed_goal": "无效进球",
    "cross": "传中",
    "pass": "传球",
    "dribble_past": "过人",
    "possession_lost": "丢球",
    "keeper_save": "门将扑救",
}

CHAIN_TEMPLATES: Dict[str, ChainTemplateDef] = {
    "corner_cross_goal": {
        "category": "outcome",
        "label_zh": "角球传中进球链",
        "description": "定位球发展：角球→传中→头球或射门→进球",
    },
    "rebound_follow_up_goal": {
        "category": "outcome",
        "label_zh": "射门被挡后补射进球链",
        "description": "首次射门被挡或扑救后出现补射并进球",
    },
    "turnover_counter_goal": {
        "category": "outcome",
        "label_zh": "抢断/反击/失误造成进球链",
        "description": "由守转攻后的快速进球",
    },
    "penalty_scored_chain": {
        "category": "outcome",
        "label_zh": "点球命中链",
        "description": "点球判罚后命中",
    },
    "red_card_decision_chain": {
        "category": "outcome",
        "label_zh": "红牌判罚链",
        "description": "犯规/争议后直红或两黄变一红",
    },
    "outcome_other": {
        "category": "outcome",
        "label_zh": "其他",
        "description": "其他进球结果叙事",
    },
    "goal_disallowed_chain": {
        "category": "correction",
        "label_zh": "进球无效链",
        "description": "进球后经 VAR/裁判改判无效",
    },
    "var_penalty_cancelled_chain": {
        "category": "correction",
        "label_zh": "VAR 取消点球链",
        "description": "VAR 介入后取消点球",
    },
    "var_overturn_chain": {
        "category": "correction",
        "label_zh": "VAR 改判链",
        "description": "VAR 改判关键事件",
    },
    "shot_save_chain": {
        "category": "danger",
        "label_zh": "射门扑救链",
        "description": "威胁射门被门将化解",
    },
    "shot_post_bar_chain": {
        "category": "danger",
        "label_zh": "射门门柱/横梁链",
        "description": "射门击中门框未进",
    },
    "second_phase_after_frame_chain": {
        "category": "danger",
        "label_zh": "门框后二次进攻链",
        "description": "门框相关后的二次进攻发展",
    },
    "goal_line_extreme_save_chain": {
        "category": "danger",
        "label_zh": "门线极限救险链",
        "description": "门线附近关键解围或扑救",
    },
    "throw_in_build_up_chain": {
        "category": "special",
        "label_zh": "手抛球发动进攻链",
        "description": "界外球快发后的推进",
    },
    "own_goal_causal_chain": {
        "category": "special",
        "label_zh": "乌龙球致因链",
        "description": "导致乌龙的压力事件序列",
    },
    "keeper_spill_danger_chain": {
        "category": "special",
        "label_zh": "门将脱手致险链",
        "description": "门将脱手后的险情发展",
    },
    "deflection_goal_chain": {
        "category": "special",
        "label_zh": "折射/变线入网链",
        "description": "变线折射后入网",
    },
    "quick_restart_set_piece_chain": {
        "category": "special",
        "label_zh": "快发定位球链",
        "description": "快发任意球/边线球后的发展",
    },
}

ALL_TEMPLATE_IDS: List[str] = list(CHAIN_TEMPLATES.keys())
