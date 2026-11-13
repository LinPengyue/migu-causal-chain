# P17: Native continuous source-video broadcast-phase observer (opt-in)

Parent: P16.1 branch `story-va-v3a-p16-broadcast-phase-evidence`, HEAD
`0ece491` (62 tests passed on server, reported 2026-11-13).

## What genuinely changed
Prior VLM goal probes used sparse source JPEGs. The same football goal
can look like LIVE in a normal-speed replay or alternate camera replay.

`native_broadcast_observer.observe_native_broadcast_phase` now optionally
sends a *single continuous reencoded MP4* source interval directly to a
Qwen-compatible OpenAI video API using
`{type:"video_url",video_url:{url:"data:video/mp4;base64,..."}}`,
PLUS original source JPG anchors carrying exact FrameStore q3 PTS.
This is a video input, not a fabricated claim of having watched video.
The original source whole-file SHA, source segment PTS, reencoded clip SHA
and bytes, all original JPG paths/PTS/SHA, exact sent frame IDs and raw
model response bytes/hash are persisted locally.

- Temporal content: source [shot-18s, net+24s], capped by source duration.
  One *continuous* segment, reencoded at 360p/5fps without sound; time
  granularity and potential missing fast-action/replay graphics are
  explicitly limited. Up to 12 MB upload; no unbounded media submission.
- Original-source JPEG anchors are concentrated near the shot and net,
  along with earlier play and reaction/post-goal context. The model must
  cite a program-generated frame ID and source PTS.
- Structured original video observation checks positive ordered phases:
  pre-goal active play -> shot/net -> immediate reaction; later replay is
  optional, and replay/slowmo within the action rejects the observation.
- All previous P16 `first_live_window_evidence` and
  `continuous_broadcast_phase` authorization gates stay unchanged.
  This *observation* cannot independently exclude a different-angle
  earlier same-action appearance. Therefore it **never** emits a
  FIRST_LIVE proof, evidence-store record, EDL insertion or final delivery.
- For other matches the method receives source MP4/SHA and shot/net at
  runtime; it contains no hardcoded B source times, score or team names.

The code is wired into the **single** `run_story_e2e` R1 Goal Video flow,
after a real goal semantic candidate is already observed. It has no separate
editor, EDL path, Critic or alternative self-revise loop. It skips if there
is no real goal shot/net observation, remaining budget, or user opt-in.

## Explicit real-video paid consent (not for automatic execution)

The default remains OFF. Even existing `--enable-real-api`
`--i-approve-budget` does **NOT** activate native-video phase review.
Only the additional `--enable-native-broadcast-observation` flag enables
one extra real model call within the shared call/cost budget and real API
mode, through the normal E2E CLIs. It may exceed estimates because vendor
charges are not a prepaid hard dollar cap. Unsupported proxy video_url
formats result in an unresolved observation, never a simulated success.

No real HTTP calls were made in developing P17. Do not run a paid B
experiment without a separately explicit approval to do so.

## Cursor server verification, zero HTTP

```bash
git fetch origin story-va-v3a-p17-native-broadcast-observer
git switch story-va-v3a-p17-native-broadcast-observer
git pull --ff-only
cd 10.27scasual_chain

PYTHONPATH=algo python -m pytest -q \
  tests/test_v3a_native_broadcast_observer.py \
  tests/test_v3a_continuous_broadcast_phase.py \
  tests/test_v3a_goal_video_repair.py \
  tests/test_v3a_stage5_broadcast_temporal_audit.py \
  tests/test_v3a_stage6_broadcast_verifier.py \
  tests/test_v3a_phase8_run_story_e2e_loop.py

git status --short
git rev-parse --short HEAD
```

Report failures and true test counts. No Stage1–7 replay, no new billed
model request, no BEST/EDL modifications. Existing Stage3 B source frame
provenance remains valid; historical Qwen logs are NOT secretly re-labeled
as native-video model input.

## Remaining barrier to true FIRST_LIVE

1. A real native-video phase observation must be run under explicit
   authorization and audited with original video and actual model output.
   This has **not** been done.
2. An independent, source-bound earlier same-action occurrence review,
   robust to alternate camera angles and normal-speed replay, is still
   needed. Old bounded pHash no-match and camera cuts are not enough.
3. Only if both positive evidence and the independent earlier-occurrence
   proof are credible may P16 gate consider FIRST_LIVE. Thereafter the
   same E2E Goal Repair, EDL render, dual-video story Verifier and release
   ledger remain mandatory.
4. Evaluate across held-out matches, not only B. Record false-live errors
   on confirmed normal-speed replay and no-later-replay cases separately.

B today: semantic source frame provenance VERIFIED, first-live NOT_VERIFIED,
Goal EDL repair NOT PERFORMED; BEST unchanged.

## P17.1 — Reuse already authenticated B Stage3 instead of buying the same observation again

P17 original wiring was checked after 71 server unit tests. The P17 native
branch correctly reads `goal_semantic.source_video_crosscheck.derived_times`
from a NEW VLM call; no field-name bug exists. However it previously did NOT
accept the six original B Qwen3.6/3.7 Stage3 citations previously proved
`ORIGINAL_SOURCE_FRAMES_EXACTLY_REPRODUCED` by P15.3. Merely switching
on native mode would repeat the paid sparse-image VLM call.

In the same `run_story_e2e` chain, P17.1 now accepts an **explicit DEV-only**
pair of original archived evidence files:
- `--native-phase-archived-frame-manifest`: read-only JSON
  `{"frames":[...]}` wrapping the ACTUAL archived Stage3 round1/round2
  frame records. Must contain the model-cited original paths, actual PTS,
  requested times. Never invent IDs, paths or PTS.
- `--native-phase-archived-semantic-log`: archived REAL Qwen
  `automated_semantic_log.json` with original `vlm_inference`, cited shot/net
  frame IDs, `provider_mode=real`, `observation_only=true`.

Before using anchors, `resolve_reverified_archived_goal_anchors` invokes
P15's `inspect_archived_real_goal_frames` and re-executes the *actual*
original-source SHA+Stage3 q3 JPEG bytes+PTS verification, NOT a trust of
an old `binding_valid=true` string. It then extracts shot/net from the
original cited frame IDs; no source frame or timestamp is fabricated.

It additionally requires exactly ONE matching current inferred missing
goal-coverage issue with `0 <= score_confirmation_sec-net_sec <= 180`.
This binds the old real goal observation to the correct story defect
heuristically, never to human causal Gold. It is a diagnostic association,
NOT first-live evidence or editing authorization. If ambiguous, fail-closed.

**Critically, archival mode SKIPS the redundant paid Stage3 sparse-image
observation** in the current E2E round. It does not claim the new native
MP4 VLM call was already done. The separate native video input remains
explicitly paid, opt-in and observation-only. The rest of the unified
story Critic/Planner/Verifier may use its own authorized budget; never
claim archival mode makes a full paid E2E run exactly one HTTP call.

Archival reuse may only be invoked through `story_e2e_cli` with frozen
`--phase5-dir`, no `--run-fresh-v3r`. It is blocked from the
`story_full_e2e_cli` fresh pipeline **even without --strict-raw-only**.
Therefore the formal raw-MP4+events-JSON benchmark is uncontaminated.

### Zero-paid regression for archived reuse

```bash
git fetch origin story-va-v3a-p17-native-broadcast-observer
git switch story-va-v3a-p17-native-broadcast-observer
git pull --ff-only
cd 10.27scasual_chain
PYTHONPATH=algo python -m pytest -q \
  tests/test_v3a_native_broadcast_observer.py \
  tests/test_v3a_continuous_broadcast_phase.py \
  tests/test_v3a_goal_video_repair.py \
  tests/test_v3a_stage5_broadcast_temporal_audit.py \
  tests/test_v3a_stage6_broadcast_verifier.py \
  tests/test_v3a_phase8_run_story_e2e_loop.py
git status --short
git rev-parse --short HEAD
```

**No paid run requested or authorized by this document.** Do not start a
real native MP4 VLM call without direct user approval. Do not rebuild Stage1–7,
modify BEST, or substitute any Gold or post-hoc result for the original
Stage3 manifest and log.

## Server verifies (Cursor)

- P17.1 regression @ `a513e70`: **80 passed**, 0 HTTP — see
  `docs/V3A_P17_1_REGRESSION_SUMMARY.md`.
- P17.2 B native preflight @ `a513e70`: **STOP_NO_PAID_CALL** (Critic-before-native
  + unproven `video_url`) — see `docs/V3A_P17_2_B_NATIVE_PREFLIGHT_SUMMARY.md`.
