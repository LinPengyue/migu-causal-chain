# Phase 8 real-run failure — zero-paid corrective response

Base paid run: `2f359ee` artifacts under
`_story_va_outputs/v3/plan2/phase8_paid_run_20261109/real_vlm_multiround/`.
No second paid API experiment.

## Root causes (proven from frozen logs)

1. **Search “verified” ≠ first-live.** `verify_search_candidate` only checked
   event-chain LIVE + PTS; planner text called it “LIVE-verified”, so 3504.14–3515.83
   became an executable `search_add` without attestation.
2. **LLM `mark_unresolved` overridden.** Round2 `llm_revision_planner.json` returned
   UNRESOLVED + `mark_unresolved` intents; `story_e2e_agent` note
   `llm_returned_no_mutating_intents; retained_search_bound_revise` re-applied Search.
3. **Feedback suppress miss.** Feedback signature category=`transition_break`
   (story_role) vs Search candidate category=`transition` → `should_penalize_candidate`
   returned no suppress → 3504 survived Round2 filter (`feedback_filtered_candidates=[]`).
4. **Story miss (video).** Bridge is 1H+4 box/fan reaction then still jumps into 2H
   buildup; Save heat ≠ causal bridge from 12' deficit to late equalizer path.

## Fixes (code)

| Area | Change |
|------|--------|
| Evidence tiers | `EVENT_PTS_CANDIDATE` vs `FIRST_LIVE_VERIFIED`; executable apply only for attested windows |
| Planner / apply | `search_add` only from `executable_safe_revision`; EVENT_PTS → propose/`mark_unresolved` |
| LLM overlay | Honor UNRESOLVED/keep-only; never retain Search REVISE; LLM failure fail-closed |
| Feedback | Category family (`transition`↔`transition_break`); prefer diagnosis category in signatures |
| Ranking | Gap-balance + large-residual risk; selection diagnostics table |
| Wiring | Pass `first_live_evidence_store` + `source_sha256` into Search |

## Zero-HTTP proof

- Tests: `tests/test_v3a_phase8_real_run_failure_fixes.py` (+ related phase8 suite green).
- Replay: `_story_va_outputs/.../ZERO_HTTP_FAILURE_FIX_REPLAY.json`

## Before → after (setup→buildup issue)

**Before (real Round1):** 3504 Save ranked #1 (`rank_score` 10.668, event LIVE) → applied.

**After (replay):** 2273 Shot is sole `FIRST_LIVE_VERIFIED` / executable for that gap;
3504 remains `EVENT_PTS_CANDIDATE` / not executable. Round2 feedback filters 3504
(`repeat_blocked_need_new_evidence`). Real Round2 LLM UNRESOLVED is honored
(no silent re-apply).

Note: promoting 2273 still requires separate story-quality verification; attestation
is a safety gate, not automatic narrative success.
