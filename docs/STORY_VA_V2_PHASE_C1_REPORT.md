# Story Video Agent V2 — Phase C-1 Report

**Branch:** `story-va-video-driven`  
**Phase B freeze:** `5629c00` + `/data2/lpy1/_story_va_outputs/v2/phase_b/_frozen/PHASE_B_FREEZE.json`  
**`render_ready`:** false  

## Fixes from Phase B

- Removed match-specific `0-1` / `1-1` / `2-1` and narrative-keyword promotion in `v2_phase_b_agent.py`.
- Added `v2_score_transitions.py`: parse generic score pairs; detect deficit → level → lead-after-deficit for **any** scores/sides.
- `independent_discovery_check` demotes LLM self-reported `story_candidate` when score evidence is weaker.
- Localization eval **no longer** treats large-window overlap as action success.

## C-1 system

Pipeline: Phase B candidate/observations → task board (`locate_*_goal`, `verify_final_result`) →  
`coarse_search` → `refine_window` → `dense_action_inspect` → independent `grade_localization`.

Grades: `scoreboard_only` | `goal_candidate` | `action_localized` | `action_corroborated` | `unresolved`.

Outputs: `story_evidence_tasks.json`, `localized_events.json`, `story_evidence.json`, `agent_trace.json`, `search_coverage.json`, `localization_eval.json`, `review_frames.json`.

## Experiments

### 1) Short-window localization smoke — DONE

- Run: `/data2/lpy1/_story_va_outputs/v2/phase_c1/win90_loc_20261028_172054`
- Clip: 90s @ abs offset 3020 (equalizer neighborhood). Wall ~264s, 22 frames, 9 real API ok, est ~$0.013.
- Planner all `llm`: coarse deficit → coarse equalizer → dense go_ahead → verify → finish.
- Tasks: 3× `candidate_found`, 0 verified.
- Offline eval (strict): **candidate_recall 1/3**, **action_localization_recall 0/3**.
  - Equalizer: center error **~4.1s**, grade `goal_candidate` (not upgraded to action_*).
  - Deficit/go_ahead not in this clip → expected misses; go_ahead dense hit was false neighborhood.
- Honest: loop works; **scoreboard/near-window ≠ action_corroborated**.

### 2) Reuse Phase B Croatia full candidate — DONE (rerun)

- Failed first attempt `croatia_full_c1_20261028_172550` (kept): noisy other-match scores + oversized coarse window → early abort. Recall 0/3.
- Successful budgeted rerun: `/data2/lpy1/_story_va_outputs/v2/phase_c1/croatia_full_c1_20261028_173514`
- Wall ~477s, frames 46, API 17 ok / 0 fail, est ~$0.028, all 10 planner steps `llm`.
- Discovery check: `story_candidate` (not demoted) after filtering highlight-insert scores.
- Task board end: 3× `candidate_found`, 1× `verified` (final scoreboard), 0 unresolved.
- Agent produced several `action_localized` grades near seeded score-change neighborhoods.
- **Strict offline eval vs V1 live goal nodes:** candidate_recall **1/3**, action_localization_recall **0/3**.
  - go_ahead: center error ~22.6s (candidate-tol hit @60s; not ≤8s action hit).
  - equalizer: ~235s off (scoreboard neighborhood ≠ gold action ~3054s).
  - deficit: ~1417s off (seeded near 2400 scoreboard state; gold action ~968s).
- Honest verdict: C-1 **loop + grades + task states work**, and go_ahead was roughly near; **system still does not reliably localize live goal actions** from Phase B scoreboard seeds alone. Do not claim C-1 acceptance for action-level editing yet.

## Honest limits

- `action_corroborated` ≠ production semantic authorization.
- Dense samples still cannot invent unobserved contacts.
- Score-change media time ≠ goal-action media time; seeds must be refined with action search, not trusted as gold.
- Dev matches ≠ unseen generalization.
- SHA / push recorded after this report update.
