"""Round 2.5 — live-only windowing with strict gates (no badge/timestamp auto-pass)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from story_video_agent.v2_phase_c1_toolbox import V2PhaseC1Toolbox

# Positive replay evidence only — do NOT match bare "replay"/"slow-motion" inside
# negations like "not a replay" or "lack of slow-motion artifacts".
_REPLAY = re.compile(
    r"("
    r"回放|重播|慢动作|慢镜|"
    r"instant\s*replay|"
    r"multi[- ]?angle\s+replay|"
    r"replay\s+(angle|transition|begins|starts|sequence|package|of|showing)|"
    r"slow[\s-]?mo(?:tion)?\s+replay|"
    r"slo[\s-]?mo\s+replay|"
    r"cut\s+to\s+(a\s+)?replay|"
    r"broadcast_state\s*[:=]\s*replay|"
    r"(?:appears\s+to\s+be|showing)\s+(?:a\s+)?(?:live\s+broadcast\s+)?replay|"
    r"replay\s+or\s+highlight|"
    r"highlight\s+sequence"
    r")",
    re.I,
)
_REPLAY_NEGATION = re.compile(
    r"("
    r"not\s+a\s+replay|"
    r"rather\s+than\s+(?:a\s+)?(?:slow[\s-]?mo(?:tion)?\s+)?replay|"
    r"rather\s+than\s+slow[\s-]?mo(?:tion)?|"
    r"no\s+(?:signs\s+of\s+)?(?:a\s+)?replay|"
    r"no\s+signs\s+of\s+slow[\s-]?mo(?:tion)?|"
    r"lack\s+of\s+slow[\s-]?mo(?:tion)?|"
    r"without\s+(?:a\s+)?replay|"
    r"without\s+the\s+temporal\s+distortion\s+typical\s+of\s+replays|"
    r"不是回放|并非回放|非回放"
    r")",
    re.I,
)
_LIVE_BADGE = re.compile(r"(直播|\blive\b)", re.I)
_SHOT = re.compile(
    r"(shot|shoot|strike|striking|struck|volley|finish|射门|打门|起脚|踢向球门|右脚射|左脚射|strikes?\s+the\s+ball|striking\s+the\s+ball)",
    re.I,
)
_NET = re.compile(r"(into the net|in the net|ball.*(net|goal)|入网|进球|破门|球网|crossing the goal line|crosses the goal)", re.I)
# Evidence of continuous live match play — NOT the persistent 直播 corner badge alone.
_LIVE_ACTION = re.compile(
    r"("
    r"live\s*(play|action|broadcast\s+feed|match)|"
    r"wide[- ]?(angle|shot|tactical|view)|"
    r"tactical\s+view|"
    r"main\s+camera|"
    r"elevated\s+(sideline|broadcast)|"
    r"match\s+clock|"
    r"scoreboard\s+(shows|display)|"
    r"continuous\s+live|"
    r"not\s+a\s+replay|"
    r"不是回放|"
    r"直播攻防|直播比赛|"
    r"攻防|"
    r"open\s+play|"
    r"match\s+in\s+progress|"
    r"attacking\s+(move|sequence|play|run)|"
    r"ball\s+in\s+play|"
    r"defensive\s+positioning|"
    r"broadcast_state\s*[:=]\s*live_action|"
    r"real-time|"
    r"natural\s+and\s+real-time"
    r")",
    re.I,
)
_TRANSITION = re.compile(r"(cut\s+to\s+replay|switch(?:es|ing)?\s+to\s+replay|进入回放|切到回放|replay\s+begins)", re.I)


def goal_search_neighborhood(ke: Dict[str, Any]) -> Dict[str, float]:
    """Broad media neighborhood to search for continuous live shot→net (may expand edit_window)."""
    shot = (ke.get("shot_action") or {}).get("media_sec")
    result = (ke.get("goal_result") or {}).get("media_sec")
    ew = ke.get("edit_window") or {}
    if shot is None:
        shot = ew.get("media_in")
    if result is None:
        result = ew.get("media_out") or ke.get("media_time_sec")
    if shot is None or result is None:
        return {"ok": 0.0, "media_in": 0.0, "media_out": 0.0}
    shot_f, result_f = float(shot), float(result)
    if result_f < shot_f:
        shot_f, result_f = result_f, shot_f
    return {
        "ok": 1.0,
        "media_in": max(0.0, shot_f - 14.0),
        "media_out": result_f + 14.0,
        "shot_sec": shot_f,
        "result_sec": result_f,
    }


def goal_live_core_window(ke: Dict[str, Any]) -> Dict[str, Any]:
    """Legacy tight seed around verified shot→result (not final accept without observation)."""
    shot = (ke.get("shot_action") or {}).get("media_sec")
    result = (ke.get("goal_result") or {}).get("media_sec")
    ew = ke.get("edit_window") or {}
    if shot is None:
        shot = ew.get("media_in")
    if result is None:
        result = ew.get("media_out") or ke.get("media_time_sec")
    if shot is None or result is None:
        return {
            "ok": False,
            "reason": "missing_shot_or_result_time",
            "media_in": None,
            "media_out": None,
        }
    shot_f = float(shot)
    result_f = float(result)
    if result_f < shot_f:
        shot_f, result_f = result_f, shot_f
    media_in = max(0.0, shot_f - 1.5)
    media_out = result_f + 2.5
    if ew.get("media_in") is not None:
        media_in = max(media_in, float(ew["media_in"]) - 0.5)
    if ew.get("media_out") is not None:
        media_out = min(media_out, float(ew["media_out"]) + 1.0)
    media_in = min(media_in, shot_f - 0.3)
    media_out = max(media_out, result_f + 0.8)
    if media_out - media_in < 4.0:
        mid = 0.5 * (shot_f + result_f)
        media_in, media_out = mid - 2.0, mid + 2.5
    return {
        "ok": True,
        "media_in": round(media_in, 3),
        "media_out": round(media_out, 3),
        "shot_sec": shot_f,
        "result_sec": result_f,
        "basis": "verified_shot_result_seed_only_not_acceptance",
        "rejected_graph_pad": "shot_minus_6s_not_used",
        "note": "Seed only; final window requires continuous live timeline + observed shot/net",
    }


def _blob_from_raw(raw: Dict[str, Any]) -> str:
    actions = (
        (raw.get("perception") or {}).get("observed_actions")
        or raw.get("observed_actions")
        or []
    )
    notes = str((raw.get("perception") or {}).get("notes") or raw.get("notes") or "")
    return " ".join(str(a) for a in actions) + " " + notes


def classify_live_replay(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Strict classifier: persistent 直播 badge ≠ live action proof."""
    if raw.get("error"):
        return {
            "live_or_replay": "unknown",
            "has_replay_keyword": False,
            "has_live_badge_keyword": False,
            "has_live_action_evidence": False,
            "has_transition_cue": False,
            "badge_alone_not_sufficient": False,
            "blob_excerpt": f"tool_error={raw.get('error')}: {raw.get('message')}",
            "observed_actions": [],
            "error": raw.get("error"),
        }
    blob = _blob_from_raw(raw)
    # Remove negated replay phrases so "not a replay" does not trip the gate.
    blob_for_replay = _REPLAY_NEGATION.sub(" ", blob)
    has_replay = bool(_REPLAY.search(blob_for_replay))
    has_badge = bool(_LIVE_BADGE.search(blob))
    has_live_action = bool(_LIVE_ACTION.search(blob))
    has_transition = bool(_TRANSITION.search(blob_for_replay))

    has_shot = bool(_SHOT.search(blob))
    has_net = bool(_NET.search(blob))
    # Shot+net without replay is weak live-action evidence only when paired with
    # non-badge continuity cues; badge alone never upgrades unknown→live.
    if has_live_action is False and has_shot and has_net and not has_replay:
        if re.search(r"(wide|tactical|approach|dribble|celebrat|推进|带球)", blob, re.I):
            has_live_action = True

    if has_replay and not has_live_action:
        status = "replay"
    elif has_transition or (has_replay and has_live_action):
        status = "mixed_or_ambiguous"
    elif has_live_action and not has_replay:
        status = "live"
    elif has_badge and not has_replay:
        # Badge alone is insufficient — treat as unknown (not passable).
        status = "unknown"
    else:
        status = "unknown"

    return {
        "live_or_replay": status,
        "has_replay_keyword": has_replay,
        "has_live_badge_keyword": has_badge,
        "has_live_action_evidence": has_live_action,
        "has_transition_cue": has_transition,
        "badge_alone_not_sufficient": has_badge and not has_live_action,
        "blob_excerpt": blob[:500],
        "observed_actions": (
            (raw.get("perception") or {}).get("observed_actions")
            or raw.get("observed_actions")
            or []
        )[:12],
    }


def observe_window(
    *,
    tools: V2PhaseC1Toolbox,
    start: float,
    end: float,
    task_id: str,
    dense: bool = False,
) -> Dict[str, Any]:
    if end - start > 45:
        start = end - 36.0
    if end <= start + 0.5:
        end = start + 1.0
    tool = "dense_action_inspect" if dense else "coarse_search"
    if dense and end - start > 16:
        mid = 0.5 * (start + end)
        start, end = mid - 8, mid + 8
    return tools.execute(tool, {"start": start, "end": end, "task_id": task_id})


def _slice_times(
    media_in: float,
    media_out: float,
    step: float = 5.0,
    anchors: Optional[Sequence[float]] = None,
) -> List[Tuple[float, float]]:
    """Build short probes. Prefer anchors around shot/result; else stepped coverage."""
    spans: List[Tuple[float, float]] = []
    width = 2.4
    centers: List[float] = []
    if anchors:
        for a in anchors:
            if a is None:
                continue
            af = float(a)
            if media_in - 0.5 <= af <= media_out + 0.5:
                centers.append(af)
    if len(centers) < 3:
        t = media_in + width * 0.5
        while t < media_out:
            centers.append(t)
            t += step
    # unique sorted centers
    uniq: List[float] = []
    for c in sorted(centers):
        if not uniq or abs(c - uniq[-1]) >= 1.6:
            uniq.append(c)
    # cap probes to control VLM cost/latency
    if len(uniq) > 8:
        # keep first, last, and evenly spaced middle
        idxs = [0] + [int(round(i * (len(uniq) - 1) / 7)) for i in range(1, 7)] + [len(uniq) - 1]
        uniq = [uniq[i] for i in sorted(set(idxs))]
    for c in uniq:
        s = max(media_in, c - width * 0.5)
        e = min(media_out, s + width)
        if e - s < 0.8:
            e = min(media_out, s + 0.9)
        if e > s + 0.5:
            spans.append((round(s, 3), round(e, 3)))
    if not spans:
        spans.append((round(media_in, 3), round(min(media_out, media_in + 2.5), 3)))
    return spans


def build_broadcast_timeline(
    *,
    tools: V2PhaseC1Toolbox,
    media_in: float,
    media_out: float,
    task_prefix: str,
    event_replay_overlaps: Optional[Sequence[Dict[str, Any]]] = None,
    step: float = 5.0,
    anchors: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """Multi-slice live/replay/transition/unknown timeline across a candidate neighborhood."""
    slices: List[Dict[str, Any]] = []
    for i, (s, e) in enumerate(_slice_times(media_in, media_out, step=step, anchors=anchors)):
        # Prefer verify_live_replay (4 frames); fall back to coarse on tool errors.
        raw = tools.execute(
            "verify_live_replay",
            {"start": s, "end": min(e, s + 8.0), "task_id": f"{task_prefix}_sl{i}"},
        )
        if raw.get("error"):
            # one retry with slightly shorter window
            mid = 0.5 * (s + e)
            raw = tools.execute(
                "verify_live_replay",
                {
                    "start": max(media_in, mid - 1.0),
                    "end": min(media_out, mid + 1.2),
                    "task_id": f"{task_prefix}_sl{i}_retry",
                },
            )
        lr = classify_live_replay(raw)
        # Event-label override: overlapping annotated REPLAY forces replay/transition
        ev_hit = [
            r
            for r in (event_replay_overlaps or [])
            if r.get("start_time_sec") is not None
            and max(s, float(r["start_time_sec"])) < min(e, float(r["end_time_sec"]))
        ]
        status = lr["live_or_replay"]
        if ev_hit and status == "live":
            status = "mixed_or_ambiguous"
        elif ev_hit and status == "unknown":
            status = "replay"
        if status == "mixed_or_ambiguous" and lr.get("has_transition_cue"):
            phase = "transition"
        elif status == "replay":
            phase = "replay"
        elif status == "live":
            phase = "live"
        else:
            phase = "unknown"
        blob = _blob_from_raw(raw)
        slices.append(
            {
                "media_in": s,
                "media_out": e,
                "phase": phase,
                "live_or_replay": status,
                "has_shot": bool(_SHOT.search(blob)),
                "has_net": bool(_NET.search(blob)),
                "event_replay_hits": [r.get("event_id") for r in ev_hit],
                "observation": lr,
            }
        )

    # Merge contiguous same-phase runs
    runs: List[Dict[str, Any]] = []
    for sl in slices:
        if runs and runs[-1]["phase"] == sl["phase"]:
            runs[-1]["media_out"] = sl["media_out"]
            runs[-1]["slices"].append(sl)
            runs[-1]["has_shot"] = runs[-1]["has_shot"] or sl["has_shot"]
            runs[-1]["has_net"] = runs[-1]["has_net"] or sl["has_net"]
        else:
            runs.append(
                {
                    "phase": sl["phase"],
                    "media_in": sl["media_in"],
                    "media_out": sl["media_out"],
                    "has_shot": sl["has_shot"],
                    "has_net": sl["has_net"],
                    "slices": [sl],
                }
            )

    return {
        "schema": "v2_r25_broadcast_timeline_segment_v1",
        "requested": {"media_in": media_in, "media_out": media_out},
        "slices": slices,
        "runs": runs,
        "n_live_slices": sum(1 for s in slices if s["phase"] == "live"),
        "n_replay_slices": sum(1 for s in slices if s["phase"] == "replay"),
        "n_unknown_slices": sum(1 for s in slices if s["phase"] == "unknown"),
        "n_transition_slices": sum(1 for s in slices if s["phase"] == "transition"),
    }


def locate_continuous_live_goal_window(
    *,
    timeline: Dict[str, Any],
    shot_sec: Optional[float],
    result_sec: Optional[float],
) -> Dict[str, Any]:
    """Propose a non-replay span covering shot→result for dense live confirmation.

    Unknown slices may bridge (empty VLM / incomplete labels) but replay/transition
    always hard-stop. Final pass still requires dense observation = live + shot + net.
    """
    slices = list(timeline.get("slices") or [])
    runs = timeline.get("runs") or []
    if not slices:
        return {"ok": False, "reason": "empty_timeline", "media_in": None, "media_out": None}

    # Contiguous bridgeable region: live or unknown (not replay/transition)
    def _bridgeable(phase: str) -> bool:
        return phase not in {"replay", "transition"}

    # Expand from shot/result outward while bridgeable
    anchor = result_sec if result_sec is not None else shot_sec
    if anchor is None:
        anchor = 0.5 * (float(slices[0]["media_in"]) + float(slices[-1]["media_out"]))

    # index of slice containing or nearest to anchor
    idx = min(
        range(len(slices)),
        key=lambda i: abs(0.5 * (slices[i]["media_in"] + slices[i]["media_out"]) - float(anchor)),
    )
    lo = hi = idx
    while lo > 0 and _bridgeable(slices[lo - 1]["phase"]):
        lo -= 1
    while hi + 1 < len(slices) and _bridgeable(slices[hi + 1]["phase"]):
        hi += 1

    # If the anchor slice itself is replay, fail
    if not _bridgeable(slices[idx]["phase"]):
        return {
            "ok": False,
            "reason": "anchor_slice_is_replay_or_transition",
            "media_in": None,
            "media_out": None,
            "anchor_slice": slices[idx],
        }

    media_in = float(slices[lo]["media_in"])
    media_out = float(slices[hi]["media_out"])

    # Prefer start a bit before shot for approach when available
    if shot_sec is not None:
        media_in = min(media_in, max(float(slices[0]["media_in"]), float(shot_sec) - 8.0))
        # but do not cross into a replay slice before shot
        for sl in slices:
            if sl["phase"] in {"replay", "transition"} and sl["media_out"] <= float(shot_sec):
                media_in = max(media_in, float(sl["media_out"]))

    # Hard trim at first replay/transition after shot/result
    trim_after = float(result_sec) if result_sec is not None else float(anchor)
    for sl in slices:
        if sl["media_in"] >= trim_after - 0.2 and sl["phase"] in {"replay", "transition"}:
            media_out = min(media_out, float(sl["media_in"]))
            break
    for r in runs:
        if r["media_in"] >= trim_after - 0.2 and r["phase"] in {"replay", "transition"}:
            media_out = min(media_out, float(r["media_in"]))
            break

    # Ensure coverage of verified shot/result times inside proposed window
    if shot_sec is not None and not (media_in - 0.2 <= float(shot_sec) <= media_out + 0.2):
        media_in = min(media_in, float(shot_sec) - 1.5)
        media_out = max(media_out, float(shot_sec) + 0.5)
    if result_sec is not None and not (media_in - 0.2 <= float(result_sec) <= media_out + 0.2):
        media_out = max(media_out, float(result_sec) + 1.5)

    # Re-apply replay trim after coverage expand
    for sl in slices:
        if sl["media_in"] >= (float(result_sec) if result_sec is not None else media_in) and sl[
            "phase"
        ] in {"replay", "transition"}:
            media_out = min(media_out, float(sl["media_in"]))
            break

    if media_out - media_in < 3.5:
        return {
            "ok": False,
            "reason": "candidate_window_too_short_after_replay_trim",
            "media_in": round(media_in, 3),
            "media_out": round(media_out, 3),
        }

    span_slices = [
        s for s in slices if s["media_out"] > media_in and s["media_in"] < media_out
    ]
    has_shot = any(s.get("has_shot") for s in span_slices)
    has_net = any(s.get("has_net") for s in span_slices)
    n_live = sum(1 for s in span_slices if s.get("phase") == "live")
    n_unknown = sum(1 for s in span_slices if s.get("phase") == "unknown")
    n_replay = sum(1 for s in span_slices if s.get("phase") in {"replay", "transition"})
    if n_replay:
        return {
            "ok": False,
            "reason": "candidate_still_contains_replay",
            "media_in": round(media_in, 3),
            "media_out": round(media_out, 3),
        }

    # Candidate is OK for dense confirmation even if timeline was mostly unknown
    # (empty VLM under low token budgets). Dense must still prove live+shot+net.
    return {
        "ok": True,
        "media_in": round(media_in, 3),
        "media_out": round(media_out, 3),
        "has_shot": has_shot,
        "has_net": has_net,
        "phase": "live" if n_live and not n_unknown else "pending_dense_live_confirm",
        "basis": "bridgeable_non_replay_span_for_dense_confirm",
        "timeline_n_live": n_live,
        "timeline_n_unknown": n_unknown,
        "needs_dense_live_confirm": True,
    }


def audit_goal_clip_live(
    *,
    ke: Dict[str, Any],
    tools: V2PhaseC1Toolbox,
    evidence_prefix: str,
    event_replay_overlaps: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Locate + gate a live-only goal window. No timestamp auto-fill for shot/net."""
    seed = goal_live_core_window(ke)
    neigh = goal_search_neighborhood(ke)
    row: Dict[str, Any] = {
        "key_event_id": ke.get("key_event_id"),
        "score_before": ke.get("score_before"),
        "score_after": ke.get("score_after"),
        "verified_shot_sec": (ke.get("shot_action") or {}).get("media_sec"),
        "verified_result_sec": (ke.get("goal_result") or {}).get("media_sec"),
        "seed_window": seed,
        "search_neighborhood": neigh,
        "gate": "hard_live_only_observed_shot_net_no_badge_no_timestamp_fill",
    }
    if not seed.get("ok") or not neigh.get("ok"):
        row.update(
            {
                "pass": False,
                "fail_reasons": ["missing_shot_or_result_time"],
                "live_or_replay": "unknown",
                "accepted_media_in": None,
                "accepted_media_out": None,
            }
        )
        return row

    shot_f = float(neigh["shot_sec"])
    result_f = float(neigh["result_sec"])
    timeline = build_broadcast_timeline(
        tools=tools,
        media_in=float(neigh["media_in"]),
        media_out=float(neigh["media_out"]),
        task_prefix=f"{evidence_prefix}_{ke.get('key_event_id')}",
        event_replay_overlaps=event_replay_overlaps,
        step=5.0,
        anchors=[
            shot_f - 10.0,
            shot_f - 5.0,
            shot_f - 1.5,
            shot_f,
            result_f,
            result_f + 2.5,
            result_f + 6.0,
            result_f + 11.0,
        ],
    )
    located = locate_continuous_live_goal_window(
        timeline=timeline,
        shot_sec=float(neigh["shot_sec"]),
        result_sec=float(neigh["result_sec"]),
    )
    row["broadcast_timeline"] = {
        "n_slices": len(timeline.get("slices") or []),
        "n_live_slices": timeline.get("n_live_slices"),
        "n_replay_slices": timeline.get("n_replay_slices"),
        "n_unknown_slices": timeline.get("n_unknown_slices"),
        "runs": [
            {k: r.get(k) for k in ("phase", "media_in", "media_out", "has_shot", "has_net")}
            for r in (timeline.get("runs") or [])
        ],
    }
    row["located_window"] = located

    fail: List[str] = []
    accepted_in: Optional[float] = None
    accepted_out: Optional[float] = None
    if not located.get("ok"):
        fail.append(str(located.get("reason") or "locate_failed"))
    else:
        shot_f = float(neigh["shot_sec"])
        result_f = float(neigh["result_sec"])
        # Tight live core for dense proof — long spans often mix trailing replay angles.
        tight_in = max(float(located["media_in"]), shot_f - 6.0)
        # Keep post-net pad short so trailing multicam/replay packages stay out.
        tight_out = min(float(located["media_out"]), result_f + 2.2)
        for r in event_replay_overlaps or []:
            rs = r.get("start_time_sec")
            if rs is None:
                continue
            if float(rs) >= shot_f - 0.5:
                tight_out = min(tight_out, float(rs) - 0.05)
        if tight_out - tight_in < 3.5:
            tight_in = max(0.0, shot_f - 4.0)
            tight_out = max(tight_out, result_f + 2.0)
            for r in event_replay_overlaps or []:
                rs = r.get("start_time_sec")
                if rs is not None and float(rs) >= shot_f - 0.5:
                    tight_out = min(tight_out, float(rs) - 0.05)

        def _dense_check(a: float, b: float, tag: str) -> Dict[str, Any]:
            raw = observe_window(
                tools=tools,
                start=a,
                end=b,
                task_id=f"{evidence_prefix}_dense_{tag}_{ke.get('key_event_id')}",
                dense=True,
            )
            lr = classify_live_replay(raw)
            blob = _blob_from_raw(raw)
            return {
                "raw": raw,
                "lr": lr,
                "blob": blob,
                "has_shot": bool(_SHOT.search(blob)),
                "has_net": bool(_NET.search(blob)),
                "window": {"media_in": a, "media_out": b},
            }

        primary = _dense_check(tight_in, tight_out, "tight")
        chosen = primary
        # If mixed because trailing multi-angle/replay, retry tighter cores.
        if primary["lr"]["live_or_replay"] in {"mixed_or_ambiguous", "replay"}:
            for tag, pad_before, pad_after in (
                ("retry", 2.5, 2.0),
                ("retry2", 1.2, 1.0),
            ):
                tighter_in = max(tight_in, shot_f - pad_before)
                tighter_out = min(tight_out, result_f + pad_after)
                if tighter_out - tighter_in < 2.8:
                    continue
                retry = _dense_check(tighter_in, tighter_out, tag)
                row[f"dense_{tag}"] = {
                    "window": retry["window"],
                    "live_or_replay": retry["lr"]["live_or_replay"],
                    "blob_excerpt": retry["lr"].get("blob_excerpt", "")[:300],
                }
                if (
                    retry["lr"]["live_or_replay"] == "live"
                    and retry["has_shot"]
                    and retry["has_net"]
                ):
                    chosen = retry
                    break

        lr = chosen["lr"]
        has_shot = chosen["has_shot"]
        has_net = chosen["has_net"]
        row["dense_observation"] = lr
        row["dense_window"] = chosen["window"]
        row["has_shot_action"] = has_shot
        row["has_net_result"] = has_net
        row["live_or_replay"] = lr["live_or_replay"]
        row["contains_replay"] = lr["live_or_replay"] in {"replay", "mixed_or_ambiguous"}
        row["timestamp_autofill_used"] = False

        if lr["live_or_replay"] != "live":
            fail.append(f"dense_live_status={lr['live_or_replay']}")
        if lr.get("badge_alone_not_sufficient") and lr["live_or_replay"] != "live":
            fail.append("live_badge_alone_insufficient")
        if not has_shot:
            fail.append("missing_shot_action_in_observation")
        if not has_net:
            fail.append("missing_net_result_in_observation")

        if not fail:
            accepted_in = float(chosen["window"]["media_in"])
            accepted_out = float(chosen["window"]["media_out"])
            # Cap duration; keep approach but avoid long celebration/replay tails.
            if accepted_out - accepted_in > 12.0:
                accepted_in = max(accepted_in, shot_f - 5.0)
                accepted_out = min(accepted_out, result_f + 3.0)
            for r in event_replay_overlaps or []:
                rs = r.get("start_time_sec")
                if rs is not None and float(rs) >= shot_f - 0.5:
                    accepted_out = min(accepted_out, float(rs) - 0.05)

    passed = len(fail) == 0 and accepted_in is not None and accepted_out is not None
    row.update(
        {
            "pass": passed,
            "fail_reasons": fail,
            "accepted_media_in": round(accepted_in, 3) if passed else None,
            "accepted_media_out": round(accepted_out, 3) if passed else None,
            "evidence_id": f"{evidence_prefix}_{ke.get('key_event_id')}",
            "unresolved": not passed,
        }
    )
    return row


def audit_strip_live(
    *,
    node_id: str,
    media_in: float,
    media_out: float,
    tools: V2PhaseC1Toolbox,
    evidence_prefix: str,
    event_replay_overlaps: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    timeline = build_broadcast_timeline(
        tools=tools,
        media_in=media_in,
        media_out=media_out,
        task_prefix=f"{evidence_prefix}_{node_id}",
        event_replay_overlaps=event_replay_overlaps,
        step=4.0,
    )
    live_runs = [r for r in (timeline.get("runs") or []) if r.get("phase") == "live"]
    fail: List[str] = []
    accepted_in = accepted_out = None
    if not live_runs:
        fail.append("no_live_run")
    elif any(r.get("phase") == "replay" for r in (timeline.get("runs") or [])):
        # Keep only the first continuous live prefix before replay
        first_live = live_runs[0]
        accepted_in = float(first_live["media_in"])
        accepted_out = float(first_live["media_out"])
        for r in timeline.get("runs") or []:
            if r["media_in"] >= accepted_in and r["phase"] in {"replay", "transition"}:
                accepted_out = min(accepted_out, float(r["media_in"]))
                break
        if accepted_out - accepted_in < 4.0:
            fail.append("live_prefix_too_short_after_replay_trim")
            accepted_in = accepted_out = None
        else:
            # Cap strip length
            accepted_out = min(accepted_out, accepted_in + 18.0)
    else:
        # All live or live+unknown — unknown blocks clean
        if any(r.get("phase") == "unknown" for r in (timeline.get("runs") or [])):
            fail.append("contains_unknown_phase")
        else:
            accepted_in = float(live_runs[0]["media_in"])
            accepted_out = min(float(live_runs[-1]["media_out"]), accepted_in + 18.0)

    return {
        "node_id": node_id,
        "requested_window": {"media_in": media_in, "media_out": media_out},
        "broadcast_timeline": {
            "runs": [
                {k: r.get(k) for k in ("phase", "media_in", "media_out")}
                for r in (timeline.get("runs") or [])
            ]
        },
        "pass_live_only": len(fail) == 0 and accepted_in is not None,
        "fail_reasons": fail,
        "accepted_media_in": accepted_in,
        "accepted_media_out": accepted_out,
        "evidence_id": f"{evidence_prefix}_{node_id}",
    }


def build_live_only_edl(
    *,
    goal_audits: Sequence[Dict[str, Any]],
    strip_audits: Sequence[Dict[str, Any]],
    r24_segments: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Rebuild EDL from R2.4 narrative order, replacing windows with live-only accepts."""
    goal_by_id = {g["key_event_id"]: g for g in goal_audits}
    strip_by_id = {s["node_id"]: s for s in strip_audits}

    title_open = {
        "segment_id": "title_open",
        "beat": "setup",
        "role": "title_card",
        "media_in": None,
        "media_out": None,
        "duration_sec": 2.5,
        "time_status": "title_card",
        "render_eligibility": "placeholder_title",
        "title_text": "Comeback Live-Only Candidate (R2.5fix)",
        "source_node_ids": [],
        "event_ids": [],
        "render_ready": False,
    }
    title_close = {
        "segment_id": "title_close",
        "beat": "resolution",
        "role": "title_card",
        "media_in": None,
        "media_out": None,
        "duration_sec": 2.0,
        "time_status": "title_card",
        "render_eligibility": "placeholder_title",
        "title_text": "End — render_ready=false — live_only_fix",
        "source_node_ids": [],
        "event_ids": [],
        "render_ready": False,
    }

    body: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []
    for s in r24_segments:
        if s.get("role") == "title_card":
            continue
        nids = s.get("source_node_ids") or []
        nid = nids[0] if nids else None
        if not nid:
            continue
        if str(nid).startswith("ke_"):
            g = goal_by_id.get(nid)
            if not g or not g.get("pass") or g.get("accepted_media_in") is None:
                dropped.append(
                    {
                        "node_id": nid,
                        "reason": (g or {}).get("fail_reasons") or ["goal_audit_failed"],
                        "unresolved": True,
                    }
                )
                continue
            body.append(
                {
                    "segment_id": f"live_{nid}",
                    "beat": s.get("beat"),
                    "role": "goal",
                    "media_in": g["accepted_media_in"],
                    "media_out": g["accepted_media_out"],
                    "duration_sec": round(
                        float(g["accepted_media_out"]) - float(g["accepted_media_in"]), 3
                    ),
                    "time_status": "verified_continuous_live",
                    "render_eligibility": "candidate",
                    "source_node_ids": [nid],
                    "event_ids": [nid],
                    "why": f"R2.5fix live-only for {g.get('score_before')}->{g.get('score_after')}",
                    "live_or_replay": g.get("live_or_replay")
                    or (g.get("dense_observation") or {}).get("live_or_replay"),
                    "shot_sec": g.get("verified_shot_sec"),
                    "result_sec": g.get("verified_result_sec"),
                    "integrity_pass": True,
                    "render_ready": False,
                }
            )
        elif str(nid).startswith("strip_"):
            st = strip_by_id.get(nid)
            if not st or not st.get("pass_live_only"):
                dropped.append(
                    {"node_id": nid, "reason": (st or {}).get("fail_reasons") or ["strip_live_fail"]}
                )
                continue
            body.append(
                {
                    "segment_id": f"live_{nid}",
                    "beat": s.get("beat"),
                    "role": "strip_context",
                    "media_in": st["accepted_media_in"],
                    "media_out": st["accepted_media_out"],
                    "duration_sec": round(
                        float(st["accepted_media_out"]) - float(st["accepted_media_in"]), 3
                    ),
                    "time_status": "live_observed_strip",
                    "render_eligibility": "candidate",
                    "source_node_ids": [nid],
                    "event_ids": [nid],
                    "why": "R2.5fix live-only strip after broadcast timeline",
                    "live_or_replay": "live",
                    "render_ready": False,
                }
            )

    body.sort(key=lambda x: float(x["media_in"]))
    segments = [title_open] + body + [title_close]
    for i, s in enumerate(segments):
        s["narrative_order"] = i
        s["source_media_order"] = (
            None
            if s.get("media_in") is None
            else sum(1 for t in body if float(t["media_in"]) < float(s.get("media_in") or 1e18))
        )
        s["edl_index"] = i
        if s.get("media_in") is not None:
            beat = s.get("beat") or "x"
            nid = (s.get("source_node_ids") or ["node"])[0]
            s["segment_id"] = f"edl_{i:02d}_{beat}_{nid}"

    n_goal = sum(1 for s in segments if s.get("role") == "goal")
    all_pass = len(goal_audits) == 5 and all(g.get("pass") for g in goal_audits)
    story_complete = n_goal == 5 and all_pass
    return {
        "schema": "v2_r25_edl_live_only_v1",
        "playout_policy": "prefer_match_timeline",
        "n_segments": len(segments),
        "n_goal_segments": n_goal,
        "n_non_goal_strip_segments": sum(1 for s in segments if s.get("role") == "strip_context"),
        "segments": segments,
        "candidate_edl": [
            {**s, "narrative_order": s["narrative_order"]}
            for s in segments
            if s.get("media_in") is not None
            or s.get("render_eligibility") in {"blocked", "placeholder_title"}
        ],
        "dropped_segments": dropped,
        "gates": {
            "live_only": True,
            "all_five_goals_pass": story_complete,
            "story_complete_candidate": story_complete,
            "render_ready": False,
            "hard_gate": "replay_mixed_unknown_blocked_no_timestamp_autofill",
        },
        "render_ready": False,
        "note": "Live-only EDL fix: continuous live timeline + observed shot/net; badge≠live",
    }


def diagnose_r24_ke3(r24_dir) -> Dict[str, Any]:
    """Root-cause note for 2:1 presentation issue without changing 3566.64."""
    from pathlib import Path
    import json

    r24_dir = Path(r24_dir)
    ke_doc = json.loads((r24_dir / "full_match_key_events.json").read_text(encoding="utf-8"))
    edl = json.loads((r24_dir / "candidate_edl.json").read_text(encoding="utf-8"))
    ke3 = next(k for k in ke_doc["key_events"] if (k.get("score_after") or []) == [2, 1])
    seg = next(
        s
        for s in edl["segments"]
        if "ke_3" in str(s.get("source_node_ids")) or "trans_2" in str(s.get("source_node_ids"))
    )
    shot = float((ke3.get("shot_action") or {}).get("media_sec"))
    result = float((ke3.get("goal_result") or {}).get("media_sec"))
    ew = ke3.get("edit_window") or {}
    return {
        "schema": "v2_r25_ke3_diagnosis_v1",
        "verified_shot_sec": shot,
        "verified_result_sec": result,
        "verified_edit_window": ew,
        "r24_edl_window": {"media_in": seg.get("media_in"), "media_out": seg.get("media_out")},
        "root_cause": (
            "R2.4 over-padded; R2.5 first pass used tight core but accepted live via 直播 badge "
            "and/or timestamp autofill. Human review of story 31–39s found multi-angle goal-line "
            "cuts that need continuous live timeline from approach through net, trimmed before "
            "post-goal replay (~3571+). Verified PTS 3562.32/3566.64 unchanged as anchors."
        ),
        "ffmpeg_consistent_with_edl": True,
        "result_time_unchanged": 3566.64,
        "fix": "broadcast_timeline_relocate_trim_before_replay",
    }
