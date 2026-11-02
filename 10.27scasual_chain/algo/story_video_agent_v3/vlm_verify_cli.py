"""CLI: V3 remote VLM verify for a localized first-live candidate.

Default = mock + zero-HTTP config audit.
Real billed calls require --enable-real-api AND --i-approve-budget (await explicit approval).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional

from .remote_vlm_verify import run_remote_vlm_verification, scrub_config_audit


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="V3 remote VLM goal-action verify (V2 ApiProvider reuse)")
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--media-in", type=float, required=True)
    p.add_argument("--media-out", type=float, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--role", default="opening_deficit")
    p.add_argument("--score-before", default="1,1")
    p.add_argument("--score-after", default="2,1")
    p.add_argument("--score-bounds-json", type=Path)
    p.add_argument("--attacking-team-hint", default="Osasuna / home side matching score delta")
    p.add_argument("--max-calls", type=int, default=3)
    p.add_argument("--max-cost-usd", type=float, default=0.5)
    p.add_argument("--max-completion-tokens", type=int, default=2048)
    p.add_argument("--config-audit-only", action="store_true",
                   help="Zero-HTTP config audit only; no frame extract / VLM")
    p.add_argument("--enable-real-api", action="store_true",
                   help="Allow real HTTP (still needs --i-approve-budget)")
    p.add_argument("--i-approve-budget", action="store_true",
                   help="Explicit budget approval for billed vision calls")
    p.add_argument(
        "--observation-only",
        action="store_true",
        default=True,
        help="Force agent_auto_verified=false (default; first real trial)",
    )
    p.add_argument(
        "--allow-auto-verify",
        action="store_true",
        help="Opt out of observation-only (still needs full cross-checks; never opens Gate)",
    )
    p.add_argument("--continuous-clip", type=Path,
                   help="Optional existing accurate continuous clip for continuity check")
    args = p.parse_args(argv)

    def _pair(s: str):
        a, b = s.split(",", 1)
        return [int(a.strip()), int(b.strip())]

    if args.config_audit_only:
        audit = scrub_config_audit(
            max_calls=args.max_calls,
            max_cost_usd=args.max_cost_usd,
            max_completion_tokens=args.max_completion_tokens,
            apply_overrides=True,
        )
        args.out_dir.mkdir(parents=True, exist_ok=True)
        path = args.out_dir / "api_config_audit_zero_http.json"
        path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "status": "ok_config_audit_only",
            "http_requests_sent": 0,
            "path": str(path),
            "ready_for_real_when_approved": audit.get("ready_for_real_when_approved"),
            "models": audit.get("models"),
            "effective_caps": audit.get("provider_global_caps"),
            "vision_effective_output_token_limit": (audit.get("vision") or {}).get(
                "effective_output_token_limit"
            ),
            "compat_checks": audit.get("compat_checks"),
            "request_body_audit": audit.get("request_body_audit"),
            "render_ready": False,
        }, ensure_ascii=False, indent=2))
        return 0

    if args.enable_real_api and not args.i_approve_budget:
        p.error("Real API refused: pass --i-approve-budget after budget approval")

    bounds = None
    if args.score_bounds_json and args.score_bounds_json.is_file():
        bounds = json.loads(args.score_bounds_json.read_text(encoding="utf-8"))

    observation_only = not bool(args.allow_auto_verify)
    summary = run_remote_vlm_verification(
        video=args.video,
        media_in=args.media_in,
        media_out=args.media_out,
        out_dir=args.out_dir,
        role=args.role,
        score_before=_pair(args.score_before),
        score_after=_pair(args.score_after),
        score_bounds=bounds,
        attacking_team_hint=args.attacking_team_hint,
        enable_real_api=args.enable_real_api,
        i_approve_budget=args.i_approve_budget,
        max_calls=args.max_calls,
        max_cost_usd=args.max_cost_usd,
        max_completion_tokens=args.max_completion_tokens,
        observation_only=observation_only,
        continuous_clip_path=args.continuous_clip,
        run_gate=False,
    )
    print(json.dumps({
        "status": "ok",
        "provider_mode": summary.get("provider_mode"),
        "observation_only": summary.get("observation_only"),
        "agent_auto_verified": summary.get("agent_auto_verified"),
        "verification_status": summary.get("verification_status"),
        "semantic_label": summary.get("semantic_label"),
        "structurally_ready_for_automated_verify": summary.get(
            "structurally_ready_for_automated_verify"
        ),
        "gate_opened": summary.get("gate_opened"),
        "http_attempts": summary.get("http_attempts"),
        "output_budget_exceeded": summary.get("output_budget_exceeded"),
        "effective_caps": summary.get("effective_caps"),
        "out_dir": str(args.out_dir),
        "render_ready": False,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
