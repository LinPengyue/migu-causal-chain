"""Prepare auditable FIRST-broadcast review from raw-only source footage.

This command is ZERO HTTP, never reads gold/P14 EDL, never edits EDL,
and cannot auto-promote sampled-frame VLM claims to FIRST_LIVE_VERIFIED.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from .first_live_window_evidence import build_broadcast_timeline_review
from .story_e2e_agent import load_match_events


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def prepare(
    *,
    source_mp4: Path,
    events_json: Path,
    stage2_queue: Path,
    semantic_logs: Sequence[Path],
    out_dir: Path,
    pad_sec: float = 12.0,
) -> dict:
    if out_dir.exists():
        raise FileExistsError("refuse_overwrite_existing_review_dir")
    if not 0 < pad_sec <= 20:
        raise ValueError("pad_sec_outside_allowed_range")
    queue = _load(stage2_queue)
    issues = [i for i in queue.get("issues", []) if i.get("status") == "SOURCE_CLIPS_READY_UNVERIFIED"]
    if len(issues) != 1:
        raise ValueError("expected_exactly_one_unresolved_goal_issue")
    issue = issues[0]
    candidates = [c for c in issue.get("continuous_candidate_clips", [])
                  if c.get("clip_path") and c.get("semantic_label") not in
                  ("replay", "wrong_attacking_side")]
    if not candidates:
        raise ValueError("no_source_video_candidates")
    candidate = max(candidates, key=lambda c: float(c["media_in"]))
    mi, mo = float(candidate["media_in"]), float(candidate["media_out"])
    if not (0 <= mi < mo):
        raise ValueError("invalid_candidate_source_pts")
    source_sha = _sha256(source_mp4)
    observations = []
    for path in semantic_logs:
        data = _load(path)
        if data.get("observation_only") is not True or data.get("provider_mode") != "real":
            raise ValueError("expected_observation_only_real_model_log")
        if str(data.get("role")) != str(issue["issue_id"]):
            raise ValueError("semantic_issue_id_mismatch")
        inf = data.get("vlm_inference") or {}
        derived = (data.get("visible_crosscheck") or {}).get("derived_times") or {}
        observations.append({
            "log_path": str(path),
            "log_sha256": _sha256(path),
            "shot_sec": derived.get("shot_sec"),
            "net_sec": derived.get("net_sec"),
            "shot_frame_ids": inf.get("shot_frame_ids") or [],
            "net_frame_ids": inf.get("net_frame_ids") or [],
            "claimed_live": inf.get("live_or_replay"),
            "observation_only": True,
        })
    out_dir.mkdir(parents=True)
    # Source events are only replay hints; absent replay labels are NOT
    # proof that this is the first broadcast of the action.
    events = load_match_events(events_json)
    review = build_broadcast_timeline_review(
        source_sha=source_sha,
        pts_start=mi,
        pts_end=mo,
        source_mp4=source_mp4,
        events=events,
        out_dir=out_dir / "broadcast_context",
        context_pad_sec=pad_sec,
        explicit_review=None,
    )
    result = {
        "schema": "v3a_stage4_first_live_review_queue_v1",
        "issue_id": issue["issue_id"],
        "source_sha256": source_sha,
        "candidate_id": candidate.get("candidate_id"),
        "source_pts_start": mi,
        "source_pts_end": mo,
        "score_before": issue.get("score_before"),
        "score_after": issue.get("score_after"),
        "score_confirmation_sec": issue.get("score_confirmation_sec"),
        "semantic_observations": observations,
        "timeline_review_status": review.get("outcome"),
        "timeline_review_method": review.get("method"),
        "replay_hits": review.get("replay_hits"),
        "broadcast_context_clip": review.get("clip"),
        "first_live_verified": False,
        "edl_repaired": False,
        "reason": "source_video_semantic_observation_and_replay_hints_are_not_first_broadcast_proof",
        "required_independent_check": (
            "Inspect original continuous source broadcast context and earlier "
            "occurrences of the SAME goal action; confirm first on-air occurrence "
            "rather than replay, slow-motion or another camera angle."
        ),
        "no_gold_edl_used": True,
        "http_requests": 0,
    }
    (out_dir / "first_live_review_queue.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Stage4 zero-HTTP first-live source review")
    p.add_argument("--source-mp4", type=Path, required=True)
    p.add_argument("--events-json", type=Path, required=True)
    p.add_argument("--stage2-queue", type=Path, required=True)
    p.add_argument("--semantic-log", type=Path, action="append", required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--context-pad-sec", type=float, default=12.0)
    a = p.parse_args(argv)
    r = prepare(
        source_mp4=a.source_mp4, events_json=a.events_json,
        stage2_queue=a.stage2_queue, semantic_logs=a.semantic_log,
        out_dir=a.out_dir, pad_sec=a.context_pad_sec,
    )
    print(json.dumps({
        "status": r["timeline_review_status"],
        "first_live_verified": False,
        "edl_repaired": False,
        "review_queue": str(a.out_dir / "first_live_review_queue.json"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
