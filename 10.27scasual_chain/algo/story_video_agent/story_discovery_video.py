"""P2: T01 story discovery from video-only score timeline.

Consumes score_timeline — never events/causal JSON.
Distinguishes no_comeback vs unresolved vs candidate/story.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from story_chain.score_path import ScoreNode, find_comeback_arc, parse_score

PathLike = Union[str, Path]

# Soft defaults only — actual windows come from adjacent stable intervals.
_DEFAULT_PRE = 90.0
_DEFAULT_POST = 30.0
_EXPAND_PAD = 30.0


def nodes_from_timeline(timeline: Dict[str, Any]) -> List[ScoreNode]:
    nodes: List[ScoreNode] = []
    for raw in timeline.get("nodes") or []:
        score = parse_score(raw.get("score"))
        if score is None and isinstance(raw.get("score"), (list, tuple)) and len(raw["score"]) == 2:
            score = (int(raw["score"][0]), int(raw["score"][1]))
        if score is None:
            continue
        nodes.append(
            ScoreNode(
                t_sec=float(raw["t_sec"]),
                score=score,
                opening=bool(raw.get("opening")),
                delta_side=raw.get("delta_side"),
                carrier_event_id=raw.get("carrier_event_id"),
            )
        )
    nodes.sort(key=lambda n: n.t_sec)
    return nodes


def _clip(v: float, duration: Optional[float]) -> float:
    v = max(0.0, v)
    if duration is not None:
        v = min(duration, v)
    return round(v, 3)


def dynamic_search_window(
    node: ScoreNode,
    path: Sequence[ScoreNode],
    *,
    duration_sec: Optional[float],
    prev_stable: Optional[ScoreNode] = None,
    next_stable: Optional[ScoreNode] = None,
    default_pre: float = _DEFAULT_PRE,
    default_post: float = _DEFAULT_POST,
) -> Dict[str, Any]:
    """Initial search suggestion from adjacent stable scores — not a hard bound.

    Prefer interval (prev_node.t, confirm_t + post]. Goal action is expected
    before scoreboard confirmation; window may extend back to previous stable.
    """
    idx = next((i for i, n in enumerate(path) if n.t_sec == node.t_sec and n.score == node.score), None)
    prev_n = prev_stable
    next_n = next_stable
    if idx is not None:
        if prev_n is None and idx > 0:
            prev_n = path[idx - 1]
        if next_n is None and idx + 1 < len(path):
            next_n = path[idx + 1]

    if prev_n is not None:
        # From previous stable (with pad) through confirmation — expandable later.
        start = max(0.0, prev_n.t_sec - _EXPAND_PAD)
    else:
        start = max(0.0, node.t_sec - default_pre)

    if next_n is not None:
        end = min(node.t_sec + default_post, next_n.t_sec)
    else:
        end = node.t_sec + default_post

    # observation interval hint for P3 expand
    obs_start = _clip(start, duration_sec)
    obs_end = _clip(end, duration_sec)
    return {
        "media_start_sec": obs_start,
        "media_end_sec": obs_end,
        "anchor_sec": round(node.t_sec, 3),
        "hard_bound": False,
        "expandable": True,
        "expand_policy": "if_unresolved_after_initial_pass_widen_toward_prev_stable_and_post_confirm",
        "prev_stable_sec": round(prev_n.t_sec, 3) if prev_n else None,
        "next_stable_sec": round(next_n.t_sec, 3) if next_n else None,
        "note": "scoreboard confirm lag; missing goal outside window ≠ absence",
    }


def _task(
    task_id: str,
    *,
    why: str,
    search: Dict[str, Any],
    expected: List[str],
    required: bool,
    budget_hint: str,
    stop_when: str,
) -> Dict[str, Any]:
    return {
        "task_id": task_id,
        "why": why,
        "search_media_range": search,
        "expected_actions_or_relations": expected,
        "required": required,
        "evidence_status": "missing",
        "existing_evidence": [],
        "retrieval_budget_hint": budget_hint,
        "stop_when": stop_when,
        "source": "score_timeline_hypothesis",
        "not_from_events_json": True,
    }


def build_evidence_tasks(
    arc: Dict[str, Any],
    path: Sequence[ScoreNode],
    *,
    duration_sec: Optional[float] = None,
    change_intervals: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    protagonist = arc["protagonist_side"]
    opponent = "right" if protagonist == "left" else "left"
    spell: List[ScoreNode] = list(arc["spell"])
    equalizer: ScoreNode = arc["equalizer"]
    go_ahead: ScoreNode = arc["go_ahead"]
    extras: List[ScoreNode] = list(arc.get("extras") or [])

    deficit_nodes = [n for n in spell if n.delta_side == opponent]
    opening_concede = deficit_nodes[0] if deficit_nodes else spell[0]

    def _win(node: ScoreNode) -> Dict[str, Any]:
        w = dynamic_search_window(node, path, duration_sec=duration_sec)
        # merge P1 change interval if provided
        if change_intervals:
            for iv in change_intervals:
                if abs(float(iv.get("t_sec", -1)) - node.t_sec) < 1.0:
                    w["p1_change_interval"] = iv
        return w

    tasks: List[Dict[str, Any]] = [
        _task(
            "locate_opponent_opening_goal",
            why="Confirm live goal that put protagonist behind (confirm time ≠ action time).",
            search=_win(opening_concede),
            expected=["live_goal", "shot_on_target", "net_or_celebration", "not_replay_only"],
            required=True,
            budget_hint="initial window then expand; never treat miss-in-window as absence",
            stop_when="live goal linked OR expanded budget exhausted → unresolved",
        ),
        _task(
            "locate_equalizer_goal",
            why="Locate protagonist equalizer ending deficit spell.",
            search=_win(equalizer),
            expected=["live_goal", "shot", "buildup_cross_or_pass", "celebration"],
            required=True,
            budget_hint="prefer action before OCR confirm; expand to prev stable if needed",
            stop_when="live equalizer verified or unresolved after expand",
        ),
        _task(
            "locate_go_ahead_goal",
            why="Locate go-ahead goal completing T01 arc.",
            search=_win(go_ahead),
            expected=["live_goal", "shot", "local_causal_candidates"],
            required=True,
            budget_hint="same as equalizer",
            stop_when="live go-ahead verified or unresolved",
        ),
        _task(
            "find_relevant_buildup",
            why="Optional narrative context before equalizer.",
            search=_win(equalizer),
            expected=["dangerous_attack", "key_pass_or_cross", "shot_attempt"],
            required=False,
            budget_hint="single coarse pass; abort if no danger cues",
            stop_when="one usable buildup window or none",
        ),
        _task(
            "verify_story_ending",
            why="Confirm final lead / wrap context.",
            search=dynamic_search_window(
                path[-1] if path else go_ahead,
                path,
                duration_sec=duration_sec,
                default_pre=30.0,
                default_post=90.0,
            ),
            expected=["final_scoreboard", "match_end_or_stable_lead"],
            required=False,
            budget_hint="sparse scoreboard checks",
            stop_when="final score consistent with path[-1]",
        ),
    ]
    for i, ex in enumerate(extras):
        tasks.append(
            _task(
                f"locate_lead_extension_goal_{i+1}",
                why="Optional lead-extension after go-ahead.",
                search=_win(ex),
                expected=["live_goal", "celebration"],
                required=False,
                budget_hint="optional beat",
                stop_when="clip found or skip",
            )
        )
    return tasks


def discover_t01_from_score_timeline(
    timeline: Dict[str, Any],
    *,
    teams_hypothesis: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    path = nodes_from_timeline(timeline)
    duration = timeline.get("duration_sec")
    degraded = bool(timeline.get("degraded"))
    path_meta = timeline.get("path_meta") or {}
    perception = timeline.get("perception_quality") or {}
    teams = teams_hypothesis or {"left": None, "right": None, "status": "unresolved"}

    base: Dict[str, Any] = {
        "schema": "video_driven_story_discovery_v2",
        "story_type": "T01_comeback",
        "grade": "unresolved",
        "protagonist_side": None,
        "opponent_side": None,
        "teams": teams,
        "score_path": [n.to_dict() for n in path],
        "last_deficit_arc": None,
        "key_nodes": {},
        "hypotheses": [],
        "semantic_verified": False,
        "score_level_only": True,
        "degraded_input": degraded,
        "perception_quality": perception,
        "notes": [
            "grade=story: score-path supports T01 (still needs video evidence)",
            "grade=none: sufficient path evidence against comeback",
            "grade=unresolved: perception insufficient — not the same as no_comeback",
        ],
    }

    # Perception gate: do not call insufficient evidence "none"
    if degraded or not path_meta.get("established", True) or len(path) < 2:
        usable = perception.get("usable_score_obs_rate")
        if usable is None:
            usable = (timeline.get("usable_ocr_count") or 0) / max(1, timeline.get("observation_count") or 1)
        if len(path) < 2 or degraded or usable < 0.15:
            base["grade"] = "unresolved"
            base["hypotheses"].append(
                {
                    "id": "perception_insufficient",
                    "status": "blocked",
                    "detail": {
                        "degraded": degraded,
                        "degrade_reasons": timeline.get("degrade_reasons"),
                        "n_nodes": len(path),
                        "usable_score_obs_rate": usable,
                    },
                }
            )
            return base

    arc = find_comeback_arc(path)
    if arc is None:
        final_leader = None
        last = path[-1].score
        if last[0] > last[1]:
            final_leader = "left"
        elif last[1] > last[0]:
            final_leader = "right"
        had_deficit = False
        if final_leader:
            for n in path:
                margin = (n.score[0] - n.score[1]) if final_leader == "left" else (n.score[1] - n.score[0])
                if margin < 0:
                    had_deficit = True
                    break
        if had_deficit:
            base["grade"] = "candidate"
            base["protagonist_side"] = final_leader
            base["opponent_side"] = "right" if final_leader == "left" else "left"
            base["hypotheses"].append(
                {
                    "id": "partial_comeback_path",
                    "status": "needs_evidence",
                    "detail": "final lead after deficit but equalizer/go_ahead not both on path",
                }
            )
        else:
            # enough established path, no deficit before final lead → true none
            if timeline.get("unresolved_transitions"):
                base["grade"] = "unresolved"
                base["hypotheses"].append({"id": "unresolved_score_jumps", "status": "blocked"})
            else:
                base["grade"] = "none"
                base["hypotheses"].append({"id": "no_comeback_arc", "status": "rejected"})
        return base

    protagonist = arc["protagonist_side"]
    base["grade"] = "candidate" if degraded else "story"
    base["protagonist_side"] = protagonist
    base["opponent_side"] = "right" if protagonist == "left" else "left"
    base["last_deficit_arc"] = {
        "spell": [n.to_dict() for n in arc["spell"]],
        "equalizer": arc["equalizer"].to_dict(),
        "go_ahead": arc["go_ahead"].to_dict(),
        "extras": [n.to_dict() for n in arc["extras"]],
    }
    base["key_nodes"] = {
        "equalizer": arc["equalizer"].to_dict(),
        "go_ahead": arc["go_ahead"].to_dict(),
        "extras": [n.to_dict() for n in arc["extras"]],
        "search_hints": {
            "equalizer": dynamic_search_window(arc["equalizer"], path, duration_sec=duration),
            "go_ahead": dynamic_search_window(arc["go_ahead"], path, duration_sec=duration),
        },
    }
    base["hypotheses"].append(
        {
            "id": "t01_last_deficit_comeback",
            "status": "score_supported",
            "detail": f"path supports comeback for {protagonist}; awaiting video evidence",
        }
    )
    return base


def discover_and_write(
    timeline: Dict[str, Any],
    out_dir: PathLike,
    *,
    teams_hypothesis: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    discovery = discover_t01_from_score_timeline(timeline, teams_hypothesis=teams_hypothesis)
    path = nodes_from_timeline(timeline)
    tasks: List[Dict[str, Any]] = []
    if discovery.get("last_deficit_arc") and discovery["grade"] in ("story", "candidate"):
        arc = find_comeback_arc(path)
        if arc:
            tasks = build_evidence_tasks(
                arc,
                path,
                duration_sec=timeline.get("duration_sec"),
                change_intervals=timeline.get("unresolved_transitions"),
            )
    elif discovery["grade"] == "unresolved":
        tasks = [
            _task(
                "improve_score_perception",
                why="P1 degraded/unestablished; densify OCR before story claims.",
                search={
                    "media_start_sec": 0.0,
                    "media_end_sec": float(timeline.get("duration_sec") or 0),
                    "hard_bound": False,
                    "expandable": True,
                },
                expected=["stable_scoreboard", "established_initial_score"],
                required=True,
                budget_hint="increase coarse budget / ROI track",
                stop_when="initial score established or budget exhausted",
            )
        ]

    bundle = {
        "schema": "video_driven_story_evidence_tasks_v2",
        "story_type": "T01_comeback",
        "discovery_grade": discovery["grade"],
        "semantic_verified": False,
        "tasks": tasks,
        "gates": {
            "no_events_json": True,
            "no_causal_json": True,
            "render_ready": False,
        },
    }
    (out / "story_discovery.json").write_text(
        json.dumps(discovery, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "story_evidence_tasks.json").write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"discovery": discovery, "evidence_tasks": bundle}
