# Phase 10-B: inference-only narrative graph wired into the Story E2E loop

Status: **IMPLEMENTED IN ISOLATED BRANCH; ZERO-PAID SERVER REGRESSION GREEN ON `fc7bed5`**. This is an
engineering method prototype, *not* a demonstrated ACL contribution or a
verified improvement in story videos.

Branch: `story-va-v3a-phase10-narrative-quality`. No V1/V2/V3-R modifications.
No additional model call is made by this change; Graph preview is zero HTTP.
A paid E2E run still requires the already existing explicit budget gates.

## 1. Research motivation

P10-A defined the external HUMAN Benchmark truth and G0/G1/G2 human quality
rubric. P10-B turns part of the Agent's internal state from a flat issue list
into an **evidence-bound, version-scoped narrative hypothesis graph**. The graph
is built from the actual working EDL, exact-match story-plan references, and
source provenance (never from Benchmark test gold). This is an *inference state*
and does not pretend to be annotated truth.

The research question remains open: does such a graph help the Agent decide
which video evidence to inspect and which edit to try, under matched budgets?
Only held-out comparison and ablation can answer it.

## 2. Implementation

`story_inferred_narrative_graph.py`:

- One graph per working EDL and source-video SHA, with `data_role=AGENT_INFERRED`.
  Each included EDL segment becomes a story node with role/slot **hints**,
  story-time interval and original source PTS interval, if present.
- Exact event IDs and short-causal-chain IDs from the EDL and matching
  story-plan `segment_id` are attached as typed `evidence_links`.
  These are existing input **references**, not verified short-chain causation.
- Consecutive story nodes get `editorial_adjacency` edges. These record only
  the chosen EDL order; `is_match_causal_claim=false` ALWAYS.
- Changes in narrative slot identify **observation hypotheses**, not defects.
  Maximum two targeted windows per round prioritize meaningful transitions
  (development→turn/climax and climax→ending), not the largest match-time gap.
- Only normalized semantic VLM evidence, with at least two IDs bound to frames
  actually sent and recognized by the existing Phase6 evidence validator, can
  annotate an edge as `MODEL_REVIEWED_NOT_HUMAN_VERIFIED`.
  This is still a sampled-frame model observation, not human-quality ground truth.
- Across rounds, a review can persist **only if source SHA, exact EDL hash,
  story-plan hash and edge ID all match**. Any edit resets review state for
  the changed cut. Previously reviewed transitions do not get re-prioritized
  without a new version.

`story_e2e_agent.py`:

1. Build graph from current working EDL/plan before layered observation.
2. Write `02_round_XX/agent_narrative_graph_pre_observe.json` and
   `agent_graph_observation_targets.json`.
3. Add bounded graph review windows to the existing `observe_layers` input
   (production path only; existing fixture paths preserved).
4. Pass inference-only graph to the existing VLM Critic context.
5. After normalized VLM evidence and semantic merge, update graph metadata;
   write `agent_narrative_graph.json` and embed in diagnosis.
6. Pass compact graph hints to rule-based and LLM Planners. Never insert graph
   hypotheses into the list of confirmed story defects.

`story_paid_eval.py`: supplies bounded graph hints to the EXISTING VLM Critic
and LLM Planner prompts; no new VLM API stage, no new HTTP call.
`story_revision_planner.py`: echoes graph provenance and summary in plan
audit, `authorizes_revision=false` always. Existing confirm/replay/PTS/
narrative-fit/goal/approval rules are unchanged.

## 3. Strict boundaries

- **No gold leakage**: `migu_long_range_story_chain_v1` and
  `data_role=BENCHMARK_GOLD` are refused even when nested inside candidate
  inference input. The current graph references only the existing input EDL
  and story-plan fields; it does not import the human benchmark validator.
- **No invented causality**: EDL ordering ≠ causal relation. A claim about an
  attack causing a goal cannot be confirmed from role labels or adjacency.
- **No autonomous mutation**: graph-only hypotheses cannot create executable
  edits. Phase10-C will introduce isolated exploratory edits separately
  without changing the formal production acceptance gate.
- **No false evaluation**: P10-A G0/G1/G2 human criteria and independent
  blind evaluation remain outside Agent. No auto-promotion of BEST.
- **No match-specific rules**: no UAE/Oman, B/C sample PTS or templates baked
  into method.
- **No implicit paid use**: graph is pure Python; any real model use still
  requires explicit V3-A CLI authorization and price ceilings.

## 4. Zero-cost server verification

From an independent worktree of
`story-va-v3a-phase10-narrative-quality`, root `10.27scasual_chain`:

```bash
python -m compileall -q algo/story_video_agent_v3
PYTHONPATH=algo python -m pytest tests/test_v3a_phase10_*.py -q
PYTHONPATH=algo python -m pytest tests/test_v3a_phase8_*.py -q
```

Check a REAL frozen V3-R Phase5 instance (substitute actual paths):

```bash
PYTHONPATH=algo python -m story_video_agent_v3.story_inferred_graph_cli \
  --edl "$V3R_PHASE5_DIR/candidate_edl.json" \
  --story-plan "$V3R_PHASE5_DIR/story_plan.json" \
  --out "$PHASE10B_OUT/agent_narrative_graph.json"
```

This preview does **not** read video frames. Evaluate the actual graph output:
source PTS, role-hint coverage, event/short-chain reference-link counts,
protected-goal role hints, transition review target count and any empty IDs.
If event/short-chain links are empty on real V3-R EDL, report the exact
schema gap. Do not hallucinate or silently backfill from benchmark gold.

Report independently for A and B if available. Verify the `story_plan` may
be reused only when its input structure is valid; otherwise file a zero-cost
schema defect for correction.

The isolated smoke experiment can additionally run existing E2E in OFFLINE
mode on a known Phase5/video, but is **not** required for source-level
acceptance and does not prove improved story quality.

### Server verification (`fc7bed5`)

Worktree: `/data2/lpy1/worktrees/migu-v3a-phase10b-verify`  
Report: `docs/V3A_PHASE10B_SERVER_VERIFY_fc7bed5.json`  
Graph previews (server): `/tmp/lpy1_phase10b_graph_preview_20261112/`

| Check | Result |
|-------|--------|
| `compileall algo/story_video_agent_v3` | exit 0 |
| `tests/test_v3a_phase10_*.py` | **36 passed / 0 failed / 0 skipped** |
| `tests/test_v3a_phase8_*.py` | **129 passed / 0 failed / 0 skipped** |
| Paid HTTP / VLM | **0** |
| Merge to main | not done |

#### Real V3-R Phase5 graph preview (no Benchmark gold)

| Match | nodes | edges | event/short-chain reference_links (summary) | observation_targets | data_role |
|-------|------:|------:|---------------------------------------------:|--------------------:|-----------|
| A UAE–Oman frozen Phase5 | 9 | 8 | 4 | 2 | `AGENT_INFERRED` |
| B Osasuna–Celta closed_loop Phase5 | 13 | 12 | 5 | 2 | `AGENT_INFERRED` |
| B strict_lin Phase5 | 12 | 11 | 4 | 2 | `AGENT_INFERRED` |

**Observed real-structure facts (do not backfill with gold):**

1. Graphs build from EDL+story_plan alone; `data_role=AGENT_INFERRED`; limitations explicitly deny gold use.
2. Action/goal segments carry references when the frozen EDL already has them (plain `event_*` and/or `causal:pred_*:atom_fill_*`). Title / deficit / scoreboard / wrap cards often have **empty** `event_ids` — this matches the V3-R EDL, not a silent gold omission.
3. Node field `short_chain_ids` was **empty on all three previews**. Causal-chain style IDs currently appear inside `event_ids` / `evidence_links` (`event:causal:...`) rather than a populated `short_chain_ids` list. Treat this as a **schema/data-shape gap on real Phase5**, not as proof of short-chain reasoning quality.
4. Edges are currently `editorial_adjacency` (`EDL_ORDER_ONLY`). Narrative-transition *hypotheses* exist on some adjacencies; none are video-reviewed (`NOT_REVIEWED` / `UNOBSERVED_ROLE_HYPOTHESIS`).
5. `observation_targets` prioritize up to two role/state transitions with `story_defect_confirmed=false` (advisory only).

This verifies offline graph construction on real frozen assets. It does **not** prove better observation/planning than a flat event list, nor any story-quality gain over V3-R.

## 5. Next evidence gates

- **P10-B source acceptance (this turn)**: compileall + regressions green; offline graph preview on actual frozen V3-R assets reviewed above.
- **P10-B method evidence (still open)**: whether graph-guided observation/planning beats flat lists under matched budgets.
- **P10-C**: introduce isolated exploratory candidate, compare full rendered
  MP4s and blind human preference using P10-A protocol. Existing V3-R remains
  BEST without actual human-supported improvement.
- **P10-D**: held-out matches, new story families and budget-matched ablations
  contrasting flat event/issue lists, graph hints, graph-guided observation,
  and graph-guided reflection. No scientific novelty/quality claims yet.

Current factual status: Phase9 produced NO_CANDIDATE_PAIR; P10-A protocol accepted after 22/22 + 129/129; P10-B on `fc7bed5` has **36/36 phase10 + 129/129 phase8** green and real A/B graph previews recorded. Story-quality / ACL method gain remains **UNVERIFIED**.
