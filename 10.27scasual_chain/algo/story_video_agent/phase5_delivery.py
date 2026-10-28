"""Phase 5 delivery: Story Plan → summary / graph / dual candidate MP4s.

Same cut timeline for story_clean.mp4 and story_qc.mp4.
No match-specific goal times. Optional glitch ranges only via explicit profile.
render_ready stays false; both variants are candidate_only.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from story_video_agent.media import probe_video
from story_video_agent.video_renderer import (
    DEFAULT_AUDIO_RATE,
    DEFAULT_FPS,
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    RenderError,
    _concat_clips,
    _cut_segment,
    _make_placeholder,
    _require_ffmpeg,
)

LOUDNORM_I = -16.0
LOUDNORM_TP = -1.5
LOUDNORM_LRA = 11.0

# Roles included in the single full-story cut (not dual narrative lengths)
_CUT_ROLE_HINTS = (
    "opponent_opening_goal_action",
    "equalizer_goal_action",
    "go_ahead_goal_action",
    "lead_extend_",
    "buildup",
    "ending",
)
_SKIP_SHOT_KINDS = {"replay_supplement", "unknown"}
_MAX_BUILDUP_CLIPS = 3
_MAX_SCOREBOARD_SEC = 3.5


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


# 进球过程完整性：不仅“锚点在窗内”，还要求射门前上下文
MIN_APPROACH_BEFORE_ANCHOR = 4.0
MIN_RESULT_AFTER_ANCHOR = 2.5
MIN_APPROACH_CLIP_SEC = 3.0


def _window_covers(a: float, b: float, t: float, *, pad_before: float = 0.0, pad_after: float = 0.0) -> bool:
    return (a + pad_before) <= t <= (b - pad_after)


def assess_goal_completeness(
    *,
    media_in: Optional[float],
    media_out: Optional[float],
    anchor: Optional[float],
    has_approach_clip: bool = False,
    glitch_break: bool = False,
    approach_media_in: Optional[float] = None,
    approach_media_out: Optional[float] = None,
) -> Dict[str, Any]:
    """Faceted goal completeness — anchor coverage alone is not enough."""
    result_visible = False
    approach_visible = False
    context_sufficient = False
    if (
        media_in is not None
        and media_out is not None
        and anchor is not None
        and _window_covers(media_in, media_out, anchor)
        and (media_out - anchor) >= MIN_RESULT_AFTER_ANCHOR - 1e-6
    ):
        result_visible = True
    approach_pad = 0.0
    if media_in is not None and anchor is not None:
        approach_pad = max(0.0, anchor - media_in)
    approach_clip_dur = 0.0
    if approach_media_in is not None and approach_media_out is not None:
        approach_clip_dur = max(0.0, approach_media_out - approach_media_in)
    if has_approach_clip and approach_clip_dur >= MIN_APPROACH_CLIP_SEC - 1e-6:
        approach_visible = True
    elif approach_pad >= MIN_APPROACH_BEFORE_ANCHOR - 1e-6:
        approach_visible = True
    context_sufficient = bool(result_visible and approach_visible)
    # 坏帧断裂且无进攻上下文补段 → 不完整
    complete = context_sufficient and not (glitch_break and not has_approach_clip)
    if glitch_break and has_approach_clip and result_visible:
        complete = True
    return {
        "result_visible": result_visible,
        "approach_visible": approach_visible,
        "context_sufficient": context_sufficient,
        "glitch_break": glitch_break,
        "approach_pad_sec": round(approach_pad, 3),
        "approach_clip_sec": round(approach_clip_dur, 3),
        "goal_action_complete": complete,
    }


def plan_goal_clips_around_glitch(
    media_in: float,
    media_out: float,
    ranges: Sequence[Tuple[float, float, str]],
    *,
    must_cover: float,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
    """Prefer split: approach before glitch + result after glitch (no bad frames).

    Returns (clips, notes, integrity_failure).
    Each clip: {part: approach|result, media_in, media_out}.
    """
    notes: List[Dict[str, Any]] = []
    a0, b0 = float(media_in), float(media_out)
    # Glitches that sit strictly between approach start and anchor
    blockers = []
    for ga, gb, lab in ranges:
        if b0 <= ga or a0 >= gb:
            continue
        if ga - 1e-6 <= must_cover <= gb + 1e-6:
            notes.append({"label": lab, "action": "anchor_in_glitch", "glitch": [ga, gb]})
            return [], notes, "goal_anchor_inside_glitch"
        if a0 < ga < must_cover:
            blockers.append((ga, gb, lab))
    if blockers:
        # Use earliest glitch before anchor as split point
        blockers.sort(key=lambda x: x[0])
        ga, gb, lab = blockers[0]
        approach_out = min(ga, must_cover)
        result_in = max(gb, a0)
        clips: List[Dict[str, Any]] = []
        if approach_out - a0 >= 1.0:
            clips.append(
                {
                    "part": "approach",
                    "media_in": round(a0, 3),
                    "media_out": round(approach_out, 3),
                }
            )
            notes.append(
                {
                    "label": lab,
                    "action": "split_approach_before_glitch",
                    "window": [a0, approach_out],
                }
            )
        if b0 - result_in >= MIN_RESULT_AFTER_ANCHOR and result_in <= must_cover <= b0:
            clips.append(
                {
                    "part": "result",
                    "media_in": round(result_in, 3),
                    "media_out": round(b0, 3),
                }
            )
            notes.append(
                {
                    "label": lab,
                    "action": "split_result_after_glitch",
                    "window": [result_in, b0],
                }
            )
        if not clips or not any(c["part"] == "result" for c in clips):
            return clips, notes, "glitch_split_missing_result"
        notes.append({"action": "split_around_glitch", "n_clips": len(clips)})
        return clips, notes, None

    # No split needed: single clean window (still may need approach pad check)
    return (
        [{"part": "result", "media_in": round(a0, 3), "media_out": round(b0, 3)}],
        notes,
        None,
    )


def apply_glitch_avoidance(
    media_in: float,
    media_out: float,
    ranges: Sequence[Tuple[float, float, str]],
    *,
    must_cover: Optional[float] = None,
    min_pad_before_anchor: float = 0.3,
    min_pad_after_anchor: float = 2.5,
    rebuild_pad_before: float = 8.0,
    rebuild_pad_after: float = 10.0,
) -> Tuple[float, float, List[Dict[str, Any]], Optional[str]]:
    """Legacy single-window trim. Prefer ``plan_goal_clips_around_glitch`` for goals."""
    notes: List[Dict[str, Any]] = []
    a, b = float(media_in), float(media_out)
    ranges = list(ranges or [])

    def _avoid(a0: float, b0: float) -> Tuple[float, float]:
        aa, bb = a0, b0
        for ga, gb, lab in ranges:
            if bb <= ga or aa >= gb:
                continue
            if must_cover is not None:
                if ga - 1e-6 <= must_cover <= gb + 1e-6:
                    notes.append(
                        {
                            "label": lab,
                            "action": "anchor_in_glitch",
                            "must_cover": must_cover,
                            "glitch": [ga, gb],
                        }
                    )
                    continue
                if must_cover >= gb:
                    notes.append({"label": lab, "action": "raise_in_keep_anchor", "from": aa, "to": gb})
                    aa = max(aa, gb)
                elif must_cover <= ga:
                    notes.append({"label": lab, "action": "lower_out_keep_anchor", "from": bb, "to": ga})
                    bb = min(bb, ga)
                else:
                    notes.append({"label": lab, "action": "ambiguous_overlap", "glitch": [ga, gb]})
            else:
                if aa < gb <= bb and (gb - aa) <= (bb - ga):
                    notes.append({"label": lab, "action": "raise_in", "from": aa, "to": gb})
                    aa = gb
                elif aa < ga < bb:
                    notes.append({"label": lab, "action": "lower_out", "from": bb, "to": ga})
                    bb = ga
            if bb - aa < 0.5 and must_cover is None:
                notes.append({"label": lab, "action": "jump_past", "to": gb + 0.2})
                aa = gb + 0.2
                bb = max(bb, aa + 2.0)
        return aa, bb

    a, b = _avoid(a, b)
    if must_cover is not None:
        ok = (
            _window_covers(a, b, must_cover)
            and must_cover - a >= min_pad_before_anchor - 1e-6
            and b - must_cover >= min_pad_after_anchor - 1e-6
        )
        still_glitch = any(not (b <= ga or a >= gb) for ga, gb, _ in ranges)
        if (not ok) or still_glitch:
            a2 = max(0.0, must_cover - rebuild_pad_before)
            b2 = must_cover + rebuild_pad_after
            notes.append({"action": "rebuild_around_anchor", "from": [a, b], "to": [a2, b2]})
            a, b = _avoid(a2, b2)
            still_glitch = any(not (b <= ga or a >= gb) for ga, gb, _ in ranges)
            covers = _window_covers(a, b, must_cover)
            pads_ok = (
                covers
                and (must_cover - a) >= min_pad_before_anchor - 1e-6
                and (b - must_cover) >= min_pad_after_anchor - 1e-6
            )
            if still_glitch or not pads_ok:
                reason = "glitch_conflicts_with_goal_anchor"
                if any(ga - 1e-6 <= must_cover <= gb + 1e-6 for ga, gb, _ in ranges):
                    reason = "goal_anchor_inside_glitch"
                elif not covers:
                    reason = "goal_anchor_outside_clean_window"
                return round(a, 3), round(b, 3), notes, reason
    return round(a, 3), round(b, 3), notes, None


def select_delivery_rows(
    plan: Dict[str, Any],
    *,
    glitch_ranges: Optional[Sequence[Tuple[float, float, str]]] = None,
) -> List[Dict[str, Any]]:
    """One full story cut from Story Plan segments / candidate_edl."""
    segs = list(plan.get("segments") or [])
    if not segs:
        segs = list(plan.get("candidate_edl") or [])
    segs = sorted(
        segs,
        key=lambda s: (s.get("narrative_order") or 0, s.get("segment_id") or ""),
    )
    glitch_ranges = list(glitch_ranges or [])
    rows: List[Dict[str, Any]] = []
    buildup_n = 0
    has_goal_for_prefix: Dict[str, bool] = {}

    for seg in segs:
        role = str(seg.get("role") or "")
        shot = str(seg.get("shot_kind") or "")
        if shot in _SKIP_SHOT_KINDS:
            continue
        if seg.get("render_eligibility") == "blocked" and seg.get("media_in") is None:
            continue
        if "pending" in role:
            continue

        # Prefer live goal actions; keep short scoreboard only if no action for same prefix
        if "goal_action" in role and "pending" not in role:
            prefix = role.replace("_goal_action", "")
            has_goal_for_prefix[prefix] = True
        if "scoreboard" in role:
            # 无对应完整进球动作的扩大比分牌：留给 ending_final_scoreboard，避免重复且不伪装进球
            if role.startswith("lead_extend_") and "scoreboard" in role:
                prefix = role.split("_scoreboard")[0]
                if not has_goal_for_prefix.get(prefix):
                    continue
            tin = _safe_float(seg.get("media_in"))
            tout = _safe_float(seg.get("media_out"))
            if tin is not None and tout is not None and (tout - tin) > _MAX_SCOREBOARD_SEC:
                seg = dict(seg)
                seg["media_out"] = round(tin + _MAX_SCOREBOARD_SEC, 3)
                prov = dict(seg.get("time_provenance") or {})
                prov["shortened_scoreboard"] = True
                seg["time_provenance"] = prov

        if "buildup" in role or role.startswith("buildup"):
            buildup_n += 1
            if buildup_n > _MAX_BUILDUP_CLIPS:
                continue

        # 未核验 match_end / 旧版 ending：不成片（可能切到其它转播）
        if role in ("ending", "ending_match_end", "ending_match_end_candidate"):
            continue
        if role == "ending_pending":
            continue
        if (
            str(seg.get("selection_reason") or "") == "ending_event"
            or "ending_match_end_rejected" in str(seg.get("blocking_reasons") or [])
        ):
            continue

        tin = _safe_float(seg.get("media_in"))
        tout = _safe_float(seg.get("media_out"))
        notes: List[Dict[str, Any]] = []
        integrity_fail: Optional[str] = None
        prov = dict(seg.get("time_provenance") or {})
        is_goal_action = (
            "goal_action" in role
            and "pending" not in role
            and "scoreboard" not in role
        )
        # 仅有比分牌不得标为完整进球动作
        if "scoreboard" in role:
            prov["not_a_goal_action"] = True
        must_cover: Optional[float] = None
        if is_goal_action:
            must_cover = _safe_float(prov.get("t_sec"))
            if must_cover is None and tin is not None and tout is not None:
                must_cover = round((tin + tout) / 2.0, 3)
                prov["anchor_fallback"] = "mid_window_untrusted"

        blocks = list(seg.get("blocking_reasons") or []) + [
            "phase5_candidate_delivery",
            "semantic_unverified",
        ]

        # ---- Goal actions: split around glitch to keep approach + result ----
        if is_goal_action and tin is not None and tout is not None and must_cover is not None:
            clips: List[Dict[str, Any]]
            if glitch_ranges:
                clips, notes, integrity_fail = plan_goal_clips_around_glitch(
                    tin, tout, glitch_ranges, must_cover=must_cover
                )
            else:
                clips = [{"part": "result", "media_in": tin, "media_out": tout}]
            approach_clip = next((c for c in clips if c["part"] == "approach"), None)
            result_clip = next((c for c in clips if c["part"] == "result"), None)
            if result_clip is None and clips:
                result_clip = clips[-1]
            glitch_break = any(
                n.get("action") in ("split_around_glitch", "raise_in_keep_anchor") for n in notes
            )
            facets = assess_goal_completeness(
                media_in=(result_clip or {}).get("media_in"),
                media_out=(result_clip or {}).get("media_out"),
                anchor=must_cover,
                has_approach_clip=approach_clip is not None,
                glitch_break=glitch_break,
                approach_media_in=(approach_clip or {}).get("media_in"),
                approach_media_out=(approach_clip or {}).get("media_out"),
            )
            # No glitch but approach pad too short → incomplete (need补证 / 回放)
            if not glitch_ranges and not facets["approach_visible"]:
                facets["goal_action_complete"] = False
                integrity_fail = integrity_fail or "insufficient_pre_shot_context"
            if integrity_fail:
                facets["goal_action_complete"] = False
                blocks.append(f"goal_integrity_failed:{integrity_fail}")
                blocks.append("needs_alternate_live_goal_search")
            if not facets["goal_action_complete"]:
                blocks.append("goal_process_incomplete")
                role_out = f"{role}_incomplete" if not role.endswith("_incomplete") else role
            else:
                role_out = role

            def _goal_row(**extra: Any) -> Dict[str, Any]:
                base = {
                    "edl_index": len(rows) + 1,
                    "beat": seg.get("beat"),
                    "shot_kind": shot,
                    "is_replay": bool(seg.get("is_replay")),
                    "time_status": seg.get("time_status"),
                    "event_ids": list(seg.get("event_ids") or []),
                    "frame_ids": list(seg.get("frame_ids") or []),
                    "linked_live_event_id": seg.get("linked_live_event_id"),
                    "narrative_order": seg.get("narrative_order"),
                    "render_eligibility": "candidate_only",
                    "blocking_reasons": list(blocks),
                    "confidence": seg.get("confidence"),
                    "include_in_cut": True,
                    "glitch_avoidance": notes,
                    "goal_anchor_t_sec": must_cover,
                    "goal_action_complete": facets["goal_action_complete"],
                    "goal_completeness_facets": facets,
                    "integrity_failure": integrity_fail,
                    "evidence_refs": list(seg.get("evidence_refs") or []),
                    "source_refs": list(seg.get("source_refs") or []),
                }
                base.update(extra)
                return base

            if approach_clip is not None:
                rows.append(
                    _goal_row(
                        segment_id=f"{seg.get('segment_id')}_approach",
                        role=f"{role_out}_approach",
                        media_in=approach_clip["media_in"],
                        media_out=approach_clip["media_out"],
                        time_provenance=dict(prov, goal_part="approach"),
                        source_media_order=approach_clip["media_in"],
                        selection_reason="goal_approach_before_glitch_or_anchor",
                        narration=(seg.get("narration") or "") + "〔射门前上下文〕",
                        is_replay=False,
                        frame_ids=[],
                    )
                )
            if result_clip is not None:
                rows.append(
                    _goal_row(
                        segment_id=str(seg.get("segment_id")),
                        role=role_out,
                        media_in=result_clip["media_in"],
                        media_out=result_clip["media_out"],
                        time_provenance=dict(prov, goal_part="result"),
                        source_media_order=result_clip["media_in"],
                        selection_reason=seg.get("selection_reason"),
                        narration=seg.get("narration") or "",
                    )
                )
            elif not clips:
                # 无法得到干净结果窗：保留补证占位（不切入坏帧）
                rows.append(
                    _goal_row(
                        segment_id=str(seg.get("segment_id")),
                        role=role_out,
                        media_in=None,
                        media_out=None,
                        time_provenance=dict(prov, goal_part="unavailable"),
                        source_media_order=None,
                        selection_reason="goal_unavailable_after_glitch_gate",
                        narration=(seg.get("narration") or "")
                        + "〔坏帧与进球冲突，未输出动作窗〕",
                        shot_kind="title_card",
                        placeholder_sec=2.0,
                        placeholder_lines=["进球动作待补证", str(integrity_fail or "")],
                    )
                )
            continue

        # ---- Non-goal / untimed ----
        if tin is not None and tout is not None and glitch_ranges:
            tin, tout, notes, integrity_fail = apply_glitch_avoidance(tin, tout, glitch_ranges)

        # 终场包装段：明确非“已核实全场哨声终场”
        ending_status = None
        if role in (
            "ending_final_scoreboard",
            "ending_story_wrap_score",
            "ending_match_end_candidate",
        ):
            ending_status = str(
                (seg.get("time_provenance") or {}).get("ending_status")
                or "unverified_story_wrap"
            )
            prov["ending_status"] = ending_status
            prov["not_verified_full_time"] = True
            blocks.append("ending_not_semantically_verified")

        row = {
            "edl_index": len(rows) + 1,
            "segment_id": seg.get("segment_id"),
            "beat": seg.get("beat"),
            "role": role,
            "shot_kind": shot,
            "is_replay": bool(seg.get("is_replay")),
            "media_in": tin,
            "media_out": tout,
            "time_status": seg.get("time_status"),
            "time_provenance": prov,
            "event_ids": list(seg.get("event_ids") or []),
            "frame_ids": list(seg.get("frame_ids") or []),
            "linked_live_event_id": seg.get("linked_live_event_id"),
            "narrative_order": seg.get("narrative_order"),
            "source_media_order": seg.get("source_media_order"),
            "render_eligibility": "candidate_only",
            "blocking_reasons": blocks,
            "confidence": seg.get("confidence"),
            "selection_reason": seg.get("selection_reason"),
            "narration": seg.get("narration") or "",
            "include_in_cut": True,
            "glitch_avoidance": notes,
            "goal_anchor_t_sec": None,
            "goal_action_complete": None,
            "integrity_failure": integrity_fail,
            "ending_status": ending_status,
            "evidence_refs": list(seg.get("evidence_refs") or []),
            "source_refs": list(seg.get("source_refs") or []),
        }
        if tin is None or tout is None:
            if shot != "title_card":
                continue
        rows.append(row)
    return resolve_delivery_window_conflicts(rows)


def _interval_overlap_sec(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def resolve_delivery_window_conflicts(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Detect overlapping media windows; ending must not repeat last scoreboard.

    If story-wrap score footage overlaps a scoreboard already in the cut, drop the
    wrap footage (title-card story wrap remains). Also collapse near-duplicate
    identical windows.
    """
    drop: set = set()
    # Pass 1: exact / near-identical windows
    by_win: Dict[Tuple[int, int], List[int]] = {}
    for i, r in enumerate(rows):
        tin, tout = _safe_float(r.get("media_in")), _safe_float(r.get("media_out"))
        if tin is None or tout is None:
            continue
        key = (int(round(tin * 100)), int(round(tout * 100)))
        by_win.setdefault(key, []).append(i)
    for idxs in by_win.values():
        if len(idxs) < 2:
            continue
        roles = [(j, str(rows[j].get("role") or "")) for j in idxs]
        wraps = [
            j
            for j, role in roles
            if role in ("ending_final_scoreboard", "ending_story_wrap_score")
        ]
        boards = [
            j
            for j, role in roles
            if ("scoreboard" in role or role.endswith("_scoreboard_anchor"))
            and role not in ("ending_final_scoreboard", "ending_story_wrap_score")
        ]
        if wraps and boards:
            # Prefer keeping the narrative scoreboard; drop redundant wrap footage
            drop.update(wraps)
        elif wraps and len(wraps) > 1:
            drop.update(wraps[1:])
        elif len(boards) > 1:
            drop.update(boards[1:])

    # Pass 2: partial overlap — wrap vs any earlier scoreboard / goal board
    for i, r in enumerate(rows):
        if i in drop:
            continue
        role = str(r.get("role") or "")
        if role not in ("ending_story_wrap_score", "ending_final_scoreboard"):
            continue
        ai, ao = _safe_float(r.get("media_in")), _safe_float(r.get("media_out"))
        if ai is None or ao is None:
            continue
        for j, o in enumerate(rows):
            if i == j or j in drop:
                continue
            orole = str(o.get("role") or "")
            if "scoreboard" not in orole and "goal_action" not in orole:
                continue
            if orole in ("ending_story_wrap_score", "ending_final_scoreboard"):
                continue
            bi, bo = _safe_float(o.get("media_in")), _safe_float(o.get("media_out"))
            if bi is None or bo is None:
                continue
            ov = _interval_overlap_sec(ai, ao, bi, bo)
            # Same in-point (±1s) or >50% of wrap duration overlapped → redundant
            wrap_dur = max(1e-3, ao - ai)
            if abs(ai - bi) <= 1.0 or ov / wrap_dur >= 0.5:
                drop.add(i)
                r.setdefault("blocking_reasons", [])
                if isinstance(r["blocking_reasons"], list):
                    r["blocking_reasons"] = list(r["blocking_reasons"]) + [
                        "ending_wrap_overlaps_prior_scoreboard_use_title_only"
                    ]
                break

    out = [r for i, r in enumerate(rows) if i not in drop]
    for i, r in enumerate(out):
        r["edl_index"] = i + 1
        r["narrative_order"] = i + 1
    return out


def _score_label_from_plan(plan: Dict[str, Any], role: str) -> List[str]:
    """Business overlays from score_path / narration — no hardcoded match scores."""
    lines: List[str] = []
    beat = ""
    for seg in plan.get("segments") or []:
        if seg.get("role") == role:
            beat = str(seg.get("beat") or "")
            narr = str(seg.get("narration") or "")
            m = re.search(r"比分确认\s+(\d+:\d+)", narr)
            if m:
                lines.append(f"比分 {m.group(1)}")
            m2 = re.search(r"(\d+:\d+)", narr)
            if not lines and m2 and "scoreboard" in role:
                lines.append(f"比分 {m2.group(1)}")
            break
    if "opponent_opening" in role:
        lines = ["失球 · 落后开始"] + lines
    elif role.startswith("equalizer") and "goal" in role:
        lines = ["扳平"] + lines
    elif role.startswith("go_ahead") and "goal" in role:
        lines = ["反超"] + lines
    elif "lead_extend" in role and "goal" in role:
        lines = ["扩大优势"] + lines
    elif "buildup" in role:
        lines = ["蓄力"]
    elif role == "ending" or "ending" in role:
        lines = ["终场"]
    if beat and beat not in lines:
        lines = [beat] + lines
    return lines[:3]


def _clean_overlays(plan: Dict[str, Any], row: Dict[str, Any]) -> List[str]:
    """Business-facing: no tech banners on live footage.

    Title cards use placeholder_lines (clean). Gameplay: light narrative cue only.
    """
    role = str(row.get("role") or "")
    if row.get("shot_kind") == "title_card":
        return []
    # Soft beat cue only — no candidate_only / media timestamps / event ids
    labels = _score_label_from_plan(plan, role.replace("_incomplete", ""))
    return [x for x in labels if x and "candidate" not in x.lower()][:2]


def _qc_overlays(plan: Dict[str, Any], row: Dict[str, Any]) -> List[str]:
    a = row.get("media_in")
    b = row.get("media_out")
    eids = ",".join(str(x) for x in (row.get("event_ids") or [])[:3]) or "-"
    complete = row.get("goal_action_complete")
    anchor = row.get("goal_anchor_t_sec")
    lines = [
        "内部 QC · candidate_only · render_ready=false",
        f"{row.get('beat') or ''} | {row.get('role') or ''}",
        f"media {a}-{b} | {row.get('time_status')}",
        f"eid:{eids}",
    ]
    if anchor is not None:
        lines.append(f"anchor={anchor} complete={complete}")
    if row.get("integrity_failure"):
        lines.append(f"integrity:{row.get('integrity_failure')}")
    return lines


def render_dual_delivery(
    *,
    plan: Dict[str, Any],
    video: Path,
    out_dir: Path,
    delivery_edl: Sequence[Dict[str, Any]],
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    fps: int = DEFAULT_FPS,
) -> Dict[str, Any]:
    """Render story_clean.mp4 and story_qc.mp4 from the same EDL timeline."""
    ffmpeg = _require_ffmpeg()
    media = probe_video(video)
    has_audio = bool(media.audio_codec)
    out_dir.mkdir(parents=True, exist_ok=True)
    results: Dict[str, Any] = {}

    for variant, overlay_fn, name in (
        ("clean", _clean_overlays, "story_clean.mp4"),
        ("qc", _qc_overlays, "story_qc.mp4"),
    ):
        work = out_dir / f"_work_{variant}"
        clips_dir = work / "clips"
        clips_dir.mkdir(parents=True, exist_ok=True)
        clip_paths: List[Path] = []
        ffmpeg_log: List[Dict[str, Any]] = []
        seg_meta: List[Dict[str, Any]] = []

        for i, row in enumerate(delivery_edl):
            sid = str(row.get("segment_id") or f"seg_{i}")
            clip_path = clips_dir / f"{i:03d}_{sid}.mp4"
            meta: Dict[str, Any] = {
                "segment_id": sid,
                "beat": row.get("beat"),
                "role": row.get("role"),
                "media_in": row.get("media_in"),
                "media_out": row.get("media_out"),
                "cut": False,
                "placeholder": False,
            }
            tin, tout = row.get("media_in"), row.get("media_out")
            if tin is None or tout is None:
                if variant == "qc":
                    lines = list(
                        row.get("placeholder_lines_qc")
                        or row.get("placeholder_lines")
                        or ["标题", sid]
                    )
                else:
                    lines = list(row.get("placeholder_lines") or ["标题", sid])
                rec = _make_placeholder(
                    ffmpeg=ffmpeg,
                    out_path=clip_path,
                    duration=float(row.get("placeholder_sec") or 2.5),
                    width=width,
                    height=height,
                    fps=fps,
                    lines=lines,
                )
                ffmpeg_log.append(rec)
                meta["placeholder"] = True
            else:
                a, b = float(tin), float(tout)
                overlays = overlay_fn(plan, row)
                af = f"aresample={DEFAULT_AUDIO_RATE},dynaudnorm=f=150:g=15"
                try:
                    rec = _cut_segment(
                        ffmpeg=ffmpeg,
                        src=Path(media.path),
                        media_in=a,
                        media_out=b,
                        out_path=clip_path,
                        width=width,
                        height=height,
                        fps=fps,
                        has_audio=has_audio,
                        overlay_lines=overlays,
                        accurate_seek=True,
                        audio_filter=af,
                    )
                    ffmpeg_log.append(rec)
                    meta["cut"] = True
                except RenderError as exc:
                    meta["skip_reason"] = str(exc)
                    rec = _make_placeholder(
                        ffmpeg=ffmpeg,
                        out_path=clip_path,
                        duration=2.5,
                        width=width,
                        height=height,
                        fps=fps,
                        lines=["裁切失败", sid, str(exc)[:40]],
                    )
                    ffmpeg_log.append(rec)
                    meta["placeholder"] = True
            clip_paths.append(clip_path)
            seg_meta.append(meta)

        raw_mp4 = work / "concat_raw.mp4"
        ffmpeg_log.append(
            _concat_clips(ffmpeg=ffmpeg, clip_paths=clip_paths, out_mp4=raw_mp4)
        )
        out_mp4 = out_dir / name
        loud_cmd = [
            ffmpeg,
            "-hide_banner",
            "-y",
            "-i",
            str(raw_mp4),
            "-af",
            f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            str(DEFAULT_AUDIO_RATE),
            "-ac",
            "2",
            str(out_mp4),
        ]
        proc = subprocess.run(
            loud_cmd, capture_output=True, text=True, check=False, timeout=1200
        )
        ffmpeg_log.append(
            {
                "label": "loudnorm_master",
                "returncode": proc.returncode,
                "stderr_tail": (proc.stderr or "")[-300:],
            }
        )
        if proc.returncode != 0:
            raise RenderError(f"loudnorm failed ({variant}): {(proc.stderr or '')[-400:]}")
        info = probe_video(out_mp4)
        results[variant] = {
            "out_mp4": str(out_mp4),
            "duration_sec": info.duration_sec,
            "segments": seg_meta,
            "ffmpeg_log_n": len(ffmpeg_log),
        }
    return results


def decide_arc_background_plan(
    *,
    prior: Sequence[Dict[str, Any]],
    protagonist_side: Optional[str],
    behind: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Generic planner: whether prior score turns are needed to understand the arc.

    Does NOT force a fixed 3-event cut, and does NOT pull all prior goals.
    Modes: none | title_summary | title_and_key_boards (≤2 scoreboards).
    """
    meaningful = [
        p
        for p in prior
        if p.get("score") not in (None, "", "0:0") and p.get("delta_side") is not None
    ]
    if not meaningful:
        return {
            "mode": "none",
            "reason": "no_meaningful_prior_score_changes",
            "affects_comeback_understanding": False,
            "boards_to_include": [],
            "title_lines": [],
        }

    side = protagonist_side
    proto_led = any(p.get("delta_side") == side for p in meaningful)
    # Multiple lead changes before last deficit → viewers need background
    multi_turn = len(meaningful) >= 2
    affects = bool(proto_led or multi_turn)

    title_lines = ["翻盘弧前情提要（非全场进球全集）"]
    path_txt = " → ".join(str(p.get("score")) for p in prior if p.get("score"))
    if path_txt:
        title_lines.append(path_txt[:48])
    title_lines.append("以下进入最后一次落后弧")

    boards: List[Dict[str, Any]] = []
    if affects and multi_turn:
        # At most 2: first proto lead (if any), and last prior state before arc
        first_lead = next((p for p in meaningful if p.get("delta_side") == side), None)
        last_prior = meaningful[-1]
        for node in (first_lead, last_prior):
            if not node:
                continue
            if any(abs(float(node["t_sec"]) - float(b["t_sec"])) < 0.5 for b in boards):
                continue
            boards.append(dict(node))
            if len(boards) >= 2:
                break
        mode = "title_and_key_boards"
        reason = "prior_multi_turn_or_proto_lead_before_last_deficit"
    elif affects:
        mode = "title_summary"
        reason = "prior_single_turn_summary_only"
    else:
        mode = "title_summary"
        reason = "light_prior_context"

    # Never include the behind_start board again (arc already covers deficit)
    behind_t = _safe_float((behind or {}).get("t_sec"))
    if behind_t is not None:
        boards = [
            b
            for b in boards
            if abs(float(b.get("t_sec")) - behind_t) > 1.0
        ]

    return {
        "mode": mode if affects else "none",
        "reason": reason if affects else "prior_does_not_materially_affect_arc_reading",
        "affects_comeback_understanding": affects,
        "boards_to_include": boards if affects and mode == "title_and_key_boards" else [],
        "title_lines": title_lines if affects else [],
        "meaningful_prior_count": len(meaningful),
    }


def build_arc_background_delivery_rows(
    background_plan: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Materialize planner decision into delivery rows (title ± ≤2 scoreboards)."""
    rows: List[Dict[str, Any]] = []
    mode = background_plan.get("mode") or "none"
    if mode == "none":
        return rows
    lines = list(background_plan.get("title_lines") or ["翻盘前情"])
    rows.append(
        {
            "edl_index": 0,
            "segment_id": "seg_arc_background_title",
            "beat": "铺垫",
            "role": "arc_background_title",
            "shot_kind": "title_card",
            "is_replay": False,
            "media_in": None,
            "media_out": None,
            "time_status": "placeholder_title",
            "time_provenance": {
                "source": "story_scope_background_plan",
                "pipeline_verified": False,
            },
            "event_ids": [],
            "frame_ids": [],
            "linked_live_event_id": None,
            "narrative_order": 0,
            "source_media_order": -2,
            "render_eligibility": "candidate_only",
            "blocking_reasons": ["phase5_candidate_delivery", "arc_background_summary"],
            "confidence": 0.8,
            "selection_reason": f"arc_background:{background_plan.get('reason')}",
            "narration": "弧前比分背景摘要（规划器判定需要；非全部进球）",
            "include_in_cut": True,
            "placeholder_sec": 3.0,
            "placeholder_lines": lines[:4],
            "placeholder_lines_qc": lines[:3]
            + [f"bg_mode={mode}", "candidate_only"],
            "evidence_refs": [],
            "source_refs": [],
            "glitch_avoidance": [],
            "goal_action_complete": None,
        }
    )
    for i, node in enumerate(background_plan.get("boards_to_include") or []):
        t = _safe_float(node.get("t_sec"))
        if t is None:
            continue
        rows.append(
            {
                "edl_index": 0,
                "segment_id": f"seg_arc_background_board_{i+1}",
                "beat": "铺垫",
                "role": "arc_background_scoreboard",
                "shot_kind": "scoreboard_anchor",
                "is_replay": False,
                "media_in": round(max(0.0, t - 1.0), 3),
                "media_out": round(t + 2.5, 3),
                "time_status": "score_path_only",
                "time_provenance": {
                    "source": "score_path_prior_context",
                    "t_sec": t,
                    "pipeline_verified": False,
                    "not_a_goal_action": True,
                },
                "event_ids": [],
                "frame_ids": [],
                "linked_live_event_id": None,
                "narrative_order": 0,
                "source_media_order": t,
                "render_eligibility": "candidate_only",
                "blocking_reasons": [
                    "phase5_candidate_delivery",
                    "arc_background_scoreboard_not_goal",
                    "semantic_unverified",
                ],
                "confidence": 0.6,
                "selection_reason": "arc_background_key_prior_score",
                "narration": f"弧前背景比分 {node.get('score')} @ {t}s（非进球动作）",
                "include_in_cut": True,
                "evidence_refs": [],
                "source_refs": [],
                "glitch_avoidance": [],
                "goal_action_complete": None,
            }
        )
    return rows


def build_story_scope(story: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    """Distinguish full-match score background vs selected last-comeback arc."""
    from story_video_agent.state import _comeback_score_steps

    score_path = [n for n in (story.get("score_path") or []) if isinstance(n, dict)]
    steps = _comeback_score_steps(story)
    behind = steps.get("behind_start")
    equalizer = steps.get("equalizer")
    go_ahead = steps.get("go_ahead")
    behind_t = _safe_float((behind or {}).get("t_sec"))
    prior = []
    arc_nodes = []
    for n in score_path:
        t = _safe_float(n.get("t_sec"))
        if behind_t is not None and t is not None and t < behind_t - 1e-6:
            prior.append(
                {
                    "score": n.get("score"),
                    "t_sec": n.get("t_sec"),
                    "delta_side": n.get("delta_side"),
                }
            )
        else:
            arc_nodes.append(
                {
                    "score": n.get("score"),
                    "t_sec": n.get("t_sec"),
                    "delta_side": n.get("delta_side"),
                }
            )
    go_t = _safe_float((go_ahead or {}).get("t_sec"))
    side = (plan.get("protagonist") or {}).get("side")
    extras = [
        n
        for n in score_path
        if go_t is not None
        and _safe_float(n.get("t_sec")) is not None
        and float(n["t_sec"]) > go_t + 1e-6
        and n.get("delta_side") == side
    ][:2]
    background_plan = decide_arc_background_plan(
        prior=prior, protagonist_side=str(side) if side else None, behind=behind
    )
    # Ending media: redundant if same anchor as go_ahead or last lead_extend board
    final = score_path[-1] if score_path else None
    final_t = _safe_float((final or {}).get("t_sec"))
    last_ext_t = None
    for ext in reversed(extras):
        last_ext_t = _safe_float(ext.get("t_sec") if isinstance(ext, dict) else None)
        if last_ext_t is not None:
            break
    wrap_media = "scoreboard_ok"
    if final_t is not None and any(
        abs(final_t - t) <= 1.0 for t in (go_t, last_ext_t) if t is not None
    ):
        wrap_media = "title_card_only"
    return {
        "full_match_score_path": [
            {
                "score": n.get("score"),
                "t_sec": n.get("t_sec"),
                "delta_side": n.get("delta_side"),
            }
            for n in score_path
        ],
        "selected_arc": {
            "kind": "t01_last_deficit_comeback",
            "behind_start": behind,
            "equalizer": equalizer,
            "go_ahead": go_ahead,
            "lead_extends": extras,
            "score_nodes_in_arc": arc_nodes,
        },
        "prior_score_turns_omitted": prior,
        "prior_turns_needed_for_context": bool(
            background_plan.get("affects_comeback_understanding")
        ),
        "background_plan": background_plan,
        "ending_wrap_media_policy": wrap_media,
        "scope_disclaimer": (
            "本次剪辑主线是 T01「最后一次落后弧」；规划器可按需补充弧前背景摘要/关键比分牌，"
            "但不会默认剪成固定三事件，也不会强制纳入全部进球。"
            "整场轨迹见 full_match_score_path；弧前省略见 prior_score_turns_omitted；"
            "补入决策见 background_plan。"
        ),
    }


def build_story_title(plan: Dict[str, Any], story: Dict[str, Any]) -> str:
    proto = (plan.get("protagonist") or {}).get("team_name") or ""
    teams = (plan.get("protagonist") or {}).get("teams") or {}
    left = teams.get("left") or ""
    right = teams.get("right") or ""
    if proto and left and right:
        other = right if proto == left else left
        return f"{proto} 逆转 {other}"
    match_id = str(story.get("match_id") or plan.get("match_id") or "比赛")
    return f"T01 逆风翻盘 · {match_id}"


def _beat_plain_label(role: str) -> str:
    role = role.replace("_incomplete", "")
    if "opponent_opening" in role and "goal" in role:
        return "对手造成落后的进球动作"
    if "deficit" in role or ("scoreboard" in role and "铺垫" in role):
        return "落后比分确认"
    if "equalizer" in role and "goal" in role:
        return "扳平进球动作"
    if "equalizer" in role:
        return "扳平比分确认"
    if "go_ahead" in role and "goal" in role:
        return "反超进球动作"
    if "go_ahead" in role:
        return "反超比分确认"
    if "lead_extend" in role and "goal" in role:
        return "扩大优势进球动作"
    if "lead_extend" in role:
        return "扩大优势比分确认"
    if "buildup" in role:
        return "蓄力阶段相关进攻/事件"
    if "ending" in role:
        return "终场/收尾画面"
    if "title" in role:
        return "标题卡"
    return role


def build_story_summary_md(
    *,
    plan: Dict[str, Any],
    story: Dict[str, Any],
    delivery_edl: Sequence[Dict[str, Any]],
    title: str,
) -> str:
    """甲方可读正文 + 技术附录。不编造球员/战术/未证实因果。"""
    teams = (plan.get("protagonist") or {}).get("teams") or {}
    side = (plan.get("protagonist") or {}).get("side")
    proto = (plan.get("protagonist") or {}).get("team_name") or "主角队"
    other = ""
    if proto and teams:
        other = teams.get("right") if proto == teams.get("left") else teams.get("left")
        other = other or ""
    score_path = [n for n in (story.get("score_path") or []) if isinstance(n, dict)]

    # Score arc in plain language (from structured path only)
    score_plain = []
    for n in score_path:
        who = n.get("delta_side")
        who_name = teams.get(str(who)) if who else None
        if who_name:
            score_plain.append(f"{n.get('score')}（{who_name}取得进球后的比分确认）")
        else:
            score_plain.append(str(n.get("score")))

    goal_rows = [
        r
        for r in delivery_edl
        if "goal_action" in str(r.get("role") or "") and r.get("shot_kind") != "title_card"
    ]
    complete_goals = [r for r in goal_rows if r.get("goal_action_complete") is not False]
    incomplete_goals = [r for r in goal_rows if r.get("goal_action_complete") is False]
    missing = list(plan.get("missing_evidence") or [])

    # ~200–400字摘要：只用结构化事实
    left_n = teams.get("left") or "主队"
    right_n = teams.get("right") or "客队"
    # 最后一次落后弧（非整场所有进球默认全收）
    arc_note = ""
    has_open = any("opponent_opening" in str(r.get("role")) for r in delivery_edl)
    has_eq = any("equalizer_goal" in str(r.get("role")) for r in delivery_edl)
    has_ga = any("go_ahead_goal" in str(r.get("role")) for r in delivery_edl)
    scope = plan.get("story_scope") or {}
    prior = scope.get("prior_score_turns_omitted") or []
    if has_open and has_eq and has_ga:
        arc_note = (
            f"本摘要与成片主线是{proto}在「最后一次落后弧」上的失球→扳平→反超"
            "（T01 选定弧），不得等同于全场所有比分故事。"
        )
        if prior:
            arc_note += (
                f"整场在此弧之前还有 {len(prior)} 次比分转折未纳入本次剪辑主线"
                f"（例如 {[p.get('score') for p in prior[:6]]}）；"
                "若甲方需要完整背景，应单独声明补镜，而非默认已覆盖。"
            )
    abstract = (
        f"本场为「逆风翻盘」类型故事。对阵双方为{left_n}与{right_n}，"
        f"系统认定的故事主角是{proto}"
        + (f"（对手为{other}）" if other else "")
        + "。"
        + arc_note
    )
    if score_plain:
        abstract += "比分确认轨迹为：" + " → ".join(score_plain) + "。"
        abstract += "上述时间为记分牌确认锚点，不等于进球动作发生时刻。"
    abstract += (
        "叙事按铺垫、蓄力、转折、高潮、收尾组织："
        "先交代造成（该弧内）落后的失球，再收录落后期间的相关进攻，"
        "随后是扳平与反超（及可能的扩大优势），最后以终场比分确认收束"
        "（远处「比赛结束」标注若不紧邻终场比分则不采用，以免误切其它转播）。"
    )
    abstract += (
        f"当前结构化收录了 {len(complete_goals)} 个判定为窗口完整的进球动作候选"
    )
    if incomplete_goals or missing:
        abstract += (
            f"，另有 {len(incomplete_goals)} 个进球动作因证据不足或花屏冲突降级为补证，"
            "摘要不将其表述为已核实进球。"
        )
    else:
        abstract += "。"
    abstract += "本文仅陈述算法已结构化的事实；未经验证的战术、球员动作与因果不作断言。"

    # Five beats in plain language
    beat_blocks: List[str] = []
    for beat in ("铺垫", "蓄力", "转折", "高潮", "收尾"):
        items = [r for r in delivery_edl if r.get("beat") == beat]
        if not items:
            beat_blocks.append(f"### {beat}\n本段暂无入选镜头，或证据不足未编排。")
            continue
        lines_b = [f"### {beat}"]
        for r in items:
            label = _beat_plain_label(str(r.get("role") or ""))
            tin, tout = r.get("media_in"), r.get("media_out")
            if tin is None:
                lines_b.append(f"- {label}（标题/说明卡）")
                continue
            status = "窗口完整候选" if r.get("goal_action_complete") is not False or "goal_action" not in str(r.get("role")) else "不完整·待补证"
            if "goal_action" in str(r.get("role") or ""):
                status = "进球动作候选·窗口完整" if r.get("goal_action_complete") is not False else "进球动作·不完整待补证"
            elif "scoreboard" in str(r.get("role") or ""):
                status = "比分确认（非进球动作）"
            lines_b.append(
                f"- {label}：原片约 {tin:.1f}–{tout:.1f} 秒；{status}。"
            )
        beat_blocks.append("\n".join(lines_b))

    # Relations in plain language
    rel_lines = [
        "- 叙事承接：各段按故事顺序衔接，**不代表**已证实战术因果。",
        "- 时间先后：有时间戳的镜头按原片时间排序。",
        "- 比分状态：score_path 相邻节点表示记分牌确认的比分变化。",
        "- 事件关联：进球镜头与事件表/因果链 live 进球的规则匹配；"
        "**不等于**独立语义核验通过，也**不等于**已证实攻防因果。",
    ]

    # Gaps
    gap_lines = []
    for r in incomplete_goals:
        gap_lines.append(
            f"- {_beat_plain_label(str(r.get('role')))}："
            f"完整性失败原因 `{r.get('integrity_failure')}`；"
            f"锚点 {r.get('goal_anchor_t_sec')}；需另搜可用直播镜头。"
        )
    for m in missing:
        gap_lines.append(f"- 缺失证据标记：{m}")
    if not gap_lines:
        gap_lines.append("- 当前无额外补证条目（仍整体为候选，未做独立语义签发）。")

    # Tech appendix table
    tech_rows = [
        "| 段 | 叙事位 | 角色 | 原片入点 | 原片出点 | 关联事件 | 时间状态 | 进球完整 | 核验 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in delivery_edl:
        tech_rows.append(
            f"| {r.get('segment_id')} | {r.get('beat')} | {r.get('role')} | "
            f"{r.get('media_in')} | {r.get('media_out')} | {r.get('event_ids')} | "
            f"{r.get('time_status')} | {r.get('goal_action_complete')} | "
            f"candidate_only / semantic_unverified |"
        )

    lines = [
        f"# {title}",
        "",
        "> 本稿为咪咕甲方可读的故事链内容摘要（候选审核）。"
        "非正式生产授权；画面语义尚未独立核验通过。",
        "",
        "## 比赛与故事类型",
        f"- 对阵：{left_n} vs {right_n}",
        f"- 故事类型：逆风翻盘（T01）",
        f"- 故事主角：{proto}",
        "",
        "## 故事标题",
        title,
        "",
        "## 故事摘要",
        abstract,
        "",
        "## 五段叙事过程",
        "\n\n".join(beat_blocks),
        "",
        "## 故事范围（全场背景 vs 本次剪辑弧）",
        "",
        (scope.get("scope_disclaimer") or "（见 story_scope）"),
        "",
        "### 整场比分背景",
    ]
    full_path = (scope.get("full_match_score_path") or score_path) if scope else score_path
    if full_path:
        for n in full_path:
            lines.append(
                f"- {n.get('score')} @ {n.get('t_sec')}s"
                + (f"（delta={n.get('delta_side')}）" if n.get("delta_side") else "")
            )
    else:
        lines.append("- （无）")
    lines.append("")
    lines.append("### 本次剪辑选取的最后翻盘弧")
    arc = (scope.get("selected_arc") or {}) if scope else {}
    for key, label in (
        ("behind_start", "弧内落后起点"),
        ("equalizer", "扳平"),
        ("go_ahead", "反超"),
    ):
        node = arc.get(key) if isinstance(arc, dict) else None
        if isinstance(node, dict):
            lines.append(f"- {label}：{node.get('score')} @ {node.get('t_sec')}s")
    if prior:
        lines.append("")
        lines.append("### 弧前省略的比分转折（未默认剪入）")
        for n in prior:
            lines.append(f"- {n.get('score')} @ {n.get('t_sec')}s")
        bg = scope.get("background_plan") or {}
        lines.append(
            f"- 规划器背景决策：mode=`{bg.get('mode')}` · "
            f"affects_understanding=`{bg.get('affects_comeback_understanding')}` · "
            f"reason=`{bg.get('reason')}`"
        )
        if bg.get("boards_to_include"):
            lines.append(
                f"- 已规划补入关键弧前比分牌（非进球动作）："
                f"{[b.get('score') for b in bg['boards_to_include']]}"
            )
        lines.append(
            "- 不会固定为「落后→扳平→反超」三事件模板，也不会强制纳入全部进球。"
        )
    lines.extend(
        [
            "",
            "## 关键比分变化（记分牌锚点）",
        ]
    )
    if score_path:
        for n in score_path:
            lines.append(
                f"- 比分确认 **{n.get('score')}**（记分牌锚点约 {n.get('t_sec')} 秒；"
                f"非进球动作时刻）"
            )
    else:
        lines.append("- （无比分轨迹）")
    lines.extend(
        [
            "",
            "## 事件关系说明",
            "\n".join(rel_lines),
            "",
            "## 镜头来源与核验状态（概要）",
            "- 业务版与内部 QC 版共用同一剪辑时间轴（同一 EDL）。",
            "- 全部镜头为算法候选：`render_ready=false`，未授予正式成片。",
            "- 进球动作优先绑定事件表/因果链中的 live 进球时间；比分牌仅作确认，不替代进球。",
            f"- 完整进球动作候选 {len(complete_goals)} 个；不完整/补证 {len(incomplete_goals)} 个。",
            "",
            "## 不能确认的关键事实与缺失证据",
            "\n".join(gap_lines),
            "",
            "---",
            "",
            "## 技术附录",
            "",
            "以下字段供研发/算法复审，不作为甲方主读内容。完整图见 `story_graph.json`，"
            "剪辑表见 `candidate_edl.json`，方案见 `story_plan.json`。",
            "",
            f"- match_id: `{story.get('match_id') or plan.get('match_id')}`",
            f"- story_tier: `{plan.get('story_tier')}`",
            f"- protagonist_side: `{side}`",
            f"- blocking_reasons: `{plan.get('blocking_reasons')}`",
            "",
            "\n".join(tech_rows),
            "",
        ]
    )
    return "\n".join(lines)


def validate_story_graph(graph: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Ensure every edge endpoint exists; relation types are declared; no forged semantic pass."""
    problems: List[str] = []
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    ids = {str(n.get("id")) for n in nodes if n.get("id") is not None}
    if len(ids) != len([n for n in nodes if n.get("id") is not None]):
        problems.append("duplicate_node_id")
    allowed = set(graph.get("relation_types") or [])
    for i, e in enumerate(edges):
        s, t = str(e.get("source")), str(e.get("target"))
        if s not in ids:
            problems.append(f"edge[{i}].source_missing:{s}")
        if t not in ids:
            problems.append(f"edge[{i}].target_missing:{t}")
        rel = e.get("relation")
        if allowed and rel not in allowed:
            problems.append(f"edge[{i}].unknown_relation:{rel}")
        # Candidate associations must not claim semantic verification done
        if e.get("relation") == "event_association" and e.get("semantic_verified") is True:
            problems.append(f"edge[{i}].forged_semantic_verified")
        if e.get("relation") == "causal_verified" and not e.get("independent_verification"):
            problems.append(f"edge[{i}].causal_verified_without_independent_check")
    return (not problems), problems


def build_story_graph(
    *,
    plan: Dict[str, Any],
    story: Dict[str, Any],
    delivery_edl: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Typed nodes/edges; all endpoints exist; no conflation of relation kinds."""
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    id_set: set = set()

    def add_node(node: Dict[str, Any]) -> str:
        nid = str(node["id"])
        if nid in id_set:
            return nid
        id_set.add(nid)
        nodes.append(node)
        return nid

    seg_ids: List[str] = []
    for row in delivery_edl:
        nid = str(row.get("segment_id") or f"seg_{len(seg_ids)}")
        seg_ids.append(
            add_node(
                {
                    "id": nid,
                    "type": "story_segment",
                    "beat": row.get("beat"),
                    "role": row.get("role"),
                    "media_in": row.get("media_in"),
                    "media_out": row.get("media_out"),
                    "time_status": row.get("time_status"),
                    "shot_kind": row.get("shot_kind"),
                    "goal_action_complete": row.get("goal_action_complete"),
                }
            )
        )
        for eid in row.get("event_ids") or []:
            add_node(
                {
                    "id": f"event:{eid}",
                    "type": "event",
                    "event_id": eid,
                    "linked_from_segment": nid,
                }
            )

    # Narrative succession among segments only
    for i in range(len(seg_ids) - 1):
        edges.append(
            {
                "source": seg_ids[i],
                "target": seg_ids[i + 1],
                "relation": "narrative_succession",
                "evidence": "delivery_edl_order",
                "semantic_verified": False,
                "note": "剪辑叙事承接，非已证实因果",
            }
        )

    seg_by_id = {n["id"]: n for n in nodes if n.get("type") == "story_segment"}
    timed = [
        (sid, _safe_float(seg_by_id[sid].get("media_in")))
        for sid in seg_ids
        if _safe_float(seg_by_id.get(sid, {}).get("media_in")) is not None
    ]
    timed.sort(key=lambda x: x[1] or 0)
    for i in range(len(timed) - 1):
        edges.append(
            {
                "source": timed[i][0],
                "target": timed[i + 1][0],
                "relation": "temporal_before",
                "evidence": "media_in_order",
                "semantic_verified": False,
                "note": "原片时间先后（可核对时间戳）",
            }
        )

    sp = [n for n in (story.get("score_path") or []) if isinstance(n, dict)]
    score_ids: List[str] = []
    for i, node in enumerate(sp):
        sid = add_node(
            {
                "id": f"score:{i}:{node.get('score')}",
                "type": "score_state",
                "score": node.get("score"),
                "t_sec": node.get("t_sec"),
                "delta_side": node.get("delta_side"),
                "carrier_event_id": node.get("carrier_event_id"),
            }
        )
        score_ids.append(sid)
        if i > 0:
            edges.append(
                {
                    "source": score_ids[i - 1],
                    "target": sid,
                    "relation": "score_state_change",
                    "evidence": "score_path",
                    "semantic_verified": False,
                    "note": "比分状态变化（记分牌锚点）",
                }
            )

    # Event association (rule-matched); NOT causal_verified / NOT semantic pass
    for row in delivery_edl:
        sid = str(row.get("segment_id"))
        for eid in row.get("event_ids") or []:
            ev_nid = f"event:{eid}"
            if ev_nid not in id_set:
                add_node({"id": ev_nid, "type": "event", "event_id": eid})
            edges.append(
                {
                    "source": sid,
                    "target": ev_nid,
                    "relation": "event_association",
                    "evidence": "segment_event_ids",
                    "semantic_verified": False,
                    "note": "镜头–事件规则关联；未做独立语义核验",
                }
            )
        for ref in row.get("evidence_refs") or []:
            if not isinstance(ref, dict):
                continue
            src = str(ref.get("source") or "")
            if not ref.get("used_as_fact"):
                continue
            if src not in (
                "live_goal_candidate",
                "opponent_opening_live_goal",
                "replay_linked_to_live",
            ):
                continue
            eid = ref.get("event_id") or ref.get("linked_live_event_id")
            if not eid:
                continue
            ev_nid = f"event:{eid}"
            if ev_nid not in id_set:
                add_node({"id": ev_nid, "type": "event", "event_id": eid})
            # Avoid duplicate association edges
            if any(
                e.get("source") == sid
                and e.get("target") == ev_nid
                and e.get("relation") == "event_association"
                for e in edges
            ):
                continue
            edges.append(
                {
                    "source": sid,
                    "target": ev_nid,
                    "relation": "event_association",
                    "evidence": src,
                    "semantic_verified": False,
                    "note": "规则证据上的事件关联；非已证实战术因果，非语义签发",
                }
            )

    graph = {
        "schema": "phase5_1_story_graph_v2",
        "match_id": story.get("match_id") or plan.get("match_id"),
        "nodes": nodes,
        "edges": edges,
        "relation_types": [
            "event_association",
            "score_state_change",
            "temporal_before",
            "narrative_succession",
            # reserved: only when independent verification exists
            "causal_verified",
        ],
        "disclaimer": (
            "narrative_succession / temporal_before / score_state_change / event_association "
            "均不得解释为已完成的独立语义核验或战术因果证实；"
            "causal_verified 仅在具备 independent_verification 时使用（本阶段不自动产出）。"
        ),
    }
    ok, problems = validate_story_graph(graph)
    graph["structure_ok"] = ok
    graph["structure_problems"] = problems
    return graph


def load_glitch_profile(path: Optional[Path]) -> List[Tuple[float, float, str]]:
    if path is None:
        return []
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = data.get("ranges") if isinstance(data, dict) else data
    out: List[Tuple[float, float, str]] = []
    for r in rows or []:
        out.append(
            (
                float(r["media_in"] if isinstance(r, dict) else r[0]),
                float(r["media_out"] if isinstance(r, dict) else r[1]),
                str(r.get("label") if isinstance(r, dict) else (r[2] if len(r) > 2 else "glitch")),
            )
        )
    return out
