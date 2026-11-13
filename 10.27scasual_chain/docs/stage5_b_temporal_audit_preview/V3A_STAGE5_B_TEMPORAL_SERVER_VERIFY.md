# Stage5 B — server verify (zero HTTP)

Code: `06f32fe` on `story-va-v3a-stage5-broadcast-temporal-audit`.
Pytest: **23 passed**. No paid API.

## Stage5 temporal audit

- two-model agreement: **true** (shot spread 0.68s, net spread 0.92s)
- OCR status: **SCORE_TRANSITION_INSUFFICIENT_OCR**
  - strong_before(0:1)=**0**, strong_after(1:1)=**5** (first @6459.2)
  - false/noisy pre ok: `[3,1]` @6441.2; in-window `[0,1]` @6449.2 (not pre-shot under rule)
- replay_event_hits: `[]`
- `ready_for_broadcast_review`: **false**
- `first_live_verified`: **false**, `edl_repaired`: **false**
- next_decision: `EVIDENCE_INSUFFICIENT_OR_CONFLICTING`

Assistive note: human-visible board is 0-1 before the shot, but automated Tesseract did not produce two strong pre-shot 0:1 readings. Do not promote from VLM/human sight.

## Stage4 full-context fix (regenerated)

New out: `/tmp/lpy1_v3a_stage4_B_first_live_review_fullctx_20261113`
- requested window [6428.62, 6477.62]
- clip duration **49.0s**, media_out=6477.62
- `context_truncated=false`, `continuous_context_complete=true`
- timeline still **UNKNOWN** / FIRST_LIVE false (expected)

## Gate

**No EDL repair.** Need stronger independent pre-shot OCR (or denser/better scoreboard decode) before broadcast-phase first-live path.
