"""G2 zero-API video evidence retrieval + human review pack.

Produces continuous source clips + frame hashes for selected_arc roles.
Never upgrades to automated_video_verified without a real semantic log (G2 default: pending).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from story_video_agent.v2_event_adapter import load_events_json
from story_video_agent.v2_g0_cross_match_preflight import (
    assert_match_id_consistent,
    reject_forbidden_input_path,
    reject_forbidden_payload,
    sha256_file,
    write_json,
)
from story_video_agent.v2_video_evidence_gate import NOT_VERIFIED, PENDING


_SHOWINFO_PTS = re.compile(r"pts_time:(?P<pts>-?\d+(?:\.\d+)?)")


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not found")
    return exe


def _ffprobe_duration(video: Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(video),
        ],
        text=True,
    ).strip()
    return float(out)


def _cut_continuous_clip(
    *,
    video: Path,
    media_in: float,
    media_out: float,
    out_mp4: Path,
) -> Dict[str, Any]:
    """Cut one continuous source window (no multi-window stitch)."""
    ffmpeg = _ffmpeg()
    media_in = max(0.0, float(media_in))
    media_out = float(media_out)
    if media_out <= media_in + 0.2:
        return {"ok": False, "reason": "empty_window"}
    dur = media_out - media_in
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    # Hybrid seek for accuracy; single continuous -t window (no concat).
    pad = min(15.0, media_in)
    coarse = max(0.0, media_in - pad)
    fine = media_in - coarse
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{coarse:.3f}",
        "-i",
        str(video),
        "-ss",
        f"{fine:.3f}",
        "-t",
        f"{dur:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(out_mp4),
    ]
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return {
        "ok": proc.returncode == 0 and out_mp4.is_file() and out_mp4.stat().st_size > 1000,
        "path": str(out_mp4),
        "media_in": media_in,
        "media_out": media_out,
        "duration_sec": round(dur, 3),
        "elapsed_sec": round(time.time() - t0, 3),
        "stderr_tail": (proc.stderr or "")[-400:],
        "continuous_source": True,
        "stitched": False,
    }


def _extract_frame(
    *,
    video: Path,
    media_sec: float,
    out_jpg: Path,
) -> Dict[str, Any]:
    ffmpeg = _ffmpeg()
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    media_sec = max(0.0, float(media_sec))
    pad = min(10.0, media_sec)
    coarse = max(0.0, media_sec - pad)
    fine = media_sec - coarse
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{coarse:.3f}",
        "-i",
        str(video),
        "-ss",
        f"{fine:.3f}",
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(out_jpg),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    ok = proc.returncode == 0 and out_jpg.is_file()
    return {
        "ok": ok,
        "path": str(out_jpg) if ok else None,
        "requested_media_sec": media_sec,
        "sha256": sha256_file(out_jpg) if ok else None,
        "stderr_tail": (proc.stderr or "")[-200:],
    }


def _scene_change_times(
    *,
    video: Path,
    start: float,
    end: float,
    threshold: float = 0.28,
    max_hits: int = 12,
) -> List[float]:
    """Local ffmpeg scene detect inside [start,end]; returns absolute media PTS."""
    ffmpeg = _ffmpeg()
    start = max(0.0, float(start))
    end = float(end)
    if end <= start + 1.0:
        return []
    dur = end - start
    # Limit CPU: cap scan length
    if dur > 240:
        start = end - 240.0
        dur = 240.0
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{dur:.3f}",
        "-i",
        str(video),
        "-filter_complex",
        f"select='gt(scene,{threshold})',showinfo",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    times: List[float] = []
    for line in (proc.stderr or "").splitlines():
        m = _SHOWINFO_PTS.search(line)
        if not m:
            continue
        # showinfo pts is relative to decoded segment start after -ss input seek ambiguity;
        # with -ss before -i, pts_time is often relative to segment. Add start.
        rel = float(m.group("pts"))
        abs_t = start + rel
        if start - 0.5 <= abs_t <= end + 0.5:
            times.append(round(abs_t, 3))
    # unique + cap
    out: List[float] = []
    for t in times:
        if not out or abs(out[-1] - t) >= 1.0:
            out.append(t)
        if len(out) >= max_hits:
            break
    return out


def _role_search_plan(
    *,
    role: str,
    score_before: Optional[List[int]],
    score_after: List[int],
    score_confirmation_sec: float,
    prev_score_sec: Optional[float],
    events: Sequence[Dict[str, Any]],
    strips: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    conf = float(score_confirmation_sec)
    prev = float(prev_score_sec) if prev_score_sec is not None else max(0.0, conf - 180.0)
    if prev >= conf:
        prev = max(0.0, conf - 120.0)

    refine_start = max(prev, conf - 45.0)
    late_start = max(prev, conf - min(180.0, max(60.0, (conf - prev) * 0.35)))

    windows: List[Dict[str, Any]] = [
        {
            "candidate_id": f"{role}_refine_tail",
            "kind": "refine_tail_before_score_confirm",
            "media_in": round(refine_start, 3),
            "media_out": round(min(conf + 5.0, conf + 8.0), 3),
            "reason": "Board confirmation is upper bound; first-live action usually in trailing 45s",
            "priority": 0,
        },
        {
            "candidate_id": f"{role}_late_third",
            "kind": "late_third_near_confirm",
            "media_in": round(late_start, 3),
            "media_out": round(conf + 3.0, 3),
            "reason": "Broader late window before score confirmation",
            "priority": 2,
        },
    ]

    # LIVE Shot events: only those near confirmation (long gaps otherwise flood early shots).
    shot_horizon = max(150.0, min(420.0, (conf - prev) * 0.2))
    live_shots: List[Dict[str, Any]] = []
    for e in events:
        t = e.get("event_time_sec")
        if t is None:
            continue
        t = float(t)
        if not (prev - 5 <= t <= conf + 5):
            continue
        et = str(e.get("event_type") or "")
        if "Shot" not in et and "shot" not in et.lower():
            continue
        if e.get("is_replay") is True or str(e.get("broadcast_phase") or "").upper() == "REPLAY":
            if conf - t <= shot_horizon:
                windows.append(
                    {
                        "candidate_id": f"{role}_replay_shot_{e.get('event_id')}",
                        "kind": "replay_shot_event",
                        "media_in": round(max(0.0, t - 8.0), 3),
                        "media_out": round(t + 12.0, 3),
                        "event_id": e.get("event_id"),
                        "reason": "Annotated REPLAY shot near confirm — negative / not first-live primary",
                        "live_or_replay": "replay",
                        "priority": 9,
                    }
                )
            continue
        if conf - t > shot_horizon:
            continue
        live_shots.append(
            {
                "candidate_id": f"{role}_live_shot_{e.get('event_id')}",
                "kind": "live_shot_event",
                "media_in": round(max(0.0, t - 12.0), 3),
                "media_out": round(min(conf + 5.0, t + 20.0), 3),
                "event_id": e.get("event_id"),
                "score_pair_at_event": e.get("score_pair"),
                "reason": (
                    f"LIVE Shot within {shot_horizon:.0f}s before score confirmation "
                    "(action candidate, not verified)"
                ),
                "live_or_replay": "live",
                "priority": 1,
                "dist_to_confirm": conf - t,
            }
        )
    live_shots.sort(key=lambda w: float(w.get("dist_to_confirm") or 1e9))
    windows.extend(live_shots[:3])

    # Predicted strips overlapping late window
    for c in strips:
        t0 = c.get("t0_sec")
        t1 = c.get("t1_sec")
        if t0 is None or t1 is None:
            continue
        t0, t1 = float(t0), float(t1)
        if t1 < late_start - 5 or t0 > conf + 10:
            continue
        last = str(c.get("last_event") or "")
        cat = str(c.get("predicted_category") or "")
        pri = 3
        if last == "goal" or cat == "outcome":
            pri = 1
        windows.append(
            {
                "candidate_id": f"{role}_strip_{c.get('strip_chain_id') or c.get('clip_id')}",
                "kind": "predicted_strip_window",
                "media_in": round(max(0.0, t0 - 2.0), 3),
                "media_out": round(min(conf + 5.0, t1 + 2.0), 3),
                "strip_chain_id": c.get("strip_chain_id"),
                "predicted_category": cat,
                "first_event": c.get("first_event"),
                "last_event": last,
                "reason": "Predicted strip overlapping search window (unverified hypothesis)",
                "priority": pri,
            }
        )

    windows.sort(key=lambda w: (int(w.get("priority") or 99), float(w["media_in"])))
    # Dedup highly overlapping windows (keep higher priority). Always keep refine_tail + live shots.
    kept: List[Dict[str, Any]] = []
    for w in windows:
        if any(
            abs(float(w["media_in"]) - float(k["media_in"])) < 3
            and abs(float(w["media_out"]) - float(k["media_out"])) < 3
            for k in kept
        ):
            continue
        kept.append(w)
        if len(kept) >= 8:
            break

    return {
        "role": role,
        "score_before": score_before,
        "score_after": score_after,
        "score_confirmation_sec": conf,
        "previous_score_observation_sec": prev,
        "note": "score_confirmation_sec is board time, NOT goal_action_sec",
        "candidate_windows": kept,
    }


def build_search_plan_from_g1(
    *,
    selected_arc: Dict[str, Any],
    events: Sequence[Dict[str, Any]],
    strips: Sequence[Dict[str, Any]],
    score_path: Sequence[Sequence[int]],
) -> Dict[str, Any]:
    """Plan only the three selected_arc roles (ignore OCR-noise / non-arc transitions)."""
    conf = selected_arc.get("score_confirmation_sec") or {}
    scores = list(score_path or [])
    # previous observation times: walk score_path media times from events timeline if present in arc
    # Use arc indices when available.
    def _prev_time_for(confirm_t: float, after_score: List[int]) -> Optional[float]:
        # Find last score observation before confirm that is not after_score
        prev_t = None
        for e in events:
            sp = e.get("score_pair")
            t = e.get("event_time_sec")
            if not sp or t is None:
                continue
            t = float(t)
            if t >= float(confirm_t) - 1e-6:
                continue
            if list(sp) == list(after_score):
                continue
            # Prefer times with board equal to score_before when known later
            prev_t = t
        return prev_t

    # Search lower bound = first confirmation of the previous score state (not last re-sighting).
    deficit_t = conf.get("deficit")
    equalizer_t = conf.get("equalizer")
    go_ahead_t = conf.get("go_ahead")
    # Earliest 0:0 (or any board before deficit) for opening search floor.
    earliest_zero = None
    for e in events:
        sp = e.get("score_pair")
        t = e.get("event_time_sec")
        if not sp or t is None:
            continue
        if list(sp) == [0, 0]:
            earliest_zero = float(t) if earliest_zero is None else min(earliest_zero, float(t))

    def _board_before(target: Optional[List[int]]) -> Optional[List[int]]:
        if not target:
            return None
        prev_board: Optional[List[int]] = None
        for s in score_path:
            cur = list(s)
            if cur == list(target):
                return prev_board
            prev_board = cur
        return prev_board

    deficit_score = list(selected_arc.get("deficit_score") or [])
    equalizer_score = list(selected_arc.get("equalizer_score") or [])
    go_ahead_score = list(selected_arc.get("go_ahead_score") or [])
    # Search floor for deficit role: prior board confirmation if known, else earliest 0:0.
    deficit_prev_board = _board_before(deficit_score)
    roles = [
        (
            "opening_deficit",
            deficit_prev_board if deficit_prev_board is not None else [0, 0],
            deficit_score,
            deficit_t,
            # Prefer time of previous board on path; fall back to earliest 0:0.
            (
                next(
                    (
                        float(e.get("event_time_sec"))
                        for e in events
                        if e.get("score_pair")
                        and list(e.get("score_pair")) == list(deficit_prev_board or [])
                        and e.get("event_time_sec") is not None
                        and deficit_t is not None
                        and float(e["event_time_sec"]) < float(deficit_t)
                    ),
                    None,
                )
                if deficit_prev_board is not None
                else earliest_zero
            )
            or earliest_zero,
        ),
        (
            "equalizer",
            deficit_score,
            equalizer_score,
            equalizer_t,
            deficit_t,
        ),
        (
            "go_ahead",
            equalizer_score,
            go_ahead_score,
            go_ahead_t,
            equalizer_t,
        ),
    ]
    plans = []
    for role, before, after, ct, prev_fixed in roles:
        if ct is None or not after:
            continue
        prev = float(prev_fixed) if prev_fixed is not None else _prev_time_for(float(ct), after)
        plans.append(
            _role_search_plan(
                role=role,
                score_before=before,
                score_after=after,
                score_confirmation_sec=float(ct),
                prev_score_sec=prev,
                events=events,
                strips=strips,
            )
        )
    return {
        "schema": "v2_g2_search_plan_v1",
        "protagonist_side": selected_arc.get("protagonist_side"),
        "protagonist_team_name": selected_arc.get("protagonist_team_name"),
        "roles": plans,
        "render_ready": False,
    }


def _enrich_with_scene_candidates(
    *,
    video: Path,
    role_plan: Dict[str, Any],
) -> Dict[str, Any]:
    conf = float(role_plan["score_confirmation_sec"])
    prev = float(role_plan.get("previous_score_observation_sec") or max(0.0, conf - 120))
    scan_start = max(prev, conf - 150.0)
    scenes = _scene_change_times(video=video, start=scan_start, end=conf, threshold=0.30, max_hits=8)
    extra = []
    for i, t in enumerate(scenes[-4:]):  # prefer late scenes
        extra.append(
            {
                "candidate_id": f"{role_plan['role']}_scene_{i}",
                "kind": "ffmpeg_scene_change",
                "media_in": round(max(0.0, t - 10.0), 3),
                "media_out": round(min(conf + 5.0, t + 15.0), 3),
                "scene_pts": t,
                "reason": "Local ffmpeg scene-change near confirmation (uncertain goal localization)",
                "priority": 4,
            }
        )
    role_plan = dict(role_plan)
    windows = list(role_plan.get("candidate_windows") or []) + extra
    windows.sort(key=lambda w: (int(w.get("priority") or 99), float(w["media_in"])))
    # Keep refine/live-shot first; allow up to 7 review candidates per role.
    role_plan["candidate_windows"] = windows[:7]
    role_plan["scene_pts_scanned"] = scenes
    return role_plan


def materialize_role_evidence(
    *,
    video: Path,
    role_plan: Dict[str, Any],
    out_dir: Path,
    identity: Dict[str, str],
    video_duration_sec: float,
) -> Dict[str, Any]:
    role = role_plan["role"]
    role_dir = out_dir / "roles" / role
    clips_dir = role_dir / "clips"
    frames_dir = role_dir / "frames"
    clips_dir.mkdir(parents=True, exist_ok=True)
    frames_dir.mkdir(parents=True, exist_ok=True)

    candidates: List[Dict[str, Any]] = []
    for w in role_plan.get("candidate_windows") or []:
        cid = str(w["candidate_id"])
        mi, mo = float(w["media_in"]), float(w["media_out"])
        # clamp
        mi = max(0.0, min(mi, video_duration_sec - 1.0))
        mo = max(mi + 0.5, min(mo, video_duration_sec))
        # Cap clip length for reviewability
        if mo - mi > 40.0:
            # keep the end (near confirmation) for refine/late; for live shot keep center
            if "shot" in cid or "scene" in cid:
                mid = 0.5 * (mi + mo)
                mi, mo = max(0.0, mid - 15.0), min(video_duration_sec, mid + 15.0)
            else:
                mi = max(mi, mo - 40.0)

        clip_path = clips_dir / f"{cid}_clip_source_continuous.mp4"
        cut = _cut_continuous_clip(video=video, media_in=mi, media_out=mo, out_mp4=clip_path)
        frame_pts = [
            mi + 0.5,
            0.5 * (mi + mo),
            max(mi + 0.5, mo - 1.0),
        ]
        frames = []
        for j, ft in enumerate(frame_pts):
            fp = frames_dir / f"{cid}_f{j}_{int(ft*1000)}.jpg"
            fr = _extract_frame(video=video, media_sec=ft, out_jpg=fp)
            frames.append(fr)

        live_flag = w.get("live_or_replay")
        if live_flag is None:
            live_flag = "unknown"
        if w.get("kind") == "replay_shot_event":
            live_flag = "replay"

        cand = {
            "candidate_id": cid,
            "role": role,
            "kind": w.get("kind"),
            "reason": w.get("reason"),
            "uncertainty": (
                "Zero-API pack: continuous source clip extracted; "
                "shot/net/first-live semantics NOT automated-verified"
            ),
            "media_in": round(mi, 3),
            "media_out": round(mo, 3),
            "source_pts": {"media_in": round(mi, 3), "media_out": round(mo, 3)},
            "score_before": role_plan.get("score_before"),
            "score_after": role_plan.get("score_after"),
            "score_confirmation_sec": role_plan.get("score_confirmation_sec"),
            "goal_action_sec": None,
            "shot_sec": None,
            "net_sec": None,
            "event_id": w.get("event_id"),
            "strip_chain_id": w.get("strip_chain_id"),
            "live_or_replay": live_flag,
            "clip_path": cut.get("path") if cut.get("ok") else None,
            "clip_export": cut,
            "frames": frames,
            "frame_paths": [f["path"] for f in frames if f.get("ok")],
            "identity": dict(identity),
            "verification_status": "unresolved",
            "semantic_verification_class": NOT_VERIFIED,
            "human_review_status": PENDING,
            "checklist": {
                "shot_action_seen": "pending_human",
                "ball_in_net_seen": "pending_human",
                "celebration_seen": "pending_human",
                "live_not_replay": "pending_human" if live_flag != "replay" else "likely_replay",
                "scoreboard_confirm_after": "pending_human",
                "continuous_clip_no_stitch": bool(cut.get("ok")),
            },
            "render_ready": False,
        }
        candidates.append(cand)

    # Prefer primary: lowest priority kinds first already ordered; mark primary_review
    primary = next(
        (c for c in candidates if c.get("kind") in ("refine_tail_before_score_confirm", "live_shot_event")),
        candidates[0] if candidates else None,
    )
    return {
        "role": role,
        "score_before": role_plan.get("score_before"),
        "score_after": role_plan.get("score_after"),
        "score_confirmation_sec": role_plan.get("score_confirmation_sec"),
        "n_candidates": len(candidates),
        "primary_candidate_id": (primary or {}).get("candidate_id"),
        "candidates": candidates,
        "verification_status": "unresolved",
        "semantic_verification_class": NOT_VERIFIED,
        "human_review_status": PENDING,
        "render_ready": False,
    }


def run_g2_evidence_pack(
    *,
    match_id: str,
    video: Path,
    events: Path,
    g1_dir: Path,
    out_dir: Path,
    input_source: str = "human_corrected",
) -> Dict[str, Any]:
    t0 = time.time()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    g1_dir = Path(g1_dir)

    gate = reject_forbidden_input_path(Path(events))
    if not gate.get("ok"):
        report = {"status": "aborted_forbidden_input", "gate": gate, "render_ready": False}
        write_json(out_dir / "cli_report.json", report)
        return report

    raw = json.loads(Path(events).read_text(encoding="utf-8"))
    pg = reject_forbidden_payload(raw if isinstance(raw, dict) else {})
    if not pg.get("ok"):
        report = {"status": "aborted_forbidden_payload", "gate": pg, "render_ready": False}
        write_json(out_dir / "cli_report.json", report)
        return report

    mid = assert_match_id_consistent(cli_match_id=match_id, events_match_id=str(raw.get("match_id") or ""))
    if not mid.get("ok"):
        report = {"status": "aborted_match_id_mismatch", "gate": mid, "render_ready": False}
        write_json(out_dir / "cli_report.json", report)
        return report

    # Load G1 artifacts
    selected_pack = json.loads((g1_dir / "selected_arc.json").read_text(encoding="utf-8"))
    selected = selected_pack.get("selected_arc") or {}
    if not selected:
        report = {"status": "aborted_no_selected_arc", "render_ready": False}
        write_json(out_dir / "cli_report.json", report)
        return report

    g1_prov = json.loads((g1_dir / "provenance.json").read_text(encoding="utf-8"))
    events_sha = sha256_file(Path(events))
    hash_cache = out_dir / "video_sha256.txt"
    if hash_cache.is_file():
        video_sha = hash_cache.read_text(encoding="utf-8").strip().split()[0]
        video_hash_source = "cached"
    else:
        # Prefer G1 hash if same video path
        if str(g1_prov.get("video")) == str(video) and g1_prov.get("video_sha256"):
            video_sha = str(g1_prov["video_sha256"])
            video_hash_source = "reused_g1"
        else:
            video_sha = sha256_file(Path(video))
            video_hash_source = "computed"
        hash_cache.write_text(video_sha + "\n", encoding="utf-8")

    if events_sha != str(g1_prov.get("events_sha256") or ""):
        # Allow if equal content path changed but warn — still bind to current
        pass

    strip_prov = (g1_prov.get("strip_provenance") or {})
    if isinstance(strip_prov, dict):
        strip_token = str(strip_prov.get("strip_provenance") or "")
    else:
        strip_token = str(strip_prov)
    identity = {
        "match_id": match_id,
        "video_sha256": video_sha,
        "events_sha256": events_sha,
        "strip_provenance": strip_token,
    }
    write_json(
        out_dir / "preflight_identity.json",
        {
            "identity": identity,
            "video": str(video),
            "events": str(events),
            "g1_dir": str(g1_dir),
            "video_hash_source": video_hash_source,
            "g1_strip_provenance": strip_prov,
            "forbidden_inputs_used": [],
            "render_ready": False,
        },
    )

    event_bundle = load_events_json(Path(events), input_source=input_source)
    strips = []
    strip_path = g1_dir / "predicted_strip_chains.json"
    if strip_path.is_file():
        strips = list(json.loads(strip_path.read_text(encoding="utf-8")).get("chains") or [])

    score_path: List[Sequence[int]] = []
    sp = g1_dir / "score_path.json"
    if sp.is_file():
        raw_tl = json.loads(sp.read_text(encoding="utf-8")).get("timeline") or []
        for x in raw_tl:
            if isinstance(x, dict) and x.get("score") is not None:
                score_path.append(list(x["score"]))
            elif isinstance(x, (list, tuple)) and len(x) == 2:
                score_path.append(list(x))

    plan = build_search_plan_from_g1(
        selected_arc=selected,
        events=list(event_bundle.get("events") or []),
        strips=strips,
        score_path=score_path,
    )
    video_duration = _ffprobe_duration(Path(video))

    # Scene enrich + materialize
    role_results = []
    index_rows = []
    for role_plan in plan.get("roles") or []:
        enriched = _enrich_with_scene_candidates(video=Path(video), role_plan=role_plan)
        result = materialize_role_evidence(
            video=Path(video),
            role_plan=enriched,
            out_dir=out_dir,
            identity=identity,
            video_duration_sec=video_duration,
        )
        write_json(out_dir / "roles" / result["role"] / "role_evidence.json", result)
        role_results.append(result)
        for c in result.get("candidates") or []:
            index_rows.append(
                {
                    "role": result["role"],
                    "candidate_id": c["candidate_id"],
                    "kind": c.get("kind"),
                    "media_in": c.get("media_in"),
                    "media_out": c.get("media_out"),
                    "clip_path": c.get("clip_path"),
                    "n_frames": len(c.get("frame_paths") or []),
                    "live_or_replay": c.get("live_or_replay"),
                    "verification_status": c.get("verification_status"),
                    "human_review_status": c.get("human_review_status"),
                    "watchable": bool(c.get("clip_path")),
                }
            )

    write_json(out_dir / "search_plan.json", plan)
    write_json(
        out_dir / "candidate_evidence_index.json",
        {
            "schema": "v2_g2_candidate_evidence_index_v1",
            "match_id": match_id,
            "n_rows": len(index_rows),
            "rows": index_rows,
            "render_ready": False,
        },
    )

    # Live/replay audit from annotations near primary windows
    live_audit = {"schema": "v2_g2_live_replay_audit_v1", "roles": [], "render_ready": False}
    for rr in role_results:
        conf = float(rr.get("score_confirmation_sec") or 0)
        nearby = []
        for e in event_bundle.get("events") or []:
            t = e.get("event_time_sec")
            if t is None:
                continue
            t = float(t)
            if abs(t - conf) > 90 and not (conf - 120 <= t <= conf + 10):
                continue
            nearby.append(
                {
                    "event_id": e.get("event_id"),
                    "event_type": e.get("event_type"),
                    "event_time_sec": t,
                    "is_replay": e.get("is_replay"),
                    "broadcast_phase": e.get("broadcast_phase"),
                    "score_pair": e.get("score_pair"),
                }
            )
        live_audit["roles"].append(
            {
                "role": rr["role"],
                "score_confirmation_sec": conf,
                "nearby_events": nearby[:40],
                "note": "Annotation flags only; visual Live-Only still needs human/VLM",
            }
        )
    write_json(out_dir / "live_replay_audit.json", live_audit)

    # Semantic verification: NOT_VERIFIED in zero-API G2
    semantic = {
        "schema": "v2_g2_video_semantic_verification_v1",
        "status": NOT_VERIFIED,
        "automated_video_verified_roles": [],
        "human_video_reviewed_roles": [],
        "pending_human_video_review_roles": [rr["role"] for rr in role_results],
        "unresolved_roles": [rr["role"] for rr in role_results],
        "n_video_verified": 0,
        "api_calls": 0,
        "note": (
            "G2 zero-API run produced continuous clips + frames only. "
            "No automated semantic verifier executed; do not treat as verified_first_live."
        ),
        "render_ready": False,
    }
    write_json(out_dir / "video_semantic_verification.json", semantic)

    n_watchable = sum(1 for r in index_rows if r.get("watchable"))
    roles_ready = all(rr.get("n_candidates", 0) > 0 and any(c.get("clip_path") for c in rr.get("candidates") or []) for rr in role_results)
    gate_decision = {
        "G2_A_EVIDENCE_PACK_READY" if "阿联酋" in match_id or "uae" in match_id.lower() or "阿曼" in match_id else "G2_EVIDENCE_PACK_READY": bool(
            roles_ready and len(role_results) == 3
        ),
        "video_verified": False,
        "unresolved_count": 3 if roles_ready else len(role_results),
        "stop_for_human_review": True,
        "render_ready": False,
    }
    # clearer keys
    gate_decision = {
        "evidence_pack_ready": bool(roles_ready and len(role_results) >= 3),
        "label_if_a": "G2_A_EVIDENCE_PACK_READY" if roles_ready and len(role_results) >= 3 else "G2_A_INCOMPLETE",
        "video_verified": False,
        "n_roles_with_watchable_clips": sum(
            1 for rr in role_results if any(c.get("clip_path") for c in rr.get("candidates") or [])
        ),
        "unresolved_core_roles": [rr["role"] for rr in role_results],
        "stop_for_human_review": True,
        "render_ready": False,
    }
    write_json(out_dir / "gate_decision.json", gate_decision)

    report = {
        "schema": "v2_g2_cli_report_v1",
        "status": "ok_evidence_pack" if gate_decision["evidence_pack_ready"] else "partial_evidence_pack",
        "match_id": match_id,
        "protagonist_side": selected.get("protagonist_side"),
        "protagonist_team_name": selected.get("protagonist_team_name"),
        "n_roles": len(role_results),
        "n_watchable_clips": n_watchable,
        "n_video_verified": 0,
        "n_unresolved": len(role_results),
        "semantic_status": NOT_VERIFIED,
        "gate": gate_decision,
        "identity": identity,
        "out_dir": str(out_dir),
        "elapsed_sec": round(time.time() - t0, 3),
        "api_calls": 0,
        "api_cost_usd": 0.0,
        "render_ready": False,
    }
    write_json(out_dir / "cli_report.json", report)
    return report
