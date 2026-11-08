# Phase 8 — Second Code Audit: remaining blockers before real video loop

Reviewed: story-va-v3a-phase8-loop-impl @ 034d4549050bc08e3c87929fcf8226acad677ebc. Static inspection of actual GitHub code and committed test artifacts. NOT an independent server pytest run, and NOT real MP4 viewing.

Status: CONDITIONAL PASS for run_story_e2e fixture wiring; NOT READY for authentic safety-approved feedback-driven video-quality loop. Keep zero HTTP, no paid API, no V1/V2 changes.

## Verified improvements

1. Real run_story_e2e entry was invoked in tests/test_v3a_phase8_run_story_e2e_loop.py. Two round directories exist: round1 working=v1; round2 parent=v1; STOP_NO_ACTION prevents round3.
2. Tests verify fixture provenance stays FIXTURE; final best=v0 and release=false. Good.
3. Current-round outcome precedes future-round budget stop in story_loop_policy.py. Delivery logic selects a version-specific snapshot rather than blindly using last verifier.
4. Phase7 NOT_EVALUATED is not mislabeled as confirmed WORSE.

User/Cursor report: 60 passed, 1 deselected; reviewer has inspected source but has not reproduced that pytest run. Cross-match and unmocked unified E2E remain NOT RUN.

## P0-A — False first-LIVE certification; MUST fix before any real video test

Contradictory source code:
- self_revise_agent.py around 2652–2675 creates new search-bound footage with evidence_status=SEARCH_EVENT_CHAIN_LIVE_VERIFIED AND first_live_status=NOT_VERIFIED.
- story_e2e_agent.py around 1173–1184 promotes that event-chain evidence to hard_safety_extra.first_live_status=FIRST_LIVE_VERIFIED using ANY applied row.
- story_video_verifier.py compute_independent_hard_safety around 407–438 regards the resulting token as proof for all newly used footage.
- The remote VLM validated payload may also supply first_live_status through quality_overlay, and that untrusted statement feeds hard_safety_extra.

Event-chain probable LIVE does NOT prove first broadcast LIVE as opposed to replay/slo-mo. Multiple newly added windows require independent proof EACH. Avoid the ANY shortcut.

Required: a separate per-source-window first-LIVE evidence ledger keyed by source-video digest + precise PTS window; only verified matching prior records or targeted visual verification may establish FIRST_LIVE_VERIFIED. VLM visual observations may contribute evidence but not self-authorize safety. Missing proof => UNKNOWN, no working approval. Any nonempty hard_vetoes => FAIL, not just replay/goal subsets. Missing video/render mismatch or source provenance cannot be PASS. Tests: event-chain status with NOT_VERIFIED => UNKNOWN; 2 added windows one unverified => UNKNOWN; any veto => FAIL; all independently verified windows => PASS. Fixtures may simulate PASS only with fixture provenance, never certify real.

## P0-B — Real VLM prompt still does not elicit PROMISING; soft loop supported mainly by fixtures

dual_video_vision_verifier.py around 467–484 asks for quality_delta_vs_baseline + legacy accept_candidate, but not explicit phase8 soft quality, partial issue effect, targeted next observation, or uncertainty. story_video_verifier.py build_phase8_verdict around 494–499 looks for phase8_quality / quality_judgment or legacy quality_delta. Real PROMISING therefore requires unsolicited compliant model output.

Required: extend existing compact dual-video prompt/JSON parser to request SOFT verdict BETTER/PROMISING/SAME/WORSE/UNCERTAIN, issue effect, global regression, short observed changes, cited sent frame IDs and optional concrete reobserve target. Keep strict legacy formal accept citation gate unchanged. A REAL_VLM PROMISING may CONTINUE_WORKING even if legacy accepted=false ONLY when independent hard safety PASS and candidate render aligned. Add zero-HTTP mock-provider integration test traversing real code channel, not only build_phase8_verdict isolated test.

## P0-C — Main-loop alternate candidate in proof is scripted, not autonomously feedback-selected

tests/test_v3a_phase8_run_story_e2e_loop.py around 164–212 patches run_story_evidence_search with a fake function that returns the second candidate when call_n>1 or feedback n_records>0. The test also passes explicit different source windows in phase8_round_fixtures for both rounds. Real Planner and real search did NOT choose candidate B over candidate A. The committed round2 evidence_search.json even says feedback_filtered_candidates=[].

This DOES prove feedback plumbing and version parent linkage. It does NOT prove production feedback actually alters candidate ranking/selection.

Required zero-HTTP test: candidates A and B are available in BOTH rounds in an event/diagnosis fixture; do NOT mock run_story_evidence_search and do NOT inject round2 revision_intents. Mock expensive render/vision only. First round chooses A; normalized feedback changes real search ranking/filter; second round chooses B. Control without feedback selects A. Assert exact filtered candidates and chosen bound_source_window.

## P0-D — Fake new-evidence token bypasses feedback suppression in real run

story_e2e_agent.py around 1358/1368 saves evidence_token = candidate_version_id:round_idx, e.g. v1:1; story_evidence_search.py passes candidate.evidence_token OR candidate_id as new_evidence_token; story_revision_feedback.py should_penalize_candidate around 425–431 treats unequal prior/new token as NEW independent evidence, skipping suppression.

Ordinary candidate_id and round count differ even when no new video observation exists. This can silently allow the identical PTS/action to repeat. The current integration mock hides it.

Required: evidence identity bound to source SHA + PTS + observed frame hashes / source observation ID, NOT round counter or candidate ID. Only recorded actual new verified observation unlocks retry; else same-context same-PTS retry is blocked/deprioritized based on CONFIRMED_NEGATIVE vs UNCERTAIN. Add regression using feedback returned by the actual normalize_feedback function and a repeated candidate: without new evidence it must NOT slip past the filter.

## P1-E — REOBSERVE currently writes metadata, not new evidence

story_e2e_agent.py around 1482–1498 only writes reobserve_target.json and directed_reobserve/target.json. pending_reobserve is never subsequently consumed to extract target frames or evaluate the SAME candidate before the next generic planning round.

Required: target-specific source/candidate ordered frame extraction with source/video hash and story/source PTS manifest, and rerun verifier only when actual new evidence exists; otherwise mark NEEDS_VLM_BUDGET or STOP_UNVERIFIED. Do not label mere JSON writing re-observation. Bound re-observation to one per candidate.

## P1-F — Version snapshot lacks immutable render/provenance digest and best comparison

story_e2e_agent.py version_snapshots has EDL/MP4 paths and verdict, not immutable digests proving bytes still correspond at release. compared_against_best is a parent-id equality or fixture override, not direct evidence of full-story best comparison. For a candidate built on working v1 when best=v0, no explicit VLM comparison to best is implemented; the conservative policy currently prevents promotion (good), but can also permanently strand improved working variants.

Required: source SHA, canonical EDL SHA, MP4 SHA and per-version verification evidence manifest; verify hashes at release. When parent != best, perform budget-controlled candidate vs best observation before promotion, or retain as review-pending without quality claims.

## Work order and handoff

1. Fix P0-A safety inference first, no paid calls.
2. Fix P0-D and P0-C together; prove feedback changes actual production search/planner selection, not just an injected mock.
3. Fix P0-B and add real-provider-shaped, zero-HTTP integration test for PROMISING without legacy ACCEPT.
4. Implement actual P1-E targeted observation and P1-F immutable best proof; keep zero HTTP.
5. Report implementation SHA, exact tests, a source-window first-LIVE negative case, actual feedback-filtered candidate list, and run_story_e2e output with no scripted second-round alternate.

Acceptance boundary: structural wiring PASS (fixture). Authentic feedback-directed search, real soft VLM exploration, first-LIVE safety, real video quality improvement, and unseen-match generalization UNVERIFIED. Do not run paid experiment or Phase9.
