# Phase 8 — Second-audit fix response

Review input: `docs/PHASE8_SECOND_CODE_AUDIT_REQUIRED_FIXES.md`  
Implementation branch: `story-va-v3a-phase8-loop-impl`  
Zero HTTP. No paid run. No V1/V2. No Phase 9.

## Fixes

| ID | Change |
|---|---|
| P0-A | Per-window `build_first_live_window_ledger` (source SHA + PTS). Event-chain / VLM claims never authorize `FIRST_LIVE_VERIFIED`. Any nonempty `hard_vetoes` → FAIL. Missing proof → UNKNOWN. Fixture may force PASS only via execution-path overlay. |
| P0-B | Dual-video prompt requests `soft_quality` / issue_effect / global_regression / suggested_next_evidence. Parser preserves soft PROMISING when `accept_candidate=false`. |
| P0-C | Real `run_story_evidence_search` + `plan_from_diagnosis` choose A then B after feedback. E2E mocks only render/observe; no scripted round-2 intents. |
| P0-D | Observation-grade `evidence_token` = source SHA + PTS + obs/frames. `candidate_id` / round counters no longer unlock retries. |
| P1-E | Directed reobserve writes frame manifest + status (`NEEDS_VLM_BUDGET` / `STOP_UNVERIFIED`); not JSON-only. |
| P1-F | Version snapshots store source/EDL/MP4 SHA; release re-checks digests. `compared_against_best` false when parent≠best without vs-best observation. |

## Tests

```bash
PYTHONPATH=algo python -u -m pytest \
  tests/test_v3a_phase8_feedback_policy.py \
  tests/test_v3a_phase8_loop_offline.py \
  tests/test_v3a_phase8_planner_search_feedback.py \
  tests/test_v3a_phase8_run_story_e2e_loop.py \
  tests/test_v3a_phase8_second_audit_fixes.py \
  tests/test_v3a_phase7_semantic_evidence.py \
  tests/test_v3a_phase6_semantic.py \
  tests/test_v3a_story_e2e.py -q --tb=line -k 'not cross_match'
```

Result: **70 passed, 1 deselected**. Unified E2E / cross_match **NOT RUN**.

## Proof artifacts

`docs/phase8_review_artifacts/second_audit_proof/`

- `first_live_negative.json` — SEARCH_EVENT_CHAIN + NOT_VERIFIED → hard safety **UNKNOWN**
- `autonomous_ab_selection.json` — control top=A@896; with feedback filtered=[A], kept top=B@1496 (no mocks)
- `e2e/` — `run_story_e2e`: r1 REVISE A@896; first_live aggregate NOT_VERIFIED; r2 feedback_filter_applied, kept B@1496; release=false

## Still unresolved

- Paid directed reobserve VLM evaluation (zero-HTTP bound → `NEEDS_VLM_BUDGET`)
- Formal REAL_VLM `PROMOTE_BEST` vs-best observation not live-exercised
- Authentic video-quality gain / unseen-match generalization **UNVERIFIED**
- No Phase 9
