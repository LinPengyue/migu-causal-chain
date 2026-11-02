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

# Detector English → V1 Chinese labels (non-goal only). No Goal invention.
_EN_TO_ZH = {
    "Pass": "传球",
    "Shot": "射门",
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
    s = str(tok).strip().replace("：", ":")
    m = re.match(r"^(\d+)\s*:\s*(\d+)$", s)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def load_raw_events(events_path: Path) -> List[Dict[str, Any]]:
    data = json.loads(Path(events_path).read_text(encoding="utf-8"))
    rows = data.get("events") if isinstance(data, dict) else data
    return list(rows or [])


def score_transitions_from_events(raw_events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Board transitions from raw Score_Recognition only (not gold goals)."""
    out: List[Dict[str, Any]] = []
    prev: Optional[Tuple[int, int]] = None
    for e in raw_events:
        attrs = e.get("attributes") or {}
        scores = attrs.get("Score_Recognition") or []
        if not scores:
            continue
        cur = _parse_score_token(scores[0])
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
) -> Dict[str, Any]:
    """Build a V1-shaped causal document from 8.31 strip + raw events only."""
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

    n_raw = len(raw_by_id)
    coverage = (len(covered_ids) / n_raw) if n_raw else 0.0

    doc = {
        "schema_version": "1.0-min",
        "match_id": match_id,
        "video_name": video_name,
        "team_1_name": team_1_name,
        "team_2_name": team_2_name,
        "team_1_color": team_1_color,
        "team_2_color": team_2_color,
        "causal_chains": chains_out,
        # Explicit V3 audit section — not consumed by stock V1 as Goal truth
        "v3_adapter": {
            "schema": "v3_v1_causal_adapter_v1",
            "prediction_source": "causal_chain6_predicted",
            "forbidden_inputs": ["*_causal.json", "strip_gold.json", "human Goal t_ms"],
            "n_raw_events": n_raw,
            "n_unique_events_in_chains": len(covered_ids),
            "event_id_coverage": round(coverage, 6),
            "category_counts_zh": cat_counts,
            "n_goal_terminals_in_adapted_chains": n_goal_terminals,
            "n_outcome_chains_en": sum(
                1 for c in (strip.get("chains") or [])
                if str(c.get("chain_category") or "").lower() == "outcome"
            ),
            "score_transitions": transitions,
            "n_score_transitions": len(transitions),
            "n_unresolved_goal_actions": sum(
                1 for t in transitions if t.get("single_goal_increment")
            ),
            "gaps": [
                "detector_events_have_no_Goal_type",
                "8.31_strip_has_zero_outcome_chains_when_no_Goal_terminals",
                "human_causal_Goal_rows_are_annotation_layer_not_detector_rows",
                "V1_GOAL_TYPES_require_Chinese_Goal_terminals_with_t_ms",
            ],
            "render_ready": False,
            "note": (
                "Adapted chains are V1-schema compatible for non-goal structure. "
                "Goal action times remain unresolved; do not copy human causal."
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
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    dump(out, doc)
    return doc
