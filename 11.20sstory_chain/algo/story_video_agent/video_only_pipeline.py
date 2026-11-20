"""P4 stub: video-only end-to-end entry (compose/render reserved).

P1/P2 are implemented via video_only_p1p2. This module defines the future
adapter surface without forging full events/causal JSON or enabling render_ready.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class VideoStoryBundle:
    """Internal IR for video-driven path (not delivery events schema)."""

    video: str
    score_timeline: Dict[str, Any]
    discovery: Dict[str, Any]
    evidence_tasks: Dict[str, Any]
    evidence_items: List[Dict[str, Any]] = field(default_factory=list)
    teams_hypothesis: Optional[Dict[str, Any]] = None
    ending_status: str = "unknown"
    semantic_verified: bool = False
    render_ready: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def adapt_to_composer_input(bundle: VideoStoryBundle) -> Dict[str, Any]:
    """Map VideoStoryBundle → composer-facing IR.

    Does NOT invent a full events.json. Composer adapters in P4 should consume
    score path + verified evidence clips + narrative slots.
    """
    if not bundle.semantic_verified:
        return {
            "ok": False,
            "reason": "semantic_verified=false; refuse render_ready",
            "render_ready": False,
            "narrative_slots": [],
            "bundle_ref": "VideoStoryBundle",
        }
    # Placeholder for P4: slot list from discovery key_nodes + evidence_items
    return {
        "ok": True,
        "render_ready": False,  # still gated by phase5_delivery policy
        "narrative_slots": [],
        "note": "P4 not implemented this round",
    }


def run_p1p2_only(video: str, out_dir: str, **kwargs: Any) -> Dict[str, Any]:
    from story_video_agent.video_only_p1p2 import main as p1p2_main

    argv = ["--video", video, "--out-dir", out_dir]
    for k, v in kwargs.items():
        argv.extend([f"--{k.replace('_', '-')}", str(v)])
    code = p1p2_main(argv)
    report_path = Path(out_dir) / "p1p2_run_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    report["exit_code"] = code
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Video-only pipeline (P1/P2 now; P3/P4 stub)")
    parser.add_argument("--video", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--stage", choices=("p1p2", "full"), default="p1p2")
    args = parser.parse_args(argv)
    if args.stage != "p1p2":
        print(json.dumps({"ok": False, "reason": "P3/P4 full stage not enabled this round", "render_ready": False}))
        return 3
    report = run_p1p2_only(args.video, args.out_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(report.get("exit_code") or 0)


if __name__ == "__main__":
    raise SystemExit(main())
