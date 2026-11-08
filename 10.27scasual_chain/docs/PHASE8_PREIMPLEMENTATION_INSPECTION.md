# Phase 8 — Pre-implementation inspection (for ChatGPT)

Date: 2026-11-08. Baseline code: `story-va-v3a-story-e2e` @ `0f8a3affd7f7242d66568b4c02a93d721fced516`.
Design docs pulled from `origin/story-va-v3a-phase8-loop-design` (`c0626cb`, `5d04457`).
Implementation branch (this report): `story-va-v3a-phase8-loop-impl`.

## 1. Git / environment

| Item | Value |
|---|---|
| Current branch at inspection start | `story-va-v3a-story-e2e` (clean) |
| HEAD | `0f8a3affd7f7242d66568b4c02a93d721fced516` |
| Uncommitted changes | none (Phase 8 WIP was previously reverted) |
| Worktree | `/data2/lpy1/worktrees/migu-v3a-handoff-A` |
| Code root | `10.27scasual_chain/` |

### V3-A pytest (actual)

Commands (zero HTTP; `PYTHONPATH=algo`):

```bash
cd 10.27scasual_chain
PYTHONPATH=algo python -u -m pytest tests/test_v3a_phase7_semantic_evidence.py -q --tb=line
# 12 passed

PYTHONPATH=algo python -u -m pytest tests/test_v3a_phase6_semantic.py -q --tb=line
# 12 passed

PYTHONPATH=algo python -u -m pytest tests/test_v3a_story_search_revise.py -q --tb=line
# 10 passed, 1 skipped

PYTHONPATH=algo python -u -m pytest tests/test_v3a_story_e2e.py -q --tb=line -k 'not cross_match'
# 8 passed, 1 deselected

PYTHONPATH=algo python -u -m pytest tests/test_v3a_unified_main_chain.py -q --tb=line -k 'not Integration and not fixture_accept and not verifier_reject'
# 5 passed, 3 deselected
```

Notes:
- `TestUnifiedE2EIntegration::*` and `TestCrossMatchOfflineDryRun` appear to hang / run very long under this environment (ffmpeg tiny-mp4 / large asset paths). Deselected for this baseline report; not treated as green.
- No paid API invoked for this inspection.

Relevant entrypoints confirmed present:
- main loop: `algo/story_video_agent_v3/story_e2e_agent.py::run_story_e2e`
- evidence search: `story_evidence_search.py::run_story_evidence_search` (has `already_searched_issue_ids`, **no** `feedback_context`)
- local planner: `story_revision_planner.py::plan_from_diagnosis` (no feedback)
- paid planner: `story_paid_eval.py::run_llm_revision_planner` (no feedback)
- dual vision verifier: `dual_video_vision_verifier.py` / `story_video_verifier.py::verify_story_revision`
- final delivery: `compute_release_authorization` + `99_final/delivery_status.json`

## 2. Phase 7 artifact structures (real files)

Root: `/data2/lpy1/_story_va_outputs/v3/plan2/story_quality_phase7_20261108/`
Round path used: `A_bridge_e2e/02_round_01/`

### revision_plan.json
- `decision`: `REVISE`
- `rationale`: `confirmed_defect_plus_verified_search_candidates_bound_to_source_pts`
- 1 intent: `search_add` of LIVE window `3504.14–3515.83` (`cand_event_000417_3504`) after `seg_setup_deficit`

### apply_report.json / edl_pts_safety.json
- Insert applied (`applied_evidence_bound`); PTS monotonic `ok: true`
- Candidate rendered; goals intact

### revision_cases.json (round)
- `final_decision`: `REJECT`
- `failure_reasons`: `["verifier_or_pipeline_rejected"]`  ← opaque umbrella, not a quality taxonomy
- `verifier_judgment.quality_judgment`: **null** (placeholder note only)
- Candidate PTS recorded; this is an audit case, **not** a confirmed negative sample

### verifier_report.json (round, as consumed by main loop)
- `candidate_accepted`: **false**
- `hard_vetoes`: `[]`
- `warnings`: `["refuse_accept_without_semantic_verification"]`
- `vision_backed`: true (sparse dual frames were sent)
- `dual_verifier.semantic_verification_status`: **`NOT_EVALUATED`**
- `dual_verifier_full.error`: `vision_citations_insufficient_or_text_only`
- `evidence_basis`: `insufficient_visual_evidence`
- `quality_delta`: `NOT_EVALUATED`
- **This is technical / evidence-insufficient REJECT, not confirmed WORSE.**

### llm_verifier.json (partial recovery)
- Parse truncated (`OUTPUT_TRUNCATED` / `PARSE_FAILED`)
- Recovered judgments used generic slots (`rev_opening` / `rev_turn`), not the bridge intent id
- One recovered item labeled `WORSE` on story-time shift — **not** validated as formal quality verdict (accept still false; semantic NOT_EVALUATED)

### Root summary `revision_cases.json` (post-audit enrichment)
- `failure_reasons`: `before_after_dual_vision_did_not_resolve_confirmed_bridge_defect`, `ok_for_semantic_accept=false`
- Retried audit judgment: `quality_judgment=SAME`, `original_issue_resolved=false`, `semantic_verification_status=FAILED`
- Still **must not** be auto-ingested as `CONFIRMED_NEGATIVE` under Phase 8 rules

### Delivery
- `99_final/delivery_status.json`: `HUMAN_REVIEW_REQUIRED`, `release_authorized=false`
- `release_gate.json` reasons: `candidate_not_accepted`, `semantic_verification_not_passed`

## 3. Spec ↔ code conflicts (must resolve without inventing a second pipeline)

| Spec requirement | Current code | Conflict |
|---|---|---|
| Multi-round feedback after non-accept | `story_e2e_agent.py` ~1190–1193: `if not vfix.get("candidate_accepted"): break` | Rejected/uncertain round **cannot** inform next round |
| Diagnose/search/edit from WORKING parent | Loop uses `best_edl`/`best_mp4` only; best updates only on `candidate_accepted` | No dual-track working/best registry |
| Feedback memory + planner/search context | `plan_from_diagnosis` / `run_llm_revision_planner` / `run_story_evidence_search` lack `feedback_context` | Search has unused `already_searched_issue_ids`; main loop does not pass it |
| Quality labels BETTER/PROMISING/SAME/WORSE/UNCERTAIN independent of accept | Loop/delivery driven by `candidate_accepted` boolean | PROMISING cannot continue; UNCERTAIN treated like hard stop |
| `failure_class` taxonomy | `revision_case.failure_reasons` often `verifier_or_pipeline_rejected` | Opaque REJECT ≠ CONFIRMED_NEGATIVE |
| Final release from **selected version’s** evidence | Final MP4/EDL from `best_*`, but `compute_release_authorization` uses `final_decision` + `last_verifier` of last round | Later reject can poison release semantics for an earlier best (Spec §1.7 / §5) |
| Paid multi-round | Preflight refuses `max_rounds>1` when paid | Spec: keep guard; add explicit `phase8_paid_multi_round` mode later — **do not delete** |
| Hard safety / first-LIVE | Still required for formal release | Must keep fail-closed; exploration may keep UNKNOWN safety separate from PASS |

### Mapping of current loop vars → planned Phase 8 state

| Today | Phase 8 (`phase8_loop_state.json`) |
|---|---|
| initial `best_edl`/`best_mp4` after V3-R | `versions[v0]` = `initial_baseline`; `best_verification_tier=BASELINE_UNVERIFIED` |
| `best_edl`/`best_mp4` (accepted only) | `best_verified_version_id` |
| *(missing)* | `working_version_id` + working EDL/MP4 for next Critic/search |
| `candidate_accepted` break | `evaluate_round_transition` → `CONTINUE_WORKING` / `REPLAN_FROM_BEST` / `STOP_*` |
| `last_verifier` for release | version-specific verification snapshot on `delivery_version_id` |
| `revision_cases.json` | input to `normalize_feedback` → `phase8_feedback_memory.json` |

## 4. Implementation plan adherence

Will follow `PHASE8_CURSOR_EXECUTION_HANDOFF.md` commit order exactly:
1. `story_revision_feedback.py` + `story_loop_policy.py` + unit tests
2. feedback-aware search + both planners
3. main-loop version registry / transitions (no accept-break)
4. `phase8_verdict` + delivery selected-version semantics
5. compatibility fixes only if needed

Constraints honored: no V1/V2 edits; no match-specific hardcodes; no gold; no automatic paid multi-round.
