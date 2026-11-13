# V3-A minimal Critic / Verifier integration (2026-11-13)

## Scope

This is an **incremental code-only integration**, not a new Planner, EDL
writer, preview pipeline, autonomous FIRST_LIVE verdict, or finished video.

Base: `6b042b676d5248986535eebcc6d259ed865752b2` (existing V3-A).
Working branch: `story-va-v3a-critic-verifier-increment-20261113`.

Only the existing modules `global_story_critic.py`,
`story_video_verifier.py`, and two call sites in `story_e2e_agent.py`
are touched. No modifications to `story_revision_planner.py`, the EDL
Editor, renderer, loop policy, V3-R, V1/V2, human-preview logic or BEST.

## Existing loop retained

V3-R initial story → original Critic + observe → original P13/B2 source
goal localization and VLM (only when independently authorized) → original
Planner → original Executor/renderer → original Verifier → original
feedback/stop policy.

The B2 video model call is **not newly added**: it already existed in
`run_story_e2e`; this patch only binds its output to the matching Critic
goal-coverage issue before the existing Planner runs.

### Critic increment

`merge_goal_video_observation_into_diagnosis` attaches:
- matched issue ID, actual VLM candidate source window, cited frame IDs;
- model-observed shot/net anchor candidates and run source SHA reference;
- explicit `first_live_verified=false`, `auto_edit_authorized=false`.

The original `diagnosis_status` and `story_defect_confirmed` are
unchanged. A VLM claim cannot create first-live proof or bypass existing
source frame re-decode/first-live timeline review.

### Verifier increment

`assess_first_live_business_context` is called within the EXISTING
`verify_story_revision` when it sees EDL-diff new source windows.
It checks:
- candidate EDL explicitly marked replay or slow motion;
- source raw-event context explicitly labeling the **whole** new source
  window as replay (requires genuine start/end media times);
- cited shot/net inside a new goal-action window and single-goal scoreboard
  order (diagnostic only).

Explicit replay conflicts add an existing-style hard veto. A clean label,
score consistency or no detected replay yields **UNRESOLVED** for first
broadcast, never PASS. The original strict source SHA/PTS, independent
first-LIVE ledger and story video Verifier remain authoritative.

Note: this incremental business check is not a full broadcast vision
classifier. It does not resolve unmarked replay in an existing baseline,
and it does not prove improved narrative quality.

## New zero-paid regression coverage

`tests/test_v3a_critic_verifier_increment.py` asserts:
- matching REAL VLM observation is attached only as Critic evidence;
- fixture/mismatched issue cannot bind;
- score/shot/net consistency does not certify first-live;
- explicit candidate replay and whole-window replay-event metadata veto;
- partial replay hints do not automatically hard-veto an entire window;
- incorrect score increments remain unresolved;
- original first-live evidence ledger stays NOT_VERIFIED without proof;
- no new windows means no spurious business failure.

These tests were **added to GitHub but not executed by this authoring
session**. No paid HTTP, server-side VLM, MP4 render or real-video
quality evaluation has been run for this commit.

## Cursor / server: validate without modifying historical artifacts

```bash
git fetch origin story-va-v3a-critic-verifier-increment-20261113
git switch story-va-v3a-critic-verifier-increment-20261113
git pull --ff-only
cd 10.27scasual_chain
python -m compileall -q algo/story_video_agent_v3
PYTHONPATH=.:algo python -m pytest -q \
  tests/test_v3a_critic_verifier_increment.py \
  tests/test_v3a_goal_video_repair.py \
  tests/test_v3a_goal_coverage_critic.py \
  tests/test_v3a_b1_human_assisted_e2e.py
git status --short
git rev-parse HEAD
```

Report *actual* pass/fail, traceback, SHA and source-review verdict.
Keep B1 historical preview and V3-R/V1/V2/BEST unchanged. No new API calls,
no human-attestation reuse, no gold/private EDL and no real-match PASS claim.

Next stage is a **separate** raw-MP4+raw-event fresh V3-R → V3-A E2E
evaluation on a clean output directory and cross-match heldout, with actual
story video judged by the human. Distinguish goal omission, replay detection,
EDL revision, post-edit safety, and perceived story quality.
