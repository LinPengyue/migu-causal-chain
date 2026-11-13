# P14 atomic-enriched + latest V3-A — zero-HTTP integration regression

Branch: `story-va-v3a-p14-story-quality-20261113` @ `f39c987`  
Script: `docs/run_v3a_p14_cv_integration_20261113.sh`  
Out: `/tmp/lpy1_v3a_p14_cv_integration_20261113/` (new; no overwrite)  
Mode: `HUMAN_ATOM_ENRICHED_DEV` (not a raw-only benchmark)

## Focus checks

| Question | Result |
| --- | --- |
| Three goals retained? | **Yes** — `opponent_opening_goal_action`, `equalizer_goal_action`, `go_ahead_goal_action` (`three_goal_roles_present=true`; recovery `n_with_goal_action_sec=3`) |
| Latest V3-A actually ran? | **Yes** — `02_round_01` present; Critic diagnosis + Verifier report written; `agent_round_count=1` |
| New candidate revision? | **No** — `edl_diff.changed=false`; `revision_applied=false`; metrics `revise_proposed=0` / `edl_changed_rounds=0`; candidate render skipped |

## Pipeline summary

- Input SHA OK (MP4 `a66147f7…`, events `ddae99b2…`); causal atoms used (DEV).
- Fresh P14 V3-R: **9** segments; initial MP4 ~**94.877s** (`7764010f…`).
- Fresh EDL SHA `b38434b9…` **identical** to historical C clean-control Phase5 EDL (regenerated, not reused as input).
- HTTP / cost: **0 / $0**. Historical P14/raw/B1 trees fingerprints **unchanged**.
- CLI exit **1** / delivery **BLOCKED** (expected: no safe revise preview; first-live still UNRESOLVED×3). No release / no BEST promote.

### Critic / Verifier increment (log + JSON, beyond round count)

Script only counts rounds; deeper check:

- Critic: 3 non-goal issues (transition×2, thin tail); **no** `goal_coverage_*`; `goal_video_critic_handoff=null` (zero-HTTP, no VLM observation to bind).
- Verifier increment present in `verifier_report.json`: `business_first_live_review` schema `v3a_light_first_live_business_v1`, status **`NO_NEW_SOURCE_WINDOWS`**, `first_live_verified=false`, `edit_authorized=false`.
- Function names do not appear in stdout JSON dump (normal); evidence of wiring is the written `business_first_live_review` field.

## Implication

P14 atom path still produces the known **3-goal ~95s** initial story under current V3-A. Zero-paid loop runs but does **not** invent a quality revision. Ready baseline for **story-quality optimization** work on this track (not raw-only equalizer recovery).

## Artifacts

- `docs/p14_cv_integration_20261113/integration_check.json`
- Critic/verifier/revision slims + goal windows under same dir
- Full run: `/tmp/lpy1_v3a_p14_cv_integration_20261113/run/`
