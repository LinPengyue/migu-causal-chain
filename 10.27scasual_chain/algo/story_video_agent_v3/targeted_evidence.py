"""V3-P2 targeted critical-goal evidence retrieval (no unbounded scan, no paid API).

Builds finite retrieval tasks from score windows + optional historical candidate
clues (match-specific handoff paths). Never hardcodes PTS into the ranking
algorithm. Produces evidence packs that V3 gate can consume; remains unresolved
without contiguous LIVE shot/net proof.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .pipeline import CRITICAL, dump


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _ffprobe_duration(path: Path) -> Optional[float]:
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            text=True,
        ).strip()
        return float(out)
    except Exception:
        return None


def _cut_clip(video: Path, media_in: float, media_out: float, out_mp4: Path) -> Dict[str, Any]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return {"ok": False, "reason": "ffmpeg_missing"}
    mi = max(0.0, float(media_in))
    mo = float(media_out)
    if mo <= mi + 0.2:
        return {"ok": False, "reason": "empty_window"}
    dur = min(40.0, mo - mi)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    pad = min(10.0, mi)
    coarse = max(0.0, mi - pad)
    fine = mi - coarse
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{coarse:.3f}", "-i", str(video),
        "-ss", f"{fine:.3f}", "-t", f"{dur:.3f}",
        "-c", "copy", str(out_mp4),
    ]
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as exc:
        return {"ok": False, "reason": f"ffmpeg_fail:{exc}"}
    return {
        "ok": True,
        "path": str(out_mp4),
        "media_in": mi,
        "media_out": mi + dur,
        "duration_sec": dur,
        "sha256": _sha256(out_mp4) if out_mp4.is_file() else None,
        "bytes": out_mp4.stat().st_size if out_mp4.is_file() else 0,
        "continuous_source": True,
        "stitched": False,
    }


def _extract_frame(video: Path, media_sec: float, out_jpg: Path) -> Dict[str, Any]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return {"ok": False, "reason": "ffmpeg_missing"}
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    t = max(0.0, float(media_sec))
    pad = min(8.0, t)
    coarse = max(0.0, t - pad)
    fine = t - coarse
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{coarse:.3f}", "-i", str(video),
        "-ss", f"{fine:.3f}", "-frames:v", "1", str(out_jpg),
    ]
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as exc:
        return {"ok": False, "reason": f"ffmpeg_fail:{exc}"}
    return {
        "ok": out_jpg.is_file(),
        "path": str(out_jpg),
        "media_sec": t,
        "sha256": _sha256(out_jpg) if out_jpg.is_file() else None,
    }


def load_historical_candidate_clues(
    *,
    match_tag: str,
    role: str,
    g22_root: Path,
) -> List[Dict[str, Any]]:
    """Read existing G2.2 first-live packs as clues — not algorithm constants."""
    pack_path = g22_root / match_tag / "roles" / role / "role_first_live_pack.json"
    if not pack_path.is_file():
        return []
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    clues = []
    for row in pack.get("exported") or []:
        if row.get("media_in") is None or row.get("media_out") is None:
            continue
        clues.append({
            "source": "g22_first_live_pack",
            "candidate_id": row.get("candidate_id"),
            "kind": row.get("kind"),
            "media_in": float(row["media_in"]),
            "media_out": float(row["media_out"]),
            "clip_path": row.get("clip_path"),
            "shot_sec": row.get("shot_sec"),
            "note": "Historical retrieval clue; must re-verify LIVE shot/net",
        })
    return clues


def build_role_retrieval_task(
    *,
    role: str,
    task_row: Dict[str, Any],
    clues: Sequence[Dict[str, Any]],
    max_candidates: int = 4,
    max_video_read_sec: float = 120.0,
) -> Dict[str, Any]:
    conf = task_row.get("score_confirmation_sec")
    windows = []
    # Primary: historical clues first (budgeted)
    for c in clues[:max_candidates]:
        windows.append({
            "media_in": c["media_in"],
            "media_out": c["media_out"],
            "origin": "historical_clue",
            "candidate_id": c.get("candidate_id"),
            "clip_path_existing": c.get("clip_path"),
        })
    # Secondary: earlier-search blocks before confirmation (not late_third hug)
    if conf is not None and len(windows) < max_candidates:
        c = float(conf)
        for i, end in enumerate([c - 5.0, c - 45.0, c - 85.0]):
            if len(windows) >= max_candidates:
                break
            if end <= 20:
                continue
            start = max(0.0, end - 35.0)
            windows.append({
                "media_in": round(start, 3),
                "media_out": round(end, 3),
                "origin": "pre_confirm_search_block",
                "block_index": i,
            })
    budget = sum(max(0.0, float(w["media_out"]) - float(w["media_in"])) for w in windows)
    return {
        "role": role,
        "score_before": task_row.get("score_before"),
        "score_after": task_row.get("score_after"),
        "score_confirmation_sec": conf,
        "goal_action_sec": None,
        "constraints": {
            "live_only": True,
            "reject_replay": True,
            "attacking_team_must_match_score_delta": True,
            "no_score_confirm_as_goal_action": True,
            "max_candidates": max_candidates,
            "max_video_read_sec": max_video_read_sec,
        },
        "candidate_windows": windows,
        "planned_video_read_sec": round(budget, 3),
        "status": "pending_local_audit",
        "render_ready": False,
    }


def audit_candidate_window(
    *,
    video: Path,
    role: str,
    window: Dict[str, Any],
    out_dir: Path,
    score_before: Optional[List[int]],
    score_after: Optional[List[int]],
    score_confirmation_sec: Optional[float],
    agent_notes: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Materialize continuous clip+frames; never auto-upgrade to verified."""
    role_dir = out_dir / "roles" / role
    clips = role_dir / "clips"
    frames = role_dir / "frames"
    cid = str(window.get("candidate_id") or f"{role}_{window.get('origin')}_{int(window['media_in'])}")
    out_clip = clips / f"{cid}_continuous.mp4"
    cut = _cut_clip(video, float(window["media_in"]), float(window["media_out"]), out_clip)
    frame_rows = []
    if cut.get("ok"):
        mi, mo = float(cut["media_in"]), float(cut["media_out"])
        for j, t in enumerate([mi + 1.0, 0.5 * (mi + mo), max(mi + 1.0, mo - 1.5)]):
            fr = _extract_frame(video, t, frames / f"{cid}_f{j}_{int(t*1000)}.jpg")
            frame_rows.append(fr)
    notes = dict(agent_notes or {})
    # Fail-closed defaults — agent frame notes cannot alone verify
    return {
        "role": role,
        "candidate_id": cid,
        "media_in": window.get("media_in"),
        "media_out": window.get("media_out"),
        "origin": window.get("origin"),
        "clip_export": cut,
        "clip_path": cut.get("path") if cut.get("ok") else None,
        "frames": frame_rows,
        "frame_paths": [f["path"] for f in frame_rows if f.get("ok")],
        "score_before": score_before,
        "score_after": score_after,
        "score_confirmation_sec": score_confirmation_sec,
        "goal_action_sec": None,
        "shot_sec": None,
        "net_sec": None,
        "observed_shot": False,
        "observed_net": False,
        "first_live_visual_ok": False,
        "attacking_team_match": False,
        "claims_continuous_live": False,
        "live_or_replay": "unknown",
        "human_video_supported": False,
        "agent_auto_verified": False,
        "verification_status": "unresolved",
        "semantic_verification_class": "NOT_VERIFIED",
        "agent_preliminary_notes": notes,
        "evidence_gaps": [
            "observed_shot_unconfirmed",
            "observed_net_unconfirmed",
            "first_live_unconfirmed",
            "attacking_team_unconfirmed",
        ],
        "render_ready": False,
    }


def run_targeted_evidence_pass(
    *,
    v3_run_dir: Path,
    video: Path,
    out_dir: Path,
    match_tag: str,
    g22_root: Path,
    prefer_roles: Optional[Sequence[str]] = None,
    max_candidates_per_role: int = 3,
) -> Dict[str, Any]:
    run = Path(v3_run_dir)
    dest = Path(out_dir)
    if dest.exists() and any(dest.iterdir()):
        raise RuntimeError(f"Refusing nonempty evidence out dir: {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    tasks = json.loads((run / "critical_goal_evidence_tasks.json").read_text(encoding="utf-8"))
    provenance = json.loads((run / "provenance.json").read_text(encoding="utf-8"))
    identity = {
        "match_id": provenance["match_id"],
        "video_sha256": provenance["input_hashes"]["video_sha256"],
        "events_sha256": provenance["input_hashes"]["events_sha256"],
        "strip_provenance": provenance["input_hashes"]["strips_sha256"],
    }
    order = list(prefer_roles or CRITICAL)
    for r in CRITICAL:
        if r not in order:
            order.append(r)

    retrieval_plan = {"schema": "v3_targeted_retrieval_plan_v1", "roles": {}, "render_ready": False}
    audits: Dict[str, Any] = {}
    evidence_goals: List[Dict[str, Any]] = []
    video_read = 0.0

    # Optional match-specific agent notes (not verification)
    agent_notes_by_role: Dict[str, Dict[str, Any]] = {}
    if match_tag.startswith("B_") and "opening_deficit" in order:
        agent_notes_by_role["opening_deficit"] = {
            "review_clue": "G2.2/G2.3 historical window near ~3128–3153 (user-cited ~3130–3135)",
            "agent_frame_audit": (
                "At ~3128–3137 board still OSA 1-1 CEL (45:06+3); corner/box action then "
                "Osasuna celebration-like reaction. No clear continuous ball-in-net proved; "
                "2:1 board confirm is later (~3199). Treat as SHOT_OR_CHANCE_UNRESOLVED."
            ),
            "human_video_supported": False,
            "agent_auto_verified": False,
        }

    for role in order:
        task_row = next((t for t in tasks.get("tasks") or [] if t.get("role") == role), None)
        if not task_row:
            continue
        clues = load_historical_candidate_clues(match_tag=match_tag, role=role, g22_root=g22_root)
        plan = build_role_retrieval_task(
            role=role, task_row=task_row, clues=clues, max_candidates=max_candidates_per_role
        )
        retrieval_plan["roles"][role] = plan
        role_audits = []
        for window in plan["candidate_windows"][:max_candidates_per_role]:
            video_read += max(0.0, float(window["media_out"]) - float(window["media_in"]))
            if video_read > 6 * 120:  # hard stop across match
                break
            audited = audit_candidate_window(
                video=video,
                role=role,
                window=window,
                out_dir=dest,
                score_before=task_row.get("score_before"),
                score_after=task_row.get("score_after"),
                score_confirmation_sec=task_row.get("score_confirmation_sec"),
                agent_notes=agent_notes_by_role.get(role) if window == plan["candidate_windows"][0] else None,
            )
            role_audits.append(audited)
        audits[role] = role_audits
        # Top candidate for evidence pack — still unresolved without full visual proof
        top = role_audits[0] if role_audits else None
        if top and top.get("clip_path"):
            evidence_goals.append({
                "role": role,
                "identity": identity,
                "live_or_replay": "unknown",
                "observed_shot": False,
                "observed_net": False,
                "first_live_visual_ok": False,
                "attacking_team_match": False,
                "claims_continuous_live": bool((top.get("clip_export") or {}).get("continuous_source")),
                "media_in": top.get("media_in"),
                "media_out": top.get("media_out"),
                "shot_sec": None,
                "net_sec": None,
                "clip_path": top.get("clip_path"),
                "frame_paths": top.get("frame_paths") or [],
                "semantic_verification_class": "NOT_VERIFIED",
                "human_video_supported": False,
                "agent_auto_verified": False,
                "verification_status": "unresolved",
                "candidate_id": top.get("candidate_id"),
                "evidence_gaps": top.get("evidence_gaps"),
                "agent_preliminary_notes": top.get("agent_preliminary_notes"),
                "render_ready": False,
            })

    pack = {
        "schema": "v3_targeted_evidence_pack_v1",
        "match_id": identity["match_id"],
        "match_tag": match_tag,
        "goals": evidence_goals,
        "n_agent_auto_verified": 0,
        "n_human_video_supported": 0,
        "video_read_sec_approx": round(video_read, 3),
        "note": "Packaged candidates for gate; NOT verified first-live goals",
        "render_ready": False,
    }
    dump(dest / "retrieval_plan.json", retrieval_plan)
    dump(dest / "candidate_audits.json", audits)
    dump(dest / "evidence_pack.json", pack)
    dump(dest / "evidence_pass_report.json", {
        "schema": "v3_targeted_evidence_pass_v1",
        "match_tag": match_tag,
        "n_roles": len(audits),
        "n_pack_goals": len(evidence_goals),
        "n_video_verified": 0,
        "n_agent_auto_verified": 0,
        "n_human_video_supported": 0,
        "critical_video_evidence_pass": False,
        "video_read_sec_approx": round(video_read, 3),
        "render_ready": False,
    })
    return pack
