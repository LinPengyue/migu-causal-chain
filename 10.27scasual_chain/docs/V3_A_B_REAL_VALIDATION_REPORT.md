# V3 Plan-2 — Real A/B Adaptation Validation Report

**Branch:** `story-va-v3-plan2-dev` → push target `origin/story-va-v3-plan2`  
**Base commit:** `42c4826124d78707a48cb95bed1f9ac4aebb4a8f`  
**Worktree:** `/data2/lpy1/worktrees/migu-story-va-v3-plan2` (isolated; V1/V2 worktrees untouched)  
**Canonical outputs:** `/data2/lpy1/_story_va_outputs/v3/plan2/{A_uae_oman_run02,B_osasuna_celta_run02}/`  
**API=0 · render_ready=false · n_video_verified=0 · no gold/causal/8.31 retrain**

## 1. Inputs (verified on disk)

| Match | Events JSON | SHA256 | Video | SHA256 (G1/V3) | Frozen strips | SHA256 | n_chains |
|-------|-------------|--------|-------|----------------|---------------|--------|----------|
| A UAE–Oman | `.../交付_out/10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语.json` | `ddae99b2…779e` | `/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4` | `a66147f7…da9c` | `.../cross_match_g1/A_uae_oman/strip_reinfer/strip_A_original.json` | `7e120576…3b6e` | **79** |
| B Osasuna–Celta | `.../交付_out/10月27日_25-26赛季西甲第10轮_奥萨苏纳VS塞尔塔_国语.json` | `e75c2ad5…5bb2` | `/mnt/data4/migu/10月27日 25-26赛季西甲第10轮 奥萨苏纳VS塞尔塔 国语.mp4` | `0d422f60…bfaa` | `.../B_osasuna_celta/strip_reinfer/strip_A_original.json` | `04b03cff…e2dd` | **65** |

Strip mode: `reinfer_A_original`. Forbidden gold/causal paths rejected by V3 guards.

## 2. Tests

```bash
PYTHONPATH=10.27scasual_chain/algo python3 -m unittest story_video_agent_v3.test_pipeline -v
```

**7 OK** (6 original + `test_hydrate_events_from_source_ids_when_sequence_empty`).  
Failures were fixed **only** in `story_video_agent_v3/` (no V1/V2 edits).

## 3. Bug found & V3 fix (run01 → run02)

### Symptom
Real A/B **run01** completed with `structure_ok=true` but **`n_buildup_candidates=0`**.  
Frozen `strip_A_original.json` chains carry `event_ids` but **empty embedded `events`**, so V2 `adapt_strip_bundle` yields `event_sequence=[]`. V3 `to_predicted_causal` previously copied only `event_sequence` → predicted causal had **zero event rows** → buildup filter had nothing to match against raw LIVE evidence.

### Root cause class
**Field adaptation / projection gap**, not planner “score-only storytelling” by design alone, and not missing 8.31 recall (79/65 present).

### Fix (V3-only)
- Hydrate predicted causal event rows from `source_event_ids` ∩ raw events (`mapping_status=hydrated_from_raw_event_ids`).
- Report `n_chains_hydrated_from_raw_ids` / empty-event counts.
- Evidence tasks: opening `score_before` from score path; keep `media_in/out/goal_action_sec=null`.
- Emit `buildup_candidates.json`; warn when buildup is zero even if graph OK.
- Unit test covers empty-sequence hydration → LIVE buildup.

**Not done:** inventing `confidence` (frozen strips have no `prob_top1` → **0/79 and 0/65 confidence fields**; reported honestly).

## 4. Real A/B results (run02)

| Check | A | B |
|-------|---|---|
| n_predictions / n_dropped | **79 / 0** | **65 / 0** |
| hydrated chains / empty events | 79 / 0 | 65 / 0 |
| protagonist | **left / 阿联酋** | **right / 塞尔塔维戈** |
| arc scores | **0:1→1:1→2:1** | **2:1→2:2→2:3** (last deficit; not earlier left comeback) |
| buildup candidates | **5** (蓄力) | **5** (蓄力) |
| story_graph_structure_ok | true | true |
| critical goal tasks | 3 unresolved | 3 unresolved |
| goal placeholders media/action | all null | all null |
| score_confirmation_sec only | 1410.43 / 6535.62 / 6957.12 | 3199.66 / 5712.01 / 6881.94 |
| fabricated Goal / human causal | **0** | **0** |
| n_video_verified / render_ready | 0 / false | 0 / false |

### Predicted-chain field integrity
- `event_ids`, `t0_ms/t1_ms`, `prediction_source=causal_chain6_predicted`, `verification_status=unverified`, `goal_action_sec=null` present.
- A: 1470 hydrated event rows across 79 chains; B: 1262 / 65.
- **Confidence missing** on all chains (upstream strip dump limitation).

### Does V1 use predicted strips (not score-only)?
- **Yes for editorial 蓄力:** 5 LIVE-matched predicted-strip events enter `story_view` / plan `buildup_action` segments.
- **Deliberately not** feeding predicted Goal chains into V1 `merge_causal_live_goals` (no action-time truth).
- Beats `铺垫/转折/高潮/收尾` remain empty lists in recognition — goals stay unresolved placeholders; scoreboard anchors exist without pretending goal media.

### Critical goal evidence gaps (both matches)
Each of `opening_deficit` / `equalizer` / `go_ahead`:
- Needs: first LIVE continuous clip, observed shot+net, attacking team, not replay, source PTS, identity-bound media.
- Status: **unresolved**; no paid VLM; gate smoke with empty/fake status packs → `blocked_missing_goal_evidence`, verified=0.

### Structure vs edit completeness
| Dimension | Verdict |
|-----------|---------|
| Arc / protagonist / 79·65 conversion | **PASS** |
| Graph / EDL placeholder honesty | **PASS** |
| Predicted-strip buildup coverage | **PASS after fix** (5/5 sampled; not full narrative richness) |
| Video-grounded story / cuttable goals | **FAIL / unresolved** (expected at this stage) |

## 5. V1 / V2 / 8.31 zero-modification check

`git diff` on this worktree touches **only**:
- `algo/story_video_agent_v3/pipeline.py`
- `algo/story_video_agent_v3/test_pipeline.py`
- this report (+ prior V3 docs on branch)

No edits under `story_video_agent/` (V1/V2), `8.31causal_chain`, or legacy output folders. V1 planner / V2 gate imported read-only.

## 6. GO / STOP — next step

**GO for targeted V2-style critical goal evidence (3 slots/match only)** — structure + evidence-task interface are ready; do **not** start unbounded G2.4 search.

**STOP conditions still in force:**
- Do not set `render_ready=true` or claim verified without contiguous LIVE shot→net evidence + identity bind.
- Do not hardcode A/B PTS or inject gold/causal.
- Confidence remains absent until upstream strip dumps expose scores (optional later hygiene, not a blocker for evidence).

## 7. Commands reproduced

See `STORY_VA_V3_PLAN2_IMPLEMENTATION.md` A/B CLIs with `--out-dir .../run02`. Gate smoke exercised via `story_video_agent_v3.gate.review_evidence` on empty/fake packs against run02 dirs.
