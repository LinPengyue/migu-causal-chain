# Story Video Agent V2 — Strip-Guided Round 2.1

**Baseline:** `story-va-video-driven@efdf81a`  
**V1 / standalone 8.31 / production strip params:** frozen  
**render_ready:** `false`

## Scope

Fix real VLM usability gating + goal evidence timing. Single missing-goal attempt only (`mg_trans_2`, 1:1→2:1). No new story framework.

## Task 1 — VLM preflight

New module: `v2_api_preflight.py` (+ CLI gate in `v2_strip_guided_r2_1_cli.py`).

| Check | Result |
|--|--|
| `/v1/models` | HTTP 200, **`data: []` (0 models)** for current key |
| Env Planner `DeepSeek-V4-Pro-0813` | HTTP **400 Invalid model name** |
| Env Vision `Qwen3.6-Plus` | HTTP **400 Invalid model name** |
| Auth | Not 401/403; catalog empty ⇒ **key has no usable model access** |
| Diagnosis | Non-retryable invalid-model / empty catalog — **not** request-format bug for minimal text/image probes |

Preflight **fails closed** before any story search loop. Artifact:

`_story_va_outputs/v2/strip_guided/croatia_r2_1_20261029_151013/mg_trans_2/api_preflight.json`

```
vision: model=Qwen3.6-Plus http=400 invalid_model=True cause=api_key_has_empty_model_catalog
```

Fatal 400/401/403 also abort mid-loop if vision returns degraded invalid-model (no retry storm).

## Task 2 — Goal evidence / time localization

Updated:

- `v2_event_guided_evidence.py` — `localize_goal_action_times`, `merge_action_evidence_windows`
- `v2_enhanced_events.py` — emit requires resolved shot+result frame times
- `v2_goal_recovery_runner.py` — uses **goal_result.media_sec** as event time; edit window from shot/result pads

Distinguished fields:

1. `observation_window` — search sample span  
2. `shot_action.{frame_id,media_sec}`  
3. `goal_result.{frame_id,media_sec}`  
4. `edit_window` — candidate cut around action times  

**Forbidden:** observation-window midpoint as goal time.  
**Gate:** keyword-only or unbound frame cites ⇒ stay unresolved / `goal_candidate`.

Unit tests: `test_v2_strip_guided_r2_1.py` (all pass).

## Task 3 — Single candidate `mg_trans_2`

Chosen for clear score change 1:1→2:1 with previous observation time and Shot-typed confirmation cue (search constraint from Round 2 detector — no gold times).

Real run: **aborted at preflight** (0 vision calls in search loop). No hand-filled Goal.

## Task 4 — Strip A/B closed loop

Not reached (no verified inferred Goal). Impact reporter `analyze_inferred_in_strip_b` is in place: keeps video-verified Goals as **story node candidates** even if strip template ≠ outcome.

## Deliverables

| Item | Status |
|--|--|
| VLM preflight result | ✓ failed closed, artifact written |
| Single Goal video evidence | ✗ blocked by empty model catalog |
| Action time + edit window | ✓ code path; no real evidence this round |
| Inferred Goal event | 0 |
| Strip A/B | not re-run (no enhanced Goal) |
| Report | this file |
| Git SHA | see commit after push |

## Next (only after VLM access restored)

1. Re-run preflight until planner/vision probes return non-empty content.  
2. Re-run `v2_strip_guided_r2_1_cli --candidate-id mg_trans_2 --real`.  
3. If verified, inspect `inferred_goal_strip_impact.json` for timeline/chain/outcome vs story-node retention.  
4. Only then expand to the other three missing Goals.
