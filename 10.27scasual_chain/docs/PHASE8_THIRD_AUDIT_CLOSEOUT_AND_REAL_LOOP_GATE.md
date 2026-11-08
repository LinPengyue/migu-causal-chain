# Phase 8 — Third Audit: Offline Mechanism Accepted; Real-Loop Gate Pending

Baseline: story-va-v3a-phase8-loop-impl @ 90752af4d7e1c2b3f67b171536a398ef73a5e4cb.
Review scope: actual GitHub code + committed proof artifacts. Reviewer has not run pytest on the remote server or viewed real MP4s.
Cursor reports 70 passed, 1 deselected; cross_match and unmocked unified E2E NOT RUN.

## Accepted within the declared offline scope

1. Per-window FIRST_LIVE=NOT_VERIFIED no longer becomes PASS solely from SEARCH_EVENT_CHAIN_LIVE_VERIFIED; proof first_live_negative.json.
2. Actual run_story_evidence_search + plan_from_diagnosis choose A with no memory, and B after A is filtered under the same static EDL/candidate set; independent autonomous_ab_selection.json. No scripted candidates in this isolated test.
3. run_story_e2e two-round wiring: feedback reaches next planning round; candidate EDL changes; fixture provenance keeps release_authorized=false and best=v0. No fabricated third round.
4. Dual-video prompt requests soft_quality; validator preserves soft PROMISING without synthesizing a strict accept; fixtures retain provenance.
5. New digest checks protect delivery against changed EDL/MP4 bytes. These are untested with real media at release.

## Remaining P0 gate: real first-LIVE certification still has no trusted production producer

story_e2e_agent.py initializes first_live_prior_ledger with an empty windows list (lines ~551–555) and only passes it into build_first_live_window_ledger around ~1244. There is no population/load of verified source-window records, nor an authenticated targeted-video verification result that can promote new footage from NOT_VERIFIED.

The ledger builder permits raw targeted_visual_verified + claimed FIRST_LIVE_VERIFIED; this is a boolean claim rather than independently checked linked video/audit evidence. The main-loop apply path currently emits first_live_status=NOT_VERIFIED for ordinary search_add footage.

Therefore the real (nonfixture) new-footage PROMISING path would typically be safety UNKNOWN, prohibiting CONTINUE_WORKING. This is safe but means authentic multi-round story improvement remains functionally blocked.

**Required minimal completion:**
- Implement/read authoritative first-live evidence records for exactly (source_sha256, PTS_start, PTS_end) based on source MP4 inspection; verify audit/evidence file references, frame or clip hashes, outcome and provenance, rather than trusting raw status booleans.
- Bind all *newly introduced* source windows by EDL diff, not only apply_report rows. If EDL adds a window absent from apply_report, safety UNKNOWN instead of interpreting has_new_footage=false.
- For multiple new windows, all must be independently verified; carry forward evidence from verified unchanged ancestor segments, without reusing proof for changed source/video digest.
- Do not weaken replay/slowmo/goal/PTS or formal release gates.

## P0 secondary: actual main-loop feedback ablation still confounded by EDL occupancy

Second-audit proof:
- Isolated A/B control with same input EDL: A selected without feedback; A filtered, B selected with feedback. PASS.
- Full run_story_e2e proof: first round inserts A into working EDL; next round searches working EDL where A is already *occupied*. r2 evidence_search.json reports feedback_filtered_candidates=[], kept B. Thus A->B in this full run is not independently attributable to feedback: occupancy alone already rules out A.

**Required test:** same round-2 baseline EDL, same event set and same diagnosis, with and without round-1 feedback; measure direct candidate choice and revision plan. Strongest is a main-loop paired ablation after first-round failed/uncertain attempt *rolled back to the same best EDL*, such that A would still be available absent feedback. Assert with-memory A suppressed and B chosen, no-memory A remains top. Keep zero HTTP. Treat the isolated A/B test as supported evidence but not full-loop causal gain.

## P1: new-evidence token still embeds round/version, and IDs are not hashes

story_e2e_agent.py around ~1441–1448 sets observation_id to candidate_version_id + round_idx and passes sent_frame_ids as frame_hashes. Those are identifiers, not actual frame-byte hashes. make_observation_evidence_token flags obs: as observation grade when observation_id exists. The current search avoids using candidate_id as a new token (good), but future candidate evidence_token that differs from stored token may bypass suppression without new observations.

**Required:** use stable source-video SHA, source window, actual frame-byte hashes, observation scope/manifest digest. Do not create a fresh evidence identity from round/version counters. A retry should require explicit validated new observation evidence, not merely unequal string tokens.

## P1: hard safety ledger self-assertion and payload integrity

build_first_live_window_ledger accepts targeted_visual_verified in raw new_windows or prior_ledger. Require verification of its supporting visual evidence record and hash/window binding before authorizing PASS. A raw boolean alone is not proof.
compute_independent_hard_safety should require an actual candidate MP4+valid matching render when used for a real revision (candidate_mp4=None must not silently PASS). Prevent source window omissions from being treated as "no new footage".
The introduced first-LIVE evidence should distinguish known LIVE from *first* LIVE across broadcast timeline; isolated stills without temporal context may be insufficient.

## Next step after zero-HTTP fixes

Run ONE small real-video dry run with zero paid calls to produce source-frame manifests, replay/first-LIVE evidence and EDL MP4 alignment, then solicit user approval for a tightly capped actual VLM multi-round quality experiment. User's previous requests did not authorize new paid calls. Any REAL_VLM quality claims must be compared against best and require video evidence, not fixtures.

## Result labels

- phase8_offline_feedback_search: PASS (static fixtures)
- phase8_unified_entrypoint_wiring: PASS (two-round fixture run)
- phase8_first_live_negative_gate: PASS
- phase8_real_first_live_positive_proof: NOT IMPLEMENTED
- phase8_main_loop_feedback_increment_ablation: PARTIAL
- phase8_real_video_quality_gain: UNVERIFIED
- phase8_unseen_match_generalization: UNVERIFIED

This review is meant to close the offline design iteration, not launch an endless new scope. Address trusted first-LIVE evidence and the causal ablation, then proceed to controlled actual-video observation; do not start Phase 9.
