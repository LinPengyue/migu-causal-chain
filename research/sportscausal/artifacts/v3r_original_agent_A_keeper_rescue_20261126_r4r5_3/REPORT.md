# R4/R5.3 original Story Agent real-video run — A keeper_rescue:2

- Code: `1ce808d` (`research/sportscausal-template-generalization`)
- Frozen R4/R5.2: `277620a` pack `artifacts/v3r_critic_adapter_preflight/A_keeper_rescue/`
- Entry: original `run_story_e2e` via `run_r3_original_agent.py`
- Overlay: R4/R5.2 staged hooks + metadata-only `data_tier` propagation; P1/P2/P3/Outer/Verifier/Timeline **byte-identical**
- Explicitly **not** executed: R1–R3 rebuild, R4/R5.1–5.2 rerun, cf397a7 single-loop
- Paid flags used in the **same** initial invocation (bounded approval in protocol): `--enable-real-api --approve-budget --outer-rounds 3 --max-calls 24 --max-cost-usd 0.10`

## Commands

```bash
cd research/sportscausal
source /home/lpy1/.config/migu-secrets/paratera.env   # keys not committed
export STORY_API_ENABLE=1

A_EVENTS=/data2/lpy1/_story_va_outputs/v3/plan2/full_e2e_A_strict_lin_20261108_095704/01_to_04_fresh_v3r/01_enrich/events_enriched.json
A_EV=artifacts/stage1_2_evidence_preflight_20261125/A_uae_oman/keeper_rescue/evidence.json
A_ORIGINAL_MP4='/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4'
A_ORIGINAL_MATCH_JSON='/data2/lpy1/worktrees/migu-story-va-v3-plan2/10.27scasual_chain/data/交付_out/10月12日_2025世预赛亚洲区_阿联酋VS阿曼_国语.json'
A_SOURCE_MANIFEST=artifacts/v3r_original_agent_inputs/A_uae_oman_source_manifest.json
NEW_RUN_DIR=artifacts/v3r_original_agent_A_keeper_rescue_20261126_r4r5_3

python run_r3_original_agent.py \
  --pack artifacts/v3r_critic_adapter_preflight/A_keeper_rescue \
  --evidence "$A_EV" --events "$A_EVENTS" \
  --match-json "$A_ORIGINAL_MATCH_JSON" --source "$A_ORIGINAL_MP4" \
  --source-manifest "$A_SOURCE_MANIFEST" \
  --original-algo ../../11.20sstory_chain/algo --allow-dev \
  --out-dir "$NEW_RUN_DIR" \
  --enable-real-api --approve-budget --outer-rounds 3 \
  --max-calls 24 --max-cost-usd 0.10
```

## Source identity (not filename/duration alone)

| field | value |
|---|---|
| video_id | `10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语` |
| trusted historical sha256 | `a66147f79609c8fbf831a8bd29de4c6d7f746b314b2b18a88ffb1fc5f319da9c` |
| provenance | `freeze_p2_closed_loop/inputs_hashes/INPUT_HASHES.json` key `A_video`; also unified_cli joe8b3h4/lnsr7429 `source_video.sha256.json` |
| local recompute | **match** trusted sha256; size 6113318593 |
| match JSON sha256 | `ddae99b21cbfcd1c75ddf620d957578e57c2c013d607ac893655c4d52b7e779e` |
| evidence/events | match frozen R4/R5.2 hashes (`9322933a…` / `33958b10…`) |

See `source_manifest.json` / `input_provenance.json`.

## Initial render

- Renderer: original `_render_edl` → `initial_render/story_clean.mp4`
- sha256: `338e842499cb2d60df0de42d68e2fa05b9e2948f7a8350a3baa30c62eac4ff91`
- duration: **70.752s** (EDL timeline aligned=true)
- render elapsed: 81.08s
- `first_live_verified=false`, `release_authorized=false`

## Main loop (max_rounds=1)

- Structural Critic (scoped): issues = ["large_source_jump_seg:1_to_seg:2", "large_source_jump_seg:4_to_seg:5", "large_source_jump_seg:5_to_seg:6"]
- Unrelated whole-match `goal_coverage_*` remain excluded (r3_scope_audit).
- Protected story segments: ['seg:1', 'seg:2', 'seg:3', 'seg:4', 'seg:5', 'seg:6']
- Planner HTTP: **1** call, model `DeepSeek-V4-Pro-0813`, decision **`UNRESOLVED`**, est_cost **0.00118035**
- Revision applied: **false**; candidate re-render: **false**
- Native delivery: **BLOCKED** (`unresolved_without_safe_candidate_preview`, `final_edl_missing_goal_anchors`); research preview only
- Formal `release_authorized`: **false**

## Story-First / Outer Loop — first failure (actual)

Requested `story_first_outer_rounds=3`. **No** `story_first_outer_comparison.json`.

All 5 prepared P1 intervals status=`MODEL_CONFIG_MISSING`, reason=`STORY_FIRST_LLM_MODEL_required_for_shared_gateway`.

- `proposal_count=0` (no valid hypotheses / responses)
- Generator request JSON files exist under `original_agent/story_first/interval_0{1..5}/` (prepared only)
- Outer versions **v1/v2/v3 research outer previews were not produced**
- Preserved seed video: **v0** only (`initial_render/story_clean.mp4`)
- Phase8 loop stopped: `STOP_NO_ACTION` / `no_executable_revision_or_valid_source`
- **No automatic rerun** (protocol: do not loosen limits or retry after partial failure)

Root cause: provider env (`paratera.env`) sets `STORY_LLM_MODEL` but not `STORY_FIRST_LLM_MODEL`, which the original Story-First shared-gateway path requires before any P1 HTTP.

## API / cost (actual)

| metric | value |
|---|---|
| http_calls | **1** |
| est_cost_usd | **0.00118** |
| max_calls / max_cost_usd caps | 24 / 0.10 |
| max_retries | 0 |
| roles used | revision_planner only (1) |
| P1/P2/P3 paid calls | 0 (P1 blocked by config; P2/P3 not reached for story-first proposals) |

## Versions present

| id | mp4 | notes |
|---|---|---|
| v0 | `initial_render/story_clean.mp4` (`338e842499cb2d60…`) | real initial render; 6 segs / ~70.75s |
| phase8 v1 | same mp4 path as initial | EDL unchanged; quality=`UNCERTAIN`; not a new render |
| outer v1/v2/v3 | **absent** | Story-First outer never started |

`ACCEPTED_PREVIEW` was **not** issued as a quality-verified delivery. Native delivery remains BLOCKED / research preview only.

## Artifact index (committed JSON; MP4s on disk only)

- `input_provenance.json`, `source_manifest.json`, `render_manifest.json`, `overlay_manifest.json`
- `story_plan.json`, `candidate_edl.json`, `report.json`, `PACK_SUMMARY.json`, `REPORT.md`
- `original_agent/story_e2e_audit.json`
- `original_agent/story_first/interval_*/generator_request.json` (+ prepared inputs)
- `original_agent/02_round_01/llm_revision_planner.json`, `story_diagnosis.json`, `revision_*`, `verifier_report.json`
- `original_agent/99_final/*` delivery/release gates
- On-disk only (gitignored): `**/*.mp4`, `overlay/algo/`, observe frames

## Non-claims

No FIRST_LIVE certification, no formal release, no narrative-quality improvement claim, no fabricated outer versions. Original algo tree in repo remains unmodified.
