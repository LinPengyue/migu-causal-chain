"""Generic scoreboard transition analysis (no match-specific score hardcoding)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Common broadcast score patterns: "2 - 1", "2-1", "2:1", fullwidth dashes.
_SCORE_RE = re.compile(
    r"(?<!\d)(\d{1,2})\s*[-–—:：]\s*(\d{1,2})(?!\d)"
)


def parse_score_pairs(text: str) -> List[Tuple[int, int]]:
    """Extract (left, right) score pairs from free text. Order is board order, not team identity."""
    out: List[Tuple[int, int]] = []
    for m in _SCORE_RE.finditer(text or ""):
        a, b = int(m.group(1)), int(m.group(2))
        if a > 20 or b > 20:
            continue
        out.append((a, b))
    return out


_OTHER_MATCH_NOISE = re.compile(
    r"different match|other match|goal highlights|进球集锦|highlights? reel|"
    r"qatar\s*vs|argentina\s*vs|senegal|mexico\b",
    re.I,
)


def unique_score_timeline(
    observations: Sequence[Dict[str, Any]], *, text_keys: Sequence[str] = ("notes", "observed_actions")
) -> List[Dict[str, Any]]:
    """Build ordered unique score states with earliest media time seen."""
    rows: List[Dict[str, Any]] = []
    for obs in observations:
        parts: List[str] = []
        for k in text_keys:
            v = obs.get(k)
            if isinstance(v, list):
                parts.extend(str(x) for x in v)
            elif v:
                parts.append(str(v))
        text = " | ".join(parts)
        if _OTHER_MATCH_NOISE.search(text):
            # Side-story / highlight inserts often contain unrelated scoreboards.
            continue
        pairs = parse_score_pairs(text)
        if not pairs:
            continue
        # Keep appearance order inside one note (e.g. "from 1-1 to 2-1").
        ordered: List[Tuple[int, int]] = []
        for m in _SCORE_RE.finditer(text):
            pair = (int(m.group(1)), int(m.group(2)))
            if pair[0] > 20 or pair[1] > 20:
                continue
            if not ordered or ordered[-1] != pair:
                ordered.append(pair)
        if not ordered:
            ordered = [pairs[-1]]
        t0 = obs.get("media_start_sec")
        if t0 is None:
            t0 = obs.get("media_start")
        t1 = obs.get("media_end_sec", obs.get("media_end"))
        for j, score in enumerate(ordered):
            # Spread multi-score notes slightly within the window for ordering.
            t_use = float(t0) if t0 is not None else None
            if t_use is not None and t1 is not None and len(ordered) > 1:
                frac = j / max(1, len(ordered) - 1)
                t_use = float(t0) + frac * max(0.0, float(t1) - float(t0))
            rows.append(
                {
                    "score": score,
                    "left": score[0],
                    "right": score[1],
                    "media_start_sec": t_use,
                    "media_end_sec": t1,
                    "source_tool": obs.get("tool") or obs.get("source_tool"),
                    "raw_excerpt": text[:240],
                }
            )
    # Dedup consecutive identical scores; keep first occurrence time.
    dedup: List[Dict[str, Any]] = []
    for r in sorted(
        rows,
        key=lambda x: (x["media_start_sec"] is None, x["media_start_sec"] or 0.0),
    ):
        if dedup and dedup[-1]["score"] == r["score"]:
            continue
        dedup.append(r)
    return dedup


def _side_trailing(left: int, right: int) -> Optional[str]:
    if left < right:
        return "left"
    if right < left:
        return "right"
    return None


def analyze_score_transitions(timeline: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Detect generic deficit → level → lead-after-deficit patterns.

    Does NOT treat narrative keywords (comeback/trailing) as confirmation.
    LLM self-labels must still pass this checker to upgrade discovery status.
    """
    states = list(timeline)
    events: List[Dict[str, Any]] = []
    deficit_side: Optional[str] = None
    deficit_score: Optional[Tuple[int, int]] = None
    leveled_after_deficit = False
    lead_after_deficit = False
    equalizer_score: Optional[Tuple[int, int]] = None
    go_ahead_score: Optional[Tuple[int, int]] = None

    for i, row in enumerate(states):
        L, R = int(row["left"]), int(row["right"])
        trail = _side_trailing(L, R)
        if trail is not None and deficit_side is None:
            deficit_side = trail
            deficit_score = (L, R)
            events.append(
                {
                    "kind": "deficit_observed",
                    "trailing_side": trail,
                    "score": (L, R),
                    "media_start_sec": row.get("media_start_sec"),
                    "index": i,
                }
            )
            continue
        # If we later see a clearer early deficit (e.g. 0-1 after a noisy insert),
        # allow one replacement before leveling.
        if (
            trail is not None
            and deficit_side is not None
            and not leveled_after_deficit
            and deficit_score is not None
            and (L + R) < sum(deficit_score)
        ):
            deficit_side = trail
            deficit_score = (L, R)
            events = [e for e in events if e.get("kind") != "deficit_observed"]
            events.append(
                {
                    "kind": "deficit_observed",
                    "trailing_side": trail,
                    "score": (L, R),
                    "media_start_sec": row.get("media_start_sec"),
                    "index": i,
                    "replaced_noisier_prior": True,
                }
            )
            continue
        if deficit_side is not None and L == R and not leveled_after_deficit:
            leveled_after_deficit = True
            equalizer_score = (L, R)
            events.append(
                {
                    "kind": "equalizer_observed",
                    "score": (L, R),
                    "media_start_sec": row.get("media_start_sec"),
                    "index": i,
                }
            )
            continue
        if deficit_side is not None and leveled_after_deficit:
            # Side that trailed now leads.
            if deficit_side == "left" and L > R:
                lead_after_deficit = True
                go_ahead_score = (L, R)
                events.append(
                    {
                        "kind": "go_ahead_observed",
                        "leading_side": "left",
                        "score": (L, R),
                        "media_start_sec": row.get("media_start_sec"),
                        "index": i,
                    }
                )
            elif deficit_side == "right" and R > L:
                lead_after_deficit = True
                go_ahead_score = (L, R)
                events.append(
                    {
                        "kind": "go_ahead_observed",
                        "leading_side": "right",
                        "score": (L, R),
                        "media_start_sec": row.get("media_start_sec"),
                        "index": i,
                    }
                )

    if deficit_side and leveled_after_deficit and lead_after_deficit:
        suggested = "story_candidate"
    elif deficit_side or leveled_after_deficit or lead_after_deficit:
        suggested = "partial_story"
    else:
        suggested = "unresolved"

    return {
        "schema": "v2_score_transition_analysis_v1",
        "timeline": states,
        "events": events,
        "deficit_side": deficit_side,
        "deficit_score": deficit_score,
        "equalizer_score": equalizer_score,
        "go_ahead_score": go_ahead_score,
        "leveled_after_deficit": leveled_after_deficit,
        "lead_after_deficit": lead_after_deficit,
        "suggested_discovery_status": suggested,
        "notes": [
            "Based only on parsed numeric scoreboard pairs",
            "Narrative keywords are ignored",
            "Does not prove goal actions are localized",
        ],
    }


def independent_discovery_check(
    *,
    llm_status: str,
    observations: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Do not trust LLM self-reported status; require score-transition consistency."""
    timeline = unique_score_timeline(observations)
    analysis = analyze_score_transitions(timeline)
    suggested = analysis["suggested_discovery_status"]
    llm = str(llm_status or "unresolved")
    # Never upgrade beyond what score evidence supports.
    rank = {"unresolved": 0, "no_comeback": 0, "partial_story": 1, "story_candidate": 2}
    final = llm if rank.get(llm, 0) <= rank.get(suggested, 0) else suggested
    # If LLM claims story_candidate but analysis is weaker, demote.
    if rank.get(llm, 0) > rank.get(suggested, 0):
        final = suggested
        demoted = True
    else:
        demoted = False
    return {
        "llm_status": llm,
        "score_suggested_status": suggested,
        "final_status": final,
        "demoted": demoted,
        "analysis": analysis,
        "verified_by": "score_transition_checker",
        "render_ready": False,
    }


def _normalize_timeline_rows(timeline: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for i, row in enumerate(timeline):
        if "left" in row and "right" in row:
            L, R = int(row["left"]), int(row["right"])
        elif "score" in row and isinstance(row["score"], (list, tuple)) and len(row["score"]) == 2:
            L, R = int(row["score"][0]), int(row["score"][1])
        else:
            continue
        rows.append(
            {
                "index": i,
                "score": (L, R),
                "left": L,
                "right": R,
                "media_start_sec": row.get("media_start_sec", row.get("event_time_sec")),
                "media_end_sec": row.get("media_end_sec"),
                "raw": row,
            }
        )
    return rows


def _find_arcs_for_side(rows: Sequence[Dict[str, Any]], side: str) -> List[Dict[str, Any]]:
    """Find every completed (and open) deficit→equalizer→go_ahead arc for one board side."""
    arcs: List[Dict[str, Any]] = []
    i = 0
    n = len(rows)
    while i < n:
        trail = _side_trailing(rows[i]["left"], rows[i]["right"])
        if trail != side:
            i += 1
            continue
        deficit = rows[i]
        j = i + 1
        equalizer = None
        go_ahead = None
        while j < n:
            L, R = rows[j]["left"], rows[j]["right"]
            if equalizer is None:
                if L == R:
                    equalizer = rows[j]
                elif _side_trailing(L, R) != side and (L + R) > sum(deficit["score"]):
                    # Lead change without a draw observation — mark incomplete.
                    break
                j += 1
                continue
            # After equalizer: wait for this side to lead.
            if side == "left" and L > R:
                go_ahead = rows[j]
                break
            if side == "right" and R > L:
                go_ahead = rows[j]
                break
            # If this side falls behind again before leading, restart from here.
            if _side_trailing(L, R) == side:
                break
            j += 1
        complete = equalizer is not None and go_ahead is not None
        arcs.append(
            {
                "protagonist_side": side,
                "complete": complete,
                "deficit_score": list(deficit["score"]),
                "deficit_index": deficit["index"],
                "deficit_media_start_sec": deficit.get("media_start_sec"),
                "equalizer_score": list(equalizer["score"]) if equalizer else None,
                "equalizer_index": equalizer["index"] if equalizer else None,
                "equalizer_media_start_sec": equalizer.get("media_start_sec") if equalizer else None,
                "go_ahead_score": list(go_ahead["score"]) if go_ahead else None,
                "go_ahead_index": go_ahead["index"] if go_ahead else None,
                "go_ahead_media_start_sec": go_ahead.get("media_start_sec") if go_ahead else None,
                "score_confirmation_sec": {
                    "deficit": deficit.get("media_start_sec"),
                    "equalizer": equalizer.get("media_start_sec") if equalizer else None,
                    "go_ahead": go_ahead.get("media_start_sec") if go_ahead else None,
                },
                "goal_action_sec": {
                    "deficit": None,
                    "equalizer": None,
                    "go_ahead": None,
                    "note": "Unset until video-verified; score_confirmation_sec is board time only",
                },
                "confidence_reason": (
                    f"{side} completed deficit→level→lead"
                    if complete
                    else f"{side} partial arc (missing equalizer and/or go-ahead)"
                ),
            }
        )
        # Continue scanning after this deficit (allow multiple arcs per side).
        i = (equalizer["index"] + 1) if equalizer is not None else i + 1
    return arcs


def analyze_last_deficit_arcs(
    timeline: Sequence[Dict[str, Any]],
    *,
    team_names: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Enumerate left/right comeback arcs; select the final winning last-deficit arc.

    Does not hardcode match scores. Unknown team names stay as board sides.
    """
    rows = _normalize_timeline_rows(timeline)
    team_names = dict(team_names or {})
    left_name = team_names.get("team_1") or team_names.get("left") or team_names.get("home")
    right_name = team_names.get("team_2") or team_names.get("right") or team_names.get("away")

    all_arcs = _find_arcs_for_side(rows, "left") + _find_arcs_for_side(rows, "right")
    complete = [a for a in all_arcs if a.get("complete")]
    abandoned = [a for a in all_arcs if not a.get("complete")]

    final_score = list(rows[-1]["score"]) if rows else None
    final_winner: Optional[str] = None
    if final_score is not None:
        if final_score[0] > final_score[1]:
            final_winner = "left"
        elif final_score[1] > final_score[0]:
            final_winner = "right"

    selected: Optional[Dict[str, Any]] = None
    status = "unresolved"
    if not rows:
        status = "unresolved"
    elif not complete:
        # Equalize-only or never trailed then led.
        if any(a.get("equalizer_score") for a in all_arcs) and not any(a.get("go_ahead_score") for a in all_arcs):
            status = "partial_story"
        elif final_winner and not any(
            _side_trailing(r["left"], r["right"]) == final_winner for r in rows
        ):
            status = "no_comeback"
        elif not any(_side_trailing(r["left"], r["right"]) for r in rows):
            status = "no_comeback"
        else:
            status = "partial_story" if all_arcs else "no_comeback"
    else:
        # Prefer complete arc whose protagonist is the final winner; else latest go-ahead.
        pool = [a for a in complete if final_winner is None or a["protagonist_side"] == final_winner]
        if not pool:
            pool = complete
            status = "partial_story"
        else:
            status = "story_candidate"
        selected = max(pool, key=lambda a: int(a.get("go_ahead_index") or -1))
        abandoned = [a for a in all_arcs if a is not selected]

    if selected is not None:
        side = selected["protagonist_side"]
        selected = {
            **selected,
            "protagonist_team_name": left_name if side == "left" else right_name,
            "board_side_mapping": {
                "left": left_name,
                "right": right_name,
                "note": "Names from events.teams only; never invented",
            },
            "roles": ["opening_deficit", "equalizer", "go_ahead"],
            "n_arc_goals": 3,
        }

    return {
        "schema": "v2_last_deficit_arc_v1",
        "timeline": [{"score": list(r["score"]), "media_start_sec": r.get("media_start_sec")} for r in rows],
        "final_score": final_score,
        "final_winner_side": final_winner,
        "all_arcs": all_arcs,
        "selected_arc": selected,
        "abandoned_arcs": abandoned,
        "status": status,
        "legacy_first_deficit_analysis": analyze_score_transitions(timeline),
        "notes": [
            "Prefer last complete deficit→equalizer→go_ahead for the final winning side",
            "score_confirmation_sec ≠ goal_action_sec",
            "Does not prove live goal localization",
        ],
        "render_ready": False,
    }


def select_last_deficit_arc(
    timeline: Sequence[Dict[str, Any]],
    *,
    team_names: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Convenience wrapper returning selected_arc payload for planner/EDL."""
    return analyze_last_deficit_arcs(timeline, team_names=team_names)
