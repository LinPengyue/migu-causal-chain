"""Official one-click Story Video E2E from three raw inputs only.

Formal inputs (required):
  --source-mp4      full match video
  --events-json     delivery events JSON (not enriched)
  --causal-json     human causal-chain JSON (atoms for enrich only)

This entrypoint NEVER accepts Phase5 / EDL / story graph / initial MP4 reuse.
It always runs: atomic enrich → strip/V1 short causal → Phase5 V3-R → V3-A story loop.

Causal-chain contract (do not mix):
  - User causal JSON: long-form human annotations used only to *supplement missing atoms*
    into events via atomic_event_enrich (structure not reused as story plan).
  - Predicted short causal (03_v1_adapt): algorithm strip→V1 adaptation for Phase5.
  - V3-R long story chain: produced inside Phase5 planner/graph (not the human file).

Examples:
  python -m story_video_agent_v3.story_full_e2e_cli \\
    --source-mp4 /path/match.mp4 \\
    --events-json /path/match.json \\
    --causal-json /path/match_causal.json \\
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
        description="One-click Story Video E2E from MP4 + events + causal only"
    )
    p.add_argument("--source-mp4", type=Path, required=True)
    p.add_argument("--events-json", type=Path, required=True,
                   help="Raw delivery events JSON (not events_enriched.json)")
    p.add_argument("--causal-json", type=Path, required=True,
                   help="Human causal atoms JSON (*_causal.json)")
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
    for label, path in (
        ("source_mp4", args.source_mp4),
        ("events_json", args.events_json),
        ("causal_json", args.causal_json),
    ):
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

    # Contract note persisted for auditors.
    contract = {
        "schema": "v3a_full_e2e_input_contract_v1",
        "formal_inputs": {
            "source_mp4": str(args.source_mp4.resolve()),
            "events_json": str(args.events_json.resolve()),
            "causal_json": str(args.causal_json.resolve()),
        },
        "causal_roles": {
            "user_causal_json": (
                "Human long-form causal annotations; used only by atomic_event_enrich "
                "to inject missing atoms into events. Not used as story plan."
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
        causal_atoms_json=args.causal_json.resolve(),
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

    # Stage presence audit (fresh tree).
    fresh_root = out_dir / "01_to_04_fresh_v3r"
    stages = {
        "01_enrich": (fresh_root / "01_enrich" / "events_enriched.json").is_file(),
        "02_strip831": (fresh_root / "02_strip831" / "strip_A_original.json").is_file(),
        "03_v1_adapt": (fresh_root / "03_v1_adapt" / "predicted_causal_live_goals_only.json").is_file(),
        "04_phase5_edl": (fresh_root / "04_phase5" / "candidate_edl.json").is_file(),
        "04_phase5_mp4": (fresh_root / "04_phase5" / "story_clean.mp4").is_file(),
        "05_live_audit": (fresh_root / "05_live_audit" / "goal_live_audit.json").is_file(),
        "v3a_final_delivery": (out_dir / "99_final" / "delivery_status.json").is_file(),
    }

    summary: Dict[str, Any] = {
        "ok": bool(audit.get("ok")) and status != "BLOCKED",
        "delivery_status": status,
        "delivery_label": delivery.get("delivery_label"),
        "blocked_reasons": delivery.get("blocked_reasons") or [],
        "out_dir": str(out_dir),
        "elapsed_sec": round(elapsed, 3),
        "decision": delivery.get("decision"),
        "final_mp4": delivery.get("final_mp4"),
        "status_gates": gates,
        "stages_present": stages,
        "fresh_v3r": True,
        "phase5_reuse": False,
        "http_calls": audit.get("http_calls"),
        "est_cost_usd": audit.get("est_cost_usd"),
        "error": audit.get("error"),
        "baseline_duplicate_audit": audit.get("baseline_duplicate_audit"),
        "contract": str(out_dir / "00_full_e2e_contract.json"),
    }
    (out_dir / "full_e2e_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if status == "BLOCKED" or audit.get("error"):
        return 1
    if not stages.get("04_phase5_mp4"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
