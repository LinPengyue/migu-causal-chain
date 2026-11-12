"""P5 post-match Goal candidate recovery from Score_Recognition + LIVE evidence.

Never reads human *_causal.json. Never treats scoreboard confirm as goal_action_sec.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .pipeline import dump
from .v1_causal_adapter import load_raw_events, score_pair_from_raw_event

_ACTION_TYPES = frozenset({
    "Shot", "Save", "Corner_kick", "Free_kick", "Dribble_past", "Throw_in",
    "Ball_possession", "Cross",
})


def _event_time(e: Dict[str, Any]) -> Optional[float]:
    mt = e.get("media_time") or {}
    t = mt.get("event_time_sec")
    if t is None:
        t = mt.get("start_time_sec")
    return float(t) if t is not None else None


def _is_replay(e: Dict[str, Any]) -> bool:
    vc = e.get("video_context") or {}
    return bool(vc.get("is_replay")) or str(vc.get("broadcast_phase") or "").upper() == "REPLAY"


def score_observations(raw_events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for e in raw_events:
        pair = score_pair_from_raw_event(e)
        if pair is None:
            continue
        t = _event_time(e)
        if t is None:
            continue
        out.append({
            "media_sec": t,
            "score": list(pair),
            "event_id": e.get("event_id"),
            "event_type": e.get("event_type"),
            "is_replay": _is_replay(e),
        })
    out.sort(key=lambda r: r["media_sec"])
    return out


def recover_goal_candidates(raw_events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build one candidate per single-goal Score_Recognition increment (count not hardcoded)."""
    obs = score_observations(raw_events)
    if not obs:
        return []
    candidates: List[Dict[str, Any]] = []
    prev = tuple(obs[0]["score"])
    for row in obs[1:]:
        cur = tuple(row["score"])
        if cur == prev:
            continue
        d0, d1 = cur[0] - prev[0], cur[1] - prev[1]
        single = (d0 + d1 == 1) and min(d0, d1) == 0 and max(d0, d1) == 1
        confirm = float(row["media_sec"])
        before_obs = [o for o in obs if tuple(o["score"]) == prev and o["media_sec"] < confirm]
        after_obs = [o for o in obs if tuple(o["score"]) == cur and o["media_sec"] >= confirm - 0.5]
        last_before = max(before_obs, key=lambda o: o["media_sec"], default=None)
        first_after = min(after_obs, key=lambda o: o["media_sec"], default=None)
        win_lo = float(last_before["media_sec"]) if last_before else confirm - 180.0
        win_hi = confirm
        nearby = []
        for e in raw_events:
            t = _event_time(e)
            if t is None or e.get("event_type") not in _ACTION_TYPES:
                continue
            if win_lo - 10.0 <= t <= confirm + 20.0:
                nearby.append({
                    "event_id": e.get("event_id"),
                    "event_type": e.get("event_type"),
                    "media_sec": t,
                    "is_replay": _is_replay(e),
                    "media_start_sec": (e.get("media_time") or {}).get("start_time_sec"),
                    "media_end_sec": (e.get("media_time") or {}).get("end_time_sec"),
                })
        nearby.sort(key=lambda x: x["media_sec"])
        scoring_side = "home_or_left" if d0 == 1 else ("away_or_right" if d1 == 1 else "unknown")
        # Board reliability: prefer non-replay carrier; OCR/score token must parse cleanly
        reliability = "high" if single and not row.get("is_replay") else ("medium" if single else "low")
        if not single:
            reliability = "reject_non_single"
        candidates.append({
            "candidate_id": f"goalcand_{len(candidates):02d}_{prev[0]}{prev[1]}_to_{cur[0]}{cur[1]}",
            "score_before": list(prev),
            "score_after": list(cur),
            "delta": [d0, d1],
            "single_goal_increment": single,
            "scoring_side": scoring_side,
            "score_confirmation_sec": confirm,
            "score_confirmation_reliability": reliability,
            "score_confirmation_event_id": row.get("event_id"),
            "score_confirmation_event_type": row.get("event_type"),
            "last_before_score_obs_sec": last_before["media_sec"] if last_before else None,
            "first_after_score_obs_sec": first_after["media_sec"] if first_after else None,
            "possible_action_interval": {
                "media_in": round(win_lo, 3),
                "media_out": round(win_hi, 3),
                "note": "Board lag window from Score_Recognition; NOT the action time itself",
            },
            "nearby_events": nearby,
            "goal_action_sec": None,
            "goal_action_interval": None,
            "is_replay": False,
            "evidence_sources": ["score_recognition"],
            "verification_status": "unresolved_goal_action" if single else "rejected_non_single_increment",
            "linked_strip_chain_ids": [],
            "notes": [],
        })
        prev = cur
    return candidates


def load_action_overlays(paths: Sequence[Path]) -> List[Dict[str, Any]]:
    """Optional recovered LIVE action hints (P3/P4/G2.2 packs). Not human causal gold."""
    out = []
    for p in paths:
        path = Path(p)
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        # Normalize several known shapes
        if data.get("schema") == "v3_goal_action_overlay_v1":
            out.extend(data.get("overlays") or [])
            continue
        if data.get("safe_live_pts") and data.get("role"):
            # p4 summary-ish
            pts = data["safe_live_pts"]
            out.append({
                "score_before": data.get("score_before"),
                "score_after": data.get("score_after"),
                "score_confirmation_sec": data.get("score_confirmation_sec"),
                "goal_action_sec": data.get("goal_action_sec") or pts.get("media_in"),
                "goal_action_interval": {
                    "media_in": pts.get("media_in"),
                    "media_out": pts.get("media_out"),
                },
                "is_replay": False,
                "source": str(path),
                "verification_status": "live_footage_supported" if data.get("live_footage_verified") else "possible_first_live",
            })
            continue
        if data.get("top1") and data.get("score_before") is not None:
            top = data["top1"]
            mi, mo = top.get("media_in"), top.get("media_out")
            out.append({
                "score_before": data.get("score_before"),
                "score_after": data.get("score_after"),
                "score_confirmation_sec": data.get("score_confirmation_sec"),
                "goal_action_sec": mi,
                "goal_action_interval": {"media_in": mi, "media_out": mo},
                "is_replay": False,
                "source": str(path),
                "verification_status": str(data.get("verification_status") or "unresolved_first_live_candidate"),
            })
    return out


def _match_window(confirm: float) -> Tuple[float, float]:
    # Align with V1 goal match window [board-180, board+15]
    return confirm - 180.0, confirm + 15.0


def apply_action_overlays(
    candidates: Sequence[Dict[str, Any]],
    overlays: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    out = [dict(c) for c in candidates]
    for cand in out:
        if not cand.get("single_goal_increment"):
            continue
        confirm = float(cand["score_confirmation_sec"])
        lo, hi = _match_window(confirm)
        best = None
        for ov in overlays:
            sb = ov.get("score_before")
            sa = ov.get("score_after")
            if sb is not None and list(sb) != list(cand["score_before"]):
                continue
            if sa is not None and list(sa) != list(cand["score_after"]):
                continue
            # optional confirm proximity
            oc = ov.get("score_confirmation_sec")
            if oc is not None and abs(float(oc) - confirm) > 5.0:
                continue
            action = ov.get("goal_action_sec")
            interval = ov.get("goal_action_interval") or {}
            if action is None and interval.get("media_in") is not None:
                action = interval.get("media_in")
            if action is None:
                continue
            action_f = float(action)
            # Prefer action inside V1 match window; else try interval end inside window
            if not (lo <= action_f <= hi):
                mo = interval.get("media_out")
                if mo is not None and lo <= float(mo) <= hi:
                    action_f = float(mo)
                elif interval.get("media_in") is not None and lo <= float(interval["media_in"]) <= hi:
                    action_f = float(interval["media_in"])
                else:
                    cand.setdefault("notes", []).append(
                        f"overlay_action_outside_v1_match_window:{action}"
                    )
                    continue
            # Must not equal confirmation (board ≠ action)
            if abs(action_f - confirm) < 0.5:
                cand.setdefault("notes", []).append("overlay_rejected_equals_score_confirm")
                continue
            best = (ov, action_f)
            break
        if best:
            ov, action_f = best
            cand["goal_action_sec"] = round(action_f, 3)
            cand["goal_action_interval"] = ov.get("goal_action_interval") or {
                "media_in": action_f,
                "media_out": min(confirm - 1.0, action_f + 8.0),
            }
            cand["is_replay"] = bool(ov.get("is_replay", False))
            cand["evidence_sources"] = list(dict.fromkeys(
                list(cand.get("evidence_sources") or []) + [str(ov.get("source") or "overlay")]
            ))
            cand["verification_status"] = ov.get("verification_status") or "action_from_overlay"
            cand.setdefault("notes", []).append("goal_action_from_live_overlay_not_scoreboard")
    return out


def provisional_action_from_nearby_events(
    candidates: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Weak event-only prior when no overlay: last LIVE Shot/Corner before confirm in window.

    Never uses score_confirmation_sec itself.
    """
    out = [dict(c) for c in candidates]
    for cand in out:
        if cand.get("goal_action_sec") is not None:
            continue
        if not cand.get("single_goal_increment"):
            continue
        confirm = float(cand["score_confirmation_sec"])
        lo, hi = _match_window(confirm)
        ranked = []
        for ev in cand.get("nearby_events") or []:
            if ev.get("is_replay"):
                continue
            t = float(ev["media_sec"])
            if not (lo <= t <= min(hi, confirm - 1.0)):
                continue
            typ = ev.get("event_type")
            rank = {"Shot": 0, "Corner_kick": 1, "Free_kick": 2, "Dribble_past": 3}.get(str(typ), 9)
            if rank >= 9:
                continue
            ranked.append((rank, -t, ev))
        if not ranked:
            continue
        ranked.sort()
        ev = ranked[0][2]
        cand["goal_action_sec"] = round(float(ev["media_sec"]), 3)
        cand["goal_action_interval"] = {
            "media_in": round(float(ev["media_sec"]) - 2.0, 3),
            "media_out": round(min(confirm - 1.0, float(ev["media_sec"]) + 6.0), 3),
        }
        cand["evidence_sources"] = list(dict.fromkeys(
            list(cand.get("evidence_sources") or []) + ["nearby_detector_event"]
        ))
        cand["verification_status"] = "provisional_from_nearby_event"
        cand["provisional_event_id"] = ev.get("event_id")
        cand.setdefault("notes", []).append(
            f"weak_prior_from_{ev.get('event_type')}; not ball-over-line proof"
        )
    return out


def link_strip_chains(
    candidates: Sequence[Dict[str, Any]],
    strip: Dict[str, Any],
) -> List[Dict[str, Any]]:
    chains = strip.get("chains") or []
    out = [dict(c) for c in candidates]
    for cand in out:
        action = cand.get("goal_action_sec")
        confirm = float(cand["score_confirmation_sec"])
        center = float(action) if action is not None else confirm - 30.0
        linked = []
        for i, ch in enumerate(chains):
            t0 = ch.get("t0_ms")
            t1 = ch.get("t1_ms")
            if t0 is None or t1 is None:
                continue
            s0, s1 = float(t0) / 1000.0, float(t1) / 1000.0
            if s1 < center - 60.0 or s0 > confirm + 5.0:
                continue
            linked.append({
                "strip_index": i,
                "clip_id": ch.get("clip_id"),
                "chain_category": ch.get("chain_category"),
                "template_id": ch.get("template_id"),
                "t0_sec": s0,
                "t1_sec": s1,
                "event_ids": ch.get("event_ids") or [],
            })
        linked.sort(key=lambda x: abs(0.5 * (x["t0_sec"] + x["t1_sec"]) - center))
        cand["linked_strip_chain_ids"] = linked[:5]
    return out


def default_g22_overlay_paths(match_tag: str) -> List[Path]:
    root = Path("/data2/lpy1/_story_va_outputs/v2/cross_match_g2/g22_first_live") / match_tag / "roles"
    paths = []
    if root.is_dir():
        for role in ("opening_deficit", "equalizer", "go_ahead"):
            p = root / role / "role_first_live_pack.json"
            if p.is_file():
                paths.append(p)
    return paths


def build_b_opening_p3_overlay() -> Dict[str, Any]:
    """Reuse verified B 3132–3146 LIVE localization (not gold causal)."""
    return {
        "score_before": [1, 1],
        "score_after": [2, 1],
        "score_confirmation_sec": 3199.66,
        "goal_action_sec": 3133.5,
        "goal_action_interval": {"media_in": 3132.0, "media_out": 3146.0},
        "is_replay": False,
        "source": "v3_p3_p4_b_opening_possible_first_live",
        "verification_status": "possible_first_live_video_supported",
        "note": "P3/P4 dense LIVE window; board flip ~3140–3144; confirm 3199.66 ≠ action",
    }


def recover_match_goals(
    *,
    events_path: Path,
    strip_path: Optional[Path] = None,
    overlay_paths: Optional[Sequence[Path]] = None,
    extra_overlays: Optional[Sequence[Dict[str, Any]]] = None,
    out_path: Optional[Path] = None,
) -> Dict[str, Any]:
    raw = load_raw_events(events_path)
    cands = recover_goal_candidates(raw)
    # Prefer explicit LIVE overlays (e.g. P3/P4) over G2.2 packs.
    overlays = list(extra_overlays or []) + load_action_overlays(overlay_paths or [])
    cands = apply_action_overlays(cands, overlays)
    cands = provisional_action_from_nearby_events(cands)
    strip = {}
    if strip_path and Path(strip_path).is_file():
        strip = json.loads(Path(strip_path).read_text(encoding="utf-8"))
        cands = link_strip_chains(cands, strip)
    payload = {
        "schema": "v3_goal_recovery_v1",
        "n_candidates": len(cands),
        "n_single_goal": sum(1 for c in cands if c.get("single_goal_increment")),
        "n_with_goal_action_sec": sum(1 for c in cands if c.get("goal_action_sec") is not None),
        "candidates": cands,
        "paid_api_calls": 0,
        "forbidden_inputs": ["*_causal.json", "strip_gold.json"],
        "render_ready": False,
        "note": "score_confirmation_sec is never copied into goal_action_sec",
    }
    if out_path:
        dump(Path(out_path), payload)
    return payload
