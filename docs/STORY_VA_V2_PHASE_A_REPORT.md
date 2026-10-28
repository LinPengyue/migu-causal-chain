# Story Video Agent V2 — Phase A Report

**Branch:** `story-va-video-driven`  
**Base:** `8d303fd`  
**Run dir:** `/data2/lpy1/_story_va_outputs/v2/phase_a/croatia_60s_compare_20261028_162740`  
**Clip (dev only):** `/tmp/migu_vd_clips/croatia_2_1_60s.mp4` (~60.8s)  
**Gates:** `STORY_API_ENABLE=1` + `STORY_API_SMOKE=1` + `--real`; no `events.json` / `causal.json`  
**`render_ready`:** false  

## 1. Reuse audit (Video-RSI ↔ migu)

| Video-RSI Initial Harness | V2 reuse / adaptation |
|---|---|
| `agent.decide` tool/answer loop | `v2_phase_a_agent.V2PhaseAAgent` (DeepSeek planner) |
| `tools.overview/scan/inspect` | `v2_rsi_toolbox.V2RSIToolbox` (+ `read_scoreboard_window`) |
| Memory of observations | `v2_story_memory.V2StoryMemory` → `story_evidence.json` |
| DeepSeek + Qwen services | Existing `ApiProvider` dual roles (`planner` / `vision`) |
| Frame extract | Existing `FrameStore` / `VisionProvider` |

Not reused: MCQ answer path, Editor/Gate/Harness evolution, RSI training.

## 2. Acceptance: planner chose next search from Qwen

Path B (`multi_round_planner`), all three planner steps `llm`:

1. DeepSeek → `overview`
2. Qwen real: fans celebrating + scoreboard Croatia 2–1 Canada / Davies & Kramaric banners
3. DeepSeek → `read_scoreboard_window` `{start:13, end:29}` (**not** the rule fallback `inspect_interval`)
4. Qwen real: corroborating scoreboard + Livaja 44' banner + live indicator
5. DeepSeek → `answer` / finish with structured hypothesis + uncertainties

Evidence memory updated after each tool; times bound to tool windows / `frame_ids`.

## 3. A vs B (same clip, separate API counters)

| Metric | A fixed-frame | B multi-round |
|---|---|---|
| Elapsed | 48.6s | 406.5s |
| Observations | 1 | 2 |
| Candidate events | 3 | 8 |
| Real API ok / fail | 1 / 0 | 5 / 1 (1 planner timeout, retried) |
| Total tokens (reported) | 11294 | 30370 |
| Est. cost USD (local prices ≠ invoice) | ~0.0029 | ~0.0089 |
| Planner modes | n/a | `llm, llm, llm` |
| Traceability | Single window | overview → local scoreboard → finish |

**Verdict (honest):** On this short clip, **B is better for traceability and corroboration** (second window + explicit hypothesis/uncertainties). Fixed path already saw the 2–1 scoreboard in one Qwen pass, so B is **not** a large discovery-coverage win here; cost/latency are higher. Do **not** claim full-match autonomous T01 discovery from this run.

## 4. Failures / unresolved

- DeepSeek reasoning can be slow; one planner read timeout (~150s) then retry OK.
- Observations ≠ fact verification; no on-pitch goal action isolated—only graphics / fan celebration.
- Scoreboard chronology ≠ proven live causality (recorded in hypothesis uncertainties).
- Early smoke runs failed when `STORY_API_MAX_COMPLETION_TOKENS=256` hard-blocked after reasoning tokens; softened hard-block unless truncated/empty (opt-in `STORY_API_HARD_BLOCK_ON_OUTPUT_BUDGET=1`).
- HEVC trailer seeks need ~1s end margin (`frames.py` / toolbox).

## 5. Commands

```bash
# mock unit
cd /tmp/migu-va2c/10.27scasual_chain/algo
PYTHONPATH=. python -m unittest story_video_agent.test_v2_phase_a -v

# real compare (billable)
set -a; source .../_local_render/phase4a_paratera.env; set +a
export STORY_API_ENABLE=1 STORY_API_SMOKE=1
export STORY_API_MAX_COMPLETION_TOKENS=8192 STORY_API_MAX_CALLS=12
export STORY_LLM_TIMEOUT_SEC=150
PYTHONPATH=. python -m story_video_agent.v2_phase_a_cli \
  --video /tmp/migu_vd_clips/croatia_2_1_60s.mp4 \
  --out-dir /data2/lpy1/_story_va_outputs/v2/phase_a/<run> \
  --mode compare --real --max-steps 4 --frame-budget 12 \
  --fixed-frames 4 --max-api-calls 12 --max-cost-usd 0.35 \
  --max-completion-tokens 8192
```

Artifacts: `path_*/story_evidence.json`, `path_*/agent_trace.json`, `compare_summary.json`, `phase_a_report.json`.

## 6. Next (Phase B — not claimed done)

Full-match MP4, no preset goal times; autonomous T01 evidence tasks; still no render until semantic verification policy.
