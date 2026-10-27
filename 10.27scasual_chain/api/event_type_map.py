"""咪咕 eventTypeId / eventName → 内部 type 的唯一 provisional 表。

正式字典未拿到前，全仓库只允许从本文件读取映射；禁止在其它模块 hardcode。

未知类型策略见 map_event_type_with_context：不静默猜成已知事件，回落为哨兵
``unmapped``，并打结构化告警日志。
"""

from __future__ import annotations

from typing import Dict

# ---------------------------------------------------------------------------
# PROTOCOL_BLOCKER（联调 RC 唯一协议待确认项）：
# 正式 eventTypeId → internal type 字典（咪咕书面版）到位后替换本表。
# ---------------------------------------------------------------------------

PROVISIONAL_EVENT_TYPE_MAP: Dict[str, str] = {
    # English / id-like
    "shot": "shot",
    "goal": "goal",
    "own_goal": "own_goal",
    "header_goal": "goal",
    "save": "keeper_save",
    "keeper_save": "keeper_save",
    "pass": "pass",
    "assist": "assist",
    "corner_kick": "corner",
    "corner": "corner",
    "free_kick": "free_kick",
    "penalty": "penalty",
    "penalty_": "penalty",
    "throw_in": "throw_in",
    "dribble_past": "dribble_past",
    "dribble_breakthrough": "dribble_breakthrough",
    "goal_line_clearance": "goal_line_clearance",
    "successful_tackle": "successful_tackle",
    "interception": "interception",
    "var": "var",
    "video_assistant_referee": "var",
    "foul": "foul",
    "red_card": "red_card",
    "second_yellow_red": "second_yellow_red",
    "yellow_card": "yellow_card",
    "cross": "cross",
    "header_shot": "header_shot",
    "aerial_won": "aerial_won",
    "possession_lost": "possession_lost",
    "controversy": "controversy",
    "disallowed_goal": "disallowed_goal",
    "match_start": "match_start",
    # 中文 eventName
    "射门": "shot",
    "进球": "goal",
    "乌龙": "own_goal",
    "乌龙球": "own_goal",
    "头球进球": "goal",
    "扑救": "keeper_save",
    "传球": "pass",
    "助攻": "assist",
    "角球": "corner",
    "任意球": "free_kick",
    "点球": "penalty",
    "界外球": "throw_in",
    "过人": "dribble_past",
    "盘带突破": "dribble_breakthrough",
    "门线救险": "goal_line_clearance",
    "抢断成功": "successful_tackle",
    "拦截": "interception",
    "红牌": "red_card",
    "两黄变一红": "second_yellow_red",
    "黄牌": "yellow_card",
    "头球": "header_shot",
    "争顶成功": "aerial_won",
    "VAR": "var",
    "犯规": "foul",
    "传中": "cross",
    "进球无效": "disallowed_goal",
}

# 未知映射哨兵：不得替换成 goal/shot 等已知类型
UNMAPPED_EVENT_TYPE = "unmapped"
