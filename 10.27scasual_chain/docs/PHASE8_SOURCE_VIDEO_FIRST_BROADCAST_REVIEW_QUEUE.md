# Phase 8 next action: original-broadcast verification, zero HTTP

State at handoff: branch story-va-v3a-phase8-loop-impl @ bf71d91338496c0c0418a2c78021cf378240910c; user/Cursor reports 55 passed, 0 API calls, release=false. This is an execution checklist, NOT an authorization to call paid APIs or claim first-LIVE.

## Decision

STOP Phase 8 architecture revisions. The offline loop and feedback selection already passed the scoped checks. No paid experiment now: no new, story-relevant clip has independently verified FIRST-BROADCAST LIVE status.

## 1. Mandatory source-data lineage audit

Candidate events path is `/data2/lpy1/causal-chain2/causal_chain/examples/交付_out/10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语.json`.
Do NOT assume 交付_out is a non-gold source. Inspect the real file schema, provenance and creation logs/related scripts; determine whether the video_context.REPLAY/LIVE fields and causal events were human-edited, model-generated from raw match JSON+MP4, or merged.
**User-approved input rule (2026-11-08): `causal.json` IS permitted as a supplementary source of atomic events for the original `赛事.json`.** It can add missing atomic event types, event links and associated source-time metadata. Do not reject `causal.json` merely because it is a supplemental file or may contain manually curated event content. Treat `赛事.json` + `causal.json` + the original source MP4 as allowed inputs for this workflow; retain the provenance and any disagreements for audit.
Distinguish permitted `causal.json` atomic-event supplementation from disallowed `strip_gold.json`, benchmark answer keys and human-labeled long-form story/EDL gold. The existence of an event or LIVE/REPLAY field inside `causal.json` is useful for candidate discovery or conservative replay screening, but is NOT independent evidence that the *picture* comes from the first broadcast. Only source-video timeline review can authorize FIRST_LIVE_VERIFIED. Report precise files, SHA and event origins; do not silently turn causal labels into video safety certifications.
If the replay flag comes from manually annotated delivery_out, it is a conservative screening signal, not an independent visual confirmation. Keep the associated clip excluded pending independent visual review (the safe choice).

## 2. Original video review for 2 meaningful candidates (no paid)

Use `赛事.json` as the primary atomic-event inventory and merge relevant `causal.json` supplementary events before candidate search, keeping source_file/source_event_id/source_pts provenance, deduplication decisions and any timestamp conflicts. The causal supplement is not a substitute for source-video first-broadcast verification.

Use source SHA `a66147f79609c8fbf831a8bd29de4c6d7f746b314b2b18a88ffb1fc5f319da9c` only after checking server bytes match.
First verify whether the preflight windows are actually relevant to an active narrative defect. Previous Phase7 bridge @3504.14–3515.83 was semantically not helpful; treat it as a negative control, NOT a default production edit. The 824.81–835.15 window is already metadata-replay positive; DO NOT use it in the story. The 6430–6445 window is currently UNKNOWN and may be prioritized only if it serves a concrete diagnosed story role.
For the two highest-ranking **story-relevant** candidates chosen by the existing diagnostic/search pipeline, extract 45-90s continuous, timestamp-accurate context from original source MP4 around each candidate. Add candidate action context, previous occurrence search (other angles/repeat/slo-mo), scoreboard/clock and replay-overlay transitions, camera continuity. If visual evidence is insufficient, do NOT mark FIRST_LIVE_VERIFIED; use UNKNOWN.
Generate small reviewable source-context clips (or a sparse indexed contact sheet PLUS short clips if upload size is limited), with source SHA, start/end PTS, clip SHA, relevant earlier matches, and exact question for reviewer. These must be uploaded into the chat if ChatGPT is to visually inspect them; local server paths alone cannot be viewed here. Do not claim ChatGPT already viewed the MP4.
One short 30s context clip or absence of replay flags is insufficient to prove first occurrence across full broadcast. If no check across relevant earlier timeline exists, classify UNKNOWN. Never use replays as substitutes for missing first broadcast actions.

## 3. Reviewer-verifiable decision schema

For each candidate return: `{candidate_id, issue_id, story_role, source_sha256, pts_start, pts_end, context_clip_path, context_sha256, earlier_occurrence_candidates, original_broadcast_observations, replay_or_slowmo_evidence, outcome, uncertainty_reason, reviewer, manual_vs_generated_evidence}`.
Allowed outcome: `FIRST_LIVE_VERIFIED` only with independently reviewed first-broadcast evidence; `REPLAY_CONFIRMED` only with grounded replay evidence; else `UNKNOWN`. No fixture `MECHANISM_TEST_NOT_MATCH_TRUTH` record may be treated as match truth. No raw `explicit_review` self-assertion is an independent verdict.
Protect raw source, baseline story, and labels. No render/release when safety UNKNOWN.

## 4. Two-round paid study design — planning only, not execution

Only after at least one truly story-relevant new clip has passed verified first-LIVE with goal and PTS safeguards: propose a two-round experiment with source/video/template frozen, compare to same baseline under equal total API/observation budget, and plan blinded human story-quality review.
Current code confirms `phase8_paid_multi_round=True` is required above one round, `max_calls<=5`, `max_cost_usd<=0.10`, retries=0. These are software stop conditions and estimated provider cost, not a guaranteed billing cap. The user has NOT approved paid calls.
Do not spend HTTP on the known weak 3504 bridge merely because it was previously attempted. Choose candidates for genuine narrative defects and record new defect avoidance.

## 5. What Cursor should report now

(a) Exact `赛事.json` + approved `causal.json` event merge, provenance, deduplication and distinctions from story/benchmark gold; (b) two candidate source clips with exact source timestamp and evidence of earlier-occurrence search; (c) PASS/UNKNOWN/REPLAY per window with uncertainty; (d) the exact total-call and cost estimate for a future evaluation, but DO NOT run it; (e) no changes to V1/V2, no gold, no paid HTTP, release=false.

Stop here. The next ChatGPT review should make a go/no-go decision about **real visual evidence**, not another iteration of abstract policy code.