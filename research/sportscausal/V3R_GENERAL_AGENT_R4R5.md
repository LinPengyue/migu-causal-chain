# R4/R5 — graph-conditioned video revision loop, first integration

Frozen R3 artifact baseline: 539c421390b2f1b133080da5dcc431fa226acdb9.
Historical backend source inspected at delivery commit 93804fb
(11.20sstory_chain/algo). Do not modify delivery or run its historical
story algorithm again. This is a research-only adapter/loop, not a
second production delivery entry.

## What is implemented

- General Story Graph + R3 initial EDL and observation task adapter.
  For comeback use recovered native story_plan edl's four action
  candidates (78s for the frozen A/B examples), not the three
  scoreboard confirmation windows. Historical include_in_cut=false
  stays intact in the original file; working preview rows explicitly
  override it for inspection only. No inherited first-live/render status.
- Actual video Critic on a complete compressed preview, graph-conditioned
  issue discovery. Story-First generates at most five hypotheses per
  chosen interval using the full chronological atom inventory; no Causal-4
  scalar/ranker in Planner, no template classification.
- Planner chooses a source observation target; includes all supplied
  observation tasks, current seed segments and Story-First alternatives.
  Broad missing-goal intervals are tiled with overlap and visible event
  summaries; a tile is a search region, not automatically a clip edit.
- Observer uses frozen V3-A native_broadcast_observer._source_context_video.
  Real video is continuous original source, transcoded silent 5fps/360p;
  _request from story_first_p3 carries native video inputs. Source file
  SHA256, clip hash and absolute bounded source window retained.
- Planner proposes one add/replace/trim/drop/keep action based on current
  observation. New/changed footage uses the bounded observed window;
  annotated replay overlap is excluded. Keep prior anchor protection.
- Render actual complete baseline and candidate reasoning previews using
  the same native clip extractor and ffmpeg concat. Verifier uses both
  native videos and compares actual narrative value/defect resolution,
  not duration or EDL delta. Rejected/uncertain trials leave the current
  edit unchanged; rationale enters subsequent Critic/Planner context.
- On accepted missing-goal revision bind the graph node only to an
  actually active new segment and matching task/beneficiary observation.
  Keep refined graph, EDL, observations, per-round evidence and feedback.
- Reuse story_paid_eval.build_capped_provider, provider_usage and
  story_first_search.story_first_calls_left. Reserve enough calls for
  observation, trial planning and comparison. No real calls by default.

## Limitations — do not describe as completed visual validation

- No real source decode, model or visual evaluation has been executed
  by the research author. All model behavior and cross-template quality
  are unvalidated. Test fixtures simulate contracts only.
- This is a new graph-conditioned orchestration layer over existing
  video/API primitives, not a direct reuse of the old goal-specific
  Planner/Critic or the full old run_story_e2e orchestration.
- The 5fps silent preview is for visual reasoning, not final rendering.
  Native-video input support and combined 12MB payload limit must be
  checked; over-cap returns error rather than pretending full coverage.
- Local live classification and no annotated replay overlap do not prove
  FIRST_LIVE. All outputs remain preview-only with release_authorized
  and first_live_verified false. Independent first-occurrence evidence,
  source boundary accuracy and human evaluation remain to be integrated.
- Model-proposed absolute action times are bounded to the observed clip
  but are not frame-accurate localization evidence. Broad search may
  require multiple observations; no claim of exhaustive goal recovery.
- Current loop uses one revision per round. No arbitrary duration/quality
  reward; complete-story no-op is allowed. No full 17-template coverage.
- The frozen R3 seed/context pool is not itself a quality guarantee.
  For equalization, do not offer arbitrary late-match tail intervals.
  Other story boundaries and semantic relevance remain model decisions.

## Cursor Stage 1: zero-HTTP integration only

    cd research/sportscausal
    python -m unittest -v test_general_story_agent

Expected 14 tests; report actual results. These include fixture-only
simulated acceptance/rejection and no-op, never actual visual success.

For each of these four real R3 story directories:
A/comeback__1, A/turnover_to_goal__1, A/keeper_rescue__2,
B/equalization__1 (optionally A/threat_phase_change__1), run once:

    python general_story_agent.py \
      --story-dir artifacts/v3r_general_r3_preflight/B/equalization__1 \
      --evidence artifacts/stage1_2_evidence_preflight_20261125/B_osasuna_celta/keeper_rescue/evidence.json \
      --events ACTUAL_ORIGINAL_STAGE1_2_ENRICHED_EVENTS_JSON \
      --allow-dev --out-dir artifacts/v3r_general_agent_prepare/B_equalization

Use the exact Stage1.2 source native enriched event document including
excluded replay rows, not compact planner_request or benchmark reference.
The code checks all evidence atom IDs/times. Do not reconstruct or rerun
historical algorithms; report unavailable original inputs as blocker.
For A substitute original A paths. This mode performs zero HTTP and no
video decode. Check seed rows, missing goal tile coverage (B
[2480.82,2675.82]), original tasks and context, actual source replay
intervals, and no unsupported first-live/release. A comeback working
preview should have four action candidate rows / 78s, original legacy
89s story_plan remains unchanged. A turnover retains 5/23.542s.

Return actual test log, prepared_agent_input.json, report.json, input
hashes, commands, and REPORT.md under artifacts/v3r_general_agent_prepare/.
No repeated R1–R3 experiments, no paid API, no reference labels.

## Later Stage 2: real source video (only after explicit budget approval)

Example CLI flags added to the same command using a NEW output folder:

    --source ACTUAL_ORIGINAL_MP4 --source-manifest VERIFIED_SOURCE_MANIFEST_JSON
    --legacy-algo-dir ACTUAL_FROZEN_11.20sstory_chain/algo
    --enable-real-api --approve-budget --max-calls 6 --max-cost-usd 0.05 --max-rounds 1

Source manifest: exact evidence video_id plus independently computed sha256
of the actual original video and source provenance. Existing backend
configuration must provide real native-video-capable planner/vision
endpoints, no credentials in reports. Cost cap is estimate not invoice
guarantee. Six calls can complete one round with Story-First; multiple
rounds need a separately approved budget. Do not execute Stage 2 as part
of this zero-HTTP validation. Preserve each trial even if rejected.
First prioritize B natural missing action or a cross-template path case;
do not repeat old equalizer/first-live experiments without new purpose.

## Acceptance criteria for later real agent tests

- A controlled deletion: find actual absent goal, bound source footage,
  verify original issue and no new defect, accept only evidence-supported
  repair. B natural missing: recover or report actual failed search.
  C intact: do not insert unrelated content.
- Cross-template: evaluate actual relation-path continuity and goalkeeper
  narrative enhancement (not just matching metadata or increasing duration).
- At least one real accepted/rejected comparison with video evidence and
  failure-aware subsequent decision before claiming effective reflection.
- Human checks actual story quality; no claim of final delivery or
  FIRST_LIVE solely from this loop.
