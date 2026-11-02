"""CLI: G2.2 first-live retrieval (zero paid API)."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Optional

from story_video_agent.v2_g0_cross_match_preflight import write_json
from story_video_agent.v2_g2_first_live_retrieval import run_g22_first_live


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="V2 G2.2 first-live retrieval pack (no paid API)")
    p.add_argument("--match-id", required=True)
    p.add_argument("--match-tag", required=True, help="e.g. A_uae_oman / B_osasuna_celta")
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--events", type=Path, required=True)
    p.add_argument("--g1-dir", type=Path, required=True)
    p.add_argument("--g2-dir", type=Path, required=True, help="Existing G2 evidence dir (7 candidates/role)")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--input-source", default="human_corrected")
    p.add_argument("--real", action="store_true", help="Rejected — G2.2 forbids paid API")
    args = p.parse_args(argv)

    if args.real:
        write_json(
            Path(args.out_dir) / "cli_report.json",
            {"status": "aborted_paid_api_disabled_in_g22", "render_ready": False},
        )
        return 2

    report = run_g22_first_live(
        match_id=args.match_id,
        match_tag=args.match_tag,
        video=Path(args.video),
        events=Path(args.events),
        g1_dir=Path(args.g1_dir),
        g2_dir=Path(args.g2_dir),
        out_dir=Path(args.out_dir),
        input_source=args.input_source,
    )
    status = str(report.get("status") or "")
    if status.startswith("aborted"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
