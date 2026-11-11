# V3-A Phase 9 real story-quality experiment report

Generated: 2026-11-11T15:16:50.197176+00:00  
Code SHA: `bcacb851cb600f461a62f82c2df7940223eb78cb`  
Branch: `story-va-v3a-full-chain-audit-fixes`

## Resume decision

Attempt1 was **not** cleanly resumable (`STOP_NO_ACTION` finalized, no resume CLI, continuation would contaminate attribution). Per user instruction, attempt1 was preserved and a **clean re-exec** was run as attempt2.

## Match / baseline

- Match: UAE–Oman (A)
- Frozen V3-R Phase5 reused
- V3-R `story_clean.mp4` SHA256: `7b0bfa49a7ff22d041496efe65c944cc57e9a2502107c2ad438119b85e4199f7` (~94.88s)

## Budget

Authorized: max_calls=5, max_cost_usd=0.10, max_rounds=3, max_retries=0

| Attempt | HTTP | est_cost_usd | Decision | Candidate rendered | APPLIED/VERIFIED/IMPROVED |
|---------|------|--------------|----------|--------------------|---------------------------|
| 1 (preserved) | 4 | 0.001149 | UNRESOLVED | no | 0/0/0 |
| 2 (primary) | 4 | 0.004355 | UNRESOLVED | no | 0/0/0 |

No third paid run.

## What happened (attempt2)

1. **Critic (VLM)**: provider `HTTP 500` / empty response (`provider_mode=degraded`). No confirmed story defect; no redundancy claim.
2. **Search**: found FIRST_LIVE candidates (2273 / 6400 etc.) but narrative-fit remained `NEEDS_VIDEO_REVIEW` without successful vision support.
3. **Planner (LLM)**: `UNRESOLVED` — refused insert/drop without confirmed defect + REVIEW_SUPPORTED / redundancy evidence.
4. **Apply / EDL**: unchanged (`changed: false`); candidate render skipped.
5. **Fullcut verifier**: not evaluated (no edit). `authorizes_promote_best=false`.
6. **Delivery**: `BLOCKED`; best remains **v0 = V3-R**.

## Required artifacts (server paths; MP4s not in git)

- V3-R baseline: `/tmp/lpy1_phase9_story_quality_20261111_rerun2/preserved_v3r_story_clean.mp4`
- V3-A candidate: **none** (explicitly not fabricated)
- Critic/Planner/EDL/Fullcut JSON under: `/tmp/lpy1_phase9_story_quality_20261111_rerun2/real_vlm_run/02_round_01/`
- Blind pack: `/tmp/lpy1_phase9_story_quality_20261111_rerun2/blind_review` — status `NO_CANDIDATE_PAIR` (cannot build honest X/Y without a second cut)
- Attempt1 archive: `/tmp/lpy1_phase9_story_quality_20261111/attempt1_vlm500_unresolved`

## Claims

- Do **not** treat this as IMPROVED / BEST / release.
- This is a **meaningful negative/infrastructure-limited result**: gates held; no fake edit was invented after VLM failure.
- API key itself is not invalid (separate health check OK); multimodal critic path was unstable on provider side.

## Best baseline

**V3-R remains the retained best baseline.**
