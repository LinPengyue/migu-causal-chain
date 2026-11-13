# P14 + current V3-A: Story Quality Trial 1 (zero HTTP, visual evidence before edit)

Base: P14 integration report `docs/V3A_P14_CV_INTEGRATION_RUN_20261113.md`,
code `650c8c9`. The baseline is 9 segments / ~94.877s with all three
goal actions. Its first-live status remains UNRESOLVED on all three.
Human Goal atoms make this **HUMAN_ATOM_ENRICHED_DEV**, not raw-only benchmark.

## Code-level reason for STOP_NO_ACTION

The actual run's `critic_issues_slim.json` has only:

- `large_source_jump_seg_setup_deficit_to_seg_buildup_event_000472` (transition)
- `large_source_jump_seg_buildup_event_000472_to_seg_equalizer_goal_action` (transition)
- `thin_post_climax_tail` (ending)

All have `HYPOTHESIS_NEEDS_VIDEO`. In
`story_revision_planner.py::_issue_confirmed_for_mutate`, unconfirmed
transition/ending hypotheses cannot drive edit. This is **correct**:
large source PTS gaps are normal highlight editing, and short aftermath
is not by itself a defective story. Merely changing Planner to ignore
this rule would repeat previous low-quality blind bridge/ending inserts.

## Trial 1: review evidence, no automatic editing

Execute in the **already existing** P14-integration worktree, on
`story-va-v3a-p14-story-quality-20261113`. Use a fresh output directory.

```bash
git fetch origin
git switch story-va-v3a-p14-story-quality-20261113
git pull --ff-only
cd 10.27scasual_chain
export PYTHONPATH="$PWD/algo"
export STORY_API_ENABLE=0
python -m py_compile docs/v3a_p14_story_quality_review.py
python docs/v3a_p14_story_quality_review.py \
  --run-dir /tmp/lpy1_v3a_p14_cv_integration_20261113/run \
  --source-mp4 '/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4' \
  --out-dir /tmp/lpy1_v3a_p14_quality_review_20261113 \
  --max-per-issue 2
```

The helper directly reads the current **real** `story_diagnosis.json`,
`evidence_search.json`, initial 9-segment EDL/MP4, and original MP4,
rechecks the V3-A source SHA, and refuses an existing output directory.
It uses existing `story_timeline` to extract ~14s finished-story
junction context for transitions, and the last ~20s for the ending.
For each issue it exports at most two short **event-PTS** source clips.
It does NOT copy from human causal annotation gold, infer a new goal time,
verify FIRST_LIVE, call HTTP, mutate any EDL, or write to BEST.

The machine-readable output is
`/tmp/lpy1_v3a_p14_quality_review_20261113/review_manifest.json`.
Keep **actual MP4s** with the manifest. Event metadata confidence/rank
is not a measure of narrative repair quality.

## What to audit in the actual clips

For each issue, inspect the *finished-cut before/after* first:

1. Is a specific game state, causal action, or emotion missing such that
   the following beat is incomprehensible? If not, report `KEEP_COHERENT`.
2. For a credible deficit, does the source candidate **show** exactly
   that missing information, not merely a high-scoring action?
3. Is the candidate a **continuous first-live original-broadcast** window,
   non-replay, with plausible timeline order? `EVENT_PTS` is not proof.
4. Does the candidate preserve every goal cut? Does the ending move
   monotonically forward (never insert a later action before an earlier
   score confirmation)?
5. Record `DEFECT_CONFIRMED`, `DEFECT_REJECTED`, or
   `EVIDENCE_INSUFFICIENT`; include MP4 source/path/time windows.

Only if both **defect and source evidence** are independently verified
should we use the existing V3-A Planner→Executor→Verifier to attempt **one**
non-goal edit, render a candidate, and compare blind A/B. Do not
modify or relax the FIRST_LIVE gate, invent a video-semantic confirmation,
modify V3-R / Goal Recovery, or hand-edit EDL to claim Agent success.

If zero-pay evidence cannot determine narrative defect status, report
`EVIDENCE_INSUFFICIENT` honestly and request a bounded real-video
semantic review **with explicit approval before any paid API**.
Do not keep iterating heuristics to inflate runtime.

## Acceptance

- 3 finished-story context clips (2 transitions, 1 ending), with source
  candidate clips wherever event-PTS search produced candidates
- SHA-bound source, review manifest, working MP4 clips
- initial 9-segment EDL and 94.877s story unchanged
- HTTP = 0; BEST/P14 original fingerprints unchanged
- no story quality improvement claimed from evidence acquisition alone
- next decision based on a concrete video problem and a concrete
  candidate action, not source-time gaps or clip duration alone

Prior Phase4 failures to avoid: generic bridge insert despite missing
story-fitness confirmation, and post-climax ending segment inserted
*before* an earlier scoreboard, reversing original source chronology.
