"""Phase 4A 实验配置与计费门控。

真实请求必须同时满足：
  STORY_API_ENABLE=1
  STORY_PHASE4A_REAL=1
  STORY_API_SMOKE=1（与 2C.1 一致，显式联调）
  以及 API Key / BASE_URL / MODEL / MAX_CALLS / MAX_COST_USD

默认 force_mock：允许对真实视频抽帧 + Mock VLM，不计费。
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
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


def croatia_seed_targets(
    *,
    eq_live: float = CROATIA_SEED_EQUALIZER_LIVE_SEC,
    eq_board: float = CROATIA_SEED_EQUALIZER_BOARD_SEC,
    ga_board: float = CROATIA_SEED_GO_AHEAD_BOARD_SEC,
    half: float = DEFAULT_WINDOW_HALF_SEC,
) -> List[Dict[str, Any]]:
    """返回搜索目标；时间仅为起点，不假定正确。"""
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
                "no trusted live goal; search before go-ahead board ≈3697s; seed only"
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


def select_seed_targets(
    targets: Sequence[str],
    *,
    half: float = DEFAULT_WINDOW_HALF_SEC,
) -> List[Dict[str, Any]]:
    """按 target_id 筛选种子窗；未知或空匹配则报错（不静默回退全量）。"""
    want = parse_targets(list(targets))
    selected = [
        t for t in croatia_seed_targets(half=half) if t["target_id"] in set(want)
    ]
    if not selected:
        raise ValueError(f"no seed targets matched {list(want)}")
    return selected


EXPERIMENT_MODES = ("vlm-only", "planner-vlm-loop")
