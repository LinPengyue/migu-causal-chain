# STORY_VA_V2 G2.2 — First-Live Retrieval Report

**Decision:** G2.1 Top-1 `late_third` packages fail first-live gate (especially B `POST_SCORE_REPLAY`, A `go_ahead` missing action). G2.2 corrects **retrieval ranking** only. G1 arcs unchanged. `n_video_verified=0`, `render_ready=false`, API=0.

## Reused vs new

| Category | Mechanism |
|----------|-----------|
| **Reused (Croatia R2.5–R2.6)** | `locate_continuous_live_goal_window` (non-replay bridge + hard-stop on replay/transition); `audit_inferred_goal` **score_order_anomaly** reject (`result_after_score_confirmation`); event-annotated REPLAY overlap trim as R2.5 override source |
| **New generic (G2.2)** | Zero-API event broadcast timeline (`is_replay`/`broadcast_phase`); `classify_post_score_replay_risk` from G2.1 human pattern; reject LIVE Shot already carrying **score_after**; demote confirm-anchored `late_third`; rank earlier scene/strip + LIVE→REPLAY-trimmed shot windows; `NEEDS_EARLIER_SEARCH` blocks; append-only G2.1 judgments on existing `role_evidence.json` |
| **Not used** | Croatia fixed PTS; V1 human times; `*_causal`/gold; cross-match verify cache; paid VLM; `late_third` time-offset tweaks |

Code: `v2_g2_first_live_retrieval.py`, `v2_g2_first_live_retrieval_cli.py`.  
Freeze: A run first → `CODE_FREEZE_AFTER_A.json` → identical modules for B.

Outputs: `/data2/lpy1/_story_va_outputs/v2/cross_match_g2/g22_first_live/{A_uae_oman,B_osasuna_celta}/`  
Each role: `first_live_search.json`, `role_first_live_pack.json`, continuous MP4 + frames, `live_replay_audit.json`.

## Remaining-6 audit (why late_third was substituted)

G2.1 human Top-1 judgments appended (not overwritten) onto G2 `role_evidence.json`.

| Match / Role | G2.1 Top-1 | Reject reason (G2.2) | Remaining keep (examples) |
|---|---|---|---|
| A opening | `GOAL_VISUAL_PRESENT_FIRST_LIVE_UNRESOLVED` | confirm-anchored / late_third pattern demoted | scene_0/1, strip clip06/07 |
| A equalizer | `REPLAY_SUSPECTED_FIRST_LIVE_UNRESOLVED` | same + near-confirm strip62 | scene_0–2, strip61 |
| A go_ahead | `GOAL_ACTION_NOT_IN_WINDOW` | late_third celebration-only window | LIVE Shot @6774.49 (new), scenes, earlier strips |
| B opening/eq/go | `POST_SCORE_REPLAY` | board already new at late_third start | scenes/strips **ending before** late_third `media_in` |

## Top-1 / Top-K (first-live-oriented; still `unresolved`)

### A 阿联酋–阿曼

| Role | New Top-1 | Source PTS | Shot/Net hyp | Live/Replay audit | Hit? |
|------|-----------|------------|--------------|-------------------|------|
| opening_deficit | reuse `scene_1` | 1315.08–1340.08 | none | earlier than late_third; `NEEDS_EARLIER_SEARCH` | **Not verified** first-live |
| equalizer | reuse `scene_2` | 6472.96–6497.96 | none | earlier; `NEEDS_EARLIER_SEARCH` | **Not verified** |
| go_ahead | `first_live_shot_event_000661` | 6767.67–6778.15 | shot 6774.49 / net~6778.49 | LIVE Shot score=[1,1] before confirm 6957; REPLAY hard-stop ~6781; score-order OK | **Best A lead** — still `unresolved` (no semantic VLM) |

Top-K: go_ahead also ranks LIVE Shot `event_000655` @6703 and earlier scenes. Opening/equalizer Top-K = earlier scenes/strips + earlier-search blocks.

### B 奥萨苏纳–塞尔塔（负控制：原 Top-1 = POST_SCORE_REPLAY）

| Role | New Top-1 | Source PTS | Shot/Net hyp | Live/Replay audit | Hit? |
|------|-----------|------------|--------------|-------------------|------|
| opening_deficit | reuse `scene_2` | 3128.32–3153.32 | none | before late_third 3162.66 | **Not verified**; `NEEDS_EARLIER_SEARCH` |
| equalizer | reuse `scene_1` | 5630.64–5655.64 | none | before late_third 5675.01 | **Not verified** |
| go_ahead | reuse `scene_2` | 6800.24–6825.24 | none | before late_third 6844.94 | **Not verified** |

No pre-confirm LIVE Shot with `score!=after` in event log for B roles → cannot claim first-live goal action from events alone.

## Honest verdict

| Question | Answer |
|----------|--------|
| Did A/B **truly find** verified first-live goal clips? | **No.** All six remain `unresolved` / `n_video_verified=0`. |
| Did retrieval leave the failed G2.1 Top-1 pattern? | **Yes.** All six new Top-1 are **not** `late_third_near_confirm`. |
| Strongest automated lead | **A go_ahead** LIVE Shot window before REPLAY package and before board confirm. |
| B | Fail-closed: only earlier search windows; human/VLM still required. |
| G1 / render | Unchanged; `render_ready=false`; no long story render; no paid API. |

## Next review needs

1. Watch six G2.2 Top-1 continuous MP4s (paths in each `candidate_evidence_index.json`).
2. For A go_ahead: confirm shot→net continuity is first-live (not a prior chance).
3. For A opening/equalizer and all B: continue earlier search or authorized dense live/replay VLM; do **not** promote on scoreboard-only or post-score replay.
