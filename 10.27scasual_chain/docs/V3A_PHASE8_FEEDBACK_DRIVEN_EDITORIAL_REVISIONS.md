# Phase8: feedback-driven non-additive story revision

## Motivation and boundaries

The previous B/C complete-cut comparison rejected added footage that was plausible as a local event but did not explain a missing story state. The previous Phase8 fullcut Verifier can screen two rendered cuts, but before this patch it only produced a verdict; it did not transfer a *qualified reason for failure* into next-round edit selection, and Planner could keep searching for filler rather than using existing footage better.

This design is **match-agnostic** and **does not include B/C timestamps, teams or match-specific rules**. No V1/V2 changes. Unmodified V3-R remains the best-known baseline until a real improvement is independently verified.

## Implementation

### 1. Learning from the actual fullcut screen

`story_fullcut_learning.extract_fullcut_learning` binds the executed `revision_intents` to the current VLM fullcut screening result, the unchanged source SHA, baseline/candidate finished MP4 digests, original issue and exact action/anchors. Only `REAL_VLM` with validated sampled frame references creates learning entries.

- `SCREENED_NO_GAIN` yields *conditional* `UNCERTAIN_OR_UNVERIFIED` feedback (not a `CONFIRMED_NEGATIVE` label). This records that one specific action did not show gain **under available sampled evidence**.
- `SCREENED_BETTER` remains `PROMISING` without formal `IMPROVED`.
- Neither outcome permanently bans a source PTS. Fake/fixture/unbound labels cannot become real feedback.
- Records are written to `02_round_XX/fullcut_revision_learning.json` and to existing `phase8_feedback_memory.json`.

### 2. One edit per iteration and alternatives

When `use_fullcut_learning=True`, `story_revision_planner` selects at most **one** independently confirmed mutation. It prefers verified, non-additive `drop/reorder/trim` over new `search_add/replace` material, deferring other intents. This makes before/after causality easier to interpret and avoids several confounded edits. Prior no-gain feedback is matched by issue/anchor rather than used globally.

The same failed structural action on the same target in the *same run* is not repeated without fresh evidence; different targets remain viable. The Phase8 loop now considers deferred confirmed edits as distinct alternatives when `SAME` feedback prompts `REPLAN_FROM_BEST`, rather than always stopping.

The old offline/fixture paths retain their previous multiple-edit behavior for testing. This change does not synthesize arbitrary edit actions from comments alone.

### 3. Real non-additive candidate generation from source-bound video

`story_editorial_redundancy.validate_editorial_redundancy_claims` evaluates an **optional one-claim** `redundancy_claims` field returned by the *existing* VLM Critic call (no extra HTTP). The Critic receives the actual sent frame-ID-to-EDL-segment mapping. A usable candidate must:

- identify **two distinct** included EDL source-bearing segments and name exactly which non-goal segment is expendable;
- cite real frame IDs and locally hashed frame bytes from both segments;
- state a specific observed visual duplication and why it hurts story comprehension;
- avoid protected goal, scoreboard, confirmation, title or ending material.

A validated claim becomes a *video-grounded proposed redundancy issue*. The existing `_structure_intents` can map its preferred_drop segment into a `drop` intent; the existing `apply_candidate_revision` creates a separate EDL without touching baseline. Every edit still must pass timeline, first-live, render, candidate goal protection and completed-cut review. Such a proposed issue is not an authenticated human-quality assessment.

### 4. Post-LLM non-additive gate

Because the LLM may override the rule Planner, `enforce_confirmed_nonadditive_edits` requires any `drop/reorder/trim` to match an independently confirmed issue, exact EDL target and non-goal/essential story protection. For redundancy, `drop` must match `preferred_drop_segment_id`; the model cannot invent a different target. Unsupported edits become `mark_unresolved`. `trim` also continues to depend on the existing bound observation/time checks.

The LLM Planner now sees confirmed non-additive issues first and is told to prefer one attributable edit, instead of letting many source-gap hypotheses dominate.

## Limitations

- VLM stills do **not** imply full broadcast/video/audio understanding. Video-grounded candidate issue claims may be wrong: no formal release or BEST without independent full-cut observation.
- If frame coverage is insufficient, no editorial redundancy issue is synthesized. A single frame of one segment is insufficient.
- A candidate may fail due to timing, pacing or semantic verification. That is a legitimate failure, not a success case.
- `SCREENED_NO_GAIN` from sampled video is not a globally confirmed negative; it remains local to the action/issue.
- No new paid VLM was called by this implementation turn. Future paid use requires explicit authorization and the existing request cap.

## Required zero-paid verification

On a **new** isolated worktree at this branch's latest HEAD, run:

```bash
cd 10.27scasual_chain
python -m compileall -q algo/story_video_agent_v3
PYTHONPATH=algo python -m pytest tests/test_v3a_phase8_editorial_redundancy.py -q
PYTHONPATH=algo python -m pytest tests/test_v3a_phase8_fullcut_learning.py -q
PYTHONPATH=algo python -m pytest tests/test_v3a_phase8_*.py -q
```

No real HTTP, no merge, no overwriting earlier verified worktrees. Report actual pass/fail/skip, failed tracebacks and branch HEAD; push result JSON for review. Success means new code mechanisms execute, **not** that story quality increased.

### Server verification (`b13da6f`)

Worktree: `/data2/lpy1/worktrees/migu-v3a-editorial-redundancy-verify`  
Report JSON: `docs/V3A_PHASE8_FEEDBACK_EDITORIAL_SERVER_VERIFY_b13da6f.json`

| Check | Result |
|-------|--------|
| `compileall algo/story_video_agent_v3` | exit 0 |
| `tests/test_v3a_phase8_editorial_redundancy.py` + `test_v3a_phase8_fullcut_learning.py` | **20 passed / 0 failed / 0 skipped** |
| `tests/test_v3a_phase8_*.py` | **129 passed / 0 failed / 0 skipped** |
| Paid HTTP / VLM | **0** |
| Algo edits in verify turn | none |
| Merge to main | not done |

Mechanism regression is green. Real full-cut story gain remains **UNVERIFIED**. Untouched V3-R remains the retained best baseline.

## Next evidence step

Once source-level tests pass, use one held-out match + a new narrative template and a real baseline/candidate complete-cut comparison. Count: correctly discovered redundancies, non-goal cut precision, intact first-live/goal anchors, before→after information difference, narrative pace and human preference. Do not claim cross-match generalization from the two existing matches alone.
