# V3-A real-failure repair challenge: controlled vs historical missing-goal EDL

Status: **ZERO-PAID SERVER RUN COMPLETE ON `147b8ae`**. A=`NOT_REPAIRED`, B=`NOT_REPAIRED`, C=`NO_UNNECESSARY_EDL_EDIT`. Critic diagnosed temporal jumps only — **no explicit missing-goal detection**; Planner UNRESOLVED; EDL unchanged. Useful failure baseline retained. See `docs/V3A_BLIND_GOAL_REPAIR_SERVER_VERIFY_147b8ae.json`.
No paid HTTP, no replay approval, no story-quality-gain claim.

## Why

Existing P8/P9/P10 tests confirmed that V3-A could render exploratory edits,
but did not prove that it could **diagnose and repair a known actual error**.
P14 recovered three A-match goal actions using DEV atoms. The P11/P12/P13
RAW_EVENTS_ONLY route missed the 1:1 equalizer action. These are excellent
historical positive/negative regression conditions, not new gold benchmarks.

Direct code inspection shows:
- `global_story_critic.structural_diagnosis` checks gaps, ordering, duplicates
  and replay, but has no paired scoreboard→missing goal-action detector.
- `story_evidence_search.search_window_for_issue` handles buildup/transition,
  ending and structural repairs but not `goal_coverage` / missed goal search.
- Existing V3-A cannot be assumed to repair a genuinely missing goal. A
  `NOT_REPAIRED` result is scientifically useful, because failure stage is
  recorded and can guide a **specific** subsequent change.
- No module should silently copy the correct goal window out of P14.

## Two distinct tasks and their data contracts

### A: controlled EDL-only omission (easy)

Constructor removes exactly one **active equalizer_goal_action** row from the
P14 candidate EDL and rerenders the broken MP4 with the original renderer.
P14's upstream Story Plan and enriched events are retained: this is
`HUMAN_ATOM_ENRICHED_DEV`, **NOT** goal discovery from raw video. The
upstream plan might still mention the omitted goal; this case tests whether
V3-A can restore a missing EDL action using allowed upstream information.

### B: genuine historical raw-only failure (harder)

Constructor copies P12's failed Phase5 EDL/MP4/plan verbatim, plus raw events
only (749 events, Goal=0); never passes P14 enriched events, P14 plan, corrected
EDL, or `*_causal.json` to the Agent. The P14 correct EDL is passed **only**
to an evaluator AFTER the V3-A run. Score transitions may guide a search
window, but must not be treated as exact action time. Only original video
semantics can establish action and first-broadcast footage.

### Controls

After these two smoke/regression cases, run a complete P14 no-defect reference
and an unrelated non-goal removable segment to assess false positive edits.
Do not tune runtime based on corrected A timestamps, and never call A a
held-out match.

## Exact server commands (new isolated worktree)

Use branch `story-va-v3a-goal-repair-challenge`; do not overwrite P14/P12.

```bash
cd /data2/lpy1/worktrees/migu-v3a-goal-repair-challenge/10.27scasual_chain

python -m compileall -q algo/story_video_agent_v3
PYTHONPATH=algo python -m pytest tests/test_v3a_blind_goal_repair_challenge.py tests/test_v3a_critic_planner_video_handoff.py -q
PYTHONPATH=algo python -m pytest tests/test_v3a_phase8_*.py tests/test_v3a_phase10_*.py tests/test_v3a_phase10d_*.py tests/test_v3a_phase10e_*.py tests/test_v3a_phase10f_*.py tests/test_v3a_p11_raw_input_and_critic_coverage.py -q

SOURCE="/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4"
RAW="data/交付_out/10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语.json"
P14="/tmp/lpy1_p14_human_atom_dev_e2e_20261112/run/01_to_04_fresh_v3r"
P12="/tmp/lpy1_p12_raw_only_20261112/run/01_to_04_fresh_v3r/04_phase5"
A="/tmp/lpy1_v3a_blind_repair_A_controlled_20261112"
B="/tmp/lpy1_v3a_blind_repair_B_historical_20261112"
C="/tmp/lpy1_v3a_blind_repair_C_clean_control_20261112"

# Preflight: no substitute outputs; if historical MP4 missing, report BLOCKED_INPUT.
test -s "$SOURCE" && test -s "$RAW"
test -s "$P14/04_phase5/candidate_edl.json"
test -s "$P14/04_phase5/story_plan.json"
test -s "$P14/01_enrich/events_enriched.json"
test -s "$P12/candidate_edl.json" && test -s "$P12/story_clean.mp4"

# A: remove one action and render a real *broken* story video.
PYTHONPATH=algo python -m story_video_agent_v3.story_repair_challenge controlled \
  --complete-edl "$P14/04_phase5/candidate_edl.json" \
  --story-plan "$P14/04_phase5/story_plan.json" \
  --events-json "$P14/01_enrich/events_enriched.json" \
  --source-mp4 "$SOURCE" --omit-role equalizer_goal_action \
  --case-dir "$A"
PYTHONPATH=algo python -m story_video_agent_v3.story_repair_challenge run-offline --case-dir "$A"
PYTHONPATH=algo python -m story_video_agent_v3.story_repair_challenge score --case-dir "$A"

# C: unmodified P14 cut is the negative control — do NOT invent repairs.
PYTHONPATH=algo python -m story_video_agent_v3.story_repair_challenge clean-control \
  --complete-edl "$P14/04_phase5/candidate_edl.json" \
  --story-plan "$P14/04_phase5/story_plan.json" \
  --baseline-mp4 "$P14/04_phase5/story_clean.mp4" \
  --events-json "$P14/01_enrich/events_enriched.json" \
  --source-mp4 "$SOURCE" --case-dir "$C"
PYTHONPATH=algo python -m story_video_agent_v3.story_repair_challenge run-offline --case-dir "$C"
PYTHONPATH=algo python -m story_video_agent_v3.story_repair_challenge score --case-dir "$C"

# B: replay actual P12 failure, without gold input.
PYTHONPATH=algo python -m story_video_agent_v3.story_repair_challenge historical \
  --failed-phase5 "$P12" --raw-events-json "$RAW" \
  --source-mp4 "$SOURCE" --case-dir "$B"
PYTHONPATH=algo python -m story_video_agent_v3.story_repair_challenge run-offline --case-dir "$B"

# This is post-run EVALUATION ONLY, not an inference argument.
PYTHONPATH=algo python -m story_video_agent_v3.story_repair_challenge score \
  --case-dir "$B" \
  --external-reference-edl "$P14/04_phase5/candidate_edl.json"
```

All three runs are **zero HTTP, main-chain V3-A**. Run-offline must not sneak in
`fixture_revision`, `confirm_issue_ids`, or `phase8_round_fixtures`.
The mere presence of a missing 1:1 in a private score file does not supply
an issue, time window or repair plan to the Agent.

## Report exact failure stage, not just a final label

Inspect:
- `agent_run/02_round_01/story_diagnosis.json` (Critic)
- `agent_run/02_round_01/evidence_search.json` (source-bound Search)
- `agent_run/02_round_01/revision_plan.json` (Planner)
- `agent_run/02_round_01/candidate_edl.json` and `edl_diff.json` (Editor)
- `agent_run/02_round_01/candidate_render.json` (Renderer)
- `agent_run/02_round_01/verifier_report.json` if present (Verifier)
- `agent_run/99_final/final_edl.json` and actual MP4 if rendered
- `private_eval/score.json` (evaluator; **not input**)

Conservative pass tiers:

1. `DETECTED`: specifically diagnosed missing goal vs generic source-time gap.
2. `GROUNDED`: located goal action in the original video, with cited source
   window and no Gold reference at inference.
3. `EDL_REPAIRED`: output includes correct action source window, other goals
   intact, source PTS monotonic, candidate MP4 actually rendered.
4. `FIRST_LIVE_VERIFIED`: independent video-based first-broadcast proof, not
   just `is_replay=false` or annotation LIVE.
5. `STORY_IMPROVED`: independently rated full-cut improvement vs broken
   story (and no regression vs original good P14 story).

The evaluator's automatic `EDL_WINDOW_RESTORED_UNVERIFIED` is an intermediate
result, **never** a claim of levels 4–5.

## What to do after the first test

If explicit goal omission is absent in Critic, add a **generic score-transition
vs narrative action-coverage hypothesis**, grounded in raw scoreboard records
and/or paired result footage; do not hardcode `6448`, the match, or the EDL
segment ID. If Critic detects but Search fails, reuse existing Goal Recovery /
first_live_localize to search only permitted source windows. If Search finds a
candidate but cannot verify it, retain UNRESOLVED, do not auto-inject. If it
produces an EDL but no video, fix apply/render contract. Only after a successful
A and B attempt on A can we transfer to unseen B-match/new story templates.

Do not reintroduce human causal Gold into B, bypass replay gates, use a
`--fixture-revision` cheat, or count tests as an autonomous success.
