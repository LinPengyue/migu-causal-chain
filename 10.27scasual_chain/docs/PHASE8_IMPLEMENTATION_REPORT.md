# Phase 8 — Implementation report (for ChatGPT review)

Branch: `story-va-v3a-phase8-loop-impl`  
Baseline: `0f8a3af`  
Design followed: `PHASE8_FAILURE_AWARE_ITERATIVE_STORY_REVISION_DESIGN.md` + `PHASE8_CURSOR_EXECUTION_HANDOFF.md`

## Commits

| SHA | Content |
|---|---|
| `6d966e7` | Design docs + pre-implementation inspection |
| `3d13808` | P8-A `story_revision_feedback.py` + `story_loop_policy.py` + unit tests |
| `a77d2bb` | P8-B feedback-aware search + dual planner wiring |
| *(HEAD after this report)* | P8-C/D/E main-loop version registry, `phase8_verdict`, delivery version selection, offline 3-round audit |

## Spec § mapping

1. Verifier quality advisory → `build_phase8_verdict` / `phase8_verdict` on `verify_story_revision` (legacy `candidate_accepted` retained; PROMISING does not synthesize accept).
2. Feedback memory → `story_revision_feedback.py` (`CONFIRMED_NEGATIVE` / `UNCERTAIN_OR_UNVERIFIED` / `POSITIVE` / `TECHNICAL_FAILURE` / `HARD_SAFETY_VETO`).
3. Planner/search next-round inputs → optional `feedback_context` on search + `plan_from_diagnosis` + `run_llm_revision_planner`.
4. Dual-track versions → `phase8_loop_state.json` via `story_loop_policy` integrated in `run_story_e2e`.
5. Targeted verify focus → parent version id recorded; Phase7 historical REJECT not auto-negative.
6. Offline tests → see below (zero HTTP).
7. Delivery → `delivery_version_ref.json`; release checks version-specific; fixtures never `release_authorized`.

## Offline tests (exact)

```bash
cd 10.27scasual_chain
PYTHONPATH=algo python -u -m pytest \
  tests/test_v3a_phase8_feedback_policy.py \
  tests/test_v3a_phase8_planner_search_feedback.py \
  tests/test_v3a_phase8_loop_offline.py \
  tests/test_v3a_phase7_semantic_evidence.py \
  tests/test_v3a_story_e2e.py -q --tb=short -k 'not cross_match'
# 41 passed, 1 deselected
```

## Three-round offline loop decisions

Artifact: `/data2/lpy1/_story_va_outputs/v3/plan2/story_quality_phase8_20261108_offline_loop/phase8_offline_loop_audit.json`

| Round | Parent | Candidate | Quality / action | Transition | Working | Best |
|---|---|---|---|---|---|---|
| 1 | v0 | v1 | PROMISING `search_add` 3504.14–3515.83 | CONTINUE_WORKING | v1 | v0 |
| 2 | v1 | v2 | alternate PTS 4200–4210 (3504 overlap suppressed by feedback) | STOP_NO_ACTION (UNCERTAIN, no new visual target) | v0 | v0 |
| 3 | — | v3 | budget | STOP_BUDGET | v0 | v0 |

Proof flags:
- `structural_loop_pass=true`
- `video_semantic_quality_verified=false`
- `unseen_match_generalization_verified=false`
- `release_authorized=false`
- `zero_http=true`
- Two distinct source candidates: `cand_old@3504-3515`, `cand_new@4200-4210`

## Phase7 REJECT handling

Historical `verifier_or_pipeline_rejected` + `semantic NOT_EVALUATED` → `TECHNICAL_FAILURE` / `UNCERTAIN_OR_UNVERIFIED`, **not** `CONFIRMED_NEGATIVE`. Same PTS retry suppressed until new evidence; PTS not permanently banned.

## Known unresolved / risks

- Full ffmpeg unified E2E integration tests still hang/slow in this environment; not claimed green.
- Paid multi-round requires explicit `phase8_paid_multi_round=True` + budget approval; **not executed**.
- Real video quality gain / unseen-match generalization are **later** milestones.
- Estimated future paid budget (do not run): still ≤$0.10 / ≤5 calls unless a new authorized protocol is provided.

## Non-claims

This implementation proves feedback changes the next decision. It does **not** claim a better finished story MP4.
