# R4/R5.2 original Story Agent Critic adapter preflight

- Code: `482e083` (`research/sportscausal-template-generalization`)
- Frozen R4/R5.1: `dbc65aa`
- Route: **original** P1/P2/P3 + Outer Loop + Verifier **byte-identical** in staged overlay; only isolated `story_e2e_agent.py` / `story_paid_eval.py` hooks + `r3_critic_adapter.py`
- Explicitly **not executed**: cf397a7 single-layer loop; no full agent/Goal-Recovery execution beyond structural Critic + `search_window_for_issue`
- Zero-cost: http_calls=0; no video decode/render; no R1–R3/history rerun; original `11.20sstory_chain/algo` git-clean

## Commands

```bash
cd research/sportscausal
python -m unittest -v test_r3_critic_adapter
# -> 7/7 OK

python stage_r3_critic_adapter.py \
  --algo-dir ../../11.20sstory_chain/algo \
  --out-dir /tmp/sportscausal_r3_critic_overlay_20261126

A_EVENTS=/data2/lpy1/_story_va_outputs/v3/plan2/full_e2e_A_strict_lin_20261108_095704/01_to_04_fresh_v3r/01_enrich/events_enriched.json
B_EVENTS=/data2/lpy1/_story_va_outputs/v3/plan2/full_e2e_B_strict_lin_20261108_095704/01_to_04_fresh_v3r/01_enrich/events_enriched.json
A_EV=artifacts/stage1_2_evidence_preflight_20261125/A_uae_oman/keeper_rescue/evidence.json
B_EV=artifacts/stage1_2_evidence_preflight_20261125/B_osasuna_celta/keeper_rescue/evidence.json
ALGO=/tmp/sportscausal_r3_critic_overlay_20261126/algo

python r3_critic_preflight.py \
  --story-dir artifacts/v3r_general_r3_preflight/A/comeback__1 \
  --evidence "$A_EV" --events "$A_EVENTS" --algo-dir "$ALGO" --allow-dev \
  --out-dir artifacts/v3r_critic_adapter_preflight/A_comeback
# A/keeper_rescue__2 -> A_keeper_rescue
# A/turnover_to_goal__1 -> A_turnover_to_goal
# B/equalization__1 -> B_equalization with B_EV + B_EVENTS
```

Evidence/events paths and sha256 match frozen dbc65aa REPORT.

## Input hashes (sha256)

| input | sha256 |
|---|---|
| `A_evidence` | `9322933a9c3ef15a990c9377ed498e97b73cb20350bbfe279114bf2f3b4043fc` |
| `B_evidence` | `a673769fe1b81f93a34f9c987302af49f8988cbf02c429ad97b1317bf7b33292` |
| `A_events` | `33958b106f3daddd8830e8735f7583527b3aa3f39ca4b6a805b6b3cfe0fb0299` |
| `B_events` | `c47015ccc7009c1a5869174709ce76e73454a6c6fa4b34bc3a34cd8812e19b6e` |
| `A_comeback_story` | `24ee0c469c950a95d5009f9326f391a72ac48cb6e99e77533bb67689098b47b4` |
| `A_keeper_story` | `9742e9395c835d478879480bc93bf11e1bece9ab2420b2696dbdd3532977251a` |
| `A_turnover_story` | `8a026218d409eceb694a6a839d4440c3d0626a4bfd050cefbec8423699493c23` |
| `B_eq_story` | `f072887bb676893a4359e1e2180d4ebf91e58393af62f4cb18e689b5f0072431` |

## Unit tests

`test_r3_critic_adapter`: **7/7 OK**. `test_general_story_agent` / cf397a7 not run.

## Overlay integrity

See `overlay_manifest.json`.

- `original_tree_unchanged`: **true** (repo algo unmodified)
- P1–P3 / Outer / Verifier / Timeline staged blobs **identical** to original:
  - `story_first_search.py`, `story_first_hypotheses.py`, `story_first_revision.py`, `story_first_video_review.py`, `story_first_p3.py`, `story_first_outer.py`, `story_video_verifier.py`, `dual_video_vision_verifier.py`, `story_timeline.py`
- Overlay-only patches: `story_e2e_agent.py`, `story_paid_eval.py` (+ added `r3_critic_adapter.py`)
- AST-changed paid-eval functions: `run_vlm_story_critic`, `run_llm_revision_planner` only
- Full overlay source copy **not** committed (tmp only); manifest committed

## Acceptance audits (actual)

### P1 9000-char template context

| story | n_pairs | fixed P1 request | `a_story_template_context` at prefix | ctx survives cap |
|---|---:|---|---|---|
| A comeback | 2 | yes (`fixed_p1_generator_request.json`) | yes | **true** |
| A keeper | 5 | yes | yes | **true** |
| A turnover | 1 | yes | yes | **true** |
| B equalization | 0 | n/a (no adjacent anchors) | `_text(plan,9000)` prefix validated; len=6852 | **true** |

Each A request `frozen_story_plan` length=9000 and starts with `{"a_story_template_context": ...}` equal to plan field (goal/subjects/teams/subtype intact).

### A keeper — unrelated goal_coverage excluded

- Original Critic emitted 3 whole-match goal issues: `goal_coverage_00_to_01`, `01_to_11`, `11_to_21`
- Scoped diagnosis **excluded all three** (`score_transition_outside_story_goal`)
- Scoped `goal_coverage` count: **0**; protected required segments: **6** (`seg:1`..`seg:6`)
- Planner fixture: drop of `seg:1` rewritten to **keep** via original `_protect_filter`

### A turnover — 5 segments + path protection

- Protected story segments: **5** (`seg:1`..`seg:5`) including relation/path context
- Original emitted `goal_coverage_00_to_01` / `01_to_11` → both excluded as outside story goal
- Story goal target retained in audit: outcome `1:1→2:1` (already covered by `seg:5`; **no** native missing goal_coverage issue for that transition)
- Planner fixture protects `seg:1` (keep)

### B equalization — target transitions + observe:5 + native search

- `missing_evidence` retains **score:2** + **observe:5** (`search_interval` [2480.82, 2675.82])
- Goal targets scoped to **0:0→0:1** and **0:1→1:1** only
- Excluded unrelated: `goal_coverage_11_to_21`, `21_to_22`, `22_to_23` + `insufficient_media_segments` (`known_partial_r3_story_not_rebuild_request`)
- **Native matching issue present**: `goal_coverage_01_to_11`
- Original `search_window_for_issue` returned:
  - kind=`missing_goal_action_evidence_search`
  - **lo=2488.6, hi=2660.32**
  - score_confirmation_sec=2660.82
  - auto_insert_authorized=false
  - bound `r3_goal_target.task_id=observe:5`

### A comeback — original diagnostics retained

- Scoped issues **identical** to original issue_id list (integrity + transition jumps)
- Coverage roles retained: opponent_opening / equalizer / go_ahead (+ buildup)
- No unrelated goal_coverage fabrication; `missing_goal_tasks_without_native_issue=[]`
- Goal targets remain score:1/2/3 transitions from R3 bindings

### File-missing probes (preflight expected)

All stories retain `missing_initial_story_mp4` / `missing_source_video_ref` because video path is null in this zero-HTTP structural preflight — **not** reported as visual defects.

## Story artifact inventory

Per story under `artifacts/v3r_critic_adapter_preflight/<name>/`:

- `story_plan.json`, `candidate_edl.json`
- `original_critic_diagnosis.json`, `scoped_critic_diagnosis.json`, `planner_diagnosis.json`
- `report.json`
- `fixed_p1_generator_request.json` (A stories only)

Root: `unittest.txt`, `overlay_manifest.json`, `PACK_SUMMARY.json`, `REPORT.md`

## Non-claims

No quality / FIRST_LIVE / release authorization. No decode/render. Original Goal Recovery / P2/P3 / outer loop **not** fully executed on adapted seeds in this stage (structural Critic + search window only).
