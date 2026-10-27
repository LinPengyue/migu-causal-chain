"""Phase 3A：Story Verifier — 比分/归属/时序/回放/视觉证据一致性。

明确区分：
- rule_fact：T01/score_path/事件字段可支持的规则事实
- vlm_observation：真实 VLM（provider_mode real/cache）观察
- verified：已核证（本阶段稀缺）
- mock：合成/fixture，不得 used_as_fact
- unresolved_conflict：冲突未解
"""

from __future__ import annotations

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
    if mode == "mock" or ev.get("is_mock") or str(ev.get("notes") or "").startswith("mock"):
        kind = "mock"
        used_as_fact = False
    elif mode in ("real", "cache") and ev.get("normalized_ok"):
        kind = "vlm_observation"
        used_as_fact = False  # 观察 ≠ 已核实事实
    elif mode in ("real", "cache"):
        kind = "vlm_observation"
    elif ev.get("fact_verified") or ev.get("kind") == "verified":
        kind = "verified"
        used_as_fact = True
    elif ev.get("kind") == "rule_fact":
        kind = "rule_fact"
        used_as_fact = True
    if ev.get("conflict") or ev.get("failure_status"):
        if kind != "mock":
            kind = "unresolved_conflict"
            used_as_fact = False
    return {
        "gap_id": ev.get("gap_id"),
        "kind": kind,
        "used_as_fact": used_as_fact,
        "provider_mode": mode or None,
        "frame_ids": list(ev.get("frame_ids") or []),
        "normalized_ok": bool(ev.get("normalized_ok")),
        "message": ev.get("message") or ev.get("notes") or "",
    }


def verify_story(
    story: Dict[str, Any],
    *,
    visual_evidence: Optional[Sequence[Dict[str, Any]]] = None,
    causal: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """核对比分轨迹、球队归属、进球/时序、回放标记与视觉证据。"""
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

    # --- 比分轨迹单调与归属 ---
    prev_t = -1.0
    prev_pair: Optional[Tuple[int, int]] = None
    for i, node in enumerate(scores):
        t = float(node.get("t_sec") or -1)
        pair = _parse_score(str(node.get("score") or ""))
        ok_time = t >= prev_t - 1e-6
        checks.append(
            {
                "id": f"score_time_{i}",
                "ok": ok_time,
                "detail": f"t_sec={t} vs prev={prev_t}",
            }
        )
        if not ok_time:
            conflicts.append(
                {
                    "type": "score_path_time_regression",
                    "index": i,
                    "t_sec": t,
                    "prev": prev_t,
                }
            )
        if pair and prev_pair:
            # 单侧进球：总和 +1 且一侧不减
            total_ok = (pair[0] + pair[1]) >= (prev_pair[0] + prev_pair[1])
            nonneg = pair[0] >= prev_pair[0] and pair[1] >= prev_pair[1]
            ok_score = total_ok and nonneg
            checks.append(
                {
                    "id": f"score_progress_{i}",
                    "ok": ok_score,
                    "detail": f"{prev_pair}->{pair}",
                }
            )
            if not ok_score:
                conflicts.append(
                    {
                        "type": "score_path_illegal_transition",
                        "from": prev_pair,
                        "to": pair,
                    }
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

    # 主角侧与翻盘弧（story/candidate）
    if tier in ("story", "candidate") and side in ("left", "right"):
        rule_facts.append(
            {
                "kind": "rule_fact",
                "used_as_fact": True,
                "fact": "protagonist_side",
                "side": side,
            }
        )
        # 是否出现过落后→扳平/反超
        deficits = []
        for node in scores:
            pair = _parse_score(str(node.get("score") or ""))
            if not pair:
                continue
            margin = pair[0] - pair[1] if side == "left" else pair[1] - pair[0]
            deficits.append((float(node.get("t_sec") or 0), margin, node.get("score")))
        saw_behind = any(m < 0 for _, m, _ in deficits)
        saw_equal_or_lead = any(m >= 0 for _, m, _ in deficits[1:] or deficits)
        ok_arc = saw_behind and any(m >= 0 for _, m, _ in deficits)
        checks.append(
            {
                "id": "comeback_arc",
                "ok": ok_arc if tier == "story" else True,
                "detail": f"behind={saw_behind} recover={saw_equal_or_lead} points={deficits}",
            }
        )
        if tier == "story" and not ok_arc:
            conflicts.append({"type": "story_tier_without_comeback_arc", "side": side})

    # --- 事件：进球动作、回放、时序 ---
    live_times: List[float] = []
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
        elif t_sec is not None:
            if live_times and t_sec + 1e-3 < live_times[-1]:
                # 不强制全局排序冲突（拆条可能乱序），仅记录
                checks.append(
                    {
                        "id": f"live_order_{eid}",
                        "ok": False,
                        "detail": f"live t={t_sec} < prev={live_times[-1]}",
                    }
                )
            live_times.append(t_sec)

    # recognition beats vs event existence / role
    beats = ((story.get("recognition") or {}).get("beats") or {})
    for beat, ids in beats.items():
        for eid in ids or []:
            ev = events.get(str(eid))
            if ev is None:
                conflicts.append(
                    {
                        "type": "beat_event_missing",
                        "beat": beat,
                        "event_id": eid,
                    }
                )
                continue
            role = ev.get("story_role")
            if role and role != beat and not ev.get("is_replay"):
                checks.append(
                    {
                        "id": f"role_mismatch_{eid}",
                        "ok": False,
                        "detail": f"beat={beat} story_role={role}",
                    }
                )
            # 回放不应作为唯一铺垫/高潮主证据而不声明
            if ev.get("is_replay") and beat in ("铺垫", "转折", "高潮"):
                checks.append(
                    {
                        "id": f"replay_as_primary_candidate_{eid}",
                        "ok": False,
                        "detail": f"replay event listed in recognition beat {beat}",
                    }
                )

    # causal teams (optional)
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

    # --- 视觉证据 ---
    for raw in visual_evidence or []:
        if not isinstance(raw, dict):
            continue
        classified = classify_visual_evidence(raw)
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
            # VLM 与比分事件粗冲突：已在 classify 中
            if classified.get("normalized_ok") is False:
                conflicts.append(
                    {
                        "type": "visual_not_normalized",
                        "gap_id": classified.get("gap_id"),
                    }
                )

    # mock 不得混入 rule_facts
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
            c for c in conflicts if c.get("type", "").startswith("visual")
        ]
        + [o for o in observations if o.get("kind") == "unresolved_conflict"],
        "notes": [
            "Mock evidence is never treated as real factual basis.",
            "VLM observations are not automatically verified facts.",
        ],
    }
