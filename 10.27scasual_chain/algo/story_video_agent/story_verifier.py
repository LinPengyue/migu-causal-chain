"""Phase 3A.1：Story Verifier — 比分/归属/时序/回放/视觉证据一致性。

`verified` 仅能由可信校验流水线（pipeline_verified）产生；
外部 JSON 的 fact_verified=true 一律视为不可信声明。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _event_index(story: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        str(e.get("event_id")): e
        for e in (story.get("events") or [])
        if isinstance(e, dict) and e.get("event_id")
    }


def _score_nodes(story: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [n for n in (story.get("score_path") or []) if isinstance(n, dict)]


def _parse_score(score: str) -> Optional[Tuple[int, int]]:
    if not isinstance(score, str) or ":" not in score:
        return None
    a, b = score.split(":", 1)
    try:
        return int(a), int(b)
    except ValueError:
        return None


def classify_visual_evidence(ev: Dict[str, Any]) -> Dict[str, Any]:
    """将 Video Agent 视觉证据条目标注来源种类。"""
    mode = str(ev.get("provider_mode") or ev.get("provider") or "")
    kind = "unresolved_conflict"
    used_as_fact = False
    pipeline_verified = bool(ev.get("pipeline_verified"))

    # 外部伪造 verified：无 pipeline_verified 则降级并记录
    forged = False
    if ev.get("fact_verified") and not pipeline_verified:
        forged = True

    if mode == "mock" or ev.get("is_mock") or str(ev.get("notes") or "").startswith("mock"):
        kind = "mock"
        used_as_fact = False
        pipeline_verified = False
    elif pipeline_verified and ev.get("normalized_ok"):
        kind = "verified"
        used_as_fact = True
    elif mode in ("real", "cache") and ev.get("normalized_ok"):
        kind = "vlm_observation"
        used_as_fact = False
    elif mode in ("real", "cache"):
        kind = "vlm_observation"
    elif ev.get("kind") == "rule_fact":
        kind = "rule_fact"
        used_as_fact = True
    elif forged:
        kind = "unresolved_conflict"
        used_as_fact = False

    if ev.get("conflict") or ev.get("failure_status"):
        if kind != "mock":
            kind = "unresolved_conflict"
            used_as_fact = False
            pipeline_verified = False

    return {
        "gap_id": ev.get("gap_id"),
        "kind": kind,
        "used_as_fact": used_as_fact,
        "pipeline_verified": pipeline_verified,
        "forged_verified_flag": forged,
        "provider_mode": mode or None,
        "frame_ids": list(ev.get("frame_ids") or []),
        "normalized_ok": bool(ev.get("normalized_ok")),
        "message": ev.get("message") or ev.get("notes") or "",
    }


def check_narration_grounding(plan: Dict[str, Any]) -> Dict[str, Any]:
    """检查 LLM/叙事是否引入证据未支持的比分或精确时间声称。"""
    allowed_scores = set()
    for ref in plan.get("evidence_refs") or []:
        if isinstance(ref, dict) and ref.get("score"):
            allowed_scores.add(str(ref["score"]))
    for node in (plan.get("diagnostics") or {}).get("verification", {}).get("rule_facts") or []:
        if node.get("score"):
            allowed_scores.add(str(node["score"]))
    # also from segments evidence
    for seg in plan.get("segments") or []:
        for ref in seg.get("evidence_refs") or []:
            if isinstance(ref, dict) and ref.get("score"):
                allowed_scores.add(str(ref["score"]))

    texts: List[str] = []
    narr = plan.get("narration") or {}
    if narr.get("summary"):
        texts.append(str(narr["summary"]))
    for v in (narr.get("by_beat") or {}).values():
        texts.append(str(v))
    for seg in plan.get("segments") or []:
        if seg.get("narration"):
            texts.append(str(seg["narration"]))
    blob = "\n".join(texts)

    score_hits = set(re.findall(r"\b\d+:\d+\b", blob))
    ungrounded_scores = sorted(s for s in score_hits if s not in allowed_scores and s not in {"0:0"})
    # 精确到毫秒的伪时间声称
    fake_precision = bool(re.search(r"\d+\.\d{4,}s", blob))
    return {
        "allowed_scores": sorted(allowed_scores),
        "mentioned_scores": sorted(score_hits),
        "ungrounded": ungrounded_scores,
        "fake_precision_time": fake_precision,
        "ok": not ungrounded_scores and not fake_precision,
    }


def verify_story(
    story: Dict[str, Any],
    *,
    visual_evidence: Optional[Sequence[Dict[str, Any]]] = None,
    causal: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []
    rule_facts: List[Dict[str, Any]] = []
    observations: List[Dict[str, Any]] = []
    mock_items: List[Dict[str, Any]] = []

    tier = story.get("story_tier") or (story.get("recognition") or {}).get("tier") or "none"
    side = story.get("protagonist_side") or (story.get("recognition") or {}).get(
        "protagonist_side"
    )
    events = _event_index(story)
    scores = _score_nodes(story)

    prev_t = -1.0
    prev_pair: Optional[Tuple[int, int]] = None
    for i, node in enumerate(scores):
        t = float(node.get("t_sec") or -1)
        pair = _parse_score(str(node.get("score") or ""))
        ok_time = t >= prev_t - 1e-6
        checks.append(
            {"id": f"score_time_{i}", "ok": ok_time, "detail": f"t_sec={t} vs prev={prev_t}"}
        )
        if not ok_time:
            conflicts.append(
                {"type": "score_path_time_regression", "index": i, "t_sec": t, "prev": prev_t}
            )
        if pair and prev_pair:
            total_ok = (pair[0] + pair[1]) >= (prev_pair[0] + prev_pair[1])
            nonneg = pair[0] >= prev_pair[0] and pair[1] >= prev_pair[1]
            ok_score = total_ok and nonneg
            checks.append(
                {"id": f"score_progress_{i}", "ok": ok_score, "detail": f"{prev_pair}->{pair}"}
            )
            if not ok_score:
                conflicts.append(
                    {"type": "score_path_illegal_transition", "from": prev_pair, "to": pair}
                )
            delta = node.get("delta_side")
            if delta == "left" and pair[0] <= prev_pair[0]:
                conflicts.append({"type": "delta_side_mismatch", "node": i, "side": "left"})
            if delta == "right" and pair[1] <= prev_pair[1]:
                conflicts.append({"type": "delta_side_mismatch", "node": i, "side": "right"})
        if pair:
            rule_facts.append(
                {
                    "kind": "rule_fact",
                    "used_as_fact": True,
                    "fact": "score_node",
                    "t_sec": t,
                    "score": node.get("score"),
                    "delta_side": node.get("delta_side"),
                    "carrier_event_id": node.get("carrier_event_id"),
                }
            )
            prev_pair = pair
        prev_t = max(prev_t, t)

    if tier in ("story", "candidate") and side in ("left", "right"):
        rule_facts.append(
            {
                "kind": "rule_fact",
                "used_as_fact": True,
                "fact": "protagonist_side",
                "side": side,
            }
        )
        deficits = []
        for node in scores:
            pair = _parse_score(str(node.get("score") or ""))
            if not pair:
                continue
            margin = pair[0] - pair[1] if side == "left" else pair[1] - pair[0]
            deficits.append((float(node.get("t_sec") or 0), margin, node.get("score")))
        saw_behind = any(m < 0 for _, m, _ in deficits)
        ok_arc = saw_behind and any(m >= 0 for _, m, _ in deficits)
        checks.append(
            {
                "id": "comeback_arc",
                "ok": ok_arc if tier == "story" else True,
                "detail": f"behind={saw_behind} points={deficits}",
            }
        )
        if tier == "story" and not ok_arc:
            conflicts.append({"type": "story_tier_without_comeback_arc", "side": side})

    for eid, ev in events.items():
        is_replay = bool(ev.get("is_replay"))
        t_ms = ev.get("t_ms")
        t_sec = float(t_ms) / 1000.0 if t_ms is not None else None
        rule_facts.append(
            {
                "kind": "rule_fact",
                "used_as_fact": True,
                "fact": "event_meta",
                "event_id": eid,
                "type": ev.get("type"),
                "is_replay": is_replay,
                "story_role": ev.get("story_role"),
                "t_sec": t_sec,
            }
        )
        if is_replay:
            checks.append(
                {
                    "id": f"replay_flag_{eid}",
                    "ok": True,
                    "detail": "replay must not drive primary live timeline",
                }
            )

    beats = ((story.get("recognition") or {}).get("beats") or {})
    for beat, ids in beats.items():
        for eid in ids or []:
            ev = events.get(str(eid))
            if ev is None:
                conflicts.append(
                    {"type": "beat_event_missing", "beat": beat, "event_id": eid}
                )
                continue
            if ev.get("is_replay") and beat in ("铺垫", "转折", "高潮"):
                checks.append(
                    {
                        "id": f"replay_as_primary_candidate_{eid}",
                        "ok": False,
                        "detail": f"replay event listed in recognition beat {beat}",
                    }
                )

    if causal:
        t1 = causal.get("team_1_name") or ""
        t2 = causal.get("team_2_name") or ""
        if t1 or t2:
            rule_facts.append(
                {
                    "kind": "rule_fact",
                    "used_as_fact": True,
                    "fact": "teams",
                    "team_1": t1,
                    "team_2": t2,
                }
            )

    for raw in visual_evidence or []:
        if not isinstance(raw, dict):
            continue
        classified = classify_visual_evidence(raw)
        if classified.get("forged_verified_flag"):
            conflicts.append(
                {
                    "type": "forged_verified_flag",
                    "gap_id": classified.get("gap_id"),
                    "detail": "fact_verified=true without pipeline_verified",
                }
            )
        if classified["kind"] == "mock":
            mock_items.append(classified)
            checks.append(
                {
                    "id": f"mock_excluded_{classified.get('gap_id')}",
                    "ok": True,
                    "detail": "mock evidence excluded from factual basis",
                }
            )
        elif classified["kind"] == "unresolved_conflict":
            conflicts.append(
                {
                    "type": "visual_conflict",
                    "gap_id": classified.get("gap_id"),
                    "message": classified.get("message"),
                }
            )
            observations.append(classified)
        else:
            observations.append(classified)
            if classified.get("normalized_ok") is False:
                conflicts.append(
                    {"type": "visual_not_normalized", "gap_id": classified.get("gap_id")}
                )

    for m in mock_items:
        if m.get("used_as_fact"):
            conflicts.append({"type": "mock_used_as_fact", "gap_id": m.get("gap_id")})

    ok = not conflicts
    return {
        "ok": ok,
        "story_tier": tier,
        "protagonist_side": side,
        "checks": checks,
        "conflicts": conflicts,
        "rule_facts": rule_facts,
        "vlm_observations": [
            o for o in observations if o.get("kind") == "vlm_observation"
        ],
        "mock_evidence": mock_items,
        "unresolved_conflicts": [
            c for c in conflicts if str(c.get("type", "")).startswith("visual")
        ]
        + [o for o in observations if o.get("kind") == "unresolved_conflict"],
        "notes": [
            "Mock evidence is never treated as real factual basis.",
            "VLM observations are not automatically verified facts.",
            "fact_verified without pipeline_verified is forged and rejected.",
        ],
    }
