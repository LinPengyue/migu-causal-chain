"""V3-A phase 1: read-only, evidence-labelled QC of frozen V3-R outputs.

This is a structural diagnostic, NOT a semantic VLM verifier and NOT a
production render-ready grant. It never rewrites EDL, video, or upstream inputs.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

BEAT_ORDER = {"铺垫": 0, "蓄力": 1, "转折": 2, "高潮": 3, "收尾": 4}
REQUIRED = {
    "behind_start": ("opponent_opening", "opponent_opening_goal_action"),
    "equalizer": ("equalizer", "equalizer_goal_action"),
    "go_ahead": ("go_ahead", "go_ahead_goal_action"),
}
DECODE_ERROR = re.compile(
    r"error while decoding|invalid data found|corrupt|concealing .* errors|invalid nal|decode error",
    re.IGNORECASE,
)
BLACK = re.compile(r"black_start:([0-9.]+)\s+black_end:([0-9.]+)")
FREEZE_START = re.compile(r"freeze_start:\s*([0-9.]+)")
FREEZE_END = re.compile(r"freeze_end:\s*([0-9.]+)")


def _number(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        v = float(value)
        if not (-1e12 < v < 1e12):
            return None
        return v
    except (ValueError, TypeError):
        return None


def _clip(row: Dict[str, Any]) -> bool:
    start, end = _number(row.get("media_in")), _number(row.get("media_out"))
    return bool(row.get("include_in_cut", True)) and start is not None and end is not None and start >= 0 and end > start


def _goal(row: Dict[str, Any]) -> bool:
    return "goal_action" in str(row.get("role") or "") and row.get("shot_kind") != "title_card"


def _role(row: Dict[str, Any], prefix: str) -> bool:
    role = str(row.get("role") or "")
    return (
        role.startswith(prefix)
        and _clip(row)
        and row.get("goal_action_complete") is not False
        and not row.get("is_replay", False)
        and row.get("shot_kind") not in ("title_card", "replay_supplement", "scoreboard_anchor")
    )


ROLE_QUALIFIER_SUFFIXES = (
    "_live", "_candidate", "_unverified", "_pending",
    "_approach", "_incomplete", "_reaction", "_transition",
)
OVERLAP_IOU_DUP = 0.45


def _canonical_role(role: Any) -> str:
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


def _iou(a_in: float, a_out: float, b_in: float, b_out: float) -> float:
    inter = max(0.0, min(a_out, b_out) - max(a_in, b_in))
    union = max(a_out, b_out) - min(a_in, b_in)
    return 0.0 if union <= 1e-9 else inter / union


def _issue(kind: str, severity: str, target: str, detail: str) -> Dict[str, str]:
    return {
        "kind": kind, "severity": severity, "target": target, "detail": detail,
        "suggested_action": {
            "missing_story_element": "locate_or_recover_story_evidence",
            "goal_window_incomplete": "inspect_local_goal_window",
            "replay_as_primary": "replace_with_live_or_block",
            "bad_media_window": "repair_or_drop_invalid_cut",
            "beat_order_inversion": "review_narrative_order",
            "duplicated_goal_event": "resolve_event_to_goal_mapping",
            "duplicate_canonical_goal_role": "drop_synonym_or_use_replace",
            "overlapping_goal_windows": "resolve_accidental_duplicate_cut",
            "baseline_goal_media_regressed": "restore_or_verify_before_accept",
            "technical_decode_error": "inspect_source_and_render",
            "known_integrity_failure": "repair_or_replace_corrupt_clip",
            "possible_image_anomaly": "manually_review_flagged_intervals",
        }.get(kind, "investigate"),
    }


def compare_edl_non_regression(
    baseline_edl: Sequence[Dict[str, Any]],
    candidate_edl: Sequence[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """Relative-to-V3-R checks: accidental duplicates and unverified goal window drift."""
    issues: List[Dict[str, str]] = []
    cand_rows = [r for r in candidate_edl if isinstance(r, dict) and r.get("include_in_cut", True)]
    goals = [r for r in cand_rows if "goal_action" in str(r.get("role") or "") and r.get("shot_kind") != "title_card"]
    by_canon: Dict[str, List[Dict[str, Any]]] = {}
    for r in goals:
        by_canon.setdefault(_canonical_role(r.get("role")), []).append(r)
    for role, group in by_canon.items():
        if len(group) > 1:
            ids = ",".join(str(x.get("segment_id") or "") for x in group)
            issues.append(_issue(
                "duplicate_canonical_goal_role", "P0", ids,
                f"Multiple in-cut goal segments share canonical role '{role}' "
                "(synonym insert / failed replace). Distinct narrative roles are OK.",
            ))
    for i in range(len(goals)):
        ai, ao = _number(goals[i].get("media_in")), _number(goals[i].get("media_out"))
        if ai is None or ao is None:
            continue
        for j in range(i + 1, len(goals)):
            bi, bo = _number(goals[j].get("media_in")), _number(goals[j].get("media_out"))
            if bi is None or bo is None:
                continue
            iou = _iou(ai, ao, bi, bo)
            same = _canonical_role(goals[i].get("role")) == _canonical_role(goals[j].get("role"))
            # High overlap of same-family goals = accidental duplicate; different roles may narratively reuse.
            if same and iou >= 0.2:
                issues.append(_issue(
                    "overlapping_goal_windows", "P0",
                    f"{goals[i].get('segment_id')},{goals[j].get('segment_id')}",
                    f"Same-role-family goal windows overlap (iou={iou:.2f}).",
                ))
            elif (not same) and iou >= OVERLAP_IOU_DUP:
                issues.append(_issue(
                    "overlapping_goal_windows", "P1",
                    f"{goals[i].get('segment_id')},{goals[j].get('segment_id')}",
                    f"Distinct roles but highly overlapping source windows (iou={iou:.2f}); review.",
                ))
    base_by_id = {
        str(r.get("segment_id")): r
        for r in baseline_edl if isinstance(r, dict) and r.get("segment_id")
    }
    for sid, b in base_by_id.items():
        if "goal_action" not in str(b.get("role") or ""):
            continue
        if b.get("include_in_cut", True) is False:
            continue
        b_in, b_out = _number(b.get("media_in")), _number(b.get("media_out"))
        if b_in is None or b_out is None:
            continue
        c = next((r for r in cand_rows if str(r.get("segment_id")) == sid), None)
        if c is None:
            # Retire via replace/drop is OK if marked; otherwise flag
            retired = next(
                (r for r in candidate_edl
                 if isinstance(r, dict) and str(r.get("segment_id")) == sid
                 and r.get("include_in_cut") is False),
                None,
            )
            if retired is None or not (
                retired.get("agent_drop_reason") or retired.get("agent_replaced_by")
            ):
                issues.append(_issue(
                    "baseline_goal_media_regressed", "P1", sid,
                    "Baseline goal cut missing from candidate without explicit drop/replace mark.",
                ))
            continue
        c_in, c_out = _number(c.get("media_in")), _number(c.get("media_out"))
        if c_in is None or c_out is None:
            continue
        if abs(b_in - c_in) > 2.0 or abs(b_out - c_out) > 2.0:
            verified = (
                c.get("first_live_status") == "FIRST_LIVE_VERIFIED"
                or c.get("agent_auto_verified") is True
            )
            if not verified:
                issues.append(_issue(
                    "baseline_goal_media_regressed", "P0", sid,
                    "Goal media window drifted vs V3-R baseline without first-live verification.",
                ))
    return issues



def _freeze_intervals(log: str, duration: float) -> List[Dict[str, float]]:
    """Include trailing freeze without an end event; it can be an intentional end card."""
    starts = [float(x) for x in FREEZE_START.findall(log)]
    ends = [float(x) for x in FREEZE_END.findall(log)]
    intervals = []
    for i, start in enumerate(starts):
        end = ends[i] if i < len(ends) else duration
        if end >= start:
            intervals.append({"start": start, "end": round(end, 3)})
    return intervals


def scan_rendered_video(path: Optional[Path]) -> Dict[str, Any]:
    """Optional technical screening of rendered MP4; not semantic/visual certification.

    Long source videos are refused: this scanner is for the short story MP4 only.
    Black/freeze intervals may be deliberate title cards, so they are warnings only.
    """
    if path is None:
        return {"status": "NOT_MEASURED", "score": None, "reason": "no_rendered_video_supplied"}
    path = Path(path)
    if not path.is_file():
        return {"status": "NOT_MEASURED", "score": None, "reason": "video_missing"}
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=20, check=True,
        )
        duration = _number(probe.stdout.strip())
        if duration is None or duration <= 0:
            return {"status": "UNKNOWN", "score": None, "reason": "duration_unreadable"}
        if duration > 900:
            return {"status": "NOT_MEASURED", "score": None,
                    "reason": "story_video_scan_limit_900s", "duration_sec": duration}
        run = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "info",
             "-i", str(path), "-an",
             "-vf", "blackdetect=d=1.0:pix_th=0.10,freezedetect=n=-55dB:d=1.5",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=180,
        )
        log = run.stderr or ""
        errors = [line.strip()[:240] for line in log.splitlines() if DECODE_ERROR.search(line)]
        black = [{"start": float(a), "end": float(b)} for a, b in BLACK.findall(log)]
        freezes = _freeze_intervals(log, duration)
        return {
            "status": "SCREENED" if run.returncode == 0 else "SCAN_FAILED",
            "score": max(0, 100 - min(100, 25 * len(errors))) if run.returncode == 0 else None,
            "score_kind": "decode_error_proxy_only",
            "duration_sec": round(duration, 3),
            "decode_error_count": len(errors), "decode_error_examples": errors[:10],
            "possible_black_intervals": black[:30],
            "possible_freeze_intervals": freezes[:30],
            "warnings_require_review": True,
            "semantic_qc_verified": False,
            "note": "Black/freeze can be normal title cards; clean decoding does not exclude macroblocks or wrong shots.",
        }
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        return {"status": "UNKNOWN", "score": None, "reason": type(exc).__name__}


def evaluate(
    story: Dict[str, Any], plan: Dict[str, Any], edl: Sequence[Dict[str, Any]],
    *, rendered_video: Optional[Path] = None,
    baseline_edl: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Deterministic diagnosis: separates EDL proxies, hard defects, unknown semantics."""
    rows = [r for r in edl if isinstance(r, dict) and r.get("include_in_cut", True)]
    issues: List[Dict[str, str]] = []
    if baseline_edl is not None:
        issues.extend(compare_edl_non_regression(list(baseline_edl), list(edl)))
    arc = (plan.get("story_scope") or {}).get("selected_arc") or {}
    tier = str(plan.get("story_tier") or story.get("story_tier") or "none")
    requirements: List[Dict[str, Any]] = []
    for key, (name, role_prefix) in REQUIRED.items():
        # If scope is missing, do not infer that all story milestones are mandatory.
        if key not in arc or arc.get(key) is None:
            requirements.append({"name": name, "required": False, "edl_present": None,
                                 "status": "UNKNOWN_SCOPE" if key not in arc else "NOT_IN_SELECTED_ARC"})
            continue
        matched = [str(r.get("segment_id") or "") for r in rows if _role(r, role_prefix)]
        has = bool(matched)
        requirements.append({"name": name, "required": True, "edl_present": has,
                             "status": "EDL_PRESENT_UNVERIFIED" if has else "MISSING_EDL",
                             "segment_ids": matched})
        if not has:
            issues.append(_issue("missing_story_element", "P0", name,
                                 "Required T01 arc goal action absent from cut; scoreboard/title is not a substitute."))

    active = [r for r in requirements if r["required"]]
    coverage_score = round(100 * sum(r["edl_present"] for r in active) / len(active), 1) if active else None
    valid_rows = [r for r in rows if r.get("shot_kind") != "title_card"]
    bad = [str(r.get("segment_id") or r.get("edl_index")) for r in valid_rows if not _clip(r)]
    if bad:
        issues.append(_issue("bad_media_window", "P0", ",".join(bad[:8]),
                             "One or more intended media cuts has an invalid/missing source window."))

    incomplete = [str(r.get("segment_id") or r.get("role")) for r in rows
                  if _goal(r) and r.get("goal_action_complete") is False]
    if incomplete:
        issues.append(_issue("goal_window_incomplete", "P0", ",".join(incomplete[:8]),
                             "Goal action is explicitly marked incomplete by upstream EDL."))

    integrity = [str(r.get("segment_id") or r.get("role")) for r in rows
                 if _clip(r) and (r.get("integrity_failure") or any(
                     str(b).startswith(("goal_integrity_failed:", "blocked_source_corruption"))
                     for b in (r.get("blocking_reasons") or [])))]
    if integrity:
        issues.append(_issue("known_integrity_failure", "P0", ",".join(integrity[:8]),
                             "Source/EDL already flags an integrity problem; do not silently pass."))

    replay = [str(r.get("segment_id") or r.get("role")) for r in rows
              if _goal(r) and r.get("is_replay") and "supplement" not in str(r.get("role") or "")]
    if replay:
        issues.append(_issue("replay_as_primary", "P0", ",".join(replay[:8]),
                             "EDL declares replay in primary goal position."))

    beats = [(str(r.get("segment_id") or r.get("role")), BEAT_ORDER[str(r.get("beat"))])
             for r in rows if _clip(r) and str(r.get("beat")) in BEAT_ORDER]
    inversions = [(beats[i - 1][0], beats[i][0]) for i in range(1, len(beats))
                  if beats[i][1] < beats[i - 1][1]]
    if inversions:
        issues.append(_issue("beat_order_inversion", "P1", str(inversions[:5]),
                             "Narrative beat regresses within selected EDL order (may be deliberate flashback)."))

    event_to_roles: Dict[str, set] = {}
    for r in rows:
        if not (_goal(r) and _clip(r)):
            continue
        role = str(r.get("role") or "").replace("_approach", "").replace("_incomplete", "")
        for event_id in r.get("event_ids") or []:
            event_to_roles.setdefault(str(event_id), set()).add(role)
    duplicated = {eid: sorted(roles) for eid, roles in event_to_roles.items() if len(roles) > 1}
    if duplicated:
        issues.append(_issue("duplicated_goal_event", "P0", str(duplicated),
                             "One source goal event drives different story goal roles."))

    coherence_checks = {
        "valid_media_windows": not bad,
        "narrative_beat_order": not inversions,
        "unique_goal_event_roles": not duplicated,
    }
    coherence_score = round(100 * sum(coherence_checks.values()) / len(coherence_checks), 1)
    video = scan_rendered_video(rendered_video)
    if video.get("decode_error_count", 0):
        issues.append(_issue("technical_decode_error", "P0", "rendered_video",
                             "Decoder emitted errors. Review source and output."))
    if video.get("possible_black_intervals") or video.get("possible_freeze_intervals"):
        issues.append(_issue("possible_image_anomaly", "P2", "rendered_video",
                             "Screening detected potential black/freeze windows; title cards may be intentional."))

    # Fail-closed: a structural score cannot certify true visual story coverage.
    blockers = [i for i in issues if i["severity"] == "P0"]
    structural_proxy_pass = len(blockers) == 0 and coverage_score == 100.0 and coherence_score == 100.0
    return {
        "schema": "v3a_story_quality_audit_v1",
        "mode": "READ_ONLY_RULE_BASELINE",
        "match_id": plan.get("match_id") or story.get("match_id"),
        "story_tier": tier,
        "dimensions": {
            "story_element_coverage": {
                "score": coverage_score, "score_kind": "candidate_edl_role_proxy",
                "required_roles": requirements,
                "not_measured": ["visual_truth", "missing_unannotated_events", "tactical_causality"],
            },
            "story_coherence": {
                "score": coherence_score, "score_kind": "edl_structural_proxy",
                "checks": coherence_checks,
                "not_measured": ["semantic_narrative_coherence", "shot_relevance"],
            },
            "image_quality": video,
        },
        "hard_gate_findings": blockers,
        "diagnostic_issues": issues,
        "unverified": ["live_vs_replay_visual_truth", "VLM_semantics", "shot_event_grounding"],
        "input_missing_evidence": list(plan.get("missing_evidence") or []),
        "revision_requests": [i for i in issues if i["severity"] in ("P0", "P1")],
        "structural_proxy_pass": structural_proxy_pass,
        "render_ready": False,
        "release_decision": "NOT_AUTHORIZED",
        "note": "Scores are deterministic structural proxies, not calibrated quality or semantic release certification.",
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only V3-A quality audit of Phase5 output")
    parser.add_argument("--phase5-dir", type=Path, required=True)
    parser.add_argument("--rendered-video", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    directory = args.phase5_dir
    required = ("t01_story.json", "story_plan.json", "candidate_edl.json")
    try:
        inputs = [json.loads((directory / name).read_text(encoding="utf-8")) for name in required]
    except (OSError, ValueError) as exc:
        parser.error("missing or malformed Phase5 output: " + str(exc))
    result = evaluate(*inputs, rendered_video=args.rendered_video)
    output = args.out or (directory / "v3a_quality_audit.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(output), "structural_proxy_pass": result["structural_proxy_pass"],
                      "render_ready": False, "release_decision": result["release_decision"],
                      "issues": len(result["diagnostic_issues"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
