# V3-A Missing-Goal Challenge: First Actual Algorithm Repair (Critic → Search)

Status: **ZERO-PAID SERVER RETEST COMPLETE ON `0187eee` (`goal_coverage_v1`)**. A/B `DETECTED=true` (`goal_coverage_01_to_11`), still `NOT_REPAIRED` / `EDL_REPAIRED=false`. C remains `NO_UNNECESSARY_EDL_EDIT` without false goal_coverage. Prior `572e153` artifacts preserved. See `docs/V3A_GOAL_COVERAGE_CRITIC_SERVER_VERIFY_0187eee.json`.
real V3-A's failure detection and source-evidence search, NOT proof of a recovered
goal, first broadcast, or better finished story.

## Baseline evidence, untouched

- Prior three-case blind run: `572e153`, A/B `NOT_REPAIRED` with no explicit
  missing-goal diagnosis; C `NO_UNNECESSARY_EDL_EDIT`.
- Actual source inputs under the prior three prepared challenge directories:
  `/tmp/lpy1_v3a_blind_repair_{A_controlled,B_historical,C_clean_control}_20261112`.
- V3-R/P14 `HUMAN_ATOM_ENRICHED_DEV` baseline remains a development reference
  only; the 1:1 correct PTS is held privately by the grader, never read by
  `run_story_e2e()`.

## What changed

1. `global_story_critic.detect_goal_coverage_hypotheses`: reuses existing
   `goal_recovery.recover_goal_candidates` score transitions (single +1
   increments only). Maps each observation to at most one active, non-replay
   `goal_action` cut using a bounded prior before score confirmation. Distinct
   single-score transitions without goal-action coverage produce
   `category=goal_coverage`, `HYPOTHESIS_NEEDS_VIDEO`, and a search bracket.
   `score_confirmation_sec` is NEVER `goal_action_sec`; no target row or
   corrected EDL is imported. Existing action coverage tolerates delayed
   scoreboards, but source search can be narrowed using the last observed
   older score plus a generic 30s buffer. The Critic's story-video
   observation spans both sides of the gap cut seam rather than zero seconds.
2. `story_e2e_agent.run_story_e2e`: the Critic and source Search read the same
   permitted original/enriched events. A's enriched Goal atoms are DEV-only,
   B's 749 raw events have zero Goal and can still produce score transitions.
3. `story_evidence_search`: prioritizes goal-coverage diagnostics before
   generic temporal jumps, searches the bounded bracket for live-labelled
   action *candidates*, and marks them `goal_probe_only`. No candidate
   is deemed FIRST_LIVE_VERIFIED or goal-semantic-confirmed from event PTS.
   `goal_action_probe` roles cannot go through the current generic auto-add
   code. A separate post-LLM `goal_coverage_mutation_gate` also blocks a
   text Planner from fabricating a goal-action insert solely from scoreboard
   timing. We still need a dedicated video-semantic goal confirmation and
   goal-action replacement/insertion mechanism.
4. Challenge CLI supports `--run-id goal_coverage_v1`: rerun the **same
   frozen prepared cases** in separate `agent_run_goal_coverage_v1` folders,
   without re-rendering their baseline videos or overwriting prior audits.
   Tagged scores are written to `private_eval/score_goal_coverage_v1.json`;
   the original `private_eval/score.json` stays unchanged.

These are match-agnostic engineering rules. Do not infer any match goal count,
timestamp, exact scoreline, expected role, or benchmark gold at inference.

## Server commands (all zero paid)

```bash
# In a NEW worktree on origin/story-va-v3a-goal-coverage-critic
cd 10.27scasual_chain
python -m compileall -q algo/story_video_agent_v3

PYTHONPATH=algo python -m pytest \
  tests/test_v3a_goal_coverage_critic.py \
  tests/test_v3a_blind_goal_repair_challenge.py \
  tests/test_v3a_critic_planner_video_handoff.py -q

PYTHONPATH=algo python -m pytest \
  tests/test_v3a_phase8_*.py tests/test_v3a_phase10_*.py \
  tests/test_v3a_phase10d_*.py tests/test_v3a_phase10e_*.py \
  tests/test_v3a_phase10f_*.py \
  tests/test_v3a_p11_raw_input_and_critic_coverage.py -q

A=/tmp/lpy1_v3a_blind_repair_A_controlled_20261112
B=/tmp/lpy1_v3a_blind_repair_B_historical_20261112
C=/tmp/lpy1_v3a_blind_repair_C_clean_control_20261112
P14=/tmp/lpy1_p14_human_atom_dev_e2e_20261112/run/01_to_04_fresh_v3r
for case in "$A" "$B" "$C"; do
    test -s "$case/run_manifest.json" || exit 2
    test -s "$case/agent_input/04_phase5/candidate_edl.json" || exit 2
done
test -s "$P14/04_phase5/candidate_edl.json" || exit 2

PYTHONPATH=algo python -m story_video_agent_v3.story_repair_challenge \
  run-offline --case-dir "$A" --run-id goal_coverage_v1
PYTHONPATH=algo python -m story_video_agent_v3.story_repair_challenge \
  score --case-dir "$A" --run-id goal_coverage_v1

PYTHONPATH=algo python -m story_video_agent_v3.story_repair_challenge \
  run-offline --case-dir "$B" --run-id goal_coverage_v1
PYTHONPATH=algo python -m story_video_agent_v3.story_repair_challenge \
  score --case-dir "$B" --run-id goal_coverage_v1 \
  --external-reference-edl "$P14/04_phase5/candidate_edl.json"

PYTHONPATH=algo python -m story_video_agent_v3.story_repair_challenge \
  run-offline --case-dir "$C" --run-id goal_coverage_v1
PYTHONPATH=algo python -m story_video_agent_v3.story_repair_challenge \
  score --case-dir "$C" --run-id goal_coverage_v1
```

If an old tagged output exists, choose `--run-id goal_coverage_v2` for **all**
corresponding runs and scorers; never delete prior evidence to force a rerun.

## Evaluation matrix

| Case | Expected first incremental proof | What is NOT claimed |
|---|---|---|
| A (EDL drop) | `explicit_goal_omission_diagnosed=true`, one 0:1→1:1 issue | first-live goal, repaired EDL, improved MP4 |
| B (raw-only historical) | Same score-transition-based issue **without human Goal input** | exact goal_action PTS / automatic video recovery |
| C (intact baseline) | No `goal_coverage` issue, `NO_UNNECESSARY_EDL_EDIT` | full source LIVE compliance |

Use *actual results*, not expected values, for final judgments.

For A/B, inspect:
- `agent_run_goal_coverage_v1/02_round_01/story_diagnosis.json`:
  `goal_coverage`, `score_before`, `score_after`, `possible_action_interval`,
  `story_defect_confirmed=false`.
- `.../02_round_01/evidence_search.json`: `targets` includes
  `missing_goal_action_evidence_search`. Candidate `EVENT_PTS_CANDIDATE`
  is NOT first-live verified.
- `.../02_round_01/revision_plan.json`: if no semantic video verification,
  must stay KEEP/UNRESOLVED and cannot mutate a goal-action EDL.
- `agent_run_goal_coverage_v1/99_final/final_edl.json` and
  `private_eval/score.json`: detect ≠ repair.
- A/B/C compare with `agent_run/...` from original `572e153` run.

## If A/B detect but cannot autonomously repair

That will be the **next** genuine technical blocker, not an excuse to fake
success. Reuse P13's source-score bracket and existing
`first_live_localize`/visual verification, obtain shot/net/team/continuous
first-broadcast evidence, then authorize a generic missing-goal EDL insertion
*only* after verifying the action. Do not treat source-board confirmation as
action timestamp, do not silently reuse a P14 known-good PTS or frozen goal
window, and do not count a model-only quality score as a better full cut.

Longer term: repeat with B Osasuna–Celta and a different narrative template.
A is a known development match, never held-out generalization evidence.
