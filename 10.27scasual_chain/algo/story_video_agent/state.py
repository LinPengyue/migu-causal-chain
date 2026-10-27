"""从 T01 故事 JSON 构建 Video Agent 初始状态与证据缺口。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

PathLike = Union[str, Path]

_ROLE_BEATS = ("铺垫", "蓄力", "转折", "高潮", "收尾")
_WINDOW = 8.0


def load_t01_story(path: PathLike) -> Dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("T01 story JSON must be an object")
    return data


def _role_times(story: Dict[str, Any]) -> Dict[str, List[float]]:
    times: Dict[str, List[float]] = {role: [] for role in _ROLE_BEATS}
    for event in story.get("events") or []:
        role = event.get("story_role")
        if role not in times:
            continue
        t_ms = event.get("t_ms")
        if t_ms is None:
            continue
        times[role].append(float(t_ms) / 1000.0)
    return times


def _score_nodes(story: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [node for node in (story.get("score_path") or []) if isinstance(node, dict)]


def detect_gaps(story: Dict[str, Any]) -> List[Dict[str, Any]]:
    """相对 T01 故事状态，列出可用视频工具补的证据缺口。不改故事识别结论。"""
    gaps: List[Dict[str, Any]] = []
    recognition = story.get("recognition") or {}
    beats = recognition.get("beats") or {}
    role_times = _role_times(story)
    score_nodes = _score_nodes(story)
    reason = story.get("no_story_reason") or recognition.get("reason") or ""
    tier = story.get("story_tier") or recognition.get("tier") or "none"

    if tier == "none":
        gaps.append(
            {
                "gap_id": "no_t01_arc",
                "kind": "no_story",
                "priority": 0,
                "tool_hint": "inspect_story_window",
                "start": 0.0,
                "end": min(_WINDOW, float(story.get("duration_sec") or _WINDOW)),
                "note": "T01 未识别出翻盘弧，Video Agent 不强制补故事",
            }
        )
        return gaps

    if not beats.get("铺垫") and not role_times["铺垫"]:
        t0 = float(score_nodes[0]["t_sec"]) if score_nodes else 0.0
        gaps.append(
            {
                "gap_id": "missing_setup_visual",
                "kind": "setup",
                "priority": 1,
                "tool_hint": "inspect_story_window",
                "start": max(0.0, t0 - 2.0),
                "end": t0 + _WINDOW,
                "note": f"铺垫缺失（reason={reason or 'empty_beat'}）；需短窗确认失球/扑救/门线画面",
            }
        )

    if not beats.get("蓄力") and not role_times["蓄力"]:
        # 蓄力窗取落后到反超之间的中段
        starts = [float(n["t_sec"]) for n in score_nodes if not n.get("opening")]
        mid = starts[0] if starts else 0.0
        if len(starts) >= 2:
            mid = (starts[0] + starts[-1]) / 2.0
        gaps.append(
            {
                "gap_id": "missing_buildup_visual",
                "kind": "buildup",
                "priority": 2,
                "tool_hint": "inspect_story_window",
                "start": max(0.0, mid - _WINDOW / 2),
                "end": mid + _WINDOW / 2,
                "note": "蓄力缺失；需确认射门/任意球/角球尝试镜头",
            }
        )

    for label, beat_key, tool_hint in (
        ("equalizer", "转折", "read_scoreboard_window"),
        ("go_ahead", "高潮", "read_scoreboard_window"),
    ):
        times = role_times.get(beat_key) or []
        if not times and beats.get(beat_key):
            # recognition 有 id 但 events 可能未展开时间：退回 score_path 非 opening 节点
            times = [float(n["t_sec"]) for n in score_nodes if not n.get("opening")][:1]
        if not times:
            continue
        t = times[0]
        gaps.append(
            {
                "gap_id": f"verify_{label}_scoreboard",
                "kind": "scoreboard",
                "priority": 3,
                "tool_hint": tool_hint,
                "start": max(0.0, t - 2.0),
                "end": t + 6.0,
                "note": f"核实{beat_key}附近记分牌是否与 score_path 一致",
            }
        )

    climax_times = role_times.get("高潮") or []
    if climax_times:
        t = climax_times[-1]
        gaps.append(
            {
                "gap_id": "post_climax_reaction",
                "kind": "reaction",
                "priority": 4,
                "tool_hint": "scan_reaction_window",
                "start": t,
                "end": t + 16.0,
                "note": "高潮后反应/庆祝镜头候选（规则层无此标注，交视频工具补）",
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
    """构造 Agent 循环使用的 item（不含 LLM 服务依赖）。"""
    duration = duration_sec
    if duration is None:
        duration = story.get("duration_sec")
    gaps = detect_gaps(story)
    return {
        "match_id": story.get("match_id") or "",
        "video_name": story.get("video_name") or "",
        "video_path": video_path or "",
        "duration": float(duration or 0.0),
        "duration_sec": float(duration or 0.0),
        "story_tier": story.get("story_tier"),
        "has_story": bool(story.get("has_story")),
        "is_candidate": bool(story.get("is_candidate")),
        "story_label_zh": story.get("story_label_zh") or "",
        "no_story_reason": story.get("no_story_reason") or "",
        "protagonist_side": story.get("protagonist_side"),
        "score_path": story.get("score_path") or [],
        "recognition": story.get("recognition") or {},
        "events": story.get("events") or [],
        "gaps": gaps,
        "template_id": "T01_comeback",
        "goal": "plan_evidence_tasks",
    }


def validate_plan_payload(payload: Dict[str, Any]) -> List[str]:
    """返回结构问题列表；空列表表示合法。"""
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
    ]
    for key in required:
        if key not in payload:
            problems.append(f"missing:{key}")
    if payload.get("schema_version") != "story-video-agent-plan-1":
        problems.append("bad_schema_version")
    if not isinstance(payload.get("evidence_tasks"), list):
        problems.append("evidence_tasks_not_list")
    else:
        for index, task in enumerate(payload["evidence_tasks"]):
            if not isinstance(task, dict):
                problems.append(f"task[{index}]_not_object")
                continue
            for key in ("task_id", "gap_id", "tool_hint", "window", "status"):
                if key not in task:
                    problems.append(f"task[{index}]_missing_{key}")
            window = task.get("window") or {}
            if not isinstance(window, dict) or "start" not in window or "end" not in window:
                problems.append(f"task[{index}]_bad_window")
    return problems
