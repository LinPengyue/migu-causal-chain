"""Generic T01 EDL composer — variable N goals, no Croatia hardcoding.

Two levels:
  - structure_only: score/event/predicted-strip placeholders; never verified_first_live
  - video_verified: only segments with complete live shot/net evidence

Never sets render_ready=True. Refuses R2.6–R2.9 Croatia builders.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


CROATIA_EDL_MODULES = (
    "v2_strip_guided_r2_6_build_edl",
    "v2_strip_guided_r2_8_build_edl",
    "v2_strip_guided_r2_9_build_edl",
)

ROLE_ORDER = ("opening_deficit", "equalizer", "go_ahead", "extend", "buildup", "resolution")


class GenericEdlError(ValueError):
    pass


def refuse_croatia_edl_builder(module_name: str, *, match_id: str) -> None:
    mid = str(match_id or "").lower()
    croatia_like = ("克罗地亚" in str(match_id)) or ("canada" in mid) or ("croatia" in mid)
    if module_name in CROATIA_EDL_MODULES and not croatia_like:
        raise GenericEdlError(
            f"refusing Croatia-only EDL builder {module_name} for match_id={match_id!r}"
        )


def _team_title(team_names: Optional[Dict[str, str]]) -> str:
    tn = team_names or {}
    left = tn.get("team_1") or tn.get("left") or "主队"
    right = tn.get("team_2") or tn.get("right") or "客队"
    if left == "主队" and right == "客队":
        return "逆风翻盘（队名未知）"
    return f"{left} vs {right} — 逆风翻盘"


def _arc_goal_slots(selected_arc: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not selected_arc:
        return []
    slots = [
        {
            "role": "opening_deficit",
            "score_before": None,
            "score_after": selected_arc.get("deficit_score"),
            "score_confirmation_sec": (selected_arc.get("score_confirmation_sec") or {}).get("deficit"),
            "goal_action_sec": (selected_arc.get("goal_action_sec") or {}).get("deficit"),
        },
        {
            "role": "equalizer",
            "score_before": selected_arc.get("deficit_score"),
            "score_after": selected_arc.get("equalizer_score"),
            "score_confirmation_sec": (selected_arc.get("score_confirmation_sec") or {}).get("equalizer"),
            "goal_action_sec": (selected_arc.get("goal_action_sec") or {}).get("equalizer"),
        },
        {
            "role": "go_ahead",
            "score_before": selected_arc.get("equalizer_score"),
            "score_after": selected_arc.get("go_ahead_score"),
            "score_confirmation_sec": (selected_arc.get("score_confirmation_sec") or {}).get("go_ahead"),
            "goal_action_sec": (selected_arc.get("goal_action_sec") or {}).get("go_ahead"),
        },
    ]
    return slots


def _verification_level(
    goal: Optional[Dict[str, Any]],
    *,
    expected_identity: Optional[Dict[str, str]] = None,
    video_duration_sec: Optional[float] = None,
) -> str:
    """Fail closed via v2_video_evidence_gate — status strings alone never upgrade."""
    from story_video_agent.v2_video_evidence_gate import verification_level_for_edl

    return verification_level_for_edl(
        goal,
        expected_identity=expected_identity,
        video_duration_sec=video_duration_sec,
    )


def compose_generic_t01_edl(
    *,
    match_id: str,
    selected_arc: Optional[Dict[str, Any]],
    arc_status: str,
    team_names: Optional[Dict[str, str]] = None,
    goals: Optional[Sequence[Dict[str, Any]]] = None,
    context_nodes: Optional[Sequence[Dict[str, Any]]] = None,
    video_duration_sec: Optional[float] = None,
    level: str = "structure_only",
    expected_identity: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Build candidate EDL. level=structure_only|video_verified."""
    if level not in ("structure_only", "video_verified"):
        raise GenericEdlError(f"unknown edl level: {level}")

    if arc_status in ("no_comeback",) or not selected_arc:
        return {
            "schema": "v2_generic_t01_edl_v1",
            "match_id": match_id,
            "level": level,
            "status": arc_status or "no_comeback",
            "title_text": _team_title(team_names),
            "segments": [],
            "note": "No T01 comeback EDL generated",
            "render_ready": False,
            "verified_first_live": False,
        }

    goals = list(goals or [])
    goal_by_role = {str(g.get("role")): g for g in goals if g.get("role")}
    segments: List[Dict[str, Any]] = []
    play = 0.0

    title = _team_title(team_names)
    segments.append(
        {
            "segment_id": "title_open",
            "role": "title_card",
            "beat": "setup",
            "duration_sec": 2.5,
            "story_play_in": 0.0,
            "story_play_out": 2.5,
            "title_text": title,
            "render_eligibility": "placeholder_title",
            "render_ready": False,
        }
    )
    play = 2.5

    unresolved_roles: List[str] = []
    for slot in _arc_goal_slots(selected_arc):
        role = slot["role"]
        g = goal_by_role.get(role)
        vlevel = _verification_level(
            g, expected_identity=expected_identity, video_duration_sec=video_duration_sec
        )
        conf_t = slot.get("score_confirmation_sec")
        action_t = None if g is None else g.get("goal_action_sec", g.get("net_sec") or g.get("shot_sec"))
        if action_t is None:
            action_t = slot.get("goal_action_sec")

        if level == "video_verified":
            if vlevel != "video_verified":
                unresolved_roles.append(role)
                segments.append(
                    {
                        "segment_id": f"edl_{role}_unresolved",
                        "role": role,
                        "beat": role,
                        "verification_level": vlevel,
                        "verification_status": "unresolved",
                        "score_before": slot.get("score_before"),
                        "score_after": slot.get("score_after"),
                        "score_confirmation_sec": conf_t,
                        "goal_action_sec": None,
                        "note": "Missing video-verified shot/net/live evidence",
                        "render_eligibility": "blocked_unresolved",
                        "render_ready": False,
                    }
                )
                continue
            tin = float(g["media_in"])
            tout = float(g["media_out"])
            if video_duration_sec is not None and (tin < 0 or tout > float(video_duration_sec) + 1e-3):
                raise GenericEdlError(f"PTS out of range for {role}: {tin}-{tout} vs dur={video_duration_sec}")
            dur = tout - tin
            segments.append(
                {
                    "segment_id": f"edl_{role}",
                    "role": role,
                    "beat": role,
                    "media_in": round(tin, 3),
                    "media_out": round(tout, 3),
                    "duration_sec": round(dur, 3),
                    "story_play_in": round(play, 3),
                    "story_play_out": round(play + dur, 3),
                    "score_before": slot.get("score_before"),
                    "score_after": slot.get("score_after"),
                    "shot_sec": g.get("shot_sec"),
                    "net_sec": g.get("net_sec"),
                    "verification_level": "video_verified",
                    "verification_status": "verified_first_live",
                    "live_or_replay": "live",
                    "source_node_ids": list(g.get("source_node_ids") or []),
                    "render_eligibility": "candidate",
                    "render_ready": False,
                }
            )
            play += dur
            continue

        # structure_only: placeholder search window around score confirmation
        unresolved_roles.append(role)
        window = None
        if conf_t is not None:
            t = float(conf_t)
            window = {
                "search_start_sec": round(max(0.0, t - 90.0), 3),
                "search_end_sec": round(t + 5.0, 3),
                "anchor": "score_confirmation_sec",
            }
        segments.append(
            {
                "segment_id": f"edl_{role}_structure",
                "role": role,
                "beat": role,
                "verification_level": vlevel,
                "verification_status": "unresolved",
                "score_before": slot.get("score_before"),
                "score_after": slot.get("score_after"),
                "score_confirmation_sec": conf_t,
                "goal_action_sec": None,
                "placeholder_search_window": window,
                "nearby_predicted_strip_ids": list((g or {}).get("nearby_predicted_strip_ids") or []),
                "note": (
                    "structure_only placeholder — not first-live verified; "
                    "do not render as completed goal segment"
                ),
                "render_eligibility": "structure_placeholder",
                "verified_first_live": False,
                "render_ready": False,
            }
        )

    # Optional non-goal context (never force-fill)
    for i, node in enumerate(context_nodes or []):
        if not node.get("include"):
            continue
        segments.append(
            {
                "segment_id": f"edl_context_{i}",
                "role": str(node.get("role") or "buildup"),
                "beat": "buildup",
                "media_in": node.get("media_in"),
                "media_out": node.get("media_out"),
                "source_node_ids": list(node.get("source_node_ids") or []),
                "verification_level": "predicted_strip_candidate",
                "render_eligibility": "optional_context",
                "render_ready": False,
            }
        )

    n_goal_slots = 3
    return {
        "schema": "v2_generic_t01_edl_v1",
        "match_id": match_id,
        "level": level,
        "status": arc_status,
        "title_text": title,
        "protagonist_side": selected_arc.get("protagonist_side"),
        "protagonist_team_name": selected_arc.get("protagonist_team_name"),
        "selected_arc_scores": {
            "deficit": selected_arc.get("deficit_score"),
            "equalizer": selected_arc.get("equalizer_score"),
            "go_ahead": selected_arc.get("go_ahead_score"),
        },
        "n_arc_goal_slots": n_goal_slots,
        "n_video_verified_goals": sum(
            1 for s in segments if s.get("verification_status") == "verified_first_live"
        ),
        "unresolved_roles": unresolved_roles,
        "segments": segments,
        "story_play_duration_sec": round(play, 3),
        "verified_first_live": False,
        "all_five_goals_verified_first_live": False,
        "note": (
            "Generic N-goal T01 composer; narrative roles ≠ fixed five segments; "
            "structure_only never claims verified_first_live"
        ),
        "render_ready": False,
    }
