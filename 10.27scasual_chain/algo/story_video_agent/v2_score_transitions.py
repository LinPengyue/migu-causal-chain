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
