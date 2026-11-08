# Phase 8 — Second-audit response (P0/P1 fixes)

Review input: `docs/PHASE8_CODE_REVIEW_REQUIRED_FIXES.md`  
Implementation branch: `story-va-v3a-phase8-loop-impl`  
Zero HTTP throughout. No paid multi-round run.

## Fixes mapped

| ID | Fix |
|---|---|
| P0-1 | `verdict_provenance` from execution path only (`FIXTURE` / `REAL_VLM` / `OFFLINE_RULE`). Fixture payloads claiming `source_kind=REAL` stay FIXTURE. Real provider channel separated from test fixtures. |
| P0-2 | `compute_independent_hard_safety` — no dependence on `accept_candidate`. PROMISING + safety PASS + rendered can `CONTINUE_WORKING`. UNKNOWN first-LIVE cannot approve working; intentional replay → FAIL. |
| P0-3 | Budget evaluated **after** current-round outcome; `PROMOTE_BEST`/`CONTINUE_WORKING` retained then `stop_reason=STOP_BUDGET` forbids further rounds. |
| P0-4 | Renamed policy scenario artifact; added `tests/test_v3a_phase8_run_story_e2e_loop.py` calling real `run_story_e2e` with mocked render/observe/search (still real loop/file audit). |
| P0-5 | Per-version `version_snapshots`; release gate reads **delivery snapshot only**, ignores last-round mutable gates. |
| P1-6 | No generic `suggested_next_evidence` fallback; REOBSERVE requires specific target and writes `directed_reobserve/`. |
| P1-7 | `CONTINUE_WORKING` requires `rendered` + mp4 exists. |
| P1-8 | Signature match uses category + anchors + missing-info; evidence_token persisted; different placement allows same PTS. |

## Tests

```bash
PYTHONPATH=algo python -u -m pytest \
  tests/test_v3a_phase8_feedback_policy.py \
  tests/test_v3a_phase8_loop_offline.py \
  tests/test_v3a_phase8_planner_search_feedback.py \
  tests/test_v3a_phase8_run_story_e2e_loop.py \
  tests/test_v3a_phase7_semantic_evidence.py \
  tests/test_v3a_phase6_semantic.py \
  tests/test_v3a_story_e2e.py -q --tb=line -k 'not cross_match'
```

Unified E2E integration / cross_match: **NOT RUN** (environment hang risk) — not claimed PASS.

## Main-loop proof (`run_story_e2e`)

Durable copy: `docs/phase8_review_artifacts/main_loop_proof/`  
(`PROOF_SUMMARY.json` + per-round `artifacts/`). Same path as `test_two_rounds_feedback_changes_edl`.

| Round | Transition | EDL change | Feedback into next |
|---|---|---|---|
| r1 | PROMISING + safety PASS → `CONTINUE_WORKING` (`working_ref=v1`) | inserts `seg_bridge_r1` @ PTS 900–908 | memory + planner/search context written |
| r2 | parent=`v1`; planner `n_records≥1`; search returns alt PTS | inserts `seg_bridge_r2` @ PTS 1500–1510 (on top of r1) | UNCERTAIN → `STOP_NO_ACTION` |
| r3 | **not executed** | — | — |

- Provenance for fixture-driven rounds: `FIXTURE` on `version_snapshot.json` (payload `source_kind=REAL` cannot override).
- best stays `v0` (PROMISING never promotes); final `working` resets to best on STOP; `release_authorized=false`.
- Flags: `structural_loop_pass=true`, `video_semantic_quality_verified=false`.

## Still unresolved

- Directed REOBSERVE does not yet call paid vision; only writes target JSON (zero-HTTP bound).
- Formal REAL_VLM `PROMOTE_BEST` still requires compared-against-best + SUFFICIENT evidence — not exercised with a live provider (by design).
- Authentic video-quality improvement and unseen-match generalization remain **UNVERIFIED**.
- No Phase 9.
