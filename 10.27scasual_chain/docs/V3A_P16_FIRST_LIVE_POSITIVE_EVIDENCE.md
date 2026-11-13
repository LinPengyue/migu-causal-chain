# P16 — Stop false FIRST_LIVE promotions; make the next B test a positive video test

Base branch: `story-va-v3a-p15-goal-repair-mainchain`, which completed the
38-test P15.3 run and exact original-source q3 replay of six Stage3 B frames.

P16 is a *main-chain safety and evidence contract* update, NOT a new clip
finder, pHash search, OCR retry or Stage8 diagnostic loop.

## Why P16 exists

The previous `validate_first_live_evidence_record` accepted
`timeline_review.outcome=FIRST_LIVE_VERIFIED` when the supplied review had
the right source SHA and action PTS, without verifying whether the review
provided *positive, original-broadcast semantic evidence*. A reviewer-generated
JSON containing the word `FIRST_LIVE_VERIFIED` must never be sufficient.

P15.3 established B's real video GOAL content:
- Qwen3.6 citations f_0000/0001/0002: ~6447.2, 6448.88, 6450.6.
- Qwen3.7 citations f_0008/0010/0011: ~6447.88, 6449.68, 6450.6.
- Source SHA a66147f79609c8fbf831a8bd29de4c6d7f746b314b2b18a88ffb1fc5f319da9c.
- All six actual model-viewed JPGs can be reproduced with original FrameStore
  q3 + PTS; q2 differs as expected.
- Stage4 49s continuous source context [6428.62,6477.62] remains UNKNOWN.
- Stage6 no earlier pHash match for its bounded lookback is NOT absence of
  the same action in a different camera view.
- Stage7 camera cuts after the net do NOT classify replay.

## P16 implementation

`algo/story_video_agent_v3/continuous_broadcast_phase.py` defines
`validate_continuous_broadcast_phase_proof` for a trusted, separately
obtained *continuous broadcast phase* review.

A FIRST_LIVE review now needs all of these, not simply four labels:
1. Identical original source SHA and exact goal-action PTS window.
2. Real, readable continuous context clip; exact file SHA and source-specific
   window; enough lead-in and after-action coverage.
3. Independently attributable real model review with model ID/response digest,
   or an explicitly attributed continuous-footage human review record.
4. Four **distinct frame citations**, tied to the source frame evidence pack,
   with positive visible cues in chronological order: live play before shot,
   shot/net action, immediate live reaction, and later replay of the SAME action.
5. Independent earlier SAME-action occurrence review; a bounded pHash negative
   or just saying 'VLM thinks live' does not fulfill this requirement.
6. Complete declared context and no conflicting replay/slow-motion/timeline
   discontinuity markers inside the action.

`first_live_window_evidence.validate_first_live_evidence_record` now refuses
all bare `FIRST_LIVE_VERIFIED` timeline labels that lack the above evidence;
goal insertion and final ledger both use this existing validator.

The pure checker validates data linkage and auditability, NOT semantic truth.
Test fixtures deliberately use synthetic JPG and MP4 bytes; even a positive
unit fixture does not prove a real football broadcast.

## Cursor: server regression only (zero paid)

```bash
git fetch origin story-va-v3a-p16-broadcast-phase-evidence
git switch story-va-v3a-p16-broadcast-phase-evidence
cd 10.27scasual_chain
PYTHONPATH=algo python -m pytest -q \
  tests/test_v3a_continuous_broadcast_phase.py \
  tests/test_v3a_goal_video_repair.py \
  tests/test_v3a_stage5_broadcast_temporal_audit.py \
  tests/test_v3a_stage6_broadcast_verifier.py
git status --short
git rev-parse --short HEAD
```

If failures arise, return actual test failure, file path and minimal cause.
Do not weaken the FIRST_LIVE gate, turn pHash/camera cuts into positives or
edit production footage.

## The next real experiment is *one* original-video temporal adjudication

B cannot be certified from its existing Stage3 sampled shot/net images,
Stage4 UNKNOWN, Stage6 bounded negative scan or Stage7 cuts alone.

The next evidence-producing step must independently inspect **the existing
continuous original broadcast** (not merely re-ask the same three Stage3
JPGs) and identify a source-grounded, time-ordered positive timeline:
live active play -> exact 6447 shot / 6450 net -> immediate live reaction ->
later replay of the SAME goal action. It also must inspect whether the
SAME ACTION occurred earlier on air with a different camera angle/at normal
speed. Every conclusion must cite source-video frames/PTS and provenance.

When actual visual audit can support all claims, produce a phase review
in the existing first-live evidence store, validate it with the new code,
then re-enter THE SAME `run_story_e2e` Goal Repair, render, dual-video
Verifier and first-live ledger. Never directly add goals from scoreboard time.

If real evidence stays ambiguous, retain UNKNOWN for B. **Do not create
Stage8/9/etc. searches or repeatedly sample the same B action.** Switch to
a genuinely held-out video/template and continue the general Agent, while
keeping the B blocker explicit in the ACL ablation report.

No paid API calls, real B review, EDL change or video rendering were performed
by the P16 commit. Any actual video review must be described as HUMAN vs
REAL-MODEL and report its true cost, inputs, and limitations.
