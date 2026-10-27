"""从 T01 故事 JSON 构建 Video Agent 初始状态与证据缺口（Phase 1.5）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

PathLike = Union[str, Path]

_ROLE_BEATS = ("铺垫", "蓄力", "转折", "高潮", "收尾")
_GOAL_TYPES = frozenset({"进球", "乌龙球", "头球破门", "goal", "own_goal", "header_goal"})
_ATTEMPT_TYPES = frozenset({"射门", "任意球", "角球", "扑救", "门线救险", "shot", "free_kick", "corner", "keeper_save"})
_TASK_STATUSES = frozenset(
    {"pending", "running", "sampled", "observed", "verified", "unresolved", "failed"}
)

# 法国 vs 澳大利亚 Phase 2B 最小感知集：扳平动作、反超动作、反应
FRANCE_PERCEPTION_FOCUS = (
    "verify_equalizer_goal_action",
    "verify_go_ahead_goal_action",
    "post_climax_reaction",
)
_CHUNK_SEC = 90.0
_OCR_PAD_BEFORE = 2.0
_OCR_PAD_AFTER = 6.0
_ACTION_PAD = 8.0
_GOAL_MATCH_SLACK = 120.0


def load_t01_story(path: PathLike) -> Dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("T01 story JSON must be an object")
    return data


def _score_nodes(story: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [node for node in (story.get("score_path") or []) if isinstance(node, dict)]


def _margin(score: str, side: str) -> Optional[int]:
    if not isinstance(score, str) or ":" not in score:
        return None
    left_s, right_s = score.split(":", 1)
    try:
        left, right = int(left_s), int(right_s)
    except ValueError:
        return None
    if side == "left":
        return left - right
    if side == "right":
        return right - left
    return None


def _comeback_score_steps(story: Dict[str, Any]) -> Dict[str, Optional[Dict[str, Any]]]:
    """从 score_path 抽出扳平/反超节点，对齐 T01 最后一次逆转弧（find_comeback_arc）。

    仅改 Video Agent 状态层；不改写 T01 识别 JSON。
    """
    side = story.get("protagonist_side") or (story.get("recognition") or {}).get("protagonist_side")
    nodes = _score_nodes(story)
    if not side or not nodes:
        return {"equalizer": None, "go_ahead": None, "behind_start": nodes[0] if nodes else None}

    last_behind_idx: Optional[int] = None
    for index, node in enumerate(nodes):
        margin = _margin(str(node.get("score") or ""), side)
        if margin is not None and margin < 0:
            last_behind_idx = index
    if last_behind_idx is None:
        return {"equalizer": None, "go_ahead": None, "behind_start": nodes[0]}

    equalizer = None
    go_ahead = None
    for node in nodes[last_behind_idx + 1 :]:
        margin = _margin(str(node.get("score") or ""), side)
        if margin is None:
            continue
        if equalizer is None and margin == 0:
            equalizer = node
        elif equalizer is not None and go_ahead is None and margin > 0:
            go_ahead = node
            break

    spell_start = last_behind_idx
    while spell_start > 0:
        prev_margin = _margin(str(nodes[spell_start - 1].get("score") or ""), side)
        if prev_margin is not None and prev_margin < 0:
            spell_start -= 1
        else:
            break
    behind_start = nodes[spell_start]
    return {"equalizer": equalizer, "go_ahead": go_ahead, "behind_start": behind_start}


def build_event_index(story: Dict[str, Any]) -> List[Dict[str, Any]]:
    """故事事件时间索引：供铺垫/蓄力搜索区间与进球锚点使用。"""
    rows: List[Dict[str, Any]] = []
    for event in story.get("events") or []:
        t_ms = event.get("t_ms")
        if t_ms is None:
            continue
        rows.append(
            {
                "event_id": str(event.get("event_id") or ""),
                "type": str(event.get("type") or ""),
                "role": str(event.get("story_role") or ""),
                "t_sec": float(t_ms) / 1000.0,
                "source": str(event.get("source") or ""),
            }
        )
    rows.sort(key=lambda row: (row["t_sec"], row["event_id"]))
    return rows


def _split_search_intervals(t0: float, t1: float, *, chunk: float = _CHUNK_SEC) -> List[Dict[str, Any]]:
    if t1 <= t0:
        return []
    intervals: List[Dict[str, Any]] = []
    cursor = t0
    level = 0
    while cursor < t1 - 1e-6:
        end = min(t1, cursor + chunk)
        intervals.append(
            {
                "start": round(cursor, 3),
                "end": round(end, 3),
                "expand_level": level,
                "expand_policy": "double_chunk_on_miss",
            }
        )
        cursor = end
        level = 0  # 同级粗搜；失败后再由执行层升 expand_level
    return intervals


def _clip_window(
    start: float,
    end: float,
    *,
    duration: Optional[float],
) -> Tuple[Optional[Dict[str, float]], Dict[str, Any]]:
    meta: Dict[str, Any] = {"clamped": False, "duration_unknown": False, "oob": False}
    if end <= start:
        meta["oob"] = True
        return None, meta
    if duration is None or duration <= 0:
        meta["duration_unknown"] = True
        return {"start": start, "end": end}, meta
    clipped_start = max(0.0, start)
    clipped_end = min(duration, end)
    if clipped_end <= clipped_start:
        meta["oob"] = True
        return None, meta
    if clipped_start != start or clipped_end != end:
        meta["clamped"] = True
    return {"start": round(clipped_start, 3), "end": round(clipped_end, 3)}, meta


def _goal_anchor_near(index: Sequence[Dict[str, Any]], score_t: float, role: Optional[str] = None) -> Optional[float]:
    candidates = []
    for row in index:
        if row["type"] not in _GOAL_TYPES:
            continue
        if role and row["role"] and row["role"] != role:
            # 仍允许同角色优先，非同角色也可作候选
            pass
        delta = row["t_sec"] - score_t
        # 进球通常早于或接近记分牌确认
        if -_GOAL_MATCH_SLACK <= delta <= 30.0:
            weight = abs(delta) + (0.0 if (not role or row["role"] == role) else 50.0)
            candidates.append((weight, row["t_sec"]))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


def _attempt_times_in(index: Sequence[Dict[str, Any]], t0: float, t1: float) -> List[float]:
    return [row["t_sec"] for row in index if t0 <= row["t_sec"] < t1 and row["type"] in _ATTEMPT_TYPES]


def detect_gaps(
    story: Dict[str, Any],
    *,
    duration_sec: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """相对 T01 状态列证据缺口。none 不生成补故事任务。"""
    tier = story.get("story_tier") or (story.get("recognition") or {}).get("tier") or "none"
    if tier == "none":
        return []

    recognition = story.get("recognition") or {}
    beats = recognition.get("beats") or {}
    reason = story.get("no_story_reason") or recognition.get("reason") or ""
    duration = duration_sec if duration_sec is not None else story.get("duration_sec")
    duration_f = float(duration) if duration not in (None, "") else None
    index = build_event_index(story)
    steps = _comeback_score_steps(story)
    gaps: List[Dict[str, Any]] = []

    equalizer = steps["equalizer"]
    go_ahead = steps["go_ahead"]
    behind = steps["behind_start"]
    eq_t = float(equalizer["t_sec"]) if equalizer else None
    ahead_t = float(go_ahead["t_sec"]) if go_ahead else None
    behind_t = float(behind["t_sec"]) if behind else 0.0

    # --- 铺垫：整段落后→扳平 的候选搜索区间，不用单点短窗 ---
    if not beats.get("铺垫"):
        t0 = 0.0 if behind and behind.get("opening") else max(0.0, behind_t - 30.0)
        t1 = eq_t if eq_t is not None else (ahead_t if ahead_t is not None else behind_t + _CHUNK_SEC)
        intervals = _split_search_intervals(t0, t1)
        seeds = []
        for t in _attempt_times_in(index, t0, t1)[:3]:
            window, meta = _clip_window(t - 2.0, t + _ACTION_PAD, duration=duration_f)
            if window and not meta["oob"]:
                seeds.append({**window, **meta})
        gaps.append(
            {
                "gap_id": "missing_setup_visual",
                "kind": "setup",
                "priority": 1,
                "tool_hint": "coarse_search_interval",
                "registerable": True,
                "search_intervals": intervals,
                "seed_windows": seeds,
                "score_anchor_sec": behind_t,
                "goal_anchor_sec": None,
                "anchor_status": "needs_search",
                "adaptive_expand": True,
                "note": (
                    f"铺垫缺失（reason={reason or 'empty_beat'}）；"
                    f"在 [{t0:.1f},{t1:.1f}] 按事件索引分段搜索失球/扑救/门线，禁止只扫首次比分旁短窗"
                ),
            }
        )

    # --- 蓄力：落后→反超 之间分段搜索 ---
    if not beats.get("蓄力"):
        t0 = behind_t
        t1 = ahead_t if ahead_t is not None else (eq_t + _CHUNK_SEC if eq_t is not None else behind_t + _CHUNK_SEC)
        intervals = _split_search_intervals(t0, t1)
        seeds = []
        for t in _attempt_times_in(index, t0, t1)[:4]:
            window, meta = _clip_window(t - 2.0, t + _ACTION_PAD, duration=duration_f)
            if window and not meta["oob"]:
                seeds.append({**window, **meta})
        gaps.append(
            {
                "gap_id": "missing_buildup_visual",
                "kind": "buildup",
                "priority": 2,
                "tool_hint": "coarse_search_interval",
                "registerable": True,
                "search_intervals": intervals,
                "seed_windows": seeds,
                "score_anchor_sec": None,
                "goal_anchor_sec": None,
                "anchor_status": "needs_search",
                "adaptive_expand": True,
                "note": f"蓄力缺失；在 [{t0:.1f},{t1:.1f}] 分段搜索射门/任意球/角球，禁止只用时间中点单窗",
            }
        )

    # --- 扳平/反超：OCR 用 score_path；动作检查用进球锚点 ---
    for label, role, node in (
        ("equalizer", "转折", equalizer),
        ("go_ahead", "高潮", go_ahead),
    ):
        if node is None:
            continue
        score_t = float(node["t_sec"])
        goal_t = _goal_anchor_near(index, score_t, role=role)

        ocr_window, ocr_meta = _clip_window(
            score_t - _OCR_PAD_BEFORE,
            score_t + _OCR_PAD_AFTER,
            duration=duration_f,
        )
        if ocr_window and not ocr_meta["oob"]:
            gaps.append(
                {
                    "gap_id": f"verify_{label}_scoreboard",
                    "kind": "scoreboard",
                    "priority": 3,
                    "tool_hint": "read_scoreboard_window",
                    "registerable": True,
                    "search_intervals": [
                        {
                            "start": ocr_window["start"],
                            "end": ocr_window["end"],
                            "expand_level": 0,
                            "expand_policy": "widen_by_4s_on_miss",
                        }
                    ],
                    "seed_windows": [ocr_window],
                    "score_anchor_sec": score_t,
                    "goal_anchor_sec": goal_t,
                    "anchor_status": "score_path",
                    "adaptive_expand": True,
                    "window_meta": ocr_meta,
                    "note": f"OCR 核实{role}记分牌，锚点取 score_path t={score_t:.1f}s（非进球动作时刻）",
                }
            )

        if goal_t is None:
            gaps.append(
                {
                    "gap_id": f"locate_{label}_goal_action",
                    "kind": "action_locate",
                    "priority": 3,
                    "tool_hint": "coarse_search_interval",
                    "registerable": True,
                    "search_intervals": _split_search_intervals(
                        max(0.0, score_t - _GOAL_MATCH_SLACK),
                        score_t + 30.0,
                        chunk=30.0,
                    ),
                    "seed_windows": [],
                    "score_anchor_sec": score_t,
                    "goal_anchor_sec": None,
                    "anchor_status": "pending_localization",
                    "adaptive_expand": True,
                    "note": f"{role}缺少可靠进球事件锚点；先在比分确认前定位进球动作，不得用 score_path 时刻冒充进球",
                }
            )
        else:
            action_window, action_meta = _clip_window(
                goal_t - 2.0,
                goal_t + _ACTION_PAD,
                duration=duration_f,
            )
            if action_window and not action_meta["oob"]:
                gaps.append(
                    {
                        "gap_id": f"verify_{label}_goal_action",
                        "kind": "action_verify",
                        "priority": 3,
                        "tool_hint": "inspect_story_window",
                        "registerable": True,
                        "search_intervals": [
                            {
                                "start": action_window["start"],
                                "end": action_window["end"],
                                "expand_level": 0,
                                "expand_policy": "widen_by_4s_on_miss",
                            }
                        ],
                        "seed_windows": [action_window],
                        "score_anchor_sec": score_t,
                        "goal_anchor_sec": goal_t,
                        "anchor_status": "goal_event",
                        "adaptive_expand": True,
                        "window_meta": action_meta,
                        "note": (
                            f"{role}动作检查使用进球锚点 t={goal_t:.1f}s；"
                            f"比分确认 t={score_t:.1f}s 仅用于 OCR"
                        ),
                    }
                )

    if go_ahead is not None:
        score_t = float(go_ahead["t_sec"])
        goal_t = _goal_anchor_near(index, score_t, role="高潮")
        anchor = goal_t if goal_t is not None else score_t
        status = "goal_event" if goal_t is not None else "score_fallback_pending"
        react_window, react_meta = _clip_window(anchor, anchor + 16.0, duration=duration_f)
        if react_window and not react_meta["oob"]:
            gaps.append(
                {
                    "gap_id": "post_climax_reaction",
                    "kind": "reaction",
                    "priority": 4,
                    "tool_hint": "scan_reaction_window",
                    "registerable": True,
                    "search_intervals": [
                        {
                            "start": react_window["start"],
                            "end": react_window["end"],
                            "expand_level": 0,
                            "expand_policy": "extend_to_32s_on_miss",
                        }
                    ],
                    "seed_windows": [react_window],
                    "score_anchor_sec": score_t,
                    "goal_anchor_sec": goal_t,
                    "anchor_status": status,
                    "adaptive_expand": True,
                    "window_meta": react_meta,
                    "note": "高潮后反应/庆祝候选；优先接在进球锚点之后",
                }
            )

    gaps.sort(key=lambda row: (int(row["priority"]), str(row["gap_id"])))
    return gaps


def build_agent_item(
    story: Dict[str, Any],
    *,
    video_path: Optional[str] = None,
    duration_sec: Optional[float] = None,
) -> Dict[str, Any]:
    duration = duration_sec
    if duration is None:
        duration = story.get("duration_sec")
    duration_f = float(duration or 0.0)
    gaps = detect_gaps(story, duration_sec=duration_f if duration_f > 0 else None)
    return {
        "match_id": story.get("match_id") or "",
        "video_name": story.get("video_name") or "",
        "video_path": video_path or "",
        "duration": duration_f,
        "duration_sec": duration_f,
        "duration_known": duration_f > 0,
        "story_tier": story.get("story_tier"),
        "has_story": bool(story.get("has_story")),
        "is_candidate": bool(story.get("is_candidate")),
        "story_label_zh": story.get("story_label_zh") or "",
        "no_story_reason": story.get("no_story_reason") or "",
        "protagonist_side": story.get("protagonist_side"),
        "score_path": story.get("score_path") or [],
        "recognition": story.get("recognition") or {},
        "events": story.get("events") or [],
        "event_index": build_event_index(story),
        "gaps": gaps,
        "template_id": "T01_comeback",
        "goal": "plan_evidence_tasks",
    }


_ALLOWED_SCHEMAS = frozenset(
    {
        "story-video-agent-plan-1.5",
        "story-video-agent-plan-2a",
        "story-video-agent-plan-2b",
    }
)


def validate_plan_payload(payload: Dict[str, Any]) -> List[str]:
    """结构 + 语义校验。空列表表示合法。"""
    problems: List[str] = []
    required = [
        "schema_version",
        "algorithm",
        "status",
        "match_id",
        "story_tier",
        "evidence_tasks",
        "gaps",
        "trace",
        "dry_run",
        "verification_complete",
    ]
    for key in required:
        if key not in payload:
            problems.append(f"missing:{key}")
    if payload.get("schema_version") not in _ALLOWED_SCHEMAS:
        problems.append("bad_schema_version")

    tier = payload.get("story_tier")
    tasks = payload.get("evidence_tasks")
    gaps = payload.get("gaps")
    if not isinstance(tasks, list):
        problems.append("evidence_tasks_not_list")
        return problems
    if not isinstance(gaps, list):
        problems.append("gaps_not_list")
        return problems

    if tier == "none" and tasks:
        problems.append("none_must_not_emit_story_tasks")
    if tier == "none" and gaps:
        problems.append("none_must_not_emit_gaps")

    media_only = bool(payload.get("media_only"))
    perception = bool(payload.get("perception"))
    if payload.get("dry_run") and payload.get("verification_complete") is True:
        problems.append("dry_run_cannot_claim_verification_complete")
    if media_only and payload.get("verification_complete") is True:
        problems.append("media_only_cannot_claim_verification_complete")
    if perception and payload.get("verification_complete") is True:
        problems.append("perception_cannot_claim_verification_complete")
    if media_only and payload.get("dry_run") is True:
        problems.append("media_only_and_dry_run_conflict")
    if perception and payload.get("dry_run") is True:
        problems.append("perception_and_dry_run_conflict")

    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            problems.append(f"task[{index}]_not_object")
            continue
        for key in ("task_id", "gap_id", "tool_hint", "status", "anchor_status"):
            if key not in task:
                problems.append(f"task[{index}]_missing_{key}")
        status = task.get("status")
        if status not in _TASK_STATUSES:
            problems.append(f"task[{index}]_bad_status")
        if payload.get("dry_run") and status == "verified":
            problems.append(f"task[{index}]_dry_run_verified_forbidden")
        if media_only and status == "verified":
            problems.append(f"task[{index}]_media_only_verified_forbidden")
        if perception and status == "verified":
            problems.append(f"task[{index}]_perception_verified_forbidden")
        if status == "observed" and not (task.get("visual_evidence") or task.get("frames")):
            problems.append(f"task[{index}]_observed_without_evidence")

        kind = task.get("kind")
        if kind == "scoreboard" and task.get("anchor_status") not in ("score_path",):
            problems.append(f"task[{index}]_scoreboard_needs_score_path_anchor")
        if kind == "action_verify" and task.get("goal_anchor_sec") is None:
            problems.append(f"task[{index}]_action_verify_missing_goal_anchor")
        if kind == "action_locate" and task.get("anchor_status") != "pending_localization":
            problems.append(f"task[{index}]_action_locate_bad_anchor_status")

        intervals = task.get("search_intervals")
        if not isinstance(intervals, list) or not intervals:
            problems.append(f"task[{index}]_missing_search_intervals")
        else:
            for j, interval in enumerate(intervals):
                if not isinstance(interval, dict):
                    problems.append(f"task[{index}]_interval[{j}]_bad")
                    continue
                if float(interval.get("end", 0)) <= float(interval.get("start", 0)):
                    problems.append(f"task[{index}]_interval[{j}]_oob")

        if task.get("window") is not None:
            window = task["window"]
            if not isinstance(window, dict) or "start" not in window or "end" not in window:
                problems.append(f"task[{index}]_bad_window")
            elif float(window["end"]) <= float(window["start"]):
                problems.append(f"task[{index}]_window_oob")

    if payload.get("status") == "budget_exhausted":
        for index, task in enumerate(tasks):
            if isinstance(task, dict) and task.get("status") in ("pending", "running"):
                problems.append(f"task[{index}]_budget_exhausted_still_open")
        if payload.get("verification_complete") is True:
            problems.append("budget_exhausted_cannot_be_verification_complete")

    return problems
