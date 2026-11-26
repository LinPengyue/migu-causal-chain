# R4/R5.3c — A keeper_rescue:2 real end-to-end (main=3, outer=3)

- Code: `5bc5922` (`research/sportscausal-template-generalization`)
- Inputs: same frozen R4/R5.2 critic pack + Stage1.2 events/evidence as 3/3b
- Prepared V0: `artifacts/v3r_original_agent_A_keeper_rescue_20261126_r4r5_3` (sha `338e8424…c4ff91`) — **not re-rendered**
- Fresh P1 (no reuse of 3b hypothesis cache): `reuse_prior_story_first_hypotheses=false`
- Confirmed: `max_rounds=3`, `phase8_paid_multi_round=true`, `story_first_outer_rounds=3`
- Algo / P1–P3 / Outer / Verifier **unchanged**; single run; no auto-retry

## Command

```bash
source /home/lpy1/.config/migu-secrets/paratera.env
export STORY_API_ENABLE=1
export STORY_FIRST_LLM_MODEL=DeepSeek-V4.1-Flash

python run_r3_original_agent.py \
  --pack artifacts/v3r_critic_adapter_preflight/A_keeper_rescue \
  --evidence "$A_EV" --events "$A_EVENTS" \
  --match-json "$A_ORIGINAL_MATCH_JSON" --source "$A_ORIGINAL_MP4" \
  --source-manifest "$A_SOURCE_MANIFEST" \
  --original-algo ../../11.20sstory_chain/algo --allow-dev \
  --prepared-dir artifacts/v3r_original_agent_A_keeper_rescue_20261126_r4r5_3 \
  --out-dir artifacts/v3r_original_agent_A_keeper_rescue_20261126_r4r5_3c \
  --main-rounds 3 --outer-rounds 3 \
  --enable-real-api --approve-budget \
  --max-calls 17 --max-cost-usd 0.0803
```

Provenance records: `requested_main_rounds=3`, `phase8_paid_multi_round=true`.

## Main loop (actual 3 rounds)

| round | decision | story_first_trial | APPLIED | edl_changed | candidate_rendered |
|---:|---|---|---|---|---|
| 1 | UNRESOLVED | NEEDS_REVISION | False | False | False |
| 2 | UNRESOLVED | NEEDS_REVISION | False | False | False |
| 3 | REVISE | READY_FOR_TRIAL | True | True | True |

### P2 feedback → replan (native)

1. **Round1** select `interval_01:H5` → P2 `NEEDS_REVISION` (`event_000397` CONTRADICTED as replay angle) → planner `UNRESOLVED`
2. **Round2** replan to `interval_01:H2` → P2 `NEEDS_REVISION` (windows REPLAY_CONFIRMED on `000340`/`000367`) → planner `UNRESOLVED`
3. **Round3** replan to `interval_01:H1` (corners/free-kick chain) → P2 **`READY_FOR_TRIAL`** → EDL changed + candidate rendered (research preview)

Initial P1: model **`DeepSeek-V4.1-Flash`**, **19** fresh proposals (interval_03 `NO_VALID_HYPOTHESES`).

## Outer loop (attempted 3)

| version | status | duration_s | mp4 sha prefix | file |
|---|---|---:|---|---|
| v0 | V3_R | 70.752 | `338e842499cb2d60…` | `story_clean.mp4` |
| v1 | ACCEPTED_PREVIEW | 134.885 | `2c1e022caae646ed…` | `story_clean.mp4` |
| v2 | P1_BUDGET_EXHAUSTED | 134.885 | `2c1e022caae646ed…` | `story_clean.mp4` |
| v3 | ACCEPTED_PREVIEW | 150.93 | `916f59830dacd912…` | `story_clean.mp4` |

- Outer round2: **`P1_BUDGET_EXHAUSTED`** (0 new proposals; kept v1 mp4)
- Outer round3: new P1 (16 proposals) + trial insert `event_000397` window [3313.77, 3329.77] → **`ACCEPTED_PREVIEW`**
- `accepted_preview_changes=2` (research selected previews only)

Paths (server):
- v0: `.../01_initial_story/story_clean.mp4`
- v1/v2: `.../02_round_03/candidate_render/story_clean.mp4`
- v3: `.../story_first_outer/round_03/trial_render/story_clean.mp4`
- EDLs: `story_first_outer/v{0,1,2,3}_edl.json`

## P3 local optimization

Executed in outer round3:

- `stop_reason=API_BUDGET`
- `local_trims=0` / `completed_edits=0`
- `preview_accepted=true` (still `preview_only`, `release_authorized=false`)
- Caption call present under `story_first_outer/round_03/p3/round_01/`

## API / cost

| metric | value |
|---|---:|
| http_calls | **17** / 17 |
| est_cost_usd | **0.051478** / 0.0803 |

By role:

| role | http | est_cost |
|---|---:|---:|
| revision_planner | 2 | 0.005721 |
| story_first_generator | 9 | 0.025623 |
| story_first_p35_planner | 2 | 0.004561 |
| story_first_p3_caption | 1 | 0.005448 |
| vision | 3 | 0.010126 |

## Delivery / non-claims

- Native delivery decision `REVISE` but status **BLOCKED** (`final_edl_missing_goal_anchors`)
- Formal `release_authorized=false`
- **`ACCEPTED_PREVIEW` ≠ quality verified / FIRST_LIVE / release**
- Phase8 best remains research-unverified baseline for formal promotion gates

## Artifacts

JSON/audit/model responses under `artifacts/v3r_original_agent_A_keeper_rescue_20261126_r4r5_3c/` (MP4s on disk only, gitignored). See `story_e2e_audit.json`, `story_first_outer_comparison.json`, per-round `story_first_trial.json`, P3 `p3_revision.json`.
