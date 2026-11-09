# V3-A Phase8: zero-paid local video narrative-quality audit (A/B/C)

Review inputs: exact uploaded MP4 bytes and sampled stills (roughly one frame per two seconds); this document is a **contextual screening audit, not a human-authenticated source-frame certificate and not full-video-with-audio adjudication**. No inference from a JSON label alone. The reviewing assistant can inspect these local user-uploaded clips but does **not** have access to the original private server source MP4.

## Reproducible inputs and identity

- Untouched V3-R baseline: uploaded `story_final.mp4`, SHA256 `7b0bfa49a7ff22d041496efe65c944cc57e9a2502107c2ad438119b85e4199f7`, around 94.85s; hash matches prior reported `baseline_v3r_story_clean.mp4`.
- A `PACK_A_setup_THEN_3504_THEN_buildup.mp4`: SHA256 `766f067c695fd35fd21616da00c7a3dab89065dcfb74316c6282192b7efc9d13`; 27.2s.
- B `PACK_B_setup_THEN_2273_THEN_buildup.mp4`: SHA256 `19494cd6d008cadf71f0d1e1a187d5c0e280a18cf74ba7e54101d90c384039d1`; 29.76s.
- C `PACK_C_buildup_THEN_6400_THEN_equalizer.mp4`: SHA256 `89145fde331ef9be1d5e283f88ace0f593947d1d5029941f58e15b6bf3551b2b`; 30.16s.

All three packs are stitched with BEFORE/CANDIDATE/AFTER identifying text overlays. The overlays are evaluation aids, not original game-broadcast labels. This audit did not generate a new finished cut.

## Narrative observations (hypotheses, not quality-ground-truth)

| Case | Screened content | Story fit vs untouched baseline | Follow-up |
|---|---|---|---|
| **A, source PTS 3504.14–3515.83, Save** | BEFORE an early deficit-setting field-wide setup; CANDIDATE goalkeeper save/holding ball plus spectators; AFTER another buildup/action sequence. The middle clip does not visibly explain a necessary missing state between these beats. | **REJECT as bridge**, independently of its previously unresolved first-live verification. Added action and crowd reaction do not automatically increase pressure or causality. | Negative control. Do not re-add, unless new observation-grade evidence actually changes the assessment. |
| **B, source PTS 2273.20–2290.41, Shot** | BEFORE deficit setup; candidate includes consecutive attacking organization and an attempted attack, then spectator cutaway; AFTER a later attacking phase. | **PROVISIONAL**, strongest of three as *potential* rising-pressure evidence. However it adds a relatively long beat, including spectator reaction, and the underlying causal/team-state bridge and cut rhythm remain unproven. | Create **offline, candidate-only** B variant and compare full baseline vs full cut, optionally explore shorter sub-windows only after exact revised first-live/source provenance validation. Do not claim REVIEW_SUPPORTED yet. |
| **C, source PTS 6400.90–6412.50, Defensive** | BEFORE keeper involvement; candidate mostly midfield defense/transition; AFTER the later equalizer sequence. | **WEAK / DEFER**. Could serve resilience or turnover theme under a different confirmed story need, but frames alone do not show the play causing or motivating the subsequent equalizer. | Keep as comparison control or different narrative-role candidate, never insert solely because it is FIRST_LIVE attested. |

### Broadcast-clock nuance in A (not a source-order bug by itself)

Sampled A screens show the candidate at broadcast time `47:38–47:43` with a `+4` stoppage-time indicator, followed by the AFTER shot labeled around `46:55–47:00` without stoppage. This is plausibly **first-half added time followed by second-half normal time**. Do **not** falsely report it as a reversal of match chronology based on scoreboard digits alone. Source-PTS, period/half, score transition and first-broadcast status must be distinguished.

## Scientific and engineering conclusions

1. A broadcast-first-LIVE certificate establishes footage safety, **not** narrative usefulness. B and C being previously user-attested first-LIVE is not proof of their story-fit or final-cut gain.
2. Current V3-A `story_narrative_fit.py` requires exact raw source SHA/PTS plus before/candidate/after original frame files and a review with source-bound context. A stitched PACK MP4 alone **must not** be fed as if it were that independent certified source record.
3. The 90-pass suite after `e258a23` verifies source-level behavior only. It does not validate real VLM story comprehension, frame semantic correctness, V3-R improvement, or unseen-match transfer.
4. Use A as negative, B as *conditional candidate*, C as *weak control*. Avoid choosing B as a hardcoded algorithm winner.
5. The next server run should be **zero paid**: preserve baseline EDL/MP4; create offline B and C trial cuts for **diagnostic human comparison only** (no release authorization or auto-accept); compare complete before/after sequences and full edited movie, judge missing information, chronology, pressure buildup, pacing, replay integrity, and goal protection. Trace back changed source PTS and log exact rejection/acceptance. If neither candidate improves the story, KEEP baseline.
6. Do not run a new paid contextual VLM until new explicit authorization. No direct changes to V1/V2 or main production branch.

**Status:** local visual screening complete; actual end-to-end candidate-versus-baseline story gain remains **UNVERIFIED**.
