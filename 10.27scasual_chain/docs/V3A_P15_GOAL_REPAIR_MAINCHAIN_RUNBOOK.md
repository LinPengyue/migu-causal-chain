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
