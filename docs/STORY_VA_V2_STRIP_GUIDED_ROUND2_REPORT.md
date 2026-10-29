# Story Video Agent V2 — Strip-Guided Round 2

**Baseline:** `story-va-video-driven@a2a5188`  
**V1 freeze / standalone 8.31:** unchanged  
**render_ready:** `false`

## Goal

Recover missing Goals from scoreboard transitions + video evidence, emit `source=video_agent_inferred` events, re-run causal_chain6 (A/B), rebuild story — without gold / V1 times / production retune.

## What shipped

| Module | Role |
|--|--|
| `v2_missing_goal_detector.py` | Score trajectory → `missing_goal_candidate` |
| `v2_enhanced_events.py` | Verified inferred Goals; never overwrite original JSON |
| `v2_strip_reinfer.py` | Production AlgoStripAdapter A/B + compare |
| `v2_goal_recovery_agent.py` | Coarse→fine search planner (LLM or rule) |
| `v2_goal_recovery_runner.py` | Full Round 2 orchestration |
| `v2_strip_guided_r2_cli.py` | CLI entry |
| `test_v2_strip_guided_r2.py` | Offline/mock unit tests |

Forbidden inputs (`*_causal.json`, `strip_gold`, V1 roles, hardcoded match times) stay out of prompts and recovery.

## Croatia — detector (events-only)

Artifacts: `_story_va_outputs/v2/strip_guided/croatia_r2_20261029_143652/`

| Item | Result |
|--|--|
| Missing candidates | **4** |
| Covered by existing Goal | 3:1→4:1 near `event_000153` @ 7747s |
| `mg_initial_deficit_0` | first board `0:1` @ 1079.06s, no 0:0 |
| `mg_trans_1` | 0:1→1:1 @ 3145.98s |
| `mg_trans_2` | 1:1→2:1 @ 3697.35s |
| `mg_trans_3` | 2:1→3:1 @ 6479.08s (replay/sub confirmation) |

Search regions are adaptive gaps between score observations (phases), **not** fixed −90/−150s. Confirmation time ≠ action time.

## Video recovery (real API)

Configured VLM `Qwen3.6-Plus` / prior DeepSeek planner IDs currently return **HTTP 400 Invalid model name** (or auth disconnect) for this key, despite appearing in `/v1/models`.  

**This round: 0 video-verified inferred Goals.** Failures kept unresolved; no keyword-only upgrades.

Skip-video run completed: detector + strip A=B=62, `n_inferred_verified=0`.

## Enhanced events + strip A/B

- Original `events.json` untouched.
- Verified inferred events would merge as `source=video_agent_inferred` only when `grade=action_localized` + shot∧net + not pure replay.

### Offline closed-loop probe (NOT video)

Injected one score-region midpoint Goal tagged `offline_probe_not_video` for equalizer candidate:

- Strip geometry **did** absorb the Goal (`event_keys` include `goal` in new special chains).
- Classifier still emitted `throw_in_build_up_chain`, **not** `outcome` (production margin/template behavior unchanged).
- Outcome count stayed **1** (late original Goal only).

So: recovery pipeline can feed 8.31; **outcome labeling may still fail under frozen production rules** even after Goal injection.

## Story rebuild

With 0 verified recoveries: beats/relations from score path + strip B; temporal=rule; narrative only for deficit→lead score path; **no causal from score order**. `render_ready=false`.

## Acceptance checklist

| Check | Status |
|--|--|
| Find four missing Goal candidates | **Yes** (4) |
| Video-localize real actions | **Blocked** (VLM model access) |
| Traceable enhanced events | Schema ready; **0** verified this round |
| 8.31 more complete strips via enhanced events | Probe: events enter chains; outcome template still weak |
| False fill / replay dupes | None emitted as verified |
| Stronger global story | Score-path candidate only; no verified clips |

## Ready for Story Graph / auto-edit?

**Not yet.** Need working VLM access + verified localized Goals; then reassess whether production strip classify yields usable outcome chains without param changes.

## Tests

```bash
PYTHONPATH=10.27scasual_chain/algo python3 -m unittest \
  story_video_agent.test_v2_strip_guided_r2 -v
```
