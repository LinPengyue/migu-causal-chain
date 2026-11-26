# R4/R5.4a — A turnover_to_goal:1 initial render + continuous observe clip

- Freeze: `db36d19`
- Story: `turnover_to_goal:1`
- Mode: **render-only** (`http_calls=0`, no paid P1)
- No R1–R3 rebuild; no keeper rerun; algo unchanged

## Task 1 — original R3 initial story render

```bash
python run_r3_original_agent.py \
  --pack artifacts/v3r_critic_adapter_preflight/A_turnover_to_goal \
  --evidence "$A_EV" --events "$A_EVENTS" \
  --match-json "$A_ORIGINAL_MATCH_JSON" --source "$A_ORIGINAL_MP4" \
  --source-manifest "$A_SOURCE_MANIFEST" \
  --original-algo ../../11.20sstory_chain/algo --allow-dev \
  --out-dir artifacts/v3r_original_agent_A_turnover_to_goal_r4r5_4a
```

| item | value |
|---|---|
| status | `RENDERED_ONLY` |
| path | `/data2/lpy1/worktrees/migu-sportscausal-template-gen/research/sportscausal/artifacts/v3r_original_agent_A_turnover_to_goal_r4r5_4a/initial_render/story_clean.mp4` |
| sha256 | `6b60cafd26fee9d321d97b08a849afa14edbf014beeca105d785a3b51793c618` |
| ffprobe duration | **23.731s** (EDL window sum 23.542s; alignment 23.731s) |
| segments | 5 |

EDL windows:

| seg | media_in–out | dur | events |
|---|---|---:|---|
| seg:1 | 6810.160–6824.070 | 13.910 | event_000668, event_000669 |
| seg:2 | 6829.010–6831.010 | 2.000 | atom_fill_0100_Pass |
| seg:3 | 6831.837–6833.837 | 2.000 | atom_fill_0101_aerial |
| seg:4 | 6836.608–6838.608 | 2.000 | atom_fill_0102_Assist |
| seg:5 | 6841.456–6845.088 | 3.632 | atom_fill_0103_Shot, atom_fill_0104_Goal |

## Task 2 — continuous source observe clip

Interval **[6810.160, 6845.088]** from original match MP4 (human observe only; does **not** modify formal EDL).

| item | value |
|---|---|
| path | `artifacts/v3r_original_agent_A_turnover_to_goal_r4r5_4a/human_observe_continuous_clip/source_continuous_6810p160_6845p088.mp4` |
| sha256 | `601efaf75a07d440e36a0d6f7424c2772dea05bd13a3a8842c2c77dc9f85d01c` |
| requested duration | **34.928s** |
| ffprobe duration | **34.960s** |

## Task 3 — structural checks (annotation-backed; still watch both videos)

### Ball-possession / continuity breaks in EDL
EDL **omits** 11.386s of source time across 4 gaps:

| after → before | gap_sec | omitted source |
|---|---:|---|
| seg:1 → seg:2 | 4.940 | [6824.070, 6829.010] |
| seg:2 → seg:3 | 0.827 | [6831.010, 6831.837] |
| seg:3 → seg:4 | 2.771 | [6833.837, 6836.608] |
| seg:4 → seg:5 | 2.848 | [6838.608, 6841.456] |

These gaps are exactly why the continuous clip (~34.9s) is longer than the 23.5s story cut. Use the continuous clip to judge whether possession / link play feels interrupted in the official cut.

### Replay / slow-mo
- On **EDL-bound** events: annotated `is_replay` / `is_slow_motion` = **False** (all listed LIVE in `video_context` for the 7 EDL event ids).
- Any event overlapping continuous window with replay/slow-mo: **0** hits.
- Non-LIVE `broadcast_phase` in window: **0**.

### Match transitions
`ignore_segments` overlapping [6810.160, 6845.088]: **1** (see `observe_manifest.json`).

### Goal-action completeness
- Shot media_time end **6843.456**; Goal **[6843.088, 6845.088]**; EDL seg:5 **[6841.456, 6845.088]**.
- Pre-shot gap **2.848s** after Assist is dropped from EDL; continuous clip retains it. Human should compare whether the strike→goal reads incomplete in the 23.5s cut.

## Files
- `report.json`, `render_manifest.json`, `input_provenance.json`
- `observe_manifest.json` (gaps, event contexts, hashes)
- MP4s on disk only (gitignored)

No quality / FIRST_LIVE / release claim.
