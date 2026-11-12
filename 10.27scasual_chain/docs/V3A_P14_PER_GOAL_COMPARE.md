# P14 HUMAN_ATOM_ENRICHED_DEV E2E — per-goal compare (NOT formal benchmark)

- code: `baa8d59a9f021186a44b007a7800a40f5a11689f`
- out: `/tmp/lpy1_p14_human_atom_dev_e2e_20261112`
- mode: **HUMAN_ATOM_ENRICHED_DEV** (dev/regression only)
- enrich: injected Goals live=3 replay=25
- story_mp4 duration=94.877000s path=`/tmp/lpy1_p14_human_atom_dev_e2e_20261112/run/01_to_04_fresh_v3r/04_phase5/story_clean.mp4`
- first-live: all key goals **UNRESOLVED** (annotation LIVE ≠ video verified)

| role | cur t | closed_loop t | Δcl | full_e2e t | Δfe | in EDL | replay? | first_live |
|---|---:|---:|---:|---:|---:|---|---|---|
| opponent_opening_goal_action | 1337.123 | 1337.123 | 0.0 | 1337.123 | 0.0 | True | False | UNRESOLVED |
| equalizer_goal_action | 6448.924 | 6449.644 | -0.72 | 6448.924 | 0.0 | True | False | UNRESOLVED |
| go_ahead_goal_action | 6841.456 | 6843.088 | -1.632 | 6841.456 | 0.0 | True | False | UNRESOLVED |

## Acceptance

- `three_key_goals_in_candidate_edl`: **True**
- `complete_playable_story_mp4`: **True**
- `no_known_replay_in_goal_action_roles`: **True**
- `unverified_first_live_marked_UNRESOLVED`: **True**
- `per_goal_compare_report_written`: **True**
- `story_quality_improved_claimed`: **False**
- `formal_benchmark_claimed`: **False**
