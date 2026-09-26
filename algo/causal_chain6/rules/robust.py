"""分类鲁棒策略：噪声降权、终局优先、锚点约束、短核 + 形态仲裁。

仅作用于 chain6 规则排序；不改 causal_chain4。由 profile.robust_classify 控制。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Set

# 匹配时可忽略的干扰（红牌链例外见 denoise_types）
NOISE_EVENTS: Set[str] = {
    "substitution",
    "injury_time",
    "yellow_card",
    "controversy",
}

EVENT_ALIASES: Dict[str, str] = {
    "dribble_breakthrough": "dribble_past",
    "header_goal": "header_goal",
    "ball_possession": "pass",
}

ANCHOR_PRIORITY: List[str] = [
    "disallowed_goal",
    "goal",
    "header_goal",
    "penalty",
    "red_card",
    "second_yellow_red",
    "goal_line_clearance",
    "keeper_save",
    "shot",
    "header_shot",
    "corner",
    "throw_in",
    "free_kick",
]

_GOAL_OUTCOME_TEMPLATES = (
    "corner_cross_goal",
    "corner_coop_goal",
    "turnover_counter_goal",
    "penalty_scored_chain",
    "rebound_follow_up_goal",
    "team_buildup_goal",
    "individual_breakthrough_goal",
    "deflection_goal_chain",
)


def robust_enabled(profile: Optional[Dict[str, Any]]) -> bool:
    if not profile:
        return True
    cfg = profile.get("robust_classify")
    if cfg is None:
        return True
    if isinstance(cfg, bool):
        return cfg
    if isinstance(cfg, dict):
        return bool(cfg.get("enabled", True))
    return True


def _cfg(profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    raw = (profile or {}).get("robust_classify")
    if isinstance(raw, dict):
        return raw
    return {}


def normalize_type(t: str) -> str:
    t = str(t or "").strip()
    return EVENT_ALIASES.get(t, t)


def normalize_types(event_types: Sequence[str]) -> List[str]:
    return [normalize_type(t) for t in event_types if t]


def denoise_types(event_types: Sequence[str], *, keep_foul: bool = False) -> List[str]:
    """去掉干扰事件；红牌相关时保留 foul。越位仅在吹掉语境保留。"""
    types = normalize_types(event_types)
    has_red = any(t in ("red_card", "second_yellow_red") for t in types)
    has_disallowed = "disallowed_goal" in types
    out: List[str] = []
    for t in types:
        if t in NOISE_EVENTS:
            continue
        if t == "offside" and not has_disallowed:
            continue
        if t == "foul" and not keep_foul and not has_red and "penalty" not in types:
            continue
        out.append(t)
    if len(out) < 2:
        out = [t for t in types if t not in NOISE_EVENTS]
    return out if out else list(types)


def primary_anchor(event_types: Sequence[str]) -> Optional[str]:
    s = set(normalize_types(event_types))
    for a in ANCHOR_PRIORITY:
        if a in s:
            return a
    return None


def extract_core_types(
    event_types: Sequence[str],
    *,
    max_core: int = 8,
    min_len_trigger: int = 7,
) -> List[str]:
    denoised = denoise_types(event_types, keep_foul=True)
    if len(denoised) <= min_len_trigger:
        return denoised

    anchor = primary_anchor(denoised)
    if not anchor:
        return denoised[:max_core]

    idx = max(i for i, t in enumerate(denoised) if t == anchor)
    half = max_core // 2
    lo = max(0, idx - half + 1)
    hi = min(len(denoised), lo + max_core)
    lo = max(0, hi - max_core)
    core = denoised[lo:hi]
    return core if core else denoised


def scoring_view(
    event_types: Sequence[str],
    profile: Optional[Dict[str, Any]] = None,
) -> List[str]:
    cfg = _cfg(profile)
    use_core = bool(cfg.get("short_core", True))
    min_trigger = int(cfg.get("core_min_len", 7))
    max_core = int(cfg.get("core_max", 8))
    if use_core:
        return extract_core_types(
            event_types, max_core=max_core, min_len_trigger=min_trigger
        )
    return denoise_types(event_types, keep_foul=True)


def _last_idx(types: Sequence[str], name: str) -> int:
    for i in range(len(types) - 1, -1, -1):
        if types[i] == name:
            return i
    return -1


def endpoint_adjustments(event_types: Sequence[str]) -> Dict[str, float]:
    """终局/锚点加减分（加到 critic_score）。"""
    types = normalize_types(event_types)
    core = denoise_types(types, keep_foul=True)
    view = core if core else types
    full = set(types)
    end = view[-1] if view else ""
    adj: Dict[str, float] = defaultdict(float)

    if "disallowed_goal" in full or end == "disallowed_goal":
        adj["goal_disallowed_chain"] += 0.55
        adj["var_overturn_chain"] += 0.30
        adj["corner_cross_goal"] -= 0.30
        adj["corner_coop_goal"] -= 0.30
        adj["own_goal_causal_chain"] -= 0.35
        adj["outcome_other"] -= 0.15

    if "penalty" in full and ("goal" in full or end == "goal"):
        adj["penalty_scored_chain"] += 0.50
        adj["red_card_decision_chain"] -= 0.15

    if ("red_card" in full or "second_yellow_red" in full) and "penalty" not in full:
        adj["red_card_decision_chain"] += 0.45

    if "keeper_save" in full and end not in ("goal", "disallowed_goal") and "goal" not in full:
        adj["shot_save_chain"] += 0.45
        adj["throw_in_build_up_chain"] -= 0.40
        adj["quick_restart_set_piece_chain"] -= 0.20
        if end == "pass" or view[-1:] == ["pass"]:
            adj["shot_save_chain"] += 0.05

    if view and view[0] == "throw_in" and end == "goal":
        adj["throw_in_build_up_chain"] += 0.40
        adj["own_goal_causal_chain"] -= 0.55
        adj["corner_cross_goal"] -= 0.10

    if "corner" in full and "cross" in full and end == "goal" and "disallowed_goal" not in full:
        adj["corner_cross_goal"] += 0.40
        adj["corner_coop_goal"] -= 0.25
        adj["own_goal_causal_chain"] -= 0.40
        adj["turnover_counter_goal"] -= 0.10

    if "corner" in full and "cross" not in full and end == "goal" and "disallowed_goal" not in full:
        adj["corner_coop_goal"] += 0.15
        adj["corner_cross_goal"] += 0.05

    if end == "goal" and "disallowed_goal" not in full:
        if "interception" in full or "successful_tackle" in full or "possession_lost" in full:
            if "corner" not in full:
                adj["turnover_counter_goal"] += 0.30
                if "dribble_past" in full or "assist" in full:
                    adj["turnover_counter_goal"] += 0.12
                adj["outcome_other"] -= 0.10
                adj["team_buildup_goal"] -= 0.12

    if "goal_line_clearance" in full and end == "goal":
        adj["turnover_counter_goal"] += 0.40
        adj["team_buildup_goal"] -= 0.30
        adj["goal_line_extreme_save_chain"] -= 0.20
        adj["individual_breakthrough_goal"] -= 0.10

    if "own_goal" not in full:
        adj["own_goal_causal_chain"] -= 0.45

    if (
        view.count("cross") >= 2
        and view.count("header_shot") >= 2
        and "keeper_save" not in full
        and end != "goal"
    ):
        adj["second_phase_after_frame_chain"] += 0.75
        adj["shot_post_bar_chain"] -= 0.35
        adj["shot_save_chain"] -= 0.15
        adj["own_goal_causal_chain"] -= 0.10
        adj["keeper_spill_danger_chain"] -= 0.15

    shot_n = view.count("shot") + view.count("header_shot")
    if end == "shot" and shot_n <= 1:
        adj["shot_post_bar_chain"] -= 0.20
        if "assist" in full or "interception" in full:
            adj["shot_post_bar_chain"] -= 0.10

    if "throw_in" in full:
        adj["throw_in_build_up_chain"] += 0.25
        adj["second_phase_after_frame_chain"] -= 0.20
        adj["shot_post_bar_chain"] -= 0.15

    return dict(adj)


def morphology_adjustments(event_types: Sequence[str]) -> Dict[str, float]:
    """形态仲裁：无进球不抢结果类、补射压纯扑救、中柱不被未完成反击抢走。"""
    types = normalize_types(event_types)
    view = denoise_types(types, keep_foul=True) or types
    full = set(types)
    end = view[-1] if view else ""
    adj: Dict[str, float] = defaultdict(float)
    has_goal = "goal" in full or "header_goal" in full

    if not has_goal and "disallowed_goal" not in full:
        for tid in _GOAL_OUTCOME_TEMPLATES:
            adj[tid] -= 0.38
        adj["turnover_counter_goal"] -= 0.12

    if end in ("shot", "header_shot") and not has_goal and "keeper_save" not in full:
        second_phase = view.count("cross") >= 2 and view.count("header_shot") >= 2
        if not second_phase:
            adj["shot_post_bar_chain"] += 0.42
            adj["turnover_counter_goal"] -= 0.28
            adj["shot_post_bar_chain"] += 0.12
        else:
            adj["shot_post_bar_chain"] -= 0.25

    if "keeper_save" in full and has_goal and end in ("goal", "header_goal"):
        i_save = _last_idx(view, "keeper_save")
        i_shot = max(_last_idx(view, "shot"), _last_idx(view, "header_shot"))
        if 0 <= i_save < i_shot:
            adj["rebound_follow_up_goal"] += 0.42
            adj["shot_save_chain"] -= 0.38

    if has_goal and "corner" in full and "disallowed_goal" not in full:
        i_int = max(
            _last_idx(view, "interception"),
            _last_idx(view, "successful_tackle"),
            _last_idx(view, "possession_lost"),
        )
        i_cor = _last_idx(view, "corner")
        if i_cor >= 0 and i_int >= 0 and i_cor > i_int:
            adj["corner_cross_goal"] += 0.18
            adj["turnover_counter_goal"] -= 0.22

    return dict(adj)


def apply_robust_scores(
    ranked: List[Dict[str, Any]],
    event_types: Sequence[str],
    *,
    profile: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    if not robust_enabled(profile) or not ranked:
        return ranked
    adj = endpoint_adjustments(event_types)
    if bool(_cfg(profile).get("morphology", True)):
        for k, v in morphology_adjustments(event_types).items():
            adj[k] = adj.get(k, 0.0) + v
    out: List[Dict[str, Any]] = []
    for r in ranked:
        tid = r["chain_template_id"]
        nr = dict(r)
        delta = float(adj.get(tid, 0.0))
        if delta:
            nr["critic_score"] = round(float(nr.get("critic_score", 0.0)) + delta, 4)
            nr["robust_delta"] = round(delta, 4)
        out.append(nr)
    out.sort(key=lambda x: -float(x.get("critic_score", 0.0)))
    return out
