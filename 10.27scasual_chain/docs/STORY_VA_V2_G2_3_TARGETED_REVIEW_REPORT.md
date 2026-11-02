# STORY_VA_V2 G2.3 — Targeted First-Live Review Report

**HEAD (this delivery):** see git after push. Base task: `STORY_VA_V2_G2_3_TARGETED_SEMANTIC_REVIEW_CURSOR_TASK.md` @ `394176f`.  
**API=0 · n_video_verified=0 · agent_auto_verified=0 · render_ready=false · G1 unchanged.**

## 1. A go_ahead `event_000661` @ 6774.49 — primary judgment

| Field | Value |
|-------|-------|
| G2.2 window | **6767.67–6778.15** (clip SHA `a578bff5…`, dur≈10.50s, 1920×1080) |
| G2.2 `net_sec≈6778.49` | **Mislabel** — was `shot+4` search hint, **past** `media_out` |
| Annotated REPLAY start | **6781.53** (`event_000662` media_start; graphic stinger visible ~6781) |
| Extended safe review | **6767.67–6781.48** (stops before REPLAY; original window not overwritten) |

**Frame audit (source PTS / match clock):**
- ~6767.67 / 81:15 — LIVE free-kick/setup, scoreboard **UAE 1–1 OMA**
- ~6772–6775 — LIVE chance; ball toward Oman goal; still **1–1**
- ~6777–6781 — cut to Oman #15 hands-on-head reaction; scoreboard **still 1–1**; then AFC graphic transition
- **No clear continuous ball-in-net** in original or extended-pre-replay window

**Verdict:** `SHOT_ONLY_NET_UNRESOLVED`.  
**Not** `human_visual_review_supported_candidate`.  
**Not** the verified 2:1 first-live goal (board confirm remains ~6957; window never shows 2:1). Ordinary LIVE chance / miss-or-unclear.

### Top-K `event_000655` @ 6703.22

Window 6699.03–6710.26 (~80:06–80:15), scoreboard **1–1**, attacking sequence with shot attempt, **no clear net**. Also `SHOT_ONLY_NET_UNRESOLVED`. Do not promote by proximity to confirm.

**Retrieval implication:** event-LIVE Shot ranking alone is insufficient for go-ahead; need denser visual first-live localization (authorized VLM later) or human search nearer the real 2:1 action — **not** unbounded earlier-window thrash in this task.

## 2. Code fix — hypothesized net must not look like evidence

| Change | Detail |
|--------|--------|
| `annotate_shot_only_evidence()` | Emits `hypothesized_result_sec` / `search_end_hint_sec`; **`net_sec=null`** unless `observed_net`; `evidence_status=SHOT_ONLY_NET_UNRESOLVED`; `claims_continuous_live=false` |
| Proposal builder | Stops writing `shot+4` into `net_sec` |
| `v2_video_evidence_gate` | Rejects hyp-as-net, shot-only upgrades, net-after-replay, wrong-team/ordinary-shot, B-style replay |
| On-disk G2.2 A go_ahead JSON | Append-only demotion of historical `net_sec` hyp (server outputs) |

## 3. Negative tests

```bash
PYTHONPATH=10.27scasual_chain/algo python3 -m unittest \
  story_video_agent.test_v2_g2_3_net_hypothesis_guards \
  story_video_agent.test_v2_g2_video_evidence_gate -q
```

**16 OK** (7 new G2.3 + 9 prior gate). Covers: hyp past clip end; LIVE shot only; net after replay; other-camera stitch; wrong team / ordinary shot; B post-score replay control.

## 4. Six Top-1 review pack (candidate_only / NOT_VERIFIED)

Server dir: `/data2/lpy1/_story_va_outputs/v2/cross_match_g2/g23_targeted_review/`  
ZIP: `.../six_g22_top1_review.zip` (~59 MB) — **upload this for human review**.

| Match / Role | Source PTS | Review 720p |
|---|---|---|
| A opening_deficit | 1315.08–1340.08 | `clips_720p/A_uae_oman__opening_deficit__g22_top1_review720p.mp4` |
| A equalizer | 6472.96–6497.96 | `...__equalizer__...` |
| A go_ahead | 6767.67–6778.15 | `...__go_ahead__...` (+ focus clips below) |
| B opening_deficit | 3128.32–3153.32 | `B_osasuna_celta__opening_deficit__...` |
| B equalizer | 5630.64–5655.64 | `...__equalizer__...` |
| B go_ahead | 6800.24–6825.24 | `...__go_ahead__...` |

Manifest fields: `observed_shot/net/first_live=review_pending` (no pre-filled PASS). B old `late_third` / A celebration late_third remain **negative controls**, not new positives.

### A go_ahead focus paths

- `/data2/lpy1/_story_va_outputs/v2/cross_match_g2/g23_targeted_review/clips_review/A_go_ahead_000661_review.mp4`
- `.../A_go_ahead_000661_extended_review.mp4` (to 6781.48, pre-REPLAY)
- `.../A_go_ahead_alternative_000655_review.mp4`
- Audit: `.../A_go_ahead_000661_audit.json`

## 5. STOP/GO

| Gate | Result |
|------|--------|
| A 000661 first-live goal? | **NO** — shot-only / net unresolved |
| Promote 000655? | **NO** |
| B verified? | **NO** (pack only) |
| Need user ZIP upload? | **YES** — `six_g22_top1_review.zip` |
| Need paid VLM next? | Likely for true 2:1 first-live; **not** run here |

Large MP4s stay on server (not git). Text report + code committed/pushed.
