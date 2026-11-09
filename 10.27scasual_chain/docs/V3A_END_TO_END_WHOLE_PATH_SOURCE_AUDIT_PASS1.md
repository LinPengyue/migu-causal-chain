# V3-A whole-path source audit — pass 1 (source-grounded, no paid calls)

Baseline: `a4387e8ef5ebbb2f9cb9bd74cf656b3381d67f7c` on `story-va-v3a-phase8-loop-impl`. Review/fix branch: `story-va-v3a-full-chain-audit-fixes`. This pass directly inspected complete source functions along the two orchestrators and supporting video/story/safety modules. This is NOT a claim that every one of the repository's Python files was audited or that a full real video experiment ran.

## User goal and approved inference inputs
Original `赛事.json` event inventory + supplemental `causal.json` atoms + raw source MP4. Existing `atomic_event_enrich.enrich_files` generates `01_enrich/events_enriched.json` and `enrich_report.json`; 8.31 strip predicts short chains; adapter and goal recovery generate V3-compatible candidate causal; Phase5 creates V3-R plan, graph, EDL and MP4; V3-A repairs story issues with Critic/Search/Planner/Verifier/feedback; end delivery must be safe, replay-free, first-broadcast LIVE and narratively better, with identical source/PTS/goal lineage. No gold/story labels as inference inputs.

## Two executable end-to-end paths (confirmed)
1. **Current Phase 8 main** `story_e2e_cli.main → story_e2e_agent.run_story_e2e`. For fresh V3-R, `resolve_baseline` calls `closed_loop_cli.run_match`; for frozen Phase5, uses prior EDL + plan + MP4. Then `global_story_critic`, `story_observe`, `story_evidence_search`, `story_revision_planner`, real VLM via `story_paid_eval`, `apply_candidate_revision`, `story_video_verifier`, loop feedback, selected best version and final delivery. This is the primary Phase8 experiment entry.
2. **Another advertised fresh end-to-end CLI** `fresh_e2e_cli.main → run_fresh_e2e`. It also calls `closed_loop_cli.run_match` and Phase5 but then invokes **`self_revise_agent.run_self_revise` directly**, instead of `run_story_e2e`. The latter function's own docstring calls it a *specialized laboratory entry*, not the unified production story E2E. Fresh CLI may produce plausible MP4/summary via a different revision, evidence and release policy. Do NOT silently equate the two scripts or change the second to the first without an explicit migration test. Label fresh CLI output candidate-only until paths are reconciled.

## Major code-grounded risks and remedies

### A. Search can pre-authorize unbound FIRST_LIVE by string (fixed in this review branch)
`story_evidence_search._annotate_first_live_tier` previously set `executable_safe_revision=True` by reading status strings on a store row keyed by SHA+PTS, without checking evidence frame byte hashes / manifest digest / schema / replay_hits. The post-edit `build_first_live_window_ledger` calls `validate_first_live_evidence_record` and is stricter, but needless edit/verification work already occurs and the test's minimal pack made a misleading green. This branch wires the same full validator into the pre-apply gate, with `require_files_exist=True`, and adds negative/positive/synthetic regressions. Event metadata or invalid/forged label-only review remains proposal-only.

### B. Search top-5 truncation happens before video evidence annotations (open)
`_rank_events_in_window` retains max 5 by event heat/type/gap balance before first-live eligibility. Verified candidate #6 can be lost even if top five have no valid broadcast proof. Fix candidate retrieval and evidence-aware selection on this branch in a separate focused patch; add a top-six clean-fixture regression. Do not hardcode a match timestamp or a preferred event.

### C. Semantics of story value are still rank heuristics (open)
`_rank_events_in_window` scores metadata heat, type hints, source-gap balance, etc. This is not video-backed causal or emotional bridge evidence. Contextual VLM Critic evaluates finished cut, but new source candidates need anchored bridge-fit assessment against adjacent beats before selection, else the optimizer can make a cut longer yet still narratively weak. User's 3504s bridge failure illustrates this limitation. Need zero-paid visual comparisons as test fixtures and future controlled experiment, not another generic ranking scalar without evidence.

### D. Fresh CLI vs main story loop drift (open, potentially high impact)
`fresh_e2e_cli.run_fresh_e2e` still runs `run_self_revise` (specialized). Its `max_calls` default is 24, `max_cost_usd` default $0.30, unlike Phase8's separately bounded 5/$0.10 main route. Do not invoke paid fresh CLI under the expired one-run permission. Mark and reconcile entrypoints with a safe migration/adapter and test complete source-to-delivery semantics before claiming generalized end-to-end behavior.

### E. Test integrity (partly fixed, more work)
Previous tests in `test_v3a_phase8_second_audit_fixes.py` generated label-only FIRST_LIVE packs. The review branch now creates synthetic byte-bound frames, manifest digests and timeline-schema records. This is *structural validator testing*, not evidence that the synthetic frames correspond to a real broadcast. Existing `test_v3a_phase8_real_run_failure_fixes.py` has server-path skipUnless cases; copy sanitized small frozen traces into the repo or add fully isolated production-function unit tests to ensure clean-checkout consistency.

## Patch inventory in this branch
- `story_evidence_search.py`: pre-apply `validate_first_live_evidence_record`, fails closed on bare labels, tampered frames, replay contradicting review; emits validation metadata into selection diagnostics.
- `test_v3a_phase8_second_audit_fixes.py`: structurally complete synthetic evidence fixture.
- `test_v3a_phase8_preapply_frame_validation.py`: tests label-only spoof, complete test pack, tampered bytes, replay_hits, source/PTS mismatch, mixed evidence.

## What has NOT yet been claimed
- Not independently run pytest (full repository/server dependencies unavailable here). New synthetic tests require actual server execution.
- No additional paid HTTP, no second paid experiment, no release authorization, no Phase9, no modifications to V1/V2.
- No proof of story-quality improvement, no full visual comparison of the most recent final MP4 and baseline.

## Next decisive step
Ask Cursor only to **sync this branch into an isolated server worktree, run `PYTHONPATH=algo python -m pytest tests/test_v3a_phase8_*.py -q`, and return actual failures and input-evidence integrity**; code ownership stays with ChatGPT. Continue independent full-chain code audit before making production branch changes. Preserve all prior experiments.