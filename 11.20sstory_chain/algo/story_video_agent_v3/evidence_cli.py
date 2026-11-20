"""CLI: V3 targeted critical-goal evidence pass + optional V2 gate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional

from .gate import review_evidence
from .pipeline import V3InputError
from .targeted_evidence import run_targeted_evidence_pass


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="V3-P2 targeted evidence retrieval + gate")
    p.add_argument("--v3-run-dir", type=Path, required=True)
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--match-tag", required=True, help="e.g. A_uae_oman / B_osasuna_celta")
    p.add_argument(
        "--g22-root",
        type=Path,
        default=Path("/data2/lpy1/_story_va_outputs/v2/cross_match_g2/g22_first_live"),
    )
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--prefer-role", action="append", default=[])
    p.add_argument("--run-gate", action="store_true")
    p.add_argument("--gate-out-dir", type=Path)
    p.add_argument("--allow-human-reviewed", action="store_true")
    args = p.parse_args(argv)

    try:
        pack = run_targeted_evidence_pass(
            v3_run_dir=args.v3_run_dir,
            video=args.video,
            out_dir=args.out_dir,
            match_tag=args.match_tag,
            g22_root=args.g22_root,
            prefer_roles=args.prefer_role or None,
        )
    except (OSError, ValueError, RuntimeError, V3InputError) as exc:
        p.error(str(exc))
        return 2

    print(json.dumps({
        "status": "ok_evidence_pack_unresolved",
        "n_goals": len(pack.get("goals") or []),
        "n_agent_auto_verified": 0,
        "out_dir": str(args.out_dir),
        "render_ready": False,
    }, ensure_ascii=False, indent=2))

    if args.run_gate:
        gate_out = args.gate_out_dir or (Path(args.out_dir) / "gate")
        report = review_evidence(
            v3_run_dir=args.v3_run_dir,
            evidence_pack=Path(args.out_dir) / "evidence_pack.json",
            output_dir=gate_out,
            allow_human=args.allow_human_reviewed,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report.get("status") else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
