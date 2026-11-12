"""Minimal closed loop: atom-enrich → 8.31 strip → V1 causal adapt → phase5 render.

No paid API. Does not pass human chain structure into 8.31 or V1 — only enriched
delivery events + predicted strip/causal. LIVE goal cuts must be audited; unresolved
segments are labeled, never claimed verified.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .atomic_event_enrich import enrich_files
from .pipeline import dump
from .v1_causal_adapter import strip_chains_to_v1_causal, load_raw_events


def _run_strip(enriched_events: Path, *, match_id: str, algo_root: Path, out_dir: Path) -> Dict[str, Any]:
    from story_video_agent.v2_strip_reinfer import events_to_timeline, run_strip_predict

    raw = json.loads(enriched_events.read_text(encoding="utf-8"))
    timeline = events_to_timeline(raw.get("events") or [])
    dump(out_dir / "timeline_enriched.json", {"match_id": match_id, "events": timeline})
    strip = run_strip_predict(
        timeline_events=timeline,
        match_id=match_id,
        algo_root=algo_root,
        label="atom_enriched",
    )
    dump(out_dir / "strip_A_original.json", strip)
    return strip


def _adapt_v1(
    *,
    strip: Dict[str, Any],
    enriched_events: Path,
    match_id: str,
    video_name: str,
    out_path: Path,
    strip_path: Optional[Path] = None,
    recovery_out_path: Optional[Path] = None,
) -> Dict[str, Any]:
    from .goal_recovery import recover_match_goals

    raw = load_raw_events(enriched_events)
    teams = {}
    try:
        full = json.loads(enriched_events.read_text(encoding="utf-8"))
        teams = full.get("teams") or {}
    except Exception:
        teams = {}
    t1 = ((teams.get("team_1") or {}) if isinstance(teams.get("team_1"), dict) else {}).get("name") or ""
    t2 = ((teams.get("team_2") or {}) if isinstance(teams.get("team_2"), dict) else {}).get("name") or ""

    # Goal Recovery: score-transition candidates from enriched events (+ optional strip link).
    # Does not invent timestamps from human causal structure; recovery forbids *_causal.json.
    recovery = recover_match_goals(
        events_path=enriched_events,
        strip_path=strip_path,
        out_path=recovery_out_path,
    )
    recovered = list(recovery.get("candidates") or [])

    doc = strip_chains_to_v1_causal(
        strip=strip,
        raw_events=raw,
        match_id=match_id,
        video_name=video_name,
        team_1_name=str(t1),
        team_2_name=str(t2),
        recovered_goals=recovered,
    )
    adapter = dict(doc.get("v3_adapter") or {})
    adapter["prediction_source"] = "causal_chain6_predicted_on_atom_enriched_events+v3_goal_recovery"
    adapter["goal_recovery_used"] = True
    adapter["goal_recovery"] = {
        "n_candidates": recovery.get("n_candidates"),
        "n_single_goal": recovery.get("n_single_goal"),
        "n_with_goal_action_sec": recovery.get("n_with_goal_action_sec"),
        "path": str(recovery_out_path) if recovery_out_path else None,
    }
    adapter["human_causal_structure_used"] = False
    doc["v3_adapter"] = adapter
    dump(out_path, doc)
    return doc

def _audit_goal_segments(predicted_causal: Dict[str, Any], enriched_events: Path) -> Dict[str, Any]:
    """Flag goal terminals LIVE vs REPLAY using enriched event video_context only."""
    raw = load_raw_events(enriched_events)
    by_id = {str(e.get("event_id")): e for e in raw}
    audits = []
    for ch in predicted_causal.get("causal_chains") or []:
        for e in ch.get("events") or []:
            if e.get("type") not in {"进球", "乌龙球", "头球破门"} and str(e.get("type_en") or "").lower() not in {
                "goal", "own_goal", "header_goal"
            }:
                continue
            eid = str(e.get("event_id"))
            src = by_id.get(eid) or {}
            vc = src.get("video_context") or {}
            is_replay = bool(vc.get("is_replay")) or str(vc.get("broadcast_phase") or "").upper() == "REPLAY"
            t = e.get("t_ms")
            t_sec = float(t) / 1000.0 if t is not None else None
            status = "replay_detected" if is_replay else (
                "live_candidate" if t_sec is not None else "unresolved"
            )
            audits.append({
                "event_id": eid,
                "type": e.get("type"),
                "t_ms": t,
                "t_sec": t_sec,
                "chain_annotation_id": ch.get("annotation_id"),
                "chain_is_replay": ch.get("is_replay"),
                "event_is_replay": is_replay,
                "live_status": status,
                "edl_eligible_claim": False,  # never auto-claim without visual confirm
                "note": (
                    "LIVE/REPLAY from enriched atom video_context / chain majority; "
                    "visual first-LIVE still required before success claim"
                ),
            })
    n_live = sum(1 for a in audits if a["live_status"] == "live_candidate")
    n_replay = sum(1 for a in audits if a["live_status"] == "replay_detected")
    return {
        "schema": "v3_closed_loop_goal_audit_v1",
        "n_goal_terminals": len(audits),
        "n_live_candidate": n_live,
        "n_replay_detected": n_replay,
        "n_unresolved": sum(1 for a in audits if a["live_status"] == "unresolved"),
        "audits": audits,
        "render_ready": False,
        "success_claimed": False,
    }


def _export_goal_preview_clips(
    *,
    video: Path,
    audit: Dict[str, Any],
    out_dir: Path,
    pad_before: float = 8.0,
    pad_after: float = 10.0,
) -> List[Dict[str, Any]]:
    """Cut short previews around live_candidate goals for human LIVE check (ffmpeg only)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, a in enumerate(audit.get("audits") or []):
        if a.get("live_status") != "live_candidate" or a.get("t_sec") is None:
            continue
        t = float(a["t_sec"])
        tin = max(0.0, t - pad_before)
        tout = t + pad_after
        dest = out_dir / f"{i:02d}_goal_livecand_{tin:.0f}_{tout:.0f}.mp4"
        cmd = [
            "ffmpeg", "-y", "-ss", f"{tin:.3f}", "-to", f"{tout:.3f}",
            "-i", str(video), "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "23", "-c:a", "aac", "-movflags", "+faststart", str(dest),
        ]
        p = subprocess.run(cmd, capture_output=True, text=True)
        rows.append({
            "event_id": a.get("event_id"),
            "t_sec": t,
            "clip": str(dest) if p.returncode == 0 and dest.is_file() else None,
            "ffmpeg_ok": p.returncode == 0,
            "live_status": "unresolved",  # pending visual; do not claim
            "stderr_tail": (p.stderr or "")[-400:],
        })
    return rows


def run_match(
    *,
    match_id: str,
    events_path: Path,
    causal_atoms_path: Optional[Path] = None,
    video: Path,
    out_dir: Path,
    algo_root: Path,
    skip_render: bool = False,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    enrich_dir = out_dir / "01_enrich"
    strip_dir = out_dir / "02_strip831"
    v1_dir = out_dir / "03_v1_adapt"
    phase5_dir = out_dir / "04_phase5"
    audit_dir = out_dir / "05_live_audit"
    for d in (enrich_dir, strip_dir, v1_dir, phase5_dir, audit_dir):
        d.mkdir(parents=True, exist_ok=True)

    enriched_path = enrich_dir / "events_enriched.json"
    enrich_report = enrich_files(
        events_path=events_path,
        causal_path=causal_atoms_path,
        out_events_path=enriched_path,
        out_report_path=enrich_dir / "enrich_report.json",
    )

    strip = _run_strip(enriched_path, match_id=match_id, algo_root=algo_root, out_dir=strip_dir)

    predicted_causal_path = v1_dir / "predicted_causal.json"
    predicted = _adapt_v1(
        strip=strip,
        enriched_events=enriched_path,
        match_id=match_id,
        video_name=video.name,
        out_path=predicted_causal_path,
        strip_path=strip_dir / "strip_A_original.json",
        recovery_out_path=v1_dir / "goal_recovery.json",
    )

    # Delivery path: drop replay chains AND replay Goal atom events (keep full strip artifact).
    raw_for_filter = load_raw_events(enriched_path)
    by_id = {str(e.get("event_id")): e for e in raw_for_filter}

    def _event_is_replay(eid: Any) -> bool:
        vc = (by_id.get(str(eid)) or {}).get("video_context") or {}
        return bool(vc.get("is_replay")) or str(vc.get("broadcast_phase") or "").upper() == "REPLAY"

    live_chains = []
    dropped_replay_goals = 0
    for ch in predicted.get("causal_chains") or []:
        if ch.get("is_replay"):
            continue
        evs = []
        for e in ch.get("events") or []:
            typ = e.get("type")
            en = str(e.get("type_en") or "")
            is_goal = typ in {"进球", "乌龙球", "头球破门"} or en.lower() in {"goal", "own_goal", "header_goal"}
            if is_goal and _event_is_replay(e.get("event_id")):
                dropped_replay_goals += 1
                continue
            evs.append(e)
        if not evs:
            continue
        for i, e in enumerate(evs):
            e = dict(e)
            e["order"] = i
            evs[i] = e
        ch2 = dict(ch)
        ch2["events"] = evs
        live_chains.append(ch2)
    predicted_live = dict(predicted)
    predicted_live["causal_chains"] = live_chains
    predicted_live["v3_adapter"] = dict(predicted.get("v3_adapter") or {})
    predicted_live["v3_adapter"]["n_chains_before_replay_filter"] = len(predicted.get("causal_chains") or [])
    predicted_live["v3_adapter"]["n_chains_after_replay_filter"] = len(live_chains)
    predicted_live["v3_adapter"]["replay_goal_events_dropped"] = dropped_replay_goals
    predicted_live["v3_adapter"]["replay_filter"] = (
        "drop_is_replay_chains_and_replay_Goal_atoms_for_phase5_only"
    )
    predicted_live_path = v1_dir / "predicted_causal_live_goals_only.json"
    dump(predicted_live_path, predicted_live)

    audit = _audit_goal_segments(predicted_live, enriched_path)
    dump(audit_dir / "goal_live_audit.json", audit)
    previews = _export_goal_preview_clips(video=video, audit=audit, out_dir=audit_dir / "goal_previews")
    dump(audit_dir / "goal_preview_clips.json", {"clips": previews})

    # Goal Recovery impact: prove candidates entered predicted_causal (not report-only).
    from .first_live_chain_audit import audit_retained_goal_first_live, build_goal_recovery_impact

    recovery_payload: Dict[str, Any] = {}
    recovery_path = v1_dir / "goal_recovery.json"
    if recovery_path.is_file():
        recovery_payload = json.loads(recovery_path.read_text(encoding="utf-8"))
    recovery_impact = build_goal_recovery_impact(
        predicted_causal=predicted,
        goal_recovery=recovery_payload,
    )
    dump(v1_dir / "goal_recovery_impact.json", recovery_impact)

    phase5_report: Dict[str, Any] = {"skipped": skip_render}
    if not skip_render:
        from story_video_agent.phase5_pipeline import run_phase5
        phase5_report = run_phase5(
            video=video,
            events=enriched_path,
            causal=predicted_live_path,
            out_dir=phase5_dir,
            glitch_profile=None,
            skip_render=False,
        )

    # First-live visual chain audit on retained Phase5 EDL goal anchors (zero paid API).
    first_live_visual: Dict[str, Any] = {
        "schema": "v3a_first_live_chain_audit_v1",
        "skipped": True,
        "reason": "phase5_edl_missing",
    }
    edl_path = phase5_dir / "candidate_edl.json"
    if edl_path.is_file() and video.is_file():
        from .final_goal_evidence import sha256_file

        # Record SHA at audit creation time (historical identity). Never backfill later.
        video_sha = sha256_file(
            video, cache_path=audit_dir / "source_video.sha256.json"
        )
        edl_obj = json.loads(edl_path.read_text(encoding="utf-8"))
        first_live_visual = audit_retained_goal_first_live(
            video=video,
            edl=edl_obj,
            out_dir=audit_dir / "first_live_visual",
            events_path=enriched_path,
            goal_recovery=recovery_payload,
            enable_paid_vlm=False,
            source_video_sha256=video_sha,
        )
        dump(audit_dir / "first_live_visual_audit.json", first_live_visual)

    summary = {
        "schema": "v3_closed_loop_run_v1",
        "input_mode": enrich_report["input_mode"],
        "human_annotation_atoms_used": enrich_report["human_annotation_atoms_used"],
        "eligible_for_raw_only_evaluation": enrich_report["eligible_for_raw_only_evaluation"],
        "match_id": match_id,
        "paid_api_calls": 0,
        "enrich": enrich_report,
        "strip": {
            "n_chains": strip.get("n_chains"),
            "n_events": strip.get("n_events"),
            "category_counts": strip.get("category_counts"),
            "path": str(strip_dir / "strip_A_original.json"),
        },
        "predicted_causal": {
            "path": str(predicted_causal_path),
            "n_chains": len(predicted.get("causal_chains") or []),
            "n_goal_terminals": (predicted.get("v3_adapter") or {}).get("n_goal_terminals_in_adapted_chains"),
            "goal_recovery_used": bool((predicted.get("v3_adapter") or {}).get("goal_recovery_used")),
            "goal_recovery": (predicted.get("v3_adapter") or {}).get("goal_recovery"),
            "goal_recovery_impact": recovery_impact,
        },
        "goal_audit": {
            "n_goal_terminals": audit.get("n_goal_terminals"),
            "n_live_candidate": audit.get("n_live_candidate"),
            "n_replay_detected": audit.get("n_replay_detected"),
            "success_claimed": False,
            "visual_first_live_verified": bool(first_live_visual.get("any_first_live_verified")),
            "first_live_status_counts": first_live_visual.get("status_counts"),
            "preview_clips": [c.get("clip") for c in previews if c.get("clip")],
            "note": (
                "Metadata LIVE audit + zero-cost first-live frame/clip audit. "
                "ffmpeg preview success and score flips never certify FIRST_LIVE_VERIFIED."
            ),
        },
        "first_live_visual": {
            "path": str(audit_dir / "first_live_visual_audit.json"),
            "status_counts": first_live_visual.get("status_counts"),
            "n_goal_anchors": first_live_visual.get("n_goal_anchors"),
            "any_replay_on_retained": first_live_visual.get("any_replay_on_retained"),
            "all_resolved_verified": first_live_visual.get("all_resolved_verified"),
            "paid_api_calls": 0,
        },
        "phase5": {
            "out_dir": str(phase5_dir),
            "story_clean": str(phase5_dir / "story_clean.mp4"),
            "story_qc": str(phase5_dir / "story_qc.mp4"),
            "report_keys": sorted(phase5_report.keys()) if isinstance(phase5_report, dict) else [],
        },
        "render_ready": False,
        "success_claimed": False,
        "note": (
            "MP4 may exist as candidate delivery; LIVE first-goal visual status remains "
            "unresolved until audited. Do not treat as verified no-replay final."
        ),
    }
    dump(out_dir / "closed_loop_summary.json", summary)
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="V3 closed loop: enrich→8.31→V1 phase5")
    p.add_argument("--match-id", required=True)
    p.add_argument("--events", type=Path, required=True)
    p.add_argument("--causal-atoms", type=Path, default=None,
                   help="Optional historical DEV atom enrichment; never raw-only benchmark input")
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--algo-root", type=Path, required=True)
    p.add_argument("--skip-render", action="store_true")
    args = p.parse_args(argv)
    summary = run_match(
        match_id=args.match_id,
        events_path=args.events,
        causal_atoms_path=args.causal_atoms,
        video=args.video,
        out_dir=args.out_dir,
        algo_root=args.algo_root,
        skip_render=args.skip_render,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
