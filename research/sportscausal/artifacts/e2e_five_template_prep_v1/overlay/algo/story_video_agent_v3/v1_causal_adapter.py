"""V3 adapter: frozen 8.31 predicted strips → V1 `schema_version=1.0-min` causal JSON.

Never reads human `*_causal.json` / gold. Never invents Goal `t_ms` or Goal event rows.
Missing goal terminals are emitted as explicit unresolved placeholders only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .pipeline import dump

# Detector / enriched-atom English → V1 Chinese labels.
# Goal/Assist only when present as real event_type rows (e.g. atom fill); never invented here.
_EN_TO_ZH = {
    "Pass": "传球",
    "Shot": "射门",
    "Goal": "进球",
    "Own_goal": "乌龙球",
    "Assist": "助攻",
    "Save": "扑救",
    "Corner_kick": "角球",
    "Free_kick": "任意球",
    "Throw_in": "界外球",
    "Ball_possession": "控球",
    "Defensive_action": "防守动作",
    "Dribble_past": "过人",
    "Foul_Being_fouled": "犯规/被犯规",
    "Win_an_aerial_duel": "争顶成功",
    "Receive_a_card": "吃牌",
    "Substitution": "换人",
    "Referees_decision": "裁判判罚",
    "Lineup": "首发阵容",
    "Offside": "越位",
    "Cross": "传中",
    "Interception": "拦截",
    "Clearance": "解围",
    "Tackle": "铲球",
}

_CAT_EN_TO_ZH = {
    "outcome": "结果链",
    "danger": "险情链",
    "correction": "修正链",
    "special": "特殊链",
    "结果链": "结果链",
    "险情链": "险情链",
    "修正链": "修正链",
    "特殊链": "特殊链",
}


def _parse_score_token(tok: Any) -> Optional[Tuple[int, int]]:
    if tok is None:
        return None
    s = str(tok).strip().replace("：", ":").replace("-", ":").replace("–", ":")
    m = re.match(r"^(\d+)\s*:\s*(\d+)$", s)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def score_pair_from_raw_event(e: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    """Decode broadcast score cues using existing V2 event-adapter precedence.

    Historical raw-event formats put the same scoreboard under either
    attributes.Score_Recognition or scores.score_recognition, as a string or
    list. These are OBSERVED board states, not goal action timestamps.
    """
    attrs = e.get("attributes") if isinstance(e.get("attributes"), dict) else {}
    scores = e.get("scores") if isinstance(e.get("scores"), dict) else {}
    for candidate in (attrs.get("Score_Recognition"), scores.get("score_recognition")):
        if isinstance(candidate, list):
            candidate = candidate[0] if candidate else None
        if candidate is None:
            continue
        parsed = _parse_score_token(candidate)
        if parsed is not None:
            return parsed
    return None


def load_raw_events(events_path: Path) -> List[Dict[str, Any]]:
    data = json.loads(Path(events_path).read_text(encoding="utf-8"))
    rows = data.get("events") if isinstance(data, dict) else data
    return list(rows or [])


def score_transitions_from_events(raw_events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Board transitions from raw Score_Recognition only (not gold goals)."""
    out: List[Dict[str, Any]] = []
    prev: Optional[Tuple[int, int]] = None
    for e in raw_events:
        cur = score_pair_from_raw_event(e)
        if cur is None:
            continue
        if prev is None:
            prev = cur
            continue
        if cur == prev:
            continue
        mt = e.get("media_time") or {}
        t = mt.get("event_time_sec")
        if t is None:
            t = mt.get("start_time_sec")
        d0, d1 = cur[0] - prev[0], cur[1] - prev[1]
        single = (d0 + d1 == 1) and min(d0, d1) == 0 and max(d0, d1) == 1
        out.append({
            "score_before": list(prev),
            "score_after": list(cur),
            "delta": [d0, d1],
            "single_goal_increment": single,
            "score_confirmation_sec": float(t) if t is not None else None,
            "carrier_event_id": e.get("event_id"),
            "carrier_event_type": e.get("event_type"),
            "goal_action_sec": None,
            "goal_event_id": None,
            "status": "unresolved_goal_action",
            "note": (
                "Scoreboard transition observed in raw events; detector stream has no Goal "
                "terminal. Do NOT fill human causal Goal t_ms here."
            ),
        })
        prev = cur
    return out


def _index_raw(raw_events: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for e in raw_events:
        eid = e.get("event_id")
        if eid is None:
            continue
        mt = e.get("media_time") or {}
        t = mt.get("event_time_sec")
        if t is None:
            t = mt.get("start_time_sec")
        out[str(eid)] = {
            "event_id": str(eid),
            "event_type": e.get("event_type"),
            "event_time_sec": float(t) if t is not None else None,
            "media_start_sec": float(mt["start_time_sec"]) if mt.get("start_time_sec") is not None else None,
            "media_end_sec": float(mt["end_time_sec"]) if mt.get("end_time_sec") is not None else None,
            "is_replay": bool((e.get("video_context") or {}).get("is_replay")),
            "broadcast_phase": (e.get("video_context") or {}).get("broadcast_phase"),
            "score_pair": _parse_score_token(((e.get("attributes") or {}).get("Score_Recognition") or [None])[0]),
        }
    return out


def _zh_type(en_or_zh: Any) -> str:
    s = str(en_or_zh or "").strip()
    if not s:
        return "未知"
    if s in _EN_TO_ZH:
        return _EN_TO_ZH[s]
    # already Chinese or unknown — pass through without inventing 进球
    if s in {"进球", "乌龙球", "头球破门"}:
        # Should never appear from detector; keep but mark upstream if seen
        return s
    return _EN_TO_ZH.get(s, s)


def _chain_events_from_ids(
    event_ids: Sequence[Any],
    raw_by_id: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    rows = []
    order = 0
    for eid in event_ids or []:
        raw = raw_by_id.get(str(eid))
        if not raw or raw.get("event_time_sec") is None:
            continue
        en = raw.get("event_type")
        zh = _zh_type(en)
        t_ms = float(raw["event_time_sec"]) * 1000.0
        rows.append({
            "event_id": str(eid),
            "order": order,
            "type": zh,
            "type_en": str(en) if en is not None else None,
            "t_ms": t_ms,
            "bz_id": "",
            "source": "raw_events+8.31_strip",
            "verification_status": "unverified",
        })
        order += 1
    return rows


def build_outcome_chains_from_recovered_goals(
    *,
    recovered_goals: Sequence[Dict[str, Any]],
    raw_by_id: Dict[str, Dict[str, Any]],
    start_ann_index: int = 0,
) -> List[Dict[str, Any]]:
    """Attach V3-recovered LIVE Goal terminals as 结果链 without mutating 8.31 strip JSON.

    If linked strip antecedents exist with Shot/Corner/etc., prepend them; otherwise
    emit a standalone Goal terminal (no invented causal predecessors).
    """
    chains: List[Dict[str, Any]] = []
    for i, g in enumerate(recovered_goals):
        if not g.get("single_goal_increment"):
            continue
        action = g.get("goal_action_sec")
        if action is None:
            continue
        confirm = float(g["score_confirmation_sec"])
        if abs(float(action) - confirm) < 0.5:
            continue  # refuse board-as-action
        if g.get("is_replay"):
            continue  # final EDL path: live only
        ante: List[Dict[str, Any]] = []
        linked = g.get("linked_strip_chain_ids") or []
        used_ids = set()
        if linked:
            # Take closest strip's pre-goal detector events (no Goal invention there)
            top = linked[0]
            for eid in top.get("event_ids") or []:
                raw = raw_by_id.get(str(eid))
                if not raw or raw.get("event_time_sec") is None:
                    continue
                if float(raw["event_time_sec"]) > float(action) + 0.5:
                    continue
                if str(eid) in used_ids:
                    continue
                used_ids.add(str(eid))
                en = raw.get("event_type")
                ante.append({
                    "event_id": str(eid),
                    "order": len(ante),
                    "type": _zh_type(en),
                    "type_en": str(en) if en is not None else None,
                    "t_ms": float(raw["event_time_sec"]) * 1000.0,
                    "bz_id": "",
                    "source": "8.31_strip_antecedent",
                    "verification_status": "unverified",
                })
            # Keep last few antecedents only
            if len(ante) > 6:
                ante = ante[-6:]
                for j, e in enumerate(ante):
                    e["order"] = j
        # Also include nearby Shot/Corner before action if not already present
        for ev in g.get("nearby_events") or []:
            if ev.get("is_replay"):
                continue
            if ev.get("event_type") not in {"Shot", "Corner_kick", "Free_kick"}:
                continue
            t = float(ev["media_sec"])
            if t > float(action) + 0.5 or t < float(action) - 90.0:
                continue
            eid = str(ev.get("event_id"))
            if eid in used_ids:
                continue
            used_ids.add(eid)
            ante.append({
                "event_id": eid,
                "order": len(ante),
                "type": _zh_type(ev.get("event_type")),
                "type_en": ev.get("event_type"),
                "t_ms": t * 1000.0,
                "bz_id": "",
                "source": "nearby_detector_event",
                "verification_status": "unverified",
            })
        goal_id = f"v3_goal_{g.get('candidate_id')}"
        goal_ev = {
            "event_id": goal_id,
            "order": len(ante),
            "type": "进球",
            "type_en": "Goal",
            "t_ms": float(action) * 1000.0,
            "bz_id": "",
            "source": "v3_goal_recovery",
            "verification_status": g.get("verification_status"),
            "score_before": g.get("score_before"),
            "score_after": g.get("score_after"),
            "score_confirmation_sec": confirm,
            "is_replay": False,
        }
        events = ante + [goal_ev]
        for j, e in enumerate(events):
            e["order"] = j
        has_ante = len(ante) > 0
        ann = f"v3_outcome_{start_ann_index + i:04d}"
        chains.append({
            "annotation_id": ann,
            "bz_id": "",
            "chain_category": "结果链",
            "causal_chain_subtype": "V3进球恢复链" if has_ante else "V3独立进球终端",
            "causal_chain_other_name": "",
            "is_replay": False,
            "segment_time_sketch": "",
            "segment_time_video": "",
            "events": events,
            "prediction_source": "v3_goal_recovery+optional_8.31_antecedent",
            "strip_clip_id": (linked[0].get("clip_id") if linked else None),
            "template_id": (linked[0].get("template_id") if linked else None),
            "t0_ms": events[0]["t_ms"],
            "t1_ms": goal_ev["t_ms"],
            "verification_status": g.get("verification_status"),
            "human_causal_relation": None,
            "causal_relation_proven": has_ante,
            "goal_candidate_id": g.get("candidate_id"),
            "live_only": True,
            "note": (
                "Outcome chain synthesized in V3 adapter; 8.31 strip file unchanged. "
                "Standalone Goal when antecedents unproven."
                if not has_ante else
                "Antecedents linked from 8.31/nearby detector events; relation unverified."
            ),
        })
    return chains


def strip_chains_to_v1_causal(
    *,
    strip: Dict[str, Any],
    raw_events: Sequence[Dict[str, Any]],
    match_id: str,
    video_name: str,
    team_1_name: str = "",
    team_2_name: str = "",
    team_1_color: str = "",
    team_2_color: str = "",
    recovered_goals: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build a V1-shaped causal document from 8.31 strip + optional V3 Goal recovery."""
    raw_by_id = _index_raw(raw_events)
    transitions = score_transitions_from_events(raw_events)

    covered_ids = set()
    chains_out: List[Dict[str, Any]] = []
    cat_counts = {"结果链": 0, "险情链": 0, "修正链": 0, "特殊链": 0, "其他": 0}
    n_goal_terminals = 0

    for i, c in enumerate(strip.get("chains") or []):
        cat_en = str(c.get("chain_category") or c.get("predicted_category") or "special")
        cat_zh = _CAT_EN_TO_ZH.get(cat_en, "特殊链")
        eids = c.get("event_ids") or c.get("source_event_ids") or []
        evs = _chain_events_from_ids(eids, raw_by_id)
        for e in evs:
            covered_ids.add(e["event_id"])
            if e.get("type") in {"进球", "乌龙球", "头球破门"}:
                n_goal_terminals += 1
        # is_replay: prefer raw majority; default False (unknown ≠ invent replay)
        replay_flags = [raw_by_id[str(x)].get("is_replay") for x in eids if str(x) in raw_by_id]
        is_replay = bool(replay_flags) and all(replay_flags)
        t0 = c.get("t0_ms")
        t1 = c.get("t1_ms")
        chains_out.append({
            "annotation_id": f"pred_{i:04d}",
            "bz_id": "",
            "chain_category": cat_zh,
            "causal_chain_subtype": str(c.get("template_id") or c.get("predicted_template_id") or ""),
            "causal_chain_other_name": "",
            "is_replay": is_replay,
            "segment_time_sketch": "",
            "segment_time_video": (
                f"{int(t0)//60000:02d}：{(int(t0)//1000)%60:02d}-"
                f"{int(t1)//60000:02d}：{(int(t1)//1000)%60:02d}"
                if t0 is not None and t1 is not None else ""
            ),
            "events": evs,
            # V3 provenance (V1 ignores unknown keys)
            "prediction_source": "causal_chain6_predicted",
            "strip_clip_id": c.get("clip_id") or c.get("strip_chain_id"),
            "template_id": c.get("template_id") or c.get("predicted_template_id"),
            "t0_ms": t0,
            "t1_ms": t1,
            "verification_status": "unverified",
            "human_causal_relation": None,
        })
        cat_counts[cat_zh] = cat_counts.get(cat_zh, 0) + 1

    outcome_chains = build_outcome_chains_from_recovered_goals(
        recovered_goals=recovered_goals or [],
        raw_by_id=raw_by_id,
        start_ann_index=len(chains_out),
    )
    for ch in outcome_chains:
        chains_out.append(ch)
        cat_counts["结果链"] = cat_counts.get("结果链", 0) + 1
        for e in ch.get("events") or []:
            if e.get("type") in {"进球", "乌龙球", "头球破门"}:
                n_goal_terminals += 1

    n_raw = len(raw_by_id)
    coverage = (len(covered_ids) / n_raw) if n_raw else 0.0
    if recovered_goals:
        n_resolved = sum(
            1 for g in recovered_goals
            if g.get("single_goal_increment") and g.get("goal_action_sec") is not None
        )
        n_unresolved = sum(
            1 for g in recovered_goals
            if g.get("single_goal_increment") and g.get("goal_action_sec") is None
        )
    else:
        n_resolved = 0
        n_unresolved = sum(1 for t in transitions if t.get("single_goal_increment"))

    doc = {
        "schema_version": "1.0-min",
        "match_id": match_id,
        "video_name": video_name,
        "team_1_name": team_1_name,
        "team_2_name": team_2_name,
        "team_1_color": team_1_color,
        "team_2_color": team_2_color,
        "causal_chains": chains_out,
        "v3_adapter": {
            "schema": "v3_v1_causal_adapter_v1",
            "prediction_source": "causal_chain6_predicted+v3_goal_recovery",
            "forbidden_inputs": ["*_causal.json", "strip_gold.json", "human Goal t_ms"],
            "n_raw_events": n_raw,
            "n_unique_events_in_chains": len(covered_ids),
            "event_id_coverage": round(coverage, 6),
            "category_counts_zh": cat_counts,
            "n_goal_terminals_in_adapted_chains": n_goal_terminals,
            "n_v3_outcome_chains": len(outcome_chains),
            "n_outcome_chains_en_from_strip": sum(
                1 for c in (strip.get("chains") or [])
                if str(c.get("chain_category") or "").lower() == "outcome"
            ),
            "score_transitions": transitions,
            "n_score_transitions": len(transitions),
            "n_recovered_goal_actions": n_resolved,
            "n_unresolved_goal_actions": n_unresolved,
            "strip_file_mutated": False,
            "gaps": [
                g for g in [
                    "detector_events_have_no_native_Goal_type",
                    "8.31_strip_outcome_still_zero_without_v3_injection",
                    None if n_resolved else "some_or_all_goal_actions_still_unresolved",
                ] if g
            ],
            "render_ready": False,
            "note": (
                "V3 injects LIVE Goal 结果链 from recovered action times; "
                "8.31 strip JSON left unchanged. Replay goals excluded."
            ),
        },
    }
    return doc


def build_from_paths(
    *,
    strip_path: Path,
    events_path: Path,
    out_path: Path,
    match_id: str,
    video_name: str,
    team_1_name: str = "",
    team_2_name: str = "",
    recovered_goals: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    strip = json.loads(Path(strip_path).read_text(encoding="utf-8"))
    # Refuse gold-shaped strip payloads
    if "causal_chains" in strip and strip.get("schema_version") == "1.0-min":
        raise RuntimeError("Refusing human causal JSON as strip input")
    if strip.get("mode") == "gold_clips" or "strip_gold" in str(strip.get("schema") or ""):
        raise RuntimeError("Refusing gold_clips / strip_gold as strip input")
    raw = load_raw_events(events_path)
    doc = strip_chains_to_v1_causal(
        strip=strip,
        raw_events=raw,
        match_id=match_id,
        video_name=video_name,
        team_1_name=team_1_name,
        team_2_name=team_2_name,
        recovered_goals=recovered_goals,
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    dump(out, doc)
    return doc
