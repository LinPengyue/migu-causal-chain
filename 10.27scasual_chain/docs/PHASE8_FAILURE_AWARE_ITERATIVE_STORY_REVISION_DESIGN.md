# Phase 8 — Failure-Aware Iterative Story Revision (V3-A)

Status: implementation-ready design; NOT an implemented or video-validated Phase 8.
Design baseline: story-va-v3a-story-e2e @ 0f8a3affd7f7242d66568b4c02a93d721fced516.
Scope: ONLY the unified V3-A run_story_e2e workflow. Do not reroute to run_self_revise; do not modify V1/V2, prediction chain, or existing artifacts.
Owner of architecture: ChatGPT; Cursor implements on a feature branch, records exact test evidence.

## 0. Scientific / product target

Given an unfamiliar match JSON, raw source MP4, and the existing V3-R-generated initial story, improve the narrative through an actual multi-round Critic → observe/search → Planner → EDL edit → render → Verifier → feedback cycle. Existing V3-R event/causal preparation may be run fresh using only the allowed match JSON + source video (no strip_gold.json or other gold data). This phase does not claim unseen-video generalization or a high-quality finished story; those require subsequent video evaluation.

Core principle: STRICT HARD SAFETY, PERMISSIVE EXPLORATION, CONSERVATIVE DELIVERY.
- Hard constraints: first broadcast LIVE only; NO replay, replay angles or slow motion; source PTS order and EDL/render alignment; protected goal action windows; no invented evidence/timestamps; source video lineage.
- Narrative: BETTER, PROMISING, SAME, WORSE, UNCERTAIN; NOT a rigid one-shot ACCEPT/REJECT.
- Quality comparisons must evaluate the *identified issue* and whole-story side effects, not duration increase or cosmetic score alone.
- Verifier may recommend another observation or edit, but must not fabricate that it saw continuous video when it only saw frames.

## 1. Verified current-code failure points

Read the code rather than changing this spec blindly if upstream moves.

1. story_e2e_agent.py around lines 526, 1064, 1191: loop diagnoses from best_edl/best_mp4; only candidate_accepted updates best, and a non-accepted candidate immediately triggers break. Thus a rejected or inconclusive iteration cannot inform the next round.
2. story_revision_planner.py plan_from_diagnosis signature currently takes diagnosis/observations/offline/fixture_intents/search_results but has no feedback memory; story_paid_eval.py run_llm_revision_planner also receives no feedback context. Modifying one planner without the other is insufficient.
3. story_evidence_search.py run_story_evidence_search accepts already_searched_issue_ids but the main loop does not supply it; repeating the same source PTS under the same intent has no context-sensitive penalty. Do not globally blacklist an entire issue ID.
4. revision_case.py captures issue/intent/candidate/judgment, but final_decision is binary ACCEPT/REJECT and failure_reasons includes verifier_or_pipeline_rejected for all failures. This is an audit record, NOT a valid negative-example taxonomy.
5. story_video_verifier.py verify_story_revision builds candidate_accepted from visual evidence and hard gates; its current output should remain backward-compatible, but must expose an independent advisory quality verdict and safety-evidence status. Do NOT weaken validate_visual_verifier_payload's evidence provenance requirements to make exploration easier.
6. story_e2e_agent.py around 345: paid API preflight refuses max_rounds > 1; a true paid multi-round run needs a separate total-run budgeted protocol, with user approval, not a silent removal of the safety budget cap.
7. story_e2e_agent.py around 1199–1230: final MP4/EDL is copied from best but release gate consumes final_decision/last_verifier/global gates that may reflect a later rejected round, not the selected delivered version. The final decision must be version-specific.
8. story_evidence_search.py _live_credibility treats an absent broadcast_phase as live_ok at reduced confidence. That is NOT proof of first LIVE. Unknown LIVE must never be promoted into the formal final video merely by being outside known replay flags.
9. last_candidate_bundle currently points its baseline_mp4 to the initial MP4 rather than always the compared parent; report exact parent IDs for every candidate.

## 2. Modules and integration

Create SMALL independently testable modules, not a competing pipeline:

A. story_revision_feedback.py (new; pure logic/JSON IO; no API calls)
- normalize_feedback(round_case_bundle, verifier_report, apply_report, candidate metadata) -> feedback entries.
- candidate_identity(match_id, story_template, issue_signature, parent_id, action, source_pts, insert_anchor) -> context key.
- summarize_feedback(memory, current_issue_signatures, max_items=...) -> compact Planner/search input.
- classify failure classes: CONFIRMED_NEGATIVE, UNCERTAIN_OR_UNVERIFIED, POSITIVE, TECHNICAL_FAILURE, HARD_SAFETY_VETO. Narrative REJECT alone is never CONFIRMED_NEGATIVE.
- Maintain per-run memory at out_dir/phase8_feedback_memory.json and each round snapshot.
- Store observed evidence, model/provider origin, sent_frame_ids, observation limitations, and correction status; no fabricated negatives.

B. story_loop_policy.py (new; pure deterministic state transitions)
- evaluate_round_transition(state, candidate, verifier, budget) -> {next_action, working_ref, best_ref, reason_codes, promote, stop_reason}.
- next_action: PROMOTE_BEST, CONTINUE_WORKING, REOBSERVE, REPLAN_FROM_BEST, STOP_NO_ACTION, STOP_BUDGET, STOP_SAFETY.
- The policy must separate: safety PASS/FAIL/UNKNOWN; narrative quality BETTER/PROMISING/SAME/WORSE/UNCERTAIN; evidence SUFFICIENT/PARTIAL/INSUFFICIENT.
- Absence of hard_vetoes is NOT equivalent to safety PASS. Unknown first-LIVE/goal evidence -> keep for targeted observation/human preview, NOT a formal-safe working version.
- PROMISING with safety PASS and nonempty edit may continue as working, never immediately become release-authorized.
- BETTER can PROMOTE_BEST only if video-backed evidence verifies issue effect and no global regression, hard safety PASS, actual EDL mutation/render, and comparison against selected best version; fixture/offline never counts as real quality improvement.
- WORSE: discard, return working to best, record a *reasoned* negative only when evidence is sufficient.
- UNCERTAIN: at most one directed re-observe for a candidate and only if specific evidence can be collected; if still uncertain, explore an alternative or stop. No infinite loops.
- SAME: no promotion; try a distinct evidence-backed edit or stop.
- Keep strict MAX_ROUNDS / total HTTP attempts / estimated cost ceilings. Every transition has a reason code.

C. Wire story_e2e_agent.py
- Initialize story version registry: initial_baseline, best_verified (at start points to baseline but marked BASELINE_UNVERIFIED, not quality IMPROVED), working_candidate, each with version_id, parent_version_id, edl, mp4, safety proof, quality proof, round, and source provenance.
- Each round's diagnosis, observation, evidence search, edit and video comparison use the correct WORKING parent. Separately track current BEST delivery anchor.
- At round end persist versions, feedback, next_action, and budget usage BEFORE any break.
- Never terminate solely because candidate_accepted=False. Stop only for a reasoned next_action / budget / no new evidence / actual KEEP with no actionable hypothesis.
- Prevent same ineffective action on same overlapping PTS + same issue signature + anchor without new evidence; allow reuse if a different scene context or newly verified observation changes the hypothesis.
- Finalize from selected best version and ITS OWN verification/safety snapshot. If no proven improvement exists, deliver baseline fallback with honest release status; never call it IMPROVED.
- Keep schema fields already used by callers (candidate_accepted, revision_status, last_verifier) as legacy views; new phase8_loop_status and version-specific delivery_ref drive the new loop/release. Avoid breaking Phase6/7 audit readers.

D. Wire story_evidence_search.py and BOTH planner paths
- Add feedback_context (optional default None) to plan_from_diagnosis and run_llm_revision_planner; provide bounded, structured records rather than long raw chat logs.
- Add feedback_context to run_story_evidence_search. The current event relevance score is a CANDIDATE PRIOR, not proof of narrative value.
- Rank by supported narrative function, visual confirmation requirement, feedback novelty, baseline event score; prefer alternate semantic evidence after an ineffective bridge. Do not blindly prefer destination proximity or footage duration.
- Use canonical issue_signature = (story template / story role / diagnosis category / adjacent stable segment anchors / missing narrative information). Issue IDs alone can change every iteration.
- Candidate duplicate test uses context + source-PTS overlap (IoU threshold configurable, proposed >=0.6) and action. For UNCERTAIN do not permanently suppress; choose REOBSERVE or alternative with explicit evidence gain. For CONFIRMED_NEGATIVE penalize same-context equivalent, not all future uses of that window.
- Preserve existing rule: a large time jump alone NEVER confirms a narrative defect. Search of unknown first-LIVE is hypothesis generation, not footage approval.

E. Wire story_video_verifier.py and dual_video_vision_verifier.py with backward compatibility
- Preserve existing hard gates + visual-frame provenance.
- Add phase8_verdict:
    safety: PASS | FAIL | UNKNOWN
    quality: BETTER | PROMISING | SAME | WORSE | UNCERTAIN
    evidence: SUFFICIENT | PARTIAL | INSUFFICIENT
    issue_effect: RESOLVED | PARTIAL | UNRESOLVED | UNOBSERVED
    global_regression: YES | NO | UNKNOWN
    focus_issue_id, evidence_refs, observed_changes, unresolved_questions,
    suggested_next_evidence, failure_class, compared_parent_version_id
- Legacy accept_candidate must not be synthesized from PROMISING. In offline fixtures, phase8_verdict can exercise control flow, but MUST have source_kind=FIXTURE and never establish real IMPROVED or real release.
- Verifier must focus on changed splice and its before/after context plus opening/ending/global cuts as feasible; compare *both* videos and state evidence limitations. More frames alone are not evidence of a solved defect.
- A soft quality verdict can be PROMISING with partial evidence, provided safety is independently PASS.

## 3. Exact state contract (phase8_loop_state.json; stable IDs)

{
  "schema": "v3a_phase8_loop_v1",
  "initial_baseline_version_id": "v0",
  "best_verified_version_id": "v0",
  "best_verification_tier": "BASELINE_UNVERIFIED",
  "working_version_id": "v0",
  "versions": {
    "v0": {
      "parent_version_id": null,
      "edl_path": "...",
      "mp4_path": "...",
      "safety": "UNKNOWN",
      "quality": "BASELINE_UNVERIFIED",
      "source": "V3R_BASELINE",
      "semantic_evidence_refs": []
    }
  },
  "feedback_memory_path": "phase8_feedback_memory.json",
  "round_history": [],
  "stop_reason": null,
  "delivery_version_id": null
}

Version IDs MUST uniquely bind EDL+render output (prefer hashes/manifests); parent_id for candidate must match the actual MP4 used by the verifier. Staging paths are not proof of verified quality.

Memory entries (schema v3a_phase8_feedback_v1) minimally:
{
  "round": 1,
  "issue_signature": {
    "template_id": "T01",
    "category": "transition",
    "anchor_segment_ids": ["left", "right"],
    "missing_narrative_info": "pressure_or_causal_transition"
  },
  "intent_id": "intent_1",
  "action": "search_add",
  "source_pts": [3504.14, 3515.83],
  "parent_version_id": "v0",
  "candidate_version_id": "v1",
  "quality": "UNCERTAIN",
  "evidence_status": "INSUFFICIENT",
  "failure_class": "UNCERTAIN_OR_UNVERIFIED",
  "observation": "No independently confirmed narrative benefit",
  "next_search_requirement": "Find visually evident buildup/pressure/turn, not just chronological bridge",
  "source_kind": "REAL_VIDEO_OR_FIXTURE_EXPLICIT",
  "evidence_refs": [],
  "new_evidence_required_for_retry": true
}
This historical example is a design fixture and MUST NOT be auto-classified as confirmed negative. No match-specific heuristic may be encoded in production.

## 4. Transition table

Condition                                  -> action
Safety FAIL / goal damage / replay        -> STOP_SAFETY for candidate; can REPLAN_FROM_BEST if budget and distinct safe alternative; never explore unsafe candidate.
Safety UNKNOWN                            -> REOBSERVE focused safety, else set aside/STOP; cannot promote or use as approved working parent.
Safety PASS + BETTER + valid verified gain -> PROMOTE_BEST, next round from promoted best.
Safety PASS + PROMISING + partial evidence -> CONTINUE_WORKING (bounded depth, max 1–2 before re-evaluate vs best).
Safety PASS + UNCERTAIN + new visual target-> REOBSERVE once, preserve original best.
Safety PASS + UNCERTAIN + no new evidence -> REPLAN_FROM_BEST or STOP_NO_ACTION.
Safety PASS + WORSE + sufficient evidence -> REPLAN_FROM_BEST + confirmed negative with cause.
Safety PASS + SAME                        -> REPLAN_FROM_BEST (different intent) or STOP_NO_ACTION.
No executable revision / no valid source -> STOP_NO_ACTION, record why.
All situations after budget exhaustion    -> STOP_BUDGET, preserve best.

Safety includes true first-LIVE verification; LIVE labels may be unverified signals. An item with no observed replay and missing authoritative LIVE proof is UNKNOWN, not PASS.

## 5. Critical release semantics

- Evaluation vs WORKING parent guides local exploration; promotion must also check full-story candidate vs CURRENT BEST. If a separate BEST comparison cannot be afforded, do not claim PROMOTE_BEST; keep preview/human review.
- A later rejected/uncertain round MUST NOT cause the earlier verified-best version to fail release merely because last_verifier reflects the rejected candidate. Conversely earlier evidence cannot be reused as proof for modified EDL/MP4 unless the relevant evidence window and media hash remain identical.
- Formal release authorization remains stricter than exploration. If the required first-LIVE, goal or full-story quality checks are absent, provide playable human-review preview where safe, but release_authorized=False.
- Distinguish loop success (multi-round feedback reached different action) from delivery success (human/independent confirmed quality gain). Do not claim both from fixtures.
- Preserve allowlist of source inputs; never access strip_gold.json or manual story labels at inference.

## 6. Budget contract

Default zero HTTP remains unchanged.
Phase8 offline fixtures: max_rounds up to 3, no paid calls; test real control flow.
Current frozen paid protocol in story_e2e_agent.py explicitly refuses max_rounds>1. DO NOT merely delete that guard; implement a separate named phase8_paid_multi_round mode (default False), STILL requiring enable_real_api AND i_approve_budget, zero retries, and total-run max_calls/max_cost enforced before AND after each request. Stop gracefully on estimated exhaustion. Disclose estimation uncertainty and never assume cost estimate is vendor hard cap.
No payable multi-round test until explicit new user budget authorization. If remaining budget cannot support a meaningful compare, stop with BUDGET_EXHAUSTED rather than accepting an unevaluated candidate.

## 7. Exact code touch map / change order

Step P8-A: new story_revision_feedback.py and story_loop_policy.py + focused unit tests; no integration, zero external APIs.
Step P8-B: add optional feedback_context to story_evidence_search.py, story_revision_planner.py and story_paid_eval.py. Keep old call signatures valid. Tests prove the second attempt changes candidate/plan and does not ban unverified evidence globally.
Step P8-C: integrate state/versions/transitions into the single main story_e2e_agent.py, replace unconditional rejection break. Keep file-based JSON audit and existing default path backward-compatible.
Step P8-D: expose phase8_verdict in story_video_verifier.py and dual_video_vision_verifier.py. Keep existing stringent release/citation validation, avoid fabricated positive judgments.
Step P8-E: fix final release selection and candidate comparison parent, preserve prior last_candidate_bundle keys for review code. Add version-specific delivery evidence.
Step P8-F: offline regression + Phase7 case replay; only then request consent for one budget-limited real run.

Potential affected test files: discover actual repo tests on server rather than invent names. No new hidden hardcodes for A match, exact PTS, goal counts or T01.

## 8. Required acceptance tests / observables

1. Offline fixture r1 safety PASS + PROMISING => working v1, best v0; r2 BETTER with real-quality simulation => best v2 in TEST STATE, formal IMPROVED remains false for fixture source.
2. Offline fixture r1 UNCERTAIN => re-observe or alternate; not auto NEGATIVE; r2 same evidence cannot loop forever.
3. Offline fixture r1 WORSE + sufficient frame evidence => reasoned negative; next search differs in intent/PTS; negative only contextual, not permanent PTS blacklist.
4. Any replay, slo-mo, unknown first-LIVE, goal removal or PTS invalidity cannot be a promoted or working-approved version.
5. Non-accepted iteration no longer universally breaks; each stop has explicit stop_reason.
6. r1 accepted best v1, r2 rejected v2 => final EDL/MP4 pair selects v1, release checks refer to v1, not r2.
7. Issue IDs changed across rounds but semantic context equivalent => memory still applies.
8. One scene can be retried after NEW video evidence or changed narrative anchor; retries logged.
9. Same test without feedback vs with feedback: candidate repeat rate, distinct decisions, and recovered problem linkage audited. No assertion that quality improved without independent evidence.
10. Provider timeout / truncated response => TECHNICAL_FAILURE or UNCERTAIN, not a negative example.
11. Phase7 historical 3504.14–3515.83 candidate: do not label actual semantic negative from historical REJECT alone; recommend targeted alternative or observation; avoid production match-specific code.
12. Production default zero HTTP; paid multi-round denied absent explicit approval; global hard budget enforced; no retries.
13. V1/V2 isolation; no new gold inputs; baseline V3-R playable fallback; PTS+EDL/MP4 checks all pass in fixture path.
14. Existing tests remain green, including old accept/reject fields and historical audit schemas.

## 9. Offline evidence required from Cursor

Before editing main loop: report branch/HEAD, git status, existing story-related pytest paths, exact mapping of run_story_e2e variables into new state.
After implementation: commit SHA; modified files/diffs; test command and pass/fail counts; zero-HTTP logs; 3-round fixture audit with state.json, feedback_memory.json, per-round plan/search/verifier_report, candidate EDL delta, final version selection and stop reason.
For Phase7 artifacts, read locally at:
  /data2/lpy1/_story_va_outputs/v3/plan2/story_quality_phase7_20261108/
Prefer existing revision_cases.json/verifier_report.json/llm_verifier.json/evidence_search.json, no real VLM rerun.
Provide structured output; no claim of improved real story quality until a legitimate original-vs-candidate video comparison.

## 10. Definition of done

Code runs on unified V3-A main entry, feedback materially changes the next action, candidates have provenance and hard safety, rejected candidates don't dead-end the loop, every run stops for an explicit reason, final version is selected by version-specific evidence, and old behavior stays compatible. Real quality improvement / unseen-match / cross-template generalization are separate later milestones.
