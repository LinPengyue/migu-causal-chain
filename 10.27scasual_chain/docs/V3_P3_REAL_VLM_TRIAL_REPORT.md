# V3-P3 Real Remote VLM Trial Report — B opening_deficit

**Branch:** `story-va-v3-plan2`  
**Baseline:** `aa49753` (+ parser fix commit)  
**Budget:** user-approved; **this trial only** (no second real process)  
**Window:** B Osasuna–Celta `opening_deficit` **3132–3146s**  
**Model:** `Qwen3.6-Plus` (`video_rsi`, Thinking off)  
**Artifacts:** `/data2/lpy1/_story_va_outputs/v3/plan2/p3_b_opening_vlm_verify/real_trial_01/`  

| Flag | Value |
|------|-------|
| `observation_only` | **true** |
| `agent_auto_verified` | **false** |
| `gate_opened` | **false** |
| `render_ready` | **false** |

---

## Final verdict

### **`possible_first_live`**

找到合理 LIVE 候选动作区间，且 R2 声称可见射门/入网并给出 frame_id + PTS；但 **R1 明确否认直接可见 shot/net（认为是进球余波/庆祝）**，两轮冲突。在 `observation_only` 与既有广角人工审计（入网不清晰）约束下，**不能**升为 `visual_evidence_sufficient`，也不是整次 API 失败（HTTP 200×2）。

保持 unresolved / 不自动开 Gate。

---

## 1. Preflight (zero HTTP) then real run

Effective caps after overrides:

| Cap | Effective |
|-----|-----------|
| MAX_CALLS | 3 |
| MAX_COST_USD | 0.5 (estimate soft) |
| MAX_COMPLETION / VLM role | 2048 |
| profile | `video_rsi` → `max_tokens=2048`, `thinking={type:disabled}`, `stream=false` |

Inputs:

- Video: `/mnt/data4/migu/10月27日 25-26赛季西甲第10轮 奥萨苏纳VS塞尔塔 国语.mp4` (duration ≈7676s; match_id matches B run03 provenance)
- Continuous clip: `.../opening_deficit_score_unknown_core_3132_continuous_accurate.mp4` (reused)
- Score bounds: `.../p3_b_opening_localize/run/opening_deficit/score_bounds.json` (last 1-1 @3140 → first 2-1 @3144)

---

## 2. HTTP / token / cost (actual)

| Metric | Value |
|--------|-------|
| HTTP attempts | **2** / 3 (no retries; stopped under budget) |
| HTTP status | 200, 200 |
| `output_budget_exceeded` | false |
| Prompt tokens | 17084 + 25466 = **42550** |
| Completion tokens | 494 + 627 = **1121** (limit 2048) |
| Est. cost USD | **≈0.00706** (local estimate ≠ invoice) |
| Wall time (real) | ≈22.8s |

No third call. Process not relaunched.

---

## 3. Pipeline bug (fixed after trial; no re-call)

Both rounds returned **valid goal-verify JSON**, but the live pipeline marked `ok=false` with `failure_status=empty_evidence` because V2 `normalize_evidence` requires `observed_actions` / `story_relation`, which the goal-verify schema does not use.

**Fix (V3 only):** `normalize_goal_verify_response` — frame_id binding without `observed_actions`.  
**Offline reparse** of saved excerpts → `real_trial_01/offline_reparse.json` (**0 additional HTTP**).

---

## 4. Round-by-round VLM semantics (from raw + offline reparse)

### Round 1 — dense mid-window (8 frames, PTS ≈3133.06–3144.96)

| Field | VLM |
|-------|-----|
| `observed_shot` | **false** |
| `observed_net` | **false** |
| `live_or_replay` | live |
| `attacking_team_match` | true |
| `claims_continuous_live` | true |
| `uncertain` | `observed_shot`, `observed_net` |
| `confidence` | 0.95 |
| Cited frames | `f_0000_3133050` (~3133.06), `f_0001_3134750` (~3134.76), `f_0005_3141550` (~3141.56) |
| Notes (excerpt) | frames show **immediate aftermath**; celebration / scoreboard to 2-1; **shot & ball-over-line not directly visible** in these samples |

Tokens: prompt 17084 / completion 494 / est $0.00286

### Round 2 — adaptive densify early window (12 frames, PTS ≈3132.06–3141.76)

| Field | VLM |
|-------|-----|
| `observed_shot` | **true** |
| `observed_net` | **true** |
| `live_or_replay` | live |
| `attacking_team_match` | true |
| `claims_continuous_live` | true |
| `uncertain` | [] |
| `confidence` | 1.0 |
| Shot frame_ids | `f_0000_3132050` **PTS 3132.06**, `f_0001_3132932` **PTS 3132.94** |
| Net frame_ids | `f_0002_3133814` **PTS 3133.82**, `f_0003_3134695` **PTS 3134.70** |
| Side notes | Osasuna red; claims player #29 (A. Osambela) scores and celebrates |

Tokens: prompt 25466 / completion 627 / est $0.00420  
shot→net PTS order OK (3132.06 ≤ 3133.82). Continuous clip OK.

---

## 5. Answers to focus questions

| Question | Answer |
|----------|--------|
| Visible shot? Which frames? | **Conflict.** R1: no. R2: yes @ 3132.06 / 3132.94 (`f_0000_3132050`, `f_0001_3132932`). |
| Ball clearly over line on first LIVE? Which frame? | **Conflict.** R1: not visible. R2: claims yes @ 3133.82 / 3134.70. Not accepted as verified under observation_only + R1 denial. |
| Save / scramble / celebration misread as net? | **R1 effectively warns this risk** (aftermath/celebration). R2 may over-claim on wide angle. |
| Attacking side Osasuna? | Both rounds: **yes** (red / OSA 2-1). |
| Replay / discontinuity? | Both claim **live** + continuous; continuous accurate clip present; no event-replay flag in this short window. |
| Inference-only “must have scored”? | **R1 is observation-honest** (cannot see shot/net). **R2 asserts direct observation** with conf=1 — treat as **VLM claim**, not Gate-ready fact. |

---

## 6. Why not `visual_evidence_sufficient`

1. Round conflict (deny vs assert net)  
2. `observation_only=true` — no auto upgrade  
3. Prior P3 human dense audit: wide LIVE angle does not unambiguously show ball fully over line  
4. High VLM confidence alone is explicitly blocked  

Why not `vlm_inference_failed`: HTTP succeeded; structured semantics recovered offline; failure was **post-response normalization**, now fixed for future runs (without repeating this paid trial).

---

## 7. Freeze / non-goals

- No expansion to other five goals  
- No second real trial / budget reset  
- No V2 Gate / no render  
- V1/V2/8.31 untouched  

---

## 8. Code follow-up in this commit

- `normalize_goal_verify_response` + longer raw excerpts  
- Tests for goal JSON without `observed_actions`  
- This report + offline reparse artifact path documented
