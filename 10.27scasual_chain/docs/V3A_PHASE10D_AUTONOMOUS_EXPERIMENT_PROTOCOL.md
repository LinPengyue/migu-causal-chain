# P10-D: authentic model-selected exploratory story cut

Status: **CODE PREPARED, SERVER REGRESSION PENDING, NO NEW PAID RUN**.
Branch: `story-va-v3a-phase10d-real-autonomous`. V3-R remains BEST.

## Objective

Unlike P10-C's local fixture `drop seg_buildup_event_000472`, P10-D
requires a real VLM Critic and LLM Planner to inspect the actual match
and independently propose an exploratory action and exact target. The
candidate must render as a full MP4 with blind X/Y. A rendered pair
does NOT establish better narrative quality. No automatic BEST promotion.

## Code changes

- `story_e2e_agent.py`: records `phase10d_provenance.json` for each
  first-round exploration. Separately identifies a real, successful paid
  Planner result, exact model-chosen target/action, fixture use, render
  status and current cost/call audit. It does not rewrite the formal
  revision decision. Model provenance survives a budget-cap transition
  after Planner completion.
- `story_phase10d_audit.py`: read-only offline checker categorizes
  `FIXTURE_ONLY`, `NO_VERIFIED_REAL_PLANNER_PROPOSAL`,
  `MODEL_PROPOSED_BUT_NOT_RENDERED`, or
  `MODEL_PROPOSED_AND_RENDERED`. All remain
  `human_story_quality=UNVERIFIED`.
- `tests/test_v3a_phase10d_autonomy_audit.py`: verifies classification
  and no false quality/release claim.

## Cursor task A: ZERO PAID REGRESSION (authorized now)

Create a NEW independent worktree on the Phase10-D branch. Do not
modify source, merge, or use API keys.

```bash
cd 10.27scasual_chain
python -m compileall -q algo/story_video_agent_v3
PYTHONPATH=algo python -m pytest tests/test_v3a_phase10_*.py -q
PYTHONPATH=algo python -m pytest tests/test_v3a_phase8_*.py -q
```

Re-run the known Phase10-C offline fixture on real A frozen Phase5
with a NEW output directory (same raw inputs and local fixture as in
P10-C report), `--phase10-explore --phase10-explore-fixture`,
`--max-rounds 1 --no-smoke-render`. No `--enable-real-api`.
Check the new provenance JSON records `fixture_used=true` and
`real_model_proposal=false`. The auditor must classify it
`FIXTURE_ONLY` even if X/Y MP4s render successfully:

```bash
PYTHONPATH=algo python -m story_video_agent_v3.story_phase10d_audit \
  --run-dir "$P10D_OFFLINE_RUN_DIR" \
  --out "$P10D_OFFLINE_REPORT_DIR/autonomy_audit.json"
```

Record code SHA, 0 paid calls, checks, source MP4 and EDL hashes,
blind pair paths, and any regression or schema mismatch. Push
verification JSON to the experiment branch. Keep large videos on
server, not Git.

## Cursor task B: PAID REAL-MODEL EXPERIMENT (NOT YET AUTHORIZED)

**Do not execute task B until user explicitly confirms a maximum USD
budget for this new P10-D run.** A previous Phase9 budget and an
instruction to continue coding are not new payment authorization.

After approval, use existing source MP4 and event JSON, frozen V3-R
Phase5, a unique output directory and the existing capped real-provider
configuration. Explicitly enable the *existing* provider budget flags
and `--phase10-explore`; do NOT pass a fixture. Start with A, max
rounds 1, cap <=5 calls, <=$0.10 estimated, zero retries. The USD cap
is an *estimate* and not a guaranteed provider invoice ceiling.

Verify first:
- provider readiness, no API key leakage, no gold or human labels;
- source SHA/EDL identity, PTS and first-live constraints;
- `llm_revision_planner.json` has a real provider, valid model JSON
  and a separate `exploratory_intents[0]`;
- `phase10d_provenance.json` agrees with real Planner audit and
  `exploratory_trial.json`;
- candidate fullcut ffprobe/EDL alignment, three goals preserved;
- no formal revision or release approval inferred from an exploratory
  trial; X/Y private allocation remains separate.

The model may reasonably decline to propose anything. Report this
as `NO_VERIFIED_REAL_PLANNER_PROPOSAL`, not a failure to force a
candidate. If model output is invalid or a source/goal gate rejects
it, report exact reason; do not patch the input to manufacture success.

## Research gates after a real run

- A model-selected valid candidate is only *autonomous proposal
  feasibility*, not improved quality.
- Blind review must use complete X/Y MP4, G0 first-live/source and
  match-fact checks, and P10-A G1/G2. One human viewer's feedback is
  developmental, not a formal 3+ rater consensus.
- Repeat on B and held-out matches and story families before claims of
  cross-match generalization. Compare matched budgets with and without
  narrative graph and exploration.
