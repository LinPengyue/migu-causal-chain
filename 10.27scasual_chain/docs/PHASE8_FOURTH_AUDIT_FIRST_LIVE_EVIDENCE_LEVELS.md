# Phase 8 fourth audit — offline loop accepted, first-live semantic proof not accepted

Reviewed branch story-va-v3a-phase8-loop-impl at 4646a697a7028abad547ad675a5f85cdbfc8ca26. Static code and committed artifact inspection, not independent pytest run or playback of real match.

## Accepted
- Paired same-EDL control proves real run_story_evidence_search + plan_from_diagnosis changes A@896-908 to B@1496-1510 when A feedback is supplied; A remains in pre-feedback candidate set, so EDL occupancy confound is excluded for this paired component test.
- The actual run_story_e2e fixture-path two-round control-flow/feedback/versioning is in place; no real quality improvement has been established.
- Event-chain labels and simple targeted_visual_verified booleans fail the negative first-live test.
- Cursor reports 77 passed, 1 deselected, not independently rerun. Unmocked unified E2E and cross_match remain NOT RUN.

## Critical P0 finding: source-frame binding mislabeled as first-broadcast LIVE
- first_live_window_evidence.py build_local_first_live_evidence_pack lines ~199-230 writes status FIRST_LIVE_VERIFIED whenever temporal_span_ok is true. temporal_span_ok only checks increasing sample timestamps within the window; it does NOT establish that footage is the first live broadcast rather than a replay.
- validate_first_live_evidence_record checks hashes, source SHA, PTS and that asserted status, NOT first-broadcast content semantics. story_video_verifier.py ledger and hard-safety then promote to safety PASS.
- In positive_pack/evidence.json all THREE image SHA-256 values are identical at t=0.670, 1.300, 1.930. This may merely be a static test video, not evidence of a replay; it proves no broadcast first-occurrence semantic property. The manifest also explicitly states claims_full_broadcast_timeline=false.
- The require_not_replay_flags property is metadata, not a replay/first-broadcast detector.
- Therefore positive pack PASS shows frame integrity and PTS binding only. Calling it FIRST_LIVE_VERIFIED is an unsafe false positive for the project requirement.

## Minimal fix (no new Agent architecture)
1. Rename the local pack verdict to FRAME_BOUND_VALID (or PTS_FRAME_BOUND). Keep source SHA, exact PTS, image-byte hashes and manifest. Default first_live_status NOT_VERIFIED.
2. Make record validation independent: binding_valid=True/False; first_live_verified=True only if a DISTINCT authenticated first-broadcast review artifact binds same source SHA + PTS and contains actual timeline/replay evidence. A local frame extraction or a VLM text claim must never self-certify first-live.
3. First-broadcast review observes surrounding SOURCE VIDEO CONTINUOUS CONTEXT: scoreboard/clock, replay transitions, broadcast overlays, motion and whether event occurred previously. Produce auditable review record with method, timestamp windows, clips/frames, hashes, reviewer/algorithm provenance, outcome FIRST_LIVE_VERIFIED | REPLAY_CONFIRMED | UNKNOWN and rationale. Sparse isolated frames alone must remain UNKNOWN. A human judgment may be manually recorded when explicit and evidence-backed, not implied by file existence.
4. Hard-safety PASS for a new segment requires independently verified first broadcast on EVERY new window. Binding-only stays safety UNKNOWN. An unapproved exploration candidate may be observed further but cannot masquerade as approved safe working or delivered video.
5. Do not weaken replay/slowmo/goal/PTS/render constraints or formal delivery gate. No paid API runs.

## Focused tests
- Valid JPG hash pack with no timeline review: binding PASS, first_live NOT_VERIFIED, hard-safety UNKNOWN.
- Synthetic replay segment still binds to source SHA/PTS but does NOT become FIRST_LIVE_VERIFIED. Explicit replay review -> hard-safety FAIL.
- Three identical extracted JPGs are no semantic proof of first broadcast.
- Missing / mismatched frame bytes, source digest or PTS fails binding validation.
- Two new segments, one unreviewed -> safety UNKNOWN.
- Prior ledger labels and raw VLM/fixture booleans do not certify real first-live.
- Existing paired A/B control and two-round loop tests remain green (adjust intentionally incorrect positive expectation).

## Closeout boundary
Accept PHASE8_OFFLINE_FEEDBACK_LOOP_PASS. Decline PHASE8_REAL_FIRST_LIVE_POSITIVE_PASS and PHASE8_REAL_VIDEO_QUALITY_GAIN. Once the evidence tiers are corrected and a zero-HTTP original-video temporal review can produce an honest verified/replay/unknown outcome, finish Phase8 mechanism work and request explicit budget approval for a bounded real-video quality experiment. Do not start Phase9 or paid calls automatically.

Cursor return: implementation SHA, test commands/results, corrected binding-positive/first-live-unknown evidence example, a reviewed first-broadcast case if available, release=false unless hard proofs present, and no V1/V2 changes.