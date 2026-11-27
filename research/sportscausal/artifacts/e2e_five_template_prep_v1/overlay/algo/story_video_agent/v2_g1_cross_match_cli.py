"""G1 cross-match generic entrypoint (zero-cost structure dry-run).

Requires explicit --match-id/--video/--events/--out-dir.
Never defaults to Croatia R22 / croatia_vlm_probe.
Never upgrades render_ready. No paid API in default path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from story_video_agent.v2_event_adapter import INPUT_SOURCES, load_events_json, planner_event_digest
from story_video_agent.v2_g0_cross_match_preflight import (
    assert_match_id_consistent,
    assert_verify_cache_entry,
    build_strip_provenance,
    cache_isolation_key,
    reject_forbidden_input_path,
    reject_forbidden_payload,
    sha256_file,
    validate_strip_bundle_provenance,
    write_json,
)
from story_video_agent.v2_generic_edl_composer import compose_generic_t01_edl, refuse_croatia_edl_builder
from story_video_agent.v2_missing_goal_detector import detect_missing_goals
from story_video_agent.v2_score_transitions import analyze_last_deficit_arcs
from story_video_agent.v2_strip_adapter import adapt_strip_bundle
from story_video_agent.v2_strip_reinfer import load_or_run_baseline_A

DEFAULT_ALGO = Path("/data2/lpy1/causal-chain2/8.31causal_chain")


def _git_sha() -> str:
    here = Path(__file__).resolve().parent
    for root in [here, *here.parents]:
        if (root / ".git").exists():
            try:
                return subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=str(root), text=True, stderr=subprocess.DEVNULL
                ).strip()
            except Exception:  # noqa: BLE001
                break
    return "unknown"


def _algo_version(algo_root: Path) -> str:
    # Prefer git SHA of independent 8.31 tree; fall back to path marker.
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(algo_root),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:  # noqa: BLE001
        return f"path:{algo_root.name}"


def _score_timeline_from_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    prev = None
    timed = [e for e in events if e.get("score_pair") and e.get("event_time_sec") is not None]
    timed.sort(key=lambda e: float(e["event_time_sec"]))
    for e in timed:
        pair = e.get("score_pair")
        if not pair or len(pair) != 2:
            continue
        score = (int(pair[0]), int(pair[1]))
        if prev == score:
            continue
        # Drop obviously invalid OCR (negative already impossible; huge already filtered)
        if score[0] > 20 or score[1] > 20:
            continue
        rows.append(
            {
                "score": score,
                "left": score[0],
                "right": score[1],
                "media_start_sec": float(e["event_time_sec"]),
                "event_id": e.get("event_id"),
            }
        )
        prev = score
    return rows


def _build_story_graph(
    *,
    match_id: str,
    selected: Optional[Dict[str, Any]],
    arc_status: str,
    missing: Dict[str, Any],
    strips: List[Dict[str, Any]],
) -> Dict[str, Any]:
    nodes: List[Dict[str, Any]] = []
    if selected:
        for role, score_key in (
            ("opening_deficit", "deficit_score"),
            ("equalizer", "equalizer_score"),
            ("go_ahead", "go_ahead_score"),
        ):
            nodes.append(
                {
                    "node_id": f"arc_{role}",
                    "role": role,
                    "score_after": selected.get(score_key),
                    "score_confirmation_sec": (selected.get("score_confirmation_sec") or {}).get(
                        role.replace("opening_", "")
                        if role.startswith("opening_")
                        else role
                    )
                    if role != "opening_deficit"
                    else (selected.get("score_confirmation_sec") or {}).get("deficit"),
                    "verification_status": "unresolved",
                    "verification_level": "score_only",
                }
            )
    # Fix opening_deficit confirmation key
    if nodes and selected:
        nodes[0]["score_confirmation_sec"] = (selected.get("score_confirmation_sec") or {}).get("deficit")
        nodes[1]["score_confirmation_sec"] = (selected.get("score_confirmation_sec") or {}).get("equalizer")
        nodes[2]["score_confirmation_sec"] = (selected.get("score_confirmation_sec") or {}).get("go_ahead")

    for c in missing.get("missing_goal_candidates") or []:
        nodes.append(
            {
                "node_id": c.get("candidate_id"),
                "role": "missing_goal_candidate",
                "score_before": c.get("score_before"),
                "score_after": c.get("score_after"),
                "score_confirmation_sec": c.get("score_confirmation_time"),
                "verification_status": c.get("verification_status") or "unresolved",
                "verification_level": "score_only",
                "nearby_predicted_strip_ids": c.get("nearby_predicted_strip_ids") or [],
            }
        )

    relations = []
    if selected and len(nodes) >= 3:
        relations.extend(
            [
                {
                    "source": "arc_opening_deficit",
                    "target": "arc_equalizer",
                    "type": "narrative",
                    "explanation": "Comeback arc equalizer after deficit (not causal proof)",
                },
                {
                    "source": "arc_equalizer",
                    "target": "arc_go_ahead",
                    "type": "narrative",
                    "explanation": "Comeback arc go-ahead after equalizer (not causal proof)",
                },
            ]
        )

    return {
        "schema": "v2_g1_story_graph_v1",
        "match_id": match_id,
        "status": arc_status,
        "protagonist_side": (selected or {}).get("protagonist_side"),
        "protagonist_team_name": (selected or {}).get("protagonist_team_name"),
        "nodes": nodes,
        "relations": relations,
        "n_predicted_strips": len(strips),
        "render_ready": False,
    }


def run_g1_dry(
    *,
    match_id: str,
    video: Path,
    events: Path,
    out_dir: Path,
    algo_root: Path = DEFAULT_ALGO,
    input_source: str = "human_corrected",
    reuse_verify_cache: Optional[Path] = None,
    skip_strip_reinfer: bool = False,
    existing_strip_json: Optional[Path] = None,
) -> Dict[str, Any]:
    t0 = time.time()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- Input gates (before any model side effects) ---
    for label, path in (("video", video), ("events", events)):
        if not Path(path).exists():
            report = {
                "status": "aborted_missing_input",
                "missing": label,
                "path": str(path),
                "render_ready": False,
            }
            write_json(out_dir / "cli_report.json", report)
            return report

    gate = reject_forbidden_input_path(events)
    if not gate.get("ok"):
        report = {"status": "aborted_forbidden_input", "gate": gate, "render_ready": False}
        write_json(out_dir / "cli_report.json", report)
        return report

    # Peek payload keys without going through adapter first (alias/causal catch)
    raw_peek = json.loads(Path(events).read_text(encoding="utf-8"))
    payload_gate = reject_forbidden_payload(raw_peek if isinstance(raw_peek, dict) else {})
    if not payload_gate.get("ok"):
        report = {"status": "aborted_forbidden_payload", "gate": payload_gate, "render_ready": False}
        write_json(out_dir / "cli_report.json", report)
        return report

    mid_gate = assert_match_id_consistent(
        cli_match_id=match_id, events_match_id=str(raw_peek.get("match_id") or "")
    )
    if not mid_gate.get("ok"):
        report = {"status": "aborted_match_id_mismatch", "gate": mid_gate, "render_ready": False}
        write_json(out_dir / "cli_report.json", report)
        return report

    events_sha = sha256_file(Path(events))
    # Reuse prior video hash if present for this out_dir to avoid rehashing 5GB each step.
    hash_cache = out_dir / "video_sha256.txt"
    if hash_cache.is_file() and hash_cache.stat().st_size > 0:
        video_sha = hash_cache.read_text(encoding="utf-8").strip().split()[0]
        video_hash_source = "cached_file"
    else:
        video_sha = sha256_file(Path(video))
        hash_cache.write_text(video_sha + "\n", encoding="utf-8")
        video_hash_source = "computed"

    event_bundle = load_events_json(Path(events), input_source=input_source)
    digest = planner_event_digest(event_bundle)
    write_json(out_dir / "event_digest.json", digest)

    timeline = _score_timeline_from_events(list(event_bundle.get("events") or []))
    write_json(out_dir / "score_path.json", {"timeline": timeline, "n": len(timeline)})

    arc_pack = analyze_last_deficit_arcs(timeline, team_names=event_bundle.get("team_names") or {})
    write_json(out_dir / "selected_arc.json", arc_pack)
    selected = arc_pack.get("selected_arc")
    arc_status = str(arc_pack.get("status") or "unresolved")

    # --- Predicted strips (raw-events reinfer OR validated existing non-gold) ---
    strip_chains: List[Dict[str, Any]] = []
    strip_meta: Dict[str, Any] = {"used": False}
    run_id = f"g1_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    algo_ver = _algo_version(Path(algo_root))

    if existing_strip_json is not None:
        raw_strip = json.loads(Path(existing_strip_json).read_text(encoding="utf-8"))
        v = validate_strip_bundle_provenance(raw_strip)
        if not v.get("ok"):
            report = {
                "status": "aborted_gold_or_invalid_strips",
                "gate": v,
                "path": str(existing_strip_json),
                "render_ready": False,
            }
            write_json(out_dir / "cli_report.json", report)
            return report
        adapted = adapt_strip_bundle(
            Path(existing_strip_json), events_path=Path(events), match_id=match_id
        )
        strip_chains = list(adapted.get("chains") or [])
        strip_meta = {
            "used": True,
            "source": "existing_validated",
            "path": str(existing_strip_json),
            "n": len(strip_chains),
        }
        pred_mode = str(raw_strip.get("mode") or "external_predicted")
    elif skip_strip_reinfer:
        pred_mode = "skipped_no_strips"
        strip_meta = {"used": False, "source": "skipped"}
    else:
        strip_dir = out_dir / "strip_reinfer"
        strip_raw = load_or_run_baseline_A(
            events_path=Path(events),
            out_dir=strip_dir,
            algo_root=Path(algo_root),
            match_id=match_id,
        )
        v = validate_strip_bundle_provenance(strip_raw)
        if not v.get("ok"):
            report = {"status": "aborted_reinfer_strip_invalid", "gate": v, "render_ready": False}
            write_json(out_dir / "cli_report.json", report)
            return report
        adapted = adapt_strip_bundle(
            strip_dir / "strip_A_original.json", events_path=Path(events), match_id=match_id
        )
        write_json(out_dir / "predicted_strip_chains.json", adapted)
        strip_chains = list(adapted.get("chains") or [])
        strip_meta = {
            "used": True,
            "source": "reinfer_raw_events",
            "algo_root": str(algo_root),
            "n": len(strip_chains),
            "category_counts": adapted.get("category_counts"),
        }
        pred_mode = str(strip_raw.get("mode") or "reinfer_A_original")

    try:
        strip_prov = build_strip_provenance(
            run_id=run_id,
            events_sha256=events_sha,
            algo_root=str(algo_root),
            algo_version=algo_ver,
            prediction_mode=pred_mode,
        )
    except ValueError as exc:
        report = {"status": "aborted_strip_provenance", "error": str(exc), "render_ready": False}
        write_json(out_dir / "cli_report.json", report)
        return report

    expected_cache = {
        "match_id": match_id,
        "video_sha256": video_sha,
        "events_sha256": events_sha,
        "strip_provenance": strip_prov["strip_provenance"],
    }
    cache_key = cache_isolation_key(**expected_cache)

    # Verify-cache: fail closed unless provenance binds
    cache_rejects: List[Dict[str, Any]] = []
    if reuse_verify_cache is not None:
        root = Path(reuse_verify_cache)
        for child in sorted(root.glob("verify_*")):
            eid = child.name.replace("verify_", "", 1)
            chk = assert_verify_cache_entry(expected=expected_cache, cache_dir=child, event_id=eid)
            if not chk.get("ok"):
                cache_rejects.append(chk)
        write_json(out_dir / "verify_cache_audit.json", {"rejects": cache_rejects, "n": len(cache_rejects)})
        # Never apply foreign/legacy cache in G1 dry-run
        if cache_rejects:
            # Continue dry-run but do not upgrade any goal from cache
            pass

    missing = detect_missing_goals(
        events=list(event_bundle.get("events") or []),
        predicted_strips=strip_chains,
        match_id=match_id,
    )
    # Force unresolved: G1 zero-API never video-verifies
    for c in missing.get("missing_goal_candidates") or []:
        c["verification_status"] = "unresolved"
        c["verification_level"] = "score_only"
        c["render_ready"] = False
    write_json(out_dir / "missing_goal_candidates.json", missing)

    story_graph = _build_story_graph(
        match_id=match_id,
        selected=selected,
        arc_status=arc_status,
        missing=missing,
        strips=strip_chains,
    )
    write_json(out_dir / "story_graph.json", story_graph)

    # Refuse Croatia EDL path for this match (raise = correctly blocked).
    croatia_edl_guard = []
    for mod in (
        "v2_strip_guided_r2_6_build_edl",
        "v2_strip_guided_r2_8_build_edl",
        "v2_strip_guided_r2_9_build_edl",
    ):
        try:
            refuse_croatia_edl_builder(mod, match_id=match_id)
            croatia_edl_guard.append({"module": mod, "refused": False, "note": "allowed_for_croatia_legacy"})
        except Exception as exc:  # noqa: BLE001
            croatia_edl_guard.append({"module": mod, "refused": True, "reason": str(exc)})
    write_json(out_dir / "croatia_edl_guard.json", {"checks": croatia_edl_guard})
    croatia_edl_refused = all(bool(x.get("refused")) for x in croatia_edl_guard)

    edl = compose_generic_t01_edl(
        match_id=match_id,
        selected_arc=selected,
        arc_status=arc_status,
        team_names=event_bundle.get("team_names") or {},
        goals=[],  # no video-verified goals in zero-API dry-run
        level="structure_only",
    )
    write_json(out_dir / "candidate_edl.json", edl)

    provenance = {
        "schema": "v2_g1_run_provenance_v1",
        "match_id": match_id,
        "video": str(video),
        "events": str(events),
        "video_sha256": video_sha,
        "video_hash_source": video_hash_source,
        "events_sha256": events_sha,
        "strip_provenance": strip_prov,
        "cache_isolation_key": cache_key,
        "git_sha": _git_sha(),
        "algo_root": str(algo_root),
        "algo_version": algo_ver,
        "input_source": input_source,
        "forbidden_inputs_used": [],
        "api_calls": 0,
        "api_cost_usd": 0.0,
        "render_ready": False,
    }
    write_json(out_dir / "provenance.json", provenance)

    n_unresolved = len(missing.get("missing_goal_candidates") or [])
    report = {
        "schema": "v2_g1_cli_report_v1",
        "status": "ok_structure_dry_run",
        "match_id": match_id,
        "arc_status": arc_status,
        "protagonist_side": (selected or {}).get("protagonist_side"),
        "protagonist_team_name": (selected or {}).get("protagonist_team_name"),
        "selected_arc": selected,
        "score_path": [list(r["score"]) for r in timeline],
        "n_missing_goal_candidates": n_unresolved,
        "n_unresolved_goals": n_unresolved,
        "n_video_verified_goals": 0,
        "strip_meta": strip_meta,
        "croatia_edl_refused": croatia_edl_refused,
        "verify_cache_rejects": len(cache_rejects),
        "elapsed_sec": round(time.time() - t0, 3),
        "api_calls": 0,
        "api_cost_usd": 0.0,
        "render_ready": False,
        "note": (
            "Zero-API structure dry-run: missing goals remain unresolved; "
            "candidate_edl is structure_only; not a delivered story video"
        ),
    }
    write_json(out_dir / "cli_report.json", report)
    return report


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="V2 G1 cross-match generic dry-run (no paid API)")
    p.add_argument("--match-id", required=True)
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--events", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--algo-root", type=Path, default=DEFAULT_ALGO)
    p.add_argument("--input-source", choices=list(INPUT_SOURCES), default="human_corrected")
    p.add_argument(
        "--reuse-verify-cache",
        type=Path,
        default=None,
        help="Audited only; entries without matching provenance are rejected (never applied in G1 dry-run)",
    )
    p.add_argument("--skip-strip-reinfer", action="store_true")
    p.add_argument(
        "--existing-strip-json",
        type=Path,
        default=None,
        help="Optional non-gold predicted strip JSON (gold_clips dumps are rejected)",
    )
    p.add_argument("--real", action="store_true", help="Rejected in G1 — paid path disabled")
    args = p.parse_args(argv)

    if args.real:
        write_json(
            Path(args.out_dir) / "cli_report.json",
            {
                "status": "aborted_paid_api_disabled_in_g1",
                "render_ready": False,
                "note": "G1 forbids --real / paid VLM/LLM",
            },
        )
        return 2

    report = run_g1_dry(
        match_id=args.match_id,
        video=Path(args.video),
        events=Path(args.events),
        out_dir=Path(args.out_dir),
        algo_root=Path(args.algo_root),
        input_source=args.input_source,
        reuse_verify_cache=args.reuse_verify_cache,
        skip_strip_reinfer=bool(args.skip_strip_reinfer),
        existing_strip_json=args.existing_strip_json,
    )
    status = str(report.get("status") or "")
    if status.startswith("aborted"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
