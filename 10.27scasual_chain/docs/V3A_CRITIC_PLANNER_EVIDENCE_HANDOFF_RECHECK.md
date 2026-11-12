# V3-A Critic -> Planner evidence handoff | P8/P9 bottleneck recheck

Status: **source change committed, server regression pending**. This is NOT a
verified story-quality gain, a FIRST_LIVE certificate, or a benchmark result.

## Why this change (read-only case evidence)

- P8: proposed +11.7 s (3504 Save) bridge did not prove missing story information;
  subsequent attempted same candidate/EDL. Search-bound fallback override was
  fixed previously; do not reopen that work.
- P8 B/C visual controls: extra shot/defensive clips did not demonstrate
  *whole-video* narrative gain. "More highlights" and "longer" are not objectives.
- P9 Qwen3.7: VLM observed the source-time jump yet said it was narratively
  functional, `keep_story_if_no_defect=true`; Planner KEEP/UNRESOLVED, no candidate
  rendered. That is a valid *conservative outcome*, not automatically an Agent failure.
- P10-D: real LLM exploratory proposal dropped ~12 s of buildup even though
  Critic reported no confirmed story defect. Rendered Y is diagnostic only;
  human quality comparison was not completed.
- P10-E/F: role-based loss-of-motivation audit and cross-match blind pair
  exist, but true positive/negative human labels are pending.

## Code root cause and minimal repair

`story_paid_eval.py::run_llm_revision_planner` previously serialized a small
set of `vlm_critic_summary` headline fields and **omitted the Critic's
citation-normalized semantic evidence, sampled KEEP finding and coverage
limits**. This prevented the Planner from weighing observed narrative facts
against speculative edits. The fix adds:

- `video_critic_observations`: only checkable, normalized cited facts from
  an actual real critic; no raw model evidence or fabricated frame IDs;
  sampled `keep_story_if_no_defect` is passed as an observation, **not a
  full-video quality proof**.
- `existing_clip_narrative_function_hints`: target/before/after roles and
  duration from current EDL, marked UNVERIFIED_ROLE_HINT; **not** an edit
  authorization or match-specific story preference.
- A reminder for formal and exploratory planners to compare the loss of
  motivation/anticipation and state continuity vs possible pacing benefit.

No new Goal Recovery, OCR, Critic, Verifier, video observation tool or release
gate. P14 baseline `4717519` remains untouched on its own branch.

## Cursor/server zero-paid verification

Use a NEW worktree on branch
`story-va-v3a-critic-planner-evidence-handoff`. Do not touch prior
`/tmp/lpy1_p14_human_atom_dev_e2e_20261112` or best V3-R artifacts.

```bash
cd 10.27scasual_chain
python -m compileall -q algo/story_video_agent_v3
PYTHONPATH=algo python -m pytest tests/test_v3a_critic_planner_video_handoff.py -q
PYTHONPATH=algo python -m pytest tests/test_v3a_phase8_*.py tests/test_v3a_phase10_*.py tests/test_v3a_phase10d_*.py tests/test_v3a_phase10e_*.py tests/test_v3a_phase10f_*.py tests/test_v3a_p11_raw_input_and_critic_coverage.py -q
```

Checks:
1. Inspect fake text Planner's actual `INPUT` packet. A normalized
   `FRAME_CITED` observation and sampled KEEP must appear; fabricated raw
   frame IDs must not. Missing/degraded critic must show UNAVAILABLE, not
   invent evidence.
2. Confirm protected goals do not appear in editable-hint targets.
3. Confirm existing nonadditive/first-live/replay gates, P10-C sandbox,
   P14 event-mode rules and P8 historical behavior remain unchanged.
4. If a case fails, fix the smallest source-level cause and report
   exact test name/line. No edits of expected behavior just to make it green.
5. Reuse *existing* P10-D A and P10-F B anonymous X/Y files for independent
   whole-story viewing and label collection. Do not unseal P10-F risk
   predictions until labels are sealed. Historical candidate pairs are
   negative/uncertain controls; do not call them improvements.
6. Optionally replay saved P9/P10-D `vlm_story_critic.json` parsed and
   normalized evidence through the fake Planner to audit the new payload;
   no new real-provider calls. A changed *prompt* does not establish that
   the real model now makes a better edit.

## Exit criteria

- Source syntax and regression tests pass on the real server.
- Verified handoff facts are displayed with accurate evidence tiers.
- Previous goal coverage and baseline videos unchanged.
- No claim of a story-quality gain until an independent full-video
  comparison (with blinded judgments) supports it.

**Separate follow-up audit, NOT silently fixed here:** the current
`validate_editorial_redundancy_claims` can label two cited stills as
`DEFECT_CONFIRMED` and enable a formal drop. This should be tested
against a genuine necessary-vs-redundant negative control before relying
on it as proof of whole-clip redundancy. Do not weaken protections
without video evidence.
