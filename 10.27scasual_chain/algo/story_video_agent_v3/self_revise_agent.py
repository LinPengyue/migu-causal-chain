"""V3-A self-revision Agent: real LLM Planner + VLM observe + model Verifier.

Pivot away from rule-only Stage-2 sorting. The LLM diagnoses story quality and
proposes revisions; VLM observes planner-requested windows; Verifier combines
Stage-1 hard gates with model semantic findings. Max three rounds.

Hard rules:
- Never invent score/goal facts or free media timestamps.
- Search windows must cite trusted anchors (T01 score nodes / existing EDL).
- VLM observation is NOT first-LIVE verification.
- Real HTTP requires enable_real_api AND i_approve_budget AND STORY_API_ENABLE=1.
- API failure must be reported honestly; never silently claim Agent success via
  rule/mock/cache fallback.
- Never mutate frozen V3-R Phase5 inputs; working copies only under out_dir.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple  # Tuple used by window/role helpers

from story_video_agent.api_provider import (
    COST_DISCLAIMER,
    ApiCallError,
    ApiConfigError,
    ApiProvider,
    api_enabled,
)
from story_video_agent.frames import FrameBudget, FrameStore
from story_video_agent.media import probe_video
from story_video_agent.vision_provider import _extract_json_obj

from .quality_audit import evaluate as quality_evaluate
from .remote_vlm_verify import apply_trial_env_overrides
from .hybrid_fallback import (
    build_orchestration_status,
    build_rule_planner_fallback,
    run_dual_verifier,
    run_ffmpeg_observe_without_vlm,
    run_rule_verifier,
)

SCHEMA = "v3a_self_revise_run_v1"
MAX_ROUNDS = 3
MAX_DIAGNOSES = 8
# Experimental loop/release composite threshold — not a calibrated production standard.
DEFAULT_QUALITY_THRESHOLD = 75.0
# Confirmed severe fact errors that hard-block loop retain (not mere missing coverage).
LOOP_HARD_VETO_KINDS = frozenset({
    "replay_as_primary",
    "replay_as_first_live",
    "duplicated_goal_event",
    "duplicate_canonical_goal_role",
    "overlapping_goal_windows",
    "baseline_goal_media_regressed",
    "known_integrity_failure",
    "technical_decode_error",
    "bad_media_window",
    "invented_event_or_time",
    "wrong_score_or_team",
    "wrong_attribution",
    "wrong_score",
    "wrong_team",
})
# Stage-1 P0 kinds that are feedback for Planner, not loop-stopping by themselves.
LOOP_FEEDBACK_P0_KINDS = frozenset({
    "missing_story_element",
    "goal_window_incomplete",
})
MAX_TOOL_REQUESTS = 4
MAX_FRAMES_PER_REQUEST = 4
LOOKBACK_SEC = 180.0
AFTER_ANCHOR_SEC = 15.0
MAX_WINDOW_SPAN = 30.0
MIN_BOUND_SPAN = 2.0
MAX_BOUND_SPAN = 40.0
SCORE_ANCHOR_EXCLUSION_SEC = 3.0
MAX_WINDOWS_OBSERVE = 3
MAX_FOLLOWUP_WINDOWS = 2
VERIFIER_MAX_RETRIES = 2
# Overlap / identity thresholds for duplicate-cut guards (match-agnostic).
ROLE_WINDOW_OVERLAP_IOU = 0.45
P1_POLISH_DIRNAME = "04_phase5_p1_polish"
RAW_PHASE5_DIRNAME = "04_phase5"
ROLE_QUALIFIER_SUFFIXES = (
    "_live", "_candidate", "_unverified", "_pending",
    "_approach", "_incomplete", "_reaction", "_transition",
)
ALLOWED_ACTIONS = {
    "search_add", "replace", "trim", "drop", "reorder", "keep", "mark_unresolved",
}
ACTION_ALIASES = {
    "add": "search_add",
    "insert": "search_add",
    "insert_segment": "search_add",
    "search": "search_add",
    "locate": "search_add",
    "recover": "search_add",
    "append": "search_add",
    "remove": "drop",
    "delete": "drop",
    "exclude": "drop",
    "shorten": "trim",
    "cut": "trim",
    "swap": "replace",
    "substitute": "replace",
    "resequence": "reorder",
    "unresolved": "mark_unresolved",
    "skip": "mark_unresolved",
    # Composer handoff dispositions → existing schema (no second protocol).
    "keep_candidate": "keep",
    "retain": "keep",
    "keep_and_inspect": "keep",
    "inspect": "keep",
    "observe": "keep",
    "need_observation": "keep",
    "defer": "mark_unresolved",
}
ALLOWED_TOOLS = {"extract_frames", "vlm_observe", "widen_search"}
TOOL_ALIASES = {
    "frames": "extract_frames",
    "extract": "extract_frames",
    "extract_frames": "extract_frames",
    "observe": "vlm_observe",
    "vlm": "vlm_observe",
    "vision": "vlm_observe",
    "vlm_observe": "vlm_observe",
    "widen": "widen_search",
    "search_widen": "widen_search",
    "widen_search": "widen_search",
    # Observed real-model aliases (France round-1)
    "observe_goal_action_window": "vlm_observe",
    "verify_segment_visual_truth": "vlm_observe",
    "review_segment_scope": "vlm_observe",
    "observe_window": "vlm_observe",
    "check_visual_truth": "vlm_observe",
}
# Story-role shorthand → EDL role + preferred score anchor key
TARGET_ROLE_MAP = {
    "opponent_opening": ("opponent_opening_goal_action", "behind_start"),
    "opponent_opening_goal_action": ("opponent_opening_goal_action", "behind_start"),
    "behind_start": ("opponent_opening_goal_action", "behind_start"),
    "equalizer": ("equalizer_goal_action", "equalizer"),
    "equalizer_goal_action": ("equalizer_goal_action", "equalizer"),
    "go_ahead": ("go_ahead_goal_action", "go_ahead"),
    "go_ahead_goal_action": ("go_ahead_goal_action", "go_ahead"),
}


def _normalize_action(raw: Any) -> Optional[str]:
    s = str(raw or "").strip()
    if not s:
        return None
    if s in ALLOWED_ACTIONS:
        return s
    # KEEP / INSPECT / UNRESOLVED (and REPAIR-without-verb → None)
    try:
        from .composer_evidence_handoff import map_disposition_to_action
        disp = map_disposition_to_action(s)
        if disp is not None:
            return disp
        if s.upper().replace("-", "_") in ("REPAIR", "FIX"):
            return None
    except Exception:
        pass
    low = s.lower()
    if low in ACTION_ALIASES:
        return ACTION_ALIASES[low]
    # e.g. insert_opponent_opening_goal_action → search_add
    for key, mapped in ACTION_ALIASES.items():
        if low.startswith(key + "_") or low.startswith(key):
            return mapped
    if "search" in low or "insert" in low or "add" in low or "recover" in low or "locate" in low:
        return "search_add"
    if "drop" in low or "remove" in low or "delete" in low:
        return "drop"
    if "trim" in low or "shorten" in low:
        return "trim"
    if "replace" in low or "swap" in low:
        return "replace"
    if "reorder" in low:
        return "reorder"
    return None


def _normalize_tool(raw: Any) -> Optional[str]:
    s = str(raw or "").strip()
    if s in ALLOWED_TOOLS:
        return s
    low = s.lower().replace("-", "_")
    if low in TOOL_ALIASES:
        return TOOL_ALIASES[low]
    if "vlm" in low or "vision" in low or "observe" in low or "verify_segment" in low or "visual_truth" in low:
        return "vlm_observe"
    if "review_segment" in low or "scope" in low:
        return "vlm_observe"
    if "frame" in low or "extract" in low:
        return "extract_frames"
    if "widen" in low:
        return "widen_search"
    return None


def _tool_field(tr: Mapping[str, Any]) -> Any:
    for k in ("tool", "tool_name", "toolName", "name", "op"):
        if tr.get(k) not in (None, ""):
            return tr.get(k)
    return None


PLANNER_SYSTEM = """You are a match-agnostic football story-video revision Planner.
Diagnose the CURRENT story cut against THIS match's T01 selected-arc and narrative needs.
Do not assume a fixed goal count, score path, or that any specific beat is missing.
If prior_round_feedback is present, address unresolved issues and verifier findings;
do not blindly repeat the same plan without incorporating that feedback.

composer_evidence_handoff (when present) projects Rule Composer / Phase5 candidates.
For EACH goal-action handoff segment, FIRST choose one disposition then emit schema:
  KEEP → revision_intents.action=keep (retain composer window; no EDL edit)
  INSPECT → action=keep PLUS directed video_tool_requests on that edl trusted_anchor
  REPAIR → concrete action in {search_add,replace,trim,drop,reorder} with evidence_refs
  UNRESOLVED → action=mark_unresolved (do not force an edit)
You may set revision_intents[].disposition to KEEP|INSPECT|REPAIR|UNRESOLVED;
executor maps it onto the actions above (REPAIR alone is invalid without a concrete edit).

Do NOT blanket re-search every goal. Prefer the handoff suggested_planner_disposition.
is_replay=false, scoreboard confirmation, and historical VLM observations are NOT
FIRST_LIVE_VERIFIED. Historical observations may be reused as observation-only evidence.
Return ONLY JSON with keys:
  diagnoses, revision_intents, video_tool_requests, notes.
video_tool_requests[].tool must be one of: vlm_observe, extract_frames, widen_search
  (aliases like observe_goal_action_window are accepted by the executor).
Each tool request needs anchor_id from trusted_anchors. Prefer absolute
search_windows {start,end} in media seconds OR relative
{start_offset_sec,end_offset_sec} on that same anchor (executor converts).
revision_intents need action in {search_add,replace,trim,drop,reorder,keep,mark_unresolved}
plus role and/or anchor_id when proposing search_add.
You MAY improve coverage, coherence, shot relevance, live-vs-replay risk, or drop
redundant cuts — choose the highest-value local change for THIS cut.
You MUST NOT invent scores, goal events, or free absolute media timestamps
without citing a trusted anchor.
Selecting a tool requests observation; it does NOT verify first LIVE goal.
Do not claim render_ready or production release.
"""

VERIFIER_SYSTEM = """Football story-video Verifier. Reply with compact JSON ONLY. No prose, no chain-of-thought.
Keys: issues, dimensions, revision_suggestions, quality_delta_vs_baseline,
hard_vetoes, evidence_of_improvement, live_segment_assessments.
dimensions MUST include exactly these four:
  story_element_coverage, narrative_coherence, image_content_quality, live_authenticity
Each dimension: {status, summary, score, evidence_refs, problems[]}
  status: improved|unchanged|regressed|unknown|insufficient_evidence
  score: number 0-100 OR null when not evaluated (never invent 0/100 for unknown)
live_authenticity scores broadcast first-LIVE risk generically (any match):
  prefer live_segment_assessments[] with
  {segment_id, live_status, score, evidence_refs, reason}
  live_status in:
    FIRST_LIVE_VERIFIED|LIKELY_LIVE|SUSPECTED_REPLAY|CONFIRMED_REPLAY|UNKNOWN
  VLM observation alone cannot set FIRST_LIVE_VERIFIED.
issues: issue_id, severity(P0|P1|P2), dimension, target_segment_id,
problem, evidence_refs, suggested_fix.
hard_vetoes ONLY for confirmed severe fact errors with evidence_refs:
  wrong_score_or_team, replay_as_first_live, severe_corruption, invented_event_or_time.
Do NOT put missing story coverage in hard_vetoes — use issues /
dimensions.story_element_coverage as a repair signal.
SUSPECTED_REPLAY lowers live_authenticity score and feeds next-round repair;
CONFIRMED_REPLAY as primary goal cut is a hard_veto.
evidence_of_improvement: [{claim, evidence_refs}]. Never invent timestamps/scores.
Never set render_ready true. Be match-agnostic: judge against THIS cut's story scope.
"""

VLM_SYSTEM_HINT = (
    "Describe only what is visible in the provided frames. "
    "Relate to the planner question. Flag suspected omissions or wrong shots. "
    "If this window lacks goal-action evidence, say so; do NOT infer the whole "
    "match lacks the goal. Suggest next_search_request only within program-"
    "provided allowed_windows (by index or start/end copied from that list). "
    "Optional structured fields: observed_shot, observed_net, live_or_replay, "
    "supports_bound_segment, candidate_goal_action_span{start,end}, "
    "scoreboard_only. Never set fact_verified true. observation_only must be true."
)


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _num(x: Any) -> Optional[float]:
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _edl_rows(edl: Any) -> List[Dict[str, Any]]:
    if isinstance(edl, list):
        return [r for r in edl if isinstance(r, dict)]
    if isinstance(edl, dict):
        for k in ("segments", "edl", "rows"):
            v = edl.get(k)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
    return []


def canonical_story_role(role: Any) -> str:
    """Strip synonymous qualifiers so opening/_live map to one story role family."""
    r = str(role or "").strip()
    changed = True
    while changed and r:
        changed = False
        for suf in ROLE_QUALIFIER_SUFFIXES:
            if r.endswith(suf):
                r = r[: -len(suf)]
                changed = True
                break
    return r


def _media_iou(a_in: float, a_out: float, b_in: float, b_out: float) -> float:
    inter = max(0.0, min(a_out, b_out) - max(a_in, b_in))
    union = max(a_out, b_out) - min(a_in, b_in)
    if union <= 1e-9:
        return 0.0
    return inter / union


def active_cut_rows(edl: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [
        dict(r) for r in edl
        if isinstance(r, Mapping) and r.get("include_in_cut", True) is not False
    ]


def find_duplicate_goal_cuts(
    edl: Sequence[Mapping[str, Any]],
    *,
    overlap_iou: float = ROLE_WINDOW_OVERLAP_IOU,
) -> List[Dict[str, Any]]:
    """Detect accidental same-role / high-overlap goal cuts (not narrative reuse of distinct roles)."""
    rows = [
        r for r in active_cut_rows(edl)
        if "goal_action" in str(r.get("role") or "") and r.get("shot_kind") != "title_card"
    ]
    dups: List[Dict[str, Any]] = []
    # Same canonical role appearing more than once
    by_role: Dict[str, List[Mapping[str, Any]]] = {}
    for r in rows:
        by_role.setdefault(canonical_story_role(r.get("role")), []).append(r)
    for role, group in by_role.items():
        if len(group) < 2:
            continue
        dups.append({
            "kind": "duplicate_canonical_role",
            "role": role,
            "segment_ids": [str(x.get("segment_id") or "") for x in group],
        })
    # High media overlap within goal_action family (same event risk)
    for i in range(len(rows)):
        ai, ao = _num(rows[i].get("media_in")), _num(rows[i].get("media_out"))
        if ai is None or ao is None or ao <= ai:
            continue
        for j in range(i + 1, len(rows)):
            bi, bo = _num(rows[j].get("media_in")), _num(rows[j].get("media_out"))
            if bi is None or bo is None or bo <= bi:
                continue
            iou = _media_iou(ai, ao, bi, bo)
            same_family = canonical_story_role(rows[i].get("role")) == canonical_story_role(rows[j].get("role"))
            if iou >= overlap_iou or (same_family and iou >= 0.2):
                dups.append({
                    "kind": "overlapping_goal_windows",
                    "iou": round(iou, 3),
                    "segment_ids": [
                        str(rows[i].get("segment_id") or ""),
                        str(rows[j].get("segment_id") or ""),
                    ],
                    "roles": [str(rows[i].get("role") or ""), str(rows[j].get("role") or "")],
                })
    return dups


def resolve_phase5_baseline(
    phase5_dir: Path,
    *,
    prefer_p1_polish: bool = True,
) -> Dict[str, Any]:
    """Prefer sibling ``04_phase5_p1_polish`` when present (accepted V3-R polish).

    Match-agnostic: no team names or fixed goal timestamps. Callers that pass an
    explicit polish dir keep it; ``--no-prefer-p1-polish`` disables the switch.
    """
    requested = phase5_dir.resolve()
    meta: Dict[str, Any] = {
        "requested_phase5_dir": str(requested),
        "resolved_phase5_dir": str(requested),
        "prefer_p1_polish": bool(prefer_p1_polish),
        "switched_to_p1_polish": False,
        "reason": "requested_path_used",
        "requested_edl_sha256": None,
        "resolved_edl_sha256": None,
    }
    req_edl = requested / "candidate_edl.json"
    if req_edl.is_file():
        meta["requested_edl_sha256"] = _sha(req_edl)
        meta["resolved_edl_sha256"] = meta["requested_edl_sha256"]
    if not prefer_p1_polish:
        meta["reason"] = "prefer_p1_polish_disabled"
        return {"path": requested, **meta}
    if requested.name == P1_POLISH_DIRNAME:
        meta["reason"] = "already_p1_polish"
        return {"path": requested, **meta}
    sibling = requested.parent / P1_POLISH_DIRNAME
    if (
        requested.name == RAW_PHASE5_DIRNAME
        and (sibling / "candidate_edl.json").is_file()
        and (sibling / "story_plan.json").is_file()
        and (sibling / "t01_story.json").is_file()
    ):
        resolved = sibling.resolve()
        meta["resolved_phase5_dir"] = str(resolved)
        meta["switched_to_p1_polish"] = True
        meta["reason"] = "sibling_04_phase5_p1_polish_preferred_as_accepted_v3r"
        meta["resolved_edl_sha256"] = _sha(resolved / "candidate_edl.json")
        return {"path": resolved, **meta}
    meta["reason"] = "no_sibling_p1_polish_or_not_raw_phase5"
    return {"path": requested, **meta}


def build_trusted_anchors(plan: Mapping[str, Any], edl: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Trusted media-time sources the model may cite; never free-form times."""
    anchors: List[Dict[str, Any]] = []
    arc = (plan.get("story_scope") or {}).get("selected_arc") or {}
    for key in ("behind_start", "equalizer", "go_ahead"):
        node = arc.get(key)
        if not isinstance(node, dict):
            continue
        t = _num(node.get("t_sec"))
        if t is None:
            continue
        anchors.append({
            "anchor_id": f"score_node:{key}",
            "kind": "T01_selected_arc_score_node",
            "arc_key": key,
            "t_sec": t,
            "score": node.get("score"),
            "note": "score_confirmation_NOT_goal_action",
        })
    for i, ext in enumerate(arc.get("lead_extends") or []):
        if not isinstance(ext, dict):
            continue
        t = _num(ext.get("t_sec"))
        if t is None:
            continue
        anchors.append({
            "anchor_id": f"score_node:lead_extend_{i}",
            "kind": "T01_selected_arc_score_node",
            "arc_key": f"lead_extend_{i}",
            "t_sec": t,
            "score": ext.get("score"),
            "note": "score_confirmation_NOT_goal_action",
        })
    for row in edl:
        sid = str(row.get("segment_id") or "")
        start, end = _num(row.get("media_in")), _num(row.get("media_out"))
        if not sid or start is None or end is None or end <= start:
            continue
        anchors.append({
            "anchor_id": f"edl:{sid}",
            "kind": "existing_edl_segment",
            "segment_id": sid,
            "role": row.get("role"),
            "media_in": start,
            "media_out": end,
        })
    return anchors


def expand_windows_from_anchor(
    anchor: Mapping[str, Any],
    *,
    lookback: float = LOOKBACK_SEC,
    after: float = AFTER_ANCHOR_SEC,
    video_duration: Optional[float] = None,
) -> List[Dict[str, float]]:
    if anchor.get("kind") == "existing_edl_segment":
        start = max(0.0, float(anchor["media_in"]) - 4.0)
        end = float(anchor["media_out"]) + 4.0
        if video_duration is not None:
            end = min(end, float(video_duration))
        return [{"start": round(start, 3), "end": round(min(start + MAX_WINDOW_SPAN, end), 3)}]
    t = _num(anchor.get("t_sec"))
    if t is None:
        raise ValueError("anchor missing t_sec")
    start = max(0.0, t - lookback)
    end = t + after
    if video_duration is not None:
        end = min(end, float(video_duration))
        start = min(start, end)
    out: List[Dict[str, float]] = []
    cur = start
    while cur < end - 1e-6 and len(out) < 8:
        stop = min(end, cur + MAX_WINDOW_SPAN)
        out.append({"start": round(cur, 3), "end": round(stop, 3)})
        cur = stop
    return out


def _frame_pts(frame: Mapping[str, Any]) -> Optional[float]:
    return _num(frame.get("actual_media_sec")) or _num(frame.get("requested_media_sec"))


def _span_inside_windows(start: float, end: float, windows: Sequence[Mapping[str, Any]]) -> bool:
    for w in windows:
        ws, we = _num(w.get("start")), _num(w.get("end"))
        if ws is None or we is None:
            continue
        if start >= ws - 1e-3 and end <= we + 1e-3:
            return True
    return False


def _overlap_window(start: float, end: float, windows: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, float]]:
    best = None
    best_ov = 0.0
    for w in windows:
        ws, we = _num(w.get("start")), _num(w.get("end"))
        if ws is None or we is None:
            continue
        lo, hi = max(start, ws), min(end, we)
        ov = hi - lo
        if ov > best_ov:
            best_ov = ov
            best = {"start": float(ws), "end": float(we)}
    return best if best_ov > 0.5 else None


def parse_next_search_request(
    raw: Any,
    *,
    allowed_windows: Sequence[Mapping[str, Any]],
    prior_window: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    """Map VLM next_search_request onto an allowed trusted window (no free timestamps)."""
    if raw is None or raw is False:
        return None
    windows = [{"start": float(w["start"]), "end": float(w["end"])} for w in allowed_windows]
    if not windows:
        return None
    idx = None
    start = end = None
    reason = "vlm_next_search"
    if isinstance(raw, int):
        idx = raw
    elif isinstance(raw, str):
        reason = raw[:200]
        # "window 2" / "index 2"
        for token in raw.replace(",", " ").split():
            if token.isdigit():
                idx = int(token)
                break
    elif isinstance(raw, dict):
        reason = str(raw.get("reason") or raw.get("why") or reason)[:200]
        if isinstance(raw.get("window_index"), int):
            idx = int(raw["window_index"])
        start = _num(raw.get("start"))
        end = _num(raw.get("end"))
        # Also accept nested window
        nested = raw.get("window") if isinstance(raw.get("window"), dict) else None
        if nested:
            start = start if start is not None else _num(nested.get("start"))
            end = end if end is not None else _num(nested.get("end"))
    if idx is not None and 0 <= idx < len(windows):
        nxt = windows[idx]
        if abs(nxt["start"] - float(prior_window.get("start", -1))) < 1e-6 and abs(
            nxt["end"] - float(prior_window.get("end", -1))
        ) < 1e-6:
            return None
        return {
            "start": nxt["start"], "end": nxt["end"],
            "reason": reason, "selection": f"allowed_index:{idx}",
            "prior_window": dict(prior_window),
        }
    if start is not None and end is not None and end > start:
        # Must match an allowed window (copy), not invent a free span.
        for i, w in enumerate(windows):
            if abs(w["start"] - start) < 0.51 and abs(w["end"] - end) < 0.51:
                if abs(w["start"] - float(prior_window.get("start", -1))) < 1e-6:
                    return None
                return {
                    "start": w["start"], "end": w["end"],
                    "reason": reason, "selection": f"allowed_match:{i}",
                    "prior_window": dict(prior_window),
                }
        hit = _overlap_window(start, end, windows)
        if hit and not (
            abs(hit["start"] - float(prior_window.get("start", -1))) < 1e-6
            and abs(hit["end"] - float(prior_window.get("end", -1))) < 1e-6
        ):
            return {
                **hit,
                "reason": reason + "|snapped_to_allowed_overlap",
                "selection": "allowed_overlap",
                "prior_window": dict(prior_window),
                "rejected_free_span": {"start": start, "end": end},
            }
        return {
            "rejected": True,
            "reason": "next_search_outside_trusted_windows",
            "requested": {"start": start, "end": end},
            "prior_window": dict(prior_window),
        }
    # Default: advance to the next unused window after prior
    ps = _num(prior_window.get("start"))
    for i, w in enumerate(windows):
        if ps is not None and w["start"] > ps + 1e-6:
            return {
                "start": w["start"], "end": w["end"],
                "reason": reason or "advance_to_next_allowed_window",
                "selection": f"sequential_next:{i}",
                "prior_window": dict(prior_window),
            }
    return None


def select_followup_windows(
    *,
    allowed_windows: Sequence[Mapping[str, Any]],
    observed: Sequence[Mapping[str, Any]],
    max_followups: int = MAX_FOLLOWUP_WINDOWS,
) -> Tuple[List[Dict[str, float]], List[Dict[str, Any]]]:
    """After negative/partial observations, pick different allowed windows."""
    used = set()
    log: List[Dict[str, Any]] = []
    for o in observed:
        w = o.get("window") or {}
        used.add((round(float(w.get("start", -1)), 3), round(float(w.get("end", -1)), 3)))
    follow: List[Dict[str, float]] = []
    for o in observed:
        vlm = o.get("vlm") if isinstance(o.get("vlm"), dict) else {}
        prior = o.get("window") or {}
        # Negative / incomplete window must not conclude match-level absence.
        neg = bool(vlm.get("scoreboard_only")) or (
            vlm.get("observed_shot") is False and vlm.get("observed_net") is False
        ) or ("0-0" in str(vlm.get("visible_content") or "") and not vlm.get("supports_bound_segment"))
        if not neg and not vlm.get("next_search_request"):
            continue
        nxt = parse_next_search_request(
            vlm.get("next_search_request") if vlm.get("next_search_request") is not None else "next",
            allowed_windows=allowed_windows,
            prior_window=prior,
        )
        if not nxt or nxt.get("rejected"):
            if nxt:
                log.append(nxt)
            continue
        key = (round(nxt["start"], 3), round(nxt["end"], 3))
        if key in used:
            log.append({**nxt, "skipped": "already_observed"})
            continue
        used.add(key)
        follow.append({"start": nxt["start"], "end": nxt["end"]})
        log.append({**nxt, "scheduled": True})
        if len(follow) >= max_followups:
            break
    return follow, log


def authorize_bound_segment(
    *,
    media_in: float,
    media_out: float,
    role: str,
    frames: Sequence[Mapping[str, Any]],
    vlm: Mapping[str, Any],
    trusted_windows: Sequence[Mapping[str, Any]],
    score_anchor_sec: Optional[float] = None,
) -> Dict[str, Any]:
    """Independent gate: VLM alone never grants verified_first_live."""
    denies: List[str] = []
    checks: Dict[str, Any] = {
        "first_live_verified": False,
        "observation_only": True,
    }
    span = media_out - media_in
    if span < MIN_BOUND_SPAN or span > MAX_BOUND_SPAN:
        denies.append("span_out_of_bounds")
    pts_ok = all(_num(f.get("actual_media_sec")) is not None for f in frames) and bool(frames)
    checks["pts_present"] = pts_ok
    if not pts_ok:
        denies.append("missing_actual_pts")
    if not _span_inside_windows(media_in, media_out, trusted_windows):
        # Allow span that overlaps a trusted window and is fully inside union of lookback
        if trusted_windows:
            union_lo = min(float(w["start"]) for w in trusted_windows)
            union_hi = max(float(w["end"]) for w in trusted_windows)
            if not (media_in >= union_lo - 1e-3 and media_out <= union_hi + 1e-3):
                denies.append("outside_trusted_search_union")
            else:
                checks["inside_trusted_union"] = True
        else:
            denies.append("no_trusted_windows")
    else:
        checks["inside_trusted_window"] = True
    if score_anchor_sec is not None:
        mid = 0.5 * (media_in + media_out)
        # Scoreboard confirmation time must not masquerade as goal-action cut.
        if abs(mid - float(score_anchor_sec)) <= SCORE_ANCHOR_EXCLUSION_SEC:
            denies.append("score_confirmation_time_cannot_be_goal_action")
        if abs(media_in - float(score_anchor_sec)) <= 0.5 and abs(media_out - (float(score_anchor_sec) + 4)) <= 1.0:
            denies.append("looks_like_scoreboard_anchor_clip")
        checks["not_score_anchor_masquerade"] = "score_confirmation_time_cannot_be_goal_action" not in denies
    if vlm.get("fact_verified") is True:
        denies.append("vlm_overclaim_fact_verified")
    if str(vlm.get("live_or_replay") or "").lower() == "replay":
        denies.append("replay_cannot_bind_primary_goal")
    if vlm.get("scoreboard_only") is True:
        denies.append("scoreboard_only_not_goal_action")
    supports = bool(vlm.get("supports_bound_segment")) or (
        vlm.get("observed_shot") is True and vlm.get("observed_net") is True
    )
    cand_span = vlm.get("candidate_goal_action_span")
    if isinstance(cand_span, dict):
        cs, ce = _num(cand_span.get("start")), _num(cand_span.get("end"))
        if cs is not None and ce is not None and ce > cs:
            supports = True
    checks["vlm_supports_bound"] = supports
    if not supports:
        denies.append("vlm_lacks_goal_action_support_fields")
    if not role or "goal_action" not in role:
        # Non-goal roles can bind with weaker supports if explicitly requested
        if "goal_action" not in role and not denies:
            pass
    allow = len(denies) == 0
    return {
        "allow": allow,
        "denies": denies,
        "checks": checks,
        "media_in": round(media_in, 3),
        "media_out": round(media_out, 3),
        "role": role,
        "evidence_status": "CANDIDATE_BOUND_UNVERIFIED_FIRST_LIVE" if allow else "REJECTED",
        "first_live_status": "NOT_VERIFIED",
        "agent_auto_verified": False,
    }


def build_bound_segment_from_observations(
    *,
    intent: Mapping[str, Any],
    observations: Sequence[Mapping[str, Any]],
    trusted_windows: Sequence[Mapping[str, Any]],
    score_anchor_sec: Optional[float],
) -> Dict[str, Any]:
    """Construct a candidate cut from real frame PTS + structured VLM fields."""
    role = str(intent.get("role") or "").strip()
    if not role:
        return {
            "ok": False,
            "reason": "bound_segment_requires_explicit_role",
            "tried": 0,
        }
    issue_id = intent.get("issue_id")
    matched = [
        o for o in observations
        if o.get("ok") and (issue_id is None or o.get("issue_id") == issue_id or not o.get("issue_id"))
    ]
    if not matched:
        matched = [o for o in observations if o.get("ok")]
    for o in matched:
        vlm = o.get("vlm") if isinstance(o.get("vlm"), dict) else {}
        frames = list(o.get("frames") or [])
        pts = [_frame_pts(f) for f in frames]
        pts = [p for p in pts if p is not None]
        if not pts:
            continue
        # Prefer explicit candidate span if it cites times inside observed PTS range
        cand = vlm.get("candidate_goal_action_span")
        if isinstance(cand, dict):
            mi, mo = _num(cand.get("start")), _num(cand.get("end"))
        else:
            mi = mo = None
        if mi is None or mo is None or mo <= mi:
            mi, mo = min(pts) - 1.0, max(pts) + 1.0
        # Clamp to observed window
        win = o.get("window") or {}
        ws, we = _num(win.get("start")), _num(win.get("end"))
        if ws is not None:
            mi = max(mi, ws)
        if we is not None:
            mo = min(mo, we)
        if mo - mi < MIN_BOUND_SPAN:
            continue
        auth = authorize_bound_segment(
            media_in=float(mi),
            media_out=float(mo),
            role=role,
            frames=frames,
            vlm=vlm,
            trusted_windows=trusted_windows,
            score_anchor_sec=score_anchor_sec,
        )
        if not auth["allow"]:
            continue
        return {
            "ok": True,
            "authorization": auth,
            "segment": {
                "segment_id": f"seg_{role}",
                "role": role,
                "media_in": auth["media_in"],
                "media_out": auth["media_out"],
                "include_in_cut": True,
                # NOT_VERIFIED must not be coerced into a live/non-replay claim.
                "is_replay": None,
                "shot_kind": "goal_action_candidate",
                "goal_action_complete": True,
                "event_ids": list(intent.get("event_ids") or []),
                "agent_bound": True,
                "evidence_status": auth["evidence_status"],
                "first_live_status": "NOT_VERIFIED",
                "agent_auto_verified": False,
                "binding_observation_id": o.get("request_id"),
                "binding_frame_ids": [f.get("frame_id") for f in frames],
                "anchor_id": intent.get("anchor_id"),
            },
            "observation_ref": o.get("request_id"),
        }
    return {
        "ok": False,
        "reason": "no_observation_passed_independent_binding_gate",
        "tried": len(matched),
    }


def important_goal_segment_ids(edl: Sequence[Dict[str, Any]]) -> List[str]:
    out = []
    for r in edl:
        role = str(r.get("role") or "")
        if "goal_action" in role and r.get("include_in_cut", True) and r.get("shot_kind") != "title_card":
            sid = str(r.get("segment_id") or "")
            if sid:
                out.append(sid)
    return out


def important_segments_regressed(
    baseline: Sequence[Dict[str, Any]],
    candidate: Sequence[Dict[str, Any]],
) -> List[str]:
    """Detect unintended damage to previously correct key goal cuts.

    ``agent_bound=True`` alone does **not** exempt media drift: unverified binds
    must not silently expand/replace a previously valid goal window.
    """
    base = {str(r.get("segment_id")): r for r in baseline if r.get("segment_id")}
    cand = {str(r.get("segment_id")): r for r in candidate if r.get("segment_id")}
    regressions = []
    for sid in important_goal_segment_ids(baseline):
        b, c = base.get(sid), cand.get(sid)
        if c is None or c.get("include_in_cut", True) is False:
            # Drop of baseline goal still flagged; decide_accept may allow intentional drop.
            if not (isinstance(c, dict) and c.get("agent_drop_reason")):
                regressions.append(sid + ":removed_or_excluded")
            continue
        if b is None:
            continue
        b_in, b_out = _num(b.get("media_in")), _num(b.get("media_out"))
        c_in, c_out = _num(c.get("media_in")), _num(c.get("media_out"))
        baseline_ok = b_in is not None and b_out is not None and b_out > b_in
        if baseline_ok and None not in (c_in, c_out):
            shifted = abs(b_in - c_in) > 2.0 or abs(b_out - c_out) > 2.0
            if shifted:
                verified = (
                    c.get("first_live_status") == "FIRST_LIVE_VERIFIED"
                    or c.get("agent_auto_verified") is True
                )
                # Modest shrink via explicit trim is allowed; expansions / jumps need verification.
                shrunk = (c_out - c_in) <= (b_out - b_in) + 0.5 and c.get("agent_trim")
                if not verified and not shrunk:
                    regressions.append(sid + ":media_shifted")
        if c.get("is_replay") is True and b.get("is_replay") is not True:
            regressions.append(sid + ":became_replay")
    # Also catch duplicate synonym inserts that leave baseline goal while adding _live twin
    for dup in find_duplicate_goal_cuts(candidate):
        regressions.append("duplicate:" + str(dup.get("kind")) + ":" + ",".join(dup.get("segment_ids") or []))
    return regressions


def coverage_score(audit: Mapping[str, Any]) -> Optional[float]:
    try:
        return float(
            ((audit.get("dimensions") or {}).get("story_element_coverage") or {}).get("score")
        )
    except (TypeError, ValueError):
        return None


def coherence_score(audit: Mapping[str, Any]) -> Optional[float]:
    try:
        return float(
            ((audit.get("dimensions") or {}).get("story_coherence") or {}).get("score")
        )
    except (TypeError, ValueError):
        return None


def image_quality_score(audit: Mapping[str, Any]) -> Optional[float]:
    """Map Stage-1 image_quality scan to 0–100 or None (UNKNOWN / not evaluated)."""
    iq = (audit.get("dimensions") or {}).get("image_quality")
    if not isinstance(iq, dict) or not iq:
        return None
    if iq.get("decode_error_count"):
        return 0.0
    # Screened but no severe decode errors → provisional structural pass, not calibrated.
    if iq.get("scanned") or iq.get("path") or "decode_error_count" in iq:
        anomalies = bool(iq.get("possible_black_intervals") or iq.get("possible_freeze_intervals"))
        return 70.0 if anomalies else 90.0
    return None


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None or isinstance(x, bool):
            return None
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def composite_quality_score(
    audit: Mapping[str, Any],
    *,
    verifier_validated: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Average of evaluated dims only. UNKNOWN/NOT_EVALUATED never become 0."""
    dims_out: Dict[str, Any] = {}
    numeric: List[float] = []
    unknown: List[str] = []

    cov = coverage_score(audit)
    coh = coherence_score(audit)
    img = image_quality_score(audit)

    api_dims = (verifier_validated or {}).get("dimensions") or {}
    # Equal-weight across evaluated dims only (experimental; not calibrated).
    for name, rule_score, api_key in (
        ("story_element_coverage", cov, "story_element_coverage"),
        ("narrative_coherence", coh, "narrative_coherence"),
        ("image_content_quality", img, "image_content_quality"),
        ("live_authenticity", None, "live_authenticity"),
    ):
        api_d = api_dims.get(api_key) if isinstance(api_dims.get(api_key), dict) else {}
        status = str(api_d.get("status") or "")
        api_score = _safe_float(api_d.get("score"))
        if status in ("NOT_EVALUATED", "UNKNOWN", "insufficient_evidence", "unknown"):
            if rule_score is not None:
                dims_out[name] = {"score": rule_score, "source": "rule_proxy", "status": "EVALUATED"}
                numeric.append(rule_score)
            else:
                dims_out[name] = {"score": None, "source": "api", "status": "UNKNOWN"}
                unknown.append(name)
        elif api_score is not None:
            dims_out[name] = {"score": api_score, "source": "api", "status": status or "EVALUATED"}
            numeric.append(api_score)
        elif rule_score is not None:
            dims_out[name] = {"score": rule_score, "source": "rule_proxy", "status": "EVALUATED"}
            numeric.append(rule_score)
        else:
            if name == "narrative_coherence" and coh is not None:
                dims_out[name] = {"score": coh, "source": "rule_proxy", "status": "EVALUATED"}
                numeric.append(coh)
            else:
                dims_out[name] = {"score": None, "source": None, "status": "UNKNOWN"}
                unknown.append(name)

    if "narrative_coherence" not in dims_out and coh is not None:
        dims_out["narrative_coherence"] = {"score": coh, "source": "rule_proxy", "status": "EVALUATED"}
        numeric.append(coh)

    composite = round(sum(numeric) / len(numeric), 2) if numeric else None
    return {
        "composite": composite,
        "dimensions": dims_out,
        "unknown_dimensions": unknown,
        "evaluated_count": len(numeric),
        "equal_weight": True,
        "note": (
            "Equal-weight mean over EVALUATED dims only; UNKNOWN excluded "
            "(never coerced to 0 or 100). Cross-round compare shared dims."
        ),
    }


def severe_hard_findings(audit: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Confirmed severe fact/technical errors (loop hard block). Missing coverage is excluded."""
    out: List[Dict[str, Any]] = []
    for f in audit.get("hard_gate_findings") or []:
        if not isinstance(f, dict):
            continue
        kind = str(f.get("kind") or f.get("issue_kind") or "")
        if kind in LOOP_HARD_VETO_KINDS:
            out.append(dict(f))
        elif kind in LOOP_FEEDBACK_P0_KINDS:
            continue
        elif str(f.get("severity")) == "P0" and kind not in LOOP_FEEDBACK_P0_KINDS:
            # Unknown P0 kinds: treat as severe only if explicitly marked confirmed.
            if f.get("confirmed") or f.get("fact_verified"):
                out.append(dict(f))
    return out


def feedback_findings(audit: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Non-blocking diagnostics for Planner (missing elements, soft issues)."""
    out: List[Dict[str, Any]] = []
    for f in (audit.get("hard_gate_findings") or []) + (audit.get("diagnostic_issues") or []):
        if not isinstance(f, dict):
            continue
        kind = str(f.get("kind") or "")
        if kind in LOOP_FEEDBACK_P0_KINDS or str(f.get("severity")) in ("P1", "P2"):
            out.append(dict(f))
    return out


def compact_context(
    *,
    story: Mapping[str, Any],
    plan: Mapping[str, Any],
    edl: Sequence[Dict[str, Any]],
    audit: Mapping[str, Any],
    predicted_causal: Optional[Mapping[str, Any]] = None,
    stage2_proposal: Optional[Mapping[str, Any]] = None,
    prior_observations: Optional[Sequence[Mapping[str, Any]]] = None,
    prior_round_feedback: Optional[Mapping[str, Any]] = None,
    video_duration: Optional[float] = None,
) -> Dict[str, Any]:
    """Pack planner/verifier inputs; keep payload small and evidence-labelled.

    prior_round_feedback carries last-round diagnoses / verifier issues / unresolved
    items so Round N+1 is not a blind re-call of the same Planner.
    """
    anchors = build_trusted_anchors(plan, edl)
    arc = (plan.get("story_scope") or {}).get("selected_arc") or {}
    edl_brief = [{
        "segment_id": r.get("segment_id"),
        "role": r.get("role"),
        "media_in": r.get("media_in"),
        "media_out": r.get("media_out"),
        "event_ids": r.get("event_ids"),
        "is_replay": r.get("is_replay"),
        "shot_kind": r.get("shot_kind"),
        "beat": r.get("beat") or r.get("narrative_beat"),
    } for r in edl]
    # Keep prompt small: only goal-ish chains near selected-arc score times.
    chains_brief = []
    arc_times = []
    for key in ("behind_start", "equalizer", "go_ahead"):
        t = _num((arc.get(key) or {}).get("t_sec")) if isinstance(arc.get(key), dict) else None
        if t is not None:
            arc_times.append(t)
    if isinstance(predicted_causal, dict):
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for ch in predicted_causal.get("causal_chains") or []:
            if not isinstance(ch, dict):
                continue
            atoms = ch.get("atoms") or ch.get("events") or []
            brief_atoms = []
            nearest = None
            for a in atoms:
                if not isinstance(a, dict):
                    continue
                typ = str(a.get("type") or a.get("event_type") or "")
                t = _num(a.get("t_sec"))
                if t is None and _num(a.get("t_ms")) is not None:
                    t = float(a["t_ms"]) / 1000.0
                if t is not None and arc_times:
                    d = min(abs(t - at) for at in arc_times)
                    nearest = d if nearest is None else min(nearest, d)
                if "goal" in typ.lower() or typ in ("进球", "Goal", "Assist", "Shot"):
                    brief_atoms.append({
                        "event_id": a.get("event_id") or a.get("id"),
                        "type": typ,
                        "t_sec": t,
                        "is_replay": a.get("is_replay") or a.get("event_is_replay"),
                    })
                if len(brief_atoms) >= 6:
                    break
            if not brief_atoms:
                continue
            scored.append((nearest if nearest is not None else 1e9, {
                "chain_id": ch.get("chain_id") or ch.get("id"),
                "terminal_type": ch.get("terminal_type") or ch.get("outcome"),
                "atoms": brief_atoms,
            }))
        scored.sort(key=lambda x: x[0])
        chains_brief = [c for _, c in scored[:8]]
    s2_tasks = []
    for t in ((stage2_proposal or {}).get("selected_tasks") or [])[:4]:
        if not isinstance(t, dict):
            continue
        s2_tasks.append({
            "task_id": t.get("task_id"),
            "issue_kind": t.get("issue_kind"),
            "severity": t.get("severity"),
            "issue_target": t.get("issue_target"),
            "score_anchor_sec": t.get("score_anchor_sec"),
            "search_windows": (t.get("search_windows") or [])[:3],
            "anchor_kind": t.get("anchor_kind"),
        })
    from .composer_evidence_handoff import build_composer_evidence_handoff

    handoff = build_composer_evidence_handoff(
        edl, prior_observations=prior_observations,
    )
    return {
        "match_id": plan.get("match_id") or story.get("match_id"),
        "title": plan.get("title") or story.get("title"),
        "protagonist": plan.get("protagonist") or story.get("protagonist"),
        "selected_arc_brief": {
            k: {"t_sec": (arc.get(k) or {}).get("t_sec"), "score": (arc.get(k) or {}).get("score")}
            for k in ("behind_start", "equalizer", "go_ahead")
            if isinstance(arc.get(k), dict)
        },
        "trusted_anchors": anchors,
        "video_duration_sec": video_duration,
        "candidate_edl": edl_brief,
        "composer_evidence_handoff": handoff,
        "stage1_hard_gates": audit.get("hard_gate_findings") or [],
        "stage1_diagnostics": audit.get("diagnostic_issues") or [],
        "stage1_revision_requests": audit.get("revision_requests") or [],
        "stage1_unverified": audit.get("unverified") or [],
        "stage1_structural_proxy_pass": audit.get("structural_proxy_pass"),
        "stage2_selected_tasks": s2_tasks,
        "predicted_causal_sample": chains_brief,
        "prior_observations": list(prior_observations or [])[-6:],
        "prior_round_feedback": prior_round_feedback or None,
        "constraints": {
            "cannot_invent_scores_or_goal_facts": True,
            "cannot_invent_absolute_timestamps": True,
            "must_cite_trusted_anchors_for_search": True,
            "vlm_is_observation_only": True,
            "match_agnostic_general_agent": True,
            "do_not_assume_fixed_goal_count_or_score_path": True,
            "max_diagnoses": MAX_DIAGNOSES,
            "max_video_tool_requests": MAX_TOOL_REQUESTS,
            "render_ready": False,
            "composer_is_replay_false_is_not_first_live": True,
            "historical_vlm_obs_cannot_certify_first_live": True,
            "prefer_handoff_disposition_over_blanket_goal_research": True,
        },
    }


def _parse_model_json(content: str, *, empty_code: str = "EMPTY_MODEL_CONTENT") -> Dict[str, Any]:
    text = str(content or "").strip()
    if not text:
        raise ValueError(empty_code)
    try:
        obj = _extract_json_obj(text)
    except Exception as exc:
        # Remap vision-provider empty wording for Planner/Verifier paths.
        msg = str(exc)
        if "empty" in msg.lower():
            raise ValueError(empty_code) from exc
        raise
    if not isinstance(obj, dict):
        raise ValueError("model JSON must be an object")
    return obj


def _anchor_t_sec(anchor: Mapping[str, Any]) -> Optional[float]:
    if anchor.get("kind") == "existing_edl_segment":
        return _num(anchor.get("media_in"))
    return _num(anchor.get("t_sec"))


def _clip_abs_window(
    start: float,
    end: float,
    *,
    video_duration: Optional[float],
) -> Optional[Dict[str, float]]:
    if end <= start:
        return None
    s, e = float(start), float(end)
    if s < 0:
        s = 0.0
    if video_duration is not None:
        dur = float(video_duration)
        if s > dur + 1e-6:
            return None
        e = min(e, dur)
    if e - s < 0.5:
        return None
    if e - s > MAX_WINDOW_SPAN + 1e-6:
        e = s + MAX_WINDOW_SPAN
    return {"start": round(s, 3), "end": round(e, 3)}


def _resolve_relative_windows(
    raw_windows: Sequence[Any],
    *,
    default_anchor: Mapping[str, Any],
    by_id: Mapping[str, Mapping[str, Any]],
    video_duration: Optional[float],
) -> Tuple[List[Dict[str, float]], List[Dict[str, Any]]]:
    """Convert relative offset windows or absolute start/end; reject free inventions."""
    out: List[Dict[str, float]] = []
    rejects: List[Dict[str, Any]] = []
    for w in raw_windows:
        if not isinstance(w, dict):
            rejects.append({"raw": w, "reason": "window_not_object",
                            "suggested_fix": "use {start,end} or {start_offset_sec,end_offset_sec}"})
            continue
        aid = str(w.get("anchor_id") or default_anchor.get("anchor_id") or "")
        anchor = by_id.get(aid) or default_anchor
        if aid and aid not in by_id and aid != str(default_anchor.get("anchor_id")):
            rejects.append({
                "raw": w, "reason": "window_unknown_anchor",
                "suggested_fix": f"cite trusted anchor_id; got {aid!r}",
            })
            continue
        t0 = _anchor_t_sec(anchor)
        if t0 is None:
            rejects.append({"raw": w, "reason": "anchor_missing_time",
                            "suggested_fix": "anchor must have t_sec or media_in"})
            continue
        # Absolute media times
        abs_start, abs_end = _num(w.get("start")), _num(w.get("end"))
        off_s, off_e = _num(w.get("start_offset_sec")), _num(w.get("end_offset_sec"))
        if abs_start is not None and abs_end is not None:
            # Absolute times must still be near the cited anchor (not free PTS invent).
            # Allow within LOOKBACK+AFTER+small margin of anchor time / EDL span.
            if anchor.get("kind") == "existing_edl_segment":
                lo = float(anchor["media_in"]) - LOOKBACK_SEC
                hi = float(anchor["media_out"]) + AFTER_ANCHOR_SEC + MAX_WINDOW_SPAN
            else:
                lo = float(t0) - LOOKBACK_SEC - 30.0
                hi = float(t0) + AFTER_ANCHOR_SEC + MAX_WINDOW_SPAN
            if abs_start < lo - 1e-3 or abs_end > hi + 1e-3:
                rejects.append({
                    "raw": w, "reason": "absolute_window_outside_anchor_bound",
                    "suggested_fix": "keep absolute window within anchor lookback/after envelope",
                })
                continue
            clipped = _clip_abs_window(abs_start, abs_end, video_duration=video_duration)
            if clipped is None:
                rejects.append({"raw": w, "reason": "absolute_window_invalid_or_oob",
                                "suggested_fix": "ensure end>start and within video duration"})
                continue
            out.append(clipped)
            continue
        if off_s is not None and off_e is not None:
            clipped = _clip_abs_window(
                float(t0) + float(off_s), float(t0) + float(off_e),
                video_duration=video_duration,
            )
            if clipped is None:
                rejects.append({
                    "raw": w, "reason": "relative_window_invalid_or_oob",
                    "suggested_fix": "offsets must yield in-range end>start vs anchor t_sec",
                })
                continue
            out.append(clipped)
            continue
        rejects.append({
            "raw": w, "reason": "window_missing_start_end_or_offsets",
            "suggested_fix": "provide start/end or start_offset_sec/end_offset_sec",
        })
    return out, rejects


def _map_role_and_anchor(
    *,
    role: Any,
    anchor_id: Any,
    target: Any,
    target_segment_id: Any,
    action_text: Any,
    by_id: Mapping[str, Mapping[str, Any]],
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (role, anchor_id, map_note)."""
    role_s = str(role or "").strip() or None
    aid = str(anchor_id or "").strip() or None
    tgt = str(target or target_segment_id or "").strip() or None
    note = None

    if not role_s and isinstance(action_text, str) and "goal_action" in action_text:
        role_s = action_text.replace("insert_", "").replace("add_", "").replace("Locate/recover ", "")
        if " " in role_s:
            role_s = None

    # target shorthand
    key = None
    for cand in (tgt, role_s):
        if not cand:
            continue
        low = cand.lower().replace(" ", "_")
        if low in TARGET_ROLE_MAP:
            key = low
            break
        if low.endswith("_goal_action") and low in TARGET_ROLE_MAP:
            key = low
            break
        # strip seg_ prefix
        if low.startswith("seg_"):
            low2 = low[4:]
            if low2 in TARGET_ROLE_MAP:
                key = low2
                break

    if key:
        mapped_role, arc_key = TARGET_ROLE_MAP[key]
        role_s = role_s or mapped_role
        prefer = f"score_node:{arc_key}"
        if not aid and prefer in by_id:
            aid = prefer
            note = f"mapped_target:{key}->{prefer}"
        elif not aid:
            # try edl role match
            for a in by_id.values():
                if a.get("kind") == "existing_edl_segment" and str(a.get("role") or "") == mapped_role:
                    aid = str(a["anchor_id"])
                    note = f"mapped_target_edl:{key}->{aid}"
                    break
        role_s = mapped_role

    if aid and aid not in by_id:
        return role_s, None, f"unknown_anchor:{aid}"
    if aid and aid in by_id:
        return role_s, aid, note
    return role_s, None, note


def validate_planner_output(
    raw: Mapping[str, Any],
    *,
    trusted_anchors: Sequence[Mapping[str, Any]],
    video_duration: Optional[float],
) -> Dict[str, Any]:
    """Normalize real-model Planner JSON; reject invented free PTS; record drops."""
    by_id = {str(a["anchor_id"]): a for a in trusted_anchors}
    diagnoses = raw.get("diagnoses")
    if not isinstance(diagnoses, list):
        raise ValueError("diagnoses must be a list")
    diagnoses = diagnoses[:MAX_DIAGNOSES]
    clean_diag = []
    for i, d in enumerate(diagnoses):
        if not isinstance(d, dict):
            continue
        refs = d.get("evidence_refs")
        if isinstance(refs, list):
            norm_refs = [{"ref": x} if isinstance(x, str) else x for x in refs if x]
        else:
            norm_refs = []
        clean_diag.append({
            "issue_id": str(d.get("issue_id") or d.get("id") or d.get("diagnosis_id") or f"diag_{i:03d}"),
            "problem": str(d.get("problem") or d.get("detail") or "")[:800],
            "severity": d.get("severity") if d.get("severity") in ("P0", "P1", "P2") else "P2",
            "target_segment_id": d.get("target_segment_id") or d.get("target"),
            "story_element": d.get("story_element") or d.get("kind"),
            "evidence_refs": norm_refs,
            "expected_improvement": str(d.get("expected_improvement") or d.get("suggested_action") or "")[:400],
        })

    intents = raw.get("revision_intents")
    if not isinstance(intents, list):
        intents = []
    clean_intents: List[Dict[str, Any]] = []
    dropped_intents: List[Dict[str, Any]] = []
    for i, it in enumerate(intents[:MAX_DIAGNOSES]):
        if not isinstance(it, dict):
            dropped_intents.append({
                "raw": it, "reason": "intent_not_object",
                "suggested_fix": "each revision_intent must be an object",
            })
            continue
        from .composer_evidence_handoff import normalize_intent_disposition

        disp_meta = normalize_intent_disposition(it)
        action_raw = it.get("action")
        # If action is a disposition keyword (KEEP/INSPECT/...), normalize it;
        # if disposition=REPAIR without concrete edit verb, reject.
        if disp_meta.get("disposition_needs_concrete_repair") and (
            not action_raw
            or str(action_raw).strip().upper().replace("-", "_") in ("REPAIR", "FIX")
        ):
            dropped_intents.append({
                "raw": it, "reason": "repair_disposition_needs_concrete_action",
                "suggested_fix": (
                    "REPAIR requires action in search_add|replace|trim|drop|reorder"
                ),
                "map_note": disp_meta.get("composer_disposition"),
            })
            continue
        action = _normalize_action(action_raw)
        if action is None and disp_meta.get("disposition_mapped_action"):
            action = disp_meta["disposition_mapped_action"]
        if action is None:
            dropped_intents.append({
                "raw": it, "reason": "unmapped_action",
                "suggested_fix": (
                    "use search_add|replace|trim|drop|reorder|keep|mark_unresolved "
                    "or disposition KEEP|INSPECT|UNRESOLVED "
                    f"(got {it.get('action')!r} disposition={it.get('disposition')!r})"
                ),
            })
            continue
        role, aid, map_note = _map_role_and_anchor(
            role=it.get("role"),
            anchor_id=it.get("anchor_id"),
            target=it.get("target"),
            target_segment_id=it.get("target_segment_id"),
            action_text=it.get("action"),
            by_id=by_id,
        )
        if action == "search_add" and not (role or aid):
            dropped_intents.append({
                "raw": it, "reason": "search_add_missing_role_or_anchor",
                "suggested_fix": "set role (goal_action role for THIS story arc) and/or trusted anchor_id",
                "map_note": map_note,
            })
            continue
        if map_note and str(map_note).startswith("unknown_anchor:"):
            dropped_intents.append({
                "raw": it, "reason": "unknown_anchor",
                "suggested_fix": "cite anchor_id from trusted_anchors",
                "map_note": map_note,
            })
            continue
        notes = [x for x in (map_note, disp_meta.get("composer_disposition")) if x]
        clean_intents.append({
            "intent_id": str(it.get("intent_id") or it.get("id") or f"intent_{i:03d}"),
            "action": action,
            "raw_action": it.get("action"),
            "disposition": disp_meta.get("composer_disposition"),
            "issue_id": it.get("issue_id"),
            "target_segment_id": it.get("target_segment_id") or it.get("target"),
            "role": role,
            "anchor_id": aid,
            "rationale": str(it.get("rationale") or it.get("action") or "")[:600],
            "expected_improvement": str(it.get("expected_improvement") or "")[:400],
            "risk": str(it.get("risk") or "")[:400],
            "evidence_refs": it.get("evidence_refs") if isinstance(it.get("evidence_refs"), list) else [],
            "map_note": ";".join(str(n) for n in notes) if notes else map_note,
        })

    tools = raw.get("video_tool_requests")
    if not isinstance(tools, list):
        tools = []
    raw_tool_count = sum(1 for t in tools if isinstance(t, dict))
    clean_tools: List[Dict[str, Any]] = []
    dropped_tools: List[Dict[str, Any]] = []
    for i, tr in enumerate(tools[:MAX_TOOL_REQUESTS]):
        if not isinstance(tr, dict):
            dropped_tools.append({
                "raw": tr, "reason": "tool_not_object",
                "suggested_fix": "each video_tool_request must be an object",
                "was_recoverable": False,
            })
            continue
        raw_tool_val = _tool_field(tr)
        tool = _normalize_tool(raw_tool_val)
        if tool is None:
            dropped_tools.append({
                "raw": tr, "reason": "unmapped_tool",
                "suggested_fix": (
                    "set tool/tool_name to vlm_observe|extract_frames|widen_search "
                    f"(got {raw_tool_val!r})"
                ),
                "was_recoverable": False,
            })
            continue
        aid = str(tr.get("anchor_id") or "")
        # Infer anchor from target when missing
        if not aid:
            _role, inferred, _n = _map_role_and_anchor(
                role=tr.get("role"),
                anchor_id=None,
                target=tr.get("target"),
                target_segment_id=tr.get("target_segment_id"),
                action_text=None,
                by_id=by_id,
            )
            aid = inferred or ""
        if aid not in by_id:
            dropped_tools.append({
                "raw": tr, "reason": "unknown_anchor",
                "suggested_fix": "cite anchor_id from trusted_anchors",
                "was_recoverable": bool(_normalize_tool(raw_tool_val)),
            })
            continue
        default_windows = expand_windows_from_anchor(by_id[aid], video_duration=video_duration)
        windows_source = "trusted_anchor_expansion"
        windows: List[Dict[str, float]] = []
        raw_wins = tr.get("search_windows")
        if isinstance(raw_wins, list) and raw_wins:
            windows, win_rejects = _resolve_relative_windows(
                raw_wins, default_anchor=by_id[aid], by_id=by_id, video_duration=video_duration,
            )
            for rj in win_rejects:
                dropped_tools.append({
                    "raw": {"tool": raw_tool_val, "window": rj.get("raw"), "anchor_id": aid},
                    "reason": rj.get("reason"),
                    "suggested_fix": rj.get("suggested_fix"),
                    "was_recoverable": False,
                })
            if windows:
                windows_source = "anchor_relative_or_absolute_normalized"
            else:
                # Fall back to trusted expansion rather than dropping the whole tool
                windows = default_windows[:3]
                windows_source = "trusted_anchor_expansion_after_window_reject"
        else:
            idx = tr.get("window_indices")
            if isinstance(idx, list) and idx:
                picked = []
                for j in idx:
                    if isinstance(j, int) and 0 <= j < len(default_windows):
                        picked.append(default_windows[j])
                windows = picked or default_windows[:3]
                windows_source = "trusted_anchor_window_indices"
            else:
                windows = default_windows[:3]
        if not windows:
            dropped_tools.append({
                "raw": tr, "reason": "no_valid_windows",
                "suggested_fix": "provide relative offsets on trusted anchor or omit windows for default expansion",
                "was_recoverable": True,
            })
            continue
        question = str(
            tr.get("question") or tr.get("reason") or tr.get("detail") or ""
        )[:600]
        clean_tools.append({
            "request_id": str(tr.get("request_id") or f"tool_{i:03d}"),
            "tool": tool,
            "raw_tool": raw_tool_val,
            "issue_id": tr.get("issue_id"),
            "anchor_id": aid,
            "question": question,
            "search_windows": windows[:3],
            "windows_source": windows_source,
        })

    # Silent-drop guard: model emitted tools that look recoverable but none survived.
    recoverable_raw = 0
    for tr in tools:
        if not isinstance(tr, dict):
            continue
        if _normalize_tool(_tool_field(tr)) is not None:
            recoverable_raw += 1
    silent_drop_violation = bool(recoverable_raw > 0 and len(clean_tools) == 0)
    if silent_drop_violation:
        raise ValueError(
            "planner_normalization_silent_drop: "
            f"{recoverable_raw} recoverable tool request(s) produced 0 clean tools; "
            "refusing to report Planner success. See dropped_tools for reasons."
        )

    if not clean_diag and not clean_intents and not clean_tools:
        raise ValueError("planner produced no usable diagnoses/intents/tools after validation")
    return {
        "diagnoses": clean_diag,
        "revision_intents": clean_intents,
        "video_tool_requests": clean_tools,
        "dropped_intents": dropped_intents,
        "dropped_tools": dropped_tools,
        "raw_tool_count": raw_tool_count,
        "recoverable_raw_tool_count": recoverable_raw,
        "silent_drop_violation": False,
        "notes": (
            json.dumps(raw.get("notes"), ensure_ascii=False)
            if isinstance(raw.get("notes"), (dict, list))
            else str(raw.get("notes") or "")
        )[:800],
        "validated": True,
    }


def validate_verifier_output(raw: Mapping[str, Any]) -> Dict[str, Any]:
    issues = raw.get("issues")
    if not isinstance(issues, list):
        raise ValueError("verifier issues must be a list")
    clean = []
    for i, iss in enumerate(issues[:MAX_DIAGNOSES]):
        if not isinstance(iss, dict):
            continue
        refs = iss.get("evidence_refs")
        if isinstance(refs, list):
            refs = [{"ref": x} if isinstance(x, str) else x for x in refs]
        else:
            refs = []
        clean.append({
            "issue_id": str(iss.get("issue_id") or f"v_{i:03d}"),
            "severity": iss.get("severity") if iss.get("severity") in ("P0", "P1", "P2") else "P2",
            "dimension": str(iss.get("dimension") or "unknown"),
            "target_segment_id": iss.get("target_segment_id"),
            "problem": str(iss.get("problem") or "")[:800],
            "evidence_refs": refs,
            "suggested_fix": str(iss.get("suggested_fix") or "")[:400],
        })
    dim_src = raw.get("dimensions") if isinstance(raw.get("dimensions"), dict) else {}
    if not dim_src and isinstance(raw.get("dimension_notes"), dict):
        dim_src = raw["dimension_notes"]
    required_dims = (
        "story_element_coverage",
        "narrative_coherence",
        "image_content_quality",
        "live_authenticity",
    )
    dimensions: Dict[str, Any] = {}
    for name in required_dims:
        d = dim_src.get(name) if isinstance(dim_src.get(name), dict) else {}
        status = str(d.get("status") or "unknown")
        if status not in (
            "improved", "unchanged", "regressed", "unknown", "insufficient_evidence",
            "NOT_EVALUATED",
        ):
            status = "unknown"
        score = _safe_float(d.get("score"))
        if status in ("unknown", "insufficient_evidence", "NOT_EVALUATED") and score is None:
            # Preserve explicit null; never coerce unknown → 0/100
            pass
        elif score is not None:
            score = max(0.0, min(100.0, float(score)))
        dimensions[name] = {
            "status": status,
            "summary": str(d.get("summary") or d.get("note") or "")[:600],
            "score": score,
            "evidence_refs": d.get("evidence_refs") if isinstance(d.get("evidence_refs"), list) else [],
            "problems": d.get("problems") if isinstance(d.get("problems"), list) else [],
        }
    live_seg = raw.get("live_segment_assessments")
    live_segment_assessments: List[Dict[str, Any]] = []
    if isinstance(live_seg, list):
        allowed_live = {
            "FIRST_LIVE_VERIFIED", "LIKELY_LIVE", "SUSPECTED_REPLAY",
            "CONFIRMED_REPLAY", "UNKNOWN",
        }
        for row in live_seg[:24]:
            if not isinstance(row, dict):
                continue
            st = str(row.get("live_status") or "UNKNOWN").upper()
            if st not in allowed_live:
                st = "UNKNOWN"
            sc = _safe_float(row.get("score"))
            if st == "UNKNOWN":
                sc = None
            elif sc is not None:
                sc = max(0.0, min(100.0, float(sc)))
            live_segment_assessments.append({
                "segment_id": str(row.get("segment_id") or "")[:120],
                "live_status": st,
                "score": sc,
                "evidence_refs": row.get("evidence_refs") if isinstance(row.get("evidence_refs"), list) else [],
                "reason": str(row.get("reason") or "")[:400],
            })
        # If dimension score missing, derive equal-weight mean of known segment scores
        if dimensions["live_authenticity"].get("score") is None and live_segment_assessments:
            known = [x["score"] for x in live_segment_assessments if x.get("score") is not None]
            if known:
                dimensions["live_authenticity"]["score"] = round(sum(known) / len(known), 2)
                if dimensions["live_authenticity"]["status"] in ("unknown", "NOT_EVALUATED"):
                    dimensions["live_authenticity"]["status"] = "unchanged"
    hard_raw = raw.get("hard_vetoes") if isinstance(raw.get("hard_vetoes"), list) else []
    # Coverage gaps (missing opening etc.) are repair signals, not loop-stopping fact errors.
    coverage_veto_kinds = {
        "missing_required_node", "missing_story_element", "missing_opening",
        "incomplete_coverage", "missing_goal_action",
    }
    hard: List[Any] = []
    demoted_coverage: List[Any] = []
    for hv in hard_raw:
        if isinstance(hv, dict):
            kind = str(hv.get("kind") or hv.get("code") or hv.get("type") or "").lower()
            text = str(hv.get("problem") or hv.get("detail") or hv.get("summary") or "").lower()
            if kind in coverage_veto_kinds or (
                "missing" in text and ("opening" in text or "coverage" in text or "node" in text)
                and "replay" not in text and "score" not in text and "corrupt" not in text
            ):
                demoted_coverage.append(hv)
                clean.append({
                    "issue_id": str(hv.get("issue_id") or f"demoted_{len(clean):03d}"),
                    "severity": "P0",
                    "dimension": "story_element_coverage",
                    "target_segment_id": hv.get("target_segment_id") or hv.get("target"),
                    "problem": str(hv.get("problem") or hv.get("detail") or kind or "missing_coverage")[:800],
                    "evidence_refs": hv.get("evidence_refs") if isinstance(hv.get("evidence_refs"), list) else [],
                    "suggested_fix": "revise_coverage_via_planner_tools",
                    "demoted_from_hard_veto": True,
                })
                continue
        hard.append(hv)
    eoi = raw.get("evidence_of_improvement") if isinstance(raw.get("evidence_of_improvement"), list) else []
    return {
        "issues": clean,
        "dimensions": dimensions,
        "dimension_notes": dimensions,  # backward-compatible alias
        "live_segment_assessments": live_segment_assessments,
        "hard_vetoes": hard,
        "demoted_coverage_vetoes": demoted_coverage,
        "evidence_of_improvement": eoi,
        "revision_suggestions": raw.get("revision_suggestions") if isinstance(raw.get("revision_suggestions"), list) else [],
        "quality_delta_vs_baseline": str(raw.get("quality_delta_vs_baseline") or "")[:600],
        "validated": True,
    }


def call_llm_planner(
    api: ApiProvider,
    context: Mapping[str, Any],
    *,
    fixture: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    if fixture is not None:
        validated = validate_planner_output(
            fixture,
            trusted_anchors=context["trusted_anchors"],
            video_duration=context.get("video_duration_sec"),
        )
        return {
            "ok": True,
            "provider_mode": "offline_fixture",
            "raw": fixture,
            "validated": validated,
            "usage": {"real_requests": 0},
            "est_cost_usd": 0.0,
        }
    user = json.dumps(context, ensure_ascii=False)
    # Intentionally no usable mock_decision for real Agent runs: failure must surface.
    resp = api.plan_decision(
        system_prompt=PLANNER_SYSTEM,
        user_prompt=user,
        mock_decision={"error": "mock_not_allowed_for_self_revise_agent"},
    )
    mode = str(resp.get("provider_mode") or "")
    content = str(resp.get("content") or "")
    if mode != "real" or resp.get("error"):
        return {
            "ok": False,
            "provider_mode": mode or "degraded",
            "error": str(resp.get("error") or f"planner_not_real:{mode}"),
            "raw_content": content,
            "raw_excerpt": content[:8000],
            "usage": resp.get("usage"),
            "est_cost_usd": resp.get("est_cost_usd"),
            "model": resp.get("model"),
        }
    try:
        raw = _parse_model_json(content)
        validated = validate_planner_output(
            raw,
            trusted_anchors=context["trusted_anchors"],
            video_duration=context.get("video_duration_sec"),
        )
    except Exception as exc:
        return {
            "ok": False,
            "provider_mode": mode,
            "error": f"planner_parse_or_validate:{type(exc).__name__}:{exc}",
            "raw_content": content,
            "raw_excerpt": content[:8000],
            "usage": resp.get("usage"),
            "est_cost_usd": resp.get("est_cost_usd"),
            "model": resp.get("model"),
        }
    return {
        "ok": True,
        "provider_mode": mode,
        "model": resp.get("model"),
        "raw": raw,
        "validated": validated,
        "raw_content": content,
        "raw_excerpt": content[:8000],
        "usage": resp.get("usage"),
        "est_cost_usd": resp.get("est_cost_usd"),
        "cost_disclaimer": COST_DISCLAIMER,
    }


def call_llm_verifier(
    api: ApiProvider,
    payload: Mapping[str, Any],
    *,
    fixture: Optional[Mapping[str, Any]] = None,
    max_retries: int = VERIFIER_MAX_RETRIES,
) -> Dict[str, Any]:
    if fixture is not None:
        return {
            "ok": True,
            "provider_mode": "offline_fixture",
            "validated": validate_verifier_output(fixture),
            "raw": fixture,
            "usage": {"real_requests": 0},
            "est_cost_usd": 0.0,
            "attempts": [{"provider_mode": "offline_fixture", "ok": True}],
            "http_ok": True,
            "generation_ok": True,
            "structured_ok": True,
        }
    attempts: List[Dict[str, Any]] = []
    last: Dict[str, Any] = {}
    for attempt in range(max(1, int(max_retries) + 1)):
        try:
            # Prefer verify_decision (stats_role=verifier; optional no-thinking override).
            if hasattr(api, "verify_decision"):
                resp = api.verify_decision(  # type: ignore[attr-defined]
                    system_prompt=VERIFIER_SYSTEM,
                    user_prompt=json.dumps(payload, ensure_ascii=False),
                    mock_decision={"error": "mock_not_allowed_for_self_revise_agent"},
                )
            else:
                resp = api.plan_decision(
                    system_prompt=VERIFIER_SYSTEM,
                    user_prompt=json.dumps(payload, ensure_ascii=False),
                    mock_decision={"error": "mock_not_allowed_for_self_revise_agent"},
                )
        except (ApiConfigError, ApiCallError) as exc:
            last = {
                "ok": False,
                "provider_mode": "degraded",
                "error": f"{type(exc).__name__}:{exc}",
                "attempt": attempt,
                "http_ok": False,
                "generation_ok": False,
                "structured_ok": False,
                "failure_code": "HTTP_OR_TRANSPORT",
            }
            attempts.append(dict(last))
            msg = str(exc).lower()
            if "502" in msg or "timeout" in msg or "proxy" in msg or "503" in msg:
                continue
            break
        mode = str(resp.get("provider_mode") or "")
        content = str(resp.get("content") or "")
        usage = resp.get("usage") or {}
        reasoning_tokens = None
        details = usage.get("completion_tokens_details")
        if isinstance(details, dict) and details.get("reasoning_tokens") is not None:
            try:
                reasoning_tokens = int(details["reasoning_tokens"])
            except (TypeError, ValueError):
                reasoning_tokens = None
        http_ok = mode == "real" and not resp.get("error")
        if mode != "real" or resp.get("error"):
            last = {
                "ok": False,
                "provider_mode": mode or "degraded",
                "error": str(resp.get("error") or f"verifier_not_real:{mode}"),
                "raw_excerpt": content[:2000],
                "usage": usage,
                "est_cost_usd": resp.get("est_cost_usd"),
                "attempt": attempt,
                "http_ok": False,
                "generation_ok": False,
                "structured_ok": False,
                "failure_code": "HTTP_OR_PROVIDER",
                "reasoning_tokens": reasoning_tokens,
            }
            attempts.append(dict(last))
            err_l = str(last["error"]).lower()
            if "502" in err_l or "timeout" in err_l or "proxy" in err_l or "503" in err_l:
                continue
            break
        if not content.strip():
            last = {
                "ok": False,
                "provider_mode": mode,
                "error": "EMPTY_MODEL_CONTENT",
                "failure_code": "EMPTY_MODEL_CONTENT",
                "raw_excerpt": "",
                "usage": usage,
                "est_cost_usd": resp.get("est_cost_usd"),
                "attempt": attempt,
                "http_ok": True,
                "generation_ok": False,
                "structured_ok": False,
                "reasoning_tokens": reasoning_tokens,
                "note": (
                    "HTTP succeeded but visible content empty "
                    "(often reasoning consumed output budget)."
                ),
            }
            attempts.append(dict(last))
            # Retry once more — model may return short JSON on next try
            continue
        try:
            raw = _parse_model_json(content, empty_code="EMPTY_MODEL_CONTENT")
            validated = validate_verifier_output(raw)
        except Exception as exc:
            code = "EMPTY_MODEL_CONTENT" if "EMPTY_MODEL_CONTENT" in str(exc) else "STRUCTURED_PARSE_FAIL"
            last = {
                "ok": False,
                "provider_mode": mode,
                "error": f"{code}:{type(exc).__name__}:{exc}",
                "failure_code": code,
                "raw_excerpt": content[:2000],
                "usage": usage,
                "est_cost_usd": resp.get("est_cost_usd"),
                "attempt": attempt,
                "http_ok": True,
                "generation_ok": bool(content.strip()),
                "structured_ok": False,
                "reasoning_tokens": reasoning_tokens,
            }
            attempts.append(dict(last))
            if code == "EMPTY_MODEL_CONTENT":
                continue
            break
        return {
            "ok": True,
            "provider_mode": mode,
            "model": resp.get("model"),
            "raw": raw,
            "validated": validated,
            "raw_excerpt": content[:4000],
            "usage": usage,
            "est_cost_usd": resp.get("est_cost_usd"),
            "cost_disclaimer": COST_DISCLAIMER,
            "attempts": attempts + [{
                "attempt": attempt, "ok": True, "provider_mode": mode,
                "http_ok": True, "generation_ok": True, "structured_ok": True,
            }],
            "http_ok": True,
            "generation_ok": True,
            "structured_ok": True,
            "reasoning_tokens": reasoning_tokens,
            "logical_role": "verifier",
        }
    # Never silently treat as rule-success
    last = dict(last or {"ok": False, "error": "verifier_unknown_failure", "provider_mode": "degraded"})
    last["ok"] = False
    last["attempts"] = attempts
    last.setdefault("http_ok", False)
    last.setdefault("generation_ok", False)
    last.setdefault("structured_ok", False)
    last.setdefault("logical_role", "verifier")
    last["rule_fallback_success"] = False
    return last


def _observe_one_window(
    api: ApiProvider,
    *,
    store: FrameStore,
    tr: Mapping[str, Any],
    win: Mapping[str, Any],
    allowed_windows: Sequence[Mapping[str, Any]],
    request_id: str,
) -> Dict[str, Any]:
    start, end = float(win["start"]), float(win["end"])
    times = store.sample_times(start, end, count=min(MAX_FRAMES_PER_REQUEST, 4))
    frames = []
    for t in times:
        rec = store.extract_at(
            t,
            gap_id=str(tr.get("request_id") or "obs"),
            tool="self_revise_observe",
        )
        frames.append(rec.to_dict())
    prompt = (
        f"{VLM_SYSTEM_HINT}\n"
        f"Planner question: {tr.get('question')}\n"
        f"issue_id: {tr.get('issue_id')}\n"
        f"anchor_id: {tr.get('anchor_id')}\n"
        f"window: [{start:.3f},{end:.3f}]\n"
        f"allowed_windows: {json.dumps(list(allowed_windows), ensure_ascii=False)}\n"
        "A negative finding in THIS window does not prove the goal is absent from the match.\n"
        "Return JSON keys: visible_content, story_relation, suspected_errors,"
        "shot_suggestions, next_search_request, cited_frame_ids, confidence,"
        "observed_shot, observed_net, live_or_replay, supports_bound_segment,"
        "candidate_goal_action_span, scoreboard_only,"
        "fact_verified(false), observation_only(true)."
    )
    mock_obj = {
        "visible_content": "mock_forbidden",
        "fact_verified": False,
        "observation_only": True,
        "cited_frame_ids": [f["frame_id"] for f in frames[:1]],
    }
    paths = [Path(f["path"]) for f in frames]
    fids = [f["frame_id"] for f in frames]
    bindings = [{
        "frame_id": f["frame_id"],
        "requested_media_sec": f.get("requested_media_sec"),
        "actual_media_sec": f.get("actual_media_sec"),
        "pts_status": f.get("pts_status"),
    } for f in frames]
    try:
        raw_resp = api.vision_json(
            prompt=prompt,
            frame_paths=paths,
            frame_ids=fids,
            mock_obj=mock_obj,
            frame_bindings=bindings,
        )
    except (ApiConfigError, ApiCallError) as exc:
        return {
            "request_id": request_id,
            "issue_id": tr.get("issue_id"),
            "anchor_id": tr.get("anchor_id"),
            "ok": False,
            "error": f"{type(exc).__name__}:{exc}",
            "provider_mode": "degraded",
            "frames": frames,
            "window": {"start": start, "end": end},
            "fact_verified": False,
            "observation_only": True,
        }
    mode = str(raw_resp.get("provider_mode") or "")
    if mode == "openai_compatible":
        mode = "real"
    content = str(raw_resp.get("content") or "")
    parsed = None
    parse_error = None
    try:
        parsed = _parse_model_json(content)
    except Exception as exc:
        parse_error = f"{type(exc).__name__}:{exc}"
    ok = mode == "real" and not raw_resp.get("error") and parsed is not None
    if parsed is not None:
        # Hard force: never let a single VLM pass claim first-LIVE verification
        parsed["fact_verified"] = False
        parsed["observation_only"] = True
    return {
        "request_id": request_id,
        "issue_id": tr.get("issue_id"),
        "anchor_id": tr.get("anchor_id"),
        "ok": ok,
        "provider_mode": mode,
        "model": raw_resp.get("model"),
        "error": None if ok else (str(raw_resp.get("error") or parse_error or f"not_real:{mode}")),
        "frames": frames,
        "window": {"start": start, "end": end},
        "vlm": parsed,
        "raw_excerpt": content[:3000],
        "usage": raw_resp.get("usage"),
        "est_cost_usd": raw_resp.get("est_cost_usd"),
        "fact_verified": False,
        "observation_only": True,
        "allowed_windows": list(allowed_windows),
    }


def run_vlm_observations(
    api: ApiProvider,
    *,
    video: Path,
    work_dir: Path,
    tool_requests: Sequence[Mapping[str, Any]],
    frame_budget: int = 16,
    max_windows_per_request: int = MAX_WINDOWS_OBSERVE,
    max_followups: int = MAX_FOLLOWUP_WINDOWS,
) -> Dict[str, Any]:
    """Observe multiple trusted windows; schedule follow-ups from VLM feedback."""
    work_dir.mkdir(parents=True, exist_ok=True)
    media = probe_video(video)
    store = FrameStore(
        media,
        out_dir=work_dir / "frames",
        budget=FrameBudget(max_frames=frame_budget),
    )
    observations: List[Dict[str, Any]] = []
    schedule_log: List[Dict[str, Any]] = []
    for tr in tool_requests:
        if tr.get("tool") not in ("extract_frames", "vlm_observe", "widen_search"):
            continue
        windows = list(tr.get("search_windows") or [])
        if not windows:
            continue
        # Observe up to N initial windows (not only the first)
        initial = windows[: max(1, int(max_windows_per_request))]
        local_obs: List[Dict[str, Any]] = []
        for i, win in enumerate(initial):
            rid = f"{tr.get('request_id') or 'tool'}_w{i}"
            obs = _observe_one_window(
                api, store=store, tr=tr, win=win,
                allowed_windows=windows, request_id=rid,
            )
            local_obs.append(obs)
            observations.append(obs)
        follow, flog = select_followup_windows(
            allowed_windows=windows,
            observed=local_obs,
            max_followups=max_followups,
        )
        schedule_log.extend(flog)
        for j, win in enumerate(follow):
            # Skip if already observed
            if any(
                abs(float((o.get("window") or {}).get("start", -1)) - float(win["start"])) < 1e-6
                for o in local_obs
            ):
                continue
            rid = f"{tr.get('request_id') or 'tool'}_follow{j}"
            schedule_log.append({
                "scheduled_followup": True,
                "request_id": rid,
                "window": win,
                "reason": "vlm_observation_feedback",
                "prior_windows": [o.get("window") for o in local_obs],
            })
            obs = _observe_one_window(
                api, store=store, tr=tr, win=win,
                allowed_windows=windows, request_id=rid,
            )
            obs["followup"] = True
            local_obs.append(obs)
            observations.append(obs)
    return {
        "observations": observations,
        "frame_manifest": store.manifest,
        "window_schedule_log": schedule_log,
        "any_real_ok": any(o.get("ok") and o.get("provider_mode") == "real" for o in observations),
        "note": (
            "Negative observation in one window is local only; "
            "it does not prove match-level absence of the story element."
        ),
    }


def apply_candidate_revision(
    baseline_edl: Sequence[Dict[str, Any]],
    intents: Sequence[Mapping[str, Any]],
    observations: Sequence[Mapping[str, Any]],
    *,
    trusted_windows_by_anchor: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
    score_anchor_by_anchor_id: Optional[Mapping[str, float]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Apply evidence-bound working-copy edits; never invent media times."""
    edl = copy.deepcopy(list(baseline_edl))
    applied: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    by_id = {str(r.get("segment_id")): i for i, r in enumerate(edl)}
    obs_ok = [o for o in observations if o.get("ok")]
    tw_map = trusted_windows_by_anchor or {}
    sa_map = score_anchor_by_anchor_id or {}
    for it in intents:
        action = it.get("action")
        sid = it.get("target_segment_id")
        if action in ("keep", "mark_unresolved"):
            applied.append({"intent": it.get("intent_id"), "action": action, "status": "recorded"})
            continue
        if action == "drop":
            if sid and sid in by_id:
                role = str(edl[by_id[sid]].get("role") or "")
                # Do not drop critical goal_action without explicit allow_drop_goal flag
                if "goal_action" in role and not it.get("allow_drop_goal"):
                    rejected.append({
                        "intent": it.get("intent_id"),
                        "reason": "refuse_drop_critical_goal_without_flag",
                    })
                    continue
                edl[by_id[sid]]["include_in_cut"] = False
                edl[by_id[sid]]["agent_drop_reason"] = it.get("rationale")
                applied.append({
                    "intent": it.get("intent_id"), "action": "drop", "segment_id": sid,
                    "status": "applied", "evidence_refs": it.get("evidence_refs") or [],
                })
            else:
                rejected.append({"intent": it.get("intent_id"), "reason": "missing_segment"})
            continue
        if action == "trim" and sid and sid in by_id:
            frames = []
            for o in obs_ok:
                if o.get("issue_id") == it.get("issue_id"):
                    frames.extend(o.get("frames") or [])
            pts = [_frame_pts(f) for f in frames]
            pts = [p for p in pts if p is not None]
            row = edl[by_id[sid]]
            mi, mo = _num(row.get("media_in")), _num(row.get("media_out"))
            if mi is None or mo is None or not pts:
                rejected.append({"intent": it.get("intent_id"), "reason": "no_pts_for_trim"})
                continue
            lo, hi = min(pts), max(pts)
            if not (mi - 1e-3 <= lo <= mo + 1e-3 and mi - 1e-3 <= hi <= mo + 1e-3):
                rejected.append({"intent": it.get("intent_id"), "reason": "pts_outside_segment"})
                continue
            new_in = max(mi, lo - 1.0)
            new_out = min(mo, hi + 1.0)
            if new_out - new_in < MIN_BOUND_SPAN:
                rejected.append({"intent": it.get("intent_id"), "reason": "trim_too_short"})
                continue
            row["media_in"], row["media_out"] = round(new_in, 3), round(new_out, 3)
            row["agent_trim"] = True
            applied.append({
                "intent": it.get("intent_id"), "action": "trim", "segment_id": sid,
                "status": "applied_evidence_bound",
                "media_in": row["media_in"], "media_out": row["media_out"],
            })
            continue
        if action in ("search_add", "replace"):
            aid = str(it.get("anchor_id") or "")
            role_req = str(it.get("role") or "").strip()
            canon = canonical_story_role(role_req)
            # search_add: refuse synonym / overlapping duplicates of an already-correct cut
            if action == "search_add" and canon:
                existing_same = []
                for row in edl:
                    if row.get("include_in_cut", True) is False:
                        continue
                    if canonical_story_role(row.get("role")) != canon:
                        continue
                    if "goal_action" not in str(row.get("role") or ""):
                        continue
                    mi, mo = _num(row.get("media_in")), _num(row.get("media_out"))
                    if mi is not None and mo is not None and mo > mi:
                        existing_same.append(row)
                if existing_same:
                    rejected.append({
                        "intent": it.get("intent_id"),
                        "reason": "duplicate_role_or_window_already_present",
                        "role": role_req,
                        "canonical_role": canon,
                        "existing_segment_ids": [
                            str(r.get("segment_id") or "") for r in existing_same
                        ],
                        "note": "use replace with evidence if the existing cut must change",
                    })
                    continue
            trusted = list(tw_map.get(aid) or [])
            # Fallback: union of windows mentioned on matching observations
            if not trusted:
                for o in obs_ok:
                    trusted.extend(o.get("allowed_windows") or [])
                    w = o.get("window")
                    if isinstance(w, dict) and _num(w.get("start")) is not None:
                        trusted.append(w)
            score_anchor = sa_map.get(aid)
            bound = build_bound_segment_from_observations(
                intent=it,
                observations=obs_ok,
                trusted_windows=trusted,
                score_anchor_sec=score_anchor,
            )
            if not bound.get("ok"):
                applied.append({
                    "intent": it.get("intent_id"),
                    "action": action,
                    "status": "pending_evidence_slot",
                    "role": it.get("role"),
                    "anchor_id": aid,
                    "bind_failure": bound,
                    "note": "no independent PTS/VLM gate passed; not written to EDL",
                })
                continue
            seg = bound["segment"]
            new_sid = str(seg["segment_id"])
            new_in, new_out = _num(seg.get("media_in")), _num(seg.get("media_out"))
            overlap_reject = False
            if new_in is not None and new_out is not None and action == "search_add":
                for row in edl:
                    if row.get("include_in_cut", True) is False:
                        continue
                    if "goal_action" not in str(row.get("role") or ""):
                        continue
                    oi, oo = _num(row.get("media_in")), _num(row.get("media_out"))
                    if oi is None or oo is None:
                        continue
                    iou = _media_iou(new_in, new_out, oi, oo)
                    same = canonical_story_role(row.get("role")) == canonical_story_role(seg.get("role"))
                    if iou >= ROLE_WINDOW_OVERLAP_IOU or (same and iou >= 0.2):
                        rejected.append({
                            "intent": it.get("intent_id"),
                            "reason": "overlapping_existing_goal_window",
                            "iou": round(iou, 3),
                            "existing_segment_id": str(row.get("segment_id") or ""),
                        })
                        overlap_reject = True
                        break
            if overlap_reject:
                continue
            if action == "replace":
                target_row = edl[by_id[sid]] if sid and sid in by_id else None
                ti = to = None
                if target_row is not None:
                    ti, to = _num(target_row.get("media_in")), _num(target_row.get("media_out"))
                baseline_valid = (
                    ti is not None and to is not None and to > ti
                    and target_row.get("is_replay") is not True
                )
                expanding = (
                    new_in is not None and new_out is not None and ti is not None and to is not None
                    and (abs(ti - new_in) > 2.0 or abs(to - new_out) > 2.0)
                )
                if (
                    baseline_valid and expanding
                    and seg.get("first_live_status") == "NOT_VERIFIED"
                    and not seg.get("agent_auto_verified")
                ):
                    rejected.append({
                        "intent": it.get("intent_id"),
                        "reason": "unverified_replace_of_existing_goal_window",
                        "target_segment_id": sid,
                        "note": "NOT_VERIFIED bind cannot displace an existing timed goal cut",
                    })
                    continue
                retire_ids = set()
                if sid:
                    retire_ids.add(str(sid))
                for row in edl:
                    if (
                        "goal_action" in str(row.get("role") or "")
                        and canonical_story_role(row.get("role")) == canonical_story_role(seg.get("role"))
                    ):
                        retire_ids.add(str(row.get("segment_id") or ""))
                for rid in retire_ids:
                    if rid and rid in by_id and rid != new_sid:
                        edl[by_id[rid]]["include_in_cut"] = False
                        edl[by_id[rid]]["agent_replaced_by"] = new_sid
                        edl[by_id[rid]]["agent_drop_reason"] = (
                            edl[by_id[rid]].get("agent_drop_reason")
                            or f"replaced_by:{new_sid}"
                        )
            # Insert / upsert bound segment
            if new_sid in by_id:
                edl[by_id[new_sid]] = seg
            else:
                insert_at = 1 if edl else 0
                for i, row in enumerate(edl):
                    if "scoreboard" in str(row.get("role") or "") or "deficit" in str(row.get("role") or ""):
                        insert_at = i
                        break
                edl.insert(insert_at, seg)
                by_id = {str(r.get("segment_id")): i for i, r in enumerate(edl)}
            if action == "replace" and sid and sid in by_id and sid != new_sid:
                edl[by_id[sid]]["include_in_cut"] = False
            applied.append({
                "intent": it.get("intent_id"),
                "action": action,
                "status": "applied_evidence_bound",
                "segment_id": new_sid,
                "media_in": seg["media_in"],
                "media_out": seg["media_out"],
                "evidence_status": seg.get("evidence_status"),
                "first_live_status": "NOT_VERIFIED",
                "authorization": bound.get("authorization"),
                "observation_ref": bound.get("observation_ref"),
            })
            continue
        if action == "reorder":
            rejected.append({"intent": it.get("intent_id"), "reason": "reorder_requires_explicit_order_list"})
            continue
        rejected.append({"intent": it.get("intent_id"), "reason": f"unsupported_or_unsafe:{action}"})
    return edl, {
        "applied": applied,
        "rejected": rejected,
        "edl_row_count": len(edl),
        "evidence_bound_count": sum(1 for a in applied if a.get("status") == "applied_evidence_bound"),
        "pending_count": sum(1 for a in applied if a.get("status") == "pending_evidence_slot"),
    }


def hard_gate_blocks(audit: Mapping[str, Any]) -> bool:
    """True only for confirmed severe fact/technical errors (not missing-element feedback)."""
    return bool(severe_hard_findings(audit))


def decide_accept(
    *,
    baseline_audit: Mapping[str, Any],
    candidate_audit: Mapping[str, Any],
    verifier: Mapping[str, Any],
    revision_meta: Mapping[str, Any],
    baseline_edl: Optional[Sequence[Dict[str, Any]]] = None,
    candidate_edl: Optional[Sequence[Dict[str, Any]]] = None,
    semantic_verification_status: Optional[str] = None,
    quality_threshold: float = DEFAULT_QUALITY_THRESHOLD,
    mode: str = "loop",
) -> Dict[str, Any]:
    """Loop retain vs release are separate.

    Loop (`mode=loop`): serve Agent self-revision — keep partial improvements even if
    feedback P0 (e.g. missing opening) remain; block only confirmed severe errors /
    important regressions. Unverified goal binds may be retained as pending proposals
    (`release_eligible=False`).

    Release (`mode=release`): final delivery gate — no pending unverified primary goals,
    no severe errors, composite threshold when scores exist. Prefer `decide_release()`.
    """
    if mode == "release":
        return decide_release(
            baseline_audit=baseline_audit,
            candidate_audit=candidate_audit,
            verifier=verifier,
            revision_meta=revision_meta,
            baseline_edl=baseline_edl,
            candidate_edl=candidate_edl,
            semantic_verification_status=semantic_verification_status,
            quality_threshold=quality_threshold,
        )

    base_p0 = sum(1 for f in (baseline_audit.get("hard_gate_findings") or []) if f.get("severity") == "P0")
    cand_p0 = sum(1 for f in (candidate_audit.get("hard_gate_findings") or []) if f.get("severity") == "P0")
    base_severe = severe_hard_findings(baseline_audit)
    cand_severe = severe_hard_findings(candidate_audit)
    applied = revision_meta.get("applied") or []
    evidence_bound = [a for a in applied if a.get("status") == "applied_evidence_bound"]
    soft_applied = [a for a in applied if a.get("status") == "applied" and a.get("action") in ("drop", "trim", "reorder")]
    pending_slots = [a for a in applied if a.get("status") == "pending_evidence_slot"]
    pending_only = bool(applied) and all(
        a.get("status") in ("pending_evidence_slot", "recorded") for a in applied
    ) and not evidence_bound and not soft_applied
    goal_binds = [
        a for a in evidence_bound
        if "goal" in str(a.get("action") or "")
        or "goal_action" in str(a.get("segment_id") or a.get("role") or "")
        or a.get("action") in ("search_add", "replace")
    ]
    sem = semantic_verification_status or (
        "PASSED" if verifier.get("ok") and verifier.get("ok_for_semantic_accept", verifier.get("ok"))
        else "NOT_EVALUATED"
    )
    api_ok = bool(verifier.get("ok"))
    validated = verifier.get("validated") or {}
    reasons: List[str] = []
    path: Optional[str] = None
    accept = False
    pending_verification = False
    release_eligible = False

    # Confirmed model hard vetoes always block
    if validated.get("hard_vetoes"):
        reasons.append("verifier_hard_veto")
        return {
            "accept": False,
            "loop_retain": False,
            "path": None,
            "reasons": reasons,
            "baseline_p0": base_p0,
            "candidate_p0": cand_p0,
            "pending_only": pending_only,
            "pending_verification": False,
            "release_eligible": False,
            "hard_vetoes": validated.get("hard_vetoes"),
            "semantic_verification_status": sem,
            "gate": "loop",
            "verifier_self_score_alone_insufficient": True,
        }

    # New confirmed severe findings vs baseline
    if len(cand_severe) > len(base_severe):
        reasons.append("new_confirmed_severe_error")
        return {
            "accept": False,
            "loop_retain": False,
            "path": None,
            "reasons": reasons + [f.get("kind") or "?" for f in cand_severe],
            "baseline_p0": base_p0,
            "candidate_p0": cand_p0,
            "pending_only": pending_only,
            "pending_verification": False,
            "release_eligible": False,
            "severe_findings": cand_severe,
            "semantic_verification_status": sem,
            "gate": "loop",
            "verifier_self_score_alone_insufficient": True,
        }

    if not api_ok:
        reasons.append("api_verifier_degraded_rule_track_active")
        # Do not fail the round solely because API Verifier 502'd.

    if pending_only or (not evidence_bound and not soft_applied and not pending_slots):
        if not evidence_bound and not soft_applied:
            reasons.append("no_evidence_bound_or_safe_edit")
            return {
                "accept": False,
                "loop_retain": False,
                "path": None,
                "reasons": reasons,
                "baseline_p0": base_p0,
                "candidate_p0": cand_p0,
                "pending_only": True,
                "pending_verification": False,
                "release_eligible": False,
                "semantic_verification_status": sem,
                "gate": "loop",
                "verifier_self_score_alone_insufficient": True,
            }

    regressions: List[str] = []
    if baseline_edl is not None and candidate_edl is not None:
        for reg in important_segments_regressed(baseline_edl, candidate_edl):
            reasons.append("important_goal_regressed:" + reg)
            regressions.append(reg)
        for dup in find_duplicate_goal_cuts(candidate_edl):
            tag = "duplicate_goal_cut:" + str(dup.get("kind"))
            reasons.append(tag)
            regressions.append(tag)
    # New SUSPECTED_REPLAY on in-cut goals vs baseline is not an automatic quality win
    live_assess = validated.get("live_segment_assessments") or []
    new_suspected = []
    for a in live_assess:
        if not isinstance(a, dict):
            continue
        if str(a.get("live_status") or "") != "SUSPECTED_REPLAY":
            continue
        new_suspected.append(str(a.get("segment_id") or "unknown"))
    if new_suspected and evidence_bound:
        reasons.append("new_or_present_suspected_replay:" + ",".join(new_suspected[:6]))

    if regressions:
        return {
            "accept": False,
            "loop_retain": False,
            "path": None,
            "reasons": reasons,
            "baseline_p0": base_p0,
            "candidate_p0": cand_p0,
            "pending_only": pending_only,
            "pending_verification": False,
            "release_eligible": False,
            "regressions": regressions,
            "semantic_verification_status": sem,
            "gate": "loop",
            "verifier_self_score_alone_insufficient": True,
        }

    # Worsened total P0 count with no compensating improvement is still rejected,
    # but missing-element P0 alone does not force reject when coverage rises.
    eoi = validated.get("evidence_of_improvement") or []
    dims = validated.get("dimensions") or {}
    has_structured_eoi = any(
        isinstance(x, dict) and (x.get("evidence_refs") or x.get("claim"))
        for x in eoi
    )
    dim_improved = any(
        isinstance(dims.get(k), dict) and dims[k].get("status") == "improved"
        and (dims[k].get("evidence_refs") or dims[k].get("summary"))
        for k in (
            "story_element_coverage", "narrative_coherence",
            "image_content_quality", "live_authenticity",
        )
    )
    dim_regressed = any(
        isinstance(dims.get(k), dict) and dims[k].get("status") == "regressed"
        for k in (
            "story_element_coverage", "narrative_coherence",
            "image_content_quality", "live_authenticity",
        )
    )
    cov_b, cov_c = coverage_score(baseline_audit), coverage_score(candidate_audit)
    coh_b, coh_c = coherence_score(baseline_audit), coherence_score(candidate_audit)
    structural_cov_up = cov_b is not None and cov_c is not None and cov_c > cov_b + 1e-6
    structural_coh_up = coh_b is not None and coh_c is not None and coh_c > coh_b + 1e-6
    structural_improve = structural_cov_up or structural_coh_up
    p0_reduced = cand_p0 < base_p0
    local_improve = structural_improve or dim_improved or p0_reduced or has_structured_eoi

    if dim_regressed and not structural_improve and not p0_reduced:
        reasons.append("dimension_regressed_without_compensating_gain")
        return {
            "accept": False,
            "loop_retain": False,
            "path": None,
            "reasons": reasons,
            "baseline_p0": base_p0,
            "candidate_p0": cand_p0,
            "coverage_baseline": cov_b,
            "coverage_candidate": cov_c,
            "coherence_baseline": coh_b,
            "coherence_candidate": coh_c,
            "pending_verification": False,
            "release_eligible": False,
            "semantic_verification_status": sem,
            "gate": "loop",
            "verifier_self_score_alone_insufficient": True,
        }

    # Unverified goal binds: keep as pending proposal for next rounds; not release-ready.
    if goal_binds and sem not in ("PASSED",):
        if structural_improve or p0_reduced or evidence_bound:
            accept = True
            pending_verification = True
            path = "loop_pending_verification"
            reasons.append("goal_bind_retained_as_pending_proposal")
            reasons.append("not_release_ready_until_semantic_verification")
        else:
            reasons.append("goal_bind_without_improvement_signal")
            accept = False

    elif cand_p0 < base_p0 and cand_p0 == 0 and evidence_bound:
        accept = True
        path = "p0_repair"
        reasons.append("p0_resolved_with_evidence_bound_edit")
        if not (has_structured_eoi or structural_improve or dim_improved):
            reasons.append("structural_hard_gate_clearance")
        if sem == "PASSED" and not cand_severe:
            release_eligible = False  # still needs decide_release / product auth
    elif p0_reduced and (evidence_bound or soft_applied or structural_improve):
        accept = True
        path = "partial_improvement"
        reasons.append("partial_p0_or_coverage_improve_loop_retain")
        if cand_p0 > 0:
            reasons.append("feedback_p0_still_open_continue_loop")
    elif (evidence_bound or soft_applied) and (structural_improve or dim_improved or has_structured_eoi):
        if has_structured_eoi or structural_improve or (soft_applied and dim_improved):
            accept = True
            path = "quality_improvement"
            reasons.append("quality_improved_with_verifiable_evidence")
        else:
            reasons.append("dimension_improved_without_evidence_refs")
            accept = False
    elif soft_applied and structural_improve:
        accept = True
        path = "quality_improvement"
        reasons.append("quality_improved_with_verifiable_evidence")
    else:
        if cand_p0 > 0:
            reasons.append("feedback_p0_still_open")
        if not local_improve:
            reasons.append("no_verifiable_quality_delta")
        if not evidence_bound and not soft_applied:
            reasons.append("no_evidence_bound_or_safe_edit")

    # Model self-rating alone never suffices
    if accept and not (
        structural_improve or evidence_bound or soft_applied or has_structured_eoi
        or path in ("p0_repair", "partial_improvement", "loop_pending_verification")
    ):
        accept = False
        pending_verification = False
        reasons.append("model_self_score_alone_insufficient")

    # Suspected replay on bound goals cannot be auto-accepted as quality improvement
    if accept and new_suspected and path in ("quality_improvement", "loop_pending_verification"):
        accept = False
        pending_verification = False
        path = None
        reasons.append("refuse_auto_accept_with_suspected_replay")

    # Unverified replacement / synonym add that only widens coverage proxy is not improvement
    if accept and candidate_edl is not None and baseline_edl is not None:
        if find_duplicate_goal_cuts(candidate_edl):
            accept = False
            path = None
            reasons.append("refuse_accept_duplicate_goal_cuts")

    scores = composite_quality_score(candidate_audit, verifier_validated=validated)
    meets_threshold = (
        scores.get("composite") is not None
        and float(scores["composite"]) >= float(quality_threshold)
        and not cand_severe
        and not pending_verification
    )

    return {
        "accept": bool(accept),
        "loop_retain": bool(accept),
        "path": path,
        "reasons": reasons or (["accepted"] if accept else ["rejected"]),
        "baseline_p0": base_p0,
        "candidate_p0": cand_p0,
        "coverage_baseline": cov_b,
        "coverage_candidate": cov_c,
        "coherence_baseline": coh_b,
        "coherence_candidate": coh_c,
        "model_quality_delta": str(validated.get("quality_delta_vs_baseline") or ""),
        "pending_only": pending_only,
        "pending_verification": bool(pending_verification),
        "release_eligible": bool(release_eligible),
        "meets_quality_threshold": bool(meets_threshold),
        "quality_threshold": float(quality_threshold),
        "composite_scores": scores,
        "feedback_findings": feedback_findings(candidate_audit),
        "severe_findings": cand_severe,
        "evidence_bound_edits": len(evidence_bound),
        "regressions": regressions,
        "semantic_verification_status": sem,
        "api_verifier_ok": api_ok,
        "gate": "loop",
        "verifier_self_score_alone_insufficient": True,
        "note": (
            "Loop retain != final release. Unverified goals stay pending. "
            f"Threshold {quality_threshold} is experimental, not calibrated."
        ),
    }


def decide_release(
    *,
    baseline_audit: Mapping[str, Any],
    candidate_audit: Mapping[str, Any],
    verifier: Mapping[str, Any],
    revision_meta: Mapping[str, Any],
    baseline_edl: Optional[Sequence[Dict[str, Any]]] = None,
    candidate_edl: Optional[Sequence[Dict[str, Any]]] = None,
    semantic_verification_status: Optional[str] = None,
    quality_threshold: float = DEFAULT_QUALITY_THRESHOLD,
) -> Dict[str, Any]:
    """Final delivery gate — stricter than loop retain. Never auto-authorizes product release."""
    del baseline_audit, baseline_edl  # release judges the candidate as delivered state
    reasons: List[str] = []
    cand_severe = severe_hard_findings(candidate_audit)
    validated = verifier.get("validated") or {}
    sem = semantic_verification_status or (
        "PASSED" if verifier.get("ok") else "NOT_EVALUATED"
    )
    applied = revision_meta.get("applied") or []
    evidence_bound = [a for a in applied if a.get("status") == "applied_evidence_bound"]
    goal_binds = [
        a for a in evidence_bound
        if "goal_action" in str(a.get("segment_id") or a.get("role") or "")
        or a.get("action") in ("search_add", "replace")
    ]
    unverified_goals: List[str] = []
    if candidate_edl is not None:
        for r in candidate_edl:
            if not isinstance(r, dict) or not r.get("include_in_cut", True):
                continue
            role = str(r.get("role") or "")
            if "goal_action" not in role:
                continue
            pending = (
                r.get("first_live_status") == "NOT_VERIFIED"
                or (r.get("agent_bound") and not r.get("agent_auto_verified"))
            )
            if pending:
                unverified_goals.append(str(r.get("segment_id") or role))

    scores = composite_quality_score(candidate_audit, verifier_validated=validated)
    release_ok = True
    if cand_severe or validated.get("hard_vetoes"):
        release_ok = False
        reasons.append("release_blocked_severe_or_veto")
    if goal_binds and sem != "PASSED":
        release_ok = False
        reasons.append("release_blocked_unverified_goal_bind")
    if unverified_goals:
        release_ok = False
        reasons.append("release_blocked_pending_goal_segments")
    if scores.get("composite") is None:
        release_ok = False
        reasons.append("release_blocked_scores_unknown")
    elif float(scores["composite"]) < float(quality_threshold):
        release_ok = False
        reasons.append("release_blocked_below_quality_threshold")
    if not verifier.get("ok") or sem in ("NOT_EVALUATED", "UNKNOWN", "DEGRADED"):
        release_ok = False
        reasons.append("release_blocked_semantic_not_evaluated")
    if not reasons and release_ok:
        reasons.append("structurally_eligible_but_product_auth_still_required")

    return {
        "accept": False,
        "loop_retain": False,
        "release_eligible": bool(release_ok),
        "path": "release_gate",
        "reasons": reasons,
        "pending_verification": bool(unverified_goals),
        "unverified_goal_segments": unverified_goals,
        "severe_findings": cand_severe,
        "composite_scores": scores,
        "quality_threshold": float(quality_threshold),
        "semantic_verification_status": sem,
        "release_decision": "NOT_AUTHORIZED",
        "render_ready": False,
        "gate": "release",
        "note": (
            "Final delivery gate is independent of loop retain. "
            "Unverified goals and API-degraded semantics cannot be formally released."
        ),
    }


def write_phase5_workdir(out_phase5: Path, *, story: Any, plan: Any, edl: Any, rendered: Optional[Path]) -> None:
    out_phase5.mkdir(parents=True, exist_ok=True)
    (out_phase5 / "t01_story.json").write_text(json.dumps(story, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_phase5 / "story_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_phase5 / "candidate_edl.json").write_text(json.dumps(edl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if rendered and rendered.is_file():
        # Do not re-render; optional copy reference for audit if present
        dest = out_phase5 / rendered.name
        if not dest.exists():
            try:
                os.symlink(rendered.resolve(), dest)
            except OSError:
                pass


def run_self_revise(
    *,
    phase5_dir: Path,
    out_dir: Path,
    video: Optional[Path] = None,
    predicted_causal: Optional[Path] = None,
    stage2_proposal: Optional[Path] = None,
    audit_path: Optional[Path] = None,
    prefer_p1_polish: bool = True,
    enable_real_api: bool = False,
    i_approve_budget: bool = False,
    max_rounds: int = 2,
    max_calls: int = 8,
    max_cost_usd: float = 1.0,
    max_completion_tokens: int = 2048,
    planner_fixture: Optional[Path] = None,
    verifier_fixture: Optional[Path] = None,
    skip_vlm: bool = False,
    allow_degraded_offline: bool = False,
    inject_planner_failure: bool = False,
    inject_vlm_failure: bool = False,
    inject_verifier_failure: bool = False,
    quality_threshold: float = DEFAULT_QUALITY_THRESHOLD,
    stop_on_quality_threshold: bool = True,
    seed_observations: Optional[Sequence[Mapping[str, Any]]] = None,
    focus_segment_ids: Optional[Sequence[str]] = None,
    max_retries: int = 2,
    max_vlm_tool_requests: Optional[int] = None,
    max_windows_per_request: Optional[int] = None,
    max_followups: Optional[int] = None,
    one_round_opening_goal: bool = False,
) -> Dict[str, Any]:
    if one_round_opening_goal:
        from .one_round_opening_budget import (
            ONE_ROUND_MAX_FOLLOWUPS,
            ONE_ROUND_MAX_HTTP,
            ONE_ROUND_MAX_RETRIES,
            ONE_ROUND_MAX_ROUNDS,
            ONE_ROUND_MAX_VLM_TOOLS,
            ONE_ROUND_MAX_WINDOWS,
            OPENING_SEGMENT_ID,
        )
        max_rounds = min(int(max_rounds), ONE_ROUND_MAX_ROUNDS)
        max_calls = min(int(max_calls), ONE_ROUND_MAX_HTTP)
        max_retries = ONE_ROUND_MAX_RETRIES
        max_vlm_tool_requests = ONE_ROUND_MAX_VLM_TOOLS
        max_windows_per_request = ONE_ROUND_MAX_WINDOWS
        max_followups = ONE_ROUND_MAX_FOLLOWUPS
        focus_segment_ids = list(focus_segment_ids or [OPENING_SEGMENT_ID])
        prefer_p1_polish = False
    baseline_resolve = resolve_phase5_baseline(phase5_dir, prefer_p1_polish=prefer_p1_polish)
    phase5_dir = Path(baseline_resolve["path"]).resolve()
    baseline_resolve_public = {
        k: (str(v) if isinstance(v, Path) else v)
        for k, v in baseline_resolve.items()
        if k != "path"
    }
    baseline_resolve_public["path"] = str(phase5_dir)
    out_dir = out_dir.resolve()
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError(f"out_dir must be empty/new: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "baseline_resolution.json").write_text(
        json.dumps(baseline_resolve_public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    baseline_resolve = baseline_resolve_public

    story = _load_json(phase5_dir / "t01_story.json")
    plan = _load_json(phase5_dir / "story_plan.json")
    edl_obj = _load_json(phase5_dir / "candidate_edl.json")
    baseline_edl = _edl_rows(edl_obj)
    audit_file = audit_path or (phase5_dir / "v3a_quality_audit.json")
    baseline_audit = _load_json(audit_file) if audit_file.is_file() else None
    if baseline_audit is None:
        # Read-only structural audit into out_dir; does not touch freeze dir
        tmp = out_dir / "_baseline_phase5"
        write_phase5_workdir(tmp, story=story, plan=plan, edl=edl_obj, rendered=phase5_dir / "story_qc.mp4")
        baseline_audit = audit_phase5_dir(
            tmp, rendered_video=None, baseline_edl=None,
        )
        (out_dir / "baseline_quality_audit.json").write_text(
            json.dumps(baseline_audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    pc = _load_json(predicted_causal) if predicted_causal and predicted_causal.is_file() else None
    s2 = _load_json(stage2_proposal) if stage2_proposal and stage2_proposal.is_file() else None

    enrich_video = None
    # Prefer explicit video; else enrich metadata path if present beside run
    if video and video.is_file():
        enrich_video = video
    video_duration = None
    if enrich_video:
        try:
            video_duration = float(probe_video(enrich_video).duration_sec)
        except Exception:
            video_duration = None

    source_sha = {
        "story": _sha(phase5_dir / "t01_story.json"),
        "plan": _sha(phase5_dir / "story_plan.json"),
        "edl": _sha(phase5_dir / "candidate_edl.json"),
        "audit": _sha(audit_file) if audit_file.is_file() else None,
    }

    real_mode = bool(enable_real_api and i_approve_budget)
    fixture_mode = planner_fixture is not None
    if real_mode and fixture_mode:
        raise ValueError("refuse mixing real API with planner fixture")
    if enable_real_api and not i_approve_budget:
        raise ValueError("Real API refused: pass i_approve_budget after budget approval")
    if real_mode and not api_enabled():
        os.environ["STORY_API_ENABLE"] = "1"
    if real_mode:
        apply_trial_env_overrides(
            max_calls=max_calls,
            max_cost_usd=max_cost_usd,
            max_completion_tokens=max_completion_tokens,
            disable_thinking=True,
        )

    api = None
    if real_mode:
        api = ApiProvider(
            require_real=True,
            force_mock=False,
            max_calls=max_calls,
            max_cost_usd=max_cost_usd,
            max_completion_tokens=max_completion_tokens,
            required_roles=["planner", "vision"],
        )
    elif fixture_mode:
        api = ApiProvider(force_mock=True, max_calls=0, max_cost_usd=0.0)
    else:
        # Config-audit / dry structure without claiming success
        api = ApiProvider(force_mock=True, max_calls=0, max_cost_usd=0.0)
    # Hard-disable provider retries for one-round / explicit zero-retry budgets.
    if api is not None and (one_round_opening_goal or int(max_retries) == 0):
        from .one_round_opening_budget import enforce_provider_one_round_budget
        enforce_provider_one_round_budget(api, max_calls=max_calls)

    p_fix = _load_json(planner_fixture) if planner_fixture else None
    v_fix = _load_json(verifier_fixture) if verifier_fixture else None

    rounds: List[Dict[str, Any]] = []
    current_edl = copy.deepcopy(baseline_edl)
    best = {
        "edl": copy.deepcopy(baseline_edl),
        "audit": baseline_audit,
        "round": 0,
        "accepted": False,
    }
    observations_acc: List[Dict[str, Any]] = []
    if seed_observations:
        for o in seed_observations:
            if isinstance(o, dict):
                seeded = dict(o)
                seeded.setdefault("historical_reuse", True)
                seeded.setdefault("counts_as_new_http", False)
                seeded.setdefault("observation_only", True)
                seeded["fact_verified"] = False
                observations_acc.append(seeded)
    prior_round_feedback: Optional[Dict[str, Any]] = None
    agent_success = False
    abort_reason = None
    fallback_reasons: List[str] = []
    last_rule_status = "NOT_RUN"
    last_semantic_status = "NOT_EVALUATED"
    degraded_mode = bool(allow_degraded_offline or real_mode or fixture_mode)
    vlm_windows = int(max_windows_per_request) if max_windows_per_request is not None else MAX_WINDOWS_OBSERVE
    vlm_followups = int(max_followups) if max_followups is not None else MAX_FOLLOWUP_WINDOWS
    vlm_tool_cap = int(max_vlm_tool_requests) if max_vlm_tool_requests is not None else MAX_TOOL_REQUESTS

    # Baseline rule report always available for degraded delivery
    baseline_rule = run_rule_verifier(story, plan, baseline_edl)
    last_rule_status = baseline_rule.get("rule_verification_status") or "RAN_WITH_FINDINGS"
    (out_dir / "baseline_rule_verifier.json").write_text(
        json.dumps(baseline_rule, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    n_rounds = max(1, min(int(max_rounds), MAX_ROUNDS))
    for r in range(1, n_rounds + 1):
        round_dir = out_dir / f"round_{r:02d}"
        round_dir.mkdir(parents=True, exist_ok=True)
        ctx = compact_context(
            story=story, plan=plan, edl=current_edl, audit=baseline_audit if r == 1 else best["audit"],
            predicted_causal=pc, stage2_proposal=s2,
            prior_observations=observations_acc,
            prior_round_feedback=prior_round_feedback,
            video_duration=video_duration,
        )
        if focus_segment_ids:
            ctx = dict(ctx)
            constraints = dict(ctx.get("constraints") or {})
            constraints["focus_segment_ids"] = list(focus_segment_ids)
            constraints["max_video_tool_requests"] = min(
                int(constraints.get("max_video_tool_requests") or vlm_tool_cap),
                vlm_tool_cap,
            )
            constraints["historical_seed_observations_present"] = bool(seed_observations)
            constraints["historical_seed_not_new_http"] = True
            ctx["constraints"] = constraints
        (round_dir / "planner_context.json").write_text(
            json.dumps(ctx, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        handoff_blob = ctx.get("composer_evidence_handoff")
        if isinstance(handoff_blob, dict):
            (round_dir / "composer_evidence_handoff.json").write_text(
                json.dumps(handoff_blob, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        if not degraded_mode:
            abort_reason = "real_api_not_enabled_or_not_approved"
            fallback_reasons.append(abort_reason)
            rounds.append({
                "round": r,
                "aborted": True,
                "reason": abort_reason,
                "note": "No mock/cache disguised as Agent success.",
            })
            break

        # --- Planner (API → rule fallback) ---
        planner: Dict[str, Any]
        if inject_planner_failure:
            planner = {"ok": False, "error": "injected:ApiCallError:502 Bad Gateway", "provider_mode": "degraded"}
        else:
            try:
                planner = call_llm_planner(
                    api, ctx, fixture=p_fix if (fixture_mode or r == 1 and p_fix) else None,
                )
            except (ApiConfigError, ApiCallError) as exc:
                planner = {"ok": False, "error": f"{type(exc).__name__}:{exc}", "provider_mode": "degraded"}
        if not planner.get("ok"):
            fallback_reasons.append(f"planner:{planner.get('error') or 'failed'}")
            planner = build_rule_planner_fallback(
                story, plan, current_edl, baseline_audit if r == 1 else best["audit"],
                video_duration=video_duration,
                fallback_reason=str(planner.get("error") or "planner_api_failed"),
            )
        (round_dir / "planner_result.json").write_text(
            json.dumps(planner, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        validated = planner["validated"]

        # --- VLM / ffmpeg observe ---
        obs_pack: Dict[str, Any] = {"observations": [], "any_real_ok": False}
        tools = list(validated.get("video_tool_requests") or [])
        tool_filter_meta: Optional[Dict[str, Any]] = None
        if focus_segment_ids:
            from .one_round_opening_budget import filter_tools_to_focus
            # Single focus id for Oman opening experiment; multi-id → first match any.
            focus_id = str(focus_segment_ids[0])
            tool_filter_meta = filter_tools_to_focus(
                tools, focus_segment_id=focus_id, max_tools=vlm_tool_cap,
            )
            tools = list(tool_filter_meta.get("tools") or [])
            (round_dir / "tool_focus_filter.json").write_text(
                json.dumps(tool_filter_meta, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        elif vlm_tool_cap < len(tools):
            tools = tools[:vlm_tool_cap]
        if not skip_vlm and tools:
            if inject_vlm_failure:
                if enrich_video:
                    try:
                        obs_pack = run_ffmpeg_observe_without_vlm(
                            video=enrich_video, work_dir=round_dir / "ffmpeg_fallback",
                            tool_requests=tools,
                        )
                    except (OSError, ValueError) as exc:
                        obs_pack = {
                            "observations": [], "any_real_ok": False,
                            "vlm_fallback": True, "semantic_status": "UNKNOWN",
                            "error": f"{type(exc).__name__}:{exc}",
                        }
                else:
                    obs_pack = {
                        "observations": [], "any_real_ok": False,
                        "vlm_fallback": True, "semantic_status": "UNKNOWN",
                        "error": "injected_vlm_failure_no_video",
                    }
                fallback_reasons.append("vlm:injected_or_api_failed_ffmpeg_fallback")
            elif real_mode and enrich_video:
                try:
                    obs_pack = run_vlm_observations(
                        api, video=enrich_video, work_dir=round_dir / "vlm", tool_requests=tools,
                        max_windows_per_request=vlm_windows,
                        max_followups=vlm_followups,
                    )
                    if not obs_pack.get("any_real_ok") and obs_pack.get("observations"):
                        # Partial failure: keep technical frames if any; else ffmpeg fallback
                        if all(not o.get("ok") or o.get("provider_mode") == "degraded" for o in obs_pack["observations"]):
                            fallback_reasons.append("vlm:all_rounds_failed")
                            obs_pack = run_ffmpeg_observe_without_vlm(
                                video=enrich_video, work_dir=round_dir / "ffmpeg_fallback",
                                tool_requests=tools,
                            )
                except (ApiConfigError, ApiCallError, OSError, ValueError) as exc:
                    fallback_reasons.append(f"vlm:{type(exc).__name__}")
                    try:
                        obs_pack = run_ffmpeg_observe_without_vlm(
                            video=enrich_video, work_dir=round_dir / "ffmpeg_fallback",
                            tool_requests=tools,
                        )
                    except (OSError, ValueError) as exc2:
                        obs_pack = {
                            "observations": [], "any_real_ok": False,
                            "semantic_status": "UNKNOWN",
                            "error": f"{type(exc2).__name__}:{exc2}",
                        }
            elif fixture_mode and not inject_vlm_failure:
                obs_pack = {
                    "observations": [{
                        "request_id": "fixture_obs", "ok": True,
                        "provider_mode": "offline_fixture",
                        "fact_verified": False, "observation_only": True,
                        "vlm": {"visible_content": "fixture", "observation_only": True,
                                "fact_verified": False},
                    }],
                    "any_real_ok": False, "note": "fixture_skip_real_vlm",
                }
            elif allow_degraded_offline and enrich_video:
                obs_pack = run_ffmpeg_observe_without_vlm(
                    video=enrich_video, work_dir=round_dir / "ffmpeg_fallback", tool_requests=tools,
                )
                fallback_reasons.append("vlm:offline_degraded_ffmpeg_only")
        (round_dir / "vlm_observations.json").write_text(
            json.dumps(obs_pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        observations_acc.extend(obs_pack.get("observations") or [])
        if obs_pack.get("window_schedule_log"):
            (round_dir / "window_schedule_log.json").write_text(
                json.dumps(obs_pack.get("window_schedule_log"), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        tw_by_anchor: Dict[str, List[Dict[str, Any]]] = {}
        sa_by_anchor: Dict[str, float] = {}
        for tr in tools:
            aid = str(tr.get("anchor_id") or "")
            if aid:
                tw_by_anchor[aid] = list(tr.get("search_windows") or [])
        for a in ctx.get("trusted_anchors") or []:
            if a.get("kind") == "T01_selected_arc_score_node" and _num(a.get("t_sec")) is not None:
                sa_by_anchor[str(a["anchor_id"])] = float(a["t_sec"])

        # Rule-fallback planner must not invent semantic EDL binds without VLM support
        intents = list(validated.get("revision_intents") or [])
        if planner.get("fallback"):
            intents = [
                it for it in intents
                if it.get("action") in ("search_add", "mark_unresolved", "keep")
            ]

        cand_edl, rev_meta = apply_candidate_revision(
            current_edl, intents, obs_pack.get("observations") or [],
            trusted_windows_by_anchor=tw_by_anchor,
            score_anchor_by_anchor_id=sa_by_anchor,
        )
        cand_phase = round_dir / "candidate_phase5"
        write_phase5_workdir(cand_phase, story=story, plan=plan, edl=cand_edl, rendered=None)
        cand_audit = audit_phase5_dir(
            cand_phase, rendered_video=None, baseline_edl=baseline_edl,
        )
        (round_dir / "candidate_quality_audit.json").write_text(
            json.dumps(cand_audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (round_dir / "revision_meta.json").write_text(
            json.dumps(rev_meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        # Critical goal/score segments for live_authenticity (match-agnostic)
        critical_rows = []
        for row in cand_edl:
            if not isinstance(row, dict) or not row.get("include_in_cut", True):
                continue
            role = str(row.get("role") or "")
            if "goal_action" in role or "scoreboard" in role or row.get("is_replay") is not None:
                critical_rows.append({
                    "segment_id": row.get("segment_id"),
                    "role": role,
                    "media_in": row.get("media_in"),
                    "media_out": row.get("media_out"),
                    "is_replay": row.get("is_replay"),
                    "first_live_status": row.get("first_live_status"),
                    "agent_bound": row.get("agent_bound"),
                    "evidence_status": row.get("evidence_status"),
                })
        ver_payload = {
            "baseline_hard_gates": baseline_audit.get("hard_gate_findings"),
            "candidate_hard_gates": cand_audit.get("hard_gate_findings"),
            "baseline_dimensions": baseline_audit.get("dimensions"),
            "candidate_dimensions": cand_audit.get("dimensions"),
            "planner_diagnoses": validated.get("diagnoses"),
            "revision_meta": rev_meta,
            "critical_segments_for_live_authenticity": critical_rows[:20],
            "prior_round_feedback": prior_round_feedback,
            "observations": [{
                "request_id": o.get("request_id"), "ok": o.get("ok"),
                "provider_mode": o.get("provider_mode"), "window": o.get("window"),
                "vlm": o.get("vlm"), "fact_verified": False,
                "semantic_status": o.get("semantic_status"),
            } for o in (obs_pack.get("observations") or [])],
            "window_schedule_log": obs_pack.get("window_schedule_log") or [],
            "constraints": ctx["constraints"],
        }

        def _api_ver_fn(payload, fixture=None):
            if inject_verifier_failure:
                return {
                    "ok": False, "provider_mode": "degraded",
                    "error": "injected:ApiCallError:502 Bad Gateway",
                    "attempts": [{"ok": False, "error": "injected_502"}],
                    "rule_fallback_success": False,
                }
            try:
                return call_llm_verifier(api, payload, fixture=fixture if fixture_mode else fixture)
            except (ApiConfigError, ApiCallError) as exc:
                return {
                    "ok": False, "provider_mode": "degraded",
                    "error": f"{type(exc).__name__}:{exc}",
                    "rule_fallback_success": False,
                }

        dual = run_dual_verifier(
            story=story, plan=plan,
            baseline_edl=baseline_edl, candidate_edl=cand_edl,
            api_verifier_fn=_api_ver_fn,
            api_payload=ver_payload,
            fixture=v_fix if fixture_mode and not inject_verifier_failure else None,
        )
        if not dual.get("ok_for_semantic_accept"):
            fallback_reasons.append(f"verifier:{dual.get('fallback_reason') or dual.get('error') or 'degraded'}")
        last_rule_status = dual.get("rule_verification_status") or last_rule_status
        last_semantic_status = dual.get("semantic_verification_status") or "NOT_EVALUATED"
        (round_dir / "dual_verifier.json").write_text(
            json.dumps(dual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        decision = decide_accept(
            baseline_audit=baseline_audit if r == 1 else best["audit"],
            candidate_audit=cand_audit,
            verifier=dual,
            revision_meta=rev_meta,
            baseline_edl=best["edl"] if best.get("accepted") else baseline_edl,
            candidate_edl=cand_edl,
            semantic_verification_status=last_semantic_status,
            quality_threshold=quality_threshold,
            mode="loop",
        )
        (round_dir / "accept_decision.json").write_text(
            json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        validated_ver = dual.get("validated") or {}
        four_dim_scores = composite_quality_score(
            cand_audit, verifier_validated=validated_ver,
        )
        round_rec = {
            "round": r,
            "planner_ok": True,
            "planner_provider_mode": planner.get("provider_mode"),
            "planner_fallback": bool(planner.get("fallback")),
            "planner_model": planner.get("model"),
            "diagnoses": validated.get("diagnoses"),
            "revision_intents": intents,
            "video_tool_requests": tools,
            "vlm_any_real_ok": obs_pack.get("any_real_ok"),
            "vlm_fallback": bool(obs_pack.get("vlm_fallback")),
            "verifier_ok": dual.get("ok"),
            "verifier_provider_mode": dual.get("provider_mode"),
            "rule_verification_status": last_rule_status,
            "semantic_verification_status": last_semantic_status,
            "revision_meta": rev_meta,
            "accept_decision": decision,
            "four_dimension_scores": four_dim_scores,
            "live_segment_assessments": validated_ver.get("live_segment_assessments") or [],
            "prior_feedback_consumed": bool(prior_round_feedback),
            "est_cost_usd_planner": planner.get("est_cost_usd"),
            "est_cost_usd_verifier": (dual.get("api") or {}).get("est_cost_usd"),
        }
        rounds.append(round_rec)

        if decision.get("accept") or decision.get("loop_retain"):
            current_edl = cand_edl
            best = {
                "edl": cand_edl,
                "audit": cand_audit,
                "round": r,
                "accepted": True,
                "pending_verification": bool(decision.get("pending_verification")),
                "path": decision.get("path"),
                "four_dimension_scores": four_dim_scores,
            }
            agent_success = True
        else:
            current_edl = copy.deepcopy(best["edl"])

        # Feed next round: diagnoses, verifier issues, unresolved, accept reasons
        prior_round_feedback = {
            "from_round": r,
            "accepted": bool(decision.get("accept") or decision.get("loop_retain")),
            "accept_path": decision.get("path"),
            "accept_reasons": decision.get("reasons"),
            "diagnoses": validated.get("diagnoses") or [],
            "verifier_issues": validated_ver.get("issues") or [],
            "hard_vetoes": validated_ver.get("hard_vetoes") or [],
            "live_segment_assessments": validated_ver.get("live_segment_assessments") or [],
            "dimension_scores": four_dim_scores,
            "revision_meta_summary": {
                "evidence_bound_count": rev_meta.get("evidence_bound_count"),
                "pending_count": rev_meta.get("pending_count"),
                "applied": [
                    {k: a.get(k) for k in ("action", "status", "segment_id", "role")}
                    for a in (rev_meta.get("applied") or [])
                ],
            },
            "unresolved_guidance": (
                "Continue improving other story aspects even if some P0 remain; "
                "prefer evidence-backed local edits; treat SUSPECTED_REPLAY as repair signal."
            ),
        }

        # Optional early stop (experiment may disable to force full N rounds).
        if (
            stop_on_quality_threshold
            and decision.get("accept")
            and decision.get("meets_quality_threshold")
            and not decision.get("pending_verification")
            and not severe_hard_findings(cand_audit)
        ):
            abort_reason = "quality_threshold_met"
            break

        if real_mode and api is not None:
            usage = api.stats.summary()
            if api.max_calls is not None and usage.get("http_attempts", 0) >= api.max_calls:
                abort_reason = "max_calls_reached"
                fallback_reasons.append(abort_reason)
                break
            if api.max_cost_usd is not None and usage.get("est_cost_usd_real", 0) >= api.max_cost_usd:
                abort_reason = "max_cost_reached"
                fallback_reasons.append(abort_reason)
                break

    usage = api.stats.summary() if api is not None else {}
    real_participation = False
    if real_mode:
        real_participation = any(
            (rr.get("planner_provider_mode") == "real")
            or (rr.get("verifier_provider_mode") == "real")
            or rr.get("vlm_any_real_ok")
            for rr in rounds if not rr.get("aborted")
        )
        if not real_participation and agent_success:
            # Do not claim multimodal success without real providers
            agent_success = False
            fallback_reasons.append("no_real_provider_participation")

    agent_contributed = bool(
        best.get("accepted") and agent_success and (
            (real_mode and real_participation) or (fixture_mode and not any(
                x.startswith("planner:") or x.startswith("vlm:") or x.startswith("verifier:")
                for x in fallback_reasons
            ))
        )
    )
    workflow_completed = True  # degraded path still completes unless hard crash
    orch = build_orchestration_status(
        workflow_completed=workflow_completed,
        rule_verification_status=str(last_rule_status),
        semantic_verification_status=str(last_semantic_status),
        fallback_reasons=fallback_reasons,
        accepted_revision=bool(best.get("accepted")),
        agent_contributed_improvement=agent_contributed,
        best_preserved=True,
    )

    # Final rule report on best EDL (baseline if nothing accepted)
    final_rule = run_rule_verifier(story, plan, best["edl"])
    (out_dir / "final_rule_verifier.json").write_text(
        json.dumps(final_rule, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    orch["rule_verification_status"] = final_rule.get("rule_verification_status") or orch["rule_verification_status"]

    # Separate final delivery gate (never confused with loop retain).
    last_rev_meta = {}
    last_dual: Dict[str, Any] = {"ok": False, "validated": {}}
    for rr in reversed(rounds):
        if rr.get("accept_decision"):
            last_rev_meta = rr.get("revision_meta") or {}
            break
    dual_path = out_dir / f"round_{best.get('round') or 1:02d}" / "dual_verifier.json"
    if dual_path.is_file():
        try:
            last_dual = json.loads(dual_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            last_dual = {"ok": False, "validated": {}}
    release = decide_release(
        baseline_audit=baseline_audit,
        candidate_audit=best.get("audit") or baseline_audit,
        verifier=last_dual if isinstance(last_dual, dict) else {"ok": False},
        revision_meta=last_rev_meta,
        candidate_edl=best["edl"],
        semantic_verification_status=last_semantic_status,
        quality_threshold=quality_threshold,
    )
    (out_dir / "release_gate.json").write_text(
        json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    orch["release_decision"] = "NOT_AUTHORIZED"
    orch["render_ready"] = False

    summary = {
        "schema": SCHEMA,
        "match_id": plan.get("match_id") or story.get("match_id"),
        "phase5_dir": str(phase5_dir),
        "baseline_resolution": baseline_resolve,
        "out_dir": str(out_dir),
        "frozen_inputs_untouched": True,
        "source_sha256": source_sha,
        "enable_real_api": enable_real_api,
        "i_approve_budget": i_approve_budget,
        "fixture_mode": fixture_mode,
        "video": str(enrich_video) if enrich_video else None,
        "video_duration_sec": video_duration,
        "max_rounds": n_rounds,
        "rounds_executed": len(rounds),
        "rounds": rounds,
        "best_round": best.get("round"),
        "accepted_any_revision": bool(best.get("accepted")),
        "pending_verification": bool(best.get("pending_verification")),
        "agent_claimed_success": bool(agent_contributed),
        "abort_reason": abort_reason,
        "quality_threshold": float(quality_threshold),
        "release_gate": release,
        "api_usage": usage,
        "cost_disclaimer": COST_DISCLAIMER,
        "edl_modified_frozen_phase5": False,
        "unresolved_risks": (
            list(feedback_findings(best.get("audit") or baseline_audit))
            + list(severe_hard_findings(best.get("audit") or baseline_audit))
        ),
        "note": (
            "Loop retain != release eligibility. "
            "Degraded execution success != multimodal self-revision success. "
            "VLM observations never certify first LIVE. "
            "UNKNOWN/NOT_EVALUATED semantic scores are not coerced to 0/100. "
            f"Quality threshold {quality_threshold} is experimental."
        ),
        **orch,
    }
    (out_dir / "self_revise_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "best_candidate_edl.json").write_text(
        json.dumps(best["edl"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def audit_phase5_dir(
    phase5: Path,
    rendered_video: Optional[Path] = None,
    baseline_edl: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    story = _load_json(phase5 / "t01_story.json")
    plan = _load_json(phase5 / "story_plan.json")
    edl = _load_json(phase5 / "candidate_edl.json")
    return quality_evaluate(
        story, plan, edl,
        rendered_video=rendered_video,
        baseline_edl=baseline_edl,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="V3-A LLM+VLM self-revision Agent (max 3 rounds)")
    p.add_argument("--phase5-dir", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--video", type=Path, default=None)
    p.add_argument("--predicted-causal", type=Path, default=None)
    p.add_argument("--stage2-proposal", type=Path, default=None)
    p.add_argument("--audit", type=Path, default=None)
    p.add_argument("--max-rounds", type=int, default=2)
    p.add_argument("--max-calls", type=int, default=8)
    p.add_argument("--max-cost-usd", type=float, default=1.0)
    p.add_argument("--max-completion-tokens", type=int, default=2048)
    p.add_argument("--enable-real-api", action="store_true")
    p.add_argument("--i-approve-budget", action="store_true")
    p.add_argument("--planner-fixture", type=Path, default=None)
    p.add_argument("--verifier-fixture", type=Path, default=None)
    p.add_argument("--skip-vlm", action="store_true")
    p.add_argument("--allow-degraded-offline", action="store_true",
                   help="Allow rule/ffmpeg degraded completion without real API")
    p.add_argument(
        "--quality-threshold", type=float, default=DEFAULT_QUALITY_THRESHOLD,
        help="Experimental composite reference (default 75; not calibrated)",
    )
    p.add_argument(
        "--no-stop-on-quality-threshold", action="store_true",
        help="Run all max_rounds even if composite meets quality_threshold",
    )
    p.add_argument("--config-audit-only", action="store_true")
    p.add_argument(
        "--no-prefer-p1-polish", action="store_true",
        help="Do not auto-switch 04_phase5 → sibling 04_phase5_p1_polish when present",
    )
    p.add_argument(
        "--one-round-opening-goal", action="store_true",
        help="Oman opening-goal isolated mode: max_rounds=1, max_calls≤3, retries=0, "
             "focus seg_opponent_opening_goal_action, no p1 polish",
    )
    p.add_argument(
        "--seed-observations", type=Path, default=None,
        help="JSON file with one observation object or {observation: ...}; historical reuse only",
    )
    p.add_argument("--max-retries", type=int, default=2,
                   help="Provider HTTP retries per call (0 for one-round hard stop)")
    args = p.parse_args(argv)

    if args.config_audit_only:
        apply_trial_env_overrides(
            max_calls=args.max_calls,
            max_cost_usd=args.max_cost_usd,
            max_completion_tokens=args.max_completion_tokens,
        )
        # force enable check without HTTP
        status = {
            "api_enabled_env": api_enabled(),
            "STORY_API_ENABLE": os.environ.get("STORY_API_ENABLE"),
            "planner_model": os.environ.get("STORY_LLM_MODEL"),
            "vision_model": os.environ.get("STORY_VLM_MODEL"),
            "base_url_set": bool(os.environ.get("STORY_LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL")),
            "max_calls": args.max_calls,
            "max_cost_usd": args.max_cost_usd,
            "http_requests_sent": 0,
            "render_ready": False,
        }
        args.out_dir.mkdir(parents=True, exist_ok=True)
        path = args.out_dir / "config_audit_only.json"
        path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "ok_config_audit_only", "path": str(path), **status}, ensure_ascii=False))
        return 0

    if args.out_dir.resolve().is_relative_to(args.phase5_dir.resolve()):
        p.error("out-dir must be outside frozen phase5 directory")

    seed_obs = None
    if args.seed_observations is not None:
        raw_seed = _load_json(args.seed_observations)
        if isinstance(raw_seed, dict) and isinstance(raw_seed.get("observation"), dict):
            seed_obs = [raw_seed["observation"]]
        elif isinstance(raw_seed, dict):
            seed_obs = [raw_seed]
        elif isinstance(raw_seed, list):
            seed_obs = [x for x in raw_seed if isinstance(x, dict)]
        else:
            p.error("--seed-observations must be a JSON object or list")

    try:
        summary = run_self_revise(
            phase5_dir=args.phase5_dir,
            out_dir=args.out_dir,
            video=args.video,
            predicted_causal=args.predicted_causal,
            stage2_proposal=args.stage2_proposal,
            audit_path=args.audit,
            prefer_p1_polish=not args.no_prefer_p1_polish,
            enable_real_api=args.enable_real_api,
            i_approve_budget=args.i_approve_budget,
            max_rounds=args.max_rounds,
            max_calls=args.max_calls,
            max_cost_usd=args.max_cost_usd,
            max_completion_tokens=args.max_completion_tokens,
            planner_fixture=args.planner_fixture,
            verifier_fixture=args.verifier_fixture,
            skip_vlm=args.skip_vlm,
            allow_degraded_offline=args.allow_degraded_offline,
            quality_threshold=args.quality_threshold,
            stop_on_quality_threshold=not args.no_stop_on_quality_threshold,
            seed_observations=seed_obs,
            max_retries=args.max_retries,
            one_round_opening_goal=args.one_round_opening_goal,
        )
    except Exception as exc:
        print(json.dumps({
            "status": "failed",
            "error": f"{type(exc).__name__}:{exc}",
            "agent_claimed_success": False,
            "render_ready": False,
        }, ensure_ascii=False))
        return 2

    print(json.dumps({
        "status": "ok" if summary.get("agent_claimed_success") else "completed_without_agent_success",
        "out_dir": summary.get("out_dir"),
        "rounds": summary.get("rounds_executed"),
        "accepted_any_revision": summary.get("accepted_any_revision"),
        "agent_claimed_success": summary.get("agent_claimed_success"),
        "abort_reason": summary.get("abort_reason"),
        "api_usage": {
            "http_attempts": (summary.get("api_usage") or {}).get("http_attempts"),
            "est_cost_usd_real": (summary.get("api_usage") or {}).get("est_cost_usd_real"),
            "real_ok": (summary.get("api_usage") or {}).get("real_ok"),
            "real_failures": (summary.get("api_usage") or {}).get("real_failures"),
        },
        "edl_modified_frozen_phase5": False,
        "render_ready": False,
    }, ensure_ascii=False))
    return 0 if summary.get("rounds_executed", 0) > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
