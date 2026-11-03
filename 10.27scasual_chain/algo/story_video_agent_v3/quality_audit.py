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
FREEZE = re.compile(r"freeze_start:\s*([0-9.]+).*?freeze_end:\s*([0-9.]+)", re.DOTALL)


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
    return bool(row.get("include_in_cut", True)) and start is not None and end is not None and end > start


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
            "technical_decode_error": "inspect_source_and_render",
            "possible_image_anomaly": "manually_review_flagged_intervals",
        }.get(kind, "investigate"),
    }


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
        freezes = [{"start": float(a), "end": float(b)} for a, b in FREEZE.findall(log)]
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
) -> Dict[str, Any]:
    """Deterministic diagnosis: separates EDL proxies, hard defects, unknown semantics."""
    rows = [r for r in edl if isinstance(r, dict) and r.get("include_in_cut", True)]
    issues: List[Dict[str, str]] = []
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
        "candidate_quality_pass": len(blockers) == 0 and coverage_score == 100.0,
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
    print(json.dumps({"report": str(output), "candidate_quality_pass": result["candidate_quality_pass"],
                      "render_ready": False, "release_decision": result["release_decision"],
                      "issues": len(result["diagnostic_issues"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
