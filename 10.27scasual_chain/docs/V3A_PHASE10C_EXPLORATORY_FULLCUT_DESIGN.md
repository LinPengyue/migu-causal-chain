# V3-A Phase 10-C | Isolated exploratory edit → fullcut X/Y blind comparison

Status: **IMPLEMENTED; ZERO-PAID SERVER REGRESSION GREEN ON `fda622c`**.
Engineering fixture trial does **not** imply scientifically demonstrated
story improvement.

Branch: `story-va-v3a-phase10c-exploratory` (from latest
`story-va-v3a-phase10-narrative-quality`, including its pending typed
event/short-causal-link repair). No edits to V1, V2 or V3-R sources.

## 1. Why Phase9 had no candidate

The Phase9 authentic Qwen3.7-Plus Critic inspected sampled frames and did not
confirm a genuine story defect; DeepSeek Planner correctly returned UNRESOLVED
and no candidate. That was correct formal-release behavior, but a story could
still improve via removing a repetitious bridge, tightening an overlong beat
or changing an unprotected presentation order.

Phase10-C tests a **conditional improvement hypothesis** without pretending a
defect was confirmed. Candidate generation and actual human-quality evidence
are separate. No forced filler / time-gap padding / fake verified labels.

## 2. Implementation architecture

Current authorized production path (unchanged):
```
working V3-R EDL → global observation → VLM Critic → strict Planner
  → verified source edits only → real Verifier → delivery gates → BEST
```

New opt-in side path (one trial, first round only):
```
same existing LLM Planner response
  → optional exploratory_intents[0] (hypothesis, expected effect, risk, exact target)
  → independent bounded-EDL mutation on a deep copy
  → pre-render source PTS / protected anchor / no-replay checks
  → original full-story renderer
  → both MP4s must be ffprobe duration-aligned with their respective EDL
  → blind_review/X.mp4 + Y.mp4
  → separate PRIVATE_unblinding.json
  → human G0/G1/G2 evaluation; NEVER automatic BEST
```

No extra HTTP step is added: the existing LLM Planner call requests an extra
optional proposal field only with `--phase10-explore`. Without real-API
authorization or explicitly supplied local fixture, no proposal is executed.
Unconfirmed story hypotheses are NOT injected into the formal revision plan.
If formal Planner chooses REVISE, the strict main revision takes precedence
and exploratory side-run is skipped.

### Implemented actions (v1)

- `drop`: remove one existing nonprotected active clip from the cut;
  no new source PTS. Never delete actual goal, opening, scoreboard, title,
  ending, final/VAR/penalty/red-card, or explicitly protected anchors.
- `trim`: shorten one existing unprotected clip to a specified source
  subwindow (min 2.0 seconds and min 45% original duration), preserving
  protected content. Never expand source PTS.
- `reorder`: relocate one unprotected clip relative to another unprotected
  segment, but only if original source PTS monotonicity stays intact.
  Chronology-breaking reorder will be rejected on real football footage.

`insert`, `replace`, or new source footage remain unsupported in this
*exploration-only* branch until independently video-verified FIRST_LIVE and
narrative fit can be enforced. They remain available through the pre-existing
strict normal revision gates; Phase10-C does not relax them.

This scope intentionally isolates a causal question for engineering:
does deleting/shortening an existing story beat help narrative quality?

### Safety and evidence

- Protected baseline segments must survive with identical order and PTS.
- Ambiguous/doubled IDs, replay metadata, missing video, reverse PTS, invalid
  trim intervals and too-short remaining cuts block exploration.
- No candidate may be labeled G0 PASS from only an LLM/EDL check. Source
  provenance and first-LIVE need independent review.
- Both videos must match their full EDL timeline within the existing
  `timeline_mp4_aligned` tolerance, not merely have an `.mp4` filename.
- X/Y is randomly assigned and copied into a blind folder with no identity
  information; private allocation JSON stays OUTSIDE the folder.
- Output directory is single-use: rerunning against the same allocation
  folder cannot silently mix previous and current blind packets.
- The branch does not call release authorization, update BEST or set
  `IMPROVED`, even when a candidate renders successfully.
- Existing P10-A G0/G1/G2 human evaluation remains the only proposed quality
  evidence protocol. Human single-rater development feedback is not a formal
  3+ rater acceptance result.

## 3. Files touched

- `story_exploratory_cut.py`: standalone safety-screened EDL proposal,
  fullcut render, timeline alignment and blind pack.
- `story_paid_eval.py`: an OPTIONAL extra proposal field on the *existing*
  Planner call, never an additional call.
- `story_e2e_agent.py`: one isolated trial in the existing unified loop;
  separate audit under `02_round_01/phase10_exploratory/`.
- `story_e2e_cli.py`: explicit `--phase10-explore` and offline-only
  `--phase10-explore-fixture`. Both off by default.
- `tests/test_v3a_phase10_exploratory_cut.py`: synthetic tests for
  protection, provenance, unchanged parent, PTS/trim/reorder, blind allocation,
  renderer failure, fullcut alignment, default-disabled flag and one-call
  LLM proposal.

## 4. Server zero-paid validation (Cursor only)

Use a **new independent worktree**, do not overwrite P10-A/B verification
trees. Run from `10.27scasual_chain`:

```bash
python -m compileall -q algo/story_video_agent_v3
PYTHONPATH=algo python -m pytest tests/test_v3a_phase10_*.py -q
PYTHONPATH=algo python -m pytest tests/test_v3a_phase8_*.py -q
```

Also re-run **P10-B typed-link** zero-cost real A/B preview after updating
the new branch: for the frozen `causal:pred_...:atom_fill_...` values, report
`event_ids`, `short_chain_ids`, `evidence_links`,
`reference_provenance`, and unresolved IDs separately. Do not claim
semantic chain truth merely because the pointer was split into typed IDs.

### Optional ONE zero-paid real-render engineering smoke

Only if available disk space and full match video are confirmed:

1. Inspect an actual frozen V3-R Phase5 EDL, select a real **nonprotected**
   `buildup/bridge` media segment. Do not hardcode A/B PTS in source code.
2. Write a local JSON fixture with this exact segment ID. Example format
   (IDs/contents shown only as FORMAT, not genuine observations):
```json
{
  "proposal": {
    "action": "drop",
    "target_segment_id": "<real_non_goal_segment_id>",
    "hypothesis": "Hypothesis only: this beat might repeat the prior setup",
    "expected_effect": "Removing it may tighten narrative pacing",
    "risk": "It might remove needed buildup and reduce story clarity"
  }
}
```
3. Then execute the existing E2E CLI **without paid flags**:
```bash
PYTHONPATH=algo python -m story_video_agent_v3.story_e2e_cli \
  --match-json "$MATCH_JSON" \
  --source-mp4 "$SOURCE_MP4" \
  --phase5-dir "$V3R_PHASE5_DIR" \
  --out-dir "$P10C_OUT" \
  --phase10-explore \
  --phase10-explore-fixture "$P10C_FIXTURE_JSON" \
  --max-rounds 1 \
  --no-smoke-render
```
4. Inspect `$P10C_OUT/02_round_01/phase10_exploratory/`:
   `exploratory_trial.json`, `proposed_candidate_edl.json`,
   `fullcut_timeline_integrity.json`, `candidate_render/story_clean.mp4`,
   `blind_review/X.mp4`, `blind_review/Y.mp4`, and private allocation.
5. The fixture-proposed video is **only a technical dry run**; it does not
   establish that an autonomous Agent discovered a defect or improved quality.
   If the fullcut timeline / replay / source gate fails, report it. Do not
   fabricate a candidate or change input timestamps merely to pass.
6. Keep private X/Y allocation away from the person watching. Send blind
   X/Y paths and source provenance, not a spoilering mapping.
7. Push structured verification report, actual used code SHA, real EDL diffs,
   both video hashes and reproducible commands. Large MP4 stays on server.

Do not launch real LLM/VLM experiments without the user's new explicit cost
authorization. A prior Phase9 budget was specific to Phase9, not transferable.

## 5. Research evaluation plan (NOT DONE)

A real model-driven candidate requires `--phase10-explore` plus the
pre-existing real-API and explicit budget switches; **DO NOT use these for the
zero-paid server verification**.

On held-out matches, freeze baseline V3-R and compare:
- flat-event/issue E2E; +P10-B narrative graph; +P10-C exploration under
  matched observation-frame, call-count and edit-attempt budgets;
- safe candidate production frequency, unique scene removal/trim precision,
  goal/scoreboard integrity, firsthand live validity, chronological accuracy;
- G1 dimension scores and blinded human preference on the **entire video**;
- cases where exploratory edit harms closure, emotion or match comprehensibility.

The "baseline" in a P10-C trial is the current working parent of V3-A.
If baseline deduplication already altered it, DO NOT label it identical to
an untouched V3-R frozen video without comparing source/EDL/MP4 hashes.

### Server verification (`fda622c`)

Worktree: `/data2/lpy1/worktrees/migu-v3a-phase10c-verify`  
Report: `docs/V3A_PHASE10C_SERVER_VERIFY_fda622c.json`  
Artifacts (server): `/tmp/lpy1_phase10c_verify_20261112/`

| Check | Result |
|-------|--------|
| `compileall algo/story_video_agent_v3` | exit 0 |
| `tests/test_v3a_phase10_*.py` | **57 passed / 0 failed / 0 skipped** |
| `tests/test_v3a_phase8_*.py` | **129 passed / 0 failed / 0 skipped** |
| Paid HTTP / VLM | **0** |
| Algo edits by Cursor | none |
| Merge to main | not done |

#### P10-B typed-link recheck (real A / B / B strict_lin)

`causal:pred_*:atom_fill_*` now splits into `short_chain_ids=[pred_*]` and
`event_ids=[atom_fill_*]`, with `typed_reference_provenance.raw_source_ref`
preserving the original pointer. `validated_against_*_inventory=False`; these
remain **unverified predicted-chain references**, not confirmed match-causal
labels. Nodes with `causal:` still inside `event_ids`: **0** on all three
previews.

#### P10-C zero-paid fixture fullcut (A UAE–Oman)

- Non-protected target: `seg_buildup_event_000472` (`buildup_action`).
- CLI: `--phase10-explore` + `--phase10-explore-fixture` + `--max-rounds 1`
  + `--no-smoke-render`; **no** `--enable-real-api`.
- Formal loop: `decision=UNRESOLVED`, `revision_applied=false`, working
  parent EDL unchanged (buildup still present in formal candidate).
- Exploratory: `EXPLORATORY_RENDERED_NOT_VERIFIED`,
  `blind_pair_status=BLIND_PAIR_READY`, `release_authorized=false`,
  `promote_best=false`, `human_quality_improved=false`.
- EDL delta: drop only `seg_buildup_event_000472`; three goal actions
  unchanged.
- Fullcut integrity: baseline/candidate **aligned**; durations
  ~94.9s / ~82.8s vs story 94.5s / 82.5s.
- Frozen Phase5 `candidate_edl.json` / `story_clean.mp4` hashes unchanged.
- Blind pack on server under
  `.../phase10_exploratory/blind_review/{X,Y}.mp4` (large MP4 not committed).

This satisfies **code-level** exit criteria. Method-level human/story gain
remains **UNVERIFIED**; V3-R remains BEST.

### Exit criteria

**Code-level**: all tests and existing Phase8 regression pass, opt-in off
by default, actual frozen V3-R inputs yield a correct candidate-or-blocker
report without paid calls, and original story input remains unchanged.

**Method-level**: a *real model*, with permitted budget, generates an
exploratory candidate grounded in actual evidence; G0 independent checks
pass; fullcut X/Y blind reviews show measurable narrative gain on new matches.
These method-level criteria are **not** met by fixture or source tests.
