"""Phase 4A 实验配置与计费门控。

真实请求必须同时满足：
  STORY_API_ENABLE=1
  STORY_PHASE4A_REAL=1
  STORY_API_SMOKE=1（与 2C.1 一致，显式联调）
  以及 API Key / BASE_URL / MODEL / MAX_CALLS / MAX_COST_USD

默认 force_mock：允许对真实视频抽帧 + Mock VLM，不计费。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from story_video_agent.api_provider import api_enabled, smoke_enabled

# 克罗地亚搜索起点（仅 seed，不得预设识别正确）
CROATIA_SEED_EQUALIZER_LIVE_SEC = 3065.903
CROATIA_SEED_EQUALIZER_BOARD_SEC = 3145.980
CROATIA_SEED_GO_AHEAD_BOARD_SEC = 3697.35

DEFAULT_MAX_ROUNDS = 3
DEFAULT_FRAMES_PER_ROUND = 3
DEFAULT_FRAME_BUDGET = 18
DEFAULT_MAX_API_CALLS = 12
DEFAULT_WINDOW_HALF_SEC = 6.0
DEFAULT_EXPAND_SEC = 8.0
DEFAULT_SHIFT_SEC = 12.0

# 可选搜索目标（CLI --targets）
TARGET_IDS: Tuple[str, ...] = ("equalizer_goal", "go_ahead_goal")
DEFAULT_TARGETS: Tuple[str, ...] = TARGET_IDS

# Video-RSI 官方双模型标签；实际 request_model 以服务商可用 ID 为准
OFFICIAL_VIDEO_RSI_MODELS: Dict[str, str] = {
    "planner": "deepseek-v4-pro",
    "vision": "qwen3.6-plus",
}

# 首次真实 VLM-only 联调固定小预算（不自动执行）
FIRST_REAL_VLM_ONLY: Dict[str, Any] = {
    "mode": "vlm-only",
    "targets": ("equalizer_goal",),
    "seed_center_sec": CROATIA_SEED_EQUALIZER_LIVE_SEC,
    "max_rounds": 1,
    "frames_per_round": 2,
    "frame_budget": 4,
    "max_api_calls": 3,
    "max_completion_tokens": 256,
    "cost_note": "STORY_API_MAX_COST_USD is an estimate soft cap, not an invoice hard limit",
}


def phase4a_real_enabled() -> bool:
    """显式 Phase 4A 计费开关（独立于通用 STORY_API_ENABLE）。"""
    return (os.environ.get("STORY_PHASE4A_REAL") or "").strip() in (
        "1",
        "true",
        "TRUE",
        "yes",
    )


def billing_allowed() -> bool:
    return bool(api_enabled() and smoke_enabled() and phase4a_real_enabled())


def parse_targets(
    raw: Optional[Union[str, Sequence[str]]] = None,
) -> Tuple[str, ...]:
    """解析 --targets；默认两者，保持向后兼容。"""
    if raw is None:
        return DEFAULT_TARGETS
    parts: List[str] = []
    if isinstance(raw, str):
        items: Sequence[str] = [raw]
    else:
        items = raw
    for item in items:
        for piece in str(item).replace(";", ",").split(","):
            p = piece.strip()
            if p:
                parts.append(p)
    if not parts:
        return DEFAULT_TARGETS
    unknown = [p for p in parts if p not in TARGET_IDS]
    if unknown:
        raise ValueError(
            f"unknown targets {unknown}; expected one of {list(TARGET_IDS)}"
        )
    # 保序去重
    seen = set()
    out: List[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return tuple(out)


def first_real_vlm_only_config(
    *,
    force_mock: bool = False,
    **overrides: Any,
) -> "Phase4AConfig":
    """首次真实 VLM-only：equalizer @≈3065.9s，极小帧/HTTP 预算。"""
    base = dict(
        mode="vlm-only",
        force_mock=force_mock,
        max_rounds=int(FIRST_REAL_VLM_ONLY["max_rounds"]),
        frames_per_round=int(FIRST_REAL_VLM_ONLY["frames_per_round"]),
        frame_budget=int(FIRST_REAL_VLM_ONLY["frame_budget"]),
        max_api_calls=int(FIRST_REAL_VLM_ONLY["max_api_calls"]),
        targets=tuple(FIRST_REAL_VLM_ONLY["targets"]),
        promote_to_render_ready=False,
    )
    base.update(overrides)
    return Phase4AConfig(**base)


@dataclass
class Phase4AConfig:
    """VLM-only 与 Planner+VLM 共用配置。"""

    mode: str = "vlm-only"  # vlm-only | planner-vlm-loop
    force_mock: bool = True
    max_rounds: int = DEFAULT_MAX_ROUNDS
    frames_per_round: int = DEFAULT_FRAMES_PER_ROUND
    frame_budget: int = DEFAULT_FRAME_BUDGET
    window_half_sec: float = DEFAULT_WINDOW_HALF_SEC
    expand_sec: float = DEFAULT_EXPAND_SEC
    shift_sec: float = DEFAULT_SHIFT_SEC
    max_api_calls: Optional[int] = DEFAULT_MAX_API_CALLS
    targets: Tuple[str, ...] = DEFAULT_TARGETS
    # 是否在内部核验后尝试 promote（默认否：4A 产出 preview 候选优化）
    promote_to_render_ready: bool = False
    # Mock 路径是否允许根据观察调整候选时间窗（仍不授予 render_ready）
    allow_mock_window_adjust: bool = True

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["billing_allowed"] = billing_allowed()
        d["phase4a_real_enabled"] = phase4a_real_enabled()
        d["api_enabled"] = api_enabled()
        d["smoke_enabled"] = smoke_enabled()
        d["official_video_rsi_models"] = dict(OFFICIAL_VIDEO_RSI_MODELS)
        return d


# 记分牌→动作粗搜：扳平常见 Δ≈60–90s；反超可能更长（本场 ~172s）。
# 不得把 board 时间当作进球动作。
DEFAULT_EQ_SEARCH_BEFORE_SEC = 120.0
DEFAULT_GA_SEARCH_BEFORE_SEC = 200.0
DEFAULT_SEARCH_AFTER_BOARD_SEC = 5.0
DEFAULT_BOARD_FALLBACK_OFFSET_SEC = 40.0


def _goalish_times_from_story_events(
    story: Dict[str, Any],
    *,
    board_t: float,
    role_hint: Optional[str] = None,
    search_before: float,
    search_after: float = DEFAULT_SEARCH_AFTER_BOARD_SEC,
) -> List[Dict[str, Any]]:
    """从 story.events 抽取 board 前的 live 进球候选（seed only）。"""
    from story_video_agent.event_mapping import (
        find_live_goal_candidates,
        index_story_events,
    )

    indexed = index_story_events(story)
    cands = find_live_goal_candidates(
        indexed,
        score_t=board_t,
        role_hint=role_hint,
        slack_before=search_before,
        slack_after=search_after,
    )
    # 部分 story 把反超写成「射门」挂在记分牌时刻——不可作动作 seed
    out: List[Dict[str, Any]] = []
    for c in cands:
        t = float(c["t_sec"])
        if abs(t - board_t) < 1.0:
            continue  # 排除记分牌同秒伪动作
        out.append(
            {
                "event_id": c.get("event_id"),
                "t_sec": t,
                "source": "story_events",
                "dt_to_score_sec": c.get("dt_to_score_sec"),
                "confidence": c.get("confidence"),
            }
        )
    return out


def _goalish_times_from_causal(
    causal: Optional[Dict[str, Any]],
    *,
    board_t: float,
    search_before: float,
    search_after: float = DEFAULT_SEARCH_AFTER_BOARD_SEC,
) -> List[Dict[str, Any]]:
    """扫描 causal_chains 中 live Goal 标注；仅作 seed，不视为核验事实。"""
    if not causal:
        return []
    goal_types = {"进球", "Goal", "goal", "乌龙球"}
    out: List[Dict[str, Any]] = []
    for chain in causal.get("causal_chains") or []:
        if not isinstance(chain, dict):
            continue
        if chain.get("is_replay"):
            continue
        for ee in chain.get("events") or []:
            if not isinstance(ee, dict):
                continue
            typ = str(ee.get("type") or ee.get("type_en") or "")
            if typ not in goal_types and "goal" not in typ.lower() and "进球" not in typ:
                continue
            try:
                t = float(ee["t_ms"]) / 1000.0 if ee.get("t_ms") is not None else None
            except (TypeError, ValueError):
                t = None
            if t is None:
                continue
            if not (board_t - search_before <= t <= board_t + search_after):
                continue
            if abs(t - board_t) < 1.0:
                continue
            out.append(
                {
                    "event_id": ee.get("event_id"),
                    "t_sec": t,
                    "source": "causal_chain",
                    "annotation_id": chain.get("annotation_id"),
                    "dt_to_score_sec": round(t - board_t, 3),
                    "confidence": 0.45,
                }
            )
    out.sort(key=lambda r: abs(float(r["dt_to_score_sec"])))
    return out


def seed_targets_from_story(
    story: Dict[str, Any],
    *,
    causal: Optional[Dict[str, Any]] = None,
    half: float = DEFAULT_WINDOW_HALF_SEC,
    eq_search_before: float = DEFAULT_EQ_SEARCH_BEFORE_SEC,
    ga_search_before: float = DEFAULT_GA_SEARCH_BEFORE_SEC,
    board_fallback_offset: float = DEFAULT_BOARD_FALLBACK_OFFSET_SEC,
) -> List[Dict[str, Any]]:
    """从任意比赛 T01 Story JSON（+可选 causal）生成 Phase4 搜索种子。

    - score_path 只提供比分锚点，不是进球动作时间
    - 优先 story/causal 的 live Goal 候选作 seed_center
    - 无候选时退化为 board - offset，并扩大 locate 窗
    - 输出仍是 seed only，不得预设识别正确 / 不得提升 render_ready
    """
    from story_video_agent.state import _comeback_score_steps

    steps = _comeback_score_steps(story)
    targets: List[Dict[str, Any]] = []

    eq_board_node = steps.get("equalizer")
    ga_board_node = steps.get("go_ahead")

    if eq_board_node and eq_board_node.get("t_sec") is not None:
        eq_board = float(eq_board_node["t_sec"])
        story_cands = _goalish_times_from_story_events(
            story,
            board_t=eq_board,
            role_hint="转折",
            search_before=eq_search_before,
        )
        causal_cands = _goalish_times_from_causal(
            causal, board_t=eq_board, search_before=eq_search_before
        )
        best = (story_cands + causal_cands)
        best.sort(key=lambda r: (0 if r["source"] == "story_events" else 1, abs(r["dt_to_score_sec"])))
        if best:
            seed = float(best[0]["t_sec"])
            note = (
                f"story/causal live goal candidate @{seed:.3f}s "
                f"(Δ={best[0]['dt_to_score_sec']}s to board); seed only"
            )
            kind = "action_verify"
            gap = "verify_equalizer_goal_action"
            provenance = best[0]
        else:
            seed = max(0.0, eq_board - board_fallback_offset)
            note = (
                f"no live goal event; fallback seed board-{board_fallback_offset:.0f}s="
                f"{seed:.3f}s; locate before board @{eq_board:.3f}s"
            )
            kind = "action_locate"
            gap = "locate_equalizer_goal_action"
            provenance = None
        targets.append(
            {
                "target_id": "equalizer_goal",
                "role": "equalizer_goal_action",
                "beat": "转折",
                "gap_id": gap,
                "kind": kind,
                "seed_center_sec": seed,
                "score_anchor_sec": eq_board,
                "seed_note": note,
                "seed_provenance": provenance,
                "window": {
                    "start": max(0.0, seed - half)
                    if kind == "action_verify"
                    else max(0.0, eq_board - eq_search_before),
                    "end": (seed + half)
                    if kind == "action_verify"
                    else max(0.0, eq_board - DEFAULT_SEARCH_AFTER_BOARD_SEC),
                },
                "segment_id_hints": ["seg_equalizer_goal_action"],
            }
        )

    if ga_board_node and ga_board_node.get("t_sec") is not None:
        ga_board = float(ga_board_node["t_sec"])
        story_cands = _goalish_times_from_story_events(
            story,
            board_t=ga_board,
            role_hint="高潮",
            search_before=ga_search_before,
        )
        causal_cands = _goalish_times_from_causal(
            causal, board_t=ga_board, search_before=ga_search_before
        )
        best = (story_cands + causal_cands)
        best.sort(key=lambda r: (0 if r["source"] == "story_events" else 1, abs(r["dt_to_score_sec"])))
        if best:
            seed = float(best[0]["t_sec"])
            note = (
                f"story/causal live goal candidate @{seed:.3f}s "
                f"(Δ={best[0]['dt_to_score_sec']}s to board); seed only"
            )
            # 有候选仍先 locate/verify，不自动信任
            kind = "action_locate"
            gap = "locate_go_ahead_goal_action"
            provenance = best[0]
            win_start = max(0.0, seed - half)
            win_end = seed + half
        else:
            seed = max(0.0, ga_board - board_fallback_offset)
            note = (
                f"no live goal event; fallback seed board-{board_fallback_offset:.0f}s="
                f"{seed:.3f}s; coarse locate in [{ga_board - ga_search_before:.1f},"
                f" {ga_board - DEFAULT_SEARCH_AFTER_BOARD_SEC:.1f}]"
            )
            kind = "action_locate"
            gap = "locate_go_ahead_goal_action"
            provenance = None
            win_start = max(0.0, ga_board - ga_search_before)
            win_end = max(0.0, ga_board - DEFAULT_SEARCH_AFTER_BOARD_SEC)
        targets.append(
            {
                "target_id": "go_ahead_goal",
                "role": "go_ahead_goal_action",
                "beat": "高潮",
                "gap_id": gap,
                "kind": kind,
                "seed_center_sec": seed,
                "score_anchor_sec": ga_board,
                "seed_note": note,
                "seed_provenance": provenance,
                "window": {"start": win_start, "end": win_end},
                "segment_id_hints": [
                    "seg_go_ahead_goal_pending",
                    "seg_go_ahead_goal_action",
                ],
            }
        )

    if not targets:
        raise ValueError(
            "seed_targets_from_story: no equalizer/go_ahead score_path milestones"
        )
    return targets


def croatia_seed_targets(
    *,
    eq_live: float = CROATIA_SEED_EQUALIZER_LIVE_SEC,
    eq_board: float = CROATIA_SEED_EQUALIZER_BOARD_SEC,
    ga_board: float = CROATIA_SEED_GO_AHEAD_BOARD_SEC,
    half: float = DEFAULT_WINDOW_HALF_SEC,
) -> List[Dict[str, Any]]:
    """克罗地亚硬编码种子（向后兼容 / 单测基线）。

    新比赛请用 ``seed_targets_from_story``。硬编码 go_ahead 窗仅 ~80s，
    本场真实动作约在 board-172s，已被 Phase4C 证明过窄。
    """
    return [
        {
            "target_id": "equalizer_goal",
            "role": "equalizer_goal_action",
            "beat": "转折",
            "gap_id": "verify_equalizer_goal_action",
            "kind": "action_verify",
            "seed_center_sec": eq_live,
            "score_anchor_sec": eq_board,
            "seed_note": "Phase3A.1 live candidate ≈3065.9s; seed only",
            "window": {
                "start": max(0.0, eq_live - half),
                "end": eq_live + half,
            },
            "segment_id_hints": ["seg_equalizer_goal_action"],
        },
        {
            "target_id": "go_ahead_goal",
            "role": "go_ahead_goal_action",
            "beat": "高潮",
            "gap_id": "locate_go_ahead_goal_action",
            "kind": "action_locate",
            "seed_center_sec": max(0.0, ga_board - 40.0),
            "score_anchor_sec": ga_board,
            "seed_note": (
                "legacy croatia hardcode: search before go-ahead board ≈3697s; "
                "window ~80s may miss long board lag; prefer seed_targets_from_story"
            ),
            "window": {
                "start": max(0.0, ga_board - 80.0),
                "end": ga_board - 5.0,
            },
            "segment_id_hints": [
                "seg_go_ahead_goal_pending",
                "seg_go_ahead_goal_action",
            ],
        },
    ]


SEED_MODE_STORY = "story"
SEED_MODE_CROATIA_LEGACY = "croatia_legacy"
SEED_MODES = (SEED_MODE_STORY, SEED_MODE_CROATIA_LEGACY)


def resolve_seed_targets(
    targets: Sequence[str],
    *,
    half: float = DEFAULT_WINDOW_HALF_SEC,
    story: Optional[Dict[str, Any]] = None,
    causal: Optional[Dict[str, Any]] = None,
    seed_mode: str = SEED_MODE_STORY,
) -> List[Dict[str, Any]]:
    """Phase4A preflight/run/CLI 统一种子入口。

    - 默认 ``story``：必须提供当前比赛 Story JSON（+可选 Causal）
    - ``croatia_legacy``：仅显式兼容测试；不得作为跨比赛默认
    - 缺少翻盘里程碑时抛错，禁止静默用记分牌时间冒充进球动作
    """
    mode = (seed_mode or SEED_MODE_STORY).strip().lower()
    if mode not in SEED_MODES:
        raise ValueError(f"unknown seed_mode {seed_mode!r}; expected one of {list(SEED_MODES)}")
    want = parse_targets(list(targets))
    if mode == SEED_MODE_CROATIA_LEGACY:
        pool = croatia_seed_targets(half=half)
    else:
        if story is None:
            raise ValueError(
                "seed_mode=story requires story dict; "
                "pass Story JSON or use --seed-mode croatia_legacy for explicit compat only"
            )
        pool = seed_targets_from_story(story, causal=causal, half=half)
    selected = [t for t in pool if t["target_id"] in set(want)]
    if not selected:
        raise ValueError(
            f"no seed targets matched {list(want)} under seed_mode={mode} "
            f"(available={[t.get('target_id') for t in pool]})"
        )
    # 硬约束：动作 seed 不得等于记分牌锚点
    for t in selected:
        seed = t.get("seed_center_sec")
        board = t.get("score_anchor_sec")
        if seed is None or board is None:
            continue
        if abs(float(seed) - float(board)) < 1.0:
            raise ValueError(
                f"seed_center must not equal scoreboard anchor for {t.get('target_id')}: "
                f"seed={seed} board={board}"
            )
    return selected


def select_seed_targets(
    targets: Sequence[str],
    *,
    half: float = DEFAULT_WINDOW_HALF_SEC,
    story: Optional[Dict[str, Any]] = None,
    causal: Optional[Dict[str, Any]] = None,
    prefer_story: bool = True,
    seed_mode: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """兼容包装：优先 ``resolve_seed_targets``。

    - 显式 ``seed_mode`` 优先
    - 否则 prefer_story + story → story；无 story 且 prefer_story → 报错
    - prefer_story=False → croatia_legacy（旧单测）
    """
    if seed_mode is not None:
        mode = seed_mode
    elif prefer_story:
        mode = SEED_MODE_STORY if story is not None else SEED_MODE_STORY
        if story is None:
            raise ValueError(
                "select_seed_targets: story required when prefer_story=True; "
                "pass story=... or prefer_story=False / seed_mode=croatia_legacy"
            )
    else:
        mode = SEED_MODE_CROATIA_LEGACY
    return resolve_seed_targets(
        targets,
        half=half,
        story=story,
        causal=causal,
        seed_mode=mode,
    )


def load_optional_json(path: Optional[Union[str, Path]]) -> Optional[Dict[str, Any]]:
    if path is None:
        return None
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"json missing: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"json root must be object: {p}")
    return data


EXPERIMENT_MODES = ("vlm-only", "planner-vlm-loop")
