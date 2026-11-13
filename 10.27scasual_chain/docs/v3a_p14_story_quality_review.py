#!/usr/bin/env python3
"""Zero-HTTP, no-edit video review pack for P14 V3-A story hypotheses.

Event metadata gives search priors, not proof of narrative defects or first live.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from story_video_agent_v3.story_timeline import build_story_timeline, edl_rows


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def focus(issue, timeline):
    segs = timeline["segments"]
    total = float(timeline["story_duration_sec"])
    if issue.get("category") == "ending":
        return {"a": max(0, total - 20), "b": total, "kind": "last_20_sec_finished_story"}
    if issue.get("category") != "transition":
        return None
    ids = issue.get("segment_ids") or []
    if len(ids) < 2:
        return None
    lookup = {s["segment_id"]: s for s in segs}
    left, right = lookup.get(ids[0]), lookup.get(ids[1])
    if not left or not right:
        return None
    seam = float(left["story_out"])
    if abs(seam - float(right["story_in"])) > 0.03:
        return None
    return {"a": max(0, seam - 7), "b": min(total, seam + 7),
            "kind": "finished_story_cut_seam", "seam": round(seam, 3),
            "before": ids[0], "after": ids[1]}


def clip(source, a, b, output):
    if b - a < .5:
        return {"ok": False, "reason": "short_window"}
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
           "-ss", f"{a:.3f}", "-i", str(source), "-t", f"{b-a:.3f}",
           "-map", "0:v:0", "-map", "0:a?", "-vf", "scale=960:-2",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
           "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(output)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    ok = r.returncode == 0 and output.is_file() and output.stat().st_size > 1024
    return {"ok": ok, "path": str(output) if ok else None,
            "error": r.stderr[-1000:] if not ok else None}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run-dir", required=True, type=Path)
    p.add_argument("--source-mp4", required=True, type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--max-per-issue", default=2, type=int)
    args = p.parse_args()
    if not 1 <= args.max_per_issue <= 3:
        p.error("--max-per-issue must be 1..3")
    root = args.run_dir
    diagnosis_file = root / "02_round_01/story_diagnosis.json"
    search_file = root / "02_round_01/evidence_search.json"
    edl_file = root / "01_initial_story/candidate_edl.json"
    story_mp4 = root / "01_initial_story/story_clean.mp4"
    audit_file = root / "story_e2e_audit.json"
    for f in (diagnosis_file, search_file, edl_file, story_mp4, audit_file, args.source_mp4):
        if not f.is_file():
            raise FileNotFoundError(f)
    if args.out_dir.exists():
        raise FileExistsError("refuse_nonempty_or_existing_review_dir:" + str(args.out_dir))
    edl = edl_rows(load(edl_file))
    roles = [str(s.get("role") or "") for s in edl]
    for role in ("opponent_opening_goal_action", "equalizer_goal_action", "go_ahead_goal_action"):
        if role not in roles:
            raise ValueError("P14_three_goal_roles_required:" + role)
    audit = load(audit_file)
    source_sha = sha(args.source_mp4)
    if not audit.get("source_sha256") or source_sha.lower() != str(audit["source_sha256"]).lower():
        raise ValueError("source_video_sha256_differs_from_v3a_audit")
    diagnosis, search = load(diagnosis_file), load(search_file)
    timeline = build_story_timeline(edl)
    issues = [i for i in diagnosis.get("issues") or [] if i.get("category") in ("transition", "ending")]
    # Only two transitions and one ending from the actual P14 run.
    args.out_dir.mkdir(parents=True)
    entries = []
    for number, issue in enumerate(issues[:3], 1):
        iid = str(issue["issue_id"])
        span = focus(issue, timeline)
        item = {"issue_id": iid, "category": issue["category"],
                "diagnosis_status": issue.get("diagnosis_status"),
                "story_defect_confirmed": False, "no_edit_authorized": True,
                "finished_story_focus": span, "source_candidates": []}
        if span:
            target = args.out_dir / f"{number:02d}_finished_story_context.mp4"
            item["finished_story_clip"] = clip(story_mp4, span["a"], span["b"], target)
        targets = [t for t in search.get("targets") or [] if t.get("issue_id") == iid]
        selected = (targets[0].get("candidates") or []) if targets else []
        seen = set()
        for candidate in selected:
            try:
                a, b = float(candidate["source_pts_start"]), float(candidate["source_pts_end"])
            except (TypeError, ValueError, KeyError):
                continue
            if a < 0 or b <= a:
                continue
            key = (round(a, 3), round(b, 3))
            if key in seen:
                continue
            seen.add(key)
            mid = (a+b)/2
            left, right = max(0, mid-6), mid+6
            output = args.out_dir / f"{number:02d}_event_candidate_{len(seen):02d}.mp4"
            item["source_candidates"].append({
                "event_id": candidate.get("event_id"),
                "candidate_id": candidate.get("candidate_id"),
                "event_pts": [a, b],
                "review_pts": [round(left, 3), round(right, 3)],
                "rank_score": candidate.get("rank_score"),
                "evidence_tier": "EVENT_PTS_CANDIDATE_ONLY",
                "first_live_verified": False, "narrative_fit_verified": False,
                "source_clip": clip(args.source_mp4, left, right, output)})
            if len(seen) >= args.max_per_issue:
                break
        entries.append(item)
    output = {"schema": "v3a_p14_story_quality_video_review_pack_v1",
              "mode": "HUMAN_ATOM_ENRICHED_DEV",
              "source_sha256": source_sha,
              "story_mp4_sha256": sha(story_mp4),
              "edl_sha256": sha(edl_file),
              "paid_http": 0,
              "edl_modified": False,
              "semantic_story_defects_verified": False,
              "first_live_verified": False,
              "issues": entries,
              "note": "Review clips only. No automatic edit, no first-live inference, no claim of story quality improvement. Event PTS is not visual-semantic proof."}
    (args.out_dir / "review_manifest.json").write_text(
        json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"n_issues": len(entries), "out_dir": str(args.out_dir),
                      "paid_http": 0, "edl_modified": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
