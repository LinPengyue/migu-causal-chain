# V3-R-General R2b/R2c — combined anchor discovery

Frozen R2a.4 artifact baseline: 0bba8b799e39d35305663d2497683c2602690950.
No previous file or delivery code is changed. No historical experiment rerun.

## Operators and output

- State transition: reuse score_state_patterns.match_score_states; bind each
  matched score step (including additional goals in one sign run) to the
  R2a.4 score-outcome episode and observation tasks. State subject is not
  score beneficiary. A missing goal keeps a search interval and task ID,
  not a carrier clip. Collect attack/rescue episodes certainly between
  action intervals conditional on current localization, and separate
  post-last-anchor context. No claim that the last confirmed score is an
  independently verified final score. A lead signature is not proof of
  successful defensive preservation.
- Relation path: walk the original directed predicted-member graph within
  a common chain, preserve contiguous available PARTIAL member paths
  without bridging missing members; no subtype whitelist. Independently
  annotated start actor and score beneficiary align; role conflict or
  contrary observed attack/control/restart blocks the path. Keep actual
  intermediate event IDs, disjoint union windows, typed local relations
  and original chain provenance. Group alternative paths sharing start
  and end instead of duplicate candidates. A path is a hypothesis, not
  confirmed possession or causal evidence. Score never supplies execution.
- Phase change: detect two consecutive observed threat runs with at least
  two distinct episodes on either side; score-only nodes cannot contribute.
  Opposite-side overlapping windows split ambiguous runs. Preserve observed
  intervals and switch search region. Not a statistical dominance or
  possession measure.
- r2bc_patterns.py dispatches explicit template configs, not classification.
  Default preflight suite contains six configurations: comeback,
  equalization, lead_preservation, set_piece_breakthrough, turnover_to_goal,
  threat_phase_change. Use --template-id to select one or --template to
  supply a different declarative JSON. R2a repeat/alternate outputs remain
  separate frozen artifacts for R3. This suite does not cover all 17 types.
- New observation tasks: relation_path_verification and
  phase_switch_verification. Keep all 18 historical tasks from the two
  real matches; only append candidate-scoped tasks. No observer runs.

The relation span/gap defaults (45/15 seconds) and phase minimum (2 episodes)
are provisional configurable preflight settings, not fitted or validated
thresholds. No per-match tuning. No arbitrary narrative score or ranking.
State context and candidate paths are not EDL; media windows are atom-bound,
not enclosing search intervals.

## Cursor protocol: once per A/B, zero paid HTTP

From independent research worktree at current code commit:

    cd research/sportscausal
    python -m unittest -v test_r2bc_patterns

Expected 20 new tests; record actual output, failures and source SHA.

    python r2bc_patterns.py \
      --evidence artifacts/stage1_2_evidence_preflight_20261125/A_uae_oman/keeper_rescue/evidence.json \
      --r2a4-dir artifacts/v3r_general_r2a4_preflight/A \
      --score-path artifacts/v3r_general_r2a3_preflight/inputs_prepared/A_score_path_from_t01.json \
      --allow-dev --out-dir artifacts/v3r_general_r2bc_preflight/A

For B substitute B_osasuna_celta and the corresponding B paths. Reuse the
frozen actual R2a.4 graph/bundle, not old full R2a.3 or fresh normalization.
Report source mismatch if any. Never use reference story labels or manual
candidate edits. No video render, HTTP, repeated historical experiments.

## Audit and return

- State: confirm A/B comeback subject, score indices and goal/context
  membership; show every node's score beneficiary separately. For B
  equalization 1:1, confirm missing action and linked observation task
  rather than invented clip. Report interval and post-anchor context,
  including whether it is redundant or weak. Do not claim last score
  equals independent final whistle.
- Path: enumerate all distinct candidate endpoint pairs and member paths
  with raw event notes/types/role evidence, exact chain IDs, FULL/PARTIAL,
  intermediate actions, temporal span, and candidate task IDs. A valid
  zero candidate result is acceptable; analyze whether absence comes
  from missing members, competing actions, time bounds or role evidence.
  Do not loosen parameters or rerun for a positive count. No causal or
  quality claims without independent verification.
- Phase: show ordered run member IDs, actor, count, actual window
  boundaries, switch interval and ambiguity diagnostics. A sparse
  switch is not established dominance. Score-only goals excluded.
- Confirm original R2a.4 artifacts are unchanged and its observation
  task IDs/content are preserved in the new pack.
- Return template JSON results, anchor_pack.json, observation_tasks.json,
  summary.json, unittest.txt, REPORT.md, exact input hashes and commands
  under artifacts/v3r_general_r2bc_preflight/.
- Keep quality_verified, first_live_verified and release_authorized false.

After targeted validation, advance to R3 common Story Graph and draft EDL
materialization. Do not repeatedly tune these operators on A/B.
