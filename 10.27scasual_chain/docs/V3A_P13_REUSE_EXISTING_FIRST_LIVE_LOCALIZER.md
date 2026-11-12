# P13 — Reuse established first-LIVE video localizer (no parallel model)

Branch: `story-va-v3a-p13-reuse-first-live-localizer`
Base: P12 server-verified `4e90953603b6f008eb06f99487f6518cf6aad333`.

## Critical distinction: execution passed, goal missing, release blocked

P12 actual raw-only A pipeline:
- Three score-confirmed single-goal transitions; only two weak detector-event
  action priors. Equalizer `goalcand_03_01_to_11` has
  `goal_action_sec=null`, confirmation 6535.62s, raw score bracket
  [6410.07s,6535.62s]; Phase5 has scoreboard, no equalizer action.
- P12 recorded `03_score_confirmed_goal_action_missing` while
  `all_required_valid=True`, because the aggregate only checked stage
  `valid` bits. P13 corrects this. `pipeline_stages_valid` may remain
  true while `all_required_valid` is false due to a semantic blocker.
  `story_goal_actions_present` denotes only timestamp *presence*,
  never first-LIVE visual proof.
- P12 25/25 sparse frame extraction successful, but no visual goal
  verification and 2 retained goals UNRESOLVED. No story-quality gain.

## Reuse instead of reinventing

Existing `first_live_localize.py` already implements:
- Canonical source-event and replay cue parsing;
- OCR densification and observed score bounds;
- Budgeted temporal candidate prioritization;
- Continuous reencoded clips + accurate and dense frames;
- Separate semantic evidence / First-LIVE status and rejection.

P13 makes `load_events_rows` reuse the canonical raw score decoder
(`attributes.Score_Recognition` / `scores.score_recognition`) so it
agrees with `goal_recovery.py`; fixes zero-valued media starts and
broadcast phase REPLAY recognition.

P13 adds a **thin entrypoint inside the existing file**,
`localize_unresolved_recovered_goals`, accepting *only* original MP4,
original events JSON, and generated raw-only Goal Recovery output. It
selects missing-action candidates and calls the existing
`run_first_live_localization`, not a newly written detector. Raw
video and event file SHA-256 must match the frozen P11 input if supplied.
No human scores, historical P3/P4 timing overlays, causal JSON, sealed
P10-F labels, gold, paid API, or Phase5 reuse.

The result is a real video/OCR/continuous-clip evidence pack for the
**existing** first-live verifier. This zero-paid run does **not** itself
establish shot/net or first-LIVE, and does NOT modify Goal Recovery
actions or EDL. Any semantic upgrade requires genuinely reviewable
video evidence and a separate safe binding.

## Cursor: one targeted zero-paid run, do NOT rerun full Phase5

Checkout this P13 branch in an isolated worktree. Then:
```bash
cd 10.27scasual_chain
python -m compileall -q algo/story_video_agent_v3
PYTHONPATH=algo python -m pytest -q \
  tests/test_v3a_p13_reuse_goal_localizer_and_semantic_gate.py \
  tests/test_v3a_p12_goal_evidence_recall.py \
  tests/test_v3a_p11_raw_input_and_critic_coverage.py

EVENTS="/data2/lpy1/worktrees/migu-v3a-p11-verify/10.27scasual_chain/data/交付_out/10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语.json"
SOURCE="/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4"
RECOVERY="/tmp/lpy1_p12_raw_only_20261112/run/01_to_04_fresh_v3r/03_v1_adapt/goal_recovery.json"
OUT="/tmp/lpy1_p13_equalizer_source_video_evidence_20261112"

PYTHONPATH=algo python -m story_video_agent_v3.first_live_localize \
  --source-mp4 "$SOURCE" \
  --events-json "$EVENTS" \
  --goal-recovery "$RECOVERY" \
  --candidate-id goalcand_03_01_to_11 \
  --max-candidates 4 --max-video-read-sec 90 \
  --expected-events-sha256 ddae99b21cbfcd1c75ddf620d957578e57c2c013d607ac893655c4d52b7e779e \
  --expected-source-sha256 a66147f79609c8fbf831a8bd29de4c6d7f746b314b2b18a88ffb1fc5f319da9c \
  --out-dir "$OUT"
```

The run uses existing OCR by default. If OCR dependencies fail,
record the failure and, **separately**, rerun with `--skip-ocr` in a
fresh output directory, clearly identifying this as an ablation.
Do not silently downgrade the primary OCR run.

## Required server feedback

Report exact code SHA and pytest results; raw events+MP4 hashes;
`score_bounds.json` (OCR vs raw observation bracket);
`localization_plan.json` candidate interval and origin;
`candidate_audits.json` source PTS, clip/frames/dense-frames paths,
extraction success, classification and evidence gaps; `evidence_pack.json`
and the top one or two continuous clips/frame indices. Provide provenance
for each clip, and say whether the visible goal action/shot/net and *first*
LIVE were *actually* demonstrated or remain UNRESOLVED. A heuristic
`possible_first_live` is not FIRST_LIVE_VERIFIED.

Do not edit algorithm code in Cursor, fake model outcomes, fill Goal
timestamps from scoreboard, insert clips into EDL, override a BLOCKED
delivery, inspect sealed P10-F data or spend on a provider. Return
artifacts so ChatGPT can directly review code/evidence and decide the
next verified integration step.

## End goals / quality criterion

(1) Generic no-gold source MP4+raw events Video Story Agent: complete
goal actions, first-LIVE, correct causal short/long chains, smooth
buildup/ending, Critic→Planner→Verifier revisions and held-out
matches/templates. User independently judges cut quality.

(2) One ACL paper: ~50% event+18-class short causal chain+new global
story benchmark; ~50% the complete end-to-end Agent, with strong
baselines, ablations, video-grounded and held-out evaluation.

No improvement or correctness claims before source-video evidence.
P13 is a reusable video-evidence step, not a confirmed-goal detector.
