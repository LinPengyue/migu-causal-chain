# V3-A zero-HTTP raw MP4+events fresh V3-R → V3-A — first run

Branch: `story-va-v3a-critic-verifier-increment-20261113` @ `ec0cc59`  
Script: `docs/run_v3a_raw_e2e_zero_http_20261113.sh`  
Out: `/tmp/lpy1_v3a_cv_raw_e2e_20261113_first_run/` (new dir; no overwrite)  
Docs mirror: `docs/cv_raw_e2e_20261113_first_run/`

## Verdict (not a quality PASS)

**Main-chain localization run completed.** Exit code **1** / delivery **BLOCKED**.  
Goal: locate where the full raw pipeline fails — **not** to claim story repair.

| Gate | Result |
| --- | --- |
| Input SHA (MP4 / events) | matched frozen `a66147f7…` / `ddae99b2…` |
| Contract | `RAW_EVENTS_ONLY`; no phase5 reuse / baseline EDL / atoms |
| Fresh V3-R | ran (`01_to_04_fresh_v3r/`); 8-seg EDL + ~72.8s MP4 |
| HTTP / cost | **0 / $0** |
| Historical BEST / prior B1 trees | fingerprints **unchanged** |
| Release / promote | false / `STOP_NO_ACTION` |

## Critical finding: fresh V3-R == historical broken B baseline

Fresh Phase5 `candidate_edl.json` SHA256 = `4afc619b…` — **identical** to Nov-12 historical B 8-seg wrong EDL.  
`story_clean.mp4` SHA256 = `f07b971f…` — **identical** to that baseline (~72.818s).

Active story roles again:

1. opponent opening goal action  
2. deficit scoreboard  
3. buildup  
4. **equalizer scoreboard only** (no equalizer goal action)  
5. go-ahead goal action + scoreboard  

Missing equalizer action corresponds to unresolved recovery id `goalcand_03_01_to_11`.  
Stage validity blocking error: `03_score_confirmed_goal_action_missing`.  
`story_goal_actions_present=false` (only 2 of 3 score-confirmed goals recovered into action).

This confirms: **do not treat B1 historical EDL as a special case** — raw V3-R regenerates the same gap.

## V3-A loop (zero-HTTP, no human preview)

| Step | Result |
| --- | --- |
| Critic | 4 issues; **`goal_coverage_01_to_11`** `HYPOTHESIS_NEEDS_VIDEO`; `goal_video_critic_handoff=null` (no real VLM observation this run) |
| Strict goal repair | unchanged / UNRESOLVED (`NO_EXTERNAL_REVIEW`) |
| EDL mutation | none (`edl_diff.changed=false`); candidate still 8 segs |
| Candidate render | skipped |
| Verifier business layer | `NO_NEW_SOURCE_WINDOWS`; `first_live_verified=false`; `edit_authorized=false` |
| Phase8 | `STOP_NO_ACTION`, `promote=false` |
| Delivery | BLOCKED `unresolved_without_safe_candidate_preview` |

Live audit on the two present goal_action rows: both `FIRST_LIVE` **UNRESOLVED** (offline; not certified).

## Implication for next work

Primary defect is **upstream V3-R / goal recovery** (equalizer `01→11` action not located → 8-seg story without equalizer goal footage).  
Zero-HTTP Critic/Verifier increments correctly **did not** auto-insert or certify repair.  
Next decision (human): fix V3-R recovery/planning vs authorize paid video observation inside the existing loop — **without** masking via manual goal insert for this diagnostic track.

## Key paths

- Full audit: `/tmp/.../cv_raw_e2e_audit.json` and `docs/cv_raw_e2e_20261113_first_run/cv_raw_e2e_audit.json`
- Fresh EDL: `docs/cv_raw_e2e_20261113_first_run/fresh_v3r_candidate_edl.json`
- Initial MP4 (not in git): `/tmp/lpy1_v3a_cv_raw_e2e_20261113_first_run/01_initial_story/story_clean.mp4`
