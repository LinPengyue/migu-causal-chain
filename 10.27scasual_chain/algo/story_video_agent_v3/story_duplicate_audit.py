"""Cross-role source-footage duplicate audit for story EDLs (match-agnostic).

Detects:
  - identical media windows
  - high IoU overlap across any roles
  - containment (one cut fully inside another)
  - optional continuous visual sequence match (time-series), not single-frame similarity

Prefer keeping verified / first-LIVE / complete goal_action cuts; drop redundant
non-goal material when preference is clear. If both sides are ambiguous, require
human review — never auto-delete.
"""
from __future__ import annotations

import json
import math
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .story_timeline import _num, active_cut_rows, build_story_timeline

SCHEMA = "v3a_story_duplicate_audit_v1"

# Media-window structural thresholds (source PTS).
CONTAIN_EPS_SEC = 0.25
HIGH_IOU = 0.55
PARTIAL_IOU = 0.35
MIN_OVERLAP_SEC = 3.0  # absolute overlap also triggers even when IoU is modest
# Visual sequence match (optional; requires ffmpeg).
VIS_SAMPLE_FPS = 2.0
VIS_MIN_PAIR_SEC = 4.0
VIS_CORR_THRESH = 0.92
VIS_MIN_LAG_SUPPORT = 6  # frames


def _media_iou(a_in: float, a_out: float, b_in: float, b_out: float) -> float:
    inter = max(0.0, min(a_out, b_out) - max(a_in, b_in))
    union = max(a_out, b_out) - min(a_in, b_in)
    if union <= 1e-9:
        return 0.0
    return inter / union


def _containment(a_in: float, a_out: float, b_in: float, b_out: float) -> Optional[str]:
    """Return 'a_in_b' / 'b_in_a' when one window is (near-)contained in the other."""
    if a_in >= b_in - CONTAIN_EPS_SEC and a_out <= b_out + CONTAIN_EPS_SEC:
        if (a_out - a_in) <= (b_out - b_in) + 1e-6:
            return "a_in_b"
    if b_in >= a_in - CONTAIN_EPS_SEC and b_out <= a_out + CONTAIN_EPS_SEC:
        if (b_out - b_in) <= (a_out - a_in) + 1e-6:
            return "b_in_a"
    return None


def _is_goal(role: str) -> bool:
    return "goal_action" in str(role or "")


def _preference_score(row: Mapping[str, Any]) -> Tuple[int, int, float, int]:
    """Higher is better to KEEP.

    Prefer: goal_action > first-live verified > longer span > earlier story index.
    """
    role = str(row.get("role") or "")
    goal = 3 if _is_goal(role) else 0
    fl = str(row.get("first_live_status") or "").upper()
    verified = 2 if fl in ("FIRST_LIVE_VERIFIED", "VERIFIED") or row.get("agent_auto_verified") is True else 0
    if row.get("is_replay") in (True, "true", "True", 1):
        verified -= 5
    mi, mo = _num(row.get("media_in")), _num(row.get("media_out"))
    span = float(mo - mi) if mi is not None and mo is not None else 0.0
    # Non-goal "fill" / bridge roles are weaker than primary goal anchors.
    weak = -1 if any(k in role for k in ("fill", "bridge", "atom")) else 0
    return (goal + verified + weak, 1 if _is_goal(role) else 0, span, 0)


def choose_keep_drop(
    a: Mapping[str, Any],
    b: Mapping[str, Any],
    *,
    contain: Optional[str] = None,
) -> Dict[str, Any]:
    """Decide keep/drop or human_review for a duplicate pair."""
    sa, sb = _preference_score(a), _preference_score(b)
    aid = str(a.get("segment_id") or "")
    bid = str(b.get("segment_id") or "")
    a_goal, b_goal = _is_goal(str(a.get("role"))), _is_goal(str(b.get("role")))

    # Containment: always drop the inner non-goal when outer is goal.
    if contain == "a_in_b" and b_goal and not a_goal:
        return {
            "decision": "auto_drop",
            "keep_segment_id": bid,
            "drop_segment_id": aid,
            "reason": "non_goal_contained_in_goal_action",
        }
    if contain == "b_in_a" and a_goal and not b_goal:
        return {
            "decision": "auto_drop",
            "keep_segment_id": aid,
            "drop_segment_id": bid,
            "reason": "non_goal_contained_in_goal_action",
        }

    # Both goals overlapping → human review (do not auto-delete either).
    if a_goal and b_goal:
        return {
            "decision": "human_review",
            "keep_segment_id": None,
            "drop_segment_id": None,
            "reason": "overlapping_goal_actions_require_human_review",
        }

    # Clear preference gap.
    if sa > sb and (a_goal or sa[0] - sb[0] >= 2 or sa[2] >= sb[2] + 4.0):
        return {
            "decision": "auto_drop",
            "keep_segment_id": aid,
            "drop_segment_id": bid,
            "reason": "prefer_higher_priority_or_longer_cut",
        }
    if sb > sa and (b_goal or sb[0] - sa[0] >= 2 or sb[2] >= sa[2] + 4.0):
        return {
            "decision": "auto_drop",
            "keep_segment_id": bid,
            "drop_segment_id": aid,
            "reason": "prefer_higher_priority_or_longer_cut",
        }

    return {
        "decision": "human_review",
        "keep_segment_id": None,
        "drop_segment_id": None,
        "reason": "ambiguous_duplicate_pair",
    }


def find_media_window_duplicates(
    edl: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Cross-role media overlap / containment / identical windows."""
    rows = []
    for r in active_cut_rows(edl):
        mi, mo = _num(r.get("media_in")), _num(r.get("media_out"))
        if mi is None or mo is None or mo <= mi:
            continue
        rows.append(dict(r))

    findings: List[Dict[str, Any]] = []
    seen_identical: Dict[Tuple[float, float], str] = {}
    for r in rows:
        mi, mo = float(r["media_in"]), float(r["media_out"])
        key = (round(mi, 2), round(mo, 2))
        sid = str(r.get("segment_id") or "")
        if key in seen_identical:
            other = next(x for x in rows if str(x.get("segment_id")) == seen_identical[key])
            pref = choose_keep_drop(other, r, contain=None)
            findings.append(
                {
                    "kind": "identical_media_window",
                    "segment_ids": [seen_identical[key], sid],
                    "roles": [str(other.get("role") or ""), str(r.get("role") or "")],
                    "media_windows": [
                        {"segment_id": seen_identical[key], "media_in": other.get("media_in"), "media_out": other.get("media_out")},
                        {"segment_id": sid, "media_in": mi, "media_out": mo},
                    ],
                    "iou": 1.0,
                    "containment": "identical",
                    **pref,
                }
            )
        else:
            seen_identical[key] = sid

    for i in range(len(rows)):
        ai, ao = float(rows[i]["media_in"]), float(rows[i]["media_out"])
        for j in range(i + 1, len(rows)):
            bi, bo = float(rows[j]["media_in"]), float(rows[j]["media_out"])
            # Skip already-reported identical keys
            if round(ai, 2) == round(bi, 2) and round(ao, 2) == round(bo, 2):
                continue
            iou = _media_iou(ai, ao, bi, bo)
            contain = _containment(ai, ao, bi, bo)
            overlap_sec = max(0.0, min(ao, bo) - max(ai, bi))
            if contain is None and iou < PARTIAL_IOU and overlap_sec < MIN_OVERLAP_SEC:
                continue
            kind = "media_containment" if contain else "media_overlap"
            if contain is None and iou < HIGH_IOU:
                kind = "media_partial_overlap"
            pref = choose_keep_drop(rows[i], rows[j], contain=contain)
            findings.append(
                {
                    "kind": kind,
                    "segment_ids": [
                        str(rows[i].get("segment_id") or ""),
                        str(rows[j].get("segment_id") or ""),
                    ],
                    "roles": [str(rows[i].get("role") or ""), str(rows[j].get("role") or "")],
                    "media_windows": [
                        {
                            "segment_id": str(rows[i].get("segment_id") or ""),
                            "media_in": ai,
                            "media_out": ao,
                        },
                        {
                            "segment_id": str(rows[j].get("segment_id") or ""),
                            "media_in": bi,
                            "media_out": bo,
                        },
                    ],
                    "iou": round(iou, 4),
                    "containment": contain,
                    "overlap_sec": round(max(0.0, min(ao, bo) - max(ai, bi)), 3),
                    **pref,
                }
            )
    return findings


def _extract_gray_sequence(
    video: Path,
    media_in: float,
    media_out: float,
    *,
    work: Path,
    fps: float = VIS_SAMPLE_FPS,
    width: int = 160,
) -> Optional[List[Any]]:
    """Extract a low-res grayscale frame sequence for time-series matching."""
    dur = media_out - media_in
    if dur < VIS_MIN_PAIR_SEC:
        return None
    out_pat = work / "f_%04d.png"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-ss", f"{media_in:.3f}", "-t", f"{dur:.3f}",
        "-i", str(video),
        "-vf", f"fps={fps},scale={width}:-1,format=gray",
        "-y", str(out_pat),
    ]
    try:
        subprocess.run(cmd, check=True, timeout=120)
    except (subprocess.SubprocessError, OSError):
        return None
    frames = sorted(work.glob("f_*.png"))
    if len(frames) < VIS_MIN_LAG_SUPPORT:
        return None
    try:
        from PIL import Image  # type: ignore
        import array
        seq = []
        for fp in frames:
            im = Image.open(fp)
            seq.append(array.array("B", im.tobytes()))
        return seq
    except Exception:
        return None


def _seq_corr(a: Sequence[Any], b: Sequence[Any], lag: int) -> Optional[float]:
    """Mean per-frame normalized correlation at a fixed lag (b relative to a)."""
    n = min(len(a), len(b) - lag if lag >= 0 else len(b))
    if lag < 0:
        # shift a forward
        a_idx0, b_idx0 = -lag, 0
        n = min(len(a) - a_idx0, len(b))
    else:
        a_idx0, b_idx0 = 0, lag
        n = min(len(a), len(b) - b_idx0)
    if n < VIS_MIN_LAG_SUPPORT:
        return None
    corrs = []
    for i in range(n):
        fa = a[a_idx0 + i]
        fb = b[b_idx0 + i]
        if len(fa) != len(fb) or not fa:
            continue
        # Pearson-ish via mean/std
        ma = sum(fa) / len(fa)
        mb = sum(fb) / len(fb)
        numa = sum((x - ma) * (y - mb) for x, y in zip(fa, fb))
        da = math.sqrt(sum((x - ma) ** 2 for x in fa))
        db = math.sqrt(sum((y - mb) ** 2 for y in fb))
        if da < 1e-6 or db < 1e-6:
            continue
        corrs.append(numa / (da * db))
    if len(corrs) < VIS_MIN_LAG_SUPPORT:
        return None
    return sum(corrs) / len(corrs)


def find_visual_sequence_duplicates(
    edl: Sequence[Mapping[str, Any]],
    source_mp4: Path,
    *,
    already_flagged_pairs: Optional[Sequence[Tuple[str, str]]] = None,
    max_pairs: int = 4,
) -> List[Dict[str, Any]]:
    """Time-series visual match for near-adjacent story cuts that may repeat action.

    Does NOT flag same-camera / similar-pitch stills: requires sustained multi-frame
    correlation at a consistent lag. Skips pairs already caught by media overlap.
    """
    if not source_mp4.is_file():
        return []
    flagged = {tuple(sorted(p)) for p in (already_flagged_pairs or [])}
    tl = build_story_timeline(edl)
    segs = [s for s in (tl.get("segments") or []) if s.get("has_media_window")]
    candidates: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            a, b = segs[i], segs[j]
            pair = tuple(sorted((str(a["segment_id"]), str(b["segment_id"]))))
            if pair in flagged:
                continue
            # Prefer story-near pairs (likely perceived as repeat in the cut).
            gap = float(b["story_in"]) - float(a["story_out"])
            if gap > 45.0:
                continue
            # Skip if media already heavily overlaps (handled structurally).
            iou = _media_iou(
                float(a["media_in"]), float(a["media_out"]),
                float(b["media_in"]), float(b["media_out"]),
            )
            if iou >= PARTIAL_IOU:
                continue
            da = float(a["media_out"]) - float(a["media_in"])
            db = float(b["media_out"]) - float(b["media_in"])
            if min(da, db) < VIS_MIN_PAIR_SEC:
                continue
            candidates.append((a, b))
            if len(candidates) >= max_pairs:
                break
        if len(candidates) >= max_pairs:
            break

    findings: List[Dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="v3a_dup_vis_") as td:
        root = Path(td)
        for a, b in candidates:
            wa = root / f"a_{a['segment_id']}"
            wb = root / f"b_{b['segment_id']}"
            wa.mkdir(); wb.mkdir()
            sa = _extract_gray_sequence(
                source_mp4, float(a["media_in"]), float(a["media_out"]), work=wa
            )
            sb = _extract_gray_sequence(
                source_mp4, float(b["media_in"]), float(b["media_out"]), work=wb
            )
            if not sa or not sb:
                continue
            best_corr, best_lag = -1.0, 0
            max_lag = max(1, abs(len(sa) - len(sb)) + int(VIS_SAMPLE_FPS * 2))
            for lag in range(-max_lag, max_lag + 1):
                c = _seq_corr(sa, sb, lag)
                if c is not None and c > best_corr:
                    best_corr, best_lag = c, lag
            if best_corr < VIS_CORR_THRESH:
                continue
            # Map timeline segments back to EDL rows for preference.
            by_id = {str(r.get("segment_id")): r for r in active_cut_rows(edl)}
            ra, rb = by_id.get(str(a["segment_id"]), a), by_id.get(str(b["segment_id"]), b)
            pref = choose_keep_drop(ra, rb, contain=None)
            findings.append(
                {
                    "kind": "visual_sequence_duplicate",
                    "segment_ids": [str(a["segment_id"]), str(b["segment_id"])],
                    "roles": [str(a.get("role") or ""), str(b.get("role") or "")],
                    "media_windows": [
                        {"segment_id": a["segment_id"], "media_in": a["media_in"], "media_out": a["media_out"]},
                        {"segment_id": b["segment_id"], "media_in": b["media_in"], "media_out": b["media_out"]},
                    ],
                    "visual_corr": round(best_corr, 4),
                    "visual_lag_frames": best_lag,
                    "story_offset_sec": round(float(b["story_in"]) - float(a["story_in"]), 3),
                    **pref,
                }
            )
    return findings


def audit_edl_duplicates(
    edl: Sequence[Mapping[str, Any]],
    *,
    source_mp4: Optional[Path] = None,
    enable_visual: bool = False,
) -> Dict[str, Any]:
    """Full duplicate audit for baseline intake / critic."""
    media_findings = find_media_window_duplicates(edl)
    flagged = [tuple(f.get("segment_ids") or []) for f in media_findings]
    visual_findings: List[Dict[str, Any]] = []
    if enable_visual and source_mp4 is not None:
        visual_findings = find_visual_sequence_duplicates(
            edl, source_mp4, already_flagged_pairs=flagged
        )
    findings = media_findings + visual_findings
    auto_drops = sorted(
        {
            str(f["drop_segment_id"])
            for f in findings
            if f.get("decision") == "auto_drop" and f.get("drop_segment_id")
        }
    )
    human = [
        f for f in findings if f.get("decision") == "human_review"
    ]
    return {
        "schema": SCHEMA,
        "finding_count": len(findings),
        "findings": findings,
        "auto_drop_segment_ids": auto_drops,
        "human_review_count": len(human),
        "human_review_findings": human,
        "note": (
            "Auto-drop only when preference is clear (e.g. non-goal contained in "
            "goal_action). Ambiguous pairs stay human_review."
        ),
    }


def apply_auto_drops(
    edl: Sequence[Mapping[str, Any]],
    audit: Mapping[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Apply clear auto-drops; never touch segments not listed."""
    drop_ids = set(audit.get("auto_drop_segment_ids") or [])
    if not drop_ids:
        return [dict(r) for r in edl], {"changed": False, "dropped": []}
    out: List[Dict[str, Any]] = []
    dropped: List[str] = []
    for r in edl:
        row = dict(r)
        sid = str(row.get("segment_id") or "")
        if sid in drop_ids and row.get("include_in_cut", True) is not False:
            # Refuse dropping protected-looking goal_action even if listed.
            if _is_goal(str(row.get("role") or "")):
                out.append(row)
                continue
            row["include_in_cut"] = False
            row["agent_drop_reason"] = "duplicate_audit_auto_drop"
            dropped.append(sid)
        out.append(row)
    return out, {"changed": bool(dropped), "dropped": dropped}


def findings_to_critic_issues(
    audit: Mapping[str, Any],
    timeline: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Map audit findings into Global Story Critic issue rows."""
    by_id = {}
    if timeline:
        for s in timeline.get("segments") or []:
            by_id[str(s.get("segment_id"))] = s
    issues: List[Dict[str, Any]] = []
    for i, f in enumerate(audit.get("findings") or []):
        sids = list(f.get("segment_ids") or [])
        story_range = [0.0, 0.0]
        if sids and sids[0] in by_id:
            story_range = [
                float(by_id[sids[0]].get("story_in") or 0.0),
                float(by_id[sids[-1]].get("story_out") or 0.0),
            ]
        sev = "major"
        if f.get("decision") == "human_review" and f.get("kind") == "visual_sequence_duplicate":
            sev = "major"
        issues.append(
            {
                "issue_id": f"cross_role_duplicate_{f.get('kind')}_{i}",
                "story_time_range": story_range,
                "segment_ids": sids,
                "observation": (
                    f"{f.get('kind')}: segments {sids} roles {f.get('roles')} "
                    f"iou={f.get('iou')} containment={f.get('containment')} "
                    f"decision={f.get('decision')} reason={f.get('reason')}"
                ),
                "narrative_problem": (
                    "Same source action/footage appears more than once in the story cut, "
                    "including across different roles."
                ),
                "severity": sev,
                "suggested_fix": (
                    f"drop:{f.get('drop_segment_id')}"
                    if f.get("drop_segment_id")
                    else "human_review_duplicate_pair"
                ),
                "evidence_sufficiency": (
                    "structure_inferred"
                    if f.get("kind") != "visual_sequence_duplicate"
                    else "observed"
                ),
                "category": "redundancy",
                "preferred_drop_segment_id": f.get("drop_segment_id"),
                "preferred_keep_segment_id": f.get("keep_segment_id"),
                "duplicate_kind": f.get("kind"),
                "duplicate_decision": f.get("decision"),
            }
        )
    return issues


def write_audit(path: Path, audit: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
