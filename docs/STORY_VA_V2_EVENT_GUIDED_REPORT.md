# Story Video Agent V2 — Event-Guided Multimodal (Round 1)

**Baseline:** `story-va-video-driven@08f0ef0` (Phase C-1)  
**V1 freeze:** Tag `story-va-v1.0-structured-baseline` @ `462ea11` (unchanged)  
**Mode:** Event-Guided Multimodal Story Agent (new; does **not** replace Phase A/B/C-1)  
**render_ready:** `false` (no Story Graph / auto-render gate)

## Route change

| | Video-only (A/B/C-1) | Event-Guided (this round) |
|--|--|--|
| Input | MP4 only | MP4 + events.json |
| Forbidden as model input | causal / roles already avoided | **causal.json, story roles, causal edges, pre-made story structure** |
| Anchors | scoreboard OCR / sparse search | event media times + Score_Recognition |
| Planner | DeepSeek discovers T01 | DeepSeek invents beats + temporal/causal/narrative relations |
| Verifier | Qwen windows | Qwen dense / live-replay near event anchors |
| Gold / causal | offline only | offline only (post-inference) |

**input_source:** `human_corrected` | `upstream_detected` (adapter tag only; same whitelist).

## Deliverables

| Module | Role |
|--|--|
| `v2_event_adapter.py` | Whitelist Event Input Adapter → `v2_standard_event_v1` |
| `v2_event_guided_{memory,agent,runner,cli,eval}.py` | Discovery + verify loop + offline eval |
| `test_v2_event_guided.py` | Adapter / override / mock runner |
| Phase A/B/C-1 CLIs | Unchanged entrypoints |

### Whitelist (kept)

`event_id`, `event_type`(+zh/id), `media_time`, `video_context.{broadcast_phase,is_replay,is_slow_motion}`, attributes: `Score_Recognition`, `Related_Player`, `Body_Part`, `Goal_Type`, `Match_Phase`, `Pitch_Area`, `Shot_Type_Camera_Angle`.

### Stripped

Annotation quality `scores.*`, criticality/emotion, any causal/story/role/chain/narrative keys. Payload with top-level `causal_chains` is refused.

## Croatia real API (canonical)

- **Video:** `/mnt/data4/migu/2022-11-28 克罗地亚vs加拿大.mp4`
- **Events:** `data/交付_out/2022-11-28 克罗地亚vs加拿大.json` (`input_source=human_corrected`, 159 kept)
- **Out:** `/data2/lpy1/_story_va_outputs/v2/event_guided/croatia_eg_20261028_182542` (`_latest` → this)
- **Offline gold:** `reports/phase5/croatia/story_graph.json` (action windows only, after inference)
- **Offline causal meta:** `*_causal.json` counts only (not model input)

### Results

| Metric | Value |
|--|--|
| discovery_status | **story_candidate** |
| score changes | 4 (0:1→1:1→2:1→3:1→4:1) |
| inferred beats | setup=`event_000004`, turning=`event_000068`, climax=`event_000076`, resolution=`event_000119`/`event_000154` |
| inferred relations | 4 (temporal / causal / narrative — model-invented) |
| Qwen grades | action_localized×4, action_corroborated×4, goal_candidate×1, scoreboard_only×1 |
| action recall (pad=90s) | **0.6** (3/5 gold action windows) |
| frames | 70 / 72 |
| real HTTP | 11 (10 vision + 1 planner) |
| tokens | ~168.7k |
| **est_cost_usd_real** | **~$0.0273** |
| elapsed | ~238s |
| render_ready | false |

Hits: opening (~30s), equalizer (~11s), lead-extend (~87s).  
Misses: go-ahead (Score_Recognition lag ~149s on Shot@3697 vs gold~3522); approach segment near same extend.

### Prior aborted / learning runs (same day)

| Run | Note | Cost |
|--|--|--|
| `...180622` | env `STORY_API_MAX_CALLS=3` truncated | ~$0.005 |
| `...180915` | full verify; LLM wrongly said `no_comeback`; shallow lookback; recall 0 @25s pad / 0.4 @90s | ~$0.027 |

Mitigations shipped: deeper lookback for weak/replay types; independent `score_anchor_deficit_to_lead` override; T01 prompt clarification; eval center pad 90s.

## Tests

```bash
PYTHONPATH=10.27scasual_chain/algo python3 -m unittest story_video_agent.test_v2_event_guided -v
```

## How to run

```bash
source 10.27scasual_chain/_local_render/phase4a_paratera.env
# raise/unset smoke caps if env has STORY_API_MAX_CALLS=3
export STORY_API_ENABLE=1 STORY_API_SMOKE=1
export STORY_API_MAX_CALLS=28 STORY_API_MAX_COST_USD=2.0
PYTHONPATH=10.27scasual_chain/algo python3 -m story_video_agent.v2_event_guided_cli \
  --video ... --events ... --out-dir ... \
  --input-source human_corrected --real \
  --gold-story-graph ... --causal-offline ...
```

Phase A/B/C-1 remain: `v2_phase_a_cli` / `v2_phase_b_cli` / `v2_phase_c1_cli`.

## Decision gate (next)

Round 1 supports continuing toward **Story Graph + auto-edit** only after review of:

1. Action completeness vs independent gold (0.6 recall — improve lag handling / multi-hypothesis lookback).
2. Visual verification quality (grades already much stronger than C-1 video-only 0/3).
3. Autonomous relation quality (human review of 4 inferred edges; causal.json not used in-loop).

**Not started:** C-2 Story Graph, Phase D render, live `upstream_detected` wiring beyond the adapter flag.
