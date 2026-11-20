"""Re-run final MP4 visual audit on an existing R2.5 fix out-dir (no full timeline)."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from story_video_agent.api_provider import ApiConfigError, ApiProvider, api_enabled, load_endpoint_configs, smoke_enabled
from story_video_agent.v2_strip_guided_r2_5_final_mp4_audit import audit_final_mp4_goals
from story_video_agent.vision_provider import VisionProvider


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--max-api-calls", type=int, default=40)
    p.add_argument("--max-cost-usd", type=float, default=2.0)
    p.add_argument("--max-completion-tokens", type=int, default=8192)
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    edl = json.loads((out_dir / "edl_live_only.json").read_text(encoding="utf-8"))
    goal_doc = json.loads((out_dir / "goal_live_window_audit.json").read_text(encoding="utf-8"))
    clean = out_dir / "story_clean_live_only.mp4"
    if not clean.is_file():
        raise SystemExit(f"missing {clean}")

    if not api_enabled() or not smoke_enabled():
        raise ApiConfigError("STORY_API_ENABLE=1 and STORY_API_SMOKE=1 required")

    api = ApiProvider(
        configs=load_endpoint_configs(),
        require_real=True,
        force_mock=False,
        max_calls=args.max_api_calls,
        max_cost_usd=args.max_cost_usd,
        max_completion_tokens=args.max_completion_tokens,
    )
    vision = VisionProvider(api=api, force_mock=False)
    t0 = time.time()
    final_audit = audit_final_mp4_goals(
        story_mp4=clean,
        edl=edl,
        goal_audits=goal_doc.get("goals") or [],
        vision=vision,
        frames_dir=out_dir / "frames_final_mp4_reaudit",
        max_frames=80,
    )
    _write(out_dir / "final_mp4_visual_audit.json", final_audit)

    visual_all = bool(final_audit.get("all_five_goals_visual_pass"))
    edl.setdefault("gates", {})["final_mp4_visual_pass"] = visual_all
    edl.setdefault("gates", {})["story_complete_candidate"] = visual_all and bool(
        edl.get("gates", {}).get("all_five_goals_pass") or edl.get("n_goal_segments") == 5
    )
    # Prefer window audit + visual
    window_all = bool(goal_doc.get("all_five_pass"))
    story_complete = window_all and visual_all
    edl["gates"]["all_five_goals_pass"] = story_complete
    edl["gates"]["story_complete_candidate"] = story_complete
    if not story_complete:
        edl["story_complete_blocked_reason"] = "final_mp4_visual_audit_failed"
    else:
        edl.pop("story_complete_blocked_reason", None)
    _write(out_dir / "edl_live_only.json", edl)

    # Refresh integrity + cli_report acceptance fields
    integrity_path = out_dir / "goal_clip_integrity_audit.json"
    if integrity_path.is_file():
        integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
    else:
        integrity = {"schema": "v2_r25_goal_clip_integrity_audit_v1", "goals": goal_doc.get("goals")}
    integrity["n_pass_final_mp4"] = final_audit.get("n_pass")
    integrity["all_five_pass"] = story_complete
    integrity["story_complete_candidate"] = story_complete
    integrity["final_mp4_visual_audit_ref"] = str(out_dir / "final_mp4_visual_audit.json")
    integrity["render_ready"] = False
    _write(integrity_path, integrity)

    report_path = out_dir / "cli_report.json"
    report: Dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    report["n_goals_window_pass"] = goal_doc.get("n_pass")
    report["n_goals_final_mp4_pass"] = final_audit.get("n_pass")
    report["all_five_goals_pass"] = story_complete
    report["story_complete_candidate"] = story_complete
    report["final_reaudit_elapsed_sec"] = round(time.time() - t0, 3)
    report["final_reaudit_api_stats"] = api.stats.summary()
    report["acceptance"] = {
        "go_ahead_2_1_present": any(
            (g.get("score_after") or []) == [2, 1] and g.get("pass")
            for g in (final_audit.get("goals") or [])
        ),
        "five_goals_live_complete": story_complete,
        "final_mp4_visual_pass": visual_all,
        "no_failed_live_segments_in_edl": edl.get("n_goal_segments") == 5,
    }
    report["render_ready"] = False
    _write(report_path, report)

    print(
        json.dumps(
            {
                "out_dir": str(out_dir),
                "window_pass": goal_doc.get("n_pass"),
                "final_pass": final_audit.get("n_pass"),
                "all_five_goals_visual_pass": visual_all,
                "story_complete_candidate": story_complete,
                "acceptance": report["acceptance"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if story_complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
