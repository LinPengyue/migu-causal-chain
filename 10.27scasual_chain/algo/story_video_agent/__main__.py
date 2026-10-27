"""CLI：dry-run / media-only / perception / compose / render（Phase 3B）。

  python -m story_video_agent --story-json ... --dry-run
  python -m story_video_agent --story-json ... --compose [--causal-json ...] [--out ...]
  python -m story_video_agent --plan-json ... --video-path ... --render preview --out ...
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from story_video_agent.narrative_composer import compose_from_paths
from story_video_agent.runner import run_story_json
from story_video_agent.story_output_schema import render_narrative_report


def main() -> None:
    parser = argparse.ArgumentParser(description="T01 Story Video Agent / Composer")
    parser.add_argument("--story-json", type=Path, default=None)
    parser.add_argument("--plan-json", type=Path, default=None, help="Phase 3A.1 compose plan")
    parser.add_argument("--video-path", type=str, default="")
    parser.add_argument("--duration-sec", type=float, default=None)
    parser.add_argument("--max-steps", type=int, default=32)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--media-only", action="store_true")
    mode.add_argument("--perception", action="store_true")
    mode.add_argument("--compose", action="store_true", help="Phase 3A story plan + EDL")
    mode.add_argument(
        "--render",
        choices=("preview", "final"),
        help="Phase 3B FFmpeg render (requires --plan-json --video-path --out)",
    )
    parser.add_argument("--causal-json", type=Path, default=None)
    parser.add_argument("--visual-evidence-json", type=Path, default=None)
    parser.add_argument("--use-llm-narration", action="store_true")
    parser.add_argument("--report-out", type=Path, default=None)
    parser.add_argument("--frame-budget", type=int, default=24)
    parser.add_argument("--frame-dir", type=Path, default=None)
    parser.add_argument("--manifest-out", type=Path, default=None)
    parser.add_argument("--france-focus", action="store_true")
    parser.add_argument("--croatia-setup-focus", action="store_true")
    parser.add_argument("--force-mock-vlm", action="store_true")
    parser.add_argument("--require-real-api", action="store_true")
    parser.add_argument("--use-llm-planner", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--max-clip-sec", type=float, default=None)
    parser.add_argument("--review-dir", type=Path, default=None, help="also write review_manifest")
    args = parser.parse_args()

    if args.render:
        if not args.plan_json or not args.video_path or not args.out:
            parser.error("--render requires --plan-json --video-path --out")
        from story_video_agent.review_assist import build_review_manifest
        from story_video_agent.video_renderer import render_from_paths

        result = render_from_paths(
            args.plan_json,
            args.video_path,
            args.out,
            mode=args.render,
            work_dir=str(args.work_dir) if args.work_dir else None,
            max_clip_sec=args.max_clip_sec,
        )
        if args.review_dir:
            plan = json.loads(Path(args.plan_json).read_text(encoding="utf-8"))
            man = build_review_manifest(plan, args.video_path, args.review_dir)
            result["review_manifest"] = man.get("path")
            result["contact_sheet"] = man.get("contact_sheet")
        print(json.dumps({k: result[k] for k in (
            "ok", "mode", "out_mp4", "n_segments", "n_cut", "n_placeholder",
            "output_media", "render_manifest", "review_manifest", "contact_sheet",
        ) if k in result}, ensure_ascii=False, indent=2))
        return

    if not args.story_json:
        parser.error("--story-json is required unless --render/--plan-json")

    if args.compose:
        plan = compose_from_paths(
            str(args.story_json),
            causal_path=str(args.causal_json) if args.causal_json else None,
            visual_evidence_path=str(args.visual_evidence_json)
            if args.visual_evidence_json
            else None,
            use_llm=bool(args.use_llm_narration),
            out_json=str(args.out) if args.out else None,
            out_report=str(args.report_out) if args.report_out else None,
        )
        if not args.out:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
        else:
            print(args.out)
        if args.report_out:
            print(args.report_out)
        elif args.out:
            # also print short status
            pass
        print(
            "compose",
            plan.get("story_tier"),
            "segments",
            len(plan.get("segments") or []),
            "verification",
            plan.get("verification_status"),
            "structure_ok",
            (plan.get("diagnostics") or {}).get("structure_ok"),
            "missing",
            len(plan.get("missing_evidence") or []),
        )
        return

    if args.perception:
        dry_run, media_only, perception = False, False, True
    elif args.media_only:
        dry_run, media_only, perception = False, True, False
    else:
        dry_run, media_only, perception = True, False, False

    focus = None
    if args.croatia_setup_focus:
        focus = ["missing_setup_visual"]

    result = run_story_json(
        str(args.story_json),
        video_path=args.video_path or None,
        duration_sec=args.duration_sec,
        max_steps=args.max_steps,
        dry_run=dry_run,
        media_only=media_only,
        perception=perception,
        frame_budget=args.frame_budget,
        frame_dir=str(args.frame_dir) if args.frame_dir else None,
        manifest_path=str(args.manifest_out) if args.manifest_out else None,
        france_focus=bool(args.france_focus),
        focus_gap_ids=focus,
        force_mock_vlm=bool(args.force_mock_vlm),
        use_llm_planner=True if args.use_llm_planner else None,
        require_real_api=bool(args.require_real_api),
    )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(args.out)
    diag = result.get("diagnostics") or {}
    print(
        "status",
        result["status"],
        "tasks",
        len(result.get("evidence_tasks") or []),
        "frames",
        diag.get("frame_count"),
        "observed",
        diag.get("observed_count"),
        "vlm_calls",
        (diag.get("vision") or {}).get("calls"),
        "elapsed",
        diag.get("elapsed_sec"),
        "verification_complete",
        result.get("verification_complete"),
        "structure_ok",
        result.get("structure_ok"),
    )


if __name__ == "__main__":
    main()
