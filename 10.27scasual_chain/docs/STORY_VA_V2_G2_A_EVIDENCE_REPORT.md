# STORY_VA_V2 G2 — Match A Evidence Report（阿联酋 vs 阿曼）

**Gate:** `G2_A_EVIDENCE_PACK_READY`  
**Not claimed:** `automated_video_verified` / `verified_first_live` / deliverable story MP4  
**API:** 0 · **render_ready:** false · **unresolved core roles:** 3

## Inputs

| Item | Path |
|------|------|
| Video | `/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4` |
| Events | `10.27scasual_chain/data/交付_out/10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语.json` |
| G1 dir | `/data2/lpy1/_story_va_outputs/v2/cross_match_g1/A_uae_oman/` |
| Out | `/data2/lpy1/_story_va_outputs/v2/cross_match_g2/A_uae_oman/` |

No causal/gold/Croatia cache. Strips from G1 `reinfer_A_original` provenance only.

## Selected arc (from G1)

| Role | Board | score_confirmation_sec (≠ action time) |
|------|-------|------------------------------------------|
| opening_deficit | →0:1 | 1410.43 |
| equalizer | →1:1 | 6535.62 |
| go_ahead | →2:1 | 6957.12 |

Protagonist: **left / 阿联酋**

## Watchable primary clips (continuous source, no stitch)

| Role | Primary candidate | Source PTS | Path |
|------|-------------------|------------|------|
| opening_deficit | late_third | 1373.43–1413.43 | `/data2/lpy1/_story_va_outputs/v2/cross_match_g2/A_uae_oman/roles/opening_deficit/clips/opening_deficit_late_third_clip_source_continuous.mp4` |
| equalizer | late_third | 6498.62–6538.62 | `.../roles/equalizer/clips/equalizer_late_third_clip_source_continuous.mp4` |
| go_ahead | late_third | 6920.12–6960.12 | `.../roles/go_ahead/clips/go_ahead_late_third_clip_source_continuous.mp4` |

Each role also has strip-window + ffmpeg scene-change alternates (7 candidates/role; **21** watchable clips total). Frames + SHA256 under each `roles/<role>/frames/`.

## Verification status

| Field | Value |
|-------|-------|
| `video_semantic_verification.json` | `NOT_VERIFIED` |
| n_video_verified | **0** |
| human_review | `pending_human_video_review` for all 3 roles |
| STOP | User must watch clips before any verified upgrade |

Artifacts: `preflight_identity.json`, `search_plan.json`, `candidate_evidence_index.json`, `live_replay_audit.json`, `gate_decision.json`, `cli_report.json`.
