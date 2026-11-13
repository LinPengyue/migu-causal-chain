# V3-A B1 human-assisted E2E (zero-paid) — 2026-11-13

Branch: `story-va-v3a-p17-native-broadcast-observer` @ `558d8a5`  
Runner: `python -m story_video_agent_v3.b1_human_assisted_e2e`  
Out: `/tmp/lpy1_v3a_b1_human_assisted_20261113/`  
Docs mirror: `docs/b1_human_assisted_20261113/`

## Preconditions

| Check | Result |
| --- | --- |
| `pytest tests/test_v3a_b1_human_assisted_e2e.py` | **3 passed** |
| B1 ↔ `StoryE2EInputs` kwargs | **OK_COMPAT** (`B1_used_missing=[]`) |
| Paid HTTP | `enable_real_api=False`, `skip_vlm=True`, `i_approve_budget=False`; env API keys unset for process |
| Gold causal chain as formal input | **not used** |
| Historical B BEST trees overwritten | **no** (`HISTORICAL_BEST_UNCHANGED True`) |

## Inputs reused (B historical)

- Wrong baseline EDL / plan / initial story: `/tmp/lpy1_v3a_blind_repair_B_historical_20261112/agent_input/04_phase5/`
- Events JSON: `.../agent_input/events.json` (also as `--match-json`)
- Source MP4: `/mnt/data4/migu/10月12日 2025世预赛亚洲区 阿联酋VS阿曼 国语.mp4` (`sha256=a66147f7…`)
- Stage3/Stage4 paths recorded in incomplete inventory (supporting references only)
- Human first-live attestation: `docs/V3A_EXPB_HUMAN_FIRST_LIVE_ATTESTATION.json` (copied as `HUMAN_ATTESTATION_NOT_FIRST_LIVE_PACK.json`)

**Attestation was not treated as a complete first-live evidence pack.** Goal-repair dir contains an explicit incomplete inventory JSON that does **not** claim to satisfy `validate_goal_video_review`.

## Missing fields for a legal source-bound repair pack

From `docs/b1_human_assisted_20261113/incomplete_goal_review_inventory.json`:

1. legal `first_live_evidence` pack with binding_valid frames + `manifest_digest` for the repair window
2. `broadcast_timeline_review.outcome=FIRST_LIVE_VERIFIED` with continuous `phase_evidence` ok
3. independent earlier same-action occurrence exclusion in phase proof
4. validated `continuous_source_clip_sha256` bound into a goal-review JSON accepted by `validate_goal_video_review`
5. `HUMAN_CONTINUOUS_VIDEO_REVIEW` or `REAL_VIDEO_MODEL_REVIEW` observation package with bound frame paths matching `first_live_evidence`
6. precise `media_in`/`media_out` human-locked cut boundaries (`precise_cut_boundaries_confirmed=false` on attestation)

Also required by contract (checklist in inventory): issue/score binding, source SHA match, clip window &lt;45s inside score bracket, redecode frame-byte match, shot/net cross-check ready, net PTS pre-confirmation bound.

## Actual run result

| Artifact | Result |
| --- | --- |
| Preflight | OK; `paid_http_authorized=false`; 2 review JSON files listed |
| `http_calls` / `est_cost_usd` | **0 / 0.0** |
| `goal_video_repair_decisions` | `changed=false`; issue `goal_coverage_01_to_11` → **UNRESOLVED** `missing_or_mismatched_issue_and_score_transition` (`review_provided=true`) |
| `revision_plan` | **UNRESOLVED** (hypothesis needs video; no auto insert) |
| `edl_diff` | `{"changed": false}`; candidate EDL sha equals baseline |
| `candidate_render` | **skipped** `edl_unchanged_reuse_working_parent` |
| Verifier | `candidate_accepted=false`, `retain_baseline=true`, evidence **INSUFFICIENT**, vision_backed false |
| Phase8 transition | **STOP_NO_ACTION** (`no_executable_revision_or_valid_source`); `promote=false` |
| Delivery | **BLOCKED** (`unresolved_without_safe_candidate_preview`); `release_authorized=false` |
| BEST in this run | stayed **v0**; no promote |
| Historical BEST trees | fingerprints identical before/after under `agent_run*`, `private_eval` |

## Blocker (closed-gate, expected)

Legal goal insert is blocked because the supplied review is an **incomplete inventory**, not a source-bound review that binds issue/score transition + first-live phase proof + semantic observation. Human attestation and Stage3/4 references alone do not open the repair gate. No forge / no gate relaxation / no paid API.

## Key paths

- Full log: `docs/b1_human_assisted_20261113/b1_full_run.txt` (+ `/tmp/.../b1_full_run.log`)
- Preflight / repair / diff / render / transition / gates / summary / fingerprints: `docs/b1_human_assisted_20261113/`
- Full agent tree (incl. frames/smoke render): `/tmp/lpy1_v3a_b1_human_assisted_20261113/agent_run/`
