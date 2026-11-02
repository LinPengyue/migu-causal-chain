"""CLI: V3-P3 first-live localization for one or more critical roles."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional

from .first_live_localize import run_first_live_localization
from .gate import review_evidence
from .pipeline import V3InputError
from .targeted_evidence import load_historical_candidate_clues


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="V3-P3 first-live localization (no paid API)")
    p.add_argument("--v3-run-dir", type=Path, required=True)
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--events", type=Path, required=True)
    p.add_argument("--match-tag", required=True)
    p.add_argument("--role", action="append", default=[], help="Critical role(s); default opening_deficit")
    p.add_argument(
        "--g22-root",
        type=Path,
        default=Path("/data2/lpy1/_story_va_outputs/v2/cross_match_g2/g22_first_live"),
    )
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--human-score-obs", type=Path, help="JSON list of human score observations")
    p.add_argument("--human-review", type=Path, help="JSON map candidate_id -> human review record")
    p.add_argument("--frame-notes", type=Path, help="JSON map candidate_id/origin -> frame notes")
    p.add_argument("--max-candidates", type=int, default=4)
    p.add_argument("--skip-ocr", action="store_true")
    p.add_argument("--run-gate", action="store_true")
    p.add_argument("--gate-out-dir", type=Path)
    p.add_argument("--allow-human-reviewed", action="store_true")
    args = p.parse_args(argv)

    run = Path(args.v3_run_dir)
    tasks = json.loads((run / "critical_goal_evidence_tasks.json").read_text(encoding="utf-8"))
    provenance = json.loads((run / "provenance.json").read_text(encoding="utf-8"))
    identity = {
        "match_id": provenance["match_id"],
        "video_sha256": provenance["input_hashes"]["video_sha256"],
        "events_sha256": provenance["input_hashes"]["events_sha256"],
        "strip_provenance": provenance["input_hashes"]["strips_sha256"],
    }
    roles = args.role or ["opening_deficit"]
    human_obs = []
    if args.human_score_obs and args.human_score_obs.is_file():
        human_obs = json.loads(args.human_score_obs.read_text(encoding="utf-8"))
    human_review = {}
    if args.human_review and args.human_review.is_file():
        human_review = json.loads(args.human_review.read_text(encoding="utf-8"))
    frame_notes = {}
    if args.frame_notes and args.frame_notes.is_file():
        frame_notes = json.loads(args.frame_notes.read_text(encoding="utf-8"))

    dest = Path(args.out_dir)
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"Refusing nonempty out dir: {dest}")
    dest.mkdir(parents=True, exist_ok=True)

    summaries = []
    combined_goals = []
    try:
        for role in roles:
            task_row = next((t for t in (tasks.get("tasks") or []) if t.get("role") == role), None)
            if not task_row:
                raise V3InputError(f"missing task for role {role}")
            clues = load_historical_candidate_clues(
                match_tag=args.match_tag, role=role, g22_root=args.g22_root
            )
            role_out = dest / role
            result = run_first_live_localization(
                video=Path(args.video),
                role=role,
                task_row=task_row,
                out_dir=role_out,
                events_path=Path(args.events),
                historical_clues=clues,
                human_score_observations=human_obs,
                human_review_by_candidate=human_review,
                frame_notes_by_candidate=frame_notes,
                identity=identity,
                max_candidates=args.max_candidates,
                skip_ocr=args.skip_ocr,
            )
            summaries.append(result["summary"])
            combined_goals.extend(result["pack"].get("goals") or [])
    except (OSError, ValueError, RuntimeError, V3InputError) as exc:
        raise SystemExit(str(exc)) from exc

    pack = {
        "schema": "v3_targeted_evidence_pack_v1",
        "match_id": identity["match_id"],
        "match_tag": args.match_tag,
        "goals": combined_goals,
        "n_agent_auto_verified": sum(1 for g in combined_goals if g.get("agent_auto_verified")),
        "n_human_video_supported": sum(1 for g in combined_goals if g.get("human_video_supported")),
        "summaries": summaries,
        "note": "P3 localization; candidate extraction ≠ goal verification",
        "render_ready": False,
    }
    (dest / "evidence_pack.json").write_text(
        json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (dest / "localization_run_report.json").write_text(
        json.dumps({
            "schema": "v3_p3_localization_run_v1",
            "match_tag": args.match_tag,
            "roles": roles,
            "summaries": summaries,
            "render_ready": False,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "ok",
        "summaries": summaries,
        "out_dir": str(dest),
        "render_ready": False,
    }, ensure_ascii=False, indent=2))

    if args.run_gate:
        gate_out = args.gate_out_dir or (dest / "gate")
        report = review_evidence(
            v3_run_dir=run,
            evidence_pack=dest / "evidence_pack.json",
            output_dir=gate_out,
            allow_human=args.allow_human_reviewed,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report.get("status") else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
