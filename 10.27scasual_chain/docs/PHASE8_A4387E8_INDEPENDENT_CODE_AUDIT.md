# Phase8 a4387e8 — Independent source audit and remaining release blockers

Code base: `a4387e8ef5ebbb2f9cb9bd74cf656b3381d67f7c`, branch `story-va-v3a-phase8-loop-impl`. This is an independent **read-only audit**; source inspected via GitHub, not a replay of Cursor's local test run. No paid HTTP authorized or performed.

## Decision

PARTIAL ACCEPT: the known feedback-category alias and LLM nonmutation fallback bugs have credible source fixes. Full closeout NOT YET: pre-apply first-LIVE gate is label-based rather than validator-based; relevant test fixtures actually certify bare string labels, and no executable real-story video-quality gain is demonstrated.

## Evidence-backed resolved points

1. `story_e2e_agent.py`: successful real Planner returning keep/mark_unresolved/no mutating intent now suppresses Search REVISE, and planner failure fails closed. This addresses the real Round2 symptom in principle. Need an integrated test invoking production merge logic, not a handwritten copy of the branch.
2. `story_revision_feedback.py`: category family maps `transition`↔`transition_break`. `story_evidence_search.py::_apply_feedback_to_candidates` prefers diagnosis category and retains context-specific PTS suppression; does not impose a permanent ban.
3. `story_evidence_search.py`: event-metadata screen now clearly returns `EVENT_PTS_CANDIDATE`; only an explicitly annotated first-LIVE candidate is passed to `search_candidates_to_observations`. `story_revision_planner.py` separates executable `search_add` from `mark_unresolved` propose-only.

## P0/P1 — Pre-apply FIRST_LIVE_VERIFIED can be spoofed by a label

`story_evidence_search.py::_annotate_first_live_tier` uses `window_key(source_sha, start, end)` to retrieve a pack, then accepts `review.first_live_status` / `review.outcome` / `pack.first_live_status` as sufficient to set `executable_safe_revision=True`. It does **not** call `validate_first_live_evidence_record` and does not check schema, bound frame bytes, manifest digest, actual source SHA+PTS record fields, `replay_hits`, or an explicit independent review method. A store row keyed to the expected window with `{ 'first_live_status':'FIRST_LIVE_VERIFIED' }` is enough for a false positive at the Search/Planner early gate. The post-edit ledger later validates more, so this is a **real pre-apply cost/safety gating hole**, not proof that final release can be bypassed.

Existing `tests/test_v3a_phase8_second_audit_fixes.py::_first_live_store_for_windows` builds such bare label-only packs (only `first_live_status` and a simple timeline review). It exercises a permissive test path, not real first-LIVE certification. The test `test_annotate_attested_windows_executable` depends on server path `EVIDENCE_STORE`; availability and integrity are not reproduced in a clean checkout.

Minimal correction: call `validate_first_live_evidence_record(pack, source_sha, pts_start, pts_end, require_files_exist=True, timeline_review=review)` from `_annotate_first_live_tier`; only `validation.ok && validation.binding_valid && validation.first_live_verified && !validation.replay_confirmed` may yield `FIRST_LIVE_VERIFIED` and `executable_safe_revision=True`. Missing frames/review, source mismatch, PTS mismatch, replay hits or malformed records must be propose-only. Preserve a useful `reject_or_defer_reason`, actual validation outcome and review provenance in selection diagnostics. Do not silently trust the pack status string.

Production test cases required: (a) bare positive status, (b) review without matching SHA/PTS, (c) positive review + replay_hits, (d) tampered frame bytes/manifest, (e) full valid attestation with actual files, (f) two clips one valid and one absent; assert the SAME pre-apply selection and post-edit ledger interpretation.

## P1 — Ranking truncates before first-LIVE annotation

`story_evidence_search.py::_rank_events_in_window` ranks by event heat/type/gap-balance and stops at `_MAX_CANDIDATES_PER_ISSUE=5` **before** `_annotate_first_live_tier` checks the evidence store. This can discard source-safe candidate 6+ even when the top five are all unverified. Current ordering puts verified candidates first only **after** that loss. The replay example could be misleadingly green if 2273 happened to be among five. Include a synthetic top-six case with five high-heat EVENT_PTS candidates and one real valid FIRST_LIVE candidate; the valid candidate must survive candidate discovery and appear in the selection diagnostics without hardcoding match times.

## P1 — Story-fit is still only a temporal/heat proxy

`_rank_events_in_window` introduced `gap_balance*2` and a fixed 900-second residual penalty; the generated `story_defect_fit.rationale` itself admits it does not prove causal story value. Equal division of a 30-minute source jump is not the same as showing a narrative bridge. Keep this as a transparent prior only, not an automatic quality gate; require video-grounded comparison to both adjacent story beats and a negative baseline for 'filler but balanced'.

## P1 — Zero-HTTP replay / test robustness

`tests/test_v3a_phase8_real_run_failure_fixes.py` marks `TestRealRunFailureRootCauses` `skipUnless(REAL_RUN.is_dir())`; the real-run trace is at an absolute server path and is not committed, so a clean checkout skips the main cases. The test for LLM overlay copies the merge logic into a test-local `if not llm_has_mut` block instead of calling production code — it cannot catch future regression in `story_e2e_agent.py`. Report both passing and skipped counts. Extract merge logic into a testable pure helper or provide an integration stub; include deterministic, committed minimal sanitized trace inputs, while maintaining no paid HTTP.

## P2 — Feedback missing categories

`_category_family(None)` returns `unknown`, so `categories_compatible`'s intended `if not fa or not fb` fallback cannot activate. This is not yet shown to affect the reported failed run, but should have a small regression if the fallback is relied upon.

## Progression gate

Do not perform another paid trial. Keep `BEST=v0`, release=false. First close the validator-backed pre-apply gate and non-skipping clean-checkout tests. Then compare the selected semantically fitting candidates against the actual baseline/candidate video and present human-reviewable clips. Existing user-verified 6400 and 2273 windows are safety-approved for **exact PTS only**, not evidence they improve narrative quality. No special-case ranking to force 2273 as winner.

## Audit scope

Directly inspected: touched Python source and test files, user-provided paid summary and committed fix-response doc. Did not execute pytest on Cursor server, view the private run JSON or full rendered baseline/candidate MP4, or independently validate reported rank ordering. Therefore no claims of real-video quality improvement or server test pass.