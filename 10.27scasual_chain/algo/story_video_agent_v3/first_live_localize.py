"""V3-P3 first-live localization + semantic evidence classification (zero paid API).

Distinguishes candidate extraction success from goal-action verification.
Score bounds only narrow search; they never substitute for shot/net time.
Never hardcodes match-specific PTS into ranking — clues are runtime inputs.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from story_video_agent.scoreboard_ocr import detect_and_read_scoreboard
from story_video_agent.v2_g2_first_live_retrieval import (
    collect_event_replay_overlaps,
    live_shots_before_confirm,
)
from story_video_agent.v2_video_evidence_gate import NOT_VERIFIED

from .pipeline import dump
from .v1_causal_adapter import score_pair_from_raw_event

SEMANTIC_LABELS = (
    "pre_goal_only",
    "shot_only",
    "post_goal_celebration",
    "replay",
    "wrong_attacking_side",
    "possible_first_live",
    "verified_first_live",
    "unresolved",
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not found")
    return exe


def cut_accurate_clip(
    *,
    video: Path,
    media_in: float,
    media_out: float,
    out_mp4: Path,
    max_dur: float = 40.0,
) -> Dict[str, Any]:
    """Hybrid seek + reencode (not stream-copy) for frame-accurate continuous clip."""
    ffmpeg = _ffmpeg()
    mi = max(0.0, float(media_in))
    mo = float(media_out)
    if mo <= mi + 0.2:
        return {"ok": False, "reason": "empty_window"}
    dur = min(float(max_dur), mo - mi)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    pad = min(15.0, mi)
    coarse = max(0.0, mi - pad)
    fine = mi - coarse
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{coarse:.3f}", "-i", str(video),
        "-ss", f"{fine:.3f}", "-t", f"{dur:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart",
        str(out_mp4),
    ]
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    ok = proc.returncode == 0 and out_mp4.is_file() and out_mp4.stat().st_size > 1000
    return {
        "ok": ok,
        "path": str(out_mp4),
        "media_in": mi,
        "media_out": mi + dur,
        "duration_sec": round(dur, 3),
        "sha256": _sha256(out_mp4) if ok else None,
        "bytes": out_mp4.stat().st_size if out_mp4.is_file() else 0,
        "continuous_source": True,
        "stitched": False,
        "accurate_decode": True,
        "stream_copy": False,
        "elapsed_sec": round(time.time() - t0, 3),
        "stderr_tail": (proc.stderr or "")[-300:],
        "reason": None if ok else f"ffmpeg_fail:{proc.returncode}",
    }


def extract_frame_accurate(video: Path, media_sec: float, out_jpg: Path) -> Dict[str, Any]:
    ffmpeg = _ffmpeg()
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    t = max(0.0, float(media_sec))
    pad = min(10.0, t)
    coarse = max(0.0, t - pad)
    fine = t - coarse
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{coarse:.3f}", "-i", str(video),
        "-ss", f"{fine:.3f}", "-frames:v", "1", "-q:v", "2", str(out_jpg),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    ok = proc.returncode == 0 and out_jpg.is_file()
    return {
        "ok": ok,
        "path": str(out_jpg),
        "media_sec": t,
        "sha256": _sha256(out_jpg) if ok else None,
        "accurate_decode": True,
    }


def _score_tuple(val: Any) -> Optional[Tuple[int, int]]:
    if isinstance(val, (list, tuple)) and len(val) >= 2:
        try:
            return int(val[0]), int(val[1])
        except (TypeError, ValueError):
            return None
    if isinstance(val, str) and ":" in val:
        a, b = val.split(":", 1)
        try:
            return int(a.strip()), int(b.strip())
        except ValueError:
            return None
    return None


def load_events_rows(events_path: Path) -> List[Dict[str, Any]]:
    data = json.loads(Path(events_path).read_text(encoding="utf-8"))
    rows = data.get("events") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    out = []
    for e in rows:
        mt = e.get("media_time") or {}
        t = mt.get("event_time_sec")
        if t is None:
            t = mt.get("start_time_sec")
        if t is None:
            continue
        vc = e.get("video_context") or {}
        # Reuse the canonical raw-event score decoder also used by Goal Recovery.
        # Some matches carry scores.score_recognition rather than attributes.
        sp = score_pair_from_raw_event(e)
        out.append({
            "event_id": e.get("event_id"),
            "event_type": e.get("event_type"),
            "event_time_sec": float(t),
            "media_start_sec": float(mt.get("start_time_sec") if mt.get("start_time_sec") is not None else t),
            "media_end_sec": float(mt.get("end_time_sec") if mt.get("end_time_sec") is not None else t),
            "is_replay": bool(vc.get("is_replay")) or str(vc.get("broadcast_phase") or "").upper() == "REPLAY",
            "broadcast_phase": vc.get("broadcast_phase"),
            "score_pair": list(sp) if sp else None,
        })
    return out


def covered_intervals(clues: Sequence[Dict[str, Any]]) -> List[Tuple[float, float]]:
    spans = []
    for c in clues:
        if c.get("media_in") is None or c.get("media_out") is None:
            continue
        spans.append((float(c["media_in"]), float(c["media_out"])))
    spans.sort()
    merged: List[Tuple[float, float]] = []
    for a, b in spans:
        if not merged or a > merged[-1][1] + 1.0:
            merged.append((a, b))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
    return merged


def uncovered_subintervals(
    search_in: float, search_out: float, covered: Sequence[Tuple[float, float]]
) -> List[Tuple[float, float]]:
    gaps: List[Tuple[float, float]] = []
    cur = float(search_in)
    for a, b in covered:
        if b <= cur:
            continue
        if a > cur + 0.5:
            gaps.append((cur, min(float(search_out), a)))
        cur = max(cur, b)
        if cur >= search_out:
            break
    if cur + 0.5 < search_out:
        gaps.append((cur, float(search_out)))
    return [(a, b) for a, b in gaps if b - a >= 2.0]


def densify_score_observations(
    *,
    video: Path,
    start_sec: float,
    end_sec: float,
    step_sec: float = 2.0,
    out_dir: Path,
    budget_frames: int = 80,
) -> List[Dict[str, Any]]:
    """Sparse OCR score samples. Failures are recorded; never invent scores."""
    import cv2

    out_dir.mkdir(parents=True, exist_ok=True)
    start = max(0.0, float(start_sec))
    end = float(end_sec)
    if end <= start:
        return []
    times = []
    t = start
    while t <= end + 1e-6 and len(times) < budget_frames:
        times.append(round(t, 3))
        t += float(step_sec)
    rows = []
    for i, ts in enumerate(times):
        fp = out_dir / f"ocr_{i:03d}_{int(ts * 1000)}.jpg"
        fr = extract_frame_accurate(video, ts, fp)
        if not fr.get("ok"):
            rows.append({"media_sec": ts, "status": "frame_fail", "score_tuple": None})
            continue
        img = cv2.imread(str(fp))
        if img is None:
            rows.append({"media_sec": ts, "status": "imread_fail", "score_tuple": None})
            continue
        det = detect_and_read_scoreboard(img)
        st = det.get("score_tuple")
        tup = None
        if isinstance(st, (list, tuple)) and len(st) >= 2:
            tup = [int(st[0]), int(st[1])]
        rows.append({
            "media_sec": ts,
            "status": det.get("status"),
            "score": det.get("score"),
            "score_tuple": tup,
            "frame_path": str(fp),
            "source": "tesseract_scoreboard_ocr",
        })
    return rows


def merge_score_bounds(
    *,
    score_before: Optional[Sequence[int]],
    score_after: Optional[Sequence[int]],
    ocr_rows: Sequence[Dict[str, Any]],
    human_obs: Sequence[Dict[str, Any]],
    event_rows: Sequence[Dict[str, Any]],
    confirm_sec: Optional[float],
) -> Dict[str, Any]:
    """Build last_before / first_after from OCR + optional human obs + events."""
    before = list(score_before) if score_before is not None else None
    after = list(score_after) if score_after is not None else None
    obs: List[Dict[str, Any]] = []
    for r in ocr_rows:
        if r.get("score_tuple") and r.get("status") in {"ok", "weak"}:
            obs.append({
                "media_sec": float(r["media_sec"]),
                "score_tuple": list(r["score_tuple"]),
                "source": "ocr",
                "status": r.get("status"),
            })
    for r in human_obs:
        st = _score_tuple(r.get("score_tuple") or r.get("score"))
        if st is None or r.get("media_sec") is None:
            continue
        obs.append({
            "media_sec": float(r["media_sec"]),
            "score_tuple": list(st),
            "source": "human_score_observation",
            "note": r.get("note"),
            "status": "human",
        })
    for e in event_rows:
        if e.get("score_pair") and e.get("event_time_sec") is not None:
            obs.append({
                "media_sec": float(e["event_time_sec"]),
                "score_tuple": list(e["score_pair"]),
                "source": "event_score_recognition",
                "event_id": e.get("event_id"),
                "status": "event",
            })
    obs.sort(key=lambda x: x["media_sec"])

    last_before = None
    first_after = None
    for o in obs:
        if before is not None and o["score_tuple"] == before:
            last_before = o
        if after is not None and o["score_tuple"] == after and first_after is None:
            first_after = o
            # keep scanning last_before before this
    # Recompute last_before strictly before first_after if both exist
    if first_after is not None and before is not None:
        prior = [o for o in obs
                 if o["score_tuple"] == before and o["media_sec"] < float(first_after["media_sec"])]
        if prior:
            last_before = prior[-1]

    unknown_in = float(last_before["media_sec"]) if last_before else None
    unknown_out = float(first_after["media_sec"]) if first_after else (
        float(confirm_sec) if confirm_sec is not None else None
    )
    return {
        "score_before": before,
        "score_after": after,
        "last_before_obs": last_before,
        "first_after_obs": first_after,
        "unknown_interval": (
            {"media_in": unknown_in, "media_out": unknown_out}
            if unknown_in is not None and unknown_out is not None and unknown_out > unknown_in
            else None
        ),
        "n_observations": len(obs),
        "observations": obs,
        "note": (
            "Score bounds constrain search only; not goal_action_sec. "
            "Board lag / OCR noise / confirm delay must not be treated as exact goal time."
        ),
    }


def propose_localization_candidates(
    *,
    role: str,
    confirm_sec: float,
    score_before: Optional[Sequence[int]],
    score_after: Optional[Sequence[int]],
    historical_clues: Sequence[Dict[str, Any]],
    events: Sequence[Dict[str, Any]],
    score_bounds: Dict[str, Any],
    max_candidates: int = 5,
    max_video_read_sec: float = 120.0,
    lookback_sec: float = 120.0,
) -> Dict[str, Any]:
    """Budgeted candidates preferring historically uncovered intervals near score flip."""
    conf = float(confirm_sec)
    covered = covered_intervals(historical_clues)
    search_in = max(0.0, conf - float(lookback_sec))
    # Prefer unknown score interval when available
    unk = score_bounds.get("unknown_interval") or {}
    if unk.get("media_in") is not None:
        search_in = min(search_in, max(0.0, float(unk["media_in"]) - 15.0))
    search_out = conf
    if unk.get("media_out") is not None:
        search_out = min(conf, float(unk["media_out"]) + 5.0)

    gaps = uncovered_subintervals(search_in, search_out, covered)
    replays = collect_event_replay_overlaps(events, media_in=search_in, media_out=search_out + 30)
    shots = live_shots_before_confirm(
        events,
        prev_sec=search_in,
        confirm_sec=conf,
        score_before=list(score_before) if score_before is not None else None,
        score_after=list(score_after) if score_after is not None else None,
    )

    cands: List[Dict[str, Any]] = []

    def _add(mi: float, mo: float, origin: str, priority: float, **extra: Any) -> None:
        if mo <= mi + 1.0:
            return
        # Skip pure replay-overlapping windows when labeled by events
        for r in replays:
            rs, re = float(r["start_time_sec"]), float(r["end_time_sec"])
            if mi >= rs - 0.5 and mo <= re + 0.5:
                cands.append({
                    "media_in": round(mi, 3),
                    "media_out": round(mo, 3),
                    "origin": origin,
                    "priority": priority - 1000,
                    "rejected_prefilter": True,
                    "reject_reason": "fully_inside_event_replay",
                    **extra,
                })
                return
        cands.append({
            "media_in": round(mi, 3),
            "media_out": round(min(mo, mi + 35.0), 3),
            "origin": origin,
            "priority": priority,
            "rejected_prefilter": False,
            **extra,
        })

    # 1) Uncovered gaps (highest) — split into ≤25s windows ending before confirm
    for gi, (ga, gb) in enumerate(gaps):
        # Prefer the late part of gap (closer to score flip) but not confirm hug alone
        span = gb - ga
        if span <= 25:
            _add(ga, gb, "uncovered_gap", 1000 - gi * 10 - (conf - gb) * 0.01, gap_index=gi)
        else:
            # take last 25s of gap + first 20s if budget
            _add(max(ga, gb - 25.0), gb, "uncovered_gap_tail", 1000 - gi * 10, gap_index=gi)
            if gb - ga > 40:
                _add(ga, ga + 20.0, "uncovered_gap_head", 900 - gi * 10, gap_index=gi)

    # 2) Unknown score interval dense core (last_before → first_after)
    if unk.get("media_in") is not None and unk.get("media_out") is not None:
        ui, uo = float(unk["media_in"]), float(unk["media_out"])
        # Expand slightly before last_before for pre-goal LIVE context
        _add(max(0.0, ui - 8.0), min(uo + 2.0, ui + 30.0), "score_unknown_core", 1100,
             bound_source="score_bounds")

    # 3) LIVE shots (if any) — rare for B opening due to sparse events
    for s in shots[:3]:
        st = float(s["event_time_sec"])
        _add(max(0.0, st - 6.0), min(conf - 1.0, st + 8.0), "live_shot_event", 800,
             shot_event_id=s.get("event_id"), shot_sec_hint=st)

    # 4) Historical clues — lower priority so we do not only re-cut the same window
    for i, c in enumerate(historical_clues[:3]):
        _add(float(c["media_in"]), float(c["media_out"]), "historical_clue_recheck",
             400 - i * 20, candidate_id=c.get("candidate_id"),
             note="Recheck only after uncovered gaps; densify required")

    # 5) Pre-confirm blocks that are NOT identical to covered historical spans
    for i, end in enumerate([conf - 5.0, conf - 45.0, conf - 85.0]):
        if end <= 20:
            continue
        start = max(0.0, end - 30.0)
        # demote if largely covered
        covered_frac = 0.0
        for a, b in covered:
            overlap = max(0.0, min(b, end) - max(a, start))
            covered_frac += overlap / max(1e-6, end - start)
        pri = 350 - i * 30 - covered_frac * 200
        _add(start, end, "pre_confirm_search_block", pri, block_index=i,
             historical_cover_frac=round(covered_frac, 3))

    # Rank & budget
    cands.sort(key=lambda c: (-float(c["priority"]), float(c["media_in"])))
    selected: List[Dict[str, Any]] = []
    budget = 0.0
    seen = set()
    for c in cands:
        if c.get("rejected_prefilter"):
            continue
        key = (round(c["media_in"], 1), round(c["media_out"], 1))
        if key in seen:
            continue
        # Avoid near-duplicate of already selected
        dup = False
        for s in selected:
            if abs(float(s["media_in"]) - float(c["media_in"])) < 3.0 and abs(
                float(s["media_out"]) - float(c["media_out"])
            ) < 3.0:
                dup = True
                break
        if dup:
            continue
        dur = float(c["media_out"]) - float(c["media_in"])
        if budget + dur > max_video_read_sec and selected:
            continue
        seen.add(key)
        budget += dur
        c["candidate_id"] = c.get("candidate_id") or f"{role}_{c['origin']}_{int(c['media_in'])}"
        selected.append(c)
        if len(selected) >= max_candidates:
            break

    return {
        "role": role,
        "search_in": round(search_in, 3),
        "search_out": round(search_out, 3),
        "covered_historical": [{"media_in": a, "media_out": b} for a, b in covered],
        "uncovered_gaps": [{"media_in": a, "media_out": b} for a, b in gaps],
        "n_replay_event_spans": len(replays),
        "n_live_shots": len(shots),
        "candidates": selected,
        "rejected_or_demoted": [c for c in cands if c.get("rejected_prefilter")],
        "planned_video_read_sec": round(budget, 3),
        "constraints": {
            "live_only": True,
            "reject_replay": True,
            "no_score_confirm_as_goal_action": True,
            "prefer_uncovered_over_historical_recut": True,
            "max_candidates": max_candidates,
            "max_video_read_sec": max_video_read_sec,
        },
    }


def classify_semantic_label(
    *,
    media_in: float,
    media_out: float,
    score_bounds: Dict[str, Any],
    events: Sequence[Dict[str, Any]],
    frame_notes: Optional[Dict[str, Any]] = None,
    automated_semantic_log: Optional[Dict[str, Any]] = None,
    human_review: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Rule+evidence classifier. Never invents verified_first_live without real semantic proof."""
    notes = dict(frame_notes or {})
    last_b = (score_bounds.get("last_before_obs") or {}).get("media_sec")
    first_a = (score_bounds.get("first_after_obs") or {}).get("media_sec")
    mid = 0.5 * (float(media_in) + float(media_out))

    # Event replay overlap
    replays = collect_event_replay_overlaps(events, media_in=media_in, media_out=media_out)
    if replays and all(
        float(r["start_time_sec"]) <= media_in + 1 and float(r["end_time_sec"]) >= media_out - 1
        for r in replays
    ):
        return {
            "semantic_label": "replay",
            "verification_status": "unresolved",
            "agent_auto_verified": False,
            "semantic_verification_class": NOT_VERIFIED,
            "reason": "window_inside_event_replay",
            "evidence_gaps": ["first_live_unconfirmed", "replay_window"],
        }

    # Explicit wrong side from notes
    if notes.get("wrong_attacking_side") is True:
        return {
            "semantic_label": "wrong_attacking_side",
            "verification_status": "unresolved",
            "agent_auto_verified": False,
            "semantic_verification_class": NOT_VERIFIED,
            "reason": "attacking_side_mismatch",
            "evidence_gaps": ["attacking_team_unconfirmed"],
        }

    # Automated semantic log path (local model / offline log) — rare in P3
    if automated_semantic_log and automated_semantic_log.get("verified_first_live"):
        if all(automated_semantic_log.get(k) for k in (
            "observed_shot", "observed_net", "live", "attacking_team_match", "continuous"
        )):
            return {
                "semantic_label": "verified_first_live",
                "verification_status": "verified_first_live",
                "agent_auto_verified": True,
                "semantic_verification_class": "automated_video_verified",
                "reason": "automated_semantic_log",
                "observed_shot": True,
                "observed_net": True,
                "first_live_visual_ok": True,
                "attacking_team_match": True,
                "claims_continuous_live": True,
                "live_or_replay": "live",
                "shot_sec": automated_semantic_log.get("shot_sec"),
                "net_sec": automated_semantic_log.get("net_sec"),
                "evidence_gaps": [],
            }

    # Human review is a separate evidence type — does not become agent_auto_verified
    if human_review and human_review.get("conclusion_label") in SEMANTIC_LABELS:
        label = human_review["conclusion_label"]
        human_ok = label in {"possible_first_live", "verified_first_live"}
        return {
            "semantic_label": label,
            "verification_status": (
                "verified_first_live" if label == "verified_first_live" else "unresolved"
            ),
            "agent_auto_verified": False,
            "human_video_supported": True,
            "semantic_verification_class": (
                "human_video_reviewed" if label == "verified_first_live" else NOT_VERIFIED
            ),
            "reason": "human_review_record",
            "observed_shot": bool(human_review.get("observed_shot")),
            "observed_net": bool(human_review.get("observed_net")),
            "first_live_visual_ok": bool(human_review.get("first_live_visual_ok")),
            "attacking_team_match": bool(human_review.get("attacking_team_match")),
            "claims_continuous_live": bool(human_review.get("claims_continuous_live", True)),
            "live_or_replay": human_review.get("live_or_replay") or (
                "live" if human_ok else "unknown"
            ),
            "shot_sec": human_review.get("shot_sec"),
            "net_sec": human_review.get("net_sec"),
            "evidence_gaps": list(human_review.get("evidence_gaps") or []),
            "human_review_record": human_review,
        }

    # Heuristic placement relative to score bounds (not verification)
    if first_a is not None and media_in >= float(first_a) - 0.5:
        if notes.get("celebration_like"):
            return {
                "semantic_label": "post_goal_celebration",
                "verification_status": "unresolved",
                "agent_auto_verified": False,
                "semantic_verification_class": NOT_VERIFIED,
                "reason": "window_after_first_after_score_obs",
                "evidence_gaps": ["observed_shot_unconfirmed", "observed_net_unconfirmed",
                                 "first_live_unconfirmed"],
            }
        # Behind-goal / slow-mo after board update → likely replay of action
        if notes.get("behind_goal_net_view") or notes.get("suspected_replay"):
            return {
                "semantic_label": "replay",
                "verification_status": "unresolved",
                "agent_auto_verified": False,
                "semantic_verification_class": NOT_VERIFIED,
                "reason": "post_score_action_view_likely_replay",
                "evidence_gaps": ["first_live_unconfirmed", "net_seen_only_in_replay_risk"],
                "net_seen_only_in_replay": True,
            }

    if last_b is not None and media_out <= float(last_b) + 0.5 and not notes.get("shot_like"):
        return {
            "semantic_label": "pre_goal_only",
            "verification_status": "unresolved",
            "agent_auto_verified": False,
            "semantic_verification_class": NOT_VERIFIED,
            "reason": "window_ends_at_or_before_last_before_score",
            "evidence_gaps": ["observed_shot_unconfirmed", "observed_net_unconfirmed"],
        }

    if notes.get("shot_like") and not notes.get("net_like"):
        return {
            "semantic_label": "shot_only",
            "verification_status": "unresolved",
            "agent_auto_verified": False,
            "semantic_verification_class": NOT_VERIFIED,
            "reason": "shot_cue_without_net_proof",
            "evidence_gaps": ["observed_net_unconfirmed", "first_live_unconfirmed"],
        }

    # Inside unknown interval with action+celebration cues → possible, not verified
    if (
        last_b is not None and first_a is not None
        and float(last_b) - 10 <= mid <= float(first_a) + 5
        and (notes.get("box_scramble") or notes.get("celebration_like") or notes.get("shot_like"))
    ):
        return {
            "semantic_label": "possible_first_live",
            "verification_status": "unresolved",
            "agent_auto_verified": False,
            "semantic_verification_class": NOT_VERIFIED,
            "reason": "inside_score_unknown_interval_with_action_cues_no_local_vlm",
            "live_or_replay": "live",
            "claims_continuous_live": True,
            "observed_shot": False,
            "observed_net": False,
            "first_live_visual_ok": False,
            "attacking_team_match": bool(notes.get("attacking_team_match")),
            "evidence_gaps": [
                "observed_shot_unconfirmed",
                "observed_net_unconfirmed",
                "no_reliable_local_video_semantic_model",
                "cannot_agent_auto_verify",
            ],
        }

    return {
        "semantic_label": "unresolved",
        "verification_status": "unresolved",
        "agent_auto_verified": False,
        "semantic_verification_class": NOT_VERIFIED,
        "reason": "insufficient_signals",
        "evidence_gaps": [
            "observed_shot_unconfirmed",
            "observed_net_unconfirmed",
            "first_live_unconfirmed",
            "attacking_team_unconfirmed",
        ],
    }


def audit_localized_candidate(
    *,
    video: Path,
    role: str,
    window: Dict[str, Any],
    out_dir: Path,
    score_before: Optional[List[int]],
    score_after: Optional[List[int]],
    score_confirmation_sec: Optional[float],
    score_bounds: Dict[str, Any],
    events: Sequence[Dict[str, Any]],
    frame_notes: Optional[Dict[str, Any]] = None,
    human_review: Optional[Dict[str, Any]] = None,
    automated_semantic_log: Optional[Dict[str, Any]] = None,
    dense_fps: float = 1.0,
    max_dense_frames: int = 24,
) -> Dict[str, Any]:
    role_dir = out_dir / "roles" / role
    clips = role_dir / "clips"
    frames = role_dir / "frames"
    dense = role_dir / "dense_frames"
    cid = str(window.get("candidate_id") or f"{role}_{window.get('origin')}_{int(window['media_in'])}")
    cut = cut_accurate_clip(
        video=video,
        media_in=float(window["media_in"]),
        media_out=float(window["media_out"]),
        out_mp4=clips / f"{cid}_continuous_accurate.mp4",
    )
    frame_rows = []
    dense_rows = []
    if cut.get("ok"):
        mi, mo = float(cut["media_in"]), float(cut["media_out"])
        sample_ts = [mi + 1.0, 0.5 * (mi + mo), max(mi + 1.0, mo - 1.5)]
        for j, t in enumerate(sample_ts):
            frame_rows.append(extract_frame_accurate(video, t, frames / f"{cid}_f{j}_{int(t*1000)}.jpg"))
        # Dense continuity strip from the accurate clip (fast) rather than N source seeks
        dense.mkdir(parents=True, exist_ok=True)
        span = max(0.5, mo - mi)
        n = min(int(max_dense_frames), max(6, int(span * float(dense_fps)) + 1))
        cmd = [
            _ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(cut["path"]),
            "-vf", f"fps={dense_fps},scale=960:-2",
            "-frames:v", str(n),
            str(dense / f"{cid}_d_%03d.jpg"),
        ]
        subprocess.run(cmd, capture_output=True, text=True)
        for fp in sorted(dense.glob(f"{cid}_d_*.jpg")):
            dense_rows.append({
                "ok": True,
                "path": str(fp),
                "sha256": _sha256(fp),
                "from_accurate_clip": True,
            })

    clf = classify_semantic_label(
        media_in=float(window["media_in"]),
        media_out=float(window["media_out"]),
        score_bounds=score_bounds,
        events=events,
        frame_notes=frame_notes,
        automated_semantic_log=automated_semantic_log,
        human_review=human_review,
    )
    return {
        "role": role,
        "candidate_id": cid,
        "media_in": window.get("media_in"),
        "media_out": window.get("media_out"),
        "origin": window.get("origin"),
        "priority": window.get("priority"),
        "source_video": str(video),
        "clip_export": cut,
        "clip_path": cut.get("path") if cut.get("ok") else None,
        "frames": frame_rows,
        "frame_paths": [f["path"] for f in frame_rows if f.get("ok")],
        "dense_frame_paths": [f["path"] for f in dense_rows if f.get("ok")],
        "n_dense_frames": len([f for f in dense_rows if f.get("ok")]),
        "score_before": score_before,
        "score_after": score_after,
        "score_confirmation_sec": score_confirmation_sec,
        "goal_action_sec": clf.get("net_sec") or clf.get("shot_sec"),
        "shot_sec": clf.get("shot_sec"),
        "net_sec": clf.get("net_sec"),
        "observed_shot": bool(clf.get("observed_shot")),
        "observed_net": bool(clf.get("observed_net")),
        "first_live_visual_ok": bool(clf.get("first_live_visual_ok")),
        "attacking_team_match": bool(clf.get("attacking_team_match")),
        "claims_continuous_live": bool(clf.get("claims_continuous_live") or cut.get("continuous_source")),
        "live_or_replay": clf.get("live_or_replay") or "unknown",
        "human_video_supported": bool(clf.get("human_video_supported")),
        "agent_auto_verified": bool(clf.get("agent_auto_verified")),
        "verification_status": clf.get("verification_status") or "unresolved",
        "semantic_label": clf.get("semantic_label") or "unresolved",
        "semantic_verification_class": clf.get("semantic_verification_class") or NOT_VERIFIED,
        "classification_reason": clf.get("reason"),
        "evidence_gaps": clf.get("evidence_gaps") or [],
        "net_seen_only_in_replay": bool(clf.get("net_seen_only_in_replay")),
        "human_review_record": clf.get("human_review_record"),
        "frame_notes": frame_notes,
        "score_bound_ref": {
            "last_before": score_bounds.get("last_before_obs"),
            "first_after": score_bounds.get("first_after_obs"),
            "unknown_interval": score_bounds.get("unknown_interval"),
        },
        "candidate_extracted_ok": bool(cut.get("ok")),
        "goal_action_verified_ok": clf.get("semantic_label") == "verified_first_live",
        "render_ready": False,
    }


def run_first_live_localization(
    *,
    video: Path,
    role: str,
    task_row: Dict[str, Any],
    out_dir: Path,
    events_path: Optional[Path] = None,
    historical_clues: Optional[Sequence[Dict[str, Any]]] = None,
    human_score_observations: Optional[Sequence[Dict[str, Any]]] = None,
    human_review_by_candidate: Optional[Dict[str, Dict[str, Any]]] = None,
    frame_notes_by_candidate: Optional[Dict[str, Dict[str, Any]]] = None,
    identity: Optional[Dict[str, Any]] = None,
    max_candidates: int = 4,
    max_video_read_sec: float = 100.0,
    ocr_step_sec: float = 3.0,
    skip_ocr: bool = False,
) -> Dict[str, Any]:
    dest = Path(out_dir)
    dest.mkdir(parents=True, exist_ok=True)
    conf = float(task_row["score_confirmation_sec"])
    score_before = task_row.get("score_before")
    score_after = task_row.get("score_after")
    clues = list(historical_clues or [])
    events = load_events_rows(events_path) if events_path else []

    # OCR densify around confirm lookback (budgeted)
    ocr_rows: List[Dict[str, Any]] = []
    if not skip_ocr:
        ocr_rows = densify_score_observations(
            video=video,
            start_sec=max(0.0, conf - 120.0),
            end_sec=conf + 2.0,
            step_sec=ocr_step_sec,
            out_dir=dest / "ocr_frames",
            budget_frames=45,
        )
        dump(dest / "ocr_observations.json", ocr_rows)

    bounds = merge_score_bounds(
        score_before=score_before,
        score_after=score_after,
        ocr_rows=ocr_rows,
        human_obs=list(human_score_observations or []),
        event_rows=events,
        confirm_sec=conf,
    )
    dump(dest / "score_bounds.json", bounds)

    plan = propose_localization_candidates(
        role=role,
        confirm_sec=conf,
        score_before=score_before,
        score_after=score_after,
        historical_clues=clues,
        events=events,
        score_bounds=bounds,
        max_candidates=max_candidates,
        max_video_read_sec=max_video_read_sec,
    )
    dump(dest / "localization_plan.json", plan)

    audits = []
    human_map = dict(human_review_by_candidate or {})
    notes_map = dict(frame_notes_by_candidate or {})
    for w in plan["candidates"]:
        cid = w["candidate_id"]
        audited = audit_localized_candidate(
            video=video,
            role=role,
            window=w,
            out_dir=dest,
            score_before=score_before,
            score_after=score_after,
            score_confirmation_sec=conf,
            score_bounds=bounds,
            events=events,
            frame_notes=notes_map.get(cid) or notes_map.get(w.get("origin")),
            human_review=human_map.get(cid),
        )
        audits.append(audited)
    dump(dest / "candidate_audits.json", {role: audits})

    # Pick best non-replay candidate for pack handoff
    def _rank_audit(a: Dict[str, Any]) -> Tuple[int, float]:
        label = a.get("semantic_label")
        pref = {
            "verified_first_live": 100,
            "possible_first_live": 80,
            "shot_only": 40,
            "pre_goal_only": 20,
            "post_goal_celebration": 10,
            "unresolved": 5,
            "wrong_attacking_side": 0,
            "replay": -10,
        }.get(str(label), 0)
        return (pref, -float(a.get("media_in") or 0))

    ranked = sorted([a for a in audits if a.get("candidate_extracted_ok")], key=_rank_audit, reverse=True)
    top = ranked[0] if ranked else None
    goals = []
    if top:
        goals.append({
            "role": role,
            "identity": identity or {},
            "live_or_replay": top.get("live_or_replay") or "unknown",
            "observed_shot": top.get("observed_shot"),
            "observed_net": top.get("observed_net"),
            "first_live_visual_ok": top.get("first_live_visual_ok"),
            "attacking_team_match": top.get("attacking_team_match"),
            "claims_continuous_live": top.get("claims_continuous_live"),
            "media_in": top.get("media_in"),
            "media_out": top.get("media_out"),
            "shot_sec": top.get("shot_sec"),
            "net_sec": top.get("net_sec"),
            "clip_path": top.get("clip_path"),
            "frame_paths": top.get("frame_paths") or [],
            "semantic_label": top.get("semantic_label"),
            "semantic_verification_class": top.get("semantic_verification_class"),
            "human_video_supported": top.get("human_video_supported"),
            "agent_auto_verified": top.get("agent_auto_verified"),
            "verification_status": top.get("verification_status"),
            "candidate_id": top.get("candidate_id"),
            "evidence_gaps": top.get("evidence_gaps"),
            "classification_reason": top.get("classification_reason"),
            "net_seen_only_in_replay": top.get("net_seen_only_in_replay"),
            "human_review_record": top.get("human_review_record"),
            "candidate_extracted_ok": True,
            "goal_action_verified_ok": top.get("goal_action_verified_ok"),
            "render_ready": False,
        })

    labels = [a.get("semantic_label") for a in audits]
    summary = {
        "schema": "v3_p3_first_live_localization_v1",
        "role": role,
        "score_before": score_before,
        "score_after": score_after,
        "score_confirmation_sec": conf,
        "score_bounds": {
            "last_before": bounds.get("last_before_obs"),
            "first_after": bounds.get("first_after_obs"),
            "unknown_interval": bounds.get("unknown_interval"),
        },
        "n_candidates": len(audits),
        "labels": labels,
        "top_candidate_id": (top or {}).get("candidate_id"),
        "top_semantic_label": (top or {}).get("semantic_label"),
        "n_candidate_extracted_ok": sum(1 for a in audits if a.get("candidate_extracted_ok")),
        "n_goal_action_verified_ok": sum(1 for a in audits if a.get("goal_action_verified_ok")),
        "n_agent_auto_verified": sum(1 for a in audits if a.get("agent_auto_verified")),
        "n_human_video_supported": sum(1 for a in audits if a.get("human_video_supported")),
        "verdict_bucket": _verdict_bucket(top),
        "render_ready": False,
    }
    pack = {
        "schema": "v3_targeted_evidence_pack_v1",
        "match_id": (identity or {}).get("match_id"),
        "goals": goals,
        "n_agent_auto_verified": summary["n_agent_auto_verified"],
        "n_human_video_supported": summary["n_human_video_supported"],
        "note": "P3 localization pack; extraction ≠ verification",
        "render_ready": False,
    }
    dump(dest / "localization_summary.json", summary)
    dump(dest / "evidence_pack.json", pack)
    return {"summary": summary, "pack": pack, "audits": audits, "bounds": bounds, "plan": plan}


def _verdict_bucket(top: Optional[Dict[str, Any]]) -> str:
    if not top:
        return "not_found_in_budget"
    lab = top.get("semantic_label")
    if lab == "verified_first_live":
        return "found_first_live_with_sufficient_evidence"
    if lab == "possible_first_live":
        return "possible_clip_semantic_insufficient_for_auto_verify"
    if lab in {"shot_only", "pre_goal_only", "post_goal_celebration", "replay"}:
        return "possible_clip_semantic_insufficient_for_auto_verify"
    return "not_found_in_budget"


def localize_unresolved_recovered_goals(
    *,
    video: Path,
    events_path: Path,
    recovery_path: Path,
    out_dir: Path,
    candidate_ids: Optional[Sequence[str]] = None,
    max_candidates: int = 4,
    max_video_read_sec: float = 90.0,
    skip_ocr: bool = False,
) -> Dict[str, Any]:
    """Run existing P3 OCR + continuous-video localizer for P12 unresolved goals.

    This is the existing localizer, NOT a second timestamp inference path.
    It produces continuous clips and bound visual frames for independent
    inspection. Without grounded shot/net and broadcast proof it cannot
    fill `goal_action_sec`, upgrade first-LIVE or authorize EDL insertion.
    """
    video = Path(video)
    events_path = Path(events_path)
    recovery_path = Path(recovery_path)
    out_dir = Path(out_dir)
    if not video.is_file() or not events_path.is_file() or not recovery_path.is_file():
        raise FileNotFoundError("raw_mp4_raw_events_and_recovery_report_required")
    if not (1 <= int(max_candidates) <= 8 and 1.0 <= float(max_video_read_sec) <= 240.0):
        raise ValueError("localizer_budget_out_of_range")
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError("refuse_reuse_nonempty_evidence_dir")
    recovery = json.loads(recovery_path.read_text(encoding="utf-8"))
    if recovery.get("schema") != "v3_goal_recovery_v1":
        raise ValueError("recovery_schema_mismatch")
    pending = [
        c for c in recovery.get("candidates") or []
        if c.get("single_goal_increment") and c.get("goal_action_sec") is None
    ]
    selected_ids = set(str(x) for x in candidate_ids) if candidate_ids else None
    if selected_ids is not None:
        available = {str(c.get("candidate_id")) for c in pending}
        missing = selected_ids - available
        if missing:
            raise ValueError("candidate_id_not_unresolved:" + ",".join(sorted(missing)))
        pending = [c for c in pending if str(c.get("candidate_id")) in selected_ids]
    # Also protects against accidentally feeding a previously edited story clip
    # as the reference: the operator must explicitly pass the raw source MP4.
    video_sha = _sha256(video)
    events_sha = _sha256(events_path)
    out_dir.mkdir(parents=True, exist_ok=False)
    records: List[Dict[str, Any]] = []
    for c in pending:
        cid = str(c["candidate_id"])
        row = {
            "score_before": c["score_before"],
            "score_after": c["score_after"],
            "score_confirmation_sec": c["score_confirmation_sec"],
        }
        res = run_first_live_localization(
            video=video,
            role=cid,
            task_row=row,
            out_dir=out_dir / cid,
            events_path=events_path,
            historical_clues=[],  # no external V1/P3 gold or recalled PTS
            human_score_observations=[],  # raw-only evaluation
            human_review_by_candidate={},
            frame_notes_by_candidate={},
            identity={"candidate_id": cid, "raw_only": True},
            max_candidates=max_candidates,
            max_video_read_sec=max_video_read_sec,
            skip_ocr=skip_ocr,
        )
        records.append({
            "candidate_id": cid,
            "score_before": c["score_before"],
            "score_after": c["score_after"],
            "score_confirmation_sec": c["score_confirmation_sec"],
            "previous_goal_action_sec": None,
            "source_score_bracket": c.get("possible_action_interval"),
            "ocr_score_bounds": res["bounds"].get("unknown_interval"),
            "n_continuous_clips_extracted": res["summary"].get("n_candidate_extracted_ok"),
            "candidate_evidence_path": str(out_dir / cid / "candidate_audits.json"),
            "evidence_pack_path": str(out_dir / cid / "evidence_pack.json"),
            "first_live_status": res["summary"].get("verdict_bucket"),
            "action_timestamp_autofilled": False,
            "edl_inserted": False,
        })
    report = {
        "schema": "v3a_raw_only_unresolved_goal_video_evidence_v1",
        "inputs": {
            "original_events_json": str(events_path.resolve()),
            "events_sha256": events_sha,
            "original_source_mp4": str(video.resolve()),
            "source_sha256": video_sha,
            "goal_recovery_json": str(recovery_path.resolve()),
            "recovery_sha256": _sha256(recovery_path),
        },
        "n_unresolved_requested": len(records),
        "results": records,
        "actual_visual_semantic_verification": False,
        "no_automatic_goal_timestamp_or_edl": True,
        "no_gold_or_historical_overlay": True,
        "paid_http": 0,
        "next_step": "Review continuous clips for shot/net, first broadcast LIVE and action boundaries before binding any revised goal evidence.",
    }
    dump(out_dir / "raw_only_video_localization_summary.json", report)
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Zero-paid reuse of the existing P3 first-LIVE video localizer on raw-only unresolved goals"
    )
    parser.add_argument("--source-mp4", type=Path, required=True)
    parser.add_argument("--events-json", type=Path, required=True)
    parser.add_argument("--goal-recovery", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--candidate-id", action="append", default=None)
    parser.add_argument("--max-candidates", type=int, default=4)
    parser.add_argument("--max-video-read-sec", type=float, default=90.0)
    parser.add_argument("--skip-ocr", action="store_true")
    args = parser.parse_args(argv)
    result = localize_unresolved_recovered_goals(
        video=args.source_mp4,
        events_path=args.events_json,
        recovery_path=args.goal_recovery,
        out_dir=args.out_dir,
        candidate_ids=args.candidate_id,
        max_candidates=args.max_candidates,
        max_video_read_sec=args.max_video_read_sec,
        skip_ocr=args.skip_ocr,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
