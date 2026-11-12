# P11 — Raw-only unified E2E + evidence-budgeted fullcut Critic

**Status: SOURCE COMMITTED; SERVER REGRESSION AND REAL-VIDEO VALIDATION PENDING.**
Branch: `story-va-v3a-p11-raw-input-coverage`, based directly on verified
P10-F `10b1c06` (NOT the superseded P10-G diagnostic branch).
Historical BEST remains unmodified V3-R. No paid API authorized by this patch.
P10-F sealed risk predictions must remain unread until human labels are locked.

## Historical evidence and decisions

- P8 already implements structural duplicate audit, video-cited duplicate
  hypotheses, before/candidate/after narrative-fit review, fullcut comparison
  and non-additive revision feedback. Do not replace those components.
- Real P9 Critic/Planner often returned UNRESOLVED with no confirmed defect
  and no candidate; P10-D had a real bounded model-proposed exploratory drop,
  but human comparison on A favored keeping its motivation/effort buildup.
- P10-E is role-based, quality unverified. P10-F B strict_lin blind Y was
  preferred for pre-goal buildup, but the human noticed brief apparently
  unrelated visual events. Neither blind identity nor sealed model risk is
  a runtime feature or a benchmark label. B closed-loop baseline had
  non-monotonic PTS and correctly blocked exploration.
- Existing `run_vlm_story_critic` previously used 4 dense frames from one
  issue OR the first eight global frames, which could starve uninspected
  shots and the ending. More prompt wording alone cannot fix missing evidence.

## Changes (minimal reuse)

1. `atomic_event_enrich.enrich_files(causal_path=None)` copies raw event
   information without inventing Gold/Goal atoms. Legacy human atom
   supplementation is still available for DEV reproduction, labeled
   `HUMAN_ATOM_ENRICHED_DEV` and ineligible for raw-only evaluation.
2. `closed_loop_cli.run_match` and `story_e2e_agent.resolve_baseline`
   permit optional `causal_atoms_path=None`. Reuse existing score-based Goal
   Recovery, predicted 8.31 causal chain, Phase5 V3-R and unified V3-A loop.
   Do not silently backfill missing Goal from human labels. The existing
   V2 adapter's score-field precedence is reused for both
   `attributes.Score_Recognition` and `scores.score_recognition` (list/string),
   including alternate raw delivery variants. Score confirmation remains
   distinct from visually verified goal action. A match lacking recoverable
   score transitions must remain UNRESOLVED/BLOCKED.
3. `story_full_e2e_cli` accepts just `--events-json --source-mp4`, adds
   `--strict-raw-only` to reject annotated causal inputs and records exact
   input mode in the contract and run summary. A legacy `--causal-json` run
   must NEVER be counted as benchmark-eligible raw-only inference.
4. Fresh input EDL with source PTS inversion is BLOCKED before the Agent
   revision loop. The official stage validity also rejects it. Do not sort
   cuts or silently drop an atom-fill conflict.
5. `story_observe` attaches actual story playback times to already
   extracted global/paragraph finished-cut frames.
6. `story_paid_eval.select_critic_frame_bundle` reuses extracted evidence
   and spends **at most 10 frames per Critic call**, balancing a small dense
   issue context with examples across distinct EDL segments. The actual
   `frame_coverage` lists observed and UNOBSERVED media segment IDs. A
   segment name or role alone NEVER counts as visual observation.
7. Exact story-cut seams map to the following EDL segment. Decoder
   frames within 0.4 seconds of nominal seams are **NOT** assigned to a
   trusted segment ID for editorial evidence claims.
8. `story_editorial_redundancy` adds a second, separate signal:
   `narrative_relevance` (unique event may be irrelevant, not duplicated).
   It requires hashed frame citations for the exact preceding, candidate,
   and following media segments. These are hypotheses only:
   `story_defect_confirmed=false`, `no_automatic_edit_authorized=true`.
   Existing Planner/Verifier evidence and release gates remain untouched.

### Limitations that must remain explicit

- One frame per segment is not equivalent to a full visual review or audio
  narrative judgment. A frame budget smaller than the EDL segment count will
  leave UNOBSERVED entries; no false full-coverage claim.
- Both human-reported B interruptions may occur inside or near protected
  goal/score windows. A bounded source-frame inspection is necessary to
  distinguish unrelated broadcast inserts, commentary, cut seams and
  genuine action context. P11 does not automatically trim protected goals.
- A genuine video-grounded irrelevance hypothesis may be rejected by
  formal Planner, which is deliberate; optional P10-C exploratory experiments
  remain subject to independent human fullcut review.
- Another historical `fresh_e2e_cli` still calls the earlier
  `self_revise_agent`. It is NOT the official raw-only evaluation entrypoint.
- No claims of better story quality, new-template generalization, achieved
  first LIVE, autonomous deletion, gold-free performance or ACL novelty.

## Cursor: zero-paid server checks only

Create a fresh worktree from P11 HEAD; do not edit algorithm code in Cursor
and do not alter any frozen previous output. Log code SHA and exact commands.

```bash
cd 10.27scasual_chain
python -m compileall -q algo/story_video_agent_v3
PYTHONPATH=algo python -m pytest -q tests/test_v3a_p11_raw_input_and_critic_coverage.py
PYTHONPATH=algo python -m pytest -q tests/test_v3a_phase8_*.py
PYTHONPATH=algo python -m pytest -q \
  tests/test_v3a_phase10_*.py tests/test_v3a_phase10d_*.py \
  tests/test_v3a_phase10e_*.py tests/test_v3a_phase10f_*.py
```

Run P11 official **raw-only**, *not* reuse-Phase5. Use the existing exact
original events file and original video; no annotated causal JSON, predicted
chain, enriched events, EDL, gold label or cached human state as inputs.
No paid flags and a fresh unique output directory:

```bash
PYTHONPATH=algo python -m story_video_agent_v3.story_full_e2e_cli \
  --source-mp4 "$SOURCE_MP4" --events-json "$RAW_EVENTS_JSON" \
  --strict-raw-only --no-smoke-render --max-rounds 1 \
  --out-dir "$NEW_P11_RAW_ONLY_OUT"
```

If recovery/strip/phase5 fails, preserve failure and all completed artifacts;
do NOT substitute human causal JSON or cached Phase5 to make the test green.
Summarize stage validity, Goal Recovery candidate_count, predicted-chain entry,
first-LIVE gate, PTS safety, and final delivery status. Never report a partial
baseline as a verified deliverable.

After an offline E2E run, inspect coverage selection without paying for VLM:

```bash
PYTHONPATH=algo python - <<'PY'
import json, os
from pathlib import Path
from story_video_agent_v3.story_paid_eval import select_critic_frame_bundle
root = Path(os.environ["NEW_P11_RAW_ONLY_OUT"]) / "02_round_01"
obs = json.loads((root/"observe"/"layered_observe.json").read_text())
diag = json.loads((root/"story_diagnosis.json").read_text())
print(json.dumps(select_critic_frame_bundle(obs, diag)["coverage"], indent=2))
PY
```

Verify that early, middle and tail EDL segments receive bounded coverage when
there are available sampled frames, and that unseen segments remain UNKNOWN.
This offline selector does not call VLM; real semantic findings are still
PENDING. The true fullcut VLM schema and visual-citation validator should
only be exercised in an *explicitly authorized* later paid trial.

**Report required:** compileall result, all pytest pass/fail/skip counts,
raw-only command, input source SHA, failed/valid stage facts, nonmonotonic
breaks, coverage ledger, changed-file diffs and exact artifact locations.

## ACL evaluation implication

Keep benchmark gold outside the inference chain. Report observed-segment
coverage and semantic false-positive/abstention rates against independently
collected holdout labels; test unseen matches AND unseen story templates.
A gate-confirmed algorithm patch is not automatically a method contribution.
