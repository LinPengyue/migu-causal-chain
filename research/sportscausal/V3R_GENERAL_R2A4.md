# V3-R-General R2a.4 — role-safe score and attack representation

Baseline: cbc11f17eac3b8f3473fdb69ee9a7de6a30d963d.
R2a.3 code and all prior experiment artifacts remain unchanged. This is a
new entry point; do not use the historical R2a.3 shot-goal actor inference
for new story planning.

## Changes

- goal_role_semantics.py: score transition localizes a unique compatible
  annotated goal; assigns score_beneficiary only. Own-goal annotations are
  not excluded. Independently role-bound notes may establish goal_executor;
  an explicitly named own-goal executor is distinct from the beneficiary.
  Note/attribute execution conflicts stay visible; a beneficiary/executor
  disagreement is not itself proof of own goal. No score-derived shooter.
- r2a4_relation_graph.py: preserve R2a.3 non-goal attack/save relations.
  Reuse the saved without_score graph when supplied and source-matched.
  A contaminated cache is refused, and a fresh safe graph can be built
  from saved R1.1 semantics instead. Local Shot->Goal membership is
  retained as outcome_context_edges, not as an attack causal edge.
  No role propagation from a score or from a goal to an empty Shot.
  Preserve uncertain shot/save hypotheses and create actionable observation
  tasks for role attribution and missing goal localization.
- r2a4_patterns.py: strict attacking_threat and goalkeeper_rescue projections
  remain independent of score-only outcomes. scoring_outcomes.json keeps
  all localized goals with score_beneficiary and neutral chain context.
  An additional alternating_threats_score_context.json is a distinct
  mixed-role narrative hypothesis, NOT a strict alternating-threat
  prediction. Its score-only nodes carry actor_role=score_beneficiary.
  Pure scoreboard sequences do not become mixed attack stories. Avoid
  duplicate goal/attack anchors when their event membership overlaps.
- test_r2a4_roles.py: 19 targeted tests. The legacy test for score-derived
  shooter attribution tests the historical R2a.3 behavior only; it is NOT
  an acceptance test for R2a.4. No previous source file was changed.

## Cursor: targeted zero-cost validation

Use the original full Stage 1.2 evidence, saved R2a.2 normalized semantics,
verified score_path inputs and saved R2a.3 without_score relation graph.
Do not run R2a.3 three-arm experiment again. Run R2a.4 only once per match.

    cd research/sportscausal
    python -m unittest -v test_r2a4_roles
    python r2a4_patterns.py --evidence A_EVIDENCE_JSON \
      --semantics artifacts/v3r_general_r2a2_preflight/A/normalized_semantics.json \
      --score-path artifacts/v3r_general_r2a3_preflight/inputs_prepared/A_score_path_from_t01.json \
      --base-graph artifacts/v3r_general_r2a3_preflight/A/without_score/relation_graph.json \
      --allow-dev --out-dir artifacts/v3r_general_r2a4_preflight/A

Use identical arguments for B with its original evidence and B paths. Record
source SHA, exact commands, input hashes and test stdout. Preserve prior
artifacts. If the cache is incompatible, report why before running fresh
R2a.4; never substitute the score-contaminated full graph.

## Audit

- A opening 0:1: preserve the score beneficiary and localized Goal,
  retain short-chain Shot context, do not assign shooter or goal executor
  from the beneficiary. The known own-goal fact is an audit fact only,
  not an input or event-id rule.
- All 7 prior score-derived shooter inferences must be absent; verify
  actual per-event predicates, not only the summary count.
- A/B score-bound goal counts, goal windows and confirmation times must
  remain traceable to the input. Goal action windows are NOT scoreboard
  carrier times. B 1:1 unlocalized score step must become an observation
  task with search interval, not a fabricated clip.
- Preserve A398-399-400, A640-641, B586-587, existing dual views,
  A420-421 conflict and B625 player conflict. Compare saved cbc11f1
  outputs directly. Check unresolved Shot/Save tasks and evidence.
- Compare strict alternate and separately named mixed score-context
  candidate, with per-node actor_role and membership. Do not count the
  mixed candidate as strict attacking-threat recognition or quality gain.
  Verify no duplicate goal counted as a second independent attack.
- Return all JSON files, unittest log and REPORT.md under
  artifacts/v3r_general_r2a4_preflight/. No paid HTTP, no rendering,
  no reference labels, no per-match fixes or manual candidate changes.

## Limitations

The score path cannot establish actual goal execution, attack or first-live
video identity. Independent explicit annotation roles are claims, not video
proof. An untyped goal may be an ordinary goal or an own goal. Neutral context
may be causally unrelated, so it is not a verified relation. Mixed role
alternation is not equivalent to the existing attack template. Observation
tasks are structured requests only: no video model or repair loop is executed.
This patch intentionally leaves R2b/R2c, R3 and R4/R5 for subsequent stages.
