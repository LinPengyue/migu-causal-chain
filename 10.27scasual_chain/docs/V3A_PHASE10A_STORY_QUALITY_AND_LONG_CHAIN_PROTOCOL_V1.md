# Phase 10-A | Migu story-narrative deliverable + long-range-chain benchmark protocol v1.0

Status: **PROPOSED / DEVELOPMENT BASELINE** (not an assertion of Migu client sign-off).  
Scope: one ACL-style Benchmark + End-to-End Video Agent paper (~equal emphasis).  
Engineering baseline: V3-R stays BEST; V3-A continues on an isolated branch.  
Implementation: `story_chain_annotation.py`, `story_quality_protocol.py`, `story_quality_cli.py`.  
Cost: zero API calls. Phase9 was UNRESOLVED: no executable issue, no candidate MP4, no human X/Y comparison.

## 1. Product contract: narrative-first story highlight

Input: original football match MP4, event JSON and derived short causal-chain information.
Output: one complete, source-traceable story video with a specific theme, understandable
setup/state changes, decisive climax, and appropriate resolution. The audience should be
able to explain **who faced what tension, how the match state changed, which grounded
events mattered, and what the ending means**.

This is not a key-moment concatenation task or a requirement to maximize exciting
shots. Non-spectacular footage is admissible when it helps the story. Large jumps in
source time are acceptable if they do not create false facts or misleading causal
claims. A fixed five-beat list is *not* a universal mandatory EDL template.

## 2. G0 hard constraints — cannot be compensated by G1 scores

| Code | Requirement | Blocking examples |
|---|---|---|
| `first_live` | Every source segment must be from first live broadcast | replay, slow motion, rebroadcast camera |
| `fact_consistency` | Score, team/event attribution and decisions remain correct | invalid goal shown as valid |
| `key_action_integrity` | Protected goal/action and result evidence remain intelligible | goal reduced to celebration only |
| `temporal_causal_integrity` | Story must not imply false order or causation | unrelated event presented as reason for goal |
| `source_traceability` | Every EDL media segment bound to source MP4 PTS | missing or forged source window |
| `technical_integrity` | Final video/audio/subtitle technically usable | black frames, truncated critical moment |

Value per code: `PASS`, `FAIL`, `UNKNOWN`. A FAIL means rejection.
UNKNOWN means unverified, not PASS. These are independently audited facts, **not
a claim made by the model**. Model-produced source-bound screens may assist an auditor
but cannot silently substitute for human G0 sign-off.

## 3. G1 narrative quality (human judgments; weights sum to 100)

| Dimension key | Weight | Human evaluation anchor |
|---|---:|---|
| `story_completeness` | 25 | Distinct theme, intelligible setup, development and closure appropriate to this story |
| `narrative_coherence` | 25 | Match state, meaningful event relations, and transitions can be followed |
| `material_narrative_value` | 20 | Each selected segment contributes information, emotion or transition; avoid repetition |
| `pacing_emotional_progression` | 15 | Rising tension / relief, no obvious stalls or abrupt collapse of momentum |
| `ending_theme_resolution` | 10 | End settles or intentionally contextualizes the central question |
| `audiovisual_quality` | 5 | Smooth continuity, intelligible sound and unobtrusive titles |

Each dimension is an integer from 1 to 5: 1 severe failure, 2 obvious flaw,
3 basically works but lacks polish, 4 good, 5 excellent. Weighted score = sum(weight * rating/5).
Initial thresholds: >=85 excellent; >=75 acceptable; 60–74.9 revision needed; <60 unacceptable.
At least 3/5 is required separately for completeness and coherence.
Scores/thresholds are **initial protocol choices**, to be calibrated against
independent human rankings; they are not yet validated measurements.

## 4. Templates are optional semantic priors (never six hard-coded editors)

| Story family | Relation to ground | Required semantic commitments |
|---|---|---|
| `comeback` | match-state reversal | credible deficit → response → equalization/lead change → outcome |
| `last_minute_winner` | suspense and resolution | consequential unresolved state → late decisive event → resolution |
| `redemption` | character-state change | evidenced setback → response/contribution → grounded resolution |
| `tactical_duel` | attack/defense contest | observed pattern → shift/reaction → outcome; no invented tactical motive |
| `controversy_turning_point` | decision/state change | incident → official ruling → observable consequence |
| `underdog_triumph` | unfavorable situation | grounded disadvantage → breakthrough → surprising outcome |
| `open` | unconstrained | specify narrative goal and evidence-linked relations |

Templates may overlap. Evaluation checks whether a chosen story fulfills its own
claim, not whether a video mechanically includes five role markers. During
inference, template suggestions are hints only; story planning can be open-ended.

## 5. Benchmark data: event → short causal chain → long narrative chain

The **existing** event annotation and 18 short-range causal-chain categories
remain independent layers. Phase10 adds **human** long-range story annotations,
not a replacement for either layer.

Schema: `migu_long_range_story_chain_v1`; `data_role=BENCHMARK_GOLD`.
One annotation = one theme in one match, with:
- Match/video SHA + split (`train/dev/test`) + story ID/goal + annotator/adjudication state.
- **Nodes** with `node_id`, `node_type` (match state, atomic event,
  short causal chain, narrative state), `narrative_role` (context/setup/
  development/turning point/climax/resolution), description, confidence status,
  `event_ids` / `short_chain_ids` and optional FIRST_LIVE source PTS windows.
- **Edges** with `from_node`, `to_node`, relation
  (`temporal/causal/enables/contrasts/resolves/narrative_support`),
  assertion status, rationale, and optional evidence source/reference.
  **Confirmed causal/enabling edges need direct cited evidence**; temporal
  proximity is not itself proof of causation.
- Story units are flexible in count. At least two nodes and one relation;
  unknown live evidence is flagged for human resolution. Replay is forbidden
  as an eligible video window.

Validator checks syntax, cross-references, duplicate IDs, PTS range, self-edge
and temporal/causal dependency cycles. `valid=true` **does not certify**
human annotation truth or compliance with actual video. Two annotators plus
adjudication are recommended before final benchmark release.

### Preventing evaluation leakage

**STRICT SEPARATION:**
- `BENCHMARK_GOLD` files are stored on the evaluator side. In official dev/test,
  the Agent receives only allowed original MP4/events/short-chain predictions
  (and if desired, template prior). It MUST NOT receive test gold story nodes,
  story edges, gold EDL or gold event corrections.
- Training data and validation protocols must isolate match/video identity,
  with split checks for duplicate/source-related match content.
- Gold may supervise a training method only on allowed training split; never
  feed held-out chain labels back into inference.
- A chain validator is **not** a story generation algorithm; no inference code
  imports this label module.

## 6. G2 blinded full-video relative improvement

Two finished, source-aligned MP4s from the same match/story goal:
- X and Y assigned randomly by an independent evaluation steward.
- Human raters receive X/Y without baseline/candidate identity or machine
  verdicts; scoring and timestamps collected before revealing allocation.
- Evaluate all six dimensions for **both** versions; record preference as
  `X_STRONG/X_SLIGHT/TIE/Y_SLIGHT/Y_STRONG/BOTH_UNACCEPTABLE`.
- Any critical candidate-side reported problem blocks promotion until resolved.
- Allocation is stored **separately** and only used after reviews are sealed.
- >=3 independent raters required for a promotion recommendation; 1–2 raters
  count only as development feedback. With 3 raters at least 2 must prefer
  candidate; higher N requires strict majority.
- Candidate G1 median >=75, completeness/coherence medians >=3, neither of
  these two core dimensions drops >1 point vs baseline, and candidate median
  overall must be >=3 points better for `IMPROVED_HUMAN_EVIDENCE`.
  Majority preference with a smaller nonnegative score change is `PROMISING`,
  **not improved**.

This rule is intentionally conservative. Revisit with human calibration and
inter-rater agreement; a single numerical score is not a universal ground truth.
No model-only `SCREENED_BETTER` or `REVIEW_SUPPORTED` can override it.
`recommend_promotion=true` is human evidence for decision making, **never**
an automatic write to BEST. Existing V3-R release criteria remain unchanged.

## 7. Offline interfaces / reproducibility

From `10.27scasual_chain`:

```bash
PYTHONPATH=algo python -m story_video_agent_v3.story_quality_cli validate-chain \
  --input <human_long_chain.json> --out <validation_report.json>

PYTHONPATH=algo python -m story_video_agent_v3.story_quality_cli blind-pair \
  --reviews <sealed_blind_reviews.json> \
  --allocation <independent_unblinding.json> \
  --gates <independent_g0_audit.json> \
  --out <blind_pair_verdict.json>

python -m compileall -q algo/story_video_agent_v3
PYTHONPATH=algo python -m pytest tests/test_v3a_phase10_*.py -q
PYTHONPATH=algo python -m pytest tests/test_v3a_phase8_*.py -q
```

`blind_reviews.json`: `{"schema":"migu_story_blind_pair_review_v1","pair_id":"...","reviews":[{"rater_id":"...","preference":"Y_STRONG","scores":{"X":{"story_completeness":3,"narrative_coherence":3,"material_narrative_value":3,"pacing_emotional_progression":3,"ending_theme_resolution":3,"audiovisual_quality":3},"Y":{"story_completeness":4,"narrative_coherence":4,"material_narrative_value":4,"pacing_emotional_progression":4,"ending_theme_resolution":4,"audiovisual_quality":4}},"issues":[]}]}`.
Human entries here are *illustrative schema examples*, never actual quality results.

`unblinding.json`: `{"schema":"migu_story_blind_allocation_v1","pair_id":"...","X":"baseline","Y":"candidate"}`.

`g0_audit.json`: `{"gates":{"X":{"first_live":"PASS","fact_consistency":"PASS","key_action_integrity":"PASS","temporal_causal_integrity":"PASS","source_traceability":"PASS","technical_integrity":"PASS"},"Y":{"first_live":"PASS","fact_consistency":"PASS","key_action_integrity":"PASS","temporal_causal_integrity":"PASS","source_traceability":"PASS","technical_integrity":"PASS"}}}`.
These PASS values are **format illustration**, not verified clips.

No paid API, no video render and no Phase9 rerun is performed by these commands.
The final human evaluation should include the rater evidence timestamps and
ratings saved alongside two actual full-MP4 file digests.

## 8. ACL method alignment: next phases (NOT implemented by Phase10-A)

**P10-B: inference-only narrative hypothesis graph**, assembled from allowed
events/short-chain predictions, story plan and newly observed video. Separate
`AGENT_INFERRED` nodes/relations from `BENCHMARK_GOLD`; put the evolving
graph into Planner/Critic feedback **without requiring a fixed template**.

**P10-C: exploratory edits**, based on uncertain story-quality hypotheses.
Permits a bounded, isolated `drop/trim/reorder/insert/replace` candidate
after hard source/live/goal protection; does NOT promote without fullcut
comparison and blinded human judgment. This addresses Phase9's no-candidate
failure *without pretending the original Critic diagnosis was wrong*.

**P10-D: new-match, new-template evidence** and matched-resource ablations:
(1) direct prompt-based clip planning, (2) existing V3-R, (3) V3-A without
long-range narrative graph, (4) +graph, (5) +active video observation,
(6) +reflection/revision. Match video, visual tokens/frames, API spend and
story evaluation budget. No new method superiority claims until measured.

**Research hypothesis** (not yet verified): an evidence-bound long-range
narrative state improves out-of-template coherent story construction over
flat event lists / static prompt-based story planning while preserving
first-live and factual constraints.

## 9. Phase10-A exit status

- Protocol, validator, CLI and unit tests: source committed on isolated branch.
- Execution of compileall/pytest on real server: **DONE** on `161e2b3` (see below).
- Real human benchmark labels: **NOT YET COLLECTED**.
- Agent inference graph integration: **P10-B PENDING**.
- End-to-end rendered story quality improvement: **UNVERIFIED**.

### Server zero-paid regression (`161e2b3`)

Worktree: `/data2/lpy1/worktrees/migu-v3a-phase10a-verify`  
Report JSON: `docs/V3A_PHASE10A_SERVER_VERIFY_161e2b3.json`

| Check | Result |
|-------|--------|
| `compileall algo/story_video_agent_v3` | exit 0 |
| `tests/test_v3a_phase10_*.py` | **22 passed / 0 failed / 0 skipped** |
| `tests/test_v3a_phase8_*.py` | **129 passed / 0 failed / 0 skipped** |
| Paid HTTP / VLM | **0** |
| Algo edits in verify turn | none |
| Merge to main | not done |

Mechanism/protocol regression is green. This does **not** claim P10-A human-benchmark acceptance or story-quality improvement over V3-R.
