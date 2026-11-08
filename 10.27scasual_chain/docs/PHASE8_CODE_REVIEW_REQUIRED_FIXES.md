# Phase 8 — Code Review / Required Corrections (2026-11-08)

Review basis: implementation branch story-va-v3a-phase8-loop-impl @ b0cb39c2b86858641db74da4d43d072daa47cb02.
Reviewer inspected actual GitHub code and three Phase8 test source files. This is a static code audit, NOT a report of local pytest execution or video playback.
Do not merge into story-va-v3a-story-e2e or launch paid multi-round tests before the blockers below are resolved.

## Summary

The offline policy/feedback primitives were implemented, and the old unconditional
"not candidate_accepted -> break" has been replaced by a separate policy transition.
Phase7 NOT_EVALUATED is correctly NOT assumed confirmed WORSE. However the current
implementation is **NOT ready for an authentic Phase8 multi-round video experiment**.

### P0-1: Real VLM verdict is incorrectly branded FIXTURE

Locations:
- story_e2e_agent.py ~1104–1126: after a REAL run_llm_verifier returns,
  fixture_v = llm_v["validated"]; it is later filled with
  source_kind = fixture_v.get("source_kind") or ("FIXTURE" if fixture_v else "REAL").
- story_video_verifier.py build_phase8_verdict ~355–356 uses
  source_kind = fx.get("source_kind") or ("FIXTURE" if fixture else "REAL").
- story_loop_policy.py ~320–330 refuses to PROMOTE_BEST for source_kind FIXTURE.

Consequence: A real remote VLM output may be marked FIXTURE, so a genuinely improved
candidate could never be promoted. Conversely synthetic fixture input could
forgibly supply source_kind="REAL" without trusted provenance, creating a
potential false improvement authorization.

Required design:
- Use separate "real_provider_verdict" and "test_fixture" channels (names may vary).
- Source origin MUST be determined by internal execution path/provider audit, not a
  content field returned by the model or a caller-controlled fixture.
- fixture/phase8_round_fixtures always provenance=FIXTURE regardless of their payload.
- real VLM normalized output provenance=REAL_VLM only after recorded successful
  provider call and frame bindings.
- Do not confuse the argument name "fixture" in legacy API with actual provenance.

Tests: real-provider-like mocked response is marked REAL_VLM (without any HTTP);
fixture claiming source_kind REAL stays FIXTURE; neither fixture nor partial
model output can falsely assert formal IMPROVED.

### P0-2: "Soft exploration" is gated by the old strict candidate_accepted boolean

Locations:
- story_video_verifier.py build_phase8_verdict ~358–370 sets safety=PASS for
  real nonfixture ONLY when vision_backed AND semantic_status == PASSED AND
  accept_candidate=True; otherwise safety=UNKNOWN.
- story_loop_policy.py ~217–233 does not permit CONTINUE_WORKING for safety UNKNOWN.

Consequence: A real PROMISING or partially-evidenced (but hard-safe) candidate
cannot continue as a working version. The only observed PROMISING -> working
path comes from fixture injecting phase8_safety=PASS.

Required design:
- Independent machine-verifiable hard-safety verdict:
  PASS only if valid EDL/render, goal protection, source-PTS consistency,
  credible *first* LIVE proof for all newly used footage, and required source lineage.
  UNKNOWN if some proof is missing, FAIL for confirmed violation. No hard safety
  condition may rely on narrative accept_candidate.
- Independent SOFT story-quality / observation verdict from VLM; it may be
  PROMISING with partial evidence when safety independently PASS.
- This must not lower formal release/evidence requirements or treat absent
  replay flags as first-LIVE proof.
- Keep soft-only candidates in a bounded exploration track, not auto-delivery.

Tests: real-provenance PROMISING + independent safety PASS + candidate rendered
-> CONTINUE_WORKING despite legacy candidate_accepted=False; UNKNOWN first-LIVE
-> cannot become approved working; intentional replay -> FAIL.

### P0-3: Budget checked before the just-completed round can be evaluated

Location: story_loop_policy.py evaluate_round_transition ~182–206:
"if rounds_done >= max_rounds: STOP_BUDGET" occurs BEFORE quality/safety.
Main loop calls this after the candidate has already been rendered/verified
(story_e2e_agent.py ~1289–1313, rounds_done=round_idx).

Consequence: A genuinely BETTER third-round result with max_rounds=3 is
discarded as STOP_BUDGET, never PROMOTE_BEST. Likewise max_rounds=1 can never
promote an improvement.

Required design:
- Evaluate current finished candidate first (including safety and improvement).
- Round budget limits FUTURE iterations, not recognition of completed current results.
- Expose both current_round_outcome and continue_allowed/stop_reason or
  apply candidate transition then finalize with STOP_BUDGET while retaining the
  updated best. Do not mask current hard veto with "budget stop."
- Also apply remaining API-call budget without retrospectively discarding a
  completed valid result; when API budget prevents verification, mark it UNKNOWN.

Tests: max_rounds=1 and BETTER + complete proof => best=v1, stop after round;
max_rounds=3 and BETTER on r3 => best=v3, delivery=v3;
r3 replay/PTS violation => veto recorded, best unchanged.

### P0-4: "Three-round E2E" evidence is a synthetic policy-unit sequence, not a single running agent loop

Location: tests/test_v3a_phase8_loop_offline.py ~38–210:
- Manually calls evaluate_round_transition and apply_transition;
- Manually builds two candidate dicts with fixed PTS and calls
  _apply_feedback_to_candidates;
- r2 invokes STOP_NO_ACTION which would cause run_story_e2e to break;
- r3 then calls evaluate_round_transition directly on already-stopped state.
There is NO run_story_e2e call in this test.

Consequence: "r1 -> r2 -> r3" in phase8_offline_loop_audit.json does NOT
establish three consecutive main-loop iterations. It also does not prove
Critic and Planner re-ran with feedback, that the next EDL was rendered, or
that the real Verifier returned a useful round-2 outcome.

Required design:
- Rename the existing artifact accurately: "offline policy transition scenario".
  Do not call it an E2E 3-round run or count r3 as occurring after STOP_NO_ACTION.
- Add an actual run_story_e2e integration test with dependency-injected/mocked
  rendering, diagnostic, source-event search and Verifier (zero HTTP), but keep
  the REAL code path + file audit + parent/version bookkeeping.
- Show from actual generated 02_round_01, 02_round_02, 02_round_03 dirs
  which decisions changed, why, and whether each round executed.
- Add a second test where STOP_NO_ACTION on r2 results in exactly 2 rounds.
- Use temporary output directories; do NOT make unit tests require writing
  /data2/lpy1. Keep production server artifact scripts separate.

### P0-5: Version-specific release checks still consume LAST round's mutable state

Location: story_e2e_agent.py ~1480–1538:
- calls compute_release_authorization with global "gates" that refer to last
  iteration, including semantic_verification_passed and candidate_rendered;
- passes audit["last_diagnosis_issues"] from last round rather than delivered version;
- release_goals_intact=True is assigned for nonbaseline selected version
  regardless of its actual version proof;
- "release_accepted" derived from legacy round_rec["accepted"] or last_v
  even though policy promotion decisions are independent of that flag.

Consequence: best=v1 may be incorrectly blocked by rejected r2; and provenance
for which version passed specific goal/first-LIVE checks can be inaccurate.

Required design:
- Cache each candidate's complete verification_snapshot, goal_safety, semantic
  evidence, source/video/EDL hashes, and diagnosis applicable to that version.
- Derive formal release gate only from selected delivery_version_id snapshot,
  never from last_* fields or mutable global gates.
- For multi-round v2 based on working v1 when best=v0, PROMOTE_BEST requires
  direct comparison to current best v0, not merely v2 vs v1.
- If best comparison absent, remain PROMISING/PENDING and do not claim VERIFIED_BETTER.
- Rejected late candidate must neither revoke nor grant release of selected best.

Tests: r1 verified v1, r2 rejected v2 => final v1 EDL+MP4, release inputs
selected from v1; v2 has no influence. r2 better than working v1 but not
compared against best v0 => cannot promote. Hash mismatch => no release.

### P1-6: REOBSERVE is a transition label, not a directed observation action

Locations:
- story_video_verifier.py ~444–445 always provides default suggested_next_evidence
  "reobserve_edit_locus_continuous_context".
- story_e2e_agent.py ~1311 checks bool(suggested_next_evidence), so the
  has_new_visual_target flag is almost always True.
- On REOBSERVE, story_e2e_agent.py ~1348 keeps working pointers and starts
  another generic Critic/search/planner cycle; there is no explicit target
  observation of the pending candidate.

Required:
- Suggested target must be specific: actual source/compiled time windows,
  issue ID, question, and missing proof type; no nonempty generic fallback.
- REOBSERVE actually dispatches targeted extraction of consecutive context
  and/or vision call for the SAME pending candidate and writes results.
- If cannot observe or budget exhausted => UNCERTAIN, try a distinct alternative
  or stop; at most one directed reobserve per candidate.
- Tests assert new observation files/frame IDs or explicit stop; no identical
  generic re-run charged as evidence gain.

### P1-7: PROMISING can become "working" when no render exists

Location: story_loop_policy.py ~295–304 checks edl_changed and safety PASS,
but not rendered or actual candidate MP4 presence/alignment. Main loop
~1341 only updates working_edl/working_mp4 if candidate_mp4 truthy; policy
may update state. With fixtures, safety PASS can be asserted despite
render failure.

Required: require rendered=True, actual file decodable, correct EDL/MP4
alignment and source lineage BEFORE CONTINUE_WORKING; otherwise
TECHNICAL_FAILURE, revert working to known-good parent/best.
Test missing render => never working v1; loop state and actual working EDL
must agree.

### P1-8: Feedback suppression is only category+PTS, not contextual signature

Locations:
- story_revision_feedback.py should_penalize_candidate ~378–433
  checks action, IoU, same category but NOT matching anchor IDs,
  missing narrative info, or template (despite docstring).
- story_evidence_search.py builds candidate signature from search metadata
  only; no compatible normalized issue signature.
- "new_evidence_token" path is not persistently written to ordinary
  normalize_feedback entries, so new evidence may not un-suppress retries.

Required: use stable template/role/anchor/missing-info signature as well as
source PTS IoU; weigh confirmed negative strongly, uncertain weakly;
persist observation evidence-token/version; new material evidence can unlock
reconsideration. No match-specific hardcode or global PTS ban.
Test same PTS reused for genuinely different story placement is allowed;
same context + no new proof is suppressed; newly validated proof permits retry.

## Required sequencing for Cursor

1. Fix P0-1 and P0-2 and add real-path mocked tests, without paid calls.
2. Fix P0-3 and P0-5 (budget + deliverable proof provenance).
3. Replace false three-round integration claim (P0-4) with actual run_story_e2e
   zero-HTTP test; correct README/report artifacts.
4. Fix REOBSERVE, render, and feedback identity issues (P1-6 to P1-8).
5. Run offline regression including phase6, phase7, cross-match if feasible;
   slow/hanging suites must be marked NOT RUN/PARTIAL, not PASS.
6. Send exact commit SHA, test commands, per-round actual main-run audit,
   delivery version snapshot and hard-gate evidence for second audit.
7. Do NOT run paid VLM, do NOT rename fixture data to REAL, do NOT assume
   41 passed means semantic quality improved.

## Acceptance boundary

Current status: offline policy/unit scaffold implemented; partial static review
passes for factual Phase7 NOT_EVALUATED handling, zero paid claims and V1/V2
isolation. The authentic multi-round revision loop and formal end-to-end
quality improvement remain UNVERIFIED. No Phase 9 yet.
