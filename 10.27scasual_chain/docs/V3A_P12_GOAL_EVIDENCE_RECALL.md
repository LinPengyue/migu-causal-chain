# P12 — Score-confirmed goal action evidence recall (zero paid)

Branch: `story-va-v3a-p12-goal-evidence-recall`. Base: P11 verified
`a14b16360f0dae3d105e4364fa18d319a9b1427a`.

## Why

P11 genuine raw-only A match produced 3 single-goal score transitions,
but only 2 provisional detector-event action times. The equalizer
`goalcand_03_01_to_11` has `goal_action_sec=null`, confirmed board
at 6535.62, score observation bracket [6410.07,6535.62], no nearby
eligible detector events. Phase5 emitted a scoreboard anchor but no
equalizer goal-action segment. The other two goal actions are also
provisional, NOT first-LIVE verified. Two live audits remain UNRESOLVED.

A missing detector event is not proof that video contains no goal.
Nor is a scoreboard transition, a predicted strip class or a nearby
event evidence of the ball crossing the line.

## Code change

- Reuse `goal_recovery.py`, not another goal detector. For each
  score-confirmed single-goal transition with no action, emit at most
  five time-bounded, spread-across-bracket video observation requests.
  Each request carries candidate identity, score transition, PTS
  interval, optional overlapping strip IDs, and hard
  `no_action_time_inferred`/`no_automatic_edl_insertion` flags.
  It does **not** populate `goal_action_sec`, insert EDL footage or
  claim first LIVE.
- The official `evaluate_stages` report now distinguishes the
  successfully executed adaptation stage from release-grade goal
  completeness. `03_score_confirmed_goal_action_missing` blocks
  `all_required_valid` even when `03_v1_adapt.valid=true`.
- No P10-F sealed labels, manual causal JSON, Gold, overlays, paid
  VLM, source-specific timestamps, or changes to the frozen 8.31
  algorithm. Historical V3-R BEST is untouched.

## Cursor instructions (no algorithm edits, no paid API)

```bash
cd 10.27scasual_chain
python -m compileall -q algo/story_video_agent_v3
PYTHONPATH=algo python -m pytest -q \
  tests/test_v3a_p12_goal_evidence_recall.py \
  tests/test_v3a_p11_raw_input_and_critic_coverage.py
PYTHONPATH=algo python -m pytest -q tests/test_v3a_phase8_*.py
PYTHONPATH=algo python -m pytest -q \
  tests/test_v3a_phase10_*.py tests/test_v3a_phase10d_*.py \
  tests/test_v3a_phase10e_*.py tests/test_v3a_phase10f_*.py
```

Then run fresh raw-only A in a **new** directory with the exact
original events JSON and source MP4 from the P11 report; use
`--strict-raw-only --no-smoke-render --max-rounds 1` and NO
`--causal-json`. The expected output may exit 1/BLOCKED;
do not patch around the gate. Record PTS monotonic, recovered goal
counts, `pending_goal_video_search`, stage blocker and first-LIVE
statuses. Do not reuse Phase5, human causal data or sealed labels.

**Zero-paid inspection request:** Extract a few uniformly spaced
source-video frames from each P12 proposed window for the equalizer,
plus 1–2s before/after where allowed. This is visual scouting only:
do not claim a first-LIVE verified action, do not splice footage and
do not declare the goal found based on a scoreboard. Save frame
paths, exact source PTS, extraction failures and source hash. If
a frame pack cannot be transported, provide a server artifact index
without inventing a sandbox link. A later video-grounded verifier
must establish shot/net, first-live broadcast status and action
boundaries before any EDL insertion. Do not use user-seen prior
goal timestamps as algorithm inputs.

## Final goals

1. Generic cross-match, cross-story-template **raw MP4 + raw events**
   agent: goal action completeness, first-live, causal planning,
   coherent buildup/ending, evidence-grounded revision and delivery.
2. One ACL paper with benchmark (~half: 18 local chain classes +
   newly annotated global story chains) and complete E2E Agent (~half).
   No novelty or quality claim until independent held-out evidence.

**Status:** code submitted, server regression and real-video evidence
pending. No demonstrated improvement in story quality.
