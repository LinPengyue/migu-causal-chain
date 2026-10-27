"""Phase 3A.1：故事方案 schema — 结构正确 ≠ 可渲染。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

SCHEMA_VERSION = "story-compose-plan-3a.1"
ALGORITHM_ID = "t01_story_composer_phase3a1"
TEMPLATE_ID = "T01_comeback"

BEATS: Tuple[str, ...] = ("铺垫", "蓄力", "转折", "高潮", "收尾")

EVIDENCE_KINDS = frozenset(
    {
        "rule_fact",
        "vlm_observation",
        "verified",
        "mock",
        "unresolved_conflict",
        "unresolved_mapping",
    }
)

TIME_STATUSES = frozenset(
    {
        "calibrated",
        "score_path_only",
        "event_ms",
        "linked_event_ms",
        "pending_localization",
        "pending_review",
        "unavailable",
    }
)

SHOT_KINDS = frozenset({"live", "replay_supplement", "unknown", "scoreboard_anchor"})

RENDER_ELIGIBILITY = frozenset(
    {"render_ready", "candidate_only", "blocked", "not_applicable"}
)

VERIFICATION_STATUSES = frozenset(
    {
        "draft",
        "structure_ok",
        "partial",
        "blocked_none",
        "conflicts_present",
        "not_render_ready",
    }
)

STORY_TIERS = frozenset({"story", "candidate", "none"})

# 不得进入 render_ready_edl 的时间状态
NOT_RENDER_READY_TIME = frozenset(
    {
        "score_path_only",
        "pending_review",
        "pending_localization",
        "unavailable",
        "event_ms",  # 未经核实的 event_ms
    }
)


def empty_plan(*, match_id: str = "", story_tier: str = "none") -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "algorithm": ALGORITHM_ID,
        "match_id": match_id,
        "template_id": TEMPLATE_ID,
        "story_tier": story_tier,
        "protagonist": {"side": None, "team_name": ""},
        "beats": list(BEATS),
        "segments": [],
        "evidence_refs": [],
        "event_ids": [],
        "event_mappings": [],
        "missing_evidence": [],
        "blocking_reasons": [],
        "verification_status": "blocked_none" if story_tier == "none" else "draft",
        "structure_ok": False,
        "render_ready": False,
        "narration": {"summary": "", "by_beat": {b: "" for b in BEATS}},
        "candidate_edl": [],
        "render_ready_edl": [],
        "edl": [],  # 兼容：等同 candidate_edl
        "diagnostics": {},
    }


def validate_compose_plan(payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """结构校验（不等于 render_ready）。"""
    problems: List[str] = []
    if not isinstance(payload, dict):
        return False, ["payload_not_object"]
    if payload.get("schema_version") != SCHEMA_VERSION:
        problems.append("schema_version")
    if payload.get("template_id") != TEMPLATE_ID:
        problems.append("template_id")
    tier = payload.get("story_tier")
    if tier not in STORY_TIERS:
        problems.append("story_tier")
    if payload.get("verification_status") not in VERIFICATION_STATUSES:
        problems.append("verification_status")
    if list(payload.get("beats") or []) != list(BEATS):
        problems.append("beats_order")

    if tier == "none":
        if payload.get("segments"):
            problems.append("none_must_not_force_comeback_segments")
        if payload.get("render_ready"):
            problems.append("none_must_not_be_render_ready")

    seen_seg: set = set()
    prev_live_t: Optional[float] = None
    for i, seg in enumerate(payload.get("segments") or []):
        if not isinstance(seg, dict):
            problems.append(f"segment[{i}]_not_object")
            continue
        sid = str(seg.get("segment_id") or "")
        if not sid or sid in seen_seg:
            problems.append(f"segment[{i}]_id")
        seen_seg.add(sid)
        if seg.get("beat") not in BEATS:
            problems.append(f"segment[{i}]_beat")
        if seg.get("time_status") not in TIME_STATUSES:
            problems.append(f"segment[{i}]_time_status")
        if seg.get("shot_kind") not in SHOT_KINDS:
            problems.append(f"segment[{i}]_shot_kind")
        if seg.get("render_eligibility") not in RENDER_ELIGIBILITY:
            problems.append(f"segment[{i}]_render_eligibility")
        ts = seg.get("time_status")
        if ts in ("pending_localization", "pending_review", "unavailable"):
            if seg.get("precise_claim"):
                problems.append(f"segment[{i}]_precise_claim_forbidden")
        if seg.get("is_replay") and seg.get("shot_kind") == "live":
            problems.append(f"segment[{i}]_replay_marked_live")
        if seg.get("shot_kind") == "replay_supplement":
            if not seg.get("linked_live_event_id") and seg.get("render_eligibility") == "render_ready":
                problems.append(f"segment[{i}]_replay_render_without_live_link")
        if seg.get("shot_kind") in ("live", "scoreboard_anchor") and seg.get("media_in") is not None:
            try:
                t = float(seg["media_in"])
            except (TypeError, ValueError):
                problems.append(f"segment[{i}]_media_in")
                continue
            if prev_live_t is not None and t + 1e-6 < prev_live_t:
                problems.append(f"segment[{i}]_live_timeline_regression")
            prev_live_t = t
        for j, ref in enumerate(seg.get("evidence_refs") or []):
            if not isinstance(ref, dict):
                problems.append(f"segment[{i}]_evidence[{j}]")
                continue
            if ref.get("kind") not in EVIDENCE_KINDS:
                problems.append(f"segment[{i}]_evidence[{j}]_kind")
            if ref.get("kind") == "mock" and ref.get("used_as_fact"):
                problems.append(f"segment[{i}]_mock_used_as_fact")
            if ref.get("kind") == "verified" and not ref.get("pipeline_verified"):
                problems.append(f"segment[{i}]_untrusted_verified_flag")

    for ref in payload.get("evidence_refs") or []:
        if isinstance(ref, dict) and ref.get("kind") == "mock" and ref.get("used_as_fact"):
            problems.append("global_mock_used_as_fact")
        if isinstance(ref, dict) and ref.get("kind") == "verified" and not ref.get(
            "pipeline_verified"
        ):
            problems.append("global_untrusted_verified_flag")

    # render_ready 全局门禁
    if payload.get("render_ready"):
        r_edl = payload.get("render_ready_edl") or []
        if not r_edl:
            problems.append("render_ready_true_but_edl_empty")
        for row in r_edl:
            if row.get("time_status") in NOT_RENDER_READY_TIME:
                problems.append(f"render_edl_forbidden_time:{row.get('segment_id')}")
            if not row.get("pipeline_time_verified"):
                problems.append(f"render_edl_unverified_time:{row.get('segment_id')}")

    return (not problems), problems


def validate_render_ready(payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """可渲染校验（严于结构）。"""
    problems: List[str] = []
    if payload.get("story_tier") == "none":
        return False, ["tier_none"]
    segs = {s.get("segment_id"): s for s in (payload.get("segments") or [])}
    need_roles = {"equalizer_goal_action", "go_ahead_goal_action"}
    have = {
        s.get("role")
        for s in segs.values()
        if s.get("render_eligibility") == "render_ready"
    }
    for role in need_roles:
        if role not in have:
            problems.append(f"missing_render_ready_role:{role}")
    for row in payload.get("render_ready_edl") or []:
        sid = row.get("segment_id")
        seg = segs.get(sid) or {}
        if seg.get("render_eligibility") != "render_ready":
            problems.append(f"edl_row_not_eligible:{sid}")
        if row.get("time_status") in NOT_RENDER_READY_TIME:
            problems.append(f"edl_row_bad_time:{sid}")
        if not row.get("pipeline_time_verified"):
            problems.append(f"edl_row_unverified:{sid}")
    ok = not problems and bool(payload.get("render_ready_edl"))
    return ok, problems


def build_candidate_edl(segments: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    edl: List[Dict[str, Any]] = []
    for i, seg in enumerate(segments):
        edl.append(
            {
                "edl_index": i + 1,
                "segment_id": seg.get("segment_id"),
                "beat": seg.get("beat"),
                "role": seg.get("role"),
                "shot_kind": seg.get("shot_kind"),
                "is_replay": bool(seg.get("is_replay")),
                "media_in": seg.get("media_in"),
                "media_out": seg.get("media_out"),
                "time_status": seg.get("time_status"),
                "time_provenance": seg.get("time_provenance"),
                "event_ids": list(seg.get("event_ids") or []),
                "frame_ids": list(seg.get("frame_ids") or []),
                "linked_live_event_id": seg.get("linked_live_event_id"),
                "narrative_order": seg.get("narrative_order"),
                "source_media_order": seg.get("source_media_order"),
                "render_eligibility": seg.get("render_eligibility"),
                "blocking_reasons": list(seg.get("blocking_reasons") or []),
                "confidence": seg.get("confidence"),
                "selection_reason": seg.get("selection_reason"),
                "narration": seg.get("narration") or "",
                "include_in_cut": False,  # candidate 默认不成片
            }
        )
    return edl


def build_render_ready_edl(segments: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    edl: List[Dict[str, Any]] = []
    idx = 0
    for seg in segments:
        if seg.get("render_eligibility") != "render_ready":
            continue
        ts = seg.get("time_status")
        if ts in NOT_RENDER_READY_TIME:
            continue
        prov = seg.get("time_provenance") or {}
        if not prov.get("pipeline_verified"):
            continue
        if seg.get("media_in") is None or seg.get("media_out") is None:
            continue
        if seg.get("shot_kind") == "replay_supplement" and not seg.get(
            "linked_live_event_id"
        ):
            continue
        idx += 1
        edl.append(
            {
                "edl_index": idx,
                "segment_id": seg.get("segment_id"),
                "beat": seg.get("beat"),
                "role": seg.get("role"),
                "shot_kind": seg.get("shot_kind"),
                "is_replay": bool(seg.get("is_replay")),
                "media_in": seg.get("media_in"),
                "media_out": seg.get("media_out"),
                "time_status": ts,
                "pipeline_time_verified": True,
                "event_ids": list(seg.get("event_ids") or []),
                "frame_ids": list(seg.get("frame_ids") or []),
                "linked_live_event_id": seg.get("linked_live_event_id"),
                "narrative_order": seg.get("narrative_order"),
                "source_media_order": seg.get("source_media_order"),
                "confidence": seg.get("confidence"),
                "narration": seg.get("narration") or "",
                "include_in_cut": True,
            }
        )
    return edl


# 向后兼容别名
def segments_to_edl(segments: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return build_candidate_edl(segments)


def render_narrative_report(plan: Dict[str, Any]) -> str:
    lines = [
        f"# T01 Story Plan — {plan.get('match_id')}",
        f"- tier: `{plan.get('story_tier')}` · template: `{plan.get('template_id')}`",
        f"- verification: `{plan.get('verification_status')}`",
        f"- structure_ok: `{plan.get('structure_ok')}` · render_ready: `{plan.get('render_ready')}`",
        f"- protagonist: {plan.get('protagonist')}",
        "",
        "## Summary",
        str((plan.get("narration") or {}).get("summary") or "(empty)"),
        "",
    ]
    if plan.get("blocking_reasons"):
        lines.append("## Blocking (not render-ready)")
        for b in plan["blocking_reasons"]:
            lines.append(f"- {b}")
        lines.append("")
    by_beat = (plan.get("narration") or {}).get("by_beat") or {}
    segs_by_beat: Dict[str, List[Dict[str, Any]]] = {b: [] for b in BEATS}
    for seg in plan.get("segments") or []:
        segs_by_beat.setdefault(str(seg.get("beat")), []).append(seg)
    for beat in BEATS:
        lines.append(f"## {beat}")
        lines.append(str(by_beat.get(beat) or ""))
        for seg in segs_by_beat.get(beat) or []:
            lines.append(
                f"- `{seg.get('segment_id')}` · shot={seg.get('shot_kind')} · "
                f"elig={seg.get('render_eligibility')} · time={seg.get('time_status')} · "
                f"in={seg.get('media_in')} out={seg.get('media_out')} · "
                f"events={seg.get('event_ids')} · conf={seg.get('confidence')}"
            )
            if seg.get("blocking_reasons"):
                lines.append(f"  - blocked: {seg['blocking_reasons']}")
            if seg.get("selection_reason"):
                lines.append(f"  - why: {seg['selection_reason']}")
            if seg.get("narration"):
                lines.append(f"  - {seg['narration']}")
        lines.append("")
    lines.append("## Render-ready EDL")
    rr = plan.get("render_ready_edl") or []
    if not rr:
        lines.append("(empty — not safe to cut)")
    for row in rr:
        lines.append(
            f"- #{row.get('edl_index')} {row.get('beat')} "
            f"[{row.get('media_in')}, {row.get('media_out')}] "
            f"{row.get('shot_kind')} events={row.get('event_ids')}"
        )
    lines.append("")
    lines.append("## Candidate EDL (draft only)")
    for row in plan.get("candidate_edl") or []:
        lines.append(
            f"- #{row.get('edl_index')} {row.get('beat')} elig={row.get('render_eligibility')} "
            f"[{row.get('media_in')}, {row.get('media_out')}] {row.get('time_status')}"
        )
    return "\n".join(lines).rstrip() + "\n"
