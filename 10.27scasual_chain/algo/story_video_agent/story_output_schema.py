"""Phase 3A：咪咕剪辑故事线方案输出 schema 与校验。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

SCHEMA_VERSION = "story-compose-plan-3a"
ALGORITHM_ID = "t01_story_composer_phase3a"
TEMPLATE_ID = "T01_comeback"

BEATS: Tuple[str, ...] = ("铺垫", "蓄力", "转折", "高潮", "收尾")

# 证据/事实来源（互斥语义）
EVIDENCE_KINDS = frozenset(
    {
        "rule_fact",  # 规则从 T01/比分路径可支持的事实
        "vlm_observation",  # 真实 VLM 观察（provider_mode=real/cache）
        "verified",  # 已核验证据（本阶段通常达不到；预留）
        "mock",  # 合成/fixture；不得当真实事实依据
        "unresolved_conflict",
    }
)

TIME_STATUSES = frozenset(
    {
        "calibrated",
        "score_path_only",
        "event_ms",
        "pending_localization",
        "pending_review",
        "unavailable",
    }
)

SHOT_KINDS = frozenset({"live", "replay_supplement", "unknown"})

VERIFICATION_STATUSES = frozenset(
    {
        "draft",
        "structure_ok",
        "partial",
        "blocked_none",
        "conflicts_present",
    }
)

STORY_TIERS = frozenset({"story", "candidate", "none"})


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
        "missing_evidence": [],
        "verification_status": "blocked_none" if story_tier == "none" else "draft",
        "narration": {"summary": "", "by_beat": {b: "" for b in BEATS}},
        "edl": [],
        "diagnostics": {},
    }


def validate_compose_plan(payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
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
        if payload.get("verification_status") not in ("blocked_none", "draft"):
            problems.append("none_verification_status")

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
        # 禁止伪精确：pending_* 不得同时给假精确 media_in/out 且声称 calibrated
        ts = seg.get("time_status")
        if ts in ("pending_localization", "pending_review", "unavailable"):
            if seg.get("time_status") == "calibrated":
                problems.append(f"segment[{i}]_fake_calibrated")
            # 允许 null；若给出数值必须标记非 calibrated（已由 time_status 约束）
            if seg.get("precise_claim"):
                problems.append(f"segment[{i}]_precise_claim_forbidden")
        # 回放不得冒充 live 主时序
        if seg.get("is_replay") and seg.get("shot_kind") == "live":
            problems.append(f"segment[{i}]_replay_marked_live")
        # live 主片段时序非递减（仅对有 media_in 的 live）
        if seg.get("shot_kind") == "live" and seg.get("media_in") is not None:
            try:
                t = float(seg["media_in"])
            except (TypeError, ValueError):
                problems.append(f"segment[{i}]_media_in")
                continue
            if prev_live_t is not None and t + 1e-6 < prev_live_t:
                problems.append(f"segment[{i}]_live_timeline_regression")
            prev_live_t = t
        # 证据引用
        for j, ref in enumerate(seg.get("evidence_refs") or []):
            if not isinstance(ref, dict):
                problems.append(f"segment[{i}]_evidence[{j}]")
                continue
            if ref.get("kind") not in EVIDENCE_KINDS:
                problems.append(f"segment[{i}]_evidence[{j}]_kind")
            if ref.get("kind") == "mock" and ref.get("used_as_fact"):
                problems.append(f"segment[{i}]_mock_used_as_fact")

    for ref in payload.get("evidence_refs") or []:
        if isinstance(ref, dict) and ref.get("kind") == "mock" and ref.get("used_as_fact"):
            problems.append("global_mock_used_as_fact")

    return (not problems), problems


def segments_to_edl(segments: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """EDL：仅导出有可用时间窗的条目；pending 片段保留占位但不伪称精确。"""
    edl: List[Dict[str, Any]] = []
    for i, seg in enumerate(segments):
        row = {
            "edl_index": i + 1,
            "segment_id": seg.get("segment_id"),
            "beat": seg.get("beat"),
            "shot_kind": seg.get("shot_kind"),
            "is_replay": bool(seg.get("is_replay")),
            "media_in": seg.get("media_in"),
            "media_out": seg.get("media_out"),
            "time_status": seg.get("time_status"),
            "event_ids": list(seg.get("event_ids") or []),
            "frame_ids": list(seg.get("frame_ids") or []),
            "narration": seg.get("narration") or "",
            "include_in_cut": bool(
                seg.get("time_status")
                in ("calibrated", "score_path_only", "event_ms")
                and seg.get("media_in") is not None
                and seg.get("media_out") is not None
            ),
        }
        edl.append(row)
    return edl


def render_narrative_report(plan: Dict[str, Any]) -> str:
    lines = [
        f"# T01 Story Plan — {plan.get('match_id')}",
        f"- tier: `{plan.get('story_tier')}` · template: `{plan.get('template_id')}`",
        f"- verification: `{plan.get('verification_status')}`",
        f"- protagonist: {plan.get('protagonist')}",
        "",
        "## Summary",
        str((plan.get("narration") or {}).get("summary") or "(empty)"),
        "",
    ]
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
                f"time={seg.get('time_status')} · "
                f"in={seg.get('media_in')} out={seg.get('media_out')} · "
                f"events={seg.get('event_ids')} · frames={seg.get('frame_ids')}"
            )
            if seg.get("narration"):
                lines.append(f"  - {seg['narration']}")
        lines.append("")
    missing = plan.get("missing_evidence") or []
    if missing:
        lines.append("## Missing evidence")
        for m in missing:
            lines.append(f"- {m}")
        lines.append("")
    lines.append("## EDL (include_in_cut)")
    for row in plan.get("edl") or []:
        if not row.get("include_in_cut"):
            continue
        lines.append(
            f"- #{row.get('edl_index')} {row.get('beat')} "
            f"[{row.get('media_in')}, {row.get('media_out')}] "
            f"{row.get('shot_kind')} events={row.get('event_ids')}"
        )
    return "\n".join(lines).rstrip() + "\n"
