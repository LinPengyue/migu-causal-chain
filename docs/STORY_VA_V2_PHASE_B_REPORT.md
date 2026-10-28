# Story Video Agent V2 — Phase B Report

**Branch:** `story-va-video-driven`  
**Base:** Phase A `514b56c`  
**`render_ready`:** false  

## Scope

Full-match / long-segment **autonomous T01 discovery** (video-only). No MP4 render. No events/causal as inference input. Offline labels used only post-hoc.

## Phase A leftovers addressed

| Item | Fix |
|---|---|
| A fairer budget compare | Compare runs **multi first**, then fixed baseline with **matched `frames_used`**; API tokens reported separately (planner extra cost explicit). |
| B candidate inflation | `evidence_items` + time-bin/role/team **dedupe**; statuses observed/hypothesized/unresolved/failed + verification_status. |
| C checked intervals | Coverage records: requested / sampled / observed / failed; sparse overview ≠ partition observed. |
| D planner latency | Opt-in `STORY_*_REQUEST_PROFILE=video_rsi` (`thinking={type:disabled}`), higher timeout/completion caps, soft output-budget block; timeouts still logged. |

## Architecture (hierarchical)

`global_overview` → `partition_scan` → `localize_event` / `read_scoreboard_window` → `verify_evidence`

Outputs: `story_discovery.json`, `story_evidence.json`, `story_evidence_tasks.json`, `search_coverage.json`, `agent_trace.json`, `run_manifest.json`.

## Experiments

### Mid-tier (10–20 min continuous) — DONE

- Clip: `/tmp/migu_vd_clips/croatia_seg15m_a.mp4` (900s; absolute offset **2880s**).
- Run: `/data2/lpy1/_story_va_outputs/v2/phase_b/croatia_seg15m_compare_20261028_165241`
- Wall ~264s. Multi: 231.7s, 18 frames, 8 real API ok / 0 fail, est ~$0.009; Fixed matched: 31.2s, 18 frames, est ~$0.006.
- Planner path: `global_overview` → `partition_scan`×3 (0–300, 300–600, 600–900) → last-step **rule** `unresolved` (no `story_candidate`).
- Offline window-overlap recall @120s: **2/2** for both A and B (equalizer+go_ahead). **Caveat:** full-partition scans trivially overlap labels; this is coverage proximity, **not** goal localization success.
- Honest verdict: hierarchical search worked and visited all partitions, but agent did **not** autonomously assert a T01 story on this budget; discovery_status=`unresolved`.

### Full match (video-only) — DONE

- Source: `/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4` (~8035s).
- Run: `/data2/lpy1/_story_va_outputs/v2/phase_b/croatia_full_multi_20261028_165906`
- Wall ~659s (~11 min). Frames 36/40. API 15 ok / 1 fail. Tokens ~115k. Est. cost ~$0.019 (≠ invoice).
- Planner modes: **all 8 steps `llm`**.
- Path: `global_overview` → partition scans (2400–3000, 3300–3900, 3900–4800, 4800–5400) → `localize_event`×2 → finish **`story_candidate`** (evidence cues: deficit/level/lead from visible scoreboards 0-1 → 1-1 → 2-1).
- Coverage: partitions observed 4 / untouched 3 / overview_sparse_only 6; fraction_observed **0.29** (sparse non-coverage remains unknown).
- Offline label window-overlap @180s: **3/3** (deficit/equalizer/go_ahead). Caveat: partition overlap ≠ precise goal-action localization; localize windows were near but not proven live goal strikes.
- Honest verdict: **video-only agent produced an evidence-backed T01 `story_candidate` without events/causal input**. Not Phase C evidence-chain complete; not render-ready; not unseen-match generalization.

## Honest evaluation rules

- Do not use evidence_item counts as correctness.
- Sparse non-discovery ≠ proven `no_comeback`.
- Dev matches are **not** unseen generalization.

## Commands

```bash
cd /tmp/migu-va2c/10.27scasual_chain/algo
PYTHONPATH=. python -m unittest story_video_agent.test_v2_phase_b -v

# real mid compare
set -a; source .../phase4a_paratera.env; set +a
export STORY_API_ENABLE=1 STORY_API_SMOKE=1
export STORY_PLANNER_REQUEST_PROFILE=video_rsi STORY_VLM_REQUEST_PROFILE=video_rsi
export STORY_API_MAX_COMPLETION_TOKENS=8192 STORY_LLM_TIMEOUT_SEC=180
PYTHONPATH=. python -m story_video_agent.v2_phase_b_cli \
  --video /tmp/migu_vd_clips/croatia_seg15m_a.mp4 \
  --out-dir /data2/lpy1/_story_va_outputs/v2/phase_b/<run> \
  --mode compare --real --max-steps 5 --frame-budget 20 --partition-sec 300

PYTHONPATH=. python -m story_video_agent.v2_phase_b_eval \
  --run-dir <run>/path_b_multi --media-offset-sec 2880 --tol-sec 120
```

## Next

Phase C only after Phase B shows evidence-backed T01 discovery (or honest unresolved with coverage).
