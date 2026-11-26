# R4/R5.2 — original Agent story scope and prompt repair

Frozen adapter results dbc65aa (8 tests, zero HTTP) inspected directly.
Actual A comeback, keeper and turnover generator_request.json each had a
9000-character frozen_story_plan ending before template/narrative_goal
because original _text sorts keys. This contradicts the stronger report
claim that complete template context was visible. The adapter now places
a bounded explicit a_story_template_context first, with goal, subjects,
team mapping, type. The unchanged original serialization/P1 is used.
Full agent_story_context also retains graph-required segments, actual
score transitions from R3 bindings and missing-goal tasks.

## Original algorithm preserved

Original structural_diagnosis still runs. Scope whole-match goal_coverage
issues to exact story score pairs from R3 goal bindings/missing goal
tasks. Keep integrity/replay/redundancy/general transition diagnostics.
Do not demand unrelated goals in a keeper story; do not impose the
comeback-specific development/ending/turn heuristics on other templates.
The known one-anchor partial story need not request a historical V3-R
rebuild. Original detector and search intervals are unchanged; missing
task without matching native issue is explicitly reported, not fabricated.
No new goal localization algorithm.

Native Critic/Planner receive R3 template goal/required nodes. Extend
the existing planner protection contract only for graph-required segments
(including path context) using native _protect_filter and its existing
overturn exception. Original goal IDs retained in original diagnosis;
planner-specific view only. No change to Verifier, shared timeline helper,
P1/P2/P3, inner/outer loop or quality decision/update policy.
The original Goal Recovery, P2/3 and loop have not yet been executed on
these adapted inputs.

For isolation, stage a separate copy of frozen original algo. Only
story_e2e_agent.py and story_paid_eval.py receive exact opt-in input hooks.
Original files in repository unchanged; pinned original source blobs
checked; staged P1/P2/P3/outer/Verifier/timeline modules byte-identical.
AST check requires only run_vlm_story_critic and run_llm_revision_planner
functions to change in shared paid evaluator. This is not a parallel
agent implementation. Do not use cf397a7 experimental loop.

## Cursor — targeted zero-HTTP preflight

    cd research/sportscausal
    python -m unittest -v test_r3_critic_adapter

Expected seven tests; actual results authoritative. No need to rerun
previous eight tests or frozen experiments in this stage.

    python stage_r3_critic_adapter.py \
      --algo-dir ../../11.20sstory_chain/algo \
      --out-dir /tmp/sportscausal_r3_critic_overlay_20261126

Use a fresh unique directory if the path exists. Keep
overlay_manifest.json in report; do not commit full staged source copy.

Native events are the same actual files in dbc65aa REPORT.md:
A/B /data2/lpy1/_story_va_outputs/v3/plan2/full_e2e_{A,B}_strict_lin_20261108_095704/01_to_04_fresh_v3r/01_enrich/events_enriched.json.

For A keeper, A turnover, A comeback, B equalization, run exactly one
targeted diagnostic/serialization preflight each:

    python r3_critic_preflight.py \
      --story-dir artifacts/v3r_general_r3_preflight/B/equalization__1 \
      --evidence artifacts/stage1_2_evidence_preflight_20261125/B_osasuna_celta/keeper_rescue/evidence.json \
      --events "$B_EVENTS" \
      --algo-dir /tmp/sportscausal_r3_critic_overlay_20261126/algo \
      --allow-dev \
      --out-dir artifacts/v3r_critic_adapter_preflight/B_equalization

A use original A evidence, events, R3 story directories. No model,
decode, render, historical V3-R or full Story Agent run. Original actual
P1 request first interval per story re-prepared only to check fixed
template prefix; B has no interval, validate actual original _text.
Native structural Critic called with no video path; file-missing
diagnostics expected in this preflight and retained. Do not report
those as visual defects.

Audit:
- all explicit template context survives original 9000-char cap;
- keeper no unrelated goal_coverage issue, required segments 6;
- turnover only matching score transition if detected, all 5 required
  segments including relation-path context protected;
- B equalization only target transitions 0:0->0:1 and 0:1->1:1,
  missing observe:5 retained; actual native search target and exact
  interval or report no matching issue. Do not force expected answer.
- A comeback original relevant goal diagnostics and heuristic behavior
  retained; compare no new story content.
- preserve original goal IDs vs planner union; fixture drop protects
  graph-required material. No visual/quality claim.
- source hook compilation, pinned hashes and function AST evidence
  from actual staged tree.

Return unittest.txt, overlay_manifest.json, four diagnostic bundles,
first actual fixed P1 requests, REPORT.md and input hashes. If source
hash or hook mismatch, report the actual blocker; do not silently patch
delivery code.

## Pending
Real initial rendering, original run_story_e2e invocation on adapted
seed, full observation task routing for relation/phase and missing
goals, actual video trial, cross-template and loop-round quality.
The original P1 operates between existing semantic anchors; tail and
missing-anchor support is not claimed. Do not expand or change Verifier
or double-loop semantics in future work. Final human quality comparison.
