"""Stage5: independent, zero-HTTP source-video temporal evidence audit.

Goal: determine whether a real-VLM shot/net observation is corroborated by
an independently decoded scoreboard transition in the ORIGINAL broadcast.
It is NOT a first-live verifier. A scoreboard update plus absence of replay
events cannot by itself prove that the footage is not a replay.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from .first_live_localize import densify_score_observations, load_events_rows


def _read(path: Path) -> dict:
    x = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(x, dict):
        raise ValueError("expected_json_object")
    return x


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def assess_score_transition(
    *,
    ocr_rows: Sequence[Mapping[str, Any]],
    score_before: Sequence[int],
    score_after: Sequence[int],
    shot_sec: float,
    net_sec: float,
    replay_overlap: bool,
) -> Dict[str, Any]:
    """Pure fail-closed classifier, requiring independent video OCR.

    Two stable 'ok' readings on each side of shot/net are needed; 'weak'
    and raw-event score fields are not allowed to certify a video flip.
    """
    before = list(map(int, score_before))
    after = list(map(int, score_after))
    if len(before) != 2 or len(after) != 2 or before == after:
        return {"status": "INVALID_SCORE_TRANSITION", "ready_for_broadcast_review": False}
    if not 0 <= shot_sec < net_sec:
        return {"status": "INVALID_SHOT_NET_PTS", "ready_for_broadcast_review": False}
    samples = []
    for r in ocr_rows:
        score = r.get("score_tuple")
        if r.get("status") not in ("ok", "weak") or not isinstance(score, (list, tuple)) or len(score) != 2:
            continue
        try:
            samples.append({
                "sec": float(r["media_sec"]),
                "score": list(map(int, score)),
                "status": r["status"],
                "frame_path": r.get("frame_path"),
            })
        except (TypeError, ValueError, KeyError):
            continue
    samples.sort(key=lambda x: x["sec"])
    strong = [x for x in samples if x["status"] == "ok"]
    before_strong = [x for x in strong if x["score"] == before and x["sec"] <= shot_sec - 0.5]
    after_strong = [x for x in strong if x["score"] == after and x["sec"] >= net_sec + 0.5]
    early_after = [x for x in strong if x["score"] == after and x["sec"] < shot_sec - 0.5]
    late_before = [
        x for x in strong
        if after_strong and x["score"] == before and x["sec"] > after_strong[0]["sec"] + 0.5
    ]
    contradictory = bool(early_after or late_before)
    corroborated = bool(
        not contradictory
        and not replay_overlap
        and len({x["sec"] for x in before_strong}) >= 2
        and len({x["sec"] for x in after_strong}) >= 2
    )
    if replay_overlap:
        status = "REPLAY_EVENT_CONFLICT"
    elif contradictory:
        status = "SCORE_ORDER_CONFLICT"
    elif corroborated:
        status = "SCORE_TRANSITION_CORROBORATED"
    else:
        status = "SCORE_TRANSITION_INSUFFICIENT_OCR"
    return {
        "status": status,
        "score_before": before,
        "score_after": after,
        "strong_before_count": len(before_strong),
        "strong_after_count": len(after_strong),
        "first_strong_after_sec": after_strong[0]["sec"] if after_strong else None,
        "last_strong_before_sec": before_strong[-1]["sec"] if before_strong else None,
        "early_after_conflicts": early_after,
        "late_before_conflicts": late_before,
        "replay_event_overlap": replay_overlap,
        "ready_for_broadcast_review": corroborated,
        "first_live_verified": False,
        "note": (
            "Independent OCR score transition is corroboration, NOT proof "
            "that the observed goal was broadcast live for the first time."
        ),
    }


def _semantic_consensus(observations: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    rows = []
    for x in observations:
        try:
            shot, net = float(x["shot_sec"]), float(x["net_sec"])
        except (TypeError, ValueError, KeyError):
            continue
        if not (0 <= shot < net) or not x.get("shot_frame_ids") or not x.get("net_frame_ids"):
            continue
        rows.append({"shot_sec": shot, "net_sec": net, "log_sha256": x.get("log_sha256")})
    if not rows:
        return {"status": "NO_CITED_SHOT_NET_OBSERVATION", "agreed": False}
    shots = [x["shot_sec"] for x in rows]
    nets = [x["net_sec"] for x in rows]
    unique_logs = {
        str(x.get("log_sha256")) for x in rows
        if isinstance(x.get("log_sha256"), str) and len(x["log_sha256"]) == 64
    }
    agreed = (
        len(rows) >= 2
        and len(unique_logs) >= 2
        and max(shots) - min(shots) <= 3.0
        and max(nets) - min(nets) <= 3.0
    )
    return {
        "status": "TWO_MODEL_TEMPORAL_AGREEMENT" if agreed else "INSUFFICIENT_INDEPENDENT_AGREEMENT",
        "agreed": agreed,
        "n_observations": len(rows),
        "shot_spread_sec": round(max(shots) - min(shots), 3),
        "net_spread_sec": round(max(nets) - min(nets), 3),
        "shot_sec": min(shots),
        "net_sec": max(nets),
        "source_log_hashes": [x["log_sha256"] for x in rows],
    }


def run(
    *,
    source_mp4: Path,
    events_json: Path,
    stage4_queue: Path,
    out_dir: Path,
    step_sec: float = 2.0,
) -> Dict[str, Any]:
    if out_dir.exists():
        raise FileExistsError("refuse_overwrite")
    if not (1.0 <= step_sec <= 4.0):
        raise ValueError("step_sec_out_of_bounds")
    q = _read(stage4_queue)
    if q.get("schema") != "v3a_stage4_first_live_review_queue_v1":
        raise ValueError("wrong_stage4_queue_schema")
    source_sha = _sha256(source_mp4)
    if source_sha != q.get("source_sha256"):
        raise ValueError("source_mp4_sha256_mismatch")
    consensus = _semantic_consensus(q.get("semantic_observations") or [])
    if consensus.get("status") == "NO_CITED_SHOT_NET_OBSERVATION":
        raise ValueError("no_real_source_semantic_observation")
    shot, net = float(consensus["shot_sec"]), float(consensus["net_sec"])
    mi, mo = float(q["source_pts_start"]), float(q["source_pts_end"])
    if not (mi <= shot < net <= mo):
        raise ValueError("semantic_pts_outside_original_candidate")
    out_dir.mkdir(parents=True)
    ocr_rows = densify_score_observations(
        video=source_mp4,
        start_sec=max(0.0, shot - 16.0),
        end_sec=net + 26.0,
        step_sec=step_sec,
        out_dir=out_dir / "source_ocr_frames",
        budget_frames=35,
    )
    events = load_events_rows(events_json)
    replay_hits = [
        {"event_id": e.get("event_id"), "start": e["media_start_sec"],
         "end": e["media_end_sec"], "broadcast_phase": e.get("broadcast_phase")}
        for e in events
        if e.get("is_replay")
        and float(e["media_start_sec"]) <= net + 2.0
        and float(e["media_end_sec"]) >= shot - 2.0
    ]
    score = assess_score_transition(
        ocr_rows=ocr_rows,
        score_before=q["score_before"],
        score_after=q["score_after"],
        shot_sec=shot,
        net_sec=net,
        replay_overlap=bool(replay_hits),
    )
    result = {
        "schema": "v3a_stage5_broadcast_temporal_audit_v1",
        "source_sha256": source_sha,
        "stage4_queue_sha256": _sha256(stage4_queue),
        "issue_id": q["issue_id"],
        "candidate_id": q["candidate_id"],
        "source_pts": [mi, mo],
        "semantic_consensus": consensus,
        "score_video_ocr": score,
        "ocr_rows": ocr_rows,
        "replay_event_hits": replay_hits,
        "no_raw_replay_event_is_not_proof_of_live": True,
        "first_live_verified": False,
        "edl_repaired": False,
        "http_requests": 0,
        "next_decision": (
            "CONTINUOUS_BROADCAST_PHASE_REVIEW_REQUIRED"
            if score.get("ready_for_broadcast_review") and consensus.get("agreed")
            else "EVIDENCE_INSUFFICIENT_OR_CONFLICTING"
        ),
        "note": (
            "Never upgrade first-live from score transition, VLM claims, "
            "or missing replay events. A separate independently evidenced "
            "broadcast-phase review is still required."
        ),
    }
    (out_dir / "broadcast_temporal_audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Zero-HTTP original-video broadcast temporal audit")
    p.add_argument("--source-mp4", type=Path, required=True)
    p.add_argument("--events-json", type=Path, required=True)
    p.add_argument("--stage4-queue", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--step-sec", type=float, default=2.0)
    a = p.parse_args(argv)
    result = run(
        source_mp4=a.source_mp4, events_json=a.events_json,
        stage4_queue=a.stage4_queue, out_dir=a.out_dir, step_sec=a.step_sec,
    )
    print(json.dumps({
        "score_video_ocr": result["score_video_ocr"]["status"],
        "two_model_agreement": result["semantic_consensus"]["agreed"],
        "first_live_verified": False,
        "edl_repaired": False,
        "next_decision": result["next_decision"],
        "output": str(a.out_dir / "broadcast_temporal_audit.json"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
