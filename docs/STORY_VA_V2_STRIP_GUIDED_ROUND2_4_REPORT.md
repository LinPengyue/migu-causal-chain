# Story VA V2 — Strip-Guided Round 2.4 Report

## Verdict

Round 2.4 closes the **Qwen observation → Memory → DeepSeek reselect** loop and produces a tighter T01 candidate: **5 verified goals + 4 live-supported non-goal strips** (down from 8), with removals driven by video evidence (replay / unresolved observation), not by a fixed strip quota.

Primary artifacts:

`/data2/lpy1/_story_va_outputs/v2/strip_guided/croatia_r2_4_20261029_192839/`

## Task results

### 1) Strip video audit
`strip_video_review.json` covers the R2.3 eight strips. Predicted labels were **not** upgraded to verified.

Keep (live, supports prior): clip24, clip45, clip46, clip58.  
Drop (replay): clip31.  
Unresolved (frame budget): clip50, clip44, clip49.

### 2) Observation feedback loop
- `V2R24StoryMemory.planner_view()` exposes `strip_observations`, pending reviews, and change log.
- Tools include `unselect_node`; finish is blocked while drop-recommended strips remain selected.
- `story_planner_trace.json` / `story_selection_changes.json` record evidence-linked unselects that alter Story Graph & EDL.

### 3) Global planning
DeepSeek reassessed after observations; did not preserve eight strips. Kept only observation-supported context strips.

### 4) EDL
`candidate_edl.json` defines both `source_media_order` and `narrative_order` (`prefer_match_timeline` for T01). No unconditional overwrite of planner beats by silent re-labeling.

### 5) Candidate videos
`story_clean_candidate.mp4` / `story_qc_candidate.mp4` generated; `render_ready=false`.

## vs R2.3
See `story_quality_comparison.md` in the run directory.

## API / cost (estimate)
~31 HTTP attempts, ~$0.048 (vision + planner). Goals reused R2.3 cache (no re-verify).

## Constraints honored
No gold/V1 times; no 8.31 production edits; no cross-match expansion; five verified goals preserved.

## Git
Commit SHA filled at commit time.
