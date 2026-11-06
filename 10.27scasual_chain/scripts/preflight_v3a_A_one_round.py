#!/usr/bin/env python3
"""Zero-cost preflight for Oman V3-A one-round opening-goal experiment.

No paid HTTP. Writes readiness artifacts under --out-dir.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "10.27scasual_chain" / "algo"))

from story_video_agent_v3.one_round_opening_budget import (  # noqa: E402
    DEFAULT_FRESH_RUN,
    DEFAULT_VLM_OBS,
    DEFAULT_VLM_SUMMARY,
    build_one_round_preflight,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--fresh-run", type=Path, default=DEFAULT_FRESH_RUN)
    p.add_argument("--historical-obs", type=Path, default=DEFAULT_VLM_OBS)
    p.add_argument("--historical-summary", type=Path, default=DEFAULT_VLM_SUMMARY)
    args = p.parse_args(argv)
    if args.out_dir.exists() and any(args.out_dir.iterdir()):
        print(json.dumps({
            "status": "failed",
            "error": f"out_dir must be empty/new: {args.out_dir}",
            "real_http_executed": False,
        }, ensure_ascii=False))
        return 2
    report = build_one_round_preflight(
        fresh_run=args.fresh_run,
        historical_obs=args.historical_obs,
        historical_summary=args.historical_summary,
        out_dir=args.out_dir,
    )
    print(json.dumps({
        "status": report.get("status"),
        "output": str(args.out_dir),
        "real_http_executed": False,
        "needs_new_vlm": (report.get("evidence_gap") or {}).get("needs_new_vlm"),
        "checks_ok": report.get("status") == "READY_FOR_AUTHORIZED_ONE_ROUND",
    }, ensure_ascii=False))
    return 0 if report.get("status") == "READY_FOR_AUTHORIZED_ONE_ROUND" else 1


if __name__ == "__main__":
    raise SystemExit(main())
