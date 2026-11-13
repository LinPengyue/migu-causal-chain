# P15 — Goal repair is a story-video operation, not a scoreboard-template patch

Branch: `story-va-v3a-p15-goal-repair-mainchain`.
Base: Stage7 report `477dec4`. Protected: V1/V2/V3-R/V3-A history and BEST video.

## Why this change

Stage7 B had 107/107 decoded samples and four post-net cut candidates, but
FIRST_LIVE remained unverified. Do not rerun Stage1–7 or claim cut evidence proves
the first broadcast. Real B goal semantics at ~6447.2/6450.6 were already obtained
in Stage3. The remaining work is independent broadcast-phase verification and
the existing *unified* E2E edit/render/Verifier loop.

Code review found two *main-chain* problems that can obstruct a repair even after
valid original-video proof becomes available:

1. The Goal Repair selector previously only accepted
   `diagnosis_status=HYPOTHESIS_NEEDS_VIDEO`. If an evidence-backed Critic confirms
   the defect and sets `CONFIRMED_STORY_DEFECT`, it is excluded.
2. EDL goal insertion demanded a role ending in `*_scoreboard_anchor` near the
   scoreboard confirmation. Other narrative templates may omit this role.
   Validated goal footage was then unusable despite passing video/safety checks.

## P15 changes

- Eligible goal defects: `HYPOTHESIS_NEEDS_VIDEO` or
  `CONFIRMED_STORY_DEFECT`. Both continue to require the SAME independent source
  SHA/PTS, shot-to-net semantic review, first-broadcast timeline review and
  original-frame re-decode before any EDL mutation.
- Preserve the score-board anchored insert path and original role when present.
- When template scoreboard beat is absent, insert the *video-verified* action
  at the unique chronological source position relative to existing active cuts,
  preserving title/placeholder rows. Use the template-neutral role
  `score_change_goal_action`, with `placement_basis` explicitly recorded.
- New goal row has `narrative_fit_status=UNVERIFIED_PENDING_RENDERED_VIDEO_REVIEW`;
  source-PTS monotonicity, render, full-video comparison, first-live ledger,
  quality verdict and release gates remain untouched.
- No Gold/P14 causal chain, no match-specific timestamps, no paid API, no
  synthetic FIRST_LIVE promotion.

## Cursor: minimum server checks (no paid API)

```bash
git fetch origin story-va-v3a-p15-goal-repair-mainchain
git switch story-va-v3a-p15-goal-repair-mainchain
cd 10.27scasual_chain
PYTHONPATH=algo python -m pytest -q tests/test_v3a_goal_video_repair.py
PYTHONPATH=algo python -m pytest -q tests/test_v3a_stage5_broadcast_temporal_audit.py tests/test_v3a_stage6_broadcast_verifier.py
git status --short
```

These are unit/regression tests on existing fixtures, NOT an A/B/C successful
real-video result. The `test_no_matching_scoreboard...` expectation was
intentionally changed from block to a chronology-guarded neutral insertion.

## Next evidence task, without repeating prior experiments

1. **Inventory only** the source-bound *existing* Stage3 semantic logs, corrected
   Stage4 continuous context (6428.62–6477.62), existing V2/V3-R verified
   evidence, first-live ledger records and First-LIVE review schemas for A/B.
   Report exact SHA+PTS+model provenance; do not reuse human causal Gold or
   treat the old 40-second truncated clip as full context.
2. Identify which exact **trusted broadcast-phase evidence** is genuinely
   missing to certify B as FIRST_LIVE (no inference from absence of pHash or cuts).
   V2 textual LIVE and Stage3 VLM `live` labels are non-authoritative.
3. Check only the actual main-chain wiring in `story_e2e_agent.run_story_e2e`:
   `goal_video_semantic_observation` → independently reviewed source-window
   evidence → `repair_goal_coverage_from_video_reviews` → `candidate_edl`
   → render → dual-video Verifier. Currently external review JSON is required;
   a full autonomous producer of trustworthy first-live proof is **not** yet
   implemented. Do not claim B repaired.
4. Keep A/B/C unchanged: A controlled deletion, B historical raw-only omission,
   C intact negative control. Cross-match/template heldout only after real
   evidence-to-edit positive path exists.

Please report pytest totals/failures, git commit SHA, source-provenance inventory,
and any clear main-chain breakage. Do not perform new paid calls, full raw-only
re-runs, extra pHash/OCR/cut scans, or edit historical BEST videos.

## Acceptance semantics

- VALID_GOAL_ACTION = source-bound cited shot/net with correct score transition.
- FIRST_LIVE_VERIFIED = independent original broadcast phase and first-airing
  evidence with provenance; neither a frame-pack hash nor VLM/cut label suffices.
- EDL_REPAIRED = concrete changed, PTS-safe EDL row and a rendered candidate.
- STORY_IMPROVED = dual-video evidence/human blind assessment, not duration.
- ACL benchmark fairness = only original video + raw event JSON as formal
  prediction inputs; development-only human atomic enrichment is separately named.

## P15.2 main-chain REAL observation bridge (after 27-pass Cursor regression)

The previous 27-pass regression applies only to commit `2620cad`, **not**
to the following P15.2 changes. Check the new branch HEAD before running.

- `observe_source_goal_video_with_shared_vlm` now records the exact model
  input frame paths/IDs/PTS, model response excerpt, and the candidate source
  clip SHA. It does NOT claim these frames were first broadcast.
- `assemble_live_goal_review_from_observation` maps REAL in-process goal
  observation to the existing goal review *only when* an independently
  provisioned `first_live_evidence_store.by_key[SHA|start:end]` contains a
  matching window's frame binding AND a broadcast timeline review.
  Missing evidence, mock provider, missing model audit, stale IDs or absent
  source clip SHA fail CLOSED.
- `run_story_e2e` passes the REAL observation and first-live evidence store
  to the already existing Goal Repair executor. Existing external-review
  mode remains supported. No second Agent or duplicated revision loop.
- Critically, Stage3 B logs already on server are **not automatically**
  self-attested as first-live, and an UNKNOWN Stage4 timeline cannot unlock
  insertion. The current B remains `EDL_REPAIRED=false`.
- P15.2 tests assert an in-process evidence-to-edit path with explicit synthetic
  video fixture, plus negative tests for UNKNOWN phase, absent evidence, bad
  model frame IDs, mock provider and absent audited model output.
  The synthetic positive uses a monkeypatched source re-decoder; it is
  ONLY a control-flow regression, NOT proof for actual match frames.

### Cursor instructions — run only new tests and evidence checks

```bash
git fetch origin story-va-v3a-p15-goal-repair-mainchain
git switch story-va-v3a-p15-goal-repair-mainchain
git pull --ff-only
cd 10.27scasual_chain
PYTHONPATH=algo python -m pytest -q tests/test_v3a_goal_video_repair.py \
  tests/test_v3a_stage5_broadcast_temporal_audit.py \
  tests/test_v3a_stage6_broadcast_verifier.py
git status --short
git rev-parse --short HEAD
```

Report the exact number of tests, errors and real source-input issues. No
new API call or FIRST_LIVE claim; no paid tests, no re-render of protected BEST.

### Evidence-to-edit blockers still to resolve

1. There is **no independently established B FIRST_LIVE broadcast timeline
   verdict**. Stage4's UNKNOWN is authoritative until real phase evidence exists.
2. The current in-process VLM frame outputs and locally generated first-live
   frame packs use potentially different frame IDs/JPEG encoders. The
   validator deliberately requires cited model-input frames to match the
   original source at the exact PTS, not similar-looking replacement frames.
   Check this exact binding gap before any future live-positive test.
3. Historical Stage3 Qwen3.6/Qwen3.7 logs predate the new
   `frame_records/model_response_audit` structure. Do not fabricate these
   fields or rewrite them as native active-Agent observations. Preserve
   separate `REUSED_PRIOR_EVIDENCE` vs in-process provenance.
4. The current adapter is for new REAL in-process goal observations; it is
   not yet a historical Stage3 replay adapter. Therefore this change alone
   does not eliminate the need for trustworthy FIRST_LIVE evidence.
5. Continue in the single `run_story_e2e` main chain. A/B/C remain the
   original blind-repair tests, not hand-authored success cases.

## P15.3: historical Stage3 exact producer replay (after P15.2 32 passed)

Cursor confirmed B Qwen3.6/Qwen3.7 original referenced JPG SHA bytes differ
from `first_live_localize.extract_frame_accurate` at the same time.
A fresh code audit identified the concrete extractor mismatch:

- `story_video_agent.frames.FrameStore._ffmpeg_extract`: fast
  `-ss <requested_media_sec> -i source -copyts -vf showinfo -q:v 3`,
  fallback `select='gte(t\\,<requested>)' ... -q:v 3`.
- `first_live_localize.extract_frame_accurate`: two-stage seek,
  `-frames:v 1 -q:v 2`.

This difference alone explains **why JPEG bytes can differ**, but it is not
yet a B match result. The fix replays the ORIGINAL FrameStore profile and
requires exact JPEG SHA equality plus original requested/actual PTS agreement
within 50 ms and whole-source SHA equality. It **does not** accept pHash,
SSIM, HSV/color histogram, loose image similarity or model LIVE labels.

Changes:
- `story_goal_video_repair.audit_source_frame_redecode`: explicit per-frame
  result, first try canonical q2, then reuse the actual historical
  `FrameStore` q3 producer; strict fail-close; source-frame identity only.
- `_source_frames_match_decoded_video` uses the audit's Boolean result,
  preserving existing caller and current frame/source safety checks.
- `source_frame_provenance_cli.py` is a zero-HTTP, read-only one-time
  provenance checker for original Stage3 `automated_semantic_log.json` and
  original `frame_manifest.json`. It refuses fabricated model frame IDs
  and never writes an evidence-store FIRST_LIVE record.
- Six new tests cover actual FFmpeg q3 reproduction, tampered JPG,
  wrong MP4 SHA, PTS mismatch, log+manifest join, invented cited IDs.
  Test fixture uses synthesized VIDEO, not B frames.

### Cursor: run P15.3 without any new model experiment

```bash
git fetch origin story-va-v3a-p15-goal-repair-mainchain
git switch story-va-v3a-p15-goal-repair-mainchain
git pull --ff-only
cd 10.27scasual_chain
PYTHONPATH=algo python -m pytest -q \
  tests/test_v3a_goal_video_repair.py \
  tests/test_v3a_stage5_broadcast_temporal_audit.py \
  tests/test_v3a_stage6_broadcast_verifier.py
git rev-parse --short HEAD
git status --short
```

To inspect B's *existing* model-cited images, use the source path and
**original** matching manifest/log paths already on the server. Run once for
Qwen3.6 and once for Qwen3.7, with different NEW report destinations:

```bash
# Resolve these to the exact EXISTING source/artifacts; do not regenerate them.
export SRC_MP4=/path/to/original_match.mp4
export SOURCE_SHA=a66147f79609c8fbf831a8bd29de4c6d7f746b314b2b18a88ffb1fc5f319da9c
export ORIGINAL_FRAME_MANIFEST=/path/to/original/frame_manifest.json
export ORIGINAL_SEMANTIC_LOG=/path/to/original/automated_semantic_log.json
export FRESH_PROVENANCE_REPORT=/path/to/new/p15_stage3_qwen36_source_frame_audit.json

PYTHONPATH=algo python -m story_video_agent_v3.source_frame_provenance_cli \
  --source-mp4 "$SRC_MP4" \
  --source-sha256 "$SOURCE_SHA" \
  --frame-manifest "$ORIGINAL_FRAME_MANIFEST" \
  --semantic-log "$ORIGINAL_SEMANTIC_LOG" \
  --out "$FRESH_PROVENANCE_REPORT"
```

Replace all three artifact paths with actual correct source/manifest/log values
for EACH model. Do not use the Qwen3.6 manifest for the Qwen3.7 observation.

If legacy q3 bytes match with PTS, **only** source-frame provenance is proved.
If they do not match, report per-frame `decoder_profile`, PTS and
`reason` from JSON, rather than relaxing identity thresholds.

Either way:
`FIRST_LIVE=NOT_VERIFIED`; `B_EDL_REPAIRED=false`. No paid API, no new
source scanning, no new cut/OCR experiment, no BEST changes, no release.
