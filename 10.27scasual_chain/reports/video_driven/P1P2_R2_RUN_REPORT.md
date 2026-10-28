# Video-Driven P1/P2 Round 2 — Real-match hardening report

**Branch:** `story-va-video-driven`  
**Parent:** `52a6517`  
**Freeze baseline (untouched):** `462ea11`  
**Scope:** P1/P2 only (no P3 search / no P4 render)

## Fixes shipped

1. **Full-span sampling** — under `max_coarse_frames` budget, coarse samples span `[0, duration]` (linspace). Coverage metrics: `span_ratio`, `max_gap_sec`, `fullspan`, uncovered intervals.
2. **Adaptive densify without score success** — densify centers include unknown/conflict streaks and large gaps, not only successful score changes.
3. **Scoreboard OCR redesign** — smaller ROI grid, clock rejection (`MM:SS`), CJK/Latin team-digit patterns, `|` / `V` separators; variants merge into **one** observation; false digit-blob pairing disabled.
4. **Score state machine** — initial score **unknown** until multi-frame establishment; no assumed `0:0`; unresolved jumps recorded; no invented mid-path.
5. **P2 grades** — `unresolved` when perception insufficient; `none` only with established non-comeback path; evidence windows `hard_bound=false` + expandable from adjacent stable nodes.
6. **Run metadata** — every report records `commit_sha`, params, perception quality, sampling coverage.
7. **Artifact inconsistency** — old `croatia_sparse_probe` (1/8 usable, `4:2`, `degraded=false`) marked **STALE**; regenerated full-match run shows `degraded=true`.

## Commands

```bash
cd 10.27scasual_chain/algo
PYTHONPATH=. python -m unittest story_video_agent.test_video_driven_p1p2 -v

PYTHONPATH=. python -m story_video_agent.video_only_p1p2 \
  --video /path/to/match.mp4 \
  --out-dir ../reports/video_driven/p1p2_r2/out \
  --max-coarse-frames 36 --max-dense-extra 12 \
  --confirm-hits 3 --establish-hits 3 --no-roi-evidence
```

## Results

### Unit / synthetic

| Case | Result |
|------|--------|
| Full-span 8000s × 80 frames | covers end (`fullspan=true`) |
| Clock `44:46` | rejected as clock |
| Synth comeback MP4 | `0:0→0:1→1:1→2:1`, **grade=story** |
| Neg black video | **grade=unresolved**, degraded |
| Degraded timeline | P2 → **unresolved** (not `none`) |

### Real short clips (dev data, not holdout)

| Clip | usable OCR rate | nodes | discovery | note |
|------|-----------------|-------|-----------|------|
| Croatia 60s @~2-1 | ~0.09–0.44 (varies) | 0 established | unresolved | scoreboard often detected; digits unstable |
| UAE 60s @0-0 | (see run dir) | — | unresolved expected | colon clocks dominate |
| France 60s @0-1 | (see run dir) | — | unresolved expected | `0 V 1` hard for tesseract |

### Real full match (Croatia, 36 coarse + densify)

| Metric | Value |
|--------|-------|
| Duration | ~8034 s |
| Samples | 48 (fullspan **true**, first=0, last≈8034) |
| Scoreboard detect rate | ~0.40 |
| Usable score obs rate | ~0.04 |
| Score nodes | **0** |
| degraded | **true** (`empty_score_path`, `initial_unestablished`, `low_usable_ocr_rate`) |
| discovery_grade | **unresolved** |
| Evidence task | `improve_score_perception` |
| Elapsed | ~271 s CPU; OCR ~226 s / 437 calls |
| render_ready | false |

**Verdict:** Architecture + abstention gates work; **local tesseract is not yet reliable enough on broadcast scorebugs to support T01 story discovery on real matches.** Do not start P3 until usable score-obs rate / established paths improve.

## Failure taxonomy (with evidence)

| Type | Example | Handling now |
|------|---------|----------------|
| Match clock as score | `44:46`, `15:52` | classified clock → not committed |
| Digit OCR garbage | `1:7`, `9:8` on Croatia clip | multi-frame establish fails → empty path |
| Seek/compress blur | bottom `CROATIA 2…1` → `CROATIA >: &` | prefer abstain |
| Opening bumper | t≈0 non-score graphics | no forced 0:0 |
| Perception insufficient | full Croatia run | P2=`unresolved`, not `no_comeback` |

ROI evidence screenshots (when enabled): `roi_evidence/` under run dirs.

## Offline eval note

events/causal JSON may be used **after** runs for recall comparison only; video-only path does not read them.

## Next (gate for P3)

P3 only after ≥1 real full match yields:
- established score path with plausible plus-one steps, and
- usable_score_obs_rate clearly above noise (target explore: ≥0.25 with confirm), and
- T01 candidate/story on a known comeback without match-specific hardcoding.

Likely work: scorebug detector (template/color), digit classifier, multi-frame tracked ROI, optional light local detector — still no paid API.
