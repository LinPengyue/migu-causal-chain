# Exp B · Scheme A independent trial cut (0 HTTP)

- Base: `ae0ae2b`
- Verdict: **`HUMAN_REVIEW_REQUIRED`** (not formal acceptance)
- Formal EDL/BEST/story_clean: **not overwritten**
- API calls: **0**

## Trial video
- Path: `/tmp/lpy1_v3a_expb_schemeA_trial_20261113/schemeA_independent_trial.mp4`
- SHA256: `6e27e8112ab7dbf48b3104ad2bfba3acbdfd50a27455ba47ebd34cb33063bf17`
- Bytes: 44217111
- Duration (ffprobe): **90.418s** (expected ~90.220s, Δ=0.198)
- Audio: **True** (original match audio on media parts; silent slate on title placeholders)

## Actual cut boundaries used
- Equalizer goal window: **[6441.88, 6459.60]** (unchanged; not expanded)
- Optional unverified suggestions only: start≈6438.0 / end≈6464.0 — **not applied**

## Validation
| check | result |
|---|---|
| segments rendered | 9 (media 7 + slate 2) |
| source PTS nondecreasing | True |
| goal actions | 3 (opening → equalizer → go-ahead) |
| scoreboard order | deficit → equalizer → go-ahead = True |
| EDL consistency | proposal Scheme A structure preserved in actual EDL JSON |

## Window / scoreboard review
- Match clock advances with PTS (75:49→76:06); no replay/slow-mo badge seen on sampled stills.
- Post-net camera cuts present; interpreted as live reaction changes, not proven replay.
- End @6459.60 already shows **1-1** but truncates huddle celebration (~6463.6).
- Scoreboard 6534.62–6538.12: clock ~77:21, **UAE 1-1** — same equalizer state.

## Why HUMAN_REVIEW_REQUIRED
- End boundary 6459.60 truncates sideline huddle celebration visible by ~6463.6; optional extend proposed but NOT applied
- Full-window continuous replay exclusion not certified beyond still+clock monotonicity audit
- Precise cut boundaries remain unlocked (attestation)
- Trial MP4 generated for review under Scheme A fixed window; not an acceptance/pass of formal delivery

Artifacts: `docs/V3A_EXPB_SCHEME_A_TRIAL_*.json` · local review stills under `/tmp/lpy1_v3a_expb_schemeA_trial_20261113/`
