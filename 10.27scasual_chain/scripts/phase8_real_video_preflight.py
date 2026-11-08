#!/usr/bin/env python3
"""Zero-HTTP source-video timeline preflight for Phase 8.

Creates SOURCE-context video clips and audit JSON. Never certifies FIRST_LIVE.
Only a separate evidence-backed broadcast review can grant FIRST_LIVE_VERIFIED.
No gold labels, provider APIs, or story EDL changes are used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from story_video_agent_v3.first_live_window_evidence import build_broadcast_timeline_review


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_events(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [e for e in data if isinstance(e, dict)]
    if isinstance(data, dict):
        for k in ("events", "event_list", "timeline_events"):
            if isinstance(data.get(k), list):
                return [e for e in data[k] if isinstance(e, dict)]
    raise ValueError("Event JSON must be a list or an object with events/event_list/timeline_events")


def parse_window(raw: str) -> tuple[str, float, float]:
    parts = raw.split(":")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("Expected LABEL:SOURCE_PTS_START:SOURCE_PTS_END")
    label, aa, bb = parts
    if not label or not all(ch.isalnum() or ch in "_-" for ch in label):
        raise argparse.ArgumentTypeError("Window label must use letters, numbers, underscore, hyphen")
    try:
        start, end = float(aa), float(bb)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("PTS must be numeric seconds") from exc
    if not (0 <= start < end):
        raise argparse.ArgumentTypeError("PTS must satisfy 0 <= start < end")
    return label, start, end


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-mp4", type=Path, required=True)
    ap.add_argument("--events-json", type=Path, default=None, help="Optional non-gold events generated from allowed raw inputs")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--window", type=parse_window, action="append", required=True, metavar="NAME:START:END")
    ap.add_argument("--context-pad-sec", type=float, default=8.0)
    args = ap.parse_args()
    if not args.source_mp4.is_file():
        ap.error(f"Missing source MP4: {args.source_mp4}")
    if args.events_json is not None and not args.events_json.is_file():
        ap.error(f"Missing generated event JSON: {args.events_json}")
    if args.context_pad_sec < 0 or args.context_pad_sec > 12:
        ap.error("--context-pad-sec must be between 0 and 12")
    names = [w[0] for w in args.window]
    if len(names) != len(set(names)):
        ap.error("Window labels must be unique")

    events = read_events(args.events_json)
    sha = sha256_file(args.source_mp4)
    args.out.mkdir(parents=True, exist_ok=True)
    cases = []
    for name, start, end in args.window:
        folder = args.out / name
        review = build_broadcast_timeline_review(
            source_sha=sha,
            pts_start=start,
            pts_end=end,
            source_mp4=args.source_mp4,
            events=events,
            out_dir=folder,
            context_pad_sec=args.context_pad_sec,
            explicit_review=None,  # NEVER synthesize a positive certification
        )
        outcome = review.get("outcome", "UNKNOWN")
        cases.append({
            "name": name, "source_pts": [start, end],
            "timeline_outcome": outcome,
            "first_live_verified": False,
            "replay_hits": review.get("replay_hits") or [],
            "context_clip": (review.get("clip") or {}).get("path"),
            "context_clip_sha256": (review.get("clip") or {}).get("sha256"),
            "clip_extraction_ok": bool((review.get("clip") or {}).get("ok")),
            "review_json": str(folder / "broadcast_timeline_review.json"),
            "next_step": "human_or_auditable_timeline_review" if outcome == "UNKNOWN" else "exclude_replay_window",
        })
    result = {
        "schema": "phase8_real_video_zero_http_preflight_v1",
        "source_mp4": str(args.source_mp4), "source_sha256": sha,
        "events_json": str(args.events_json) if args.events_json else None,
        "provider_calls": 0, "paid_calls": 0, "gold_used": False,
        "first_live_positive_claims": 0, "release_authorized": False,
        "note": "A source clip is evidence for review, not a FIRST_LIVE_VERIFIED certificate.",
        "cases": cases,
    }
    (args.out / "preflight_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())