"""V3-A Stage-3: bounded, read-only media evidence acquisition for Stage-2 P0.

Only accepts an unchanged Phase5 + SHA-bound Stage-2 proposal, and a video
matching the Phase5 recorded source. The default path extracts frames only;
real VLM requires two explicit CLI switches and a configured remote provider.
Observations never grant verified LIVE or change any EDL.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from story_video_agent.frames import FrameBudget, FrameStore
from story_video_agent.media import MediaInfo, probe_video
from story_video_agent_v3.planner_stage2 import (
    SCHEMA as PROPOSAL_SCHEMA, _intervals, _sha, compile_safe_candidates,
)

SCHEMA = "v3a_stage3_media_evidence_v1"
PER_WINDOW_SAMPLES = 3
MAX_FRAMES = 24
MAX_VLM_CALLS = 3
MAX_VLM_EST_COST_USD = 0.5
MAX_VLM_OUTPUT_TOKENS = 640
MAX_PTS_DRIFT_SEC = 2.0
VLM_WINDOW_STRATEGY = "first_middle_last"


def _fail(msg: str) -> None:
    raise ValueError(msg)


def _load(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        _fail(f"{path.name} is not a JSON object")
    return value


def _input_paths(phase5: Path, audit: Path) -> Dict[str, Path]:
    return {
        "story": phase5 / "t01_story.json",
        "plan": phase5 / "story_plan.json",
        "edl": phase5 / "candidate_edl.json",
        "audit": audit,
    }


def validate_stage3_inputs(
    proposal: Dict[str, Any],
    story: Dict[str, Any],
    plan: Dict[str, Any],
    edl: Sequence[Dict[str, Any]],
    audit: Dict[str, Any],
    source_hashes: Dict[str, str],
    *,
    video_path: Optional[Path] = None,
    manifest: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Fail closed on cross-run or modified-input proposals. No media access."""
    if proposal.get("schema") != PROPOSAL_SCHEMA:
        _fail("invalid Stage-2 proposal schema")
    if proposal.get("edl_modified") is not False or proposal.get("render_ready") is not False:
        _fail("Stage-2 proposal must be immutable and not authorized")
    if proposal.get("release_decision") != "NOT_AUTHORIZED":
        _fail("Stage-2 proposal improperly claims release authorization")
    if proposal.get("stage2_status") != "PROPOSAL_ONLY":
        _fail("Stage-2 proposal is not an unexecuted evidence proposal")
    if proposal.get("source_sha256") != source_hashes:
        _fail("Stage-2 source_sha256 mismatch: frozen input or audit changed")
    match = str(story.get("match_id") or "")
    if not match or any(str(doc.get("match_id") or "") != match for doc in (plan, audit, proposal)):
        _fail("match_id mismatch (possible cross-match contamination)")
    if audit.get("render_ready") is not False or audit.get("release_decision") != "NOT_AUTHORIZED":
        _fail("Stage-1 audit must not grant release")
    selected = proposal.get("selected_tasks")
    if not isinstance(selected, list) or len(selected) != 1:
        _fail("Stage-3 first increment requires exactly one selected P0 task")
    task = selected[0]
    if not isinstance(task, dict):
        _fail("invalid selected task")
    candidates = compile_safe_candidates(story, plan, edl, audit)
    expected = {row["task_id"]: row for row in candidates}
    tid = task.get("task_id")
    if tid not in expected or task != expected[tid]:
        _fail("Stage-2 task differs from canonical derivation")
    if (
        task.get("issue_kind") != "missing_story_element"
        or task.get("issue_target") != "opponent_opening"
        or task.get("severity") != "P0"
        or task.get("may_edit_edl") is not False
        or task.get("evidence_status") != "UNVERIFIED"
        or task.get("repair_intent") != "add_missing_role_after_evidence_verification"
    ):
        _fail("only missing opponent opening P0 is supported in Stage-3 first increment")
    arc = (plan.get("story_scope") or {}).get("selected_arc") or {}
    score = arc.get("behind_start") or {}
    score_t = score.get("t_sec")
    if score_t is None or not math.isfinite(float(score_t)) or float(score_t) < 0:
        _fail("missing/invalid T01 behind_start score anchor")
    if float(task.get("score_anchor_sec")) != float(score_t):
        _fail("score anchor drift from T01 selected arc")
    if task.get("search_windows") != _intervals(float(score_t)):
        _fail("search window drift from bounded Stage-2 time generation")
    refs = task.get("evidence_refs") or []
    if len(refs) != 1 or refs[0].get("verification") != "SOURCE_ANCHOR_ONLY":
        _fail("task unexpectedly claims verified goal evidence")
    if video_path is not None:
        if manifest is None:
            _fail("Phase5 manifest is required to bind input video")
        recorded = (manifest.get("inputs") or {}).get("video")
        if not recorded or Path(str(recorded)).resolve() != Path(video_path).resolve():
            _fail("video does not match original Phase5 source path")
        if str(manifest.get("match_id") or "") != match:
            _fail("Phase5 manifest match_id mismatch")
        if manifest.get("render_ready") is not False:
            _fail("Phase5 manifest may not grant render_ready")
    return task


def _validate_bounds(task: Dict[str, Any], media: MediaInfo, *, per_window: int, max_frames: int) -> None:
    windows = task["search_windows"]
    if not windows or len(windows) > 8:
        _fail("wrong window count")
    if per_window < 1 or per_window > 4:
        _fail("samples per window must be 1..4")
    if max_frames < len(windows) * per_window or max_frames > MAX_FRAMES:
        _fail("frame budget too low for planned sampling or above cap")
    for w in windows:
        start, end = float(w["start"]), float(w["end"])
        if not (0 <= start < end <= media.duration_sec and end - start <= 30.001):
            _fail("search interval out of source video bounds")


def _select_vlm_window_indices(n: int) -> List[int]:
    """Inspect at most 3 windows, ensuring the anchor-near and early windows included."""
    if n <= MAX_VLM_CALLS:
        return list(range(n))
    idx = [0, (n - 1) // 2, n - 1]
    return sorted(set(idx))


def sample_media(
    task: Dict[str, Any], media: MediaInfo, *,
    frame_dir: Path,
    samples_per_window: int = PER_WINDOW_SAMPLES,
    frame_budget: int = MAX_FRAMES,
) -> Tuple[List[Dict[str, Any]], FrameStore]:
    _validate_bounds(task, media, per_window=samples_per_window, max_frames=frame_budget)
    tid = str(task["task_id"])
    store = FrameStore(
        media, out_dir=frame_dir,
        budget=FrameBudget(max_frames=frame_budget, per_gap_caps={tid: frame_budget}),
    )
    windows: List[Dict[str, Any]] = []
    for index, win in enumerate(task["search_windows"]):
        records = store.extract_window(
            float(win["start"]), float(win["end"]),
            gap_id=tid, tool="v3a_stage3_bounded_coarse_search",
            count=samples_per_window,
        )
        frames: List[Dict[str, Any]] = []
        for rec in records:
            row = rec.to_dict()
            pts = rec.actual_media_sec
            req = rec.requested_media_sec
            drift = None if pts is None else round(abs(float(pts) - float(req)), 3)
            row["pts_drift_sec"] = drift
            row["time_reliability"] = (
                "PTS_MISSING" if pts is None else
                "PTS_DRIFT_REVIEW" if drift is not None and drift > MAX_PTS_DRIFT_SEC else
                "PTS_WITHIN_TOLERANCE"
            )
            row["semantic_status"] = "UNOBSERVED"
            frames.append(row)
        windows.append({
            "window_index": index, "media_start_sec": float(win["start"]),
            "media_end_sec": float(win["end"]), "frames": frames,
            "n_frames": len(frames), "visual_semantics": "UNKNOWN",
            "first_live_goal_verified": False,
        })
    return windows, store


def _make_contact_sheet(windows: Sequence[Dict[str, Any]], destination: Path) -> Dict[str, Any]:
    """Human-review aid; captions are bound to requested timestamps, not VLM claims."""
    try:
        from PIL import Image, ImageDraw, ImageOps
    except ImportError:
        return {
            "status": "UNAVAILABLE", "reason": "Pillow not installed",
            "frame_manifest_still_available": True,
        }
    frames = [
        (w["window_index"], row) for w in windows for row in w.get("frames") or []
    ]
    if not frames:
        return {"status": "EMPTY", "reason": "no frames"}
    width, height, label_h, columns = 360, 210, 44, 3
    nrows = (len(frames) + columns - 1) // columns
    canvas = Image.new("RGB", (width * columns, (height + label_h) * nrows), "white")
    draw = ImageDraw.Draw(canvas)
    for i, (win_idx, row) in enumerate(frames):
        x = (i % columns) * width
        y = (i // columns) * (height + label_h)
        with Image.open(str(row["path"])) as raw:
            tile = ImageOps.fit(raw.convert("RGB"), (width, height))
        canvas.paste(tile, (x, y))
        label = (
            f"W{win_idx} req={row['requested_media_sec']:.2f}s "
            f"pts={row['actual_media_sec'] if row['actual_media_sec'] is not None else '?'}"
        )
        draw.text((x + 5, y + height + 4), label, fill="black")
        draw.text((x + 5, y + height + 22), str(row["frame_id"]), fill="black")
    canvas.save(destination, quality=85)
    return {
        "status": "CREATED", "path": str(destination),
        "frames": len(frames), "columns": columns,
        "note": "Coarse still-image index only; not proof of first-live goal.",
    }


def _observe_windows(
    windows: List[Dict[str, Any]], *,
    task_id: str, enable_real_vlm: bool,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if not enable_real_vlm:
        return [], {
            "provider_mode": "not_called",
            "real_requests": 0,
            "note": "Sampling only. No VLM observation, no visual verification.",
        }
    # Import/create provider only under explicit real mode; no implicit mock pass.
    from story_video_agent.api_provider import ApiProvider, api_enabled
    from story_video_agent.vision_provider import VisionProvider
    if not api_enabled():
        _fail("real VLM additionally requires STORY_API_ENABLE=1")
    api = ApiProvider(
        require_real=True, required_roles=["vision"],
        max_calls=MAX_VLM_CALLS,
        max_cost_usd=MAX_VLM_EST_COST_USD,
        max_completion_tokens=MAX_VLM_OUTPUT_TOKENS,
    )
    vision = VisionProvider(api)
    indices = _select_vlm_window_indices(len(windows))
    observations: List[Dict[str, Any]] = []
    for idx in indices:
        win = windows[idx]
        frames = win["frames"]
        bindings = [
            {
                "frame_id": f["frame_id"],
                "requested_media_sec": f["requested_media_sec"],
                "actual_media_sec": f["actual_media_sec"],
                "pts_status": f["pts_status"],
                "match_logic_sec": None,
                "match_logic_status": "uncalibrated",
            }
            for f in frames
        ]
        observed = vision.describe_frames(
            gap_id=task_id,
            gap_note=(
                "Find visual CLUES for the opponent goal that caused the selected comeback arc deficit. "
                "A score change does not prove first-live goal action. "
                "Do not assume a replay or celebration is a live goal. "
                f"Scanned source interval [{win['media_start_sec']}, {win['media_end_sec']}]."
            ),
            frame_paths=[Path(f["path"]) for f in frames],
            frame_ids=[str(f["frame_id"]) for f in frames],
            frame_bindings=bindings,
            gap={
                "gap_id": task_id, "kind": "action_localize",
                "score_anchor_sec": None,
                "tool_hint": "coarse_search_interval",
            },
        )
        observed["search_window_index"] = idx
        observed["observation_only"] = True
        observed["fact_verified"] = False
        observed["first_live_goal_verified"] = False
        observations.append(observed)
    return observations, {
        "provider_mode": "real_invoked",
        "vlm_window_indices": indices,
        "api_usage": api.stats.summary(),
        "cost_cap_note": "estimate-only soft guard, not billing guarantee",
        "max_calls": MAX_VLM_CALLS,
    }


def run(
    *,
    phase5: Path,
    proposal_path: Path,
    video: Path,
    out_dir: Path,
    audit_path: Optional[Path] = None,
    samples_per_window: int = PER_WINDOW_SAMPLES,
    frame_budget: int = MAX_FRAMES,
    enable_real_vlm: bool = False,
    approve_api_cost: bool = False,
) -> Dict[str, Any]:
    phase5, video, proposal_path, out_dir = map(Path, (phase5, video, proposal_path, out_dir))
    if enable_real_vlm and not approve_api_cost:
        _fail("real VLM requires explicit approve_api_cost")
    if not enable_real_vlm and approve_api_cost:
        _fail("approve_api_cost without enable_real_vlm is not meaningful")
    if out_dir.exists():
        _fail("output directory already exists; refuse overwrite, use a new run directory")
    if out_dir.resolve().is_relative_to(phase5.resolve()):
        _fail("output directory must be outside frozen Phase5")
    if video.resolve().is_relative_to(out_dir.resolve()):
        _fail("source video cannot be in new output directory")
    audit_path = Path(audit_path) if audit_path else phase5 / "v3a_quality_audit.json"
    paths = _input_paths(phase5, audit_path)
    source_hashes = {name: _sha(path) for name, path in paths.items()}
    story, plan, audit = (_load(paths[x]) for x in ("story", "plan", "audit"))
    edl = json.loads(paths["edl"].read_text(encoding="utf-8"))
    if not isinstance(edl, list):
        _fail("EDL must be an array")
    proposal = _load(proposal_path)
    manifest = _load(phase5 / "phase5_manifest.json")
    task = validate_stage3_inputs(
        proposal, story, plan, edl, audit, source_hashes,
        video_path=video, manifest=manifest,
    )
    media = probe_video(video)
    _validate_bounds(task, media, per_window=samples_per_window, max_frames=frame_budget)
    # Validate all inputs and media before touching output directory.
    out_dir.mkdir(parents=True)
    windows, store = sample_media(
        task, media, frame_dir=out_dir / "frames",
        samples_per_window=samples_per_window, frame_budget=frame_budget,
    )
    store.write_manifest(out_dir / "frame_manifest.json")
    contact_sheet = _make_contact_sheet(windows, out_dir / "contact_sheet.jpg")
    observations, api_report = _observe_windows(
        windows, task_id=str(task["task_id"]), enable_real_vlm=enable_real_vlm,
    )
    report: Dict[str, Any] = {
        "schema": SCHEMA, "mode": "REAL_VLM_OBSERVATION" if enable_real_vlm else "FRAMES_ONLY",
        "match_id": story.get("match_id"), "task_id": task["task_id"],
        "issue_kind": task["issue_kind"], "issue_target": task["issue_target"],
        "source_sha256": source_hashes, "proposal_sha256": _sha(proposal_path),
        "video": {
            **media.to_dict(),
            "mtime_ns": video.stat().st_mtime_ns,
            "note": "Video identity is original Phase5 path and file metadata, not a full-video SHA.",
        },
        "score_anchor_sec": task.get("score_anchor_sec"),
        "score_anchor_kind": "score_confirmation_only_not_goal_action",
        "search_windows": windows, "contact_sheet": contact_sheet,
        "frame_budget_used": store.budget.used,
        "frame_budget_max": store.budget.max_frames,
        "vlm_observations": observations, "vlm_execution": api_report,
        "negative_goal_atom_used_as_truth": False,
        "semantic_coverage": "UNKNOWN",
        "first_live_goal_verified": False,
        "edl_modified": False, "render_ready": False,
        "release_decision": "NOT_AUTHORIZED",
        "next_action": "manual_contact_sheet_review_then_local_live_video_probe",
        "note": "Sparse frames are reconnaissance; absence of goal in samples is NOT evidence that no goal exists. VLM observations alone cannot prove first LIVE.",
    }
    dest = out_dir / "stage3_evidence.json"
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="V3-A Stage-3 bounded video evidence search")
    p.add_argument("--phase5-dir", type=Path, required=True)
    p.add_argument("--proposal", type=Path, required=True)
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--audit", type=Path, default=None)
    p.add_argument("--samples-per-window", type=int, default=PER_WINDOW_SAMPLES)
    p.add_argument("--frame-budget", type=int, default=MAX_FRAMES)
    p.add_argument("--enable-real-vlm", action="store_true")
    p.add_argument("--approve-api-cost", action="store_true")
    args = p.parse_args(argv)
    try:
        report = run(
            phase5=args.phase5_dir, proposal_path=args.proposal,
            video=args.video, out_dir=args.out_dir, audit_path=args.audit,
            samples_per_window=args.samples_per_window, frame_budget=args.frame_budget,
            enable_real_vlm=args.enable_real_vlm,
            approve_api_cost=args.approve_api_cost,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        p.error(f"Stage-3 refused or failed: {type(exc).__name__}: {exc}")
    print(json.dumps({
        "report": str(args.out_dir / "stage3_evidence.json"),
        "mode": report["mode"], "frames": report["frame_budget_used"],
        "first_live_goal_verified": False, "edl_modified": False, "render_ready": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
