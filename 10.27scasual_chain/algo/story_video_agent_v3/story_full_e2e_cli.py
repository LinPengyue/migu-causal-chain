"""One-click Story E2E from original event JSON + full video.

Formal raw-only inference (required):
  --source-mp4      full match video
  --events-json     delivery events JSON (not enriched)
Historical development ONLY:
  --causal-json     optional human annotated causal atoms; NOT gold-free eval

This entrypoint NEVER accepts Phase5 / EDL / story graph / initial MP4 reuse.
It always runs: raw events (optional DEV atom enrich) → strip/V1 causal
prediction with Goal Recovery → Phase5 V3-R → V3-A story loop.

Causal-chain contract (do not mix):
  - Optional user causal JSON is historical development supervision, excluded
    from raw-only / benchmark-qualified runs.
  - Predicted short causal (03_v1_adapt): strip→V1 + Goal Recovery for Phase5.
  - V3-R long story chain: produced inside Phase5 planner/graph (not the human file).

Examples:
  python -m story_video_agent_v3.story_full_e2e_cli \\
    --source-mp4 /path/match.mp4 \\
    --events-json /path/match.json \\
    --out-dir /data2/lpy1/_story_va_outputs/v3/plan2/full_e2e_A_<ts> \\
    --match-id uae_oman_dev
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .story_e2e_agent import StoryE2EInputs, run_story_e2e


FORBIDDEN_NAME_HINTS = (
    "events_enriched",
    "predicted_causal",
    "candidate_edl",
    "story_plan",
    "story_clean",
    "04_phase5",
)


def _looks_like_intermediate(path: Path) -> Optional[str]:
    name = path.name.lower()
    s = str(path).lower()
    for hint in FORBIDDEN_NAME_HINTS:
        if hint in name or f"/{hint}" in s or s.endswith(hint):
            return hint
    return None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="One-click Story Video E2E from raw events JSON + source MP4"
    )
    p.add_argument("--source-mp4", type=Path, required=True)
    p.add_argument("--events-json", type=Path, required=True,
                   help="Raw delivery events JSON (not events_enriched.json)")
    p.add_argument("--independent-atoms-json", type=Path, default=None,
                   help="Independent event-level annotations: atomic_events list, never causal/story gold")
    p.add_argument("--causal-json", type=Path, default=None,
                   help="Optional historical development-only human causal atoms; invalid for raw-only eval")
    p.add_argument("--strict-raw-only", action="store_true", default=False,
                   help="Reject any human causal annotation input (recommended for official evaluation)")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--match-id", type=str, default=None)
    p.add_argument("--algo-root", type=Path, default=None)
    p.add_argument("--max-rounds", type=int, default=1)
    p.add_argument("--no-smoke-render", action="store_true", default=False)
    p.add_argument("--enable-real-api", action="store_true", default=False)
    p.add_argument("--i-approve-budget", action="store_true", default=False)
    p.add_argument("--max-calls", type=int, default=5)
    p.add_argument("--max-cost-usd", type=float, default=0.10)
    # Explicitly rejected if passed (catch misuse).
    p.add_argument("--phase5-dir", type=Path, default=None,
                   help=argparse.SUPPRESS)
    p.add_argument("--baseline-edl", type=Path, default=None,
                   help=argparse.SUPPRESS)
    return p


def validate_inputs(args: argparse.Namespace) -> list[str]:
    errs: list[str] = []
    if args.phase5_dir is not None or args.baseline_edl is not None:
        errs.append("phase5_dir/baseline_edl_forbidden_in_full_e2e")
    if args.independent_atoms_json is not None and args.causal_json is not None:
        errs.append("independent_atoms_and_causal_gold_mutually_exclusive")
    if getattr(args, "strict_raw_only", False) and (args.causal_json is not None or args.independent_atoms_json is not None):
        errs.append("strict_raw_only_rejects_external_event_annotations")
    inputs = [
        ("source_mp4", args.source_mp4),
        ("events_json", args.events_json),
    ]
    if args.causal_json is not None:
        inputs.append(("causal_json", args.causal_json))
    if args.independent_atoms_json is not None:
        inputs.append(("independent_atoms_json", args.independent_atoms_json))
    for label, path in inputs:
        if not path.is_file():
            errs.append(f"missing_{label}:{path}")
            continue
        hint = _looks_like_intermediate(path)
        if hint and label != "source_mp4":
            errs.append(f"refusing_intermediate_input_{label}_looks_like_{hint}")
    # out_dir must not be inside an existing Phase5 tree being "reused"
    out = args.out_dir.resolve()
    for parent in [out, *out.parents]:
        if parent.name == "04_phase5":
            errs.append("out_dir_must_not_be_inside_existing_phase5")
            break
    return errs


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    errs = validate_inputs(args)
    if errs:
        print(json.dumps({"ok": False, "errors": errs}, ensure_ascii=False, indent=2))
        return 2

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    # Refuse non-empty out_dir that already has 04_phase5 (silent reuse risk).
    if (out_dir / "01_to_04_fresh_v3r" / "04_phase5" / "candidate_edl.json").is_file() or (
        out_dir / "04_phase5" / "candidate_edl.json"
    ).is_file():
        print(
            json.dumps(
                {
                    "ok": False,
                    "errors": ["out_dir_already_contains_phase5_refuse_silent_reuse"],
                    "out_dir": str(out_dir),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    match_id = args.match_id or args.events_json.stem
    algo_root = args.algo_root or Path(__file__).resolve().parents[2]

    # A legacy annotated-atom run is never a raw-only evaluation case.
    raw_only = args.causal_json is None and args.independent_atoms_json is None
    input_mode = ("RAW_EVENTS_ONLY" if raw_only else (
        "INDEPENDENT_ATOMIC_ANNOTATED" if args.independent_atoms_json is not None
        else "HUMAN_ATOM_ENRICHED_DEV"))
    # Contract note persisted for auditors.
    contract = {
        "schema": "v3a_full_e2e_input_contract_v1",
        "formal_inputs": {
            "source_mp4": str(args.source_mp4.resolve()),
            "events_json": str(args.events_json.resolve()),
            "causal_json": str(args.causal_json.resolve()) if args.causal_json else None,
            "independent_atoms_json": str(args.independent_atoms_json.resolve()) if args.independent_atoms_json else None,
        },
        "input_mode": input_mode,
        "eligible_for_raw_only_evaluation": raw_only,
        "human_annotation_atoms_used": not raw_only,
        "eligible_for_event_annotated_evaluation": args.causal_json is None,
        "causal_roles": {
            "user_causal_json": (
                "Optional DEV-only annotated atoms for legacy reproduction; "
                "never a permitted raw-only evaluation input."
            ),
            "predicted_short_causal": (
                "Algorithm strip→V1 adaptation under 03_v1_adapt; Phase5 input."
            ),
            "v3r_long_story_chain": (
                "Produced inside Phase5 planner/graph from enriched events + predicted causal."
            ),
        },
        "forbidden": [
            "phase5_dir reuse",
            "baseline_edl",
            "prebuilt story_clean.mp4",
            "events_enriched as input",
            "predicted_causal as input",
        ],
        "pipeline": (
            "atomic_enrich → strip831 → v1_adapt → phase5(V3-R) → "
            "V3-A(critic/search/revise/render/verify) → delivery_status"
        ),
    }
    (out_dir / "00_full_e2e_contract.json").write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    inp = StoryE2EInputs(
        match_json=args.events_json.resolve(),  # lineage; enrich uses events_json
        source_mp4=args.source_mp4.resolve(),
        out_dir=out_dir,
        phase5_dir=None,
        events_json=args.events_json.resolve(),
        causal_atoms_json=args.causal_json.resolve() if args.causal_json else None,
        independent_atoms_json=args.independent_atoms_json.resolve() if args.independent_atoms_json else None,
        match_id=match_id,
        algo_root=algo_root.resolve(),
        run_fresh_v3r=True,
        skip_vlm=not bool(args.enable_real_api),
        enable_real_api=bool(args.enable_real_api),
        i_approve_budget=bool(args.i_approve_budget),
        smoke_render=not bool(args.no_smoke_render),
        max_rounds=int(args.max_rounds),
        max_calls=int(args.max_calls),
        max_cost_usd=float(args.max_cost_usd),
        max_retries=0,
    )

    t0 = time.time()
    audit = run_story_e2e(inp)
    elapsed = time.time() - t0
    delivery = audit.get("delivery") or {}
    gates = audit.get("status_gates") or {}
    status = delivery.get("delivery_status") or delivery.get("delivery_label")

    # Stage presence + validity (file existence alone is insufficient).
    fresh_root = out_dir / "01_to_04_fresh_v3r"
    stage_eval = evaluate_stages(out_dir=out_dir, fresh_root=fresh_root, delivery=delivery)
    stages = {k: bool(v.get("present")) for k, v in stage_eval["stages"].items()}
    stages_valid = {k: bool(v.get("valid")) for k, v in stage_eval["stages"].items()}

    summary: Dict[str, Any] = {
        "ok": bool(audit.get("ok")) and status != "BLOCKED" and bool(stage_eval.get("all_required_valid")),
        "delivery_status": status,
        "delivery_label": delivery.get("delivery_label"),
        "blocked_reasons": delivery.get("blocked_reasons") or [],
        "out_dir": str(out_dir),
        "elapsed_sec": round(elapsed, 3),
        "decision": delivery.get("decision"),
        "final_mp4": delivery.get("final_mp4"),
        "status_gates": gates,
        "stages_present": stages,
        "stages_valid": stages_valid,
        "stage_validity": stage_eval,
        "fresh_v3r": True,
        "phase5_reuse": False,
        "input_mode": "RAW_EVENTS_ONLY" if raw_only else "HUMAN_ATOM_ENRICHED_DEV",
        "eligible_for_raw_only_evaluation": raw_only,
        "human_annotation_atoms_used": not raw_only,
        "http_calls": audit.get("http_calls"),
        "est_cost_usd": audit.get("est_cost_usd"),
        "error": audit.get("error") or stage_eval.get("blocking_errors"),
        "baseline_duplicate_audit": audit.get("baseline_duplicate_audit"),
        "goal_recovery_impact": stage_eval.get("goal_recovery_impact"),
        "first_live_visual": stage_eval.get("first_live_visual"),
        "contract": str(out_dir / "00_full_e2e_contract.json"),
    }
    (out_dir / "full_e2e_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if status == "BLOCKED" or audit.get("error"):
        return 1
    if not stages_valid.get("04_phase5_mp4"):
        return 1
    if stage_eval.get("blocking_errors"):
        return 1
    return 0


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _mp4_ok(path: Path, *, min_bytes: int = 50_000) -> bool:
    return path.is_file() and path.stat().st_size >= min_bytes


def evaluate_stages(
    *,
    out_dir: Path,
    fresh_root: Path,
    delivery: Dict[str, Any],
) -> Dict[str, Any]:
    """Validate stage outputs by content, not mere path presence."""
    stages: Dict[str, Dict[str, Any]] = {}
    blocking: list[str] = []

    enrich = fresh_root / "01_enrich" / "events_enriched.json"
    enrich_rep = fresh_root / "01_enrich" / "enrich_report.json"
    enrich_ok = False
    enrich_detail: Dict[str, Any] = {}
    if enrich.is_file() and enrich_rep.is_file():
        try:
            er = _read_json(enrich_rep)
            ev = _read_json(enrich)
            n_ev = len(ev.get("events") or []) if isinstance(ev, dict) else 0
            enrich_ok = n_ev > 0 and int(er.get("n_injected") or 0) >= 0
            enrich_detail = {
                "n_events": n_ev,
                "n_injected": er.get("n_injected"),
                "n_goal_injected": er.get("n_goal_injected"),
            }
        except Exception as exc:  # noqa: BLE001
            blocking.append(f"01_enrich_invalid:{exc}")
    stages["01_enrich"] = {"present": enrich.is_file(), "valid": enrich_ok, **enrich_detail}
    if enrich.is_file() and not enrich_ok:
        blocking.append("01_enrich_empty_or_invalid")

    strip_p = fresh_root / "02_strip831" / "strip_A_original.json"
    strip_ok = False
    strip_detail: Dict[str, Any] = {}
    if strip_p.is_file():
        try:
            st = _read_json(strip_p)
            n_ch = int(st.get("n_chains") or len(st.get("chains") or []))
            strip_ok = n_ch > 0
            strip_detail = {"n_chains": n_ch}
        except Exception as exc:  # noqa: BLE001
            blocking.append(f"02_strip831_invalid:{exc}")
    stages["02_strip831"] = {"present": strip_p.is_file(), "valid": strip_ok, **strip_detail}
    if strip_p.is_file() and not strip_ok:
        blocking.append("02_strip831_empty_chains")

    recovery_p = fresh_root / "03_v1_adapt" / "goal_recovery.json"
    impact_p = fresh_root / "03_v1_adapt" / "goal_recovery_impact.json"
    predicted_p = fresh_root / "03_v1_adapt" / "predicted_causal.json"
    live_p = fresh_root / "03_v1_adapt" / "predicted_causal_live_goals_only.json"
    v1_ok = False
    recovery_impact = None
    # None means the goal inventory was unavailable; do not silently claim
    # completeness when the recovery stage itself never ran.
    goal_actions_present: Optional[bool] = None
    v1_detail: Dict[str, Any] = {}
    if live_p.is_file() and predicted_p.is_file() and recovery_p.is_file():
        try:
            rec = _read_json(recovery_p)
            pred = _read_json(predicted_p)
            impact = _read_json(impact_p) if impact_p.is_file() else {}
            recovery_impact = impact
            n_cand = int(rec.get("n_candidates") or len(rec.get("candidates") or []))
            adapter = pred.get("v3_adapter") or {}
            entered = bool(impact.get("entered_predicted_causal")) or int(
                adapter.get("n_v3_outcome_chains") or 0
            ) > 0 or int(adapter.get("n_goal_terminals_in_adapted_chains") or 0) > 0
            # Valid when recovery file has real candidates AND adapter consumed recovery.
            v1_ok = (
                n_cand > 0
                and bool(adapter.get("goal_recovery_used"))
                and entered
                and len(pred.get("causal_chains") or []) > 0
            )
            v1_detail = {
                "n_recovery_candidates": n_cand,
                "n_with_goal_action_sec": rec.get("n_with_goal_action_sec"),
                "n_single_goal": rec.get("n_single_goal"),
                "n_unresolved_single_goals": rec.get("n_unresolved_single_goals"),
                "all_single_goal_actions_located": rec.get("all_single_goal_actions_located"),
                "goal_recovery_used": adapter.get("goal_recovery_used"),
                "entered_predicted_causal": entered,
                "n_v3_outcome_chains": adapter.get("n_v3_outcome_chains"),
                "n_goal_terminals": adapter.get("n_goal_terminals_in_adapted_chains"),
            }
            # A completed software stage is not a complete story. In
            # particular, scoreboard-only equalizers must not silently pass
            # the release-oriented stage gate just because two other goals
            # supplied action timestamps.
            single_goals = [
                c for c in (rec.get("candidates") or [])
                if c.get("single_goal_increment")
            ]
            unresolved = [
                c for c in single_goals if c.get("goal_action_sec") is None
            ]
            goal_actions_present = (
                not bool(unresolved) if single_goals else None
            )
            v1_detail["unresolved_goal_candidate_ids"] = [
                str(c.get("candidate_id")) for c in unresolved
            ]
            if unresolved:
                blocking.append("03_score_confirmed_goal_action_missing")
            if n_cand <= 0:
                blocking.append("03_goal_recovery_empty_candidates")
            if not adapter.get("goal_recovery_used"):
                blocking.append("03_goal_recovery_not_used_in_adapter")
            if not entered:
                blocking.append("03_goal_recovery_not_entered_predicted_causal")
        except Exception as exc:  # noqa: BLE001
            blocking.append(f"03_v1_adapt_invalid:{exc}")
    stages["03_v1_adapt"] = {
        "present": live_p.is_file() and recovery_p.is_file(),
        "valid": v1_ok,
        **v1_detail,
    }

    edl_p = fresh_root / "04_phase5" / "candidate_edl.json"
    mp4_p = fresh_root / "04_phase5" / "story_clean.mp4"
    edl_ok = False
    mp4_ok = _mp4_ok(mp4_p)
    edl_detail: Dict[str, Any] = {}
    if edl_p.is_file():
        try:
            edl = _read_json(edl_p)
            n_seg = len(edl) if isinstance(edl, list) else len(
                (edl.get("segments") if isinstance(edl, dict) else None) or []
            )
            from .story_edl_safety import check_source_pts_monotonic
            from .story_timeline import edl_rows
            pts = check_source_pts_monotonic(edl_rows(edl))
            edl_ok = n_seg > 0 and pts.get("ok") is True
            edl_detail = {
                "n_segments": n_seg,
                "source_pts_monotonic": bool(pts.get("ok")),
                "source_pts_breaks": pts.get("breaks") or [],
            }
            if not pts.get("ok"):
                blocking.append("04_phase5_source_pts_nonmonotonic")
        except Exception as exc:  # noqa: BLE001
            blocking.append(f"04_phase5_edl_invalid:{exc}")
    stages["04_phase5_edl"] = {"present": edl_p.is_file(), "valid": edl_ok, **edl_detail}
    stages["04_phase5_mp4"] = {
        "present": mp4_p.is_file(),
        "valid": mp4_ok,
        "bytes": mp4_p.stat().st_size if mp4_p.is_file() else 0,
    }
    if edl_p.is_file() and not edl_ok:
        blocking.append("04_phase5_edl_empty")
    if mp4_p.is_file() and not mp4_ok:
        blocking.append("04_phase5_mp4_too_small_or_missing")

    live_meta = fresh_root / "05_live_audit" / "goal_live_audit.json"
    live_vis = fresh_root / "05_live_audit" / "first_live_visual_audit.json"
    first_live_visual = None
    live_ok = False
    live_detail: Dict[str, Any] = {}
    if live_meta.is_file() and live_vis.is_file():
        try:
            meta = _read_json(live_meta)
            vis = _read_json(live_vis)
            first_live_visual = {
                "status_counts": vis.get("status_counts"),
                "n_goal_anchors": vis.get("n_goal_anchors"),
                "any_first_live_verified": vis.get("any_first_live_verified"),
                "any_replay_on_retained": vis.get("any_replay_on_retained"),
                "goals": [
                    {
                        "segment_id": g.get("segment_id"),
                        "role": g.get("role"),
                        "first_live_status": g.get("first_live_status"),
                        "media_in": g.get("media_in"),
                        "media_out": g.get("media_out"),
                        "score_confirmation_sec": g.get("score_confirmation_sec"),
                        "goal_action_sec": g.get("goal_action_sec"),
                        "score_confirm_collision": g.get("score_confirm_collision"),
                        "candidate_extracted_ok": g.get("candidate_extracted_ok"),
                        "clip_path": g.get("clip_path"),
                        "frame_paths": (g.get("frame_paths") or [])[:3],
                    }
                    for g in (vis.get("goals") or [])
                ],
            }
            # Valid evidence package: anchors audited, frames/clips attempted, no false verified claim.
            n_anch = int(vis.get("n_goal_anchors") or 0)
            false_claim = bool(vis.get("any_first_live_verified")) and int(
                (vis.get("status_counts") or {}).get("FIRST_LIVE_VERIFIED") or 0
            ) > 0 and not any(
                g.get("agent_auto_verified") and g.get("goal_action_verified_ok")
                for g in (vis.get("goals") or [])
            )
            extracted = sum(1 for g in (vis.get("goals") or []) if g.get("candidate_extracted_ok"))
            live_ok = (
                int(meta.get("n_goal_terminals") or 0) >= 0
                and n_anch > 0
                and extracted == n_anch
                and not false_claim
                and vis.get("success_claimed") is False
            )
            live_detail = {
                "n_meta_goal_terminals": meta.get("n_goal_terminals"),
                "n_visual_anchors": n_anch,
                "n_extracted": extracted,
                "status_counts": vis.get("status_counts"),
                "false_verified_claim": false_claim,
            }
            if n_anch <= 0:
                blocking.append("05_first_live_no_goal_anchors")
            if extracted < n_anch:
                blocking.append("05_first_live_incomplete_evidence_extraction")
            if false_claim:
                blocking.append("05_first_live_false_verified_claim")
        except Exception as exc:  # noqa: BLE001
            blocking.append(f"05_live_audit_invalid:{exc}")
    stages["05_live_audit"] = {
        "present": live_meta.is_file() and live_vis.is_file(),
        "valid": live_ok,
        **live_detail,
    }
    if not (live_meta.is_file() and live_vis.is_file()):
        blocking.append("05_live_audit_missing_visual_or_meta")

    delivery_p = out_dir / "99_final" / "delivery_status.json"
    final_mp4 = out_dir / "99_final" / "story_final.mp4"
    cand_mp4 = out_dir / "99_final" / "human_review_candidate" / "v3a_candidate.mp4"
    align_p = out_dir / "99_final" / "timeline_mp4_alignment.json"
    evid_p = out_dir / "99_final" / "final_goal_evidence_manifest.json"
    lineage_p = out_dir / "99_final" / "goal_lineage_report.json"
    final_ok = False
    final_detail: Dict[str, Any] = {}
    if delivery_p.is_file():
        try:
            ds = _read_json(delivery_p)
            align = _read_json(align_p) if align_p.is_file() else {}
            evid = _read_json(evid_p) if evid_p.is_file() else {}
            lineage = _read_json(lineage_p) if lineage_p.is_file() else {}
            label = ds.get("delivery_status") or ds.get("delivery_label")
            # Candidate authenticity: when HUMAN_REVIEW_REQUIRED, candidate mp4 must exist
            # and must not be identical path-only reuse without file.
            cand_ok = True
            if label == "HUMAN_REVIEW_REQUIRED":
                cand_ok = _mp4_ok(cand_mp4)
            release_flag = bool(ds.get("release_authorized"))
            release_consistent = (
                (label == "RELEASE_READY" and release_flag)
                or (label != "RELEASE_READY" and not release_flag)
            )
            evid_ok = (
                evid_p.is_file()
                and str(evid.get("label") or "") == "final_delivery"
                and int(evid.get("n_goal_anchors") or 0) > 0
                and evid.get("success_claimed") is False
            )
            # Strict coverage may be < n_goals; do not require 100% STRICT to pass
            # stage validity — but counts must be present and consistent.
            n_goals = int(lineage.get("n_final_goal_segments") or 0)
            n_strict = int(lineage.get("n_strict_complete") or lineage.get("n_structurally_traced_to_mp4") or 0)
            n_inf = int(lineage.get("n_inferred") or 0)
            n_unres = int(lineage.get("n_unresolved") or 0)
            lineage_ok = (
                lineage_p.is_file()
                and n_goals > 0
                and (n_strict + n_inf + n_unres) == n_goals
            )
            # RELEASE_READY must be justified by final EDL evidence, not V3-R history.
            release_evid_ok = True
            if label == "RELEASE_READY":
                counts = evid.get("status_counts") or {}
                release_evid_ok = (
                    int(counts.get("FIRST_LIVE_VERIFIED") or 0)
                    == int(evid.get("n_goal_anchors") or 0)
                    and bool(evid.get("all_resolved_verified"))
                )
            final_ok = (
                label in ("RELEASE_READY", "HUMAN_REVIEW_REQUIRED", "BLOCKED")
                and (label == "BLOCKED" or _mp4_ok(final_mp4))
                and (label != "HUMAN_REVIEW_REQUIRED" or cand_ok)
                and (label == "BLOCKED" or align.get("aligned") is True)
                and release_consistent
                and evid_ok
                and lineage_ok
                and release_evid_ok
            )
            # Explicit: never treat HUMAN_REVIEW as auto-release success.
            if label == "HUMAN_REVIEW_REQUIRED" and ds.get("release_authorized"):
                final_ok = False
                blocking.append("99_human_review_cannot_set_release_authorized")
            if label == "HUMAN_REVIEW_REQUIRED" and not cand_ok:
                blocking.append("99_human_review_candidate_mp4_missing_or_tiny")
            if label != "BLOCKED" and align_p.is_file() and align.get("aligned") is not True:
                blocking.append("99_edl_mp4_not_aligned")
            if not evid_ok:
                blocking.append("99_final_goal_evidence_manifest_missing_or_invalid")
            if not lineage_ok:
                blocking.append("99_goal_lineage_incomplete_or_missing")
            if label == "RELEASE_READY" and not release_evid_ok:
                blocking.append("99_release_ready_without_final_edl_first_live_verified")
            # UNRESOLVED must not be auto-upgraded in manifest.
            if any(
                g.get("first_live_status") == "FIRST_LIVE_VERIFIED"
                and not (g.get("agent_auto_verified") and g.get("goal_action_verified_ok"))
                for g in (evid.get("goals") or [])
            ):
                final_ok = False
                blocking.append("99_false_first_live_verified_upgrade")
            final_detail = {
                "delivery_status": label,
                "release_authorized": ds.get("release_authorized"),
                "final_mp4_ok": _mp4_ok(final_mp4),
                "candidate_mp4_ok": _mp4_ok(cand_mp4) if cand_mp4.exists() or label == "HUMAN_REVIEW_REQUIRED" else None,
                "aligned": align.get("aligned"),
                "n_final_goal_evidence": evid.get("n_goal_anchors"),
                "final_first_live_counts": evid.get("status_counts"),
                "n_lineage_strict_complete": lineage.get("n_strict_complete"),
                "n_lineage_inferred": lineage.get("n_inferred"),
                "n_lineage_unresolved": lineage.get("n_unresolved"),
                "n_lineage_traced_strict": lineage.get("n_structurally_traced_to_mp4"),
            }
        except Exception as exc:  # noqa: BLE001
            blocking.append(f"99_final_invalid:{exc}")
    stages["v3a_final_delivery"] = {
        "present": delivery_p.is_file(),
        "valid": final_ok,
        **final_detail,
    }

    required = (
        "01_enrich",
        "02_strip831",
        "03_v1_adapt",
        "04_phase5_edl",
        "04_phase5_mp4",
        "05_live_audit",
        "v3a_final_delivery",
    )
    pipeline_stages_valid = all(bool(stages[k].get("valid")) for k in required)
    # Execution-stage validity is not equivalent to a complete story.
    # A score-confirmed goal without an action is a semantic blocker even
    # when the adapter ran correctly and generated some other goal chains.
    all_required_valid = pipeline_stages_valid and not blocking
    delivery_label = delivery.get("delivery_label") or delivery.get("delivery_status")
    release_ready = (
        all_required_valid
        and delivery_label == "RELEASE_READY"
        and bool(delivery.get("release_authorized"))
    )
    return {
        "schema": "v3a_full_e2e_stage_validity_v1",
        "stages": stages,
        "pipeline_stages_valid": pipeline_stages_valid,
        "story_goal_actions_present": goal_actions_present,
        "all_required_valid": all_required_valid,
        "release_ready": release_ready,
        "blocking_errors": blocking,
        "goal_recovery_impact": recovery_impact,
        "first_live_visual": first_live_visual,
        "delivery_label": delivery.get("delivery_label") or delivery.get("delivery_status"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
