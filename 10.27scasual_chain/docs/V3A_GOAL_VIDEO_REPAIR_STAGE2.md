# V3-A Stage-2 missing-goal VIDEO repair: Critic → source footage → gated EDL candidate

**Status: CODE COMMITTED, SERVER RUN NOT YET DONE.** No claim of recovered goal,
FIRST_LIVE_VERIFIED, accepted story, improved story quality, or benchmark score.

Base is the frozen A/B/C DETECTED=true audit at commit `cf9b97c`.
All modifications are on a new isolated branch. The old `agent_run` and
`agent_run_goal_coverage_v1`, prior score JSONs and P14 output stay untouched.

## What changed and what did NOT

Existing P13 `first_live_localize.run_first_live_localization` now runs on the
**score-derived goal_coverage issue** in the main V3-A loop (first round only):
continuous accurate candidate MP4s, sparse/dense frames, and score/replay hints
are saved under `02_round_01/source_goal_video_review/`. No gold target PTS,
no historical correct EDL, no new special-case localization algorithm.

- In zero-paid mode, the result is `VIDEO_REVIEW_PENDING`. Extraction alone
  does not produce a Goal EDL, and `EDL_REPAIRED=false` is expected.
- If explicitly authorized for real API in the future, ONE shared-budget source
  VLM observation can be performed on a localized continuous candidate clip,
  using `remote_vlm_verify.call_goal_verify_round` and the same capped
  `ApiProvider` as Critic/Planner/Verifier. It records shot/net/time/cited
  frames, but does **not** self-certify first-broadcast LIVE or authorize a Goal.
- A dedicated **external source-video proof input**, if supplied, is validated
  before goal insert. It must match the Critic's issue and score states, original
  source SHA, exact source PTS, frame-byte hashes that are **redecoded from the
  original MP4**, continuous source clip hash, explicit shot→net frame IDs and
  attacking-side observation, and a **separate authenticated broadcast timeline
  review**. Raw `LIVE`, `is_replay=false`, model confidence, or
  score-confirmation PTS alone fail this gate.
- If and only if the proof passes, a separate EDL insert is attempted before
  the story's existing next scoreboard anchor. It preserves other goals,
  checks all neighboring PTS, and then goes through the existing duplicate
  audit, renderer, first-live window ledger and full-story Verifier.
  **Creating a repaired CANDIDATE does not mean final acceptance/quality gain.**
- Imported reviews are explicitly `EXTERNALLY_SUPPLIED_VIDEO_REVIEW`;
  even if one carries real-model provenance, it is NOT counted as autonomous
  V3-A video verification because that provider call did not occur in this
  run. Production first-live certification is not inferred from model booleans.

## Zero-paid real-server retest

Use a NEW worktree for branch `story-va-v3a-goal-video-repair-gate`. Preserve
all original A/B/C inputs and original run directories.

```bash
cd 10.27scasual_chain
python -m compileall -q algo/story_video_agent_v3

PYTHONPATH=algo python -m pytest -q \
  tests/test_v3a_goal_video_repair.py \
  tests/test_v3a_goal_coverage_critic.py \
  tests/test_v3a_blind_goal_repair_challenge.py \
  tests/test_v3a_critic_planner_video_handoff.py

PYTHONPATH=algo python -m pytest -q \
  tests/test_v3a_phase8_*.py tests/test_v3a_phase10_*.py \
  tests/test_v3a_phase10d_*.py tests/test_v3a_phase10e_*.py \
  tests/test_v3a_phase10f_*.py \
  tests/test_v3a_p11_raw_input_and_critic_coverage.py

A=/tmp/lpy1_v3a_blind_repair_A_controlled_20261112
B=/tmp/lpy1_v3a_blind_repair_B_historical_20261112
C=/tmp/lpy1_v3a_blind_repair_C_clean_control_20261112
P14=/tmp/lpy1_p14_human_atom_dev_e2e_20261112/run/01_to_04_fresh_v3r

for case in "$A" "$B" "$C"; do
  test -s "$case/run_manifest.json" || exit 2
  test -s "$case/agent_input/04_phase5/story_clean.mp4" || exit 2
done

# Source-video read/cuts/ffmpeg are expected for A and B; NO HTTP calls.
for case in "$A" "$B" "$C"; do
  PYTHONPATH=algo python -m story_video_agent_v3.story_repair_challenge \
    run-offline --case-dir "$case" --run-id goal_video_stage2_v1
done
PYTHONPATH=algo python -m story_video_agent_v3.story_repair_challenge \
  score --case-dir "$A" --run-id goal_video_stage2_v1
PYTHONPATH=algo python -m story_video_agent_v3.story_repair_challenge \
  score --case-dir "$B" --run-id goal_video_stage2_v1 \
  --external-reference-edl "$P14/04_phase5/candidate_edl.json"
PYTHONPATH=algo python -m story_video_agent_v3.story_repair_challenge \
  score --case-dir "$C" --run-id goal_video_stage2_v1
```

IMPORTANT: Existing `--run-id` paths are never overwritten; use a unique tag
if a directory already exists. No `--fixture-revision`, Gold EDL at inference,
`--causal-json` for B, or fabricated goal time in any Agent input.

## What to inspect

For each case:
- `agent_run_goal_video_stage2_v1/02_round_01/story_diagnosis.json`
- `.../evidence_search.json`
- `.../source_goal_video_review/source_goal_video_review_queue.json`
- `.../source_goal_video_review/<goal_coverage_issue_id>/candidate_audits.json`
- `.../goal_video_repair_decisions.json`
- `.../revision_plan.json`, `candidate_edl.json`, `candidate_render.json`
- `.../verifier_report.json` and `99_final/final_edl.json`
- `private_eval/score_goal_video_stage2_v1.json`

Expected in ZERO-paid mode, subject to real execution:

- A/B: `DETECTED=true`, goal clip candidate(s) physically extracted if
  source MP4/ffmpeg work, video semantics and first-LIVE remain UNRESOLVED,
  no unsupported EDL insert, final status `NOT_REPAIRED`.
- C: no goal_coverage issue, no source-goal localizer call, no false edit.
- Keep candidate-level EDL/MP4 metrics separate from accepted FINAL.
- If A/B localization fails, include exception, ffmpeg output, clip byte
  checks, and concrete score bracket. P13's historic `not_found_in_budget`
  meant **no semantic verification**, not proof that a goal was absent.

## Paid/real-model follow-up — DO NOT RUN WITHOUT USER AUTHORIZATION

The CLI already supports `--enable-real-api --i-approve-budget` with
`--max-calls 5 --max-cost-usd 0.10 --max-rounds 1`. When explicitly
authorized, the new `source_goal_vlm_observation.json` is produced from the
same real provider budget as the story Critic and Planner. A positive model
judgment is still only observation; independent first-live timeline validation
remains necessary to safely approve a Goal.

A further optional **external review** path
`--goal-repair-evidence-dir /path/to/authenticated_source_video_reviews`
accepts one JSON named `goal_coverage_*.json` per issue. The format requires
`issue_id`, `score_before`, `score_after`, `source_sha256`,
`media_in/out`, `first_live_evidence` (original SHA+PTS/JPG manifest),
`broadcast_timeline_review` (distinct, authenticated continuous context),
and `video_semantic_observation` with cited shot/net frames, source clip
hash, reviewer provenance. These are INFERENCE evidence sources, **not**
corrected EDLs or downstream Gold. If generated by human review, label the
result `HUMAN_VIDEO_REVIEW_ASSISTED`, never fully autonomous.

Do not manufacture a review file from `score.json`, P14 correct EDL, or
boolean-only `first_live=true`. The unit-test fixture is synthetic control
flow only and must never be treated as actual verified match evidence.

## Exact next scientific hurdle

Demonstrate that an actual source-video model/reviewer can correctly establish
shot, net, score side and FIRST occurrence on the broadcast timeline **without
the Gold EDL**, and that the repaired EDL produces a video whose factual and
narrative quality improves under a blinded full-cut comparison. Then repeat
on a different match/template. A zero-paid structural test alone does not
prove this.
