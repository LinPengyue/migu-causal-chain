"""Phase 5 generic T01 Story Video Agent entry.

Inputs: full-match video + events JSON + causal JSON
  → T01 recognize → compose_story_plan → delivery EDL
  → story_clean.mp4 + story_qc.mp4 + story_summary.md + story_graph.json

No match-specific hardcoded goal times / team names / score sequences.
Optional --glitch-profile only when explicitly passed (never auto Croatia).
No paid API / VLM. render_ready remains false.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from story_chain.end_to_end import run_paths
from story_video_agent.narrative_composer import compose_story_plan
from story_video_agent.phase5_delivery import (
    build_story_graph,
    build_story_scope,
    build_story_summary_md,
    build_story_title,
    load_glitch_profile,
    render_dual_delivery,
    select_delivery_rows,
    validate_story_graph,
)

ROOT = Path(__file__).resolve().parents[2]


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def enrich_plan_title(plan: Dict[str, Any], story: Dict[str, Any]) -> str:
    title = build_story_title(plan, story)
    narr = dict(plan.get("narration") or {})
    narr["title"] = title
    # Do not spoil final score in title card text used for clean overlays
    plan["narration"] = narr
    return title


def insert_title_cards(
    delivery_edl: List[Dict[str, Any]],
    *,
    title: str,
    final_score: Optional[str],
) -> List[Dict[str, Any]]:
    """Open without spoiling final score; close may show result."""
    open_card = {
        "edl_index": 0,
        "segment_id": "seg_title_open",
        "beat": "铺垫",
        "role": "story_title",
        "shot_kind": "title_card",
        "is_replay": False,
        "media_in": None,
        "media_out": None,
        "time_status": "placeholder_title",
        "time_provenance": {"source": "phase5_packaging", "pipeline_verified": False},
        "event_ids": [],
        "frame_ids": [],
        "linked_live_event_id": None,
        "narrative_order": 0,
        "source_media_order": -1,
        "render_eligibility": "candidate_only",
        "blocking_reasons": ["phase5_candidate_delivery"],
        "confidence": 1.0,
        "selection_reason": "phase5_narrative_packaging",
        "narration": "开场标题（不剧透终场比分）",
        "include_in_cut": True,
        "placeholder_sec": 3.0,
        "placeholder_lines": [
            title,
            "逆风翻盘",
        ],
        "placeholder_lines_qc": [
            title,
            "逆风翻盘 · QC",
            "candidate_only · render_ready=false",
        ],
        "evidence_refs": [],
        "source_refs": [],
        "glitch_avoidance": [],
    }
    close_lines = [title, "故事收束"]
    close_lines_qc = [
        title,
        "故事收束 · 终场画面未独立核验",
        "candidate_only · render_ready=false",
    ]
    if final_score:
        close_lines.insert(1, f"最终比分 {final_score}")
        close_lines_qc.insert(1, f"最终比分 {final_score}")
    close_card = {
        **open_card,
        "segment_id": "seg_title_close",
        "beat": "收尾",
        "role": "story_wrap_title",
        "narrative_order": 10_000,
        "narration": "最终比分/故事收束包装（非已核实 FULL TIME 直播）",
        "selection_reason": "ending_story_wrap_packaging",
        "placeholder_lines": close_lines,
        "placeholder_lines_qc": close_lines_qc,
        "ending_status": "unverified_story_wrap",
    }
    out = [open_card] + list(delivery_edl) + [close_card]
    for i, row in enumerate(out):
        row["edl_index"] = i + 1
        row["narrative_order"] = i + 1
    return out


def run_phase5(
    *,
    video: Path,
    events: Path,
    causal: Path,
    out_dir: Path,
    glitch_profile: Optional[Path] = None,
    skip_render: bool = False,
) -> Dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    story = run_paths(events, causal)
    _write_json(out_dir / "t01_story.json", story)

    causal_doc = json.loads(Path(causal).read_text(encoding="utf-8"))
    plan = compose_story_plan(story, causal=causal_doc, use_llm=False)
    plan["render_ready"] = False
    plan.setdefault("gates", {})
    plan["gates"].update(
        {
            "candidate_only": True,
            "no_paid_api": True,
            "no_auto_semantic_grant": True,
            "phase5_generic": True,
            "glitch_profile": str(glitch_profile) if glitch_profile else None,
        }
    )
    title = enrich_plan_title(plan, story)
    plan["story_scope"] = build_story_scope(story, plan)
    _write_json(out_dir / "story_plan.json", plan)
    _write_json(out_dir / "story_scope.json", plan["story_scope"])

    glitch = load_glitch_profile(glitch_profile)
    delivery = select_delivery_rows(plan, glitch_ranges=glitch)
    sp = story.get("score_path") or []
    final_score = None
    if sp and isinstance(sp[-1], dict):
        final_score = sp[-1].get("score")
    delivery = insert_title_cards(delivery, title=title, final_score=final_score)
    _write_json(out_dir / "candidate_edl.json", delivery)

    summary_md = build_story_summary_md(
        plan=plan, story=story, delivery_edl=delivery, title=title
    )
    (out_dir / "story_summary.md").write_text(summary_md, encoding="utf-8")

    graph = build_story_graph(plan=plan, story=story, delivery_edl=delivery)
    g_ok, g_problems = validate_story_graph(graph)
    graph["structure_ok"] = g_ok
    graph["structure_problems"] = g_problems
    _write_json(out_dir / "story_graph.json", graph)
    if not g_ok:
        raise RuntimeError(f"story_graph structure invalid: {g_problems}")

    review_note = (
        "【审核说明 · 非画面烧录】\n"
        "本目录 story_clean.mp4 / story_qc.mp4 均为内部候选交付（candidate_only）。\n"
        "render_ready=false；未做付费 VLM / 独立语义签发；非正式咪咕生产成片。\n"
        "业务版去除技术叠字不等于获得正式授权。详见 story_summary.md 与 phase5_manifest.json。\n"
    )
    (out_dir / "REVIEW_NOTE.txt").write_text(review_note, encoding="utf-8")

    render_info: Dict[str, Any] = {"skipped": True}
    if not skip_render and plan.get("story_tier") != "none":
        if len([r for r in delivery if r.get("media_in") is not None]) == 0:
            render_info = {
                "skipped": True,
                "reason": "no_timed_segments",
                "missing": plan.get("missing_evidence"),
            }
        else:
            render_info = render_dual_delivery(
                plan=plan,
                video=Path(video),
                out_dir=out_dir,
                delivery_edl=delivery,
            )
            render_info["skipped"] = False
    elif plan.get("story_tier") == "none":
        render_info = {"skipped": True, "reason": "tier_none"}

    manifest = {
        "algorithm": "phase5_generic_t01",
        "match_id": story.get("match_id"),
        "story_tier": plan.get("story_tier"),
        "title": title,
        "protagonist": plan.get("protagonist"),
        "render_ready": False,
        "candidate_only": True,
        "inputs": {
            "video": str(video),
            "events": str(events),
            "causal": str(causal),
            "glitch_profile": str(glitch_profile) if glitch_profile else None,
        },
        "outputs": {
            "story_plan": str(out_dir / "story_plan.json"),
            "candidate_edl": str(out_dir / "candidate_edl.json"),
            "story_summary": str(out_dir / "story_summary.md"),
            "story_graph": str(out_dir / "story_graph.json"),
            "story_clean": str(out_dir / "story_clean.mp4"),
            "story_qc": str(out_dir / "story_qc.mp4"),
        },
        "delivery_segments": len(delivery),
        "timed_segments": sum(1 for r in delivery if r.get("media_in") is not None),
        "missing_evidence": plan.get("missing_evidence"),
        "blocking_reasons": plan.get("blocking_reasons"),
        "render": render_info,
        "unverified_capabilities": [
            "paid_planner",
            "production_vlm_semantic_grant",
            "independent_gt_accuracy",
        ],
    }
    _write_json(out_dir / "phase5_manifest.json", manifest)
    return manifest


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Phase 5 generic T01 story video pipeline")
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--events", type=Path, required=True)
    p.add_argument("--causal", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument(
        "--glitch-profile",
        type=Path,
        default=None,
        help="Optional JSON of source glitch ranges; never auto-selected",
    )
    p.add_argument("--skip-render", action="store_true")
    args = p.parse_args(argv)

    if not args.skip_render and not args.video.is_file():
        print(f"ERROR: video missing: {args.video}", file=sys.stderr)
        return 2
    if args.skip_render and not args.video.is_file():
        print(f"WARN: video missing (ok with --skip-render): {args.video}", file=sys.stderr)
    if not args.events.is_file() or not args.causal.is_file():
        print("ERROR: events/causal missing", file=sys.stderr)
        return 2

    # Ensure algo on path
    algo = Path(__file__).resolve().parents[1]
    if str(algo) not in sys.path:
        sys.path.insert(0, str(algo))

    manifest = run_phase5(
        video=args.video,
        events=args.events,
        causal=args.causal,
        out_dir=args.out_dir,
        glitch_profile=args.glitch_profile,
        skip_render=args.skip_render,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if manifest.get("story_tier") != "none" or args.skip_render else 0


if __name__ == "__main__":
    raise SystemExit(main())
