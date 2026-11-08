# Phase 8 fourth audit — fix response

Branch: `story-va-v3a-phase8-fourth-audit`

## Scope
Only evidence-tier correction. No Planner/Verifier redesign. No auto paid. Offline feedback loop + paired ablation remain accepted.

## Changes
1. `build_local_first_live_evidence_pack` → `FRAME_BOUND_VALID` / `first_live_status=NOT_VERIFIED` (never `FIRST_LIVE_VERIFIED`).
2. `validate_frame_binding` vs `validate_first_live_evidence_record` split; `ok` only when binding **and** authenticated `broadcast_timeline_review` verify first-live.
3. `build_broadcast_timeline_review` over continuous source context + event-chain replay overlap / explicit authenticated review → `FIRST_LIVE_VERIFIED` | `REPLAY_CONFIRMED` | `UNKNOWN`.
4. Ledger + hard-safety: binding-only ⇒ `UNKNOWN` (`pending_timeline_review`); replay ⇒ `FAIL`; all windows first-live verified ⇒ `PASS`.
5. Tests: `tests/test_v3a_phase8_fourth_audit_evidence_levels.py` (+ adjusted second/third expectations).

## Real-source timeline artifacts
Under `docs/phase8_review_artifacts/fourth_audit_proof/`:

| Case | Binding | Timeline | Hard safety |
|------|---------|----------|-------------|
| UAE-Oman live window @6430–6445 | FRAME_BOUND_VALID | UNKNOWN | UNKNOWN |
| UAE-Oman replay window @824.81–835.15 | FRAME_BOUND_VALID | REPLAY_CONFIRMED | FAIL |
| Mechanism authenticated review | FRAME_BOUND_VALID | FIRST_LIVE_VERIFIED | PASS (MECHANISM_TEST_NOT_MATCH_TRUTH) |

Honest real-match first-broadcast status: **UNKNOWN** (no unpaid human continuous-context certification).  
`PHASE8_REAL_FIRST_LIVE_POSITIVE_PASS=false`, `release_authorized=false`.

## Tests
```bash
cd 10.27scasual_chain && PYTHONPATH=algo python -m pytest tests/test_v3a_phase8_*.py -q
# 53 passed
```
