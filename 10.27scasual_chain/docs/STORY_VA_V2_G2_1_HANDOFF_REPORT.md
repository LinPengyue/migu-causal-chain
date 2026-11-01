# STORY_VA_V2 G2.1 — Human Review Handoff Report

**Branch HEAD (at handoff):** see commit after this doc  
**G2 baseline:** `5ac591fb8269e85484b8a546fc1f1a6640ebecd0`  
**API:** 0 · **n_video_verified_goals:** 0 · **render_ready:** false  
**Verification statuses:** unchanged (`candidate_only` / unresolved / NOT_VERIFIED)

## Package directory

`/data2/lpy1/_story_va_outputs/v2/cross_match_g2/human_review_handoff/`

| Artifact | Path |
|----------|------|
| Six 720p review MP4s | `.../clips_720p/*__review720p.mp4` |
| Zip (6 clips + manifest + checklist + index) | `.../six_primary_review720p.zip` (~87 MB) |
| Manifest | `.../review_manifest.json` |
| Checklist | `.../REVIEW_CHECKLIST.md` |
| Index | `.../six_clips_review_index.md` |
| Nav compilation only | `.../review_compilation.mp4` (~77 MB; **not** continuity proof) |

Original G2 `*_late_third_clip_source_continuous.mp4` files were **not modified**.

## Six absolute paths (upload these)

1. `/data2/lpy1/_story_va_outputs/v2/cross_match_g2/human_review_handoff/clips_720p/A_uae_oman__opening_deficit__review720p.mp4` — PTS 1373.43–1413.43  
2. `/data2/lpy1/_story_va_outputs/v2/cross_match_g2/human_review_handoff/clips_720p/A_uae_oman__equalizer__review720p.mp4` — PTS 6498.62–6538.62  
3. `/data2/lpy1/_story_va_outputs/v2/cross_match_g2/human_review_handoff/clips_720p/A_uae_oman__go_ahead__review720p.mp4` — PTS 6920.12–6960.12  
4. `/data2/lpy1/_story_va_outputs/v2/cross_match_g2/human_review_handoff/clips_720p/B_osasuna_celta__opening_deficit__review720p.mp4` — PTS 3162.66–3202.66 (**arc 2:1**, not earliest 0:1)  
5. `/data2/lpy1/_story_va_outputs/v2/cross_match_g2/human_review_handoff/clips_720p/B_osasuna_celta__equalizer__review720p.mp4` — PTS 5675.01–5715.01  
6. `/data2/lpy1/_story_va_outputs/v2/cross_match_g2/human_review_handoff/clips_720p/B_osasuna_celta__go_ahead__review720p.mp4` — PTS 6844.94–6884.94  

**Preferred upload bundle:** `/data2/lpy1/_story_va_outputs/v2/cross_match_g2/human_review_handoff/six_primary_review720p.zip`

SHA256 for each review file and its G2 source clip are in `review_manifest.json` (`g2_source_clip_sha256`, `review_mp4_sha256`, source video/events hashes, continuity flags).

## Continuity

Each review720p is a continuous H.264/AAC reencode of **one** G2 late_third source clip (scale 720p + banner). No multi-window stitch, reorder, or frame synthesis. Single-file clips remain the evidence; compilation is navigation only.

## Not done (by design)

- No paid API / VLM  
- No verification_status upgrade  
- No formal story long-form render  
- Large MP4/zip not pushed to GitHub  
