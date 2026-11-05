"""Fresh V3-R -> V3-A end-to-end orchestration (no historical intermediate inputs).

The human causal file is consumed ONLY by closed_loop_cli.run_match's atomic
extractor. Historical artifacts are read solely for post-run comparison.
The default is zero-paid-API degraded verification, not a model success claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Sequence


STAGE_FILES = {
    "atomic_enrichment": "01_enrich/events_enriched.json",
    "strip_831": "02_strip831/strip_A_original.json",
    "v1_adapter": "03_v1_adapt/predicted_causal.json",
    "replay_filtered_prediction": "03_v1_adapt/predicted_causal_live_goals_only.json",
    "t01": "04_phase5/t01_story.json",
    "rule_composer": "04_phase5/story_plan.json",
    "v3r_edl": "04_phase5/candidate_edl.json",
    "v3r_video": "04_phase5/story_clean.mp4",
    "v3a_edl": "05_v3a/best_candidate_edl.json",
    "v3a_video": "06_candidate_render/story_clean.mp4",
}
HISTORY_FILES = {
    "atomic_enrichment": "01_enrich/events_enriched.json",
    "strip_831": "02_strip831/strip_A_original.json",
    "v1_adapter": "03_v1_adapt/predicted_causal.json",
    "replay_filtered_prediction": "03_v1_adapt/predicted_causal_live_goals_only.json",
    "t01": "04_phase5/t01_story.json",
    "rule_composer": "04_phase5/story_plan.json",
    "v3r_edl": "04_phase5/candidate_edl.json",
    "polish_edl_reference_only": "04_phase5_p1_polish/candidate_edl.json",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> Dict[str, Any]:
    p = Path(path).resolve()
    if not p.is_file():
        return {"path": str(p), "exists": False, "sha256": None}
    return {"path": str(p), "exists": True, "size_bytes": p.stat().st_size,
            "sha256": sha256_file(p)}


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def edl_rows(obj: Any) -> list[dict[str, Any]]:
    if isinstance(obj, list):
        return [row for row in obj if isinstance(row, dict)]
    if isinstance(obj, dict):
        for key in ("segments", "edl", "rows"):
            if isinstance(obj.get(key), list):
                return [row for row in obj[key] if isinstance(row, dict)]
    raise ValueError("EDL must be a list or an object containing segment rows")


def validate_render_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Renderer does not honor include_in_cut itself: filter here explicitly."""
    active = [dict(row) for row in rows if row.get("include_in_cut", True) is not False]
    if not active:
        raise ValueError("Refusing to render an empty EDL")
    ids: set[str] = set()
    for row in active:
        sid = str(row.get("segment_id") or "")
        if not sid or sid in ids:
            raise ValueError(f"Duplicate or missing active segment_id: {sid!r}")
        ids.add(sid)
        if row.get("is_replay") is True or str(row.get("first_live_status") or "").upper() in {
            "SUSPECTED_REPLAY", "CONFIRMED_REPLAY", "REPLAY",
        }:
            raise ValueError(f"Refusing explicit replay-risk segment: {sid}")
        a, b = row.get("media_in"), row.get("media_out")
        if (a is None) != (b is None):
            raise ValueError(f"Partial media window: {sid}")
        if a is not None and (float(a) < 0 or float(b) <= float(a)):
            raise ValueError(f"Invalid media window: {sid}")
    # Reuse the existing P0 duplicate-goal detector; do not create new heuristics.
    from .self_revise_agent import find_duplicate_goal_cuts
    duplicates = find_duplicate_goal_cuts(active)
    if duplicates:
        raise ValueError(f"Refusing duplicate goal cuts: {duplicates}")
    return active


def historical_trace(history_root: Optional[Path], sources: Dict[str, Path]) -> Dict[str, Any]:
    """Read-only provenance; historical intermediates never enter algorithm calls."""
    if history_root is None:
        return {"available": False, "reason": "no_history_root_provided"}
    root = Path(history_root).resolve()
    report = root / "01_enrich/enrich_report.json"
    trace: Dict[str, Any] = {"available": root.is_dir(), "history_root": str(root),
                             "enrich_report": str(report), "historical_sources": {},
                             "read_only": True}
    if report.is_file():
        doc = read_json(report)
        for key, field in (("events", "source_events"), ("causal_atoms", "source_causal_atoms_only")):
            val = doc.get(field)
            trace["historical_sources"][key] = {
                "path": val,
                "same_as_requested": Path(val).resolve() == sources[key].resolve() if val else None,
            }
    phase5_manifest = root / "04_phase5/phase5_manifest.json"
    if phase5_manifest.is_file():
        doc = read_json(phase5_manifest)
        val = (doc.get("inputs") or {}).get("video")
        trace["historical_sources"]["video"] = {
            "path": val,
            "same_as_requested": Path(val).resolve() == sources["video"].resolve() if val else None,
        }
    return trace


def compare_history(run_root: Path, history_root: Optional[Path]) -> Dict[str, Any]:
    if history_root is None:
        return {"available": False}
    old_root = Path(history_root).resolve()
    results: Dict[str, Any] = {"available": old_root.is_dir(), "comparison_only": True,
                               "history_root": str(old_root), "files": {}}
    for key, rel in HISTORY_FILES.items():
        old = file_record(old_root / rel)
        new = file_record(run_root / STAGE_FILES[key]) if key in STAGE_FILES else None
        results["files"][key] = {"historical": old, "fresh": new,
                                  "byte_identical": (old["sha256"] == new["sha256"]
                                                     if new and old["exists"] and new["exists"] else None)}
    return results


def git_info(repo_root: Path) -> Dict[str, Any]:
    def git(*args: str) -> Optional[str]:
        p = subprocess.run(["git", "-C", str(repo_root), *args],
                           text=True, capture_output=True, check=False)
        return p.stdout.strip() if p.returncode == 0 else None
    status = git("status", "--porcelain")
    return {"commit": git("rev-parse", "HEAD"), "dirty": None if status is None else bool(status)}


def preflight_real_api(*, max_calls: int, max_cost_usd: float, max_completion_tokens: int) -> Dict[str, Any]:
    """Check real Planner/VLM endpoint configuration before expensive video work.

    This sends no HTTP requests, does not expose credentials, and does not
    claim the endpoint is reachable. The budget is an estimate, not a bill cap.
    """
    from story_video_agent.api_provider import ApiProvider
    from .remote_vlm_verify import apply_trial_env_overrides

    apply_trial_env_overrides(
        max_calls=max_calls, max_cost_usd=max_cost_usd,
        max_completion_tokens=max_completion_tokens, disable_thinking=True,
    )
    provider = ApiProvider(
        require_real=True, force_mock=False,
        max_calls=max_calls, max_cost_usd=max_cost_usd,
        max_completion_tokens=max_completion_tokens,
        required_roles=("planner", "vision"),
    )
    status = provider.status()
    if not status.get("planner_ready") or not status.get("vision_ready"):
        raise RuntimeError("Real Planner/VLM API configuration incomplete")
    return {
        "configured": True,
        "http_attempts": 0,
        "planner": status["planner"],
        "vision": status["vision"],
        "max_calls": status["max_calls"],
        "max_cost_usd_estimate": status["max_cost_usd"],
        "max_completion_tokens": status["max_completion_tokens"],
        "cost_disclaimer": status["cost_disclaimer"],
        "note": "Configuration check only; no network or model response was tested.",
    }


def run_fresh_e2e(
    *, match_id: str, events: Path, causal_atoms: Path, video: Path,
    out_dir: Path, algo_root: Path, history_root: Optional[Path] = None,
    enable_real_api: bool = False, i_approve_budget: bool = False,
    max_rounds: int = 3, max_calls: int = 24, max_cost_usd: float = 0.30,
    max_completion_tokens: int = 2048,
) -> Dict[str, Any]:
    from .closed_loop_cli import run_match
    from .self_revise_agent import run_self_revise
    from story_video_agent.phase5_delivery import render_dual_delivery

    if enable_real_api != i_approve_budget:
        raise ValueError("Real API requires BOTH enable_real_api and i_approve_budget")
    if max_rounds < 1 or max_rounds > 3 or max_calls < 1 or max_cost_usd <= 0:
        raise ValueError("Invalid round/call/cost limits")
    root = Path(out_dir).resolve()
    sources = {"events": Path(events).resolve(), "causal_atoms": Path(causal_atoms).resolve(),
               "video": Path(video).resolve()}
    for key, path in sources.items():
        if not path.is_file():
            raise FileNotFoundError(f"Missing {key}: {path}")
        if path == root or root in path.parents:
            raise ValueError("Output directory cannot contain input sources")
    if sources["events"].name == "events_enriched.json" or "01_enrich" in sources["events"].parts:
        raise ValueError("Raw events required; enriched historical events are forbidden")
    if sources["causal_atoms"].name.startswith("predicted_causal") or "03_v1_adapt" in sources["causal_atoms"].parts:
        raise ValueError("Raw human causal file required for atom extraction, not predicted chains")
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"Fresh output directory must be empty: {root}")
    if history_root is not None and root == Path(history_root).resolve():
        raise ValueError("Cannot overwrite historical run root")
    root.mkdir(parents=True, exist_ok=True)
    report: Dict[str, Any] = {"schema": "v3a_fresh_e2e_v1", "status": "running",
                              "match_id": match_id, "out_dir": str(root),
                              "api_mode": "real" if enable_real_api else "offline_degraded",
                              "render_ready": False, "release_decision": "NOT_AUTHORIZED"}
    try:
        # The human causal file is only handed to the atomic enrichment stage.
        if enable_real_api:
            report["api_preflight"] = preflight_real_api(
                max_calls=max_calls, max_cost_usd=max_cost_usd,
                max_completion_tokens=max_completion_tokens,
            )
            write_json(root / "api_preflight.json", report["api_preflight"])
        report["sources"] = {key: file_record(path) for key, path in sources.items()}
        report["execution_plan"] = {
            "algo_root": str(Path(algo_root).resolve()),
            "settings": {"strip_profile": "production", "rule_composer_use_llm": False,
                         "max_rounds": max_rounds, "max_calls": max_calls,
                         "max_cost_usd": max_cost_usd, "max_completion_tokens": max_completion_tokens},
            "stages": [
                {"name": "atomic_enrichment", "implementation": "atomic_event_enrich.enrich_files",
                 "inputs": ["sources.events", "sources.causal_atoms"], "output": "01_enrich/events_enriched.json"},
                {"name": "strip_831", "implementation": "v2_strip_reinfer.run_strip_predict/AlgoStripAdapter",
                 "inputs": ["01_enrich/events_enriched.json"], "output": "02_strip831/strip_A_original.json"},
                {"name": "v1_adapter", "implementation": "v1_causal_adapter.strip_chains_to_v1_causal",
                 "inputs": ["02_strip831/strip_A_original.json", "01_enrich/events_enriched.json"],
                 "output": "03_v1_adapt/predicted_causal_live_goals_only.json"},
                {"name": "v3r", "implementation": "phase5_pipeline.run_phase5",
                 "inputs": ["03_v1_adapt/predicted_causal_live_goals_only.json", "01_enrich/events_enriched.json", "sources.video"],
                 "output": "04_phase5/candidate_edl.json"},
                {"name": "v3a", "implementation": "self_revise_agent.run_self_revise",
                 "inputs": ["04_phase5/candidate_edl.json", "03_v1_adapt/predicted_causal_live_goals_only.json", "sources.video"],
                 "output": "05_v3a/best_candidate_edl.json"},
                {"name": "render", "implementation": "phase5_delivery.render_dual_delivery",
                 "inputs": ["05_v3a/best_candidate_edl.json", "sources.video"],
                 "output": "06_candidate_render/story_clean.mp4"},
            ],
            "limitation": "atomic_event_enrich currently infers atom replay flag from human chain is_replay; do not claim fully independent video LIVE classification",
        }
        report["historical_trace"] = historical_trace(history_root, sources)
        report["git"] = git_info(Path(algo_root).resolve().parent)
        write_json(root / "00_input_manifest.json", report)

        baseline_root = root / "01_to_04_fresh_v3r"
        run_match(match_id=match_id, events_path=sources["events"],
                  causal_atoms_path=sources["causal_atoms"], video=sources["video"],
                  out_dir=baseline_root, algo_root=Path(algo_root), skip_render=False)
        phase5 = baseline_root / "04_phase5"
        predicted = baseline_root / "03_v1_adapt/predicted_causal_live_goals_only.json"
        for rel in STAGE_FILES.values():
            if rel.startswith("05_v3a") or rel.startswith("06_candidate"):
                continue
            p = baseline_root / rel
            if not p.is_file():
                raise RuntimeError(f"Fresh upstream stage missing output: {p}")
        manifest = read_json(phase5 / "phase5_manifest.json")
        actual_inputs = manifest.get("inputs") or {}
        if Path(actual_inputs.get("video", "")).resolve() != sources["video"]:
            raise RuntimeError("Phase5 did not consume this run's raw video")
        if Path(actual_inputs.get("causal", "")).resolve() != predicted.resolve():
            raise RuntimeError("Phase5 did not consume this run's predicted causal")
        if Path(actual_inputs.get("events", "")).resolve() != (baseline_root / "01_enrich/events_enriched.json").resolve():
            raise RuntimeError("Phase5 did not consume this run's enriched events")
        report["v3r"] = {"phase5_dir": str(phase5), "manifest": str(phase5 / "phase5_manifest.json")}
        write_json(root / "e2e_progress.json", report)

        # No history Stage-2 proposal/audit/cache, no automatic P1-polish switch.
        agent_dir = root / "05_v3a"
        agent = run_self_revise(
            phase5_dir=phase5, out_dir=agent_dir, video=sources["video"],
            predicted_causal=predicted, stage2_proposal=None, audit_path=None,
            prefer_p1_polish=False, enable_real_api=enable_real_api,
            i_approve_budget=i_approve_budget, max_rounds=max_rounds,
            max_calls=max_calls, max_cost_usd=max_cost_usd,
            max_completion_tokens=max_completion_tokens,
            allow_degraded_offline=not enable_real_api, skip_vlm=not enable_real_api,
            stop_on_quality_threshold=False,
        )
        if Path(agent.get("phase5_dir", "")).resolve() != phase5.resolve():
            raise RuntimeError("V3-A switched away from the fresh V3-R baseline")
        baseline_edl = edl_rows(read_json(phase5 / "candidate_edl.json"))
        best_edl = edl_rows(read_json(agent_dir / "best_candidate_edl.json"))
        if not agent.get("accepted_any_revision") and best_edl != baseline_edl:
            raise RuntimeError("No accepted revision but best EDL differs from fresh V3-R")
        # Unsafe accepted revisions are preserved for audit but never rendered.
        # A rejected candidate falls back to the freshly generated V3-R EDL.
        render_selection = "agent_candidate" if agent.get("accepted_any_revision") else "baseline_unchanged"
        render_edl = best_edl
        try:
            active = validate_render_rows(render_edl)
        except ValueError as exc:
            if not agent.get("accepted_any_revision"):
                raise  # unsafe baseline is a real failure, not a successful fallback
            render_selection = "baseline_safety_fallback"
            report["candidate_rejected_reason"] = f"{type(exc).__name__}: {exc}"
            render_edl = baseline_edl
            active = validate_render_rows(render_edl)
        report["render_selection"] = render_selection
        render_dir = root / "06_candidate_render"
        write_json(render_dir / "candidate_edl.json", render_edl)
        rendered = render_dual_delivery(
            plan=read_json(phase5 / "story_plan.json"), video=sources["video"],
            out_dir=render_dir, delivery_edl=active,
        )
        for name in ("story_clean.mp4", "story_qc.mp4"):
            if not (render_dir / name).is_file():
                raise RuntimeError(f"Candidate render missing {name}")
        usage = agent.get("api_usage") or {}
        rounds = agent.get("rounds") or []
        real_planner = any(r.get("planner_provider_mode") == "real" for r in rounds)
        real_vision = any(r.get("vlm_any_real_ok") for r in rounds)
        real_verifier = any(r.get("verifier_provider_mode") == "real" for r in rounds)
        report["agent"] = {"summary": str(agent_dir / "self_revise_summary.json"),
                           "best_round": agent.get("best_round"),
                           "accepted_any_revision": bool(agent.get("accepted_any_revision")),
                           "agent_claimed_success": bool(agent.get("agent_claimed_success")),
                           "api_usage": usage,
                           "real_planner": real_planner,
                           "real_vision": real_vision,
                           "real_verifier": real_verifier,
                           "real_multimodal_round_trip": real_planner and real_vision and real_verifier,
                           "rounds_executed": agent.get("rounds_executed"),
                           "abort_reason": agent.get("abort_reason")}
        report["render"] = rendered
        report["lineage"] = {
            key: file_record((baseline_root if key not in {"v3a_edl", "v3a_video"} else root) / rel)
            for key, rel in STAGE_FILES.items()
        }
        report["historical_comparison"] = compare_history(baseline_root, history_root)
        report["status"] = (
            "completed_real_multimodal_candidate_only"
            if enable_real_api and report["agent"]["real_multimodal_round_trip"]
            else "completed_degraded_candidate_only"
        )
        report["note"] = (
            "The candidate is NOT first-LIVE certified or production ready. "
            "Real API configured does not imply successful real model participation. "
            "Model cost is an estimate, not an invoice cap. "
            "Historical P1 polish is comparison-only, not a pipeline input."
        )
        write_json(root / "fresh_e2e_summary.json", report)
        return report
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        write_json(root / "fresh_e2e_summary.json", report)
        raise


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Fresh atomic → 8.31 → V3-R → V3-A → candidate MP4")
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--causal-atoms", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--algo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--history-root", type=Path, default=None)
    parser.add_argument("--enable-real-api", action="store_true")
    parser.add_argument("--i-approve-budget", action="store_true")
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--max-calls", type=int, default=24)
    parser.add_argument("--max-cost-usd", type=float, default=0.30)
    parser.add_argument("--max-completion-tokens", type=int, default=2048)
    args = parser.parse_args(argv)
    result = run_fresh_e2e(**vars(args))
    print(json.dumps({"status": result["status"], "out_dir": result["out_dir"],
                      "agent": result.get("agent"), "render_ready": False},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
