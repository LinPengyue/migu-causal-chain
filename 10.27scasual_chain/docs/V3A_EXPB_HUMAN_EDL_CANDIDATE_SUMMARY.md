# Exp B — human-attested goal EDL candidate (proposal only, 0 HTTP)

- HEAD tested: `403df8d`
- Pytest: **67 passed** (human EDL candidate + offline + context QA + continuous phase + goal repair)
- Status: `PROPOSAL_ONLY_REQUIRES_CLIP_BOUNDARY_AND_STORY_REVIEW`
- `api_calls=0`, `first_live_verified=false`, `executable_safe_revision=false`, `edl_modified=false`

## Candidate window (hypothesis only)

- `media_in=6441.88` / `media_out=6459.60` (= shot 6447.88 − 6 / net 6450.6 + 9)
- **Precise boundaries NOT human-locked** (`precise_cut_boundaries_confirmed=false`)

## Neighbors

| | segment_id | media | role |
|---|---|---|---|
| insert after | `seg_buildup_event_000411` | 3442.75–3454.75 | buildup_action |
| insert before | `seg_equalizer_scoreboard` | 6534.62–6538.12 | equalizer_scoreboard_anchor |
| placement | `CHRONOLOGICAL_NEIGHBORS` | | |

- Overlap with existing EDL timed segments: **none**
- Source gap pred→goal ≈ **2987 s**; goal→scoreboard ≈ **75 s**

## Window 6441.88–6459.60 replay / continuity

- Prior ExpB stills in-window show live attack→shot→net→early celebration; **no clear replay chrome on those stills**.
- Stage7 cuts in-window: [(6451.7, 6452.2), (6454.2, 6454.7), (6456.7, 6457.2)] (post-net camera-change diagnostics; **not** proven replay/slow-mo).
- Suspect same-action wide @**6488.60 is outside** this window.
- Sparse stills **cannot** fully rule out a brief replay insert between samples → `replay_or_slowmo_ruled_out_for_full_window=false`.

## Story structure risks (do not relax gates)

1. Large narrative jump from buildup (~3454) to equalizer goal (~6442).
2. Boundaries not human-approved.
3. Window may end before a clear 1-1 board; successor scoreboard is ~75s later.
4. Post-net camera cuts need continuous-video review for slow-mo/replay packages.

Artifacts: `docs/V3A_EXPB_GOAL_EDL_CANDIDATE.json`, `docs/V3A_EXPB_HUMAN_FIRST_LIVE_ATTESTATION.json`, `docs/V3A_EXPB_HUMAN_EDL_STORY_STRUCTURE_AUDIT.json`.
