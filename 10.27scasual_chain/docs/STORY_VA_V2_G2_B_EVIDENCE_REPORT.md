# STORY_VA_V2 G2 — Match B Evidence Report（奥萨苏纳 vs 塞尔塔）

**Status:** `ok_evidence_pack` under **frozen** G2 code (fingerprint hashes unchanged vs pre-B)  
**Zero-modification transfer:** only `--match-id/--video/--events/--g1-dir/--out-dir` changed  
**API:** 0 · **render_ready:** false · **n_video_verified:** 0

## Inputs

| Item | Path |
|------|------|
| Video | `/mnt/data4/migu/10月27日 25-26赛季西甲第10轮 奥萨苏纳VS塞尔塔 国语.mp4` |
| Events | `.../交付_out/10月27日_25-26赛季西甲第10轮_奥萨苏纳VS塞尔塔_国语.json` |
| G1 dir | `/data2/lpy1/_story_va_outputs/v2/cross_match_g1/B_osasuna_celta/` |
| Out | `/data2/lpy1/_story_va_outputs/v2/cross_match_g2/B_osasuna_celta/` |

## Selected last-arc (right / 塞尔塔维戈)

| Role | Board transition targeted | score_confirmation_sec | Primary continuous clip |
|------|---------------------------|------------------------|-------------------------|
| opening_deficit | arc deficit board **2:1** @3199.66 | 3199.66 | `.../roles/opening_deficit/clips/opening_deficit_late_third_clip_source_continuous.mp4` (3162.66–3202.66) |
| equalizer | **2:1→2:2** | 5712.01 | `.../equalizer/clips/equalizer_late_third_clip_source_continuous.mp4` (5675.01–5715.01) |
| go_ahead | **2:2→2:3** | 6881.94 | `.../go_ahead/clips/go_ahead_late_third_clip_source_continuous.mp4` (6844.94–6884.94) |

G1 non-arc transitions (0:1 / 1:1 early) were **not** used as the three core last-arc goals.

**Note:** `score_before` metadata on opening_deficit may show `[0,0]` as search-floor bookkeeping; the exported primary window is anchored on **2:1 confirmation @3199.66** for the selected right arc.

## Verification

- `semantic_status`: **NOT_VERIFIED**
- All roles: `unresolved` / `pending_human_video_review`
- **21** watchable continuous clips; no stitch; no verified upgrade
- Elapsed ~1008s · API=0
