"""Human-attested goal recovery: isolated, non-executable EDL proposal.

No automatic FIRST_LIVE promotion, no mutation of existing EDL or rendered video.
Window is a review hypothesis, not a verified first-live range. All timestamps
are source PTS; exact start/end must be checked against continuous original video.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .story_timeline import edl_rows, active_cut_rows, build_story_timeline


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def make_proposal(*, edl: Any, attestation: dict, source_sha: str,
                  issue_id: str, shot: float, net: float,
                  pre_sec: float = 6.0, post_sec: float = 9.0) -> dict:
    if not attestation.get("human_confirmed_first_live") is True:
        raise ValueError("explicit_human_first_live_attestation_required")
    if attestation.get("source_sha256") != source_sha:
        raise ValueError("human_attestation_source_sha_mismatch")
    if attestation.get("issue_id") != issue_id:
        raise ValueError("human_attestation_issue_mismatch")
    if not str(attestation.get("reviewer_confirmation") or "").strip():
        raise ValueError("reviewer_confirmation_required")
    if not all(math.isfinite(x) for x in (shot, net, pre_sec, post_sec)):
        raise ValueError("non_finite_timestamp")
    if not (0 < shot < net and 0 < pre_sec <= 20 and 0 < post_sec <= 25):
        raise ValueError("invalid_goal_or_clip_window")
    rows = active_cut_rows(edl_rows(edl))
    if not rows:
        raise ValueError("empty_edl")
    start, end = round(shot - pre_sec, 3), round(net + post_sec, 3)
    if start < 0:
        raise ValueError("negative_media_in")
    for row in rows:
        a, b = row.get("media_in"), row.get("media_out")
        if a is None or b is None:
            continue
        a, b = float(a), float(b)
        if max(start, a) < min(end, b) - .001:
            raise ValueError("proposed_goal_overlaps_existing_edl_segment:" + str(row.get("segment_id")))
    # Find insertion in source-time order, never silently reorder story beats.
    before = [r for r in rows if r.get("media_out") is not None and float(r["media_out"]) <= start]
    after = [r for r in rows if r.get("media_in") is not None and float(r["media_in"]) >= end]
    predecessor = max(before, key=lambda r: float(r["media_out"]), default=None)
    successor = min(after, key=lambda r: float(r["media_in"]), default=None)
    if predecessor is None or successor is None:
        placement = "NEEDS_STORY_SLOT_REVIEW"
    else:
        pi, si = rows.index(predecessor), rows.index(successor)
        placement = "CHRONOLOGICAL_NEIGHBORS" if pi < si else "NON_MONOTONIC_EDL_REQUIRES_REVIEW"
    segment = {
        "segment_id": "expb_human_goal_candidate_" + issue_id,
        "role": "equalizer_goal_action",
        "media_in": start, "media_out": end,
        "include_in_cut": True,
        "first_live_status": "HUMAN_ATTESTED_NOT_AUTOMATICALLY_VERIFIED",
        "is_replay": None,
        "evidence_tier": "HUMAN_VIDEO_REVIEW",
        "issue_id": issue_id,
    }
    return {
        "schema": "v3a_expb_human_goal_edl_candidate_v1",
        "status": "PROPOSAL_ONLY_REQUIRES_CLIP_BOUNDARY_AND_STORY_REVIEW",
        "source_sha256": source_sha,
        "issue_id": issue_id, "shot_sec": shot, "net_sec": net,
        "human_attestation": attestation,
        "baseline_story_timeline": build_story_timeline(rows),
        "proposed_segment": segment,
        "suggested_insert_after_segment_id": predecessor.get("segment_id") if predecessor else None,
        "suggested_insert_before_segment_id": successor.get("segment_id") if successor else None,
        "placement_status": placement,
        "checks_required": [
            "human_review_continuous_original_video_boundaries",
            "no_replay_or_slow_motion_in_full_window",
            "goal_identity_and_scoreboard_consistency",
            "chronology_and_story_beat_order",
            "duplicate_goal_and_existing_goal_anchor_check",
            "narrative_flow_before_and_after",
            "render_blind_review_before_acceptance",
        ],
        "first_live_verified": False,
        "executable_safe_revision": False,
        "edl_modified": False, "best_modified": False, "api_calls": 0,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--baseline-edl", type=Path, required=True)
    p.add_argument("--human-attestation", type=Path, required=True)
    p.add_argument("--source-sha256", required=True)
    p.add_argument("--issue-id", required=True)
    p.add_argument("--shot-sec", type=float, required=True)
    p.add_argument("--net-sec", type=float, required=True)
    p.add_argument("--pre-sec", type=float, default=6)
    p.add_argument("--post-sec", type=float, default=9)
    p.add_argument("--out-dir", type=Path, required=True)
    a = p.parse_args()
    if a.out_dir.exists():
        raise ValueError("refuse_overwrite_output_dir")
    edl = json.loads(a.baseline_edl.read_text(encoding="utf-8"))
    attestation = json.loads(a.human_attestation.read_text(encoding="utf-8"))
    result = make_proposal(
        edl=edl, attestation=attestation, source_sha=a.source_sha256,
        issue_id=a.issue_id, shot=a.shot_sec, net=a.net_sec,
        pre_sec=a.pre_sec, post_sec=a.post_sec,
    )
    result["baseline_edl_sha256"] = sha(a.baseline_edl)
    result["attestation_sha256"] = sha(a.human_attestation)
    a.out_dir.mkdir(parents=True)
    (a.out_dir / "expb_goal_edl_candidate.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": result["status"], "api_calls": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
