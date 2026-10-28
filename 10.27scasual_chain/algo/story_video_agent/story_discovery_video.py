"""P2: T01 story discovery from video-only score timeline.

Consumes ScoreNode path / score_timeline.json — never events/causal JSON.
Score-level discovery ≠ semantically verified story.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from story_chain.score_path import ScoreNode, find_comeback_arc, parse_score

PathLike = Union[str, Path]

# Search windows around scoreboard confirmation (media PTS), not goal action time.
_OPENING_PRE = 45.0
_OPENING_POST = 15.0
_GOAL_PRE = 90.0
_GOAL_POST = 30.0
_BUILDUP_PRE = 120.0
_ENDING_POST = 90.0


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


def _fmt(score: tuple) -> str:
    return f"{score[0]}:{score[1]}"


def _search_range(center: float, pre: float, post: float, duration: Optional[float]) -> Dict[str, float]:
    start = max(0.0, center - pre)
    end = center + post
    if duration is not None:
        end = min(duration, end)
    return {"media_start_sec": round(start, 3), "media_end_sec": round(end, 3), "anchor_sec": round(center, 3)}


def _task(
    task_id: str,
    *,
    why: str,
    search: Dict[str, float],
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
) -> List[Dict[str, Any]]:
    protagonist = arc["protagonist_side"]
    opponent = "right" if protagonist == "left" else "left"
    spell: List[ScoreNode] = list(arc["spell"])
    equalizer: ScoreNode = arc["equalizer"]
    go_ahead: ScoreNode = arc["go_ahead"]
    extras: List[ScoreNode] = list(arc.get("extras") or [])

    # first deficit transition inside spell (opponent opening / deepening)
    deficit_nodes = [n for n in spell if n.delta_side == opponent]
    opening_concede = deficit_nodes[0] if deficit_nodes else spell[0]

    tasks: List[Dict[str, Any]] = [
        _task(
            "locate_opponent_opening_goal",
            why="Confirm the live goal that put the protagonist behind (scoreboard lag ≠ action time).",
            search=_search_range(opening_concede.t_sec, _OPENING_PRE, _OPENING_POST, duration_sec),
            expected=["live_goal", "shot_on_target", "net_or_celebration", "not_replay_only"],
            required=True,
            budget_hint="coarse 8s → refine 2s; stop after live goal + scoreboard consistency",
            stop_when="live goal clip linked to this score step OR window exhausted unresolved",
        ),
        _task(
            "locate_equalizer_goal",
            why="Locate protagonist equalizer that ends the deficit spell.",
            search=_search_range(equalizer.t_sec, _GOAL_PRE, _GOAL_POST, duration_sec),
            expected=["live_goal", "shot", "buildup_cross_or_pass", "celebration"],
            required=True,
            budget_hint="coarse around scoreboard confirm; prefer action before OCR confirm",
            stop_when="live equalizer verified or unresolved after refine",
        ),
        _task(
            "locate_go_ahead_goal",
            why="Locate go-ahead goal that completes the T01 comeback arc.",
            search=_search_range(go_ahead.t_sec, _GOAL_PRE, _GOAL_POST, duration_sec),
            expected=["live_goal", "shot", "local_causal_candidates"],
            required=True,
            budget_hint="same as equalizer; mandatory for story grade",
            stop_when="live go-ahead verified or unresolved",
        ),
        _task(
            "find_relevant_buildup",
            why="Optional narrative context before equalizer (not full 18-class chain).",
            search=_search_range(equalizer.t_sec, _BUILDUP_PRE, 5.0, duration_sec),
            expected=["dangerous_attack", "key_pass_or_cross", "shot_attempt"],
            required=False,
            budget_hint="single coarse pass; abort if no danger cues",
            stop_when="one usable buildup window or none",
        ),
        _task(
            "verify_story_ending",
            why="Confirm final lead holds / match end context for wrap title.",
            search=_search_range(
                path[-1].t_sec if path else go_ahead.t_sec,
                30.0,
                _ENDING_POST,
                duration_sec,
            ),
            expected=["final_scoreboard", "match_end_or_stable_lead"],
            required=False,
            budget_hint="sparse scoreboard checks only",
            stop_when="final score consistent with path[-1]",
        ),
    ]
    for i, ex in enumerate(extras):
        tasks.append(
            _task(
                f"locate_lead_extension_goal_{i+1}",
                why="Optional lead-extension goal after go-ahead for narrative punch.",
                search=_search_range(ex.t_sec, _GOAL_PRE, _GOAL_POST, duration_sec),
                expected=["live_goal", "celebration"],
                required=False,
                budget_hint="only if story packaging requests extra beat",
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
    teams = teams_hypothesis or {"left": None, "right": None, "status": "unresolved"}

    base: Dict[str, Any] = {
        "schema": "video_driven_story_discovery_v1",
        "story_type": "T01_comeback",
        "grade": "none",
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
        "notes": [
            "grade=story means score-path supports T01; evidence still required for semantic_verified",
            "media PTS anchors are scoreboard confirmation times, not goal action times",
        ],
    }

    if len(path) < 2:
        base["grade"] = "none"
        base["hypotheses"].append({"id": "insufficient_score_path", "status": "blocked"})
        return base

    arc = find_comeback_arc(path)
    if arc is None:
        # candidate: any lead change / deficit without full equalizer+go_ahead
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
                    "detail": "final lead after deficit but equalizer/go_ahead not both committed on path",
                }
            )
        else:
            base["grade"] = "none"
            base["hypotheses"].append({"id": "no_comeback_arc", "status": "rejected"})
        return base

    protagonist = arc["protagonist_side"]
    base["grade"] = "story" if not degraded else "candidate"
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
            "equalizer": _search_range(arc["equalizer"].t_sec, _GOAL_PRE, _GOAL_POST, duration),
            "go_ahead": _search_range(arc["go_ahead"].t_sec, _GOAL_PRE, _GOAL_POST, duration),
        },
    }
    base["hypotheses"].append(
        {
            "id": "t01_last_deficit_comeback",
            "status": "score_supported",
            "detail": f"path supports comeback for {protagonist}; awaiting video evidence tasks",
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
        # rebuild arc objects for task builder
        from story_chain.score_path import find_comeback_arc as _fca

        arc = _fca(path)
        if arc:
            tasks = build_evidence_tasks(arc, path, duration_sec=timeline.get("duration_sec"))
    elif discovery["grade"] == "candidate":
        # minimal tasks: verify final score transitions only
        if len(path) >= 2:
            tasks = [
                _task(
                    "verify_score_path_nodes",
                    why="Candidate path incomplete; re-check scoreboard around each committed node.",
                    search=_search_range(path[-1].t_sec, 60.0, 30.0, timeline.get("duration_sec")),
                    expected=["scoreboard_consistency"],
                    required=True,
                    budget_hint="sparse OCR densify only",
                    stop_when="path confirmed or conflict",
                )
            ]

    bundle = {
        "schema": "video_driven_story_evidence_tasks_v1",
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
