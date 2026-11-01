# STORY_VA_V2 G2 — Implementation Report

## Code delivered

| File | Role |
|------|------|
| `v2_video_evidence_gate.py` | Fail-closed upgrade gate (identity, PTS order, continuous clip+frames, semantic class) |
| `v2_generic_edl_composer.py` | Uses gate — status-only `verified_first_live` no longer upgrades |
| `v2_g2_video_evidence.py` | Zero-API search plan + ffmpeg continuous clips/frames/evidence index |
| `v2_g2_video_evidence_cli.py` | Production entry (`--real` aborted) |
| `test_v2_g2_video_evidence_gate.py` | Anti-cases: fake status, wrong match, replay, inverted/OOR PTS, stitch, scoreboard-only |

## Tests

```bash
PYTHONPATH=10.27scasual_chain/algo \
  python3 -m unittest \
  story_video_agent.test_v2_g2_video_evidence_gate \
  story_video_agent.test_v2_g1_cross_match_integration -q
```

**24 OK** (G2 gate + G1 regression).

## Runs

| Match | Out dir | Pack | Verified | Clips | API |
|-------|---------|------|----------|-------|-----|
| A 阿联酋–阿曼 | `/data2/lpy1/_story_va_outputs/v2/cross_match_g2/A_uae_oman/` | READY | 0 | 21 | 0 |
| B 塞尔塔末弧 | `/data2/lpy1/_story_va_outputs/v2/cross_match_g2/B_osasuna_celta/` | READY (frozen transfer) | 0 | 21 | 0 |

Large MP4/JPG stay on server (not git).

## Honesty

- Evidence pack ≠ video verified.
- `render_ready=false` everywhere.
- No paid API, no causal/gold, no Croatia cache, no formal long story render.
