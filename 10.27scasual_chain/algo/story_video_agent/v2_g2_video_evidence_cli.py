"""CLI: G2 zero-API video evidence pack for one match."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Optional

from story_video_agent.v2_g0_cross_match_preflight import write_json
from story_video_agent.v2_g2_video_evidence import run_g2_evidence_pack


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="V2 G2 zero-API video evidence pack")
    p.add_argument("--match-id", required=True)
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--events", type=Path, required=True)
    p.add_argument("--g1-dir", type=Path, required=True, help="G1 dry-run dir with selected_arc/provenance")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--input-source", default="human_corrected")
    p.add_argument("--real", action="store_true", help="Rejected — G2 task forbids paid API")
    args = p.parse_args(argv)

    if args.real:
        write_json(
            Path(args.out_dir) / "cli_report.json",
            {"status": "aborted_paid_api_disabled_in_g2", "render_ready": False},
        )
        return 2

    report = run_g2_evidence_pack(
        match_id=args.match_id,
        video=Path(args.video),
        events=Path(args.events),
        g1_dir=Path(args.g1_dir),
        out_dir=Path(args.out_dir),
        input_source=args.input_source,
    )
    status = str(report.get("status") or "")
    if status.startswith("aborted"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
