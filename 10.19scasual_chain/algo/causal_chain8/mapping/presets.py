"""事件 type 映射：中文/params/type_en → 英文 key（含 own_goal/乌龙球）。"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from causal_chain2.chain_schema import EVENT_TYPES

from causal_chain8.schema.templates import CHAIN4_TEMPLATES

ZH_EVENT_TO_TYPE: Dict[str, str] = {zh: en for en, zh in EVENT_TYPES.items()}
ZH_EVENT_TO_TYPE.update(
    {
        "头球": "header_shot",
        "传中": "cross",
        "角球": "corner",
        "点球": "penalty",
        "犯规": "foul",
        "抢断": "successful_tackle",
        "拦截": "interception",
        "扑救": "keeper_save",
        "门线救险": "goal_line_clearance",
        "过人": "dribble_past",
        "防守动作": "successful_tackle",
        "犯规/被犯规": "fouled",
        "控球": "pass",
        "乌龙": "own_goal",
        "乌龙球": "own_goal",
    }
)

EN_EVENT_TO_TYPE: Dict[str, str] = {
    "pass": "pass",
    "shot": "shot",
    "goal": "goal",
    "own_goal": "own_goal",
    "owngoal": "own_goal",
    "save": "keeper_save",
    "throw_in": "throw_in",
    "corner_kick": "corner",
    "free_kick": "free_kick",
    "goal_line_clearance": "goal_line_clearance",
    "dribble_past": "dribble_past",
    "defensive_action": "successful_tackle",
    "ball_possession": "pass",
    "assist": "assist",
    "win_an_aerial_duel": "aerial_won",
    "header": "header_shot",
    "cross": "cross",
    "foul": "foul",
    "var": "var",
}

LABEL_ZH_TO_TEMPLATE: Dict[str, str] = {
    meta["label_zh"]: tid for tid, meta in CHAIN4_TEMPLATES.items()
}
LABEL_ZH_TO_TEMPLATE.update(
    {
        "其他": "outcome_other",
        "个人突破后射门进球链": "individual_breakthrough_goal",
        "团队配合射门进球链": "team_buildup_goal",
        "角球配合进球链": "corner_coop_goal",
        "抢断/反击/失误后直接进球链": "turnover_counter_goal",
        "抢断/反击/失误造成进球链": "turnover_counter_goal",
        "射门扑救链": "shot_save_chain",
        "角球传中进球链": "corner_cross_goal",
        "进球无效链": "goal_disallowed_chain",
        "射中门柱/横梁链": "shot_post_bar_chain",
        "门线极限救险链": "goal_line_extreme_save_chain",
        "门框后二次进攻链": "second_phase_after_frame_chain",
        "门将脱手致险链": "keeper_spill_danger_chain",
        "手抛球发动进攻链": "throw_in_build_up_chain",
        "快发定位球链": "quick_restart_set_piece_chain",
        "折射/变线进球链": "deflection_goal_chain",
        "折射/变线入网链": "deflection_goal_chain",
        "射门被扑后补射进球链": "rebound_follow_up_goal",
        "VAR取消点球链": "var_penalty_cancelled_chain",
        "VAR改判链": "var_overturn_chain",
        "乌龙球致因链": "own_goal_causal_chain",
    }
)

CAT_ZH_TO_EN = {
    "结果链": "outcome",
    "改判链": "correction",
    "修正链": "correction",
    "险情链": "danger",
    "特殊链": "special",
}

OFFICIAL_ZH_TYPES = set(EVENT_TYPES.values()) | {"头球", "传中"}


def map_event_strict(ev: Dict[str, Any], warnings: List[str]) -> str:
    zh = str(ev.get("type", "")).strip()
    if zh in ZH_EVENT_TO_TYPE:
        en = ZH_EVENT_TO_TYPE[zh]
        if zh == "控球":
            warnings.append("mapped_ball_possession_to_pass")
        if zh == "防守动作":
            warnings.append("mapped_defensive_action_to_tackle")
        return en

    type_en = str(ev.get("type_en", "")).strip()
    if type_en:
        key = re.sub(r"[^a-z0-9]+", "_", type_en.lower()).strip("_")
        if key in EN_EVENT_TO_TYPE:
            return EN_EVENT_TO_TYPE[key]

    if zh:
        warnings.append(f"unknown_event_type:{zh}")
    return "pass"


def map_event_params_first(ev: Dict[str, Any], warnings: List[str]) -> str:
    params = ev.get("params") or {}
    tag = str(params.get("Type", "")).strip().lower()
    zh = str(ev.get("type", "")).strip()

    if tag == "cross" and zh in ("传球", ""):
        if zh == "传球":
            warnings.append("params_cross_overrides_pass")
        return "cross"

    if tag in ("key_pass", "short_pass", "long_pass") and zh in ("传球", ""):
        return "pass"

    return map_event_strict(ev, warnings)


def map_event_annotation_compat(ev: Dict[str, Any], warnings: List[str]) -> str:
    return map_event_params_first(ev, warnings)


def validate_official_zh(ev: Dict[str, Any], warnings: List[str]) -> None:
    zh = str(ev.get("type", "")).strip()
    if zh and zh not in OFFICIAL_ZH_TYPES:
        warnings.append(f"non_official_zh_type:{zh}")
